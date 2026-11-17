from fastapi import APIRouter,HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from app.models import SQLDraft
from app.services.proc_generator import generate_select
from app.services.proc_storage import save_generation,list_generations,get_generation
router=APIRouter(prefix='/api')
class ProcRequest(BaseModel):
    service:SQLDraft
@router.post('/generate/preview')
def preview(body:ProcRequest):return {key:value for key,value in generate_select(body.service).items() if not key.startswith('_')}
class SaveRequest(ProcRequest):
    expected_sha256:str
    overwrite_confirmed:bool=False
@router.post('/generate/save')
def save(body:SaveRequest):
    result=generate_select(body.service)
    if result['errors']:raise HTTPException(400,'\n'.join(result['errors']))
    if result['sha256']!=body.expected_sha256:raise HTTPException(409,'미리보기 후 정의/템플릿이 변경되었습니다. 다시 생성하세요.')
    try:generation_id=save_generation(body.service,result,body.overwrite_confirmed)
    except LookupError as exc:raise HTTPException(400,str(exc)) from exc
    except FileExistsError as exc:raise HTTPException(409,{'code':'overwrite_required','message':str(exc)}) from exc
    return {'id':generation_id,'filename':result['filename'],'sha256':result['sha256']}
@router.get('/services/{service_id}/generations')
def history(service_id:str):return list_generations(service_id)
@router.get('/generations/{generation_id}')
def generation(generation_id:int):
    result=get_generation(generation_id)
    if not result:raise HTTPException(404,'생성 이력이 없습니다.')
    return result
@router.get('/generations/{generation_id}/download')
def download(generation_id:int):
    result=get_generation(generation_id)
    if not result:raise HTTPException(404,'생성 이력이 없습니다.')
    return Response(content=result['content'].encode(result['encoding']),media_type='application/octet-stream',headers={'Content-Disposition':'attachment; filename="'+result['filename']+'"','X-Content-SHA256':result['sha256']})
