"""Idempotent additive migration. Existing interview rows remain unclaimed."""
def migrate(db):
    with db.get_conn() as conn:
        conn.execute('BEGIN IMMEDIATE')
        statements = [
            'CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)',
            '''CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT NOT NULL COLLATE NOCASE UNIQUE,
               password_hash TEXT NOT NULL, created_at TEXT NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS user_profiles(user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
               nickname TEXT NOT NULL, major_id TEXT NOT NULL, other_major TEXT NOT NULL DEFAULT '',grade TEXT NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS auth_sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
               created_at REAL NOT NULL,expires_at REAL NOT NULL)''',
            'CREATE INDEX IF NOT EXISTS idx_auth_user ON auth_sessions(user_id)',
            'CREATE INDEX IF NOT EXISTS idx_auth_expiry ON auth_sessions(expires_at)',
            'CREATE TABLE IF NOT EXISTS auth_attempts(subject TEXT NOT NULL, window INTEGER NOT NULL,count INTEGER NOT NULL,PRIMARY KEY(subject,window))',
            '''CREATE TABLE IF NOT EXISTS trial_owners(interview_id TEXT PRIMARY KEY REFERENCES interviews(id) ON DELETE CASCADE,owner_hash TEXT NOT NULL)''',
            'CREATE INDEX IF NOT EXISTS idx_trial_owner ON trial_owners(owner_hash)',
            '''CREATE TABLE IF NOT EXISTS interview_profile_snapshots(interview_id TEXT PRIMARY KEY REFERENCES interviews(id) ON DELETE CASCADE,
               major TEXT NOT NULL,grade TEXT NOT NULL,consent INTEGER NOT NULL,version TEXT NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS reanswers(id TEXT PRIMARY KEY,interview_id TEXT NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
               answer_sequence INTEGER NOT NULL,answer TEXT NOT NULL,request_id TEXT NOT NULL,created_at TEXT NOT NULL,
               scoring_version TEXT NOT NULL,UNIQUE(interview_id,request_id))''',
            '''CREATE TABLE IF NOT EXISTS start_requests(scope_hash TEXT NOT NULL,request_id TEXT NOT NULL,
               request_hash TEXT NOT NULL,state TEXT NOT NULL,runner_id TEXT NOT NULL,token TEXT NOT NULL,
               owner_user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
               interview_id TEXT REFERENCES interviews(id) ON DELETE SET NULL,
               response_json TEXT,error_status INTEGER,created_at REAL NOT NULL,
               PRIMARY KEY(scope_hash,request_id))''',
            'CREATE INDEX IF NOT EXISTS idx_start_request_interview ON start_requests(interview_id)',
            'CREATE INDEX IF NOT EXISTS idx_start_request_expiry ON start_requests(created_at) WHERE interview_id IS NULL',
            '''CREATE TRIGGER IF NOT EXISTS clear_deleted_start_response BEFORE DELETE ON interviews BEGIN
               UPDATE start_requests SET state='deleted',response_json=NULL,interview_id=NULL
               WHERE interview_id=OLD.id; END'''
        ]
        for sql in statements:conn.execute(sql)
        if 'owner_user_id' not in [r[1] for r in conn.execute('PRAGMA table_info(interviews)')]:
            conn.execute('ALTER TABLE interviews ADD COLUMN owner_user_id TEXT REFERENCES users(id) ON DELETE CASCADE')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_interview_user ON interviews(owner_user_id)')
        conn.execute("INSERT OR IGNORE INTO schema_migrations VALUES ('accounts-v1',?)",(db._now(),))
        conn.execute("INSERT OR IGNORE INTO schema_migrations VALUES ('start-requests-v1',?)",(db._now(),))
