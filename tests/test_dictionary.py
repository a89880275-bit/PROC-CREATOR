import copy
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
import pytest
from openpyxl import Workbook
from fastapi.testclient import TestClient
from app import db
from app.main import app
from app.models import Service,Column
from app.services import table_dictionary as dictionary
from app.services.excel_importer import read_excel,parse_type,HEADERS
from app.services.mapping_service import auto_mappings
from app.services.sql_builder import SQLRequest,generate
from app.services.host_validation import prepare,host_warnings

REAL_EXCEL=Path(__file__).resolve().parents[1]/'MDMEDORT.xlsx'
@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'dictionary.sqlite3')
    with TestClient(app,base_url='http://127.0.0.1:8765') as c:
        c.headers['X-CSRF-Token']=c.get('/api/session').json()['csrf_token']
        yield c

def workbook(rows,headers=HEADERS):
    """Small in-memory synthetic fixtures, distinct from supplied acceptance workbook."""
    w=Workbook();s=w.active;s.append(headers)
    for row in rows:s.append(row)
    b=BytesIO();w.save(b);w.close();return b.getvalue()

def preview_real(client):
    # Deliberately fail if the supplied file is missing; no silent substitution.
    assert REAL_EXCEL.is_file(),'실제 제공된 MDMEDORT.xlsx가 필요합니다.'
    r=client.post('/api/dictionary/excel/preview',content=REAL_EXCEL.read_bytes(),headers={'X-File-Name':'MDMEDORT.xlsx'})
    assert r.status_code==200,r.text
    return r.json()
def selection(p,keys=None):
    return {'import_id':p['import_id'],'selections':[{'owner':e['table']['owner'],'table_name':e['table']['table_name'],'keys':keys if keys is not None else [c['key'] for c in e['changes']]} for e in p['tables']]}
def register(client):
    p=preview_real(client);r=client.post('/api/dictionary/commit',json=selection(p));assert r.status_code==200,r.text
    return r.json()['tables'][0]

def test_supplied_workbook_preview_and_register(client):
    p=preview_real(client);assert p['errors']==[]
    assert len(p['tables'])==1;t=p['tables'][0]['table'];assert t['table_name']=='MDMEDORT';assert len(t['columns'])==188
    cols={c['name']:c for c in t['columns']}
    assert cols['PATNO']['length']==8 and cols['PATNO']['primary_key'] and not cols['PATNO']['nullable']
    assert cols['ORDSEQNO']['precision']==22 and cols['ORDSEQNO']['scale']==0
    assert cols['ORDSEQNO']['raw_data_type']=='NUMBER(22)'
    assert cols['ORDDATE']['db_type']=='DATE'
    assert client.get('/api/dictionary/tables').json()==[] # preview never registers
    r=client.post('/api/dictionary/commit',json=selection(p));assert r.status_code==200
    assert client.post('/api/dictionary/commit',json=selection(p)).status_code==400
    assert client.get('/api/dictionary/tables/MDMEDORT').json()['columns']==t['columns']
    for query in ['MDMEDORT',t['comment'],'ORDSEQNO',cols['PATNO']['comment']]:
        assert len(client.get('/api/dictionary/tables',params={'q':query}).json())==1
    log=client.get('/api/dictionary/imports').json();assert log[0]['filename']=='MDMEDORT.xlsx' and log[0]['status']=='applied'
    assert len(client.get('/api/dictionary/tables/MDMEDORT/history').json())==1

def test_multiple_tables_defaults_and_nulls(client):
    data=workbook([['A','업무A','TBS',1,'ID','NUMBER(10)','PK','NOT NULL','0','식별자'],['A','업무A','TBS',2,'VALUE','VARCHAR2(30 CHAR)','','','\'X\'','내용'],['B','업무B','TBS',1,'DATE1','DATE','','Y','SYSDATE','일자']])
    p=client.post('/api/dictionary/excel/preview',content=data).json();assert not p['errors']
    assert len(p['tables'])==2
    assert client.post('/api/dictionary/commit',json=selection(p)).status_code==200
    a=client.get('/api/dictionary/tables/A').json();assert a['columns'][0]['data_default']=='0';assert a['columns'][1]['nullable']
    assert client.get('/api/dictionary/tables/B').json()['columns'][0]['data_default']=='SYSDATE'

@pytest.mark.parametrize('rows,headers',[([['BAD; DROP','','',1,'X','DATE','','','','']],HEADERS),([['A','','',1,'X','MYSTERY','','','','']],HEADERS),([['A','','',1,'X','DATE','','','',''],['A','','',1,'X','DATE','','','','']],HEADERS),([['=SUM(1,2)','','',1,'X','DATE','','','','']],HEADERS),([['A']],['TABLE_NAME'])])
def test_invalid_excel_never_applies(client,rows,headers):
    p=client.post('/api/dictionary/excel/preview',content=workbook(rows,headers)).json()
    assert p['errors'];assert client.post('/api/dictionary/commit',json=selection(p)).status_code==400
    assert client.get('/api/dictionary/tables').json()==[]

def test_invalid_zip_history(client):
    p=client.post('/api/dictionary/excel/preview',content=b'not zip').json();assert p['errors']
    assert client.get('/api/dictionary/imports').json()[0]['status']=='invalid'

def test_selective_changes_and_service_preservation(client):
    t=register(client);cols=[Column(**c) for c in t['columns']]
    s=Service(service_id='USED_S1',table_name='MDMEDORT',columns=cols,variables=auto_mappings(cols,['PATNO'],['ORDDATE']))
    s.variables[0].variable_name='sUserPatno';assert client.post('/api/services',json=s.model_dump()).status_code==201
    before=client.get('/api/services/USED_S1').json()
    changed=copy.deepcopy(t);changed['comment']='새 설명';changed['columns'][0]['length']=12
    removed=changed['columns'].pop(1)['name'];changed['columns'].append(Column(name='NEWCOL',column_id=999).model_dump())
    p=client.post('/api/dictionary/preview',json={'tables':[changed]}).json()
    kinds={x['key']:x['kind'] for x in p['tables'][0]['changes']}
    assert kinds['column:PATNO']=='변경' and kinds['column:'+removed]=='삭제' and kinds['column:NEWCOL']=='신규'
    assert p['tables'][0]['usage'][0]['service_id']=='USED_S1'
    assert client.post('/api/dictionary/commit',json=selection(p,['column:PATNO','column:NEWCOL'])).status_code==200
    latest=client.get('/api/dictionary/tables/MDMEDORT').json()
    assert latest['comment']==t['comment'] # unchecked metadata preserved
    assert any(c['name']==removed for c in latest['columns']) # unchecked deletion preserved
    assert latest['columns'][0]['length']==12
    assert client.get('/api/services/USED_S1').json()==before
    assert client.get('/api/dictionary/tables/MDMEDORT/usage').json()[0]['columns']
    assert len(client.get('/api/dictionary/tables/MDMEDORT/history').json())==2

def test_stale_preview_atomic_and_unrelated_table_preserved(client):
    t=register(client)
    t['comment']='first';p=client.post('/api/dictionary/preview',json={'tables':[t]}).json()
    t['comment']='second';q=client.post('/api/dictionary/preview',json={'tables':[t]}).json()
    assert client.post('/api/dictionary/commit',json=selection(p)).status_code==200
    assert client.post('/api/dictionary/commit',json=selection(q)).status_code==400
    assert client.get('/api/dictionary/tables/MDMEDORT').json()['comment']=='first'
    other={'table_name':'OTHER','columns':[Column(name='ID').model_dump()]}
    v=client.post('/api/dictionary/preview',json={'tables':[other]}).json()
    assert client.post('/api/dictionary/commit',json=selection(v)).status_code==200
    assert len(client.get('/api/dictionary/tables').json())==2

@pytest.mark.parametrize('operation',['SELECT','INSERT','UPDATE','DELETE'])
def test_supplied_excel_sql_and_auto_mapping(client,operation):
    t=register(client);s=Service(service_id='MED_S1',table_name=t['table_name'],columns=[Column(**c) for c in t['columns']],table_alias='a')
    r=client.post('/api/sql/prepare',json=SQLRequest(service=s,operation=operation,selected=['PATNO','ORDDATE','ORDSEQNO'],conditions=[{'column':'PATNO'},{'column':'ORDDATE'},{'column':'ORDSEQNO'}],order_by=['ORDDATE']).model_dump())
    assert r.status_code==200,r.text
    p=r.json();assert ':sPatno' in p['sql'];assert "TO_DATE(:sOrddate, 'YYYY-MM-DD')" in p['sql'];assert 'TO_NUMBER(:iOrdseqno)' in p['sql']
    ins=[v for v in p['service']['variables'] if v['role']=='IN'];assert [v['field_name'] for v in ins]==['S_TYPE1','S_TYPE2','S_TYPE3']
    if operation=='SELECT':
        assert "TO_CHAR(a.ORDDATE, 'YYYY-MM-DD')" in p['sql'];assert 'ORDER BY a.ORDDATE' in p['sql']
        assert [v['field_name'] for v in p['service']['variables'] if v['role']=='OUT']==['S_STRING1','S_STRING2','S_STRING3']
    else: assert 'TO_CHAR(' not in p['sql']

def test_prepare_preserves_manual_and_builder(client):
    t=register(client);cols=[Column(**c) for c in t['columns']]
    s=Service(service_id='KEEP_S1',table_name='MDMEDORT',columns=cols,variables=auto_mappings(cols,['PATNO'],[]),builder_state={'selected':['ORDDATE'],'conditions':[{'column':'PATNO','operator':'=','connector':'AND'}],'order_by':['ORDDATE']})
    s.variables[0].variable_name='sManuallyNamed'
    r=client.post('/api/sql/prepare',json=SQLRequest(service=s,operation='SELECT',selected=['ORDDATE'],conditions=[{'column':'PATNO'}]).model_dump())
    assert r.status_code==200;prepared=r.json()['service'];assert prepared['variables'][0]['variable_name']=='sManuallyNamed'
    assert client.post('/api/services',json=prepared).status_code==201
    reopened=client.get('/api/services/KEEP_S1').json();assert reopened['builder_state']==s.builder_state
    with db.connect() as d: assert d.execute("SELECT alias FROM service_tables WHERE service_id='KEEP_S1'").fetchone()[0]==''

def test_precision_and_date_host_validation():
    n=Column(name='N',db_type='NUMBER',precision=22,scale=0)
    vs=auto_mappings([n],['N'],[]);s=Service(service_id='S',columns=[n],variables=vs)
    assert vs[0].host_length>=25
    s.variables[0].host_type='int'
    with pytest.raises(ValueError,match='정밀도'):host_warnings(s)
    s.variables[0].host_type='asciz';s.variables[0].host_length=2
    with pytest.raises(ValueError,match='길이'):host_warnings(s)
    d=Column(name='D',db_type='DATE');s=Service(service_id='S',columns=[d],variables=auto_mappings([d],['D'],[]));s.variables[0].host_type='double'
    with pytest.raises(ValueError,match='날짜'):host_warnings(s)
@pytest.mark.parametrize('raw,p,scale',[('NUMBER(22)',22,0),('NUMBER(10,2)',10,2),('NUMBER(8,-2)',8,-2),('NUMBER',None,None)])
def test_number_type_parse(raw,p,scale):
    t=parse_type(raw);assert t['precision']==p and t['scale']==scale

def test_schema_upgrade_preserves_existing_rows(client):
    s=Service(service_id='OLD_S1',description='이전 서비스');client.post('/api/services',json=s.model_dump());before=client.get('/api/services/OLD_S1').json()
    with db.connect() as d:
        for table in ['business_tables','dictionary_history','excel_imports']: d.execute('DROP TABLE '+table)
        d.execute('DELETE FROM schema_migrations WHERE version=2')
    db.migrate();db.migrate()
    assert client.get('/api/services/OLD_S1').json()==before
    with db.connect() as d:
        assert [r[0] for r in d.execute('SELECT version FROM schema_migrations ORDER BY version')]==[1,2,3,4]
        assert d.execute('PRAGMA foreign_key_check').fetchall()==[]

def test_selected_deletion_and_history_does_not_change_services(client):
    t=register(client);s=Service(service_id='DELETE_KEEP_S1',table_name='MDMEDORT',columns=[Column(**c) for c in t['columns']])
    client.post('/api/services',json=s.model_dump());before=client.get('/api/services/DELETE_KEEP_S1').json()
    target=t['columns'].pop(0)['name'];p=client.post('/api/dictionary/preview',json={'tables':[t]}).json()
    assert client.post('/api/dictionary/commit',json=selection(p,['column:'+target])).status_code==200
    assert target not in [c['name'] for c in client.get('/api/dictionary/tables/MDMEDORT').json()['columns']]
    assert client.get('/api/services/DELETE_KEEP_S1').json()==before
    h=client.get('/api/dictionary/tables/MDMEDORT/history').json()[0]
    import json
    assert len(json.loads(h['before_json'])['columns'])==188 and len(json.loads(h['after_json'])['columns'])==187

def test_dictionary_commit_rolls_back_entire_batch(client):
    tables=[{'table_name':n,'columns':[Column(name='ID').model_dump()]} for n in ['A','B']]
    p=client.post('/api/dictionary/preview',json={'tables':tables}).json()
    with db.connect() as d:
        d.execute("CREATE TRIGGER fail_second BEFORE INSERT ON business_tables WHEN NEW.table_name='B' BEGIN SELECT RAISE(ABORT, 'test'); END")
    with pytest.raises(Exception):client.post('/api/dictionary/commit',json=selection(p))
    assert client.get('/api/dictionary/tables').json()==[]
    with db.connect() as d:
        assert d.execute('SELECT count(*) FROM dictionary_history').fetchone()[0]==0
        assert d.execute('SELECT status FROM excel_imports').fetchone()[0]=='preview'

def test_supplied_188_output_limit_no_mapping_loss(client):
    t=register(client);s=Service(service_id='TOO_MANY_S1',table_name='MDMEDORT',columns=[Column(**c) for c in t['columns']])
    req=SQLRequest(service=s,operation='SELECT',selected=[c.name for c in s.columns])
    assert client.post('/api/sql/prepare',json=req.model_dump()).status_code==400
    assert s.variables==[]

@pytest.mark.parametrize('fmt,length,valid',[('YYYY-MM-DD',10,True),('YYYY-MM-DD HH24:MI:SS',19,True),('YYYY-MM-DD HH24:MI:SS',10,False),('not-a-format',40,False)])
def test_date_formats_and_host_length(fmt,length,valid):
    c=Column(name='D',db_type='DATE',length=length,date_format=fmt)
    s=Service(service_id='DATE_S1',columns=[c],variables=auto_mappings([c],['D'],[]))
    if valid: assert host_warnings(s)
    else:
        with pytest.raises(ValueError):host_warnings(s)

def test_invalid_column_ordinal_and_manual_input(client):
    p=client.post('/api/dictionary/excel/preview',content=workbook([['A','','',1.5,'ID','DATE','','','','']])).json()
    assert p['errors']
    assert client.post('/api/dictionary/preview',json={'tables':[{'owner':12,'table_name':'A','columns':[]}]}).status_code==422

def test_usage_distinguishes_selected_columns_from_metadata(client):
    t=register(client)
    s=Service(service_id='USAGE_S1',table_name='MDMEDORT',columns=[Column(**c) for c in t['columns']],builder_state={'selected':['PATNO'],'conditions':[{'column':'ORDDATE'}],'order_by':['ORDSEQNO']})
    assert client.post('/api/services',json=s.model_dump()).status_code==201
    row=client.get('/api/dictionary/tables/MDMEDORT/usage').json()[0]
    assert set(row['columns'])=={'PATNO','ORDDATE','ORDSEQNO'}
    assert len(row['defined_columns'])==188

def test_sql_preview_without_service_id_then_save_requires_id(client):
    t=register(client)
    body={'service':{'service_id':'','table_name':'MDMEDORT','columns':t['columns']},'operation':'SELECT','selected':['PATNO','ORDDATE'],'conditions':[{'column':'PATNO'}],'order_by':['ORDDATE']}
    result=client.post('/api/sql/prepare',json=body)
    assert result.status_code==200,result.text
    preview=result.json();assert preview['service']['service_id']==''
    assert 'WHERE PATNO = :sPatno' in preview['sql'] and 'ORDER BY ORDDATE' in preview['sql']
    assert client.get('/api/services').json()==[]
    assert client.post('/api/services',json=preview['service']).status_code==422
    preview['service']['service_id']='SAVED_AFTER_PREVIEW'
    assert client.post('/api/services',json=preview['service']).status_code==201

def test_invalid_nonempty_draft_id_still_rejected(client):
    r=client.post('/api/sql/prepare',json={'service':{'service_id':'../bad'},'operation':'SELECT','selected':[]})
    assert r.status_code==422
