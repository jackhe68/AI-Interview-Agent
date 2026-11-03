"""Additive migration preserves synthetic pre-account records and is repeatable."""
import sqlite3,sys,tempfile,hashlib,json,subprocess
from contextlib import closing
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import database
with tempfile.TemporaryDirectory() as directory:
 path=Path(directory)/'legacy.db';database.DB_PATH=str(path)
 with closing(sqlite3.connect(path)) as conn:
  conn.execute('CREATE TABLE interviews(id TEXT PRIMARY KEY,job TEXT NOT NULL,difficulty TEXT NOT NULL,started_at TEXT NOT NULL,ended_at TEXT,status TEXT NOT NULL,current_question INTEGER NOT NULL DEFAULT 1,followup_count INTEGER NOT NULL DEFAULT 0)')
  conn.execute("INSERT INTO interviews VALUES ('synthetic-legacy','Java 后端','校招标准','2026-10-30T20:00:00',NULL,'active',1,0)");conn.commit()
  original=tuple(conn.execute('SELECT * FROM interviews').fetchone())
 database.init_db();database.init_db()
 with database.get_conn() as conn:
  row=tuple(conn.execute('SELECT * FROM interviews').fetchone());assert row[:-1]==original and row[-1] is None
  assert {r[0] for r in conn.execute('SELECT version FROM schema_migrations')}=={'accounts-v1','start-requests-v1'}
  assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]
 backup=Path(directory)/'backup.db'
 subprocess.run([sys.executable,str(ROOT/'tools/account_store.py'),'backup','--database',str(path),'--target',str(backup)],check=True,capture_output=True)
 subprocess.run([sys.executable,str(ROOT/'tools/account_store.py'),'restore','--database',str(path),'--source',str(backup),'--offline'],check=True,capture_output=True)
 with database.get_conn() as conn:assert tuple(conn.execute('SELECT * FROM interviews').fetchone())[:-1]==original
 Path(str(backup)+'.deletions.jsonl').write_text(json.dumps(dict(kind='interview',hash=hashlib.sha256(b'synthetic-legacy').hexdigest()))+'\n',encoding='utf-8')
 existing=json.dumps(dict(kind='user',hash=hashlib.sha256(b'not-a-real-user').hexdigest()))+'\n'
 Path(str(path)+'.deletions.jsonl').write_text(existing+'{\"kind\":',encoding='utf-8')
 subprocess.run([sys.executable,str(ROOT/'tools/account_store.py'),'restore','--database',str(path),'--source',str(backup),'--offline'],check=True,capture_output=True)
 with database.get_conn() as conn:assert conn.execute('SELECT count(*) FROM interviews').fetchone()[0]==0
 assert existing in Path(str(path)+'.deletions.jsonl').read_text(encoding='utf-8')
 print('PASS repeatable migration preserves legacy columns and unclaimed ownership; offline backup/restore CLI passes integrity checks')
