"""Add mapping metadata without dropping service definitions or historical snapshots."""
import json
from uuid import uuid5,NAMESPACE_URL
from app.models import Variable

def migrate_mapping_metadata(db):
    if db.execute('SELECT 1 FROM schema_migrations WHERE version=3').fetchone():return
    db.execute('BEGIN IMMEDIATE')
    columns={row[1] for row in db.execute('PRAGMA table_info(variables)')}
    if 'mapping_meta_json' not in columns:db.execute("ALTER TABLE variables ADD COLUMN mapping_meta_json TEXT NOT NULL DEFAULT '{}'")
    for row in db.execute('SELECT service_id,snapshot_json FROM services').fetchall():
        service=json.loads(row['snapshot_json']);sid=row['service_id']
        outer_main=any(j.get('join_type') in {'RIGHT','FULL'} for j in service.get('join_tables',[]))
        catalog={c['name']:{**c,**({'nullable':True} if outer_main else {})} for c in service.get('columns',[])}
        catalog.update({j['alias']+'.'+c['name']:{**c,**({'nullable':True} if j.get('join_type') in {'LEFT','FULL'} else {})} for j in service.get('join_tables',[]) for c in j.get('columns',[])})
        for index,value in enumerate(service.get('variables',[])):
            column=catalog.get(value.get('db_column'),{})
            for field,source,default in [('column_comment','comment',''),('db_length','length',None),('nullable','nullable',True),('precision','precision',None),('scale','scale',None),('date_format','date_format','YYYY-MM-DD')]:value.setdefault(field,column.get(source,default))
            value.setdefault('mapping_id',uuid5(NAMESPACE_URL,f'{sid}/{index}/{value["role"]}/{value["variable_name"]}').hex)
            value.setdefault('sql_bind_name',value['variable_name'] if value['role']=='IN' else '')
            value.setdefault('mapping_status','confirmed' if value.get('is_manual') else 'auto')
            value=Variable(**value).model_dump();service['variables'][index]=value
            db.execute('UPDATE variables SET mapping_meta_json=? WHERE service_id=? AND variable_name=?',(json.dumps(value,ensure_ascii=False),sid,value['variable_name']))
        service.setdefault('mapping_sql_fingerprint','')
        db.execute('UPDATE services SET snapshot_json=? WHERE service_id=?',(json.dumps(service,ensure_ascii=False),sid))
    db.execute('INSERT INTO schema_migrations VALUES(3)')
