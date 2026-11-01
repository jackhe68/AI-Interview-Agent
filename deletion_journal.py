"""Durable deletion hashes kept outside SQLite backups to avoid resurrection on restore."""
import hashlib,json,os,threading
from pathlib import Path
from datetime import datetime,timezone
LOCK=threading.Lock()

def path(db):return Path(str(db.DB_PATH)+'.deletions.jsonl')
def digest(value):return hashlib.sha256(value.encode()).hexdigest()

def record(db,sids=(),uid=None):
    entries=[('interview',sid) for sid in sids]+([('user',uid)] if uid else [])
    if not entries:return
    with LOCK:
        file=path(db);unterminated=False
        if file.exists() and file.stat().st_size:
            with file.open('rb') as previous:previous.seek(-1,os.SEEK_END);unterminated=previous.read(1)!=b'\n'
        with file.open('a',encoding='utf-8') as stream:
            if unterminated:stream.write('\n')  # Separate a crash-torn tail from the next committed deletion.
            for kind,value in entries:
                stream.write(json.dumps(dict(kind=kind,hash=digest(value),at=datetime.now(timezone.utc).isoformat()))+'\n')
            stream.flush();os.fsync(stream.fileno())

def replay(db):
    file=path(db)
    if not file.exists():return
    deleted={'user':set(),'interview':set()}
    for line in file.read_text(encoding='utf-8').splitlines():
        try:
            entry=json.loads(line)
            if entry.get('kind') in deleted and isinstance(entry.get('hash'),str) and len(entry['hash'])==64:deleted[entry['kind']].add(entry['hash'])
        except ValueError:
            # A torn final append precedes a DB commit and does not signify completion.
            continue
    with db.get_conn() as conn:
        conn.execute('BEGIN IMMEDIATE')
        for table,kind in [('interviews','interview'),('users','user')]:
            ids=[row[0] for row in conn.execute('SELECT id FROM '+table) if digest(row[0]) in deleted[kind]]
            for ident in ids:conn.execute('DELETE FROM '+table+' WHERE id=?',(ident,))
