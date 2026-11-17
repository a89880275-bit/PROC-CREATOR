import re
from pydantic import BaseModel, Field, field_validator
from typing import Literal
from app.models import SQLDraft, Service
from app.services.sql_sources import column_catalog, validate_join

class Condition(BaseModel):
    column: str
    operator: Literal['=','<>','>','>=','<','<=','LIKE','IS NULL','IS NOT NULL'] = '='
    connector: Literal['AND','OR'] = 'AND'
class SQLRequest(BaseModel):
    service: SQLDraft
    @field_validator('service', mode='before')
    @classmethod
    def accept_saved_service(cls, value):
        return value.model_dump() if isinstance(value, Service) else value
    operation: Literal['SELECT','INSERT','UPDATE','DELETE']
    selected: list[str] = Field(default_factory=list)
    conditions: list[Condition] = Field(default_factory=list)
    order_by: list[str] = Field(default_factory=list)
    allow_full_table: bool = False

def generate(r: SQLRequest):
    s=r.service
    from app.services.host_validation import host_warnings, date_width
    host_warnings(s)
    validate_join(s,r.operation)
    catalog=column_catalog(s)
    cols={key:entry[0] for key,entry in catalog.items()}
    binds={v.db_column:v.variable_name for v in s.variables if v.role=='IN'}
    def col(n):
        if n not in cols: raise ValueError('등록되지 않은 컬럼: '+n)
        c,alias=catalog[n]
        return (alias+'.' if alias else '')+c.name
    def bind(n):
        if n not in binds: raise ValueError('입력 매핑이 필요합니다: '+n)
        c=cols[n]; b=':'+binds[n]
        if c.db_type.upper() in {'DATE','TIMESTAMP'}:
            date_width(c.date_format)
            if not re.fullmatch(r'[A-Za-z0-9 /:.\-]+',c.date_format): raise ValueError('날짜 형식을 확인하세요.')
            b=('TO_DATE' if c.db_type.upper()=='DATE' else 'TO_TIMESTAMP')+f"({b}, '{c.date_format}')"
        if c.db_type.upper() in {'NUMBER','NUMERIC','DECIMAL','INTEGER','INT','SMALLINT','FLOAT','BINARY_FLOAT','BINARY_DOUBLE'}:
            v=next(v for v in s.variables if v.role=='IN' and v.db_column==n)
            if v.host_type in {'asciz','char'}: b='TO_NUMBER('+b+')'
        return b
    table=(s.owner+'.' if s.owner else '')+s.table_name
    for n in r.selected: col(n)
    if len(r.selected)!=len(set(r.selected)):raise ValueError('중복 선택 컬럼입니다.')
    selected=r.selected
    main_alias=s.table_alias or ('a' if s.join_tables else '')
    from_table=table+(' '+main_alias if main_alias else '')
    for joined in s.join_tables:
        target=(joined.owner+'.' if joined.owner else '')+joined.table_name
        on=' AND '.join(main_alias+'.'+c.left_column+' '+c.operator+' '+joined.alias+'.'+c.right_column for c in joined.conditions)
        from_table+='\n'+joined.join_type+' JOIN '+target+' '+joined.alias+' ON '+on
    where=[]
    for c in r.conditions:
        term=col(c.column)+' '+c.operator
        if c.operator not in {'IS NULL','IS NOT NULL'}: term+=' '+bind(c.column)
        where.append((c.connector+' ' if where else '')+term)
    suffix='\nWHERE '+' '.join(where) if where else ''
    if r.operation in {'UPDATE','DELETE'} and not where and not r.allow_full_table:
        raise ValueError('조건 없는 UPDATE/DELETE는 차단됩니다. 전체 행 위험 확인이 필요합니다.')
    if r.operation=='SELECT':
        if not selected: raise ValueError('조회 컬럼을 선택하세요.')
        expressions=[]
        output_aliases=set()
        for n in selected:
            c=cols[n]
            if c.db_type.upper() in {'DATE','TIMESTAMP'}:
                date_width(c.date_format)
                if not re.fullmatch(r'[A-Za-z0-9 /:.\-]+',c.date_format): raise ValueError('날짜 형식을 확인하세요.')
                expression=f"TO_CHAR({col(n)}, '{c.date_format}')"
            else: expression=col(n)
            if s.join_tables:
                alias=catalog[n][1]+'_'+c.name
                if alias.upper() in output_aliases:raise ValueError('출력 별칭이 충돌합니다. 테이블 별칭을 변경하세요: '+alias)
                output_aliases.add(alias.upper())
                if len(alias)>64: raise ValueError('출력 컬럼 별칭이 너무 깁니다: '+alias)
                expression+=' AS '+alias
            elif c.db_type.upper() in {'DATE','TIMESTAMP'}: expression+=' AS '+n
            expressions.append(expression)
        query='SELECT '+', '.join(expressions)+'\nFROM '+from_table+suffix
        if r.order_by: query+='\nORDER BY '+', '.join(col(n) for n in r.order_by)
        return query+';'
    if r.operation=='DELETE': return 'DELETE FROM '+from_table+suffix+';'
    if not selected: raise ValueError('입력/수정 컬럼을 선택하세요.')
    if r.operation=='INSERT': return 'INSERT INTO '+table+' ('+', '.join(selected)+')\nVALUES ('+', '.join(bind(n) for n in selected)+');'
    return 'UPDATE '+from_table+'\nSET '+', '.join(n+' = '+bind(n) for n in selected)+suffix+';'
