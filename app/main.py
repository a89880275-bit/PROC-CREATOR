from contextlib import asynccontextmanager
from pathlib import Path
import secrets
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from app import db
from app.models import Service, Column
from app.services.mapping_service import auto_mappings
from app.services.sql_builder import SQLRequest, generate
from pydantic import BaseModel, Field

TOKEN=secrets.token_urlsafe(32)
ROOT=Path(__file__).resolve().parent
@asynccontextmanager
async def lifespan(app):
    db.migrate()
    yield
app=FastAPI(title='Tmax Pro*C Service Manager MVP',lifespan=lifespan)
@app.middleware('http')
async def local_only(request:Request,call_next):
    if request.headers.get('host') not in {'127.0.0.1:8765','127.0.0.1','localhost:8765'}:
        return JSONResponse({'detail':'로컬 Host만 허용합니다.'},status_code=403)
    origin=request.headers.get('origin')
    if origin and origin not in {'http://127.0.0.1:8765','http://localhost:8765'}:
        return JSONResponse({'detail':'외부 Origin은 차단됩니다.'},status_code=403)
    if request.method not in {'GET','HEAD','OPTIONS'} and request.headers.get('x-csrf-token')!=TOKEN:
        return JSONResponse({'detail':'보안 토큰이 없습니다. 새로고침하세요.'},status_code=403)
    response=await call_next(request)
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Cache-Control']='no-store'
    return response
@app.exception_handler(ValueError)
async def invalid(request,exc): return JSONResponse({'detail':str(exc)},status_code=400)
@app.get('/api/session')
def session(): return {'csrf_token':TOKEN}
@app.get('/api/services')
def services():
    return [{**{k:v for k,v in r.items() if k!='snapshot_json'},'table_name':__import__('json').loads(r['snapshot_json'])['table_name']} for r in db.list_services()]
@app.get('/api/services/{sid}')
def get(sid:str):
    s=db.get_service(sid)
    if not s: raise HTTPException(404,'서비스가 없습니다.')
    return s
@app.post('/api/services',status_code=201)
def create(s:Service): return db.save(s,True)
@app.put('/api/services/{sid}')
def update(sid:str,s:Service):
    if sid!=s.service_id: raise HTTPException(400,'서비스 ID는 변경할 수 없습니다. 복제를 사용하세요.')
    if not db.get_service(sid): raise HTTPException(404,'서비스가 없습니다.')
    return db.save(s)
@app.delete('/api/services/{sid}')
def delete(sid:str):
    if not db.delete(sid): raise HTTPException(404,'서비스가 없습니다.')
    return {'ok':True}
@app.post('/api/sql/generate')
def sql(r:SQLRequest): return {'sql':generate(r)}
class MappingRequest(BaseModel):
    columns:list[Column] = Field(max_length=200)
    inputs:list[str] = Field(default_factory=list)
    outputs:list[str] = Field(default_factory=list)
@app.post('/api/mappings/auto')
def mappings(r:MappingRequest): return [v.model_dump() for v in auto_mappings(r.columns,r.inputs,r.outputs)]
@app.get('/')
def index(): return FileResponse(ROOT/'static/index.html')
from app.dictionary_api import router as dictionary_router
app.include_router(dictionary_router)
from app.mapping_api import router as mapping_router
app.include_router(mapping_router)
from app.proc_api import router as proc_router
app.include_router(proc_router)
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
