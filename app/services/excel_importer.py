"""Read-only Excel metadata ingestion. Never evaluates cell formulas or defaults."""
from io import BytesIO
from zipfile import ZipFile, BadZipFile
import re
from openpyxl import load_workbook
from app.models import Column, IDENT
HEADERS=['TABLE_NAME','COMMENTS','TABLESPACE_NAME','COLUMN_ID','COLUMN_NAME','DATA_TYPE','KEY','NOTNULL','DATA_DEFAULT','COMMENTS_1']
MAX_BYTES=10*1024*1024

def text(v): return '' if v is None else str(v).strip()
def parse_type(raw):
    raw=text(raw).upper()
    m=re.fullmatch(r'(VARCHAR2|VARCHAR|CHAR|NCHAR|NVARCHAR2)\s*\(\s*(\d+)\s*(?:BYTE|CHAR)?\s*\)',raw)
    if m: return dict(db_type=m[1],length=int(m[2]),precision=None,scale=None)
    m=re.fullmatch(r'(NUMBER|NUMERIC|DECIMAL)(?:\s*\(\s*(\d+|\*)\s*(?:,\s*(-?\d+)\s*)?\))?',raw)
    if m:
        p=int(m[2]) if m[2] and m[2]!='*' else None
        return dict(db_type=m[1],length=64,precision=p,scale=int(m[3]) if m[3] else (0 if p else None))
    if raw in {'DATE','TIMESTAMP'} or re.fullmatch(r'TIMESTAMP\([0-9]\)',raw):
        return dict(db_type='DATE' if raw=='DATE' else 'TIMESTAMP',length=40 if raw.startswith('TIMESTAMP') else 19,precision=None,scale=None)
    if raw in {'INTEGER','INT','SMALLINT','FLOAT','BINARY_FLOAT','BINARY_DOUBLE','CLOB'}:
        return dict(db_type=raw,length=64 if raw!='CLOB' else 32767,precision=None,scale=None)
    raise ValueError('지원하지 않는 자료형: '+raw)

def read_excel(content):
    errors=[];warnings=[];tables={}; count=0
    if len(content)>MAX_BYTES: raise ValueError('Excel 파일은 10MB 이하만 허용합니다.')
    try:
        with ZipFile(BytesIO(content)) as z:
            if sum(x.file_size for x in z.infolist())>50*1024*1024 or len(z.infolist())>2000:
                raise ValueError('압축 해제 크기 또는 항목 제한을 초과했습니다.')
        workbook=load_workbook(BytesIO(content),read_only=True,data_only=False)
    except (BadZipFile,KeyError,OSError) as exc: raise ValueError('올바른 XLSX 파일이 아닙니다.') from exc
    try:
        for sheet in workbook:
            rows=sheet.iter_rows(values_only=False)
            first=next(rows,None)
            if not first or not any(c.value is not None for c in first): continue
            headers=[text(c.value).upper() for c in first]
            if not all(x in headers for x in HEADERS):
                errors.append(f'{sheet.title}: 필수 헤더가 없습니다.');continue
            if len(headers)!=len(set(headers)): errors.append(f'{sheet.title}: 중복 헤더입니다.');continue
            idx={h:headers.index(h) for h in HEADERS}; previous=''
            for rowno,row in enumerate(rows,2):
                if not any(c.value is not None for c in row): continue
                count+=1
                if count>20000: raise ValueError('최대 20,000개 컬럼 행을 허용합니다.')
                location=f'{sheet.title}!{rowno}'
                try:
                    if any(c.data_type=='f' for c in row): raise ValueError('수식 셀은 지원하지 않습니다. 값으로 변환하세요.')
                    r={h:row[i].value if i<len(row) else None for h,i in idx.items()}
                    name=text(r['TABLE_NAME']).upper() or previous
                    if not re.fullmatch(IDENT,name): raise ValueError('테이블명이 올바르지 않습니다.')
                    previous=name
                    column=text(r['COLUMN_NAME']).upper()
                    if not re.fullmatch(IDENT,column): raise ValueError('컬럼명이 올바르지 않습니다.')
                    key=text(r['KEY']).upper();nn=text(r['NOTNULL']).upper()
                    if key not in {'','PK','P','PRIMARY KEY'}: raise ValueError('KEY는 빈 값 또는 PK여야 합니다.')
                    if nn not in {'','NOT NULL','Y','YES','1','N','NO','0','NULL','NULLABLE'}: raise ValueError('NOTNULL 값이 올바르지 않습니다.')
                    column_id=int(r['COLUMN_ID'])
                    if column_id<1 or float(r['COLUMN_ID'])!=column_id: raise ValueError('COLUMN_ID는 1 이상의 정수여야 합니다.')
                    col=Column(name=column,**parse_type(r['DATA_TYPE']),raw_data_type=text(r['DATA_TYPE']),column_id=column_id,primary_key=bool(key),nullable=not(bool(key) or nn in {'NOT NULL','Y','YES','1'}),data_default=text(r['DATA_DEFAULT']),comment=text(r['COMMENTS_1']))
                    t=tables.setdefault(name,dict(table_name=name,owner='',comment=text(r['COMMENTS']),tablespace_name=text(r['TABLESPACE_NAME']),columns=[]))
                    for field,header in [('comment','COMMENTS'),('tablespace_name','TABLESPACE_NAME')]:
                        value=text(r[header])
                        if value and t[field] and value!=t[field]: raise ValueError('동일 테이블의 설명/테이블스페이스가 다릅니다.')
                        if value: t[field]=value
                    if any(c['name']==column or c['column_id']==col.column_id for c in t['columns']): raise ValueError('컬럼명 또는 COLUMN_ID 중복입니다.')
                    t['columns'].append(col.model_dump())
                    if col.db_type in {'NUMBER','NUMERIC','DECIMAL'} and col.precision is None: warnings.append(f'{location} {column}: NUMBER 정밀도/스케일 수동 확인 필요')
                    if col.db_type=='CLOB': warnings.append(f'{location} {column}: CLOB 호스트 선언은 환경 확인 필요')
                except (ValueError,TypeError) as exc: errors.append(f'{location}: {exc}')
        if not tables: errors.append('등록할 테이블이 없습니다.')
        for t in tables.values(): t['columns'].sort(key=lambda c:c['column_id'])
        return list(tables.values()),errors,warnings
    finally: workbook.close()
