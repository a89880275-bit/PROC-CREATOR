import sqlite3, json, os
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone
from app.models import Service
DB_PATH=Path(os.environ.get('PROC_MANAGER_DB',Path(__file__).resolve().parent.parent/'data/service_manager.sqlite3'))
@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DB_PATH)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db: yield db
    finally: db.close()
def migrate():
    with connect() as d:
        d.executescript('''
        CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY);
        INSERT OR IGNORE INTO schema_migrations VALUES(1);
        CREATE TABLE IF NOT EXISTS services(service_id TEXT PRIMARY KEY,name TEXT NOT NULL,type TEXT NOT NULL,description TEXT,max_row_count INTEGER,template_id TEXT,current_version INTEGER,created_at TEXT,updated_at TEXT,snapshot_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS service_tables(service_id TEXT REFERENCES services ON DELETE CASCADE,position INTEGER,owner TEXT,table_name TEXT,alias TEXT,UNIQUE(service_id,position));
        CREATE TABLE IF NOT EXISTS columns_cache(connection_profile TEXT,owner TEXT,table_name TEXT,column_name TEXT,data_type TEXT,length INTEGER,precision INTEGER,scale INTEGER,nullable INTEGER,comment TEXT,cached_at TEXT,UNIQUE(connection_profile,owner,table_name,column_name));
        CREATE TABLE IF NOT EXISTS sql_blocks(id INTEGER PRIMARY KEY,service_id TEXT REFERENCES services ON DELETE CASCADE,position INTEGER,block_type TEXT,generated_sql TEXT,final_sql TEXT,is_manual INTEGER,error_policy TEXT,UNIQUE(service_id,position));
        CREATE TABLE IF NOT EXISTS variables(id INTEGER PRIMARY KEY,service_id TEXT REFERENCES services ON DELETE CASCADE,variable_name TEXT,db_column TEXT,db_type TEXT,host_type TEXT,host_length INTEGER,role TEXT,is_manual INTEGER,UNIQUE(service_id,variable_name));
        CREATE TABLE IF NOT EXISTS field_mappings(id INTEGER PRIMARY KEY,service_id TEXT REFERENCES services ON DELETE CASCADE,direction TEXT,position INTEGER,field_name TEXT,variable_id INTEGER REFERENCES variables ON DELETE CASCADE,legacy_flag INTEGER DEFAULT 0,UNIQUE(service_id,direction,position),UNIQUE(service_id,direction,field_name));
        CREATE TABLE IF NOT EXISTS templates(id TEXT PRIMARY KEY,template_type TEXT,version INTEGER,body TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS service_versions(id INTEGER PRIMARY KEY,service_id TEXT REFERENCES services ON DELETE CASCADE,version_no INTEGER,snapshot_json TEXT,change_note TEXT,created_at TEXT,UNIQUE(service_id,version_no));
        CREATE TABLE IF NOT EXISTS generated_files(id INTEGER PRIMARY KEY,service_id TEXT REFERENCES services ON DELETE CASCADE,version_no INTEGER,filename TEXT,content TEXT,sha256 TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY,service_id TEXT,action TEXT,details_json TEXT,created_at TEXT);
        ''')
        from app.services.table_dictionary import migrate_dictionary
        migrate_dictionary(d)
        from app.services.mapping_migration import migrate_mapping_metadata
        migrate_mapping_metadata(d)
        from app.services.proc_storage import migrate_proc_storage
        migrate_proc_storage(d)
def list_services():
    with connect() as d: return [dict(r) for r in d.execute('SELECT service_id,name,type,description,current_version,updated_at,snapshot_json FROM services ORDER BY updated_at DESC')]
def get_service(sid):
    with connect() as d:
        row=d.execute('SELECT snapshot_json FROM services WHERE service_id=?',(sid,)).fetchone()
        return json.loads(row[0]) if row else None
def save(s:Service,create=False):
    now=datetime.now(timezone.utc).isoformat()
    with connect() as d:
        row=d.execute('SELECT current_version,created_at FROM services WHERE service_id=?',(s.service_id,)).fetchone()
        if create and row: raise ValueError('이미 존재하는 서비스 ID입니다.')
        if not create and not row: raise LookupError('서비스가 없습니다.')
        if row and row[0]!=s.current_version: raise ValueError('다른 창에서 변경되었습니다. 다시 열어 주세요.')
        s.current_version=(row[0] if row else 0)+1
        payload=s.model_dump_json()
        d.execute('INSERT INTO services VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(service_id) DO UPDATE SET name=excluded.name,type=excluded.type,description=excluded.description,max_row_count=excluded.max_row_count,template_id=excluded.template_id,current_version=excluded.current_version,updated_at=excluded.updated_at,snapshot_json=excluded.snapshot_json',(s.service_id,s.name,s.type,s.description,s.max_row_count,s.template_id,s.current_version,row[1] if row else now,now,payload))
        for table in ['field_mappings','variables','sql_blocks','service_tables']:
            d.execute(f'DELETE FROM {table} WHERE service_id=?',(s.service_id,))
        d.execute('INSERT INTO service_tables VALUES(?,?,?,?,?)',(s.service_id,0,s.owner,s.table_name,s.table_alias))
        for position,joined in enumerate(s.join_tables,1):
            d.execute('INSERT INTO service_tables VALUES(?,?,?,?,?)',(s.service_id,position,joined.owner,joined.table_name,joined.alias))
        for i,b in enumerate(s.sql_blocks): d.execute('INSERT INTO sql_blocks(service_id,position,block_type,generated_sql,final_sql,is_manual,error_policy) VALUES(?,?,?,?,?,?,?)',(s.service_id,i,b.block_type,b.generated_sql,b.final_sql,b.is_manual,b.error_policy))
        positions={'IN':0,'OUT':0}
        for v in s.variables:
            cur=d.execute('INSERT INTO variables(service_id,variable_name,db_column,db_type,host_type,host_length,role,is_manual,mapping_meta_json) VALUES(?,?,?,?,?,?,?,?,?)',(s.service_id,v.variable_name,v.db_column,v.db_type,v.host_type,v.host_length,v.role,v.is_manual,v.model_dump_json()))
            positions[v.role]+=1
            d.execute('INSERT INTO field_mappings(service_id,direction,position,field_name,variable_id) VALUES(?,?,?,?,?)',(s.service_id,v.role,positions[v.role],v.field_name,cur.lastrowid))
        d.execute('INSERT INTO service_versions(service_id,version_no,snapshot_json,change_note,created_at) VALUES(?,?,?,?,?)',(s.service_id,s.current_version,payload,'MVP 저장',now))
        d.execute('INSERT INTO audit_log(service_id,action,details_json,created_at) VALUES(?,?,?,?)',(s.service_id,'save',json.dumps({'version':s.current_version}),now))
    return s.model_dump()
def delete(sid):
    with connect() as d: return d.execute('DELETE FROM services WHERE service_id=?',(sid,)).rowcount

