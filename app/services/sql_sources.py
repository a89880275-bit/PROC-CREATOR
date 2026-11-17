"""Resolve column references to typed snapshots without flattening duplicate names."""
def column_catalog(service):
    main_alias=service.table_alias or ('a' if service.join_tables else '')
    outer_main=any(j.join_type in {'RIGHT','FULL'} for j in service.join_tables)
    catalog={c.name:(c.model_copy(update={'nullable':True}) if outer_main else c,main_alias) for c in service.columns}
    for joined in service.join_tables:
        for c in joined.columns:
            nullable=c.nullable or joined.join_type in {'LEFT','FULL'}
            catalog[joined.alias+'.'+c.name]=(c.model_copy(update={'nullable':nullable}),joined.alias)
    return catalog

def type_family(column):
    t=column.db_type.upper()
    if t in {'CHAR','VARCHAR2','VARCHAR','NCHAR','NVARCHAR2','CLOB'}:return '문자'
    if t in {'NUMBER','NUMERIC','DECIMAL','INTEGER','INT','SMALLINT','FLOAT','BINARY_FLOAT','BINARY_DOUBLE'}:return '숫자'
    if t in {'DATE','TIMESTAMP'}:return '날짜'
    return t

def validate_join(service,operation):
    if not service.join_tables:return
    if operation!='SELECT': raise ValueError('JOIN 자동 생성은 SELECT만 지원합니다. 수정 SQL은 조인 테이블을 해제하거나 직접 편집하세요.')
    main={c.name:c for c in service.columns}
    for joined in service.join_tables:
        if not joined.conditions:raise ValueError('JOIN 조건을 하나 이상 추가하세요. 메인 컬럼과 조인 컬럼을 선택해야 합니다.')
        columns={c.name:c for c in joined.columns}
        for condition in joined.conditions:
            if condition.left_column not in main or condition.right_column not in columns:raise ValueError('JOIN 조건에 등록되지 않은 컬럼이 있습니다.')
            if type_family(main[condition.left_column])!=type_family(columns[condition.right_column]):raise ValueError('JOIN 조건의 자료형이 다릅니다: '+condition.left_column+' / '+condition.right_column)
