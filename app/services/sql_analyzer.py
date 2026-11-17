"""Small Oracle-aware lexer and conservative SELECT projection analysis.
This is a token analyzer, not an Oracle semantic compiler. Unknown expressions
remain unmapped and require explicit type/source confirmation.
"""
from dataclasses import dataclass
import re
from app.models import Column
from app.services.sql_sources import column_catalog

@dataclass
class Token:
    text:str
    kind:str
    start:int
    end:int
    depth:int=0
    @property
    def upper(self):return self.text.upper()

def tokenize(sql):
    tokens=[];i=0;depth=0;n=len(sql)
    while i<n:
        ch=sql[i];start=i
        if ch.isspace():i+=1;continue
        if sql.startswith('--',i):
            j=sql.find('\n',i+2);i=n if j<0 else j+1;continue
        if sql.startswith('/*',i):
            j=sql.find('*/',i+2)
            if j<0:raise ValueError('닫히지 않은 SQL 주석입니다.')
            i=j+2;continue
        if ch.lower()=='q' and i+2<n and sql[i+1]=="'":
            opening=sql[i+2];closing={'[':']','{':'}','(':')','<':'>'}.get(opening,opening)
            j=sql.find(closing+"'",i+3)
            if j<0:raise ValueError('닫히지 않은 Oracle q 문자열입니다.')
            i=j+2;tokens.append(Token(sql[start:i],'string',start,i,depth));continue
        if ch in "'\"":
            quote=ch;i+=1
            while i<n:
                if sql[i]==quote:
                    if i+1<n and sql[i+1]==quote:i+=2;continue
                    i+=1;break
                i+=1
            else:raise ValueError('닫히지 않은 SQL 문자열/식별자입니다.')
            tokens.append(Token(sql[start:i],'string' if quote=="'" else 'quoted',start,i,depth));continue
        if sql.startswith(':=',i) or sql.startswith('::',i):
            i+=2;tokens.append(Token(sql[start:i],'symbol',start,i,depth));continue
        if ch==':':
            m=re.match(r':[A-Za-z_][A-Za-z0-9_]*',sql[i:])
            if not m:raise ValueError('지원하지 않는 바인드 표기입니다. :변수명 형식을 사용하세요.')
            i+=len(m[0]);tokens.append(Token(m[0][1:],'bind',start,i,depth));continue
        if ch.isalpha() or ch=='_':
            i+=1
            while i<n and (sql[i].isalnum() or sql[i] in '_$#'):i+=1
            tokens.append(Token(sql[start:i],'word',start,i,depth));continue
        if ch.isdigit():
            m=re.match(r'\d+(?:\.\d+)?(?:[eE][+-]?\d+)?',sql[i:]);i+=len(m[0]);tokens.append(Token(m[0],'number',start,i,depth));continue
        if ch=='(':tokens.append(Token(ch,'symbol',i,i+1,depth));depth+=1;i+=1;continue
        if ch==')':
            depth-=1
            if depth<0:raise ValueError('SQL 괄호가 맞지 않습니다.')
        if sql[i:i+2] in {'<=','>=','<>','!=','||'}:i+=2
        else:i+=1
        tokens.append(Token(sql[start:i],'symbol',start,i,depth))
    if depth:raise ValueError('SQL 괄호가 맞지 않습니다.')
    return tokens

def indicator_bindings(tokens):
    relations={};indicator_starts=set()
    for i,t in enumerate(tokens):
        if t.kind!='bind':continue
        host=None
        if i and tokens[i-1].kind=='bind' and tokens[i-1].start not in indicator_starts:host=tokens[i-1].text
        elif i>=2 and tokens[i-1].upper=='INDICATOR' and tokens[i-2].kind=='bind':host=tokens[i-2].text
        if host:
            if host in relations and relations[host]!=t.text:raise ValueError('동일 호스트 변수의 NULL 지시 변수가 다릅니다: '+host)
            relations[host]=t.text;indicator_starts.add(t.start)
    return relations,indicator_starts

def parse_into_groups(tokens):
    groups=[];current=[]
    for t in tokens:
        if t.text==',':groups.append(current);current=[]
        else:current.append(t)
    if current:groups.append(current)
    bindings=[]
    for group in groups:
        valid=(len(group)==1 and group[0].kind=='bind') or (len(group)==2 and all(t.kind=='bind' for t in group)) or (len(group)==3 and group[0].kind=='bind' and group[1].upper=='INDICATOR' and group[2].kind=='bind')
        if not valid:raise ValueError('INTO는 단순 호스트 변수/NULL 지시 변수 목록이어야 합니다.')
        bindings.append((group[0],group[-1].text if len(group)>1 else ''))
    if not bindings:raise ValueError('INTO 대상이 비어 있습니다.')
    if len({t.text for t,_ in bindings})!=len(bindings):raise ValueError('INTO 출력 호스트 변수가 중복됩니다.')
    return bindings

def split_items(tokens,depth):
    groups=[];current=[]
    for t in tokens:
        if t.text==',' and t.depth==depth:groups.append(current);current=[]
        else:current.append(t)
    if current:groups.append(current)
    return groups

def normalize_expression(expression):
    return ' '.join(t.upper if t.kind=='word' else t.text for t in tokenize(expression))

def source_resolver(service,tokens):
    catalog=column_catalog(service);qualified={};bare={};warnings=[]
    for key,(column,alias) in catalog.items():
        if '.' not in key:
            for qualifier in filter(None,[alias,service.table_name]):qualified[(qualifier.upper(),column.name.upper())]=key
        else:qualified[(alias.upper(),column.name.upper())]=key
        bare.setdefault(column.name.upper(),[]).append(key)
    # Recognize aliases typed in a simple FROM/JOIN; refuse unknown source tables.
    unknown_source=False
    sources=[(service.owner,service.table_name,'')]+[(j.owner,j.table_name,j.alias+'.') for j in service.join_tables]
    for i,t in enumerate(tokens):
        if t.upper not in {'FROM','JOIN','UPDATE','INTO'} or t.kind!='word':continue
        if t.upper=='INTO' and tokens[0].upper!='INSERT':continue
        if t.upper=='FROM' and not any(x.upper=='SELECT' and x.depth==t.depth for x in tokens[:i]):continue
        if i+1>=len(tokens):continue
        if tokens[i+1].text=='(':
            unknown_source=True;warnings.append('FROM 서브쿼리는 자료형을 자동 확정하지 않습니다.');continue
        parts=[tokens[i+1].text];j=i+2
        if j+1<len(tokens) and tokens[j].text=='.':parts.append(tokens[j+1].text);j+=2
        table=parts[-1].upper();owner=parts[0].upper() if len(parts)>1 else ''
        matches=[s for s in sources if s[1].upper()==table and (not owner or s[0].upper()==owner)]
        if not matches:unknown_source=True;warnings.append('서비스 정의에 없는 SQL 테이블: '+'.'.join(parts));continue
        if j<len(tokens) and tokens[j].upper=='AS':j+=1
        if j<len(tokens) and tokens[j].kind=='word' and tokens[j].upper not in {'WHERE','INNER','LEFT','RIGHT','FULL','JOIN','ON','GROUP','ORDER','HAVING','SET','VALUES','UNION','FETCH','OFFSET','CONNECT','START'}:
            alias=tokens[j].upper
            if len(matches)==1:
                prefix=matches[0][2]
                for key,(column,_) in catalog.items():
                    if (key.startswith(prefix) if prefix else '.' not in key):qualified[(alias,column.name.upper())]=key
    def resolve(group):
        if unknown_source:return None
        if len(group)==1 and group[0].kind in {'word','quoted'}:
            name=group[0].text.strip('"').upper();matches=bare.get(name,[])
            return matches[0] if len(matches)==1 else None
        if len(group)==3 and group[1].text=='.':return qualified.get((group[0].text.strip('"').upper(),group[2].text.strip('"').upper()))
        return None
    return catalog,resolve,warnings

def references(tokens,resolve,unique=True):
    result=[];i=0
    while i<len(tokens):
        if i+2<len(tokens) and tokens[i+1].text=='.':key=resolve(tokens[i:i+3]);i+=3
        else:
            key=None if i+1<len(tokens) and tokens[i+1].text=='(' and tokens[i].kind=='word' else resolve(tokens[i:i+1]);i+=1
        if key and (not unique or key not in result):result.append(key)
    return result

def infer_projection(group,sql,catalog,resolve,position):
    alias='';expr=group[:]
    if not expr:raise ValueError('빈 SELECT 컬럼입니다.')
    level=expr[0].depth
    as_positions=[i for i,t in enumerate(expr) if t.upper=='AS' and t.depth==level]
    if as_positions:
        i=as_positions[-1]
        if i!=len(expr)-2:raise ValueError('출력 별칭 구문을 확인하세요.')
        alias=expr[-1].text.strip('"');expr=expr[:i]
    elif len(expr)>1 and expr[-1].kind in {'word','quoted'} and expr[-2].text not in {'.','+','-','*','/','||'} and expr[-2].upper not in {'END','DISTINCT'}:
        # A direct qualified reference (a.X) is not an alias.
        if resolve(expr) is None:alias=expr[-1].text.strip('"');expr=expr[:-1]
    key=resolve(expr);column=catalog[key][0] if key else None
    expression=sql[expr[0].start:expr[-1].end]
    refs=references(expr,resolve)
    if key:alias=alias or column.name
    else:
        function=expr[0].upper
        if function=='TO_CHAR' and len(expr)>2:
            literals=[t for t in expr if t.kind=='string']
            if literals:
                try:
                    from app.services.host_validation import date_width
                    width=date_width(literals[-1].text[1:-1])
                    if width:column=Column(name='EXPRESSION',db_type='VARCHAR2',length=width,comment='문자열 변환식')
                except ValueError:pass
            # Numeric/NLS or dynamic formats require explicit result-length confirmation.
        elif function=='COUNT':column=Column(name='EXPRESSION',db_type='NUMBER',precision=38,scale=0,length=64,nullable=False,comment='집계 COUNT')
        elif function in {'MIN','MAX','SUM'} and len(refs)==1:
            base=catalog[refs[0]][0]
            if function in {'MIN','MAX'}:column=base.model_copy(update={'nullable':True})
            elif base.db_type.upper() in {'NUMBER','INTEGER','INT','FLOAT'}:column=base.model_copy(update={'precision':38,'length':max(64,base.length),'nullable':True})
        elif function=='AVG':column=None # Oracle precision depends on expression; require explicit confirmation.
        elif len(expr)==1 and expr[0].kind=='string':column=Column(name='EXPRESSION',length=max(1,len(expr[0].text)-2),comment='문자 리터럴')
        elif len(expr)==1 and expr[0].kind=='number':
            value=expr[0].text
            if 'E' not in value.upper():column=Column(name='EXPRESSION',db_type='NUMBER',precision=min(38,len(value.replace('.',''))),scale=len(value.split('.')[1]) if '.' in value else 0,length=64,comment='숫자 리터럴')
        elif refs and any(t.text in {'+','-','*','/'} for t in expr):
            bases=[catalog[k][0] for k in refs]
            known_words=set()
            for index,t in enumerate(expr):
                if t.kind in {'word','quoted'} and (resolve(expr[index:index+1]) or (index+2<len(expr) and resolve(expr[index:index+3])) or (index>=2 and resolve(expr[index-2:index+1]))):known_words.add(index)
            pure=all(t.kind not in {'word','quoted'} or i in known_words for i,t in enumerate(expr))
            simple= len(references(expr,resolve,unique=False))==1 and all(t.kind!='number' or ('.' not in t.text and 'E' not in t.upper) for t in expr) and not any(t.kind=='word' and i+1<len(expr) and expr[i+1].text=='(' for i,t in enumerate(expr))
            if pure and simple and all(c.db_type.upper() in {'NUMBER','INTEGER','INT'} for c in bases) and not any(t.text=='/' for t in expr):
                column=Column(name='EXPRESSION',db_type='NUMBER',precision=38,scale=max(c.scale or 0 for c in bases),length=64,comment='숫자 계산식 (정밀도 검토 필요)')
    if column and len(refs)==1 and not key:column=column.model_copy(update={'comment':catalog[refs[0]][0].comment or column.comment})
    return dict(key=f'OUT:{position}',role='OUT',db_column=key or (refs[0] if len(refs)==1 else ''),expression=expression,output_alias=alias,position=position,metadata=column.model_dump() if column else None,source_references=refs,status='auto' if column and alias else 'unmapped',reason='' if column and alias else '계산식의 별칭 및 DB 자료형을 확인하세요.')

def analyze_sql(service):
    sql=service.sql_blocks[0].final_sql if service.sql_blocks else ''
    if len(sql)>200000:raise ValueError('SQL 분석은 200,000자 이하만 지원합니다.')
    if not sql.strip():raise ValueError('분석할 최종 SQL이 없습니다.')
    tokens=tokenize(sql);catalog,resolve,warnings=source_resolver(service,tokens);errors=[];outputs=[]
    if not tokens:raise ValueError('SQL 문장이 없습니다.')
    root=tokens[0].upper
    if root not in {'SELECT','WITH','INSERT','UPDATE','DELETE'}:errors.append('동기화는 SELECT/INSERT/UPDATE/DELETE 단일 SQL을 지원합니다. PL/SQL·다중 SQL은 수동 확인이 필요합니다.')
    semicolons=[i for i,t in enumerate(tokens) if t.text==';']
    if any(i!=len(tokens)-1 for i in semicolons):errors.append('여러 SQL 문장을 한 번에 동기화하지 않습니다.')
    into_range=None;into_bindings=[]
    select=next((i for i,t in enumerate(tokens) if t.upper=='SELECT' and t.depth==0),None)
    if root in {'SELECT','WITH'} and select is not None:
        end=next((i for i in range(select+1,len(tokens)) if tokens[i].depth==0 and tokens[i].upper=='FROM'),len(tokens))
        into_index=next((i for i in range(select+1,end) if tokens[i].depth==0 and tokens[i].upper=='INTO'),None)
        if into_index is not None:
            into_bindings=parse_into_groups(tokens[into_index+1:end]);into_range=(tokens[into_index].start,tokens[end].start if end<len(tokens) else len(sql))
        projection=tokens[select+1:into_index if into_index is not None else end]
        if not projection:errors.append('SELECT 결과 컬럼이 비어 있습니다.')
        if projection and projection[0].upper in {'DISTINCT','ALL'}:projection=projection[1:]

        if any(t.upper in {'UNION','INTERSECT','MINUS'} and t.depth==0 for t in tokens):errors.append('집합 연산 SQL은 이 단계에서 수동 매핑해야 합니다.')
        for group in split_items(projection,0):
            if group and group[-1].text==';':group=group[:-1]
            wildcard=len(group)==1 and group[0].text=='*'
            qualified_star=len(group)==3 and group[1].text=='.' and group[2].text=='*'
            if wildcard or qualified_star:
                if warnings:
                    errors.append('출처가 확인되지 않은 FROM의 *는 확장할 수 없습니다. 서비스 테이블 정의와 SQL을 확인하세요.');continue
                for key,(column,alias) in catalog.items():
                    if qualified_star and group[0].upper not in {alias.upper(),service.table_name.upper() if '.' not in key else ''}:continue
                    outputs.append(dict(key=f'OUT:{len(outputs)+1}',role='OUT',db_column=key,expression=(alias+'.' if alias else '')+column.name,output_alias=column.name,position=len(outputs)+1,metadata=column.model_dump(),source_references=[key],status='auto',reason=''))
            elif group:outputs.append(infer_projection(group,sql,catalog,resolve,len(outputs)+1))
    if into_bindings:
        if len(into_bindings)!=len(outputs):errors.append('SELECT 결과와 기존 INTO 호스트 개수가 다릅니다.')
        else:
            for item,(target,indicator) in zip(outputs,into_bindings):
                item['into_variable_name']=target.text;item['null_indicator']=indicator
                item['output_alias']=item['output_alias'] or target.text
                if item['metadata']:item['status']='auto';item['reason']=''
    aliases=[x['output_alias'].upper() for x in outputs if x['output_alias']]
    if len(aliases)!=len(set(aliases)):errors.append('SELECT 출력 별칭이 중복됩니다. 서로 다른 AS 별칭을 지정하세요.')
    indicators,indicator_starts=indicator_bindings(tokens)
    inputs=[];seen=set()
    for index,t in enumerate(tokens):
        if t.kind!='bind' or t.text in seen or t.start in indicator_starts or (into_range and into_range[0]<t.start<into_range[1]):continue
        seen.add(t.text);candidate=[]
        # Local predicate window, bounded by clause/boolean keywords and projection separators.
        left=index-1
        while left>=0 and index-left<=25 and tokens[left].upper not in {'WHERE','AND','OR','ON','HAVING','SELECT','SET','VALUES'} and tokens[left].text!=';':left-=1
        right=index+1
        while right<len(tokens) and right-index<=25 and tokens[right].upper not in {'AND','OR','GROUP','ORDER','WHERE','HAVING'} and tokens[right].text!=';':right+=1
        candidate=references(tokens[left+1:right],resolve)
        key=candidate[0] if len(candidate)==1 else ''
        existing=next((v for v in service.variables if v.role=='IN' and v.variable_name==t.text),None)
        if existing and existing.db_column in catalog:key=existing.db_column
        if not key:
            from app.services.mapping_service import variable_name
            candidates=[]
            for ref,(column,alias) in catalog.items():
                try:
                    naming=column.model_copy(update={'name':alias+'_'+column.name}) if '.' in ref else column
                    if variable_name(naming)==t.text:candidates.append(ref)
                except ValueError:pass
            if len(candidates)==1:key=candidates[0]
        column=catalog[key][0] if key else None
        inputs.append(dict(key='IN:'+t.text,role='IN',sql_bind_name=t.text,null_indicator=indicators.get(t.text,''),db_column=key,expression=':'+t.text,output_alias='',position=len(inputs)+1,metadata=column.model_dump() if column else None,source_references=[key] if key else [],status='auto' if column else 'unmapped',reason='' if column else '입력 바인드의 컬럼/자료형을 확인하세요.'))
    if {r['sql_bind_name'] for r in inputs}&{t.text for t,_ in into_bindings}:errors.append('입력과 기존 INTO에서 같은 호스트를 공유할 수 없습니다. 조회 배열 출력 변수명을 분리하세요.')
    if len(inputs)>10:errors.append('GET 입력 전문은 10개까지 가능합니다.')
    if len(outputs)>100:errors.append('PUT 출력 전문은 100개까지 가능합니다.')
    return dict(inputs=inputs,outputs=outputs,warnings=list(dict.fromkeys(warnings)),errors=errors,limitations='토큰 기반 정적 분석입니다. Oracle 실행·완전한 SQL 의미 분석은 수행하지 않습니다.')
