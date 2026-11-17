import re
from app.models import Column, Variable

def variable_name(column: Column):
    t=column.db_type.upper().split('(')[0].strip()
    if t in {'NUMBER','NUMERIC','DECIMAL'}:
        if column.scale is None or column.precision is None:
            raise ValueError(f'{column.name}: NUMBER 정밀도/스케일을 확인하세요.')
        prefix='i' if column.scale<=0 else 'd'
    elif t in {'INTEGER','INT','SMALLINT'}: prefix='i'
    elif t in {'FLOAT','BINARY_FLOAT','BINARY_DOUBLE','DOUBLE'}: prefix='d'
    elif t in {'CHAR','VARCHAR2','VARCHAR','NCHAR','NVARCHAR2','CLOB','DATE','TIMESTAMP'}: prefix='s'
    else: raise ValueError(f'{column.name}: 미확인 DB 타입 {t}')
    base=re.sub('[^a-z0-9_]', '_', column.name.lower()).strip('_') or 'column'
    return prefix+base[0].upper()+base[1:]

def auto_mappings(columns, inputs, outputs):
    known={c.name:c for c in columns}
    result=[]
    if len(inputs)>10 or len(outputs)>100: raise ValueError('입력 10개 / 출력 100개 제한을 초과했습니다.')
    for role, names, prefix in [('IN',inputs,'S_TYPE'),('OUT',outputs,'S_STRING')]:
        for i,name in enumerate(names,1):
            if name not in known: raise ValueError('알 수 없는 컬럼: '+name)
            c=known[name]
            numeric=c.db_type.upper() in {'NUMBER','NUMERIC','DECIMAL'}
            length=max(c.length,64,(c.precision or 38)+max(0,-(c.scale or 0))+3,(c.scale or 0)+3) if numeric else c.length
            result.append(Variable(db_column=name, db_type=c.db_type, variable_name=variable_name(c)+('Out' if role=='OUT' else ''), role=role,host_length=length,field_name=prefix+str(i),array=role=='OUT',column_comment=c.comment,db_length=c.length,nullable=c.nullable,precision=c.precision,scale=c.scale,date_format=c.date_format,sql_bind_name=variable_name(c) if role=='IN' else '',output_alias=c.name if role=='OUT' else '',source_expression=c.name))
    if len({v.variable_name for v in result})!=len(result): raise ValueError('변수명 충돌: 직접 수정하세요.')
    return result
