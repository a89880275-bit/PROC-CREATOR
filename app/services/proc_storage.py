"""Immutable generation history; no user-controlled filesystem writes."""
import json
from datetime import datetime,timezone
from app import db

def migrate_proc_storage(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS proc_generations(
      id INTEGER PRIMARY KEY,service_id TEXT NOT NULL REFERENCES services(service_id) ON DELETE CASCADE,
      version_no INTEGER NOT NULL,filename TEXT NOT NULL,encoding TEXT NOT NULL,content TEXT NOT NULL,
      sha256 TEXT NOT NULL,service_snapshot_json TEXT NOT NULL,template_id TEXT NOT NULL,
      template_version TEXT NOT NULL,template_sha256 TEXT NOT NULL,settings_json TEXT NOT NULL,
      warnings_json TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS proc_generations_service ON proc_generations(service_id,id);
    INSERT OR IGNORE INTO schema_migrations VALUES(4);
    ''')

def save_generation(service,result,overwrite=False):
    stamp=datetime.now(timezone.utc).isoformat()
    with db.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT current_version FROM services WHERE service_id=?',(service.service_id,)).fetchone()
        if not row:raise LookupError('생성 결과를 저장/다운로드하려면 먼저 서비스를 저장하세요.')
        if row[0]!=service.current_version:raise ValueError('서비스 저장 버전이 변경되었습니다. 다시 열고 미리보기를 생성하세요.')
        exists=con.execute('SELECT 1 FROM proc_generations WHERE service_id=? AND filename=?',(service.service_id,result['filename'])).fetchone()
        if exists and not overwrite:raise FileExistsError('같은 파일명의 생성 이력이 있습니다. 덮어쓰기 확인이 필요합니다. 이전 이력은 보존됩니다.')
        template_body=result['_template_body']
        key=result['template_id']+'@'+result['template_version']+':'+result['template_sha256'][:12]
        con.execute('INSERT OR IGNORE INTO templates VALUES(?,?,?,?,?)',(key,'select',1,template_body,stamp))
        cur=con.execute('INSERT INTO proc_generations(service_id,version_no,filename,encoding,content,sha256,service_snapshot_json,template_id,template_version,template_sha256,settings_json,warnings_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(service.service_id,service.current_version,result['filename'],result['encoding'],result['source'],result['sha256'],service.model_dump_json(),result['template_id'],result['template_version'],result['template_sha256'],service.proc_settings.model_dump_json(),json.dumps(result['warnings'],ensure_ascii=False),stamp))
        con.execute('INSERT INTO generated_files(service_id,version_no,filename,content,sha256,created_at) VALUES(?,?,?,?,?,?)',(service.service_id,service.current_version,result['filename'],result['source'],result['sha256'],stamp))
        con.execute('INSERT INTO audit_log(service_id,action,details_json,created_at) VALUES(?,?,?,?)',(service.service_id,'proc_generate',json.dumps({'generation_id':cur.lastrowid,'filename':result['filename'],'template_version':result['template_version']}),stamp))
        return cur.lastrowid

def get_generation(generation_id):
    with db.connect() as con:
        row=con.execute('SELECT * FROM proc_generations WHERE id=?',(generation_id,)).fetchone()
        return dict(row) if row else None

def list_generations(service_id):
    with db.connect() as con:
        return [dict(r) for r in con.execute('SELECT id,filename,encoding,sha256,version_no,template_version,created_at FROM proc_generations WHERE service_id=? ORDER BY id DESC',(service_id,))]
