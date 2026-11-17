from pathlib import Path
from collections import Counter
import pytest
from fastapi.testclient import TestClient
from app import db
from app.main import app
from app.models import Column,SQLDraft,Variable
from app.services.sql_analyzer import tokenize,analyze_sql
from app.services.mapping_sync import preview_sync,apply_sync

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'sync.sqlite3')
    with TestClient(app,base_url='http://127.0.0.1:8765') as c:
        c.headers['X-CSRF-Token']=c.get('/api/session').json()['csrf_token'];yield c

def draft(sql,columns=None):
    return SQLDraft(service_id='',table_name='T',columns=columns or [Column(name='PATNO',length=20,comment='환자번호'),Column(name='SEQNO',db_type='NUMBER',precision=10,scale=0,length=64),Column(name='MEDDATE',db_type='DATE',length=19),Column(name='AMOUNT',db_type='NUMBER',precision=12,scale=2,length=64)],sql_blocks=[{'final_sql':sql}])
def apply(s,**kwargs):return apply_sync(s,preview_sync(s)['fingerprint'],**kwargs)

@pytest.mark.parametrize('count',range(1,11))
def test_get_1_through_10(count):
    columns=[Column(name='C'+str(i)) for i in range(1,count+1)]
    s=draft('SELECT C1 FROM T WHERE '+' AND '.join(c.name+' = :p'+str(i) for i,c in enumerate(columns,1)),columns)
    result=apply(s);inputs=[v for v in result.variables if v.role=='IN']
    assert [v.field_name for v in inputs]==['S_TYPE'+str(i) for i in range(1,count+1)]
@pytest.mark.parametrize('count',range(1,101))
def test_put_1_through_100(count):
    columns=[Column(name='C'+str(i)) for i in range(1,count+1)];s=draft('SELECT '+', '.join(c.name for c in columns)+' FROM T',columns)
    outputs=[v for v in apply(s).variables if v.role=='OUT'];assert len(outputs)==count
    assert outputs[-1].field_name=='S_STRING'+str(count)
@pytest.mark.parametrize('role,count',[('IN',11),('OUT',101)])
def test_limits_reject(role,count):
    columns=[Column(name='C'+str(i)) for i in range(1,count+1)]
    sql='SELECT C1 FROM T WHERE '+' AND '.join(c.name+'=:p'+str(i) for i,c in enumerate(columns,1)) if role=='IN' else 'SELECT '+','.join(c.name for c in columns)+' FROM T'
    s=draft(sql,columns);assert preview_sync(s)['errors']
    with pytest.raises(ValueError):apply(s)

def test_lexer_excludes_strings_comments_qquotes_and_assignment():
    tokens=tokenize("BEGIN :actual := ':fake'; -- :comment\n/* :hidden */ x := q'[a :not_bind]'; y := 'it''s :no'; :other := 1; END;")
    assert [t.text for t in tokens if t.kind=='bind']==['actual','other']
@pytest.mark.parametrize('sql',["SELECT 'oops FROM T","SELECT PATNO FROM T /* no end",'SELECT (PATNO FROM T'])
def test_unclosed_sql_rejected(sql):
    with pytest.raises(ValueError):analyze_sql(draft(sql))

def test_repeated_input_dedup_and_input_output_names():
    s=apply(draft("SELECT PATNO FROM T WHERE PATNO=:sPatno OR PATNO=:sPatno OR ':fake'=':fake'"))
    assert len([v for v in s.variables if v.role=='IN'])==1
    assert [v.variable_name for v in s.variables]==['sPatno','sPatnoOut']

def test_type_naming_precision_and_date():
    s=apply(draft("SELECT PATNO, SEQNO, MEDDATE, AMOUNT FROM T WHERE PATNO=:sPatno AND SEQNO=:iSeqno AND MEDDATE=TO_DATE(:sMeddate,'YYYY-MM-DD') AND AMOUNT=:dAmount"))
    assert [v.variable_name for v in s.variables if v.role=='OUT']==['sPatnoOut','iSeqnoOut','sMeddateOut','dAmountOut']
    assert s.variables[1].host_type=='asciz'

def test_manual_name_order_preserved_and_bind_rewrite_is_token_based():
    s=apply(draft("SELECT PATNO,SEQNO FROM T WHERE PATNO=:sPatno AND SEQNO=:iSeqno AND ':sPatno'='x'"))
    inputs=[v for v in s.variables if v.role=='IN'];outputs=[v for v in s.variables if v.role=='OUT']
    inputs[0].variable_name='sUserPatient';inputs[0].is_manual=True
    s.variables=[inputs[1],inputs[0],outputs[1],outputs[0]]
    for v in s.variables:v.order_manual=True
    plan=preview_sync(s);assert any(r['rewrite_bind'] for r in plan['rows'])
    before=[v.variable_name for v in s.variables];result=apply_sync(s,plan['fingerprint'])
    assert [v.variable_name for v in result.variables]==before
    assert 'PATNO=:sUserPatient' in result.sql_blocks[0].final_sql
    assert "':sPatno'" in result.sql_blocks[0].final_sql
    assert [v.field_name for v in result.variables if v.role=='IN']==['S_TYPE1','S_TYPE2']

def test_sql_edit_add_remove_requires_confirmation_choice():
    s=apply(draft('SELECT PATNO,SEQNO FROM T WHERE PATNO=:sPatno'))
    removed=next(v for v in s.variables if v.role=='OUT' and v.db_column=='SEQNO');removed.is_manual=True;removed.variable_name='sKeepSeq'
    s.sql_blocks[0].final_sql='SELECT PATNO, AMOUNT FROM T WHERE PATNO=:sPatno AND AMOUNT=:dNewAmount'
    plan=preview_sync(s);assert removed.mapping_id in [v['mapping_id'] for v in plan['removed']]
    kept=apply_sync(s,plan['fingerprint']);assert any(v.variable_name=='sKeepSeq' and not v.is_active for v in kept.variables)
    deleted=apply_sync(s,plan['fingerprint'],remove_ids=[removed.mapping_id]);assert all(v.mapping_id!=removed.mapping_id for v in deleted.variables)
    assert any(v.variable_name=='dNewAmount' and v.role=='IN' for v in deleted.variables)

def test_output_reorder_only_on_explicit_request():
    s=apply(draft('SELECT PATNO,SEQNO FROM T'));before=[v.mapping_id for v in s.variables]
    for v in s.variables:v.order_manual=True
    s.sql_blocks[0].final_sql='SELECT SEQNO,PATNO FROM T'
    assert [v.mapping_id for v in apply(s).variables]==before
    result=apply(s,reorder_outputs=True);assert [v.db_column for v in result.variables]==['SEQNO','PATNO']
    assert [v.field_name for v in result.variables]==['S_STRING1','S_STRING2']

def test_computed_aliases_and_unknown_expression_type_confirmation():
    s=draft("SELECT COUNT(*) AS CNT,SUM(AMOUNT) AS TOTAL,AMOUNT*2 AS DOUBLE_AMOUNT,NVL(PATNO,'-') AS LABEL FROM T")
    plan=preview_sync(s);label=next(r for r in plan['rows'] if r['output_alias']=='LABEL');assert label['metadata'] is None
    with pytest.raises(ValueError):apply(s)
    result=apply(s,overrides={label['key']:{'metadata':Column(name='LABEL',length=30,comment='표시명').model_dump()}})
    assert [v.variable_name for v in result.variables]==['iCntOut','dTotalOut','dDouble_amountOut','sLabelOut']
    assert result.variables[-1].source_expression=="NVL(PATNO,'-')"
    assert result.variables[-1].mapping_status=='confirmed'
@pytest.mark.parametrize('sql',["SELECT COUNT(*) FROM T",'SELECT PATNO AS X, SEQNO AS X FROM T','BEGIN :p := 1; END;','SELECT PATNO FROM T; DELETE FROM T;'])
def test_unsafe_or_ambiguous_sync_not_claimed_complete(sql):
    s=draft(sql)
    with pytest.raises(ValueError):apply(s)

def test_unknown_bind_manual_source_resolution():
    s=draft('SELECT PATNO FROM T WHERE :unknown IS NOT NULL')
    plan=preview_sync(s);assert plan['rows'][0]['status']=='unmapped'
    c=s.columns[0];result=apply(s,overrides={'IN:unknown':{'db_column':'PATNO'}})
    assert result.variables[0].db_column=='PATNO'

def test_stale_preview_rejected_and_no_mutation():
    s=draft('SELECT PATNO FROM T');p=preview_sync(s);s.sql_blocks[0].final_sql='SELECT SEQNO FROM T'
    with pytest.raises(ValueError,match='미리보기'):apply_sync(s,p['fingerprint'])
    assert s.variables==[]

def test_host_collision_and_number22_int_rejected():
    s=draft('SELECT PATNO FROM T WHERE PATNO=:sPatno')
    with pytest.raises(ValueError,match='충돌'):apply(s,overrides={'OUT:1':{'variable_name':'sPatno'}})
    s=draft('SELECT BIG FROM T',[Column(name='BIG',db_type='NUMBER',precision=22,scale=0,length=64)])
    with pytest.raises(ValueError,match='범위'):apply(s,overrides={'OUT:1':{'host_type':'int'}})

def test_sync_api_save_reopen_full_mapping_contract(client):
    s=draft('SELECT PATNO, AMOUNT*2 AS TOTAL FROM T WHERE PATNO=:sPatno');s.service_id='SYNC_S1'
    p=client.post('/api/mappings/sync/preview',json={'service':s.model_dump()});assert p.status_code==200,p.text
    body={'service':s.model_dump(),'fingerprint':p.json()['fingerprint']}
    result=client.post('/api/mappings/sync/apply',json=body);assert result.status_code==200,result.text
    data=result.json()['service'];data['variables'][0]['variable_name']='sManual';data['variables'][0]['is_manual']=True
    r=client.post('/api/services',json=data);assert r.status_code==201,r.text
    reopened=client.get('/api/services/SYNC_S1').json();assert reopened['variables']==data['variables']
    with db.connect() as d:
        stored=d.execute('SELECT mapping_meta_json FROM variables ORDER BY id').fetchall()
        assert len(stored)==3 and all('source_expression' in r[0] for r in stored)
        assert d.execute('PRAGMA foreign_key_check').fetchall()==[]

def test_v2_migration_preserves_custom_names_sql_order_and_history(client):
    import json
    from app.services.mapping_migration import migrate_mapping_metadata
    s=apply(draft('SELECT PATNO,SEQNO FROM T WHERE PATNO=:sPatno'));s.service_id='LEGACY_S1';s.variables[0].variable_name='sLegacy';s.variables[0].is_manual=True
    client.post('/api/services',json=s.model_dump())
    with db.connect() as d:
        before=d.execute('SELECT snapshot_json FROM services').fetchone()[0];payload=json.loads(before)
        for v in payload['variables']:
            for field in ['mapping_id','column_comment','source_expression','output_alias','mapping_status','order_manual','precision','scale','date_format','sql_bind_name','source_position','is_active']:v.pop(field,None)
        d.execute('UPDATE services SET snapshot_json=?',(json.dumps(payload),));d.execute('DELETE FROM schema_migrations WHERE version=3');d.execute('ALTER TABLE variables DROP COLUMN mapping_meta_json')
        history=d.execute('SELECT snapshot_json FROM service_versions').fetchall()
    db.migrate();db.migrate()
    data=client.get('/api/services/LEGACY_S1').json()
    assert data['variables'][0]['variable_name']=='sLegacy' and data['variables'][0]['is_manual']
    assert data['sql_blocks']==payload['sql_blocks']
    assert len({v['mapping_id'] for v in data['variables']})==3
    assert data['variables'][0]['column_comment']=='환자번호'
    with db.connect() as d:assert d.execute('SELECT snapshot_json FROM service_versions').fetchall()==history

def test_unknown_arithmetic_word_requires_type_confirmation():
    for sql in ['SELECT AMOUNT + UNKNOWN_COLUMN AS VALUE FROM T','SELECT AMOUNT * AMOUNT AS VALUE FROM T','SELECT AMOUNT * 1.5 AS VALUE FROM T',"SELECT TO_CHAR(AMOUNT,'FM99999990D00') AS VALUE FROM T"]:
        p=preview_sync(draft(sql));assert p['rows'][0]['metadata'] is None

def test_unknown_source_wildcard_not_expanded_as_known_table():
    p=preview_sync(draft('SELECT * FROM UNKNOWN_TABLE'))
    assert p['errors'] and p['rows']==[]

def test_extract_from_is_not_a_table_clause():
    p=preview_sync(draft('SELECT PATNO,EXTRACT(YEAR FROM MEDDATE) AS YEAR1 FROM T'))
    assert p['rows'][0]['metadata']['db_type']=='VARCHAR2'
    assert p['rows'][1]['metadata'] is None

def test_expression_source_column_description_preserved():
    p=preview_sync(draft("SELECT TO_CHAR(MEDDATE,'YYYY-MM-DD') AS DAY FROM T",[Column(name='MEDDATE',db_type='DATE',length=19,comment='진료일자')]))
    assert p['rows'][0]['metadata']['comment']=='진료일자'
    assert p['rows'][0]['db_column']=='MEDDATE'

def test_legacy_outer_join_result_nullability_migration(client):
    import json
    s=SQLDraft(service_id='LEFT_LEGACY',table_name='T',table_alias='a',columns=[Column(name='ID',nullable=False)],join_tables=[{'table_name':'U','alias':'b','join_type':'LEFT','columns':[Column(name='ID',nullable=False).model_dump()],'conditions':[{'left_column':'ID','right_column':'ID'}]}],sql_blocks=[{'final_sql':'SELECT a.ID AS MAIN_ID,b.ID AS JOIN_ID FROM T a LEFT JOIN U b ON b.ID=a.ID'}])
    s=apply(s);client.post('/api/services',json=s.model_dump())
    with db.connect() as d:
        raw=json.loads(d.execute('SELECT snapshot_json FROM services').fetchone()[0])
        for v in raw['variables']:v.pop('nullable',None)
        d.execute('UPDATE services SET snapshot_json=?',(json.dumps(raw),));d.execute('DELETE FROM schema_migrations WHERE version=3')
    db.migrate();raw=client.get('/api/services/LEFT_LEGACY').json()
    values={v['db_column']:v['nullable'] for v in raw['variables']}
    assert values=={'ID':False,'b.ID':True}
