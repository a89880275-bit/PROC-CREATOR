import pytest
from fastapi.testclient import TestClient
from app import db
from app.main import app
from app.models import Service, Column
from app.services.mapping_service import variable_name,auto_mappings
from app.services.sql_builder import SQLRequest,generate

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'test.sqlite3')
    with TestClient(app,base_url='http://127.0.0.1:8765') as c:
        c.headers['X-CSRF-Token']=c.get('/api/session').json()['csrf_token']
        yield c

def sample():
    cols=[Column(name='PATNO'),Column(name='SEQNO',db_type='NUMBER',precision=10,scale=0)]
    return Service(service_id='MD_TEST_S1',columns=cols,variables=auto_mappings(cols,['PATNO','SEQNO'],['PATNO','SEQNO']))
@pytest.mark.parametrize('col,expected',[(Column(name='PATNO'),'sPatno'),(Column(name='SEQNO',db_type='NUMBER',precision=10,scale=0),'iSeqno'),(Column(name='AMOUNT',db_type='NUMBER',precision=10,scale=2),'dAmount'),(Column(name='MED_DATE',db_type='DATE'),'sMed_date')])
def test_names(col,expected): assert variable_name(col)==expected

def test_uncertain_number():
    with pytest.raises(ValueError): variable_name(Column(name='N',db_type='NUMBER'))
@pytest.mark.parametrize('role,count,ok',[('IN',3,True),('IN',10,True),('IN',11,False),('OUT',8,True),('OUT',100,True),('OUT',101,False)])
def test_mapping_limits(role,count,ok):
    cols=[Column(name='C'+str(i)) for i in range(count)]; names=[c.name for c in cols]
    if not ok:
        with pytest.raises(ValueError): auto_mappings(cols,names if role=='IN' else [],names if role=='OUT' else [])
    else:
        vs=auto_mappings(cols,names if role=='IN' else [],names if role=='OUT' else [])
        assert vs[-1].field_name==('S_TYPE' if role=='IN' else 'S_STRING')+str(count)
@pytest.mark.parametrize('operation',['SELECT','INSERT','UPDATE','DELETE'])
def test_crud(operation):
    r=SQLRequest(service=sample(),operation=operation,selected=['SEQNO'],conditions=[{'column':'PATNO'}])
    sql=generate(r)
    assert ':sPatno' in sql or operation=='INSERT'
    assert 'SAMPLE_TABLE' in sql
@pytest.mark.parametrize('operation',['UPDATE','DELETE'])
def test_danger(operation):
    r=SQLRequest(service=sample(),operation=operation,selected=['SEQNO'])
    with pytest.raises(ValueError): generate(r)
    r.allow_full_table=True
    assert generate(r).startswith(operation)
def test_unknown_columns():
    with pytest.raises(ValueError): generate(SQLRequest(service=sample(),operation='SELECT',selected=['PATNO; DROP TABLE X']))
def test_save_reopen(client):
    s=sample();s.variables[1].variable_name='sSeqno';s.variables[1].is_manual=True
    s.sql_blocks[0].generated_sql='SELECT PATNO FROM X;';s.sql_blocks[0].final_sql="SELECT PATNO FROM X WHERE PATNO=:sPatno;";s.sql_blocks[0].is_manual=True
    r=client.post('/api/services',json=s.model_dump());assert r.status_code==201,r.text
    saved=client.get('/api/services/'+s.service_id).json()
    assert saved['variables'][1]['variable_name']=='sSeqno'
    assert saved['sql_blocks'][0]['final_sql']!=saved['sql_blocks'][0]['generated_sql']
    assert client.put('/api/services/'+s.service_id,json=saved).status_code==200
    assert client.put('/api/services/'+s.service_id,json=saved).status_code==400
    with db.connect() as d:
        assert d.execute('SELECT count(*) FROM service_versions').fetchone()[0]==2
        assert d.execute('SELECT count(*) FROM field_mappings').fetchone()[0]==4
        assert d.execute('PRAGMA foreign_key_check').fetchall()==[]
    assert client.post('/api/services',json=s.model_dump()).status_code==400
    assert client.delete('/api/services/'+s.service_id).status_code==200
    assert client.get('/api/services/'+s.service_id).status_code==404

def test_reorder_and_collision(client):
    s=sample();s.variables[2],s.variables[3]=s.variables[3],s.variables[2]
    response=client.post('/api/services',json=s.model_dump());assert response.status_code==201
    out=[v for v in response.json()['variables'] if v['role']=='OUT'];assert out[0]['db_column']=='SEQNO' and out[0]['field_name']=='S_STRING1'
    s.variables[1].variable_name=s.variables[0].variable_name
    assert client.post('/api/services',json=s.model_dump()).status_code==422

def test_security(client):
    assert client.get('/api/services',headers={'Host':'evil.example'}).status_code==403
    assert client.get('/api/session',headers={'Origin':'https://evil.example'}).status_code==403
    assert client.post('/api/services',json=sample().model_dump(),headers={'X-CSRF-Token':'wrong'}).status_code==403
    assert client.get('/').status_code==200
    assert "default-src 'self'" in client.get('/').headers['Content-Security-Policy']

def test_atomic_failure(client):
    s=sample();client.post('/api/services',json=s.model_dump());before=db.get_service(s.service_id)
    with db.connect() as d:
        d.execute("CREATE TRIGGER fail_mapping BEFORE INSERT ON field_mappings BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    s=Service(**before);s.name='failed edit'
    with pytest.raises(Exception): db.save(s)
    assert db.get_service(s.service_id)==before

def test_migration_idempotent(client):
    db.migrate();db.migrate()
    with db.connect() as d: assert [r[0] for r in d.execute('SELECT version FROM schema_migrations ORDER BY version')]==[1,2,3,4]


def test_select_has_no_automatic_row_limit():
    s=sample();s.max_row_count=50
    sql=generate(SQLRequest(service=s,operation='SELECT',selected=['PATNO'],order_by=['PATNO']))
    assert sql=='SELECT PATNO\nFROM SAMPLE_TABLE\nORDER BY PATNO;'
    assert 'ROWNUM' not in sql
