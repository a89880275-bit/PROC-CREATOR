"""Reusable metadata dictionary, preview tokens, selective atomic updates and history."""
import json, secrets, hashlib, re
from datetime import datetime, timezone
from app import db
from app.models import Column, IDENT

def now(): return datetime.now(timezone.utc).isoformat()
def migrate_dictionary(d):
    d.executescript('''
    CREATE TABLE IF NOT EXISTS business_tables(owner TEXT NOT NULL,table_name TEXT NOT NULL,revision INTEGER NOT NULL,snapshot_json TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(owner,table_name));
    CREATE TABLE IF NOT EXISTS dictionary_history(id INTEGER PRIMARY KEY,owner TEXT NOT NULL,table_name TEXT NOT NULL,revision INTEGER NOT NULL,before_json TEXT,after_json TEXT NOT NULL,import_id TEXT,created_at TEXT NOT NULL,UNIQUE(owner,table_name,revision));
    CREATE TABLE IF NOT EXISTS excel_imports(id TEXT PRIMARY KEY,filename TEXT NOT NULL,sha256 TEXT NOT NULL,status TEXT NOT NULL,preview_json TEXT NOT NULL,selection_json TEXT,created_at TEXT NOT NULL,applied_at TEXT);
    INSERT OR IGNORE INTO schema_migrations VALUES(2);
    ''')

def lookup(owner,name,d=None):
    if d is None:
        with db.connect() as con: return lookup(owner,name,con)
    r=d.execute('SELECT snapshot_json FROM business_tables WHERE owner=? AND table_name=?',(owner,name)).fetchone()
    return json.loads(r[0]) if r else None

def usage(owner,name,changed=None,d=None):
    if d is None:
        with db.connect() as con: return usage(owner,name,changed,con)
    result=[]
    for row in d.execute('SELECT snapshot_json FROM services'):
        s=json.loads(row[0])
        sources=[dict(owner=s.get('owner',''),table_name=s.get('table_name',''),columns=s.get('columns',[]),prefix='')]
        sources += [dict(owner=j.get('owner',''),table_name=j['table_name'],columns=j.get('columns',[]),prefix=j['alias']+'.') for j in s.get('join_tables',[])]
        matching=[source for source in sources if source['owner'].upper()==owner.upper() and source['table_name'].upper()==name.upper()]
        if not matching:continue
        references={source['prefix']+c['name']:c['name'] for source in matching for c in source['columns']}
        defined=set(references.values())
        state=s.get('builder_state',{})
        tracked=set(state.get('selected',[]))|set(state.get('order_by',[]))
        tracked|={c['column'] for c in state.get('conditions',[]) if 'column' in c}
        tracked|={v['db_column'] for v in s.get('variables',[]) if v['db_column']}
        for joined in s.get('join_tables',[]):
            for condition in joined.get('conditions',[]):
                tracked.add(condition['left_column'])
                tracked.add(joined['alias']+'.'+condition['right_column'])
        tracked={references[ref] for ref in tracked if ref in references}
        manual=any(b.get('is_manual') for b in s.get('sql_blocks',[]))
        names=sorted(tracked or defined)
        # Manual SQL is not fully parsed: conservatively retain definition-based impacts.
        candidates=set(names)|defined if manual else set(names)
        affected=sorted(candidates&set(changed or candidates))
        result.append(dict(service_id=s['service_id'],name=s['name'],columns=names,
                           defined_columns=sorted(defined),affected_columns=affected,
                           has_manual_sql=manual,note='SQL 구성/전문 매핑 기준. 구성 정보가 없으면 보관 컬럼 전체를 후보로 표시합니다. 직접 편집 SQL은 정의 전체로 보수적으로 영향 분석하며 추가 의존성은 수동 확인 필요'))
    return result

def diff(old,new):
    before={c['name']:c for c in (old or {}).get('columns',[])};after={c['name']:c for c in new['columns']};items=[]
    if not old or any(old.get(k,'')!=new.get(k,'') for k in ['comment','tablespace_name']):
        items.append(dict(key='metadata',kind='신규' if not old else '변경',name='테이블 정보',before={k:(old or {}).get(k,'') for k in ['comment','tablespace_name']},after={k:new.get(k,'') for k in ['comment','tablespace_name']}))
    for n in after.keys()|before.keys():
        if n not in before: kind='신규'
        elif n not in after: kind='삭제'
        elif before[n]!=after[n]: kind='변경'
        else: continue
        items.append(dict(key='column:'+n,kind=kind,name=n,before=before.get(n),after=after.get(n)))
    return sorted(items,key=lambda x:x['key'])

def preview(tables,filename,content=b'',errors=None,warnings=None):
    errors=list(errors or []);warnings=list(warnings or []);entries=[];seen=set()
    with db.connect() as d:
        for t in tables:
            try:
                owner=t.get('owner','').upper();name=t['table_name'].upper()
                if not re.fullmatch(IDENT,name) or (owner and not re.fullmatch(IDENT,owner)): raise ValueError('테이블/소유자 식별자가 올바르지 않습니다.')
                if (owner,name) in seen: raise ValueError('중복 테이블입니다.')
                seen.add((owner,name))
                cols=[Column(**c).model_dump() for c in t['columns']]
                if not cols or len({c['name'].upper() for c in cols})!=len(cols): raise ValueError('컬럼이 비어 있거나 중복됩니다.')
                new=dict(owner=owner,table_name=name,comment=t.get('comment',''),tablespace_name=t.get('tablespace_name',''),columns=cols)
                old=lookup(owner,name,d);changes=diff(old,new)
                entries.append(dict(table=new,base_revision=old['revision'] if old else 0,changes=changes,usage=usage(owner,name,[x['name'] for x in changes],d)))
            except (ValueError,KeyError,TypeError) as exc: errors.append(str(exc))
        token=secrets.token_urlsafe(24)
        payload=dict(import_id=token,tables=entries,errors=errors,warnings=warnings)
        d.execute('INSERT INTO excel_imports(id,filename,sha256,status,preview_json,selection_json,created_at,applied_at) VALUES(?,?,?,?,?,?,?,?)',(token,filename,hashlib.sha256(content).hexdigest(),'invalid' if errors else 'preview',json.dumps(payload,ensure_ascii=False),None,now(),None))
    return payload

def commit(token,selections):
    with db.connect() as d:
        d.execute('BEGIN IMMEDIATE')
        row=d.execute('SELECT status,preview_json FROM excel_imports WHERE id=?',(token,)).fetchone()
        if not row or row['status']!='preview': raise ValueError('유효한 미반영 미리보기가 아닙니다.')
        p=json.loads(row['preview_json']);applied=[]
        valid={(e['table']['owner'],e['table']['table_name']):e for e in p['tables']};seen=set()
        for selection in selections:
            key=(selection.get('owner',''),selection['table_name'])
            if key not in valid or key in seen: raise ValueError('선택 테이블이 올바르지 않습니다.')
            seen.add(key);e=valid[key];keys=set(selection['keys']);changes={x['key']:x for x in e['changes']}
            if not keys: continue
            if not keys<=changes.keys(): raise ValueError('선택 변경 항목이 올바르지 않습니다.')
            old=lookup(*key,d)
            if (old['revision'] if old else 0)!=e['base_revision']: raise ValueError('사전이 다른 창에서 변경되었습니다. 다시 미리보기 하세요.')
            new=json.loads(json.dumps(old or dict(owner=key[0],table_name=key[1],comment='',tablespace_name='',columns=[])))
            columns={c['name']:c for c in new['columns']}
            for k in keys:
                c=changes[k]
                if k=='metadata': new.update(c['after'])
                elif c['after'] is None: columns.pop(c['name'],None)
                else: columns[c['name']]=c['after']
            if not columns: raise ValueError('테이블에는 최소 1개 컬럼이 필요합니다.')
            new['columns']=sorted(columns.values(),key=lambda c:(c['column_id'],c['name']));new['revision']=e['base_revision']+1
            stamp=now();raw=json.dumps(new,ensure_ascii=False)
            d.execute('INSERT INTO business_tables VALUES(?,?,?,?,?) ON CONFLICT(owner,table_name) DO UPDATE SET revision=excluded.revision,snapshot_json=excluded.snapshot_json,updated_at=excluded.updated_at',(*key,new['revision'],raw,stamp))
            d.execute('INSERT INTO dictionary_history(owner,table_name,revision,before_json,after_json,import_id,created_at) VALUES(?,?,?,?,?,?,?)',(*key,new['revision'],json.dumps(old,ensure_ascii=False) if old else None,raw,token,stamp))
            applied.append(new)
        if not applied: raise ValueError('반영할 변경 항목을 선택하세요.')
        d.execute('UPDATE excel_imports SET status=?,selection_json=?,applied_at=? WHERE id=?',('applied',json.dumps(selections,ensure_ascii=False),now(),token))
    return dict(tables=applied)

def search(q=''):
    needle=q.casefold();result=[]
    with db.connect() as d:
        for row in d.execute('SELECT snapshot_json,updated_at FROM business_tables ORDER BY owner,table_name'):
            t=json.loads(row[0]);hay=' '.join([t['table_name'],t['comment']]+[c['name']+' '+c['comment'] for c in t['columns']])
            if needle in hay.casefold(): result.append({**t,'updated_at':row[1]})
    return result

def history(owner,name):
    with db.connect() as d:
        return [dict(r) for r in d.execute('SELECT * FROM dictionary_history WHERE owner=? AND table_name=? ORDER BY revision DESC',(owner,name))]
def imports():
    with db.connect() as d:
        return [dict(r) for r in d.execute('SELECT id,filename,sha256,status,created_at,applied_at,selection_json FROM excel_imports ORDER BY created_at DESC LIMIT 100')]

