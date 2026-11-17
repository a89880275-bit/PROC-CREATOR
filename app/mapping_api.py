from fastapi import APIRouter
from pydantic import BaseModel,Field
from app.models import SQLDraft
from app.services.sql_analyzer import analyze_sql
from app.services.mapping_sync import preview_sync,apply_sync
router=APIRouter(prefix='/api')
class AnalyzeRequest(BaseModel):
    service:SQLDraft
@router.post('/sql/analyze')
def analyze(body:AnalyzeRequest):return analyze_sql(body.service)
@router.post('/mappings/sync/preview')
def preview(body:AnalyzeRequest):return preview_sync(body.service)
class SyncRequest(AnalyzeRequest):
    fingerprint:str
    overrides:dict[str,dict]=Field(default_factory=dict)
    remove_ids:list[str]=Field(default_factory=list)
    reorder_outputs:bool=False
@router.post('/mappings/sync/apply')
def apply(body:SyncRequest):
    result=apply_sync(body.service,body.fingerprint,body.overrides,body.remove_ids,body.reorder_outputs)
    return {'service':result.model_dump(),'sql':result.sql_blocks[0].final_sql}
