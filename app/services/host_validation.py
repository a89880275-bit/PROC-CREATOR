"""Host definitions remain provisional until the target Pro*C environment is checked."""
from app.services.mapping_service import auto_mappings
from app.models import Service
from app.services.sql_sources import column_catalog, validate_join
import re

def date_width(fmt):
    """Conservative supported Oracle format subset; no claim of full SQL parsing."""
    tokens={'YYYY':4,'RRRR':4,'HH24':2,'HH12':2,'MONTH':9,'MON':3,'DDD':3,
            'YY':2,'RR':2,'MM':2,'DD':2,'HH':2,'MI':2,'SS':2,'AM':2,'PM':2}
    remaining=fmt.upper();width=0
    while remaining:
        fraction=re.match(r'FF([1-9])?',remaining)
        if fraction:
            width+=int(fraction[1] or 9);remaining=remaining[len(fraction[0]):];continue
        found=next((t for t in tokens if remaining.startswith(t)),None)
        if found: width+=tokens[found];remaining=remaining[len(found):]
        elif remaining[0] in ' -/:.': width+=1;remaining=remaining[1:]
        else: raise ValueError('지원하지 않는 날짜 포맷입니다: '+fmt)
    return width

def host_warnings(service):
    result=[];cols={key:entry[0] for key,entry in column_catalog(service).items()}
    for v in service.variables:
        c=cols.get(v.db_column)
        if not c: result.append(f'{v.variable_name}: 사전에 없는 보관 매핑입니다. 삭제하지 않았습니다.');continue
        t=c.db_type.upper()
        if t in {'NUMBER','NUMERIC','DECIMAL'}:
            if c.precision is None or c.scale is None: raise ValueError(c.name+': NUMBER 정밀도/스케일 확인 필요')
            if v.host_type in {'int','long'} and (c.scale!=0 or c.precision>(9 if v.host_type=='int' else 18)):
                raise ValueError(c.name+': 정수 호스트 선언에 정밀도 손실 위험이 있습니다. asciz 등으로 수정하세요.')
            if v.host_type in {'asciz','char'} and v.host_length < max(c.precision+max(0,-c.scale)+3,c.scale+3):
                raise ValueError(c.name+': NUMBER 문자열 호스트 길이가 부족합니다.')
            result.append(c.name+': 숫자 접두어는 선언 타입 보장이 아닙니다. 문자열 입력은 TO_NUMBER로 변환하며 운영 NLS/정밀도 검증이 필요합니다.')
        if t in {'DATE','TIMESTAMP'}:
            if not c.date_format: raise ValueError(c.name+': 날짜 문자열 포맷이 필요합니다.')
            if v.host_type not in {'asciz','char'}: raise ValueError(c.name+': 날짜 입력은 문자열 호스트 선언을 사용하세요.')
            if v.host_length<date_width(c.date_format): raise ValueError(c.name+': 날짜 호스트 길이가 부족합니다.')
            result.append(c.name+': '+c.date_format+' 문자열 변환. 실제 포맷과 NULL 지시 변수를 확인하세요.')
        if c.nullable and not v.null_indicator:
            result.append(c.name+': NULL 허용 컬럼입니다. Pro*C 생성 전에 NULL 지시 변수를 지정하세요.')
    return list(dict.fromkeys(result))

def prepare(request):
    s=request.service.model_copy(deep=True)
    validate_join(s,request.operation)
    catalog=column_catalog(s)
    inputs=[c.column for c in request.conditions if c.operator not in {'IS NULL','IS NOT NULL'}]
    if request.operation in {'INSERT','UPDATE'}: inputs+=request.selected
    outputs=request.selected if request.operation=='SELECT' else []
    for role,names in [('IN',inputs),('OUT',outputs)]:
        for n in dict.fromkeys(names):
            if any(v.role==role and v.db_column==n for v in s.variables): continue
            if n not in catalog:raise ValueError('등록되지 않은 컬럼: '+n)
            c,alias=catalog[n]
            source=c.model_copy(update={'name':alias+'_'+c.name}) if '.' in n else c
            vs=auto_mappings([source],[source.name] if role=='IN' else [],[source.name] if role=='OUT' else [])
            v=vs[0];v.db_column=n;taken={x.variable_name for x in s.variables}
            if v.variable_name in taken: v.variable_name+=('Out' if role=='OUT' else 'In')
            if v.variable_name in taken: raise ValueError('변수명 충돌: '+v.variable_name)
            s.variables.append(v)
    s=type(request.service).model_validate(s.model_dump())
    return s,host_warnings(s)
