import copy
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app import db
from app.main import app
from app.models import Column
from app.services.excel_importer import read_excel

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'joins.sqlite3')
    with TestClient(app,base_url='http://127.0.0.1:8765') as c:
        c.headers['X-CSRF-Token']=c.get('/api/session').json()['csrf_token']
        yield c

def request_body(join_type='INNER'):
    tables,errors,_=read_excel((Path(__file__).resolve().parents[1]/'MDMEDORT.xlsx').read_bytes());assert not errors
    columns=[Column(name='PATNO',length=8,nullable=False,primary_key=True).model_dump(),Column(name='PATNAME',length=40).model_dump(),Column(name='BIRTHDATE',db_type='DATE',length=19).model_dump()]
    return {'service':{'service_id':'JOIN_S1','table_name':'MDMEDORT','table_alias':'a','columns':tables[0]['columns'],'join_tables':[{'table_name':'APPATBAT','alias':'b','join_type':join_type,'columns':columns,'conditions':[{'left_column':'PATNO','right_column':'PATNO'}]}]},'operation':'SELECT','selected':['PATNO','b.PATNO','b.PATNAME','b.BIRTHDATE'],'conditions':[{'column':'PATNO'},{'column':'b.PATNAME','operator':'LIKE'}],'order_by':['ORDDATE','b.PATNAME']}

@pytest.mark.parametrize('join_type',['INNER','LEFT','RIGHT','FULL'])
def test_two_table_join_generation_and_mappings(client,join_type):
    body=request_body(join_type);r=client.post('/api/sql/prepare',json=body);assert r.status_code==200,r.text
    p=r.json();sql=p['sql']
    assert sql.startswith('SELECT a.PATNO') and 'ROWNUM' not in sql
    assert f'{join_type} JOIN APPATBAT b ON a.PATNO = b.PATNO' in sql
    assert 'a.PATNO AS a_PATNO' in sql and 'b.PATNO AS b_PATNO' in sql
    assert "TO_CHAR(b.BIRTHDATE, 'YYYY-MM-DD') AS b_BIRTHDATE" in sql
    assert 'b.PATNAME LIKE :sB_patname' in sql and 'ORDER BY a.ORDDATE, b.PATNAME' in sql
    ins=[v for v in p['service']['variables'] if v['role']=='IN'];outs=[v for v in p['service']['variables'] if v['role']=='OUT']
    assert len(ins)==2 # ON does not create input fields
    assert [v['field_name'] for v in ins]==['S_TYPE1','S_TYPE2']
    assert [v['field_name'] for v in outs]==['S_STRING1','S_STRING2','S_STRING3','S_STRING4']
    assert len({v['variable_name'] for v in p['service']['variables']})==6
    if join_type=='LEFT':assert any('b.PATNO' in v['db_column'] for v in outs) and any('PATNO: NULL' in w for w in p['warnings'])

@pytest.mark.parametrize('operation',['INSERT','UPDATE','DELETE'])
def test_join_mutations_not_generated(client,operation):
    body=request_body();body['operation']=operation
    r=client.post('/api/sql/prepare',json=body);assert r.status_code==400
    assert 'SELECT' in r.json()['detail']

@pytest.mark.parametrize('bad',['missing_on','unknown_left','unknown_right','type_mismatch','unknown_reference','duplicate_selection'])
def test_join_validation(client,bad):
    body=request_body();j=body['service']['join_tables'][0]
    if bad=='missing_on':j['conditions']=[]
    if bad=='unknown_left':j['conditions'][0]['left_column']='NO_COLUMN'
    if bad=='unknown_right':j['conditions'][0]['right_column']='NO_COLUMN'
    if bad=='type_mismatch':j['conditions'][0]['left_column']='ORDDATE'
    if bad=='unknown_reference':body['selected']=['wrong.PATNO']
    if bad=='duplicate_selection':body['selected']=['PATNO','PATNO']
    assert client.post('/api/sql/prepare',json=body).status_code==400

@pytest.mark.parametrize('bad',['duplicate_alias','invalid_alias','injection_column'])
def test_invalid_join_identifiers(client,bad):
    body=request_body();j=body['service']['join_tables'][0]
    if bad=='duplicate_alias':j['alias']='A'
    if bad=='invalid_alias':j['alias']='b;DELETE'
    if bad=='injection_column':j['conditions'][0]['right_column']='PATNO OR 1=1'
    assert client.post('/api/sql/prepare',json=body).status_code==422

def test_join_save_reopen_manual_mapping_and_dictionary_usage(client):
    body=request_body('LEFT');body['service']['builder_state']={'selected':body['selected'],'conditions':body['conditions'],'order_by':body['order_by']}
    p=client.post('/api/sql/prepare',json=body).json()
    service=p['service'];service['variables'][0]['variable_name']='sManualPatient';service['variables'][0]['is_manual']=True
    service['sql_blocks'][0]['generated_sql']=p['sql'];service['sql_blocks'][0]['final_sql']=p['sql']
    saved=client.post('/api/services',json=service);assert saved.status_code==201,saved.text
    reopened=client.get('/api/services/JOIN_S1').json();assert reopened['join_tables']==service['join_tables']
    again=client.post('/api/sql/prepare',json={**body,'service':reopened});assert again.status_code==200
    assert ':sManualPatient' in again.json()['sql']
    with db.connect() as d:
        assert [r[0] for r in d.execute('SELECT table_name FROM service_tables ORDER BY position')]==['MDMEDORT','APPATBAT']
        assert d.execute('PRAGMA foreign_key_check').fetchall()==[]
    usage=client.get('/api/dictionary/tables/APPATBAT/usage').json();assert usage[0]['service_id']=='JOIN_S1'
    assert set(usage[0]['columns'])=={'PATNO','PATNAME','BIRTHDATE'}
    main=client.get('/api/dictionary/tables/MDMEDORT/usage').json();assert 'PATNO' in main[0]['columns']

def test_same_table_self_join_and_default_main_alias(client):
    body=request_body();body['service']['table_alias']='';body['service']['join_tables'][0]['table_name']='MDMEDORT'
    body['service']['join_tables'][0]['columns']=copy.deepcopy(body['service']['columns']);body['selected']=['PATNO','b.PATNO'];body['conditions']=[];body['order_by']=[]
    r=client.post('/api/sql/prepare',json=body);assert r.status_code==200,r.text
    assert 'FROM MDMEDORT a\nINNER JOIN MDMEDORT b' in r.json()['sql']

def test_multiple_join_conditions_and_nullable_output_warning(client):
    body=request_body('LEFT');body['service']['join_tables'][0]['columns'].append(Column(name='ORDSEQNO',db_type='NUMBER',precision=22,scale=0,length=64).model_dump())
    body['service']['join_tables'][0]['conditions'].append({'left_column':'ORDSEQNO','right_column':'ORDSEQNO'})
    r=client.post('/api/sql/prepare',json=body);assert r.status_code==200,r.text
    assert 'ON a.PATNO = b.PATNO AND a.ORDSEQNO = b.ORDSEQNO' in r.json()['sql']
