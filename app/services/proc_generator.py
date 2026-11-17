"""Sample-derived SELECT Pro*C generator. No execution or compiler claim."""
from pathlib import Path
import re,hashlib
from jinja2 import Environment,FileSystemLoader,StrictUndefined
from app.models import IDENT
from app.services.sql_analyzer import tokenize,analyze_sql,normalize_expression,indicator_bindings,parse_into_groups
from app.services.mapping_sync import sql_fingerprint
TEMPLATE_ID='select.sample.md_fdrpt_s5'
TEMPLATE_VERSION='1.0.0'
ROOT=Path(__file__).resolve().parents[1]
ASCIZ=[(1,'asciz1'),(10,'asciz10'),(20,'asciz20'),(30,'asciz30'),(50,'asciz50'),(100,'asciz1h'),(300,'asciz3h'),(500,'asciz5h'),(3000,'asciz3k')]
FIXED_NAMES={'rowcnt1','iDaycnt','jj','ii','ix','DataCnt','NULL','DEBUG','__STDC__','printf','memset',*(name for _,name in ASCIZ),'int','char','long','short','double','float','void','return','if','else','for','while','struct','typedef','static','const','enum','union','sizeof','break','continue','switch','case','do','auto','signed','unsigned','register','volatile','extern','goto','default','MSGLEN','MAXBUFSIZE','FBFR','TPSVCINFO','MakeErrMsg','MakeMsg','GET','PUT','TPRETURN','TPRETURN_ERROR','applog','Finit','Fsizeof','Fprint','tprealloc','SQLMSG','TUXMSG','TUXFMSG','DBSEL','TUXALLOC','TUXINIT','SF_A220','SF_B220','transf','message','rowcnt','iy','msg','MAXROWCNT','SVCNAME','SQLCODE','SQLCNT','NOTFOUND','TOOMANY'}

def validate_filename(value):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]{0,100}\.pc',value) or '..' in value:raise ValueError('출력 파일명은 경로 없는 영문/숫자/밑줄의 .pc 파일명이어야 합니다.')
    if value.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:raise ValueError('Windows 예약 파일명입니다.')
    return value

def select_parts(sql):
    tokens=tokenize(sql)
    if not tokens or tokens[0].upper!='SELECT' or tokens[0].kind!='word':raise ValueError('조회용 생성기는 SELECT로 시작하는 단일 SQL만 지원합니다. WITH/PLSQL/다중 SQL은 수동 검토하세요.')
    if any(t.text==';' and i!=len(tokens)-1 for i,t in enumerate(tokens)):raise ValueError('여러 SQL 문장을 포함할 수 없습니다.')
    root=[t for t in tokens if t.depth==0 and t.kind=='word']
    if any(t.upper in {'UNION','INTERSECT','MINUS','FETCH','OFFSET','MODEL','MATCH_RECOGNIZE'} for t in root):raise ValueError('이 SQL 구조는 안전하게 INTO를 변환할 수 없습니다. 집합/확장 구문을 단순화하세요.')
    if any(root[i].upper=='FOR' and i+1<len(root) and root[i+1].upper=='UPDATE' for i in range(len(root))):raise ValueError('조회용 생성기는 FOR UPDATE 잠금 SQL을 지원하지 않습니다.')
    if any(line.lstrip().startswith('#') for line in sql.splitlines()):raise ValueError('SQL 안에 C 전처리 지시문을 넣을 수 없습니다.')
    from_token=next((t for t in root if t.upper=='FROM'),None)
    if not from_token:raise ValueError('최상위 FROM을 확인할 수 없습니다. 복잡한 SQL은 직접 검토하세요.')
    into=next((t for t in root if t.upper=='INTO' and t.start<from_token.start),None)
    existing=[t for t in tokens if into and into.end<=t.start<from_token.start]
    if into:
        if not existing:raise ValueError('기존 INTO 대상이 비어 있습니다.')
        bindings=parse_into_groups(existing)
        analysis_sql=sql[:into.start]+sql[from_token.start:]
    else:bindings=[];analysis_sql=sql
    return tokens,from_token,into,bindings,analysis_sql

def declared_type(v):
    if v.host_type=='asciz':
        choice=next(((n,name) for n,name in ASCIZ if n>=v.host_length),None)
    else:choice=next(((n,name) for n,name in ASCIZ if name==v.host_type),None)
    if not choice:raise ValueError(v.variable_name+': 샘플에서 확인한 asciz 선언만 지원합니다(최대 3000). 숫자 native 타입의 GET/PUT 서명은 미확인입니다.')
    capacity,name=choice
    if capacity<v.host_length:raise ValueError(v.variable_name+': asciz 선언 용량이 호스트 길이보다 작습니다.')
    if v.db_type.upper() in {'VARCHAR2','CHAR','VARCHAR','NCHAR','NVARCHAR2'} and v.db_length and v.host_length<v.db_length:raise ValueError(v.variable_name+': DB/결과 문자열 길이보다 호스트 길이가 짧습니다.')
    if v.db_type.upper() in {'NUMBER','NUMERIC','DECIMAL'}:
        if v.precision is None or v.scale is None:raise ValueError(v.variable_name+': NUMBER 정밀도/스케일을 확정하세요.')
        if capacity<max(v.precision+max(0,-v.scale)+3,v.scale+3):raise ValueError(v.variable_name+': NUMBER 문자열 선언 길이가 부족합니다.')
    if v.db_type.upper() not in {'VARCHAR2','CHAR','VARCHAR','NCHAR','NVARCHAR2','DATE','TIMESTAMP','NUMBER','NUMERIC','DECIMAL','INTEGER','INT','SMALLINT','FLOAT','BINARY_FLOAT','BINARY_DOUBLE'}:raise ValueError(v.variable_name+': 이 템플릿에서 확인하지 않은 DB 타입입니다.')
    return name,capacity

def choose_indicator(value,variable,used):
    name=value or 'n_'+variable[:60]
    if not value and name in used:name='n_'+variable[:49]+'_'+hashlib.sha256(variable.encode()).hexdigest()[:8]
    if not re.fullmatch(IDENT,name) or name in used or re.fullmatch(r'S_(?:TYPE|STRING)\d+',name):raise ValueError('NULL 지시 변수명이 충돌하거나 올바르지 않습니다: '+name)
    used.add(name);return name

def enclosing_functions(tokens):
    stack=[];result={}
    for i,t in enumerate(tokens):
        if t.text=='(':stack.append(tokens[i-1].upper if i and tokens[i-1].kind=='word' else '')
        elif t.text==')':
            if stack:stack.pop()
        elif t.kind=='bind':result[t.start]=set(stack)
    return result

def generate_select(service):
    errors=[];warnings=[
        '실제 Pro*C 컴파일·Tmax 실행 미검증. 검증 전 운영 배포 불가.',
        'global.h/oravar, SVCNAME·SQLCNT·NOTFOUND·TOOMANY·메시지 코드 및 FML 필드 정의가 필요합니다.',
        'GET/PUT 매크로 내부 오류 반환·버퍼 길이 검증은 헤더가 없어 확인하지 못했습니다. 호출 형식만 샘플과 일치합니다.',
        'SELECT_ERROR=YES 및 프로젝트 Pro*C 선언/배열 옵션을 확인해야 초과 건수를 오류로 구분할 수 있습니다.',
        'NULL 지시 배열은 Oracle 공식 문서를 따른 확장입니다. 출력 NULL은 빈 문자열로 전달하므로 NULL/빈 문자열 구분은 보존하지 않습니다.'
    ]
    try:
        if service.type!='select':raise ValueError('이번 생성기는 조회용 서비스만 지원합니다.')
        if not service.service_id:raise ValueError('기본정보에서 서비스 ID를 입력하세요.')
        if len(service.sql_blocks)!=1:raise ValueError('조회 SQL 블록 하나가 필요합니다.')
        sql=service.sql_blocks[0].final_sql
        tokens,from_token,into,existing_into,analysis_sql=select_parts(sql)
        inputs=[v for v in service.variables if v.role=='IN'];outputs=[v for v in service.variables if v.role=='OUT']
        if len(inputs)>10 or len(outputs)>100:raise ValueError('GET 10개 / PUT 100개 제한을 초과했습니다.')
        if not outputs:raise ValueError('출력 PUT 매핑이 필요합니다.')
        if any(not v.is_active for v in service.variables):raise ValueError('SQL에서 미사용으로 보관한 매핑이 있습니다. 동기화 미리보기에서 삭제 여부를 확인해 정리하세요.')
        if any(v.mapping_status=='unmapped' for v in service.variables):raise ValueError('확정되지 않은 매핑이 있습니다. SQL 전문 동기화를 완료하세요.')
        if any(not v.array for v in outputs):raise ValueError('다중 행 조회의 출력 매핑은 배열 옵션이 필요합니다.')
        if any(v.array for v in inputs):raise ValueError('GET 입력은 스칼라 호스트 변수를 사용하세요.')
        for role,group,prefix in [('IN',inputs,'S_TYPE'),('OUT',outputs,'S_STRING')]:
            if [v.field_name for v in group]!=[prefix+str(i) for i in range(1,len(group)+1)]:raise ValueError(role+': 저장된 전문 번호가 표시 순서와 다릅니다.')
        temporary=service.model_copy(deep=True);temporary.sql_blocks[0].final_sql=analysis_sql
        analysis=analyze_sql(temporary)
        if analysis['errors']:raise ValueError('\n'.join(analysis['errors']))
        warnings.extend(analysis['warnings'])
        if len(analysis['outputs'])!=len(outputs):raise ValueError('SELECT 결과 개수와 PUT 매핑 개수가 다릅니다. 전문 동기화가 필요합니다.')
        input_names={v.variable_name for v in inputs};actual={r['sql_bind_name'] for r in analysis['inputs']}
        if actual!=input_names:raise ValueError('SQL/GET 호스트 불일치. 미선언: '+', '.join(sorted(actual-input_names))+' / SQL 미사용: '+', '.join(sorted(input_names-actual)))
        ordered=[];used_outputs=set()
        for item in analysis['outputs']:
            matches=[v for v in outputs if v.mapping_id not in used_outputs and v.output_alias and v.output_alias.upper()==item['output_alias'].upper()]
            if not matches:matches=[v for v in outputs if v.mapping_id not in used_outputs and v.source_expression and normalize_expression(v.source_expression)==normalize_expression(item['expression'])]
            if len(matches)!=1:raise ValueError('SELECT 결과와 PUT 매핑을 유일하게 연결할 수 없습니다: '+(item['output_alias'] or item['expression']))
            v=matches[0]
            if not v.source_expression or normalize_expression(v.source_expression)!=normalize_expression(item['expression']):raise ValueError(v.variable_name+': SELECT 식이 변경되었습니다. 전문 동기화를 실행하세요.')
            if v.db_type.upper() in {'DATE','TIMESTAMP'} and not any(t.upper=='TO_CHAR' for t in tokenize(item['expression'])):raise ValueError(v.variable_name+': DATE 출력은 최종 SQL에 TO_CHAR 포맷을 명시하세요.')
            if item['metadata'] is None:
                if v.mapping_status!='confirmed':raise ValueError(v.variable_name+': 복잡한 식의 자료형을 먼저 사용자 확정하세요.')
                warnings.append(v.variable_name+': 계산식/서브쿼리의 결과 자료형은 사용자 확정값을 사용합니다. Oracle 의미 검증은 미실행입니다.')
            used_outputs.add(v.mapping_id);ordered.append(v)
        if into and [t.text for t,_ in existing_into]!=[v.variable_name for v in ordered]:raise ValueError('기존 INTO 호스트 순서와 SELECT/PUT 매핑이 다릅니다.')
        # Require a sync after substantive edits; a verified existing INTO is allowed.
        if not into and service.mapping_sql_fingerprint!=sql_fingerprint(sql):raise ValueError('최종 SQL이 변경되었거나 전문이 동기화되지 않았습니다. Tmax 전문 매핑에서 확인 반영하세요.')
        used=set(FIXED_NAMES)
        for v in service.variables:
            if v.variable_name in used or re.fullmatch(r'S_(?:TYPE|STRING)\d+',v.variable_name):raise ValueError('고정/중복 변수명 충돌: '+v.variable_name)
            used.add(v.variable_name)
        indicators,indicator_starts=indicator_bindings(tokens);functions=enclosing_functions(tokens)
        input_definitions=[];output_definitions=[];indicator_by_name={};estimated=0
        for v in inputs:
            declaration,capacity=declared_type(v)
            occurrences=[t for t in tokens if t.kind=='bind' and t.text==v.variable_name and t.start not in indicator_starts and not (into and into.start<t.start<from_token.start)]
            if v.db_type.upper() in {'DATE','TIMESTAMP'} and any(not functions.get(t.start,set())&{'TO_DATE','TO_TIMESTAMP'} for t in occurrences):raise ValueError(v.variable_name+': DATE 입력은 최종 SQL에 TO_DATE/TO_TIMESTAMP 변환을 명시하세요.')
            actual_indicator=indicators.get(v.variable_name,'')
            if v.null_indicator and actual_indicator and v.null_indicator!=actual_indicator:raise ValueError(v.variable_name+': SQL NULL 지시 변수와 매핑이 다릅니다.')
            indicator=choose_indicator(v.null_indicator or actual_indicator,v.variable_name,used) if v.null_indicator or actual_indicator else ''
            if indicator:indicator_by_name[v.variable_name]=indicator;warnings.append(v.variable_name+': 입력 NULL 지시 변수는 0으로 초기화합니다. Tmax 필드 NULL/누락 정책은 GET 정의 확인이 필요합니다.')
            input_definitions.append(dict(name=v.variable_name,field=v.field_name,declaration=declaration,indicator=indicator));estimated+=capacity+1
        for v in outputs:
            declaration,capacity=declared_type(v)
            actual_indicator=next((indicator for token,indicator in existing_into if token.text==v.variable_name),'')
            if v.null_indicator and actual_indicator and v.null_indicator!=actual_indicator:raise ValueError(v.variable_name+': 기존 INTO NULL 지시 변수와 매핑이 다릅니다.')
            indicator=choose_indicator(v.null_indicator or actual_indicator,v.variable_name,used);indicator_by_name[v.variable_name]=indicator
            output_definitions.append(dict(name=v.variable_name,field=v.field_name,declaration=declaration,indicator=indicator));estimated+=(capacity+3)*service.max_row_count
        if estimated>16*1024*1024:raise ValueError('배열 선언 예상 크기가 16MiB를 초과합니다. MAXROWCNT 또는 호스트 길이를 줄이세요.')
        warnings.append('문자 배열/지시 변수 예상 크기: '+str(estimated)+'바이트. 실제 sizeof/스택 한도는 운영 정의를 확인하세요.')
        if len(inputs)>2 or len(outputs)>8:warnings.append('샘플에 없는 추가 S_TYPE/S_STRING 번호의 FML 필드 정의를 확인하세요.')
        if any(v.db_type.upper() in {'NUMBER','NUMERIC','DECIMAL','INTEGER','INT','FLOAT'} for v in service.variables):warnings.append('NUMBER는 이름 접두어와 무관하게 문자열 asciz로 전달합니다. SQL/Oracle 숫자 변환과 NLS를 확인하세요.')
        changes=[]
        if into:
            for token,indicator in existing_into:
                if not indicator:changes.append((token.end,token.end,':'+indicator_by_name[token.text]))
        else:
            target=',\n     '.join(':'+v.variable_name+':'+indicator_by_name[v.variable_name] for v in ordered)
            changes.append((from_token.start,from_token.start,'\nINTO '+target+'\n'))
        for t in tokens:
            if t.kind=='bind' and t.text in input_names and t.start not in indicator_starts and t.text in indicator_by_name and t.text not in indicators:changes.append((t.end,t.end,':'+indicator_by_name[t.text]))
        embedded=sql
        for start,end,replacement in sorted(changes,key=lambda c:c[0],reverse=True):embedded=embedded[:start]+replacement+embedded[end:]
        final_tokens=tokenize(embedded)
        if final_tokens[-1].text==';':
            t=final_tokens[-1];embedded=embedded[:t.start]+embedded[t.end:]
        embedded=embedded.rstrip()+'\n;'
        environment=Environment(loader=FileSystemLoader(ROOT/'templates'),undefined=StrictUndefined,autoescape=False,keep_trailing_newline=True,trim_blocks=True,lstrip_blocks=True)
        template_path=ROOT/'templates/select.pc.j2';template_bytes=template_path.read_bytes();template_sha=hashlib.sha256(template_bytes).hexdigest();template_body=template_bytes.decode('utf-8-sig')
        source=environment.from_string(template_body).render(template_version=TEMPLATE_VERSION,service_id=service.service_id,max_row_count=service.max_row_count,inputs=input_definitions,outputs=output_definitions,embedded_sql=embedded)
        filename=validate_filename(service.proc_settings.filename or service.service_id.lower()+'.pc')
        try:encoded=source.encode(service.proc_settings.encoding)
        except UnicodeEncodeError as exc:raise ValueError('선택한 인코딩으로 저장할 수 없는 문자가 있습니다. UTF-8을 선택하세요.') from exc
        return dict(source=source,filename=filename,encoding=service.proc_settings.encoding,sha256=hashlib.sha256(encoded).hexdigest(),template_id=TEMPLATE_ID,template_version=TEMPLATE_VERSION,template_sha256=template_sha,embedded_sql=embedded,warnings=list(dict.fromkeys(warnings)),errors=[],compiled=False,estimated_buffer_bytes=estimated,_template_body=template_body,declarations={'inputs':input_definitions,'outputs':output_definitions},sql_output_order=[v.variable_name for v in ordered])
    except ValueError as exc:
        errors.append(str(exc));return dict(source='',filename='',encoding=service.proc_settings.encoding,errors=errors,warnings=list(dict.fromkeys(warnings)),compiled=False)
