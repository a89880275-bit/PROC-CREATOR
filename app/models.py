from typing import Literal
import re
from uuid import uuid4
from pydantic import BaseModel, Field, model_validator

IDENT = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"
class Column(BaseModel):
    name: str = Field(pattern=IDENT)
    db_type: str = 'VARCHAR2'
    length: int = Field(default=20, ge=1, le=32767)
    precision: int | None = Field(default=None, ge=1, le=38)
    scale: int | None = Field(default=None, ge=-84, le=127)
    nullable: bool = True
    comment: str = ''
    primary_key: bool = False
    date_format: str = 'YYYY-MM-DD'
    data_default: str = ''
    raw_data_type: str = ''
    column_id: int = Field(default=0, ge=0)
class Variable(BaseModel):
    mapping_id: str = Field(default_factory=lambda:uuid4().hex)
    column_comment: str = ''
    db_length: int | None = None
    nullable: bool = True
    source_expression: str = ''
    output_alias: str = ''
    sql_bind_name: str = ''
    mapping_status: Literal['auto','confirmed','unmapped'] = 'auto'
    is_active: bool = True
    order_manual: bool = False
    source_position: int = 0
    precision: int | None = None
    scale: int | None = None
    date_format: str = 'YYYY-MM-DD'
    db_column: str
    db_type: str = 'VARCHAR2'
    variable_name: str = Field(pattern=IDENT)
    role: Literal['IN','OUT']
    host_type: str = 'asciz'
    host_length: int = Field(default=20, ge=1, le=32767)
    is_manual: bool = False
    field_name: str = ''
    array: bool = False
    null_indicator: str = ''
class Block(BaseModel):
    block_type: Literal['SELECT','INSERT','UPDATE','DELETE'] = 'SELECT'
    generated_sql: str = ''
    final_sql: str = ''
    is_manual: bool = False
    error_policy: str = 'stop'
class JoinCondition(BaseModel):
    left_column: str = Field(pattern=IDENT)
    operator: Literal['=','<>','>','>=','<','<='] = '='
    right_column: str = Field(pattern=IDENT)
class JoinTable(BaseModel):
    owner: str = ''
    table_name: str = Field(pattern=IDENT)
    alias: str = Field(default='b',pattern=IDENT)
    join_type: Literal['INNER','LEFT','RIGHT','FULL'] = 'INNER'
    columns: list[Column] = Field(default_factory=list,max_length=200)
    conditions: list[JoinCondition] = Field(default_factory=list,max_length=10)
    dictionary_revision: int = 0
    @model_validator(mode='after')
    def validate_table(self):
        if self.owner and not re.fullmatch(IDENT,self.owner): raise ValueError('조인 테이블 소유자가 올바르지 않습니다.')
        if len({c.name.upper() for c in self.columns})!=len(self.columns): raise ValueError('조인 테이블 컬럼명이 중복됩니다.')
        return self

class ProcSettings(BaseModel):
    filename: str = ''
    encoding: Literal['utf-8','cp949'] = 'utf-8'
    null_policy: Literal['empty'] = 'empty'

class Service(BaseModel):
    service_id: str = Field(pattern=IDENT)
    name: str = ''
    type: Literal['select','transaction'] = 'select'
    description: str = ''
    table_name: str = Field(default='SAMPLE_TABLE', pattern=IDENT)
    owner: str = ''
    table_alias: str = ''
    dictionary_revision: int = 0
    join_tables: list[JoinTable] = Field(default_factory=list,max_length=1)
    proc_settings: ProcSettings = Field(default_factory=ProcSettings)
    mapping_sql_fingerprint: str = ''
    builder_state: dict = Field(default_factory=dict)
    max_row_count: int = Field(default=1000, ge=1, le=100000)
    template_id: str = 'select'
    current_version: int = Field(default=0, ge=0)
    columns: list[Column] = Field(default_factory=list, max_length=200)
    variables: list[Variable] = Field(default_factory=list, max_length=110)
    sql_blocks: list[Block] = Field(default_factory=lambda:[Block()], max_length=1)
    @model_validator(mode='after')
    def validate_all(self):
        if self.owner and not re.fullmatch(IDENT, self.owner):
            raise ValueError('소유자 식별자가 올바르지 않습니다.')
        if self.table_alias and not re.fullmatch(IDENT, self.table_alias):
            raise ValueError('테이블 별칭이 올바르지 않습니다.')
        if self.join_tables and self.join_tables[0].alias.lower()==(self.table_alias or 'a').lower():
            raise ValueError('메인/조인 테이블 별칭이 중복됩니다.')
        names = [c.name.upper() for c in self.columns]
        if len(names) != len(set(names)):
            raise ValueError('중복 컬럼명입니다.')
        if len({v.mapping_id for v in self.variables})!=len(self.variables):raise ValueError('매핑 ID가 중복됩니다.')
        names = [v.variable_name for v in self.variables]
        if len(names) != len(set(names)):
            raise ValueError('호스트 변수명이 충돌합니다. 직접 수정하세요.')
        reserved = {'int','char','double','float','return','for','if','while','switch','void','static','struct','transf','message','rowcnt','msg'}
        for v in self.variables:
            if v.variable_name in reserved:
                raise ValueError('예약된 호스트 변수명입니다: '+v.variable_name)
        for role, limit, prefix in [('IN',10,'S_TYPE'),('OUT',100,'S_STRING')]:
            group = [v for v in self.variables if v.role == role]
            if len(group)>limit:
                raise ValueError(f'{role} 전문은 {limit}개까지 가능합니다.')
            for i,v in enumerate(group,1):
                v.field_name = prefix+str(i)
        return self


class SQLDraft(Service):
    """Unsaved SQL definitions may omit the ID required for persistent services."""
    service_id: str = Field(default='', pattern=r"^(?:[A-Za-z_][A-Za-z0-9_]{0,63})?$")
