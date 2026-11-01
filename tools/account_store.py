"""Offline migration, consistent backup, restore and integrity verification."""
import argparse,json,sqlite3,sys,os
from pathlib import Path
from contextlib import closing
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import database

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('operation',choices=['migrate','verify','backup','restore'])
    parser.add_argument('--database',required=True);parser.add_argument('--target');parser.add_argument('--source');parser.add_argument('--offline',action='store_true')
    args=parser.parse_args();database.DB_PATH=str(Path(args.database).resolve());path=Path(database.DB_PATH)
    if args.operation in ('backup','verify') and not path.is_file():parser.error('database file does not exist')
    if args.operation=='backup':
        if not args.target:parser.error('backup requires --target')
        target=Path(args.target).resolve()
        if target==path or target.exists():parser.error('target must be a new backup file')
        target.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(path)) as src,closing(sqlite3.connect(target)) as dst:src.backup(dst)
        journal=Path(str(path)+'.deletions.jsonl')
        if journal.exists():Path(str(target)+'.deletions.jsonl').write_bytes(journal.read_bytes())
    elif args.operation=='restore':
        if not args.offline or not args.source:parser.error('stop the service first; restore requires --offline --source')
        source=Path(args.source).resolve()
        if not source.is_file() or source==path:parser.error('source must be a separate existing backup')
        # Merge the backup deletion journal into the newer local journal; never replace it.
        source_journal=Path(str(source)+'.deletions.jsonl');target_journal=Path(str(path)+'.deletions.jsonl')
        if source_journal.exists():
            current_journal=target_journal.read_text(encoding='utf-8') if target_journal.exists() else ''
            known=set(current_journal.splitlines())
            with target_journal.open('a',encoding='utf-8') as stream:
                if current_journal and not current_journal.endswith('\n'):stream.write('\n')
                for line in source_journal.read_text(encoding='utf-8').splitlines():
                    if line not in known:stream.write(line+'\n');known.add(line)
                stream.flush();os.fsync(stream.fileno())
        # Preserve current data before restoring. Do not replace the newer deletion journal.
        if path.exists():
            backup=Path(str(path)+'.pre-restore-'+__import__('uuid').uuid4().hex+'.db')
            with closing(sqlite3.connect(path)) as src,closing(sqlite3.connect(backup)) as dst:src.backup(dst)
        with closing(sqlite3.connect(source)) as src,closing(sqlite3.connect(path)) as dst:src.backup(dst)
        database.init_db()
    elif args.operation=='migrate':database.init_db()
    with database.get_conn() as conn:
        integrity=conn.execute('PRAGMA integrity_check').fetchone()[0]
        foreign_keys=conn.execute('PRAGMA foreign_key_check').fetchall()
    if integrity!='ok' or foreign_keys:raise SystemExit('Database integrity verification failed')
    print(json.dumps(dict(operation=args.operation,integrity=integrity,foreign_key_errors=len(foreign_keys))))

if __name__=='__main__':main()
