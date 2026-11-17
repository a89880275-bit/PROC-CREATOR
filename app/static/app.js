const $=id=>document.getElementById(id);let s,existing=false,dirty=false,token='',services=[],conds=[];
let savingService=false;
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function status(t,error=false){$('status').textContent=t;$('status').className=error?'error':'';const inline=$('sql-status');if(inline&&!$('sql').hidden){inline.hidden=false;inline.textContent=t;inline.className=error?'error':'';}}
function apiError(detail){
 if(typeof detail==='string')return detail;
 if(!Array.isArray(detail))return '요청을 처리할 수 없습니다. 입력 내용을 확인하세요.';
 return detail.map(e=>{
  const path=e.loc||[];
  if(path.includes('service_id'))return '기본정보에서 올바른 서비스 ID를 입력하세요. 저장할 때 서비스 ID가 필요합니다.';
  if(path.includes('columns')&&e.type==='too_short')return '등록할 컬럼이 없습니다. 수동 컬럼을 입력하거나 Excel 미리보기의 등록 버튼을 사용하세요.';
  return '입력값을 확인하세요 ('+path.filter(x=>x!=='body').join(' → ')+').';
 }).join('\n');
}
async function api(path,method='GET',body){const r=await fetch('/api'+path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':token},body:body===undefined?undefined:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(apiError(d.detail));return d;}
function action(fn){return async()=>{try{await fn();}catch(e){status(e.message,true);}};}
function blank(){return {service_id:'',name:'',type:'select',description:'',table_name:'SAMPLE_TABLE',owner:'',table_alias:'',dictionary_revision:0,join_tables:[],builder_state:{},max_row_count:1000,template_id:'select',current_version:0,columns:[],variables:[],sql_blocks:[{block_type:'SELECT',generated_sql:'',final_sql:'',is_manual:false,error_policy:'stop'}]};}
function tab(id){if(id==='proc'&&s&&typeof renderProcControls==='function'){collect();renderProcControls();}if(id==='mapping'&&s&&typeof scheduleMappingAnalysis==='function')scheduleMappingAnalysis(0);if(id==='sql'&&s)collect();if(id==='sql'&&typeof refreshSQLTables==='function')refreshSQLTables().catch(e=>status(e.message,true));document.body.classList.toggle('sql-mode',id==='sql');document.body.classList.toggle('dictionary-mode',id==='dictionary');document.querySelectorAll('.tab').forEach(x=>x.hidden=x.id!==id);document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('active',x.dataset.tab===id));}
function collect(){if(typeof captureBuilder==='function')captureBuilder();for(const k of ['service_id','name','type','description','owner','table_name','table_alias'])s[k]=$(k).value;s.max_row_count=Number($('max_row_count').value);s.template_id=s.type;s.sql_blocks[0].final_sql=$('final_sql').value;s.sql_blocks[0].is_manual=s.sql_blocks[0].final_sql!==s.sql_blocks[0].generated_sql;return s;}
function render(){if(typeof invalidateMappingPlan==='function')invalidateMappingPlan();for(const k of ['service_id','name','type','description','owner','table_name','table_alias','max_row_count'])$(k).value=s[k]??'';$('service_id').disabled=existing;$('title').textContent=existing?`${s.service_id} · v${s.current_version}`:'새 서비스';$('generated_sql').value=s.sql_blocks[0].generated_sql;$('final_sql').value=s.sql_blocks[0].final_sql;$('operation').value=s.sql_blocks[0].block_type;columns();mappings();conditions();if(typeof restoreBuilder==='function')restoreBuilder();if(typeof renderJoinControls==='function')renderJoinControls();if(typeof renderProcControls==='function')renderProcControls();}
function input(value,cls,type='text'){return `<input class="${cls}" type="${type}" value="${esc(value)}">`;}
function columns(){$('column-rows').innerHTML=s.columns.map((c,i)=>`<tr data-i="${i}"><td>${input(c.name,'name')}</td><td>${input(c.db_type,'db_type')}</td><td>${input(c.length,'length','number')}</td><td>${input(c.precision??'','precision','number')}</td><td>${input(c.scale??'','scale','number')}</td><td>${input(c.date_format,'date_format')}</td><td><input class="primary_key" type="checkbox" ${c.primary_key?'checked':''}></td><td><input class="nullable" type="checkbox" ${c.nullable?'checked':''}></td><td>${input(c.comment,'comment')}</td><td><input class="use-in" type="checkbox" ${s.variables.some(v=>v.role==='IN'&&v.db_column===c.name)?'checked':''}></td><td><input class="use-out" type="checkbox" checked></td><td><button class="remove-col">삭제</button></td></tr>`).join('');}
$('column-rows').addEventListener('change',e=>{const tr=e.target.closest('tr'),c=s.columns[+tr.dataset.i],k=e.target.className;if(k.startsWith('use-')){dirty=true;if(typeof captureColumnSelection==='function')captureColumnSelection();return;}c[k]=e.target.type==='checkbox'?e.target.checked:['length','precision','scale'].includes(k)?(e.target.value===''?null:Number(e.target.value)):e.target.value;dirty=true;});
$('column-rows').addEventListener('click',e=>{if(e.target.className==='remove-col'){s.columns.splice(+e.target.closest('tr').dataset.i,1);columns();dirty=true;}});
function numbered(vars){let counts={IN:0,OUT:0};return vars.map(v=>({...v,field_name:(v.role==='IN'?'S_TYPE':'S_STRING')+(++counts[v.role])}));}
function mappings(){s.variables=numbered(s.variables);if(typeof renderTmaxMappings==='function')renderTmaxMappings();}
function conditions(){$('conditions').innerHTML=conds.map((c,i)=>`<div class="condition" data-i="${i}"><select class="connector">${['AND','OR'].map(x=>`<option ${c.connector===x?'selected':''}>${x}</option>`).join('')}</select><select class="column">${(typeof sqlColumns==='function'?sqlColumns():s.columns.map(c=>({...c,key:c.name,label:c.name}))).map(x=>`<option value="${esc(x.key)}" ${c.column===x.key?'selected':''}>${esc(x.label)}</option>`).join('')}</select><select class="operator">${['=','<>','>','>=','<','<=','LIKE','IS NULL','IS NOT NULL'].map(x=>`<option ${c.operator===x?'selected':''}>${esc(x)}</option>`).join('')}</select><button data-remove-condition="1">삭제</button></div>`).join('');}
$('conditions').addEventListener('change',e=>{conds[+e.target.closest('.condition').dataset.i][e.target.className]=e.target.value;});$('conditions').addEventListener('click',e=>{if(e.target.dataset.removeCondition){conds.splice(+e.target.closest('.condition').dataset.i,1);conditions();}});
async function refresh(){services=await api('/services');list();}function list(){const q=$('search').value.toLowerCase(),f=$('filter').value;$('list').innerHTML=services.filter(x=>(!f||x.type===f)&&[x.service_id,x.name,x.description,x.table_name].join(' ').toLowerCase().includes(q)).map(x=>`<button class="service" data-id="${esc(x.service_id)}">${esc(x.service_id)} · ${esc(x.name)}<small>${x.type==='select'?'조회':'트랜잭션'} · ${esc(x.table_name)} · v${x.current_version}<br>${esc(new Date(x.updated_at).toLocaleString('ko-KR'))}</small></button>`).join('');}

$('list').addEventListener('click',e=>{const b=e.target.closest('[data-id]');if(b)action(async()=>{if(dirty&&!confirm('저장하지 않은 변경을 버릴까요?'))return;s=await api('/services/'+encodeURIComponent(b.dataset.id));existing=true;dirty=false;conds=[];render();status('저장된 서비스를 불러왔습니다.');})()});
$('search').oninput=list;$('filter').onchange=list;document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>tab(b.dataset.tab));
$('new').onclick=()=>{if(dirty&&!confirm('저장하지 않은 변경을 버릴까요?'))return;s=blank();existing=false;dirty=false;conds=[];render();tab('basic');status('새 서비스를 입력하세요.');};
$('sample').onclick=()=>{if(dirty&&!confirm('현재 편집 내용을 샘플로 바꿀까요?'))return;s=blank();s.service_id='MD_SAMPLE_S1';s.name='샘플 환자 조회';s.table_name='PATIENT';s.columns=[{name:'PATNO',db_type:'VARCHAR2',length:20,precision:null,scale:null,nullable:false,primary_key:true,comment:'환자번호',date_format:'YYYY-MM-DD'},{name:'SEQNO',db_type:'NUMBER',length:20,precision:10,scale:0,nullable:true,primary_key:false,comment:'순번',date_format:'YYYY-MM-DD'}];existing=false;dirty=true;conds=[];render();tab('columns');status('입력/출력 컬럼을 체크한 뒤 자동 매핑을 실행하세요.');};
$('save').onclick=action(async()=>{
 if(savingService)return;savingService=true;$('save').disabled=true;if($('proc-preview'))$('proc-preview').disabled=true;
 try{collect();if(!s.service_id.trim())throw Error('저장하려면 기본정보 탭에서 서비스 ID를 입력하세요. SQL 미리보기는 저장 없이 사용할 수 있습니다.');status('서비스 저장 중…');
 s=await api('/services'+(existing?'/'+encodeURIComponent(s.service_id):''),existing?'PUT':'POST',s);existing=true;dirty=false;render();await refresh();status('저장 완료 · 버전 '+s.current_version);
 }finally{savingService=false;$('save').disabled=false;if($('proc-preview'))$('proc-preview').disabled=typeof procBusy==='boolean'&&procBusy;}
});
$('duplicate').onclick=()=>{collect();const id=prompt('복제할 새 서비스 ID',s.service_id+'_COPY');if(!id)return;s.service_id=id;s.current_version=0;existing=false;dirty=true;render();status('복제본입니다. 저장을 눌러 생성하세요.');};
$('delete').onclick=action(async()=>{if(!existing)return;if(!confirm(s.service_id+' 서비스를 삭제할까요?'))return;await api('/services/'+encodeURIComponent(s.service_id),'DELETE');dirty=false;$('new').click();await refresh();status('삭제했습니다.');});
$('add-column').onclick=()=>{s.columns.push({name:'COL'+(s.columns.length+1),db_type:'VARCHAR2',length:20,precision:null,scale:null,nullable:true,primary_key:false,comment:'',date_format:'YYYY-MM-DD'});columns();dirty=true;};
$('auto-map').onclick=action(async()=>{collect();const rows=[...$('column-rows').rows],names=cls=>rows.filter(r=>r.querySelector('.'+cls).checked).map(r=>s.columns[+r.dataset.i].name);if(s.variables.length&&!confirm('현재 수동 매핑을 자동 매핑으로 교체할까요?'))return;s.variables=await api('/mappings/auto','POST',{columns:s.columns,inputs:names('use-in'),outputs:names('use-out')});mappings();dirty=true;status('자동 매핑 완료. 변수명과 실제 선언 타입을 확인하세요.');});
for(const role of ['IN','OUT'])$(role==='IN'?'add-in':'add-out').onclick=()=>{if(s.variables.filter(v=>v.role===role).length>=(role==='IN'?10:100)){status('전문 개수 제한을 초과했습니다.',true);return;}s.variables.push({role,variable_name:'sNew'+(s.variables.length+1),db_column:'',db_type:'VARCHAR2',host_type:'asciz',host_length:20,is_manual:true,array:role==='OUT',null_indicator:''});s.variables.sort((a,b)=>a.role.localeCompare(b.role));mappings();dirty=true;};
$('add-condition').onclick=()=>{if(!s.columns.length){status('컬럼을 먼저 등록하세요.',true);return;}conds.push({column:s.columns[0].name,operator:'=',connector:'AND'});conditions();};
$('generate').onclick=action(async()=>{
 const button=$('generate');button.disabled=true;button.textContent='SQL 생성 중…';
 try{
 collect();let b=s.sql_blocks[0];
 status('선택한 컬럼과 조건으로 SQL을 생성하고 있습니다.');
 if(b.final_sql!==b.generated_sql){if(!s.service_id.trim())throw Error('수동 편집본을 버전으로 보관하려면 기본정보에서 서비스 ID를 입력한 후 다시 생성하세요.');if(!confirm('현재 편집본을 버전으로 저장한 뒤 새 SQL로 교체할까요?'))return;const saved=await api('/services'+(existing?'/'+encodeURIComponent(s.service_id):''),existing?'PUT':'POST',s);s.current_version=saved.current_version;existing=true;$('service_id').disabled=true;await refresh();}
 const operation=$('operation').value;let allow=false;
 if(['UPDATE','DELETE'].includes(operation)&&!conds.length){allow=confirm('위험: WHERE 조건 없이 전체 행을 변경/삭제하는 SQL을 생성할까요?');if(!allow)return;}
 const result=await api('/sql/prepare','POST',{service:s,operation,selected:s.builder_state.selected??[],conditions:conds,order_by:$('order-by').value.split(',').map(x=>x.trim()).filter(Boolean),allow_full_table:allow});
 s=result.service;b=s.sql_blocks[0];b.block_type=operation;b.generated_sql=result.sql;b.final_sql=result.sql;b.is_manual=false;
 $('generated_sql').value=result.sql;$('final_sql').value=result.sql;mappings();dirty=true;if(typeof mappingGenerated==='function')mappingGenerated();
 $('sql-warnings').hidden=result.warnings.length===0;$('sql-warning-title').textContent='검증 경고 '+result.warnings.length+'건';$('sql-warning-body').textContent=result.warnings.join('\n');
 status('SQL 생성 완료. 아래 최종 SQL을 확인하세요.'+(s.service_id?'':' 서비스 저장 시에는 기본정보에서 서비스 ID를 입력하세요.'));
 if(!document.body.classList.contains('sql-mode'))$('final_sql').scrollIntoView({block:'center'});
 }finally{button.disabled=false;button.textContent='SQL 자동 생성 / 재생성';}
});
$('copy').onclick=action(async()=>{await navigator.clipboard.writeText($('final_sql').value);status('복사했습니다.');});$('download').onclick=()=>{collect();const u=URL.createObjectURL(new Blob([s.sql_blocks[0].final_sql],{type:'text/plain;charset=utf-8'})),a=document.createElement('a');a.href=u;a.download=(s.service_id.replace(/[^A-Za-z0-9_]/g,'_')||'service')+'.sql';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};
document.querySelector('section').addEventListener('input',()=>dirty=true);window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
action(async()=>{token=(await api('/session')).csrf_token;s=blank();render();tab('basic');await refresh();status('로컬 모드 · Oracle 연결 없이 사용 가능합니다.');})();

