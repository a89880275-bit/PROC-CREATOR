/* Optional second table for SELECT. Metadata is snapshotted with the service. */
let sqlDictionaryTables=[];
const tableKey=t=>(t.owner||'')+'|'+t.table_name;
async function refreshSQLTables(){sqlDictionaryTables=await api('/dictionary/tables');$('sql-column-source').onchange=renderPicker;
if(s)renderJoinControls();}
function tableOptions(current,optional){
 const options=sqlDictionaryTables.map(t=>`<option value="${esc(tableKey(t))}">${esc((t.owner?t.owner+'.':'')+t.table_name+' / '+t.comment)}</option>`);
 if(current&&!sqlDictionaryTables.some(t=>tableKey(t)===tableKey(current)))options.unshift(`<option value="${esc(tableKey(current))}">${esc(current.table_name)} (보관 정의)</option>`);
 return `<option value="">${optional?'선택 안 함':'테이블 사전에서 선택'}</option>`+options.join('');
}
function renderJoinControls(){
 if(!s)return;const joined=(s.join_tables||[])[0];
 $('sql-main-table').innerHTML=tableOptions(s,false);$('sql-main-table').value=tableKey(s);$('sql-main-alias').value=s.table_alias||'';
 $('sql-join-table').innerHTML=tableOptions(joined,true);$('sql-join-table').value=joined?tableKey(joined):'';$('sql-join-alias').value=joined?.alias||'b';
 $('sql-join-settings').hidden=!joined;$('sql-join-type').value=joined?.join_type||'INNER';
 for(const option of $('operation').options)option.disabled=!!joined&&option.value!=='SELECT';
 const filter=$('sql-column-source');filter.options[1].textContent='메인 '+(s.table_alias||'a');filter.options[2].textContent='조인 '+(joined?.alias||'b');filter.options[2].disabled=!joined;if(!joined&&filter.value==='join')filter.value='all';
 renderJoinConditions();renderPicker();
}
function renderJoinConditions(){const joined=(s.join_tables||[])[0];if(!joined){$('sql-join-conditions').innerHTML='';return;}
 const options=(columns,value,alias)=>columns.map(c=>`<option value="${esc(c.name)}" ${c.name===value?'selected':''}>${esc(alias+'.'+c.name)}</option>`).join('');
 $('sql-join-conditions').innerHTML=joined.conditions.map((c,i)=>`<div class="join-condition" data-index="${i}"><select class="left_column" aria-label="메인 JOIN 컬럼">${options(s.columns,c.left_column,s.table_alias||'a')}</select><select class="operator" aria-label="JOIN 연산자">${['=','<>','>','>=','<','<='].map(x=>`<option ${c.operator===x?'selected':''}>${esc(x)}</option>`).join('')}</select><select class="right_column" aria-label="조인 JOIN 컬럼">${options(joined.columns,c.right_column,joined.alias)}</select><button class="remove-join-condition" aria-label="JOIN 조건 삭제">×</button></div>`).join('')||'<p>JOIN 조건을 추가하세요.</p>';
}
function clearJoinedSelections(prefix){
 s.builder_state??={};s.builder_state.selected=(s.builder_state.selected||[]).filter(n=>!n.startsWith(prefix));
 conds=conds.filter(c=>!c.column.startsWith(prefix));$('order-by').value=$('order-by').value.split(',').map(n=>n.trim()).filter(n=>n&&!n.startsWith(prefix)).join(', ');
}
$('sql-main-table').onchange=action(async()=>{
 const t=sqlDictionaryTables.find(t=>tableKey(t)===$('sql-main-table').value);if(!t||tableKey(t)===tableKey(s))return;
 collect();if(s.columns.length&&!confirm('메인 테이블을 변경하고 SQL 컬럼/조건 선택을 초기화할까요? 기존 SQL과 전문 매핑은 보존됩니다.')){renderJoinControls();return;}
 s.owner=t.owner;s.table_name=t.table_name;s.columns=structuredClone(t.columns);s.dictionary_revision=t.revision;
 if(s.join_tables?.length)s.join_tables[0].conditions=[];
 s.builder_state={selected:[],conditions:[],order_by:[]};conds=[];$('order-by').value='';dirty=true;render();
 status('메인 테이블을 변경했습니다. 컬럼과 JOIN 조건을 다시 선택하세요. 기존 SQL/매핑은 보존했습니다.');
});
$('sql-join-table').onchange=action(async()=>{
 const key=$('sql-join-table').value,t=sqlDictionaryTables.find(t=>tableKey(t)===key),old=(s.join_tables||[])[0];
 if(old&&tableKey(old)===key)return;
 collect();if(old&&!confirm('조인 테이블을 변경/해제할까요? 해당 컬럼 선택과 조건은 초기화하며 기존 SQL·전문 매핑은 보존합니다.')){renderJoinControls();return;}
 if(old)clearJoinedSelections(old.alias+'.');
 if(!key)s.join_tables=[];
 else{
  if(!t)throw Error('선택한 조인 테이블을 찾을 수 없습니다. 테이블 사전을 다시 확인하세요.');
  s.table_alias=s.table_alias||'a';$('table_alias').value=s.table_alias;
  let alias=$('sql-join-alias').value||'b';if(alias.toLowerCase()===s.table_alias.toLowerCase())alias=['b','j','j2'].find(x=>x.toLowerCase()!==s.table_alias.toLowerCase());
  const common=s.columns.find(c=>c.primary_key&&t.columns.some(x=>x.name===c.name))||s.columns.find(c=>t.columns.some(x=>x.name===c.name));
  s.join_tables=[{owner:t.owner,table_name:t.table_name,alias,join_type:'INNER',columns:structuredClone(t.columns),dictionary_revision:t.revision,conditions:common?[{left_column:common.name,operator:'=',right_column:common.name}]:[]}];
  $('operation').value='SELECT';s.sql_blocks[0].block_type='SELECT';
 }
 captureBuilder();renderJoinControls();conditions();renderPicker();dirty=true;
 status(key?'조인 테이블을 추가했습니다. 동명 컬럼의 JOIN 조건 후보를 검토하고 양쪽 컬럼을 선택하세요.':'조인을 해제했습니다. 기존 전문 매핑은 보존했습니다.');
});
function validateSourceAlias(alias,other){if(!/^[A-Za-z_][A-Za-z0-9_]{0,19}$/.test(alias))throw Error('별칭은 영문/숫자/밑줄로 20자 이내로 입력하세요.');if(alias.toLowerCase()===other.toLowerCase())throw Error('메인/조인 별칭은 서로 달라야 합니다.');}
$('sql-main-alias').onchange=action(async()=>{const alias=$('sql-main-alias').value.trim(),joined=(s.join_tables||[])[0];try{if(alias||joined)validateSourceAlias(alias,joined?.alias||'');}catch(e){$('sql-main-alias').value=s.table_alias||'';throw e;}s.table_alias=alias;$('table_alias').value=alias;renderJoinConditions();conditions();renderPicker();dirty=true;});
$('sql-join-alias').onchange=action(async()=>{const joined=(s.join_tables||[])[0];if(!joined)return;const alias=$('sql-join-alias').value.trim();try{validateSourceAlias(alias,s.table_alias||'a');}catch(e){$('sql-join-alias').value=joined.alias;throw e;}
 const before=joined.alias+'.',after=alias+'.',remap=n=>n.startsWith(before)?after+n.slice(before.length):n;
 captureBuilder();s.builder_state.selected=(s.builder_state.selected||[]).map(remap);conds.forEach(c=>c.column=remap(c.column));$('order-by').value=$('order-by').value.split(',').map(x=>x.trim()).filter(Boolean).map(remap).join(', ');s.variables.forEach(v=>v.db_column=remap(v.db_column));joined.alias=alias;captureBuilder();renderJoinControls();conditions();renderPicker();mappings();dirty=true;status('별칭과 컬럼 연결을 변경했습니다. 기존 SQL은 보존했으므로 다시 생성해 주세요.');});
$('sql-join-type').onchange=()=>{const joined=(s.join_tables||[])[0];if(joined){joined.join_type=$('sql-join-type').value;dirty=true;}};
$('sql-add-join-condition').onclick=()=>{const joined=(s.join_tables||[])[0];if(!joined||!s.columns.length||!joined.columns.length)return;if(joined.conditions.length>=10){status('JOIN 조건은 10개까지 가능합니다.',true);return;}joined.conditions.push({left_column:s.columns[0].name,operator:'=',right_column:joined.columns[0].name});renderJoinConditions();dirty=true;};
$('sql-join-conditions').addEventListener('change',e=>{const row=e.target.closest('.join-condition');if(row){s.join_tables[0].conditions[+row.dataset.index][e.target.className]=e.target.value;dirty=true;}});
$('sql-join-conditions').addEventListener('click',e=>{if(e.target.classList.contains('remove-join-condition')){s.join_tables[0].conditions.splice(+e.target.closest('.join-condition').dataset.index,1);renderJoinConditions();dirty=true;}});
$('sql-column-source').onchange=renderPicker;
if(s)renderJoinControls();
