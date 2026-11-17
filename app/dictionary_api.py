from urllib.parse import unquote
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field
from app.services import table_dictionary as dictionary
from app.services.excel_importer import read_excel,MAX_BYTES
from app.services.sql_builder import SQLRequest,generate
from app.services.host_validation import prepare
from app.models import Column, IDENT
router=APIRouter(prefix='/api')
@router.post('/dictionary/excel/preview')
async def excel_preview(request:Request):
    # Raw binary avoids multipart dependency and never treats a supplied path as a filesystem path.
    data=bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>MAX_BYTES: raise HTTPException(413,'Excel 파일은 10MB 이하만 허용합니다.')
    filename=unquote(request.headers.get('x-file-name','upload.xlsx'))[:200]
    try:
        tables,errors,warnings=read_excel(bytes(data))
    except Exception as exc:
        if not isinstance(exc,ValueError): exc=ValueError('Excel을 읽을 수 없습니다. XLSX 형식을 확인하세요.')
        tables,errors,warnings=[],[str(exc)],[]
    return dictionary.preview(tables,filename,bytes(data),errors,warnings)
class TableDefinition(BaseModel):
    owner:str=''
    table_name:str=Field(pattern=IDENT)
    comment:str=''
    tablespace_name:str=''
    columns:list[Column]=Field(min_length=1,max_length=20000)
class ManualPreview(BaseModel):
    tables:list[TableDefinition] = Field(min_length=1,max_length=200)
@router.post('/dictionary/preview')
def manual_preview(body:ManualPreview): return dictionary.preview([t.model_dump() for t in body.tables],'수동 등록')
class Selection(BaseModel):
    owner:str=''
    table_name:str
    keys:list[str]
class Commit(BaseModel):
    import_id:str
    selections:list[Selection]
@router.post('/dictionary/commit')
def commit(body:Commit): return dictionary.commit(body.import_id,[s.model_dump() for s in body.selections])
@router.get('/dictionary/tables')
def tables(q:str=''): return dictionary.search(q)
@router.get('/dictionary/tables/{name}')
def table(name:str,owner:str=''):
    t=dictionary.lookup(owner,name)
    if not t: raise HTTPException(404,'테이블이 없습니다.')
    return t
@router.get('/dictionary/tables/{name}/usage')
def usage(name:str,owner:str=''): return dictionary.usage(owner,name)
@router.get('/dictionary/tables/{name}/history')
def history(name:str,owner:str=''): return dictionary.history(owner,name)
@router.get('/dictionary/imports')
def imports(): return dictionary.imports()
@router.post('/sql/prepare')
def prepare_sql(body:SQLRequest):
    s,warnings=prepare(body)
    sql=generate(body.model_copy(update={'service':s}))
    from app.services.mapping_sync import annotate_generated
    annotate_generated(s,sql)
    return dict(service=s.model_dump(),warnings=warnings,sql=sql)
