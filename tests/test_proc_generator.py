from pathlib import Path
import hashlib,json,re
import pytest
from fastapi.testclient import TestClient
from app import db
from app.main import app
from app.models import Column,SQLDraft
from app.services.mapping_sync import preview_sync,apply_sync,sql_fingerprint
from app.services.proc_generator import generate_select,select_parts

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'proc.sqlite3')
    with TestClient(app,base_url='http://127.0.0.1:8765') as c:
        c.headers['X-CSRF-Token']=c.get('/api/session').json()['csrf_token'];yield c

def service(inputs=1,outputs=1):
    columns=[Column(name='C'+str(i),length=20) for i in range(max(inputs,outputs))]
    sql='SELECT '+','.join(c.name for c in columns[:outputs])+' FROM TEST_TABLE'
    if inputs:sql+=' WHERE '+' AND '.join(c.name+'=:sC'+str(i) for i,c in enumerate(columns[:inputs]))
    s=SQLDraft(service_id='MD_TEST_S1',columns=columns,table_name='TEST_TABLE',sql_blocks=[{'final_sql':sql}])
    return apply_sync(s,preview_sync(s)['fingerprint'])

@pytest.mark.parametrize('count',[1,10])
def test_inputs_and_duplicate_get(count):
    s=service(count,1);r=generate_select(s);assert not r['errors'],r
    assert len(re.findall(r'GET \(S_TYPE\d+, 0,',r['source']))==count
    s.sql_blocks[0].final_sql+=' OR C0=:sC0';s=apply_sync(s,preview_sync(s)['fingerprint'])
    r=generate_select(s);assert not r['errors'];assert r['source'].count('GET (S_TYPE1, 0, sC0);')==1
@pytest.mark.parametrize('count',[1,100])
def test_output_count_and_array_declarations(count):
    r=generate_select(service(1,count));assert not r['errors'],r
    assert len(re.findall(r'PUT \(S_STRING\d+, iy,',r['source']))==count
    assert 'asciz20 sC0Out[MAXROWCNT];' in r['source']
    assert 'short n_sC0Out[MAXROWCNT];' in r['source']
    assert r['sql_output_order'][0]=='sC0Out'
@pytest.mark.parametrize('role,count',[('IN',11),('OUT',101)])
def test_limits_block_preview(client,role,count):
    s=service();body=s.model_dump();v=next(v for v in body['variables'] if v['role']==role)
    body['variables']=[{**v,'mapping_id':'m'+str(i),'variable_name':'sV'+str(i)} for i in range(count)]
    response=client.post('/api/generate/preview',json={'service':body});assert response.status_code==422
    with db.connect() as d:assert d.execute('SELECT count(*) FROM proc_generations').fetchone()[0]==0

def test_no_data_multirow_and_overflow_paths_structurally():
    source=generate_select(service())['source']
    assert 'rowcnt = SQLCNT;' in source
    assert 'if (rowcnt==0)' in source and 'MakeMsg(message,SF_A220,0);' in source
    assert 'for (iy=0; iy<rowcnt; iy++)' in source and 'sC0Out[iy]' in source
    assert 'SQLCODE==TOOMANY || SQLCNT>MAXROWCNT' in source
    assert 'MakeMsg(message,SF_B220,MAXROWCNT);' in source
    assert 'ROWNUM' not in source and 'commit' not in source.lower()
    assert 'SQLCODE!=0 && SQLCODE!=NOTFOUND && SQLCODE!=TOOMANY' in source

def test_date_and_number_string_declarations():
    s=SQLDraft(service_id='MD_NUM_S1',table_name='T',columns=[Column(name='N',db_type='NUMBER',precision=22,scale=0,length=64),Column(name='D',db_type='DATE',length=19)],sql_blocks=[{'final_sql':"SELECT N,TO_CHAR(D,'YYYY-MM-DD') AS D FROM T WHERE N=TO_NUMBER(:iN) AND D=TO_DATE(:sD,'YYYY-MM-DD')"}])
    s=apply_sync(s,preview_sync(s)['fingerprint']);r=generate_select(s);assert not r['errors'],r
    assert 'asciz1h iN;' in r['source'] and 'asciz1h iNOut[MAXROWCNT];' in r['source']
    assert "TO_CHAR(D,'YYYY-MM-DD') AS D" in r['embedded_sql']
    assert "TO_DATE(:sD,'YYYY-MM-DD')" in r['embedded_sql']

def test_join_subquery_case_nvl_user_confirmed_type():
    s=SQLDraft(service_id='MD_JOIN_S1',table_name='T',table_alias='a',columns=[Column(name='ID'),Column(name='NAME')],join_tables=[{'table_name':'U','alias':'b','columns':[Column(name='ID').model_dump()],'conditions':[{'left_column':'ID','right_column':'ID'}]}],sql_blocks=[{'final_sql':"SELECT CASE WHEN a.ID IS NULL THEN 'N' ELSE NVL(a.NAME,'-') END AS LABEL FROM T a LEFT JOIN U b ON b.ID=a.ID WHERE a.ID=:sId AND EXISTS (SELECT 1 FROM U x WHERE x.ID=a.ID)"}])
    p=preview_sync(s);s=apply_sync(s,p['fingerprint'],overrides={'OUT:1':{'metadata':Column(name='LABEL',length=30).model_dump()}})
    r=generate_select(s);assert not r['errors'],r
    assert "CASE WHEN a.ID IS NULL THEN 'N' ELSE NVL(a.NAME,'-') END AS LABEL" in r['embedded_sql']
    assert 'EXISTS (SELECT 1 FROM U x WHERE x.ID=a.ID)' in r['embedded_sql']
    assert len([t for t in __import__('app.services.sql_analyzer',fromlist=['tokenize']).tokenize(r['embedded_sql']) if t.upper=='INTO'])==1

def test_existing_into_kept_and_missing_indicator_augmented():
    s=service();s.sql_blocks[0].final_sql=s.sql_blocks[0].final_sql.replace(' FROM',' INTO :sC0Out FROM')
    r=generate_select(s);assert not r['errors'],r
    assert r['embedded_sql'].upper().count(' INTO ')==1
    assert 'INTO :sC0Out:n_sC0Out FROM' in r['embedded_sql']
    s.sql_blocks[0].final_sql=s.sql_blocks[0].final_sql.replace(':sC0Out',':wrong')
    assert generate_select(s)['errors']

def test_comments_literals_untouched_and_undeclared_bind_detected():
    s=service();s.sql_blocks[0].final_sql+=" AND ':fake INTO FROM'=':fake INTO FROM' /* :ignored */ -- comment\n"
    s=apply_sync(s,preview_sync(s)['fingerprint']);r=generate_select(s);assert not r['errors']
    assert "':fake INTO FROM'" in r['embedded_sql'] and '/* :ignored */' in r['embedded_sql']
    s.sql_blocks[0].final_sql+=' AND C0=:notDeclared'
    assert '미선언' in generate_select(s)['errors'][0]

def test_manual_names_and_put_order_vs_select_into_order():
    s=service(2,2);inputs=[v for v in s.variables if v.role=='IN'];outputs=[v for v in s.variables if v.role=='OUT']
    inputs[0].variable_name='sManual';inputs[0].is_manual=True
    s.variables=inputs+[outputs[1],outputs[0]]
    s=apply_sync(s,preview_sync(s)['fingerprint'])
    r=generate_select(s);assert not r['errors'],r
    assert 'GET (S_TYPE1, 0, sManual);' in r['source']
    assert 'PUT (S_STRING1, iy, sC1Out[iy]);' in r['source']
    assert r['sql_output_order']==['sC0Out','sC1Out']

def test_null_and_truncation_paths():
    r=generate_select(service());assert not r['errors']
    assert ':sC0Out:n_sC0Out' in r['embedded_sql']
    assert 'n_sC0Out[iy]==-1' in r['source'] and 'memset(&sC0Out[iy], 0, sizeof(sC0Out[iy]));' in r['source']
    assert 'n_sC0Out[iy]>0 || n_sC0Out[iy]==-2' in r['source']
@pytest.mark.parametrize('change',['int','too_short','collision','too_large','unsafe_name','transaction','inactive'])
def test_unsupported_or_invalid_generation_blocked(change):
    s=service()
    if change=='int':s.variables[0].host_type='int'
    if change=='too_short':s.variables[0].host_length=1
    if change=='collision':s.variables[1].null_indicator='rowcnt'
    if change=='too_large':s.max_row_count=1000000
    if change=='unsafe_name':s.proc_settings.filename='../bad.pc'
    if change=='transaction':s.type='transaction'
    if change=='inactive':s.variables[0].is_active=False
    assert generate_select(s)['errors']

def test_sql_changed_requires_sync_and_complex_statements_stop():
    s=service();s.sql_blocks[0].final_sql+=' AND C0 IS NOT NULL'
    assert generate_select(s)['errors']
    for sql in ['WITH X AS (SELECT 1 FROM DUAL) SELECT * FROM X','SELECT C0 FROM TEST_TABLE UNION SELECT C0 FROM TEST_TABLE','SELECT C0 FROM TEST_TABLE; DELETE FROM TEST_TABLE;']:
        s.sql_blocks[0].final_sql=sql;assert generate_select(s)['errors']

def test_sample_macro_structure_comparison():
    sample=(Path(__file__).resolve().parents[1]/'samples/md_fdrpt_s5.pc').read_bytes().decode('cp949')
    generated=generate_select(service())['source']
    for pattern in [r'int\s+DataCnt\s*=0',r'#include <global.h>',r'exec sql include oravar;',r'#define\s+MAXROWCNT',r'#if defined\(__STDC__\)',r'GET\s*\(S_TYPE1,\s*0,',r'PUT\s*\(S_STRING1,\s*iy,',r'MakeErrMsg\(message,SVCNAME,DBSEL,SQLMSG\)',r'MakeMsg\(message,SF_A220,rowcnt\)',r'TPRETURN\(message,0\)',r'tprealloc\(\(char \*\)transf,MAXBUFSIZE\)',r'Finit\(transf,Fsizeof\(transf\)\)']:
        assert re.search(pattern,sample),pattern
        assert re.search(pattern,generated),pattern

def test_preview_save_download_snapshot_template_and_overwrite(client):
    s=service();saved=client.post('/api/services',json=s.model_dump());assert saved.status_code==201
    data=saved.json();r=client.post('/api/generate/preview',json={'service':data});assert r.status_code==200,r.text
    p=r.json();assert not p['errors'] and p['compiled'] is False and p['filename']=='md_test_s1.pc'
    body={'service':data,'expected_sha256':p['sha256']}
    first=client.post('/api/generate/save',json=body);assert first.status_code==200,first.text
    ident=first.json()['id'];download=client.get(f'/api/generations/{ident}/download')
    assert download.content==p['source'].encode('utf-8')
    assert hashlib.sha256(download.content).hexdigest()==p['sha256']
    assert 'md_test_s1.pc' in download.headers['content-disposition']
    assert client.post('/api/generate/save',json=body).status_code==409
    second=client.post('/api/generate/save',json={**body,'overwrite_confirmed':True});assert second.status_code==200
    assert second.json()['id']!=ident
    record=client.get(f'/api/generations/{ident}').json();assert json.loads(record['service_snapshot_json'])==data
    assert record['template_version']=='1.0.0'
    assert len(client.get('/api/services/MD_TEST_S1/generations').json())==2
    with db.connect() as d:assert d.execute('SELECT count(*) FROM generated_files').fetchone()[0]==2

def test_unsaved_and_stale_preview_not_persisted(client):
    s=service();p=generate_select(s)
    assert client.post('/api/generate/save',json={'service':s.model_dump(),'expected_sha256':p['sha256']}).status_code==400
    data=client.post('/api/services',json=s.model_dump()).json();data['max_row_count']=50
    assert client.post('/api/generate/save',json={'service':data,'expected_sha256':p['sha256']}).status_code==409

def test_cp949_encoding_and_input_indicator():
    s=service();s.sql_blocks[0].final_sql=s.sql_blocks[0].final_sql.replace(':sC0',':sC0:n_in')+" AND '환자'='환자'"
    s=apply_sync(s,preview_sync(s)['fingerprint']);assert len([v for v in s.variables if v.role=='IN'])==1
    assert next(v for v in s.variables if v.role=='IN').null_indicator=='n_in'
    s.proc_settings.encoding='cp949';r=generate_select(s);assert not r['errors'],r
    assert 'short n_in;' in r['source']
    assert hashlib.sha256(r['source'].encode('cp949')).hexdigest()==r['sha256']

def test_existing_into_from_scratch_sync_and_generate():
    s=SQLDraft(service_id='MD_INTO_S1',table_name='T',columns=[Column(name='PATNO')],sql_blocks=[{'final_sql':'SELECT PATNO INTO :sResult FROM T WHERE PATNO=:sPatno'}])
    p=preview_sync(s);assert not p['errors'],p
    s=apply_sync(s,p['fingerprint']);assert [v.variable_name for v in s.variables]==['sPatno','sResult']
    r=generate_select(s);assert not r['errors'],r
    assert r['embedded_sql'].count('INTO')==1 and ':sResult:n_sResult' in r['embedded_sql']

def test_existing_into_count_without_alias_and_manual_output_rename():
    s=SQLDraft(service_id='MD_COUNT_S1',table_name='T',columns=[Column(name='PATNO')],sql_blocks=[{'final_sql':'SELECT COUNT(*) INTO :iCount:n_count FROM T'}])
    s=apply_sync(s,preview_sync(s)['fingerprint']);s.variables[0].variable_name='sManualCount';s.variables[0].is_manual=True
    s=apply_sync(s,preview_sync(s)['fingerprint'])
    assert 'INTO :sManualCount:n_count' in s.sql_blocks[0].final_sql
    assert len(preview_sync(s)['removed'])==0
    r=generate_select(s);assert not r['errors'],r
    assert 'short n_count[MAXROWCNT]' in r['source']

def test_existing_into_input_output_host_overlap_rejected():
    s=SQLDraft(service_id='MD_BAD_S1',table_name='T',columns=[Column(name='PATNO')],sql_blocks=[{'final_sql':'SELECT PATNO INTO :sPatno FROM T WHERE PATNO=:sPatno'}])
    assert preview_sync(s)['errors']
