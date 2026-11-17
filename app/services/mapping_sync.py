"""Preview first; apply only a fingerprint-matched, explicitly confirmed mapping plan."""
import hashlib,json,re
from app.models import Column,Variable
from app.services.mapping_service import auto_mappings
from app.services.sql_analyzer import analyze_sql,tokenize,normalize_expression,indicator_bindings
from app.services.sql_sources import column_catalog

def fingerprint(service):return hashlib.sha256(service.model_dump_json().encode()).hexdigest()
def sql_fingerprint(sql):return hashlib.sha256(sql.encode()).hexdigest()
def safe_identifier(value):
    value=re.sub(r'[^A-Za-z0-9_]','_',value).strip('_') or 'Value'
    return ('_'+value if value[0].isdigit() else value)[:48]

def proposed_variable(item,metadata=None):
    metadata=metadata or item['metadata']
    if metadata is None:return None
    c=Column(**metadata)
    seed=item['sql_bind_name'] if item['role']=='IN' else item['output_alias'] or (c.name if item['db_column'] else '')
    if not seed:return None
    naming=c.model_copy(update={'name':safe_identifier(seed if not item['db_column'] or item['role']=='OUT' else c.name)})
    try:v=auto_mappings([naming],[naming.name] if item['role']=='IN' else [],[naming.name] if item['role']=='OUT' else [])[0]
    except ValueError:return None
    if item['role']=='IN':v.variable_name=item['sql_bind_name'];v.sql_bind_name=item['sql_bind_name']
    elif item.get('into_variable_name'):v.variable_name=item['into_variable_name']
    v.db_column=item['db_column'];v.column_comment=c.comment;v.source_expression=item['expression'];v.output_alias=item['output_alias'];v.source_position=item['position'];v.null_indicator=item.get('null_indicator','')
    return v

def preview_sync(service):
    analysis=analyze_sql(service);used=set();rows=[];old=service.variables
    for item in analysis['inputs']+analysis['outputs']:
        candidates=[v for v in old if v.role==item['role'] and v.mapping_id not in used]
        match=None
        if item['role']=='IN':
            match=next((v for v in candidates if v.variable_name==item['sql_bind_name'] or v.sql_bind_name==item['sql_bind_name']),None)
            if not match and item['db_column']:match=next((v for v in candidates if v.db_column==item['db_column']),None)
        else:
            match=next((v for v in candidates if v.output_alias and v.output_alias.upper()==item['output_alias'].upper()),None)
            if not match:
                refs=item['source_references']
                match=next((v for v in candidates if (item['db_column'] and v.db_column==item['db_column']) or (len(refs)==1 and v.db_column==refs[0])),None)
        if item['role']=='OUT' and not match:match=next((v for v in candidates if v.source_expression and normalize_expression(v.source_expression)==normalize_expression(item['expression'])),None)
        if match:used.add(match.mapping_id)
        if match and item['metadata'] is None and (item['role']=='IN' or (match.mapping_status=='confirmed' and match.source_expression and normalize_expression(match.source_expression)==normalize_expression(item['expression']))):
            item['metadata']=Column(name=safe_identifier(match.db_column or match.variable_name),db_type=match.db_type,length=match.db_length or match.host_length,precision=match.precision,scale=match.scale,comment=match.column_comment,date_format=match.date_format).model_dump()
        proposed=proposed_variable(item)
        if match and proposed:
            proposed.mapping_id=match.mapping_id;proposed.variable_name=match.variable_name
            proposed.host_type=match.host_type
            proposed.host_length=match.db_length or match.host_length if match.is_manual else max(match.host_length,proposed.host_length)
            proposed.is_manual=match.is_manual;proposed.order_manual=match.order_manual;proposed.null_indicator=match.null_indicator or proposed.null_indicator;proposed.array=match.array
            if not proposed.db_column:proposed.db_column=match.db_column if len(item['source_references'])==1 else ''
        change='신규' if not match else '유지'
        if match:
            changed=match.source_expression and normalize_expression(match.source_expression)!=normalize_expression(item['expression'])
            if changed or (match.source_position and match.source_position!=item['position']) or match.output_alias!=item['output_alias'] or not match.is_active:change='변경'
        sql_name=item.get('sql_bind_name') if item['role']=='IN' else item.get('into_variable_name')
        rewrite=bool(match and sql_name and sql_name!=match.variable_name)
        if rewrite and change=='유지':change='변경'
        rows.append({**item,'match_id':match.mapping_id if match else None,'existing':match.model_dump() if match else None,'proposed':proposed.model_dump() if proposed else None,'change':change,'rewrite_bind':rewrite,'status':'confirmed' if match and match.is_manual else item['status']})
    removed=[v.model_dump() for v in old if v.mapping_id not in used]
    return dict(fingerprint=fingerprint(service),rows=rows,removed=removed,errors=analysis['errors'],warnings=analysis['warnings'],limitations=analysis['limitations'])

def rewrite_binds(sql,replacements):
    tokens=tokenize(sql);_,indicator_starts=indicator_bindings(tokens)
    changes=[(t.start,t.end,':'+replacements[t.text]) for t in tokens if t.kind=='bind' and t.start not in indicator_starts and t.text in replacements and replacements[t.text]!=t.text]
    for start,end,value in reversed(changes):sql=sql[:start]+value+sql[end:]
    return sql

def apply_sync(service,expected,overrides=None,remove_ids=None,reorder_outputs=False):
    if fingerprint(service)!=expected:raise ValueError('미리보기 후 SQL 또는 매핑이 변경되었습니다. 다시 분석하세요.')
    plan=preview_sync(service)
    if plan['errors']:raise ValueError('\n'.join(plan['errors']))
    overrides=overrides or {};remove_ids=set(remove_ids or []);allowed={v['mapping_id'] for v in plan['removed']}
    if not remove_ids<=allowed:raise ValueError('삭제 선택이 현재 미리보기와 다릅니다.')
    if not set(overrides)<={r['key'] for r in plan['rows']}:raise ValueError('유효하지 않은 매핑 수정 항목입니다.')
    replacements={};by_id={};sql_order=[];names=set()
    for item in plan['rows']:
        edit=overrides.get(item['key'],{});item=dict(item)
        if 'db_column' in edit:
            catalog=column_catalog(service)
            if edit['db_column'] and edit['db_column'] not in catalog:raise ValueError('등록되지 않은 수동 매핑 컬럼입니다.')
            item['db_column']=edit['db_column'];item['source_references']=[edit['db_column']] if edit['db_column'] else []
            if edit['db_column'] and 'metadata' not in edit:item['metadata']=catalog[edit['db_column']][0].model_dump()
        metadata=edit.get('metadata') or item['metadata']
        v=Variable(**item['proposed']) if item['proposed'] else proposed_variable(item,metadata)
        if metadata is not None and ('metadata' in edit or 'db_column' in edit or v is None):v=proposed_variable(item,metadata)
        if v is None:raise ValueError(item['key']+': 별칭/자료형/정밀도/스케일을 확인한 뒤 반영하세요.')
        existing=Variable(**item['existing']) if item['existing'] else None
        if existing:
            v.mapping_id=existing.mapping_id;v.variable_name=existing.variable_name;v.is_manual=existing.is_manual;v.order_manual=existing.order_manual;v.null_indicator=existing.null_indicator or v.null_indicator;v.host_type=existing.host_type
            v.host_length=existing.host_length if existing.is_manual else max(existing.host_length,v.host_length)
        for field in ['variable_name','host_type','host_length']:
            if field in edit and edit[field] is not None:setattr(v,field,edit[field]);v.is_manual=True
        if 'metadata' in edit or 'db_column' in edit:v.is_manual=True
        if v.variable_name in names:raise ValueError('호스트 변수명 충돌: '+v.variable_name+' (미리보기에서 수정하세요.)')
        names.add(v.variable_name);v.is_active=True;v.mapping_status='confirmed';v.source_position=item['position']
        if item['role']=='IN':replacements[item['sql_bind_name']]=v.variable_name;v.sql_bind_name=v.variable_name;v.source_expression=':'+v.variable_name
        if item['role']=='OUT' and item.get('into_variable_name'):replacements[item['into_variable_name']]=v.variable_name
        by_id[v.mapping_id]=v
        if item['role']=='OUT':sql_order.append(v.mapping_id)
    # Preserve the user's existing order; new rows append within each role.
    current=[]
    for old in service.variables:
        if old.mapping_id in by_id:current.append(by_id.pop(old.mapping_id))
        elif old.mapping_id not in remove_ids:
            stale=old.model_copy(deep=True);stale.is_active=False;current.append(stale)
    current+=list(by_id.values())
    if reorder_outputs:
        positions={key:i for i,key in enumerate(sql_order)}
        inputs=[v for v in current if v.role=='IN'];outputs=[v for v in current if v.role=='OUT']
        outputs.sort(key=lambda v:positions.get(v.mapping_id,len(positions)))
        for v in outputs:v.order_manual=True
        current=inputs+outputs
    result=service.model_copy(deep=True);result.variables=current
    result.sql_blocks[0].final_sql=rewrite_binds(result.sql_blocks[0].final_sql,replacements)
    result.sql_blocks[0].is_manual=result.sql_blocks[0].final_sql!=result.sql_blocks[0].generated_sql
    result.mapping_sql_fingerprint=sql_fingerprint(result.sql_blocks[0].final_sql)
    result=type(service).model_validate(result.model_dump())
    # Validate result types independently of source columns, including computed expressions.
    for v in result.variables:
        if not v.is_active:continue
        if v.db_type.upper() in {'NUMBER','NUMERIC','DECIMAL'}:
            if v.precision is None or v.scale is None:raise ValueError(v.variable_name+': NUMBER 정밀도/스케일 확인이 필요합니다.')
            if v.host_type in {'int','long'} and (v.scale!=0 or v.precision>(9 if v.host_type=='int' else 18)):raise ValueError(v.variable_name+': 정수 호스트 범위를 초과합니다. asciz 문자열 등을 사용하세요.')
            if v.host_type in {'asciz','char'} and v.host_length<max(v.precision+max(0,-v.scale)+3,v.scale+3):raise ValueError(v.variable_name+': 숫자 호스트 길이가 부족합니다.')
        if v.db_type.upper() in {'DATE','TIMESTAMP'}:
            from app.services.host_validation import date_width
            if v.host_type not in {'asciz','char'} or v.host_length<date_width(v.date_format):raise ValueError(v.variable_name+': DATE 문자열 타입/길이/포맷을 확인하세요.')
    return result

def annotate_generated(service,sql):
    temporary=service.model_copy(deep=True);temporary.sql_blocks[0].final_sql=sql
    analysis=analyze_sql(temporary)
    inputs={x['sql_bind_name']:x for x in analysis['inputs']}
    outputs=analysis['outputs']
    for v in service.variables:
        item=inputs.get(v.variable_name) if v.role=='IN' else next((x for x in outputs if x['db_column']==v.db_column or x['source_references']==[v.db_column]),None)
        v.is_active=bool(item)
        if item:
            v.source_expression=item['expression'];v.output_alias=item['output_alias'];v.source_position=item['position']
            if v.role=='IN':v.sql_bind_name=v.variable_name
    service.mapping_sql_fingerprint=sql_fingerprint(sql)
