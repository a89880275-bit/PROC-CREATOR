/* Split GET/PUT grids and explicit, fingerprint-checked SQL synchronization. */
let mappingPlan=null,mappingRevision=0,mappingTimer=null;
const mappingId=()=>crypto.randomUUID().replaceAll('-','');
function invalidateMappingPlan(){mappingRevision++;mappingPlan=null;$('sync-preview-panel').innerHTML='';}
function renderTmaxMappings(){
 if(!s)return;for(const v of s.variables)v.mapping_id||=mappingId();
 for(const [role,id,counter,limit] of [['IN','mapping-rows','mapping-in-count',10],['OUT','output-mapping-rows','mapping-out-count',100]]){
  const rows=s.variables.map((v,i)=>({v,i})).filter(r=>r.v.role===role);$(counter).textContent=`${rows.length} / ${limit}개`;
  $(id).innerHTML=rows.map(({v,i},position)=>`<tr data-i="${i}"><td>${position+1}</td><td title="${esc(v.source_expression||'')}">${input(v.db_column,'db_column')}<small>${esc(v.output_alias|| (v.sql_bind_name?':'+v.sql_bind_name:''))}</small></td><td>${esc(v.column_comment||'')}</td><td>${esc(v.db_type)}${v.precision!=null?'('+v.precision+','+(v.scale??'?')+')':v.db_length?'('+v.db_length+')':''}</td><td>${esc(v.field_name)}</td><td>${input(v.variable_name,'variable_name')}</td><td>${input(v.host_type,'host_type')}</td><td>${input(v.host_length,'host_length','number')}</td><td>${input(v.null_indicator||'','null_indicator')}</td><td><input type="checkbox" class="array" ${v.array?'checked':''}></td><td>${v.is_manual||v.order_manual?'수동':'자동'}<small>${v.is_active===false?'SQL 미사용 · 보관':v.mapping_status==='confirmed'?'사용자 확정':v.mapping_status==='unmapped'?'미매핑':'자동 발견'}</small></td><td><button data-move="-1">↑</button><button data-move="1">↓</button><button data-remove="1">삭제</button></td></tr>`).join('')||'<tr><td colspan="12">SQL을 생성하거나 분석해 전문 매핑을 추가하세요.</td></tr>';
 }
}
function mappingMessage(message,error=false){$('mapping-notice').textContent=message;$('mapping-notice').className=error?'error':'';$('sql-mapping-notice').textContent=message;}
for(const id of ['mapping-rows','output-mapping-rows']){
 $(id).addEventListener('change',e=>{const row=e.target.closest('[data-i]');if(!row)return;const v=s.variables[+row.dataset.i],field=e.target.className;
  v[field]=e.target.type==='checkbox'?e.target.checked:field==='host_length'?Number(e.target.value):e.target.value;
  if(field==='db_column'){const c=sqlColumns().find(c=>c.key===v.db_column);if(c){v.db_type=c.db_type;v.precision=c.precision;v.scale=c.scale;v.column_comment=c.comment;v.date_format=c.date_format;}}
  v.is_manual=true;v.mapping_status='confirmed';row.children[10].innerHTML='수동<small>사용자 확정</small>';dirty=true;invalidateMappingPlan();mappingMessage('수동 매핑을 변경했습니다. 최종 SQL과 동기화 미리보기를 확인하세요.');
 });
 $(id).addEventListener('click',e=>{const row=e.target.closest('[data-i]');if(!row)return;const index=+row.dataset.i,v=s.variables[index];
  if(e.target.dataset.remove){if(!confirm(`${v.field_name} / ${v.variable_name} 매핑을 삭제할까요? SQL은 그대로 유지됩니다.`))return;s.variables.splice(index,1);}
  else if(e.target.dataset.move){const same=s.variables.map((v,i)=>({v,i})).filter(r=>r.v.role===v.role),at=same.findIndex(r=>r.i===index),other=at+Number(e.target.dataset.move);if(other<0||other>=same.length)return;
   const next=structuredClone(s.variables),j=same[other].i;[next[index],next[j]]=[next[j],next[index]];next[index].order_manual=true;next[j].order_manual=true;
   const preview=numbered(next).filter(r=>r.role===v.role).map(r=>r.variable_name+' → '+r.field_name).join('\n');if(!confirm('전문 번호 재배정 미리보기\n'+preview+'\n반영할까요?'))return;s.variables=next;
  }else return;
  dirty=true;invalidateMappingPlan();mappings();mappingMessage('전문 매핑 순서를 변경했습니다. 저장하면 다시 열 때 유지됩니다.');
 });
}
for(const role of ['IN','OUT'])$(role==='IN'?'add-in':'add-out').onclick=()=>{if(s.variables.filter(v=>v.role===role).length>=(role==='IN'?10:100)){mappingMessage('입력 10개 / 출력 100개 제한을 초과했습니다.',true);return;}
 let name='sManual'+(s.variables.length+1)+(role==='OUT'?'Out':'');while(s.variables.some(v=>v.variable_name===name))name+='_';
 s.variables.push({mapping_id:mappingId(),role,db_column:'',column_comment:'',db_type:'VARCHAR2',variable_name:name,sql_bind_name:role==='IN'?name:'',host_type:'asciz',host_length:20,array:role==='OUT',is_manual:true,order_manual:false,mapping_status:'unmapped',is_active:true,source_expression:'',output_alias:'',null_indicator:'',precision:null,scale:null,date_format:'YYYY-MM-DD'});dirty=true;invalidateMappingPlan();mappings();};
function mappingGenerated(){invalidateMappingPlan();mappingMessage('SQL 생성 기준 GET/PUT 매핑을 추가했습니다. 수동 이름·전문 순서는 보존했습니다.');}
function metadataFields(item){const c=item.metadata||{},value=item.proposed||item.existing||{};return `<select class="sync-source" aria-label="분석 항목 DB 컬럼"><option value="">직접 자료형 확인 / 계산식</option>${sqlColumns().map(c=>`<option value="${esc(c.key)}" ${item.db_column===c.key?'selected':''}>${esc(c.label)}</option>`).join('')}</select><select class="sync-type" aria-label="분석 항목 DB 타입"><option value="">자료형 확인 필요</option>${['VARCHAR2','CHAR','DATE','TIMESTAMP','NUMBER','INTEGER','FLOAT','CLOB'].map(t=>`<option ${c.db_type===t?'selected':''}>${t}</option>`).join('')}</select><input class="sync-length" type="number" min="1" value="${c.length||64}" aria-label="자료형 길이"><input class="sync-precision" type="number" value="${c.precision??''}" placeholder="정밀도" aria-label="정밀도"><input class="sync-scale" type="number" value="${c.scale??''}" placeholder="스케일" aria-label="스케일"><small>${esc(item.reason||'')}</small>`;}
function showMappingPlan(plan,forceOpen=false){mappingPlan=plan;const fresh=plan.rows.filter(r=>r.change==='신규').length,changed=plan.rows.filter(r=>r.change==='변경').length;
 $('sync-preview-panel').innerHTML=`<details id="sync-plan-details" ${forceOpen||plan.errors.length||plan.removed.length||plan.rows.some(r=>r.change!=='유지'||r.rewrite_bind||!r.proposed)?'open':''}><summary>SQL / 전문 차이 미리보기</summary><p>신규 ${fresh}개 · 변경 ${changed}개 · SQL에서 사라진 기존 매핑 ${plan.removed.length}개</p><p>${esc(plan.limitations)} 기존 수동 이름·호스트 타입·전문 순서는 유지합니다. 이름이 SQL 바인드와 다르면 확인 후 SQL의 실제 바인드 토큰만 일치시킵니다.</p>${plan.errors.map(e=>`<p class="validation-error">${esc(e)}</p>`).join('')}${plan.warnings.map(w=>`<p>경고: ${esc(w)}</p>`).join('')}<div class="scroll"><table class="sync-table"><thead><tr><th>변경</th><th>방향 / SQL 위치</th><th>SQL 바인드 / 출력 별칭·식</th><th>DB 컬럼 / 자료형 확인</th><th>변수명</th><th>호스트 타입</th><th>호스트 길이</th><th>분석 상태</th></tr></thead><tbody>${plan.rows.map((r,i)=>`<tr data-plan-index="${i}"><td>${r.change}${r.rewrite_bind?'<small>SQL 바인드명 정합화</small>':''}</td><td>${r.role} #${r.position}</td><td>${esc(r.sql_bind_name||r.output_alias||'별칭 필요')}<small class="sql-expression">${esc(r.expression)}</small></td><td>${metadataFields(r)}</td><td><input class="sync-variable" value="${esc(r.proposed?.variable_name||r.existing?.variable_name||'')}" placeholder="자료형 확인 후 자동 생성"></td><td><input class="sync-host" value="${esc(r.proposed?.host_type||r.existing?.host_type||'asciz')}"></td><td><input class="sync-host-length" type="number" value="${r.proposed?.host_length||r.existing?.host_length||64}"></td><td>${r.status==='unmapped'?'미매핑 · 확인 필요':r.status==='confirmed'?'사용자 확정':'자동 발견'}</td></tr>`).join('')}</tbody></table></div>${plan.removed.length?'<h4>SQL에서 사라진 매핑 — 기본은 보관, 체크한 항목만 삭제</h4>'+plan.removed.map(v=>`<label class="sync-removal"><input type="checkbox" data-remove-id="${esc(v.mapping_id)}"> ${esc(v.field_name)} / ${esc(v.variable_name)} / ${esc(v.db_column)} ${v.is_manual?'(수동 수정됨)':''}</label>`).join(''):''}<label class="sync-removal"><input id="sync-output-order" type="checkbox"> SELECT 결과 순서대로 출력 전문을 재배정 (기존 수동 순서 변경 포함, 명시적 선택)</label><p id="sync-reorder-preview"></p><button id="sync-apply" class="primary" ${plan.errors.length?'disabled':''}>확인한 변경 반영</button></details>`;
 $('sync-preview-panel').onchange=e=>{const row=e.target.closest('[data-plan-index]');if(row)e.target.dataset.touched='1';if(row&&e.target.classList.contains('sync-source')){const c=sqlColumns().find(c=>c.key===e.target.value);if(c)for(const [cls,field] of [['sync-type','db_type'],['sync-length','length'],['sync-precision','precision'],['sync-scale','scale']]){row.querySelector('.'+cls).value=c[field]??'';delete row.querySelector('.'+cls).dataset.touched;}}if(e.target.id==='sync-output-order')$('sync-reorder-preview').textContent=e.target.checked?plan.rows.filter(r=>r.role==='OUT').map((r,i)=>(r.output_alias||r.expression)+' → S_STRING'+(i+1)).join(' / '):'기존 출력 전문 순서를 유지합니다.';};
 $('sync-apply').onclick=action(applyMappingPlan);mappingMessage(`SQL 분석 완료: 신규 ${fresh}개, 변경 ${changed}개, 삭제 후보 ${plan.removed.length}개. 확인 후 반영하세요.`);
}
async function analyzeMappings(forceOpen=false){collect();if(!s.sql_blocks[0].final_sql.trim()){mappingMessage('먼저 SQL을 생성하거나 최종 SQL을 입력하세요.',true);return;}
 const revision=mappingRevision;mappingMessage('최종 SQL의 입력 바인드·SELECT 결과를 분석하고 있습니다.');const plan=await api('/mappings/sync/preview','POST',{service:s});if(revision!==mappingRevision)return;showMappingPlan(plan,forceOpen);}
$('sync-preview').onclick=action(()=>analyzeMappings(true));
async function applyMappingPlan(){if(!mappingPlan)throw Error('먼저 SQL 동기화 미리보기를 실행하세요.');collect();const overrides={};
 $('sync-preview-panel').querySelectorAll('[data-plan-index]').forEach(row=>{const item=mappingPlan.rows[+row.dataset.planIndex],edit={};
  const value=cls=>row.querySelector('.'+cls),touched=cls=>value(cls).dataset.touched==='1';
  const metaTouched=['sync-type','sync-length','sync-precision','sync-scale','sync-source'].some(touched);
  if(metaTouched||(!item.metadata&&value('sync-type').value)){
   let meta={...(item.metadata||{}),name:item.metadata?.name||'VALUE',db_type:value('sync-type').value,length:Number(value('sync-length').value),precision:value('sync-precision').value===''?null:Number(value('sync-precision').value),scale:value('sync-scale').value===''?null:Number(value('sync-scale').value)};
   if(touched('sync-source')){edit.db_column=value('sync-source').value;const c=sqlColumns().find(c=>c.key===edit.db_column);if(c){meta={...c,name:c.name};for(const [cls,field] of [['sync-type','db_type'],['sync-length','length'],['sync-precision','precision'],['sync-scale','scale']])if(touched(cls))meta[field]=cls==='sync-type'?value(cls).value:value(cls).value===''?null:Number(value(cls).value);}}
   edit.metadata=meta;
  }
  if(touched('sync-variable')&&value('sync-variable').value.trim())edit.variable_name=value('sync-variable').value.trim();
  if(touched('sync-host'))edit.host_type=value('sync-host').value;
  if(touched('sync-host-length'))edit.host_length=Number(value('sync-host-length').value);
  if(Object.keys(edit).length)overrides[item.key]=edit;
 });
 const remove_ids=[...$('sync-preview-panel').querySelectorAll('[data-remove-id]:checked')].map(x=>x.dataset.removeId),reorder=$('sync-output-order').checked;
 if(!confirm('SQL 분석에 따른 매핑 변경을 반영할까요?'+(remove_ids.length?'\n선택한 기존 매핑 '+remove_ids.length+'개를 삭제합니다.':'\nSQL에서 사라진 기존 매핑은 삭제하지 않고 보관합니다.')+(reorder?'\n출력 전문을 SELECT 순서로 재배정합니다.':'\n기존 전문 순서를 유지합니다.')))return;
 const result=await api('/mappings/sync/apply','POST',{service:s,fingerprint:mappingPlan.fingerprint,overrides,remove_ids,reorder_outputs:reorder});s=result.service;$('final_sql').value=result.sql;dirty=true;invalidateMappingPlan();mappings();mappingMessage('SQL과 전문 매핑을 동기화했습니다. 서비스 저장을 눌러 보관하세요.');status('전문 동기화 완료. 수동 변수명·호스트 선언을 보존했습니다.');
}
function scheduleMappingAnalysis(delay=700){clearTimeout(mappingTimer);mappingTimer=setTimeout(()=>{action(analyzeMappings)();},delay);}
$('final_sql').addEventListener('input',()=>{invalidateMappingPlan();mappingMessage('SQL이 변경되었습니다. 분석 후 동기화 미리보기에서 확인하세요.');scheduleMappingAnalysis();});
$('open-mapping').onclick=()=>{collect();tab('mapping');};
if(s)renderTmaxMappings();
