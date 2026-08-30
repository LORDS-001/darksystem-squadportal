#!/usr/bin/env python3
import base64, hashlib, hmac, json, logging, os, re, secrets, smtplib, sqlite3, threading, time
from datetime import datetime, timezone
from email.message import EmailMessage
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent

def load_dotenv_file():
    env_file = ROOT / '.env'
    if not env_file.exists(): return
    for raw in env_file.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        key, value = line.split('=', 1)
        key = key.strip(); value = value.strip().strip('\"').strip("'")
        os.environ.setdefault(key, value)

load_dotenv_file()
DB_PATH = ROOT / 'dark_system.sqlite3'
DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
PORT = int(os.getenv('PORT') or '8080')
HOST = os.getenv('HOST', '0.0.0.0')
SESSION_SECRET = os.getenv('DARK_SYSTEM_SESSION_SECRET', 'change-this-in-production')
OWNER_SETUP_SECRET = os.getenv('OWNER_SETUP_SECRET', '').strip()
DEMO_DATA = os.getenv('DARK_SYSTEM_DEMO_DATA', '0') == '1'
COOKIE_NAME = 'dark_system_session'
SESSION_TTL = 60 * 60 * 24 * 7
RATE_LIMIT_WINDOW = 300
RATE_LIMIT_MAX = 12
RECOVERY_TTL = 600
RATE_LIMITS = {}
SQUAD_ROLES = ('Squad Owner', 'Squad Leader', 'Assistant Squad Leader', 'Squad Member')
SQUAD_MEMBER_STATUSES = ('Online', 'Offline', 'Disabled')
COMMUNITY_ACCOUNT_STATUSES = ('Active', 'Disabled')
OWNER_CONTENT_DOMAINS = ('announcements', 'reports', 'complaints', 'events', 'notifications')
OWNER_CONTENT_STATE_DOMAINS = ('announcements', 'reports', 'complaints', 'events')
OWNER_CONTENT_FIELDS = {
    'announcements': ('id', 'title', 'body', 'author', 'authorId', 'createdAt', 'updatedAt', 'time'),
    'reports': ('id', 'title', 'body', 'memberId', 'values', 'time', 'files', 'author', 'authorId', 'createdAt', 'updatedAt'),
    'complaints': ('id', 'subject', 'title', 'body', 'memberId', 'time', 'files', 'response', 'respondedBy', 'author', 'authorId', 'createdAt', 'updatedAt'),
    'events': ('id', 'title', 'date', 'time', 'rules', 'body', 'description', 'author', 'authorId', 'createdAt', 'updatedAt'),
    'notifications': ('id', 'title', 'message', 'audienceId', 'read', 'action', 'targetType', 'targetId', 'author', 'authorId', 'createdAt', 'updatedAt'),
}
OWNER_CONTENT_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$')
OWNER_TOURNAMENT_FIELDS = (
    'title', 'game', 'format', 'date', 'time', 'slots', 'reward', 'rules',
    'registrationDeadline', 'squadSlots', 'membersPerSquad',
    'registrationOpen', 'squadRegistrationOpen',
)
OWNER_TOURNAMENT_TEXT_LIMITS = {
    'title': 200, 'game': 120, 'format': 80, 'date': 10, 'time': 20,
    'reward': 1000, 'rules': 8000, 'registrationDeadline': 40,
}
OWNER_MATCH_STATUSES = ('Pending', 'Scheduled', 'Ready', 'In Progress', 'Postponed', 'Cancelled')

PUBLIC_STATIC_FILES = {
    '/': 'index.html',
    '/index.html': 'index.html',
    '/owner-admin': 'owner-admin.html',
    '/owner-admin/': 'owner-admin.html',
    '/style.css': 'style.css',
    '/script.js': 'script.js',
    '/owner-admin.css': 'owner-admin.css',
    '/owner-admin.js': 'owner-admin.js',
    '/owner-admin-api.js': 'owner-admin-api.js',
    '/owner-admin-squad.js': 'owner-admin-squad.js',
    '/owner-admin-tournaments.js': 'owner-admin-tournaments.js',
    '/owner-admin-seasons.js': 'owner-admin-seasons.js',
    '/owner-admin-audit.js': 'owner-admin-audit.js',
    '/assets/mlbb/birthday-mage.jpg': 'assets/mlbb/birthday-mage.jpg',
    '/assets/mlbb/bunny-gunner.jpg': 'assets/mlbb/bunny-gunner.jpg',
    '/assets/mlbb/cafe-welcome.jpg': 'assets/mlbb/cafe-welcome.jpg',
    '/assets/mlbb/celestial-mage.jpg': 'assets/mlbb/celestial-mage.jpg',
    '/assets/mlbb/dark-archer.jpg': 'assets/mlbb/dark-archer.jpg',
    '/assets/mlbb/hero-dragon.jpg': 'assets/mlbb/hero-dragon.jpg',
    '/assets/mlbb/ice-archer.jpg': 'assets/mlbb/ice-archer.jpg',
    '/assets/mlbb/neon-warrior.jpg': 'assets/mlbb/neon-warrior.jpg',
    '/assets/mlbb/pink-mage.jpg': 'assets/mlbb/pink-mage.jpg',
}

LOCK = threading.RLock()

def now_iso():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

class ClosingSQLiteConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()

class PostgresCompat:
    def __init__(self, conn):
        self.conn = conn
    def _sql(self, sql):
        return sql.replace('INSERT OR IGNORE', 'INSERT') if False else sql.replace('?', '%s')
    def execute(self, sql, params=()):
        sql = sql.replace('INSERT OR IGNORE INTO', 'INSERT INTO').replace('?', '%s')
        # Preserve SQLite's INSERT OR IGNORE semantics for the small number of seed rows.
        if 'INSERT INTO app_state' in sql and 'ON CONFLICT' not in sql and 'VALUES' in sql:
            sql = sql + ' ON CONFLICT DO NOTHING'
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return cur
    def executemany(self, sql, seq):
        sql = sql.replace('?', '%s')
        cur = self.conn.cursor(); cur.executemany(sql, seq); return cur
    def executescript(self, script):
        cur = self.conn.cursor()
        for statement in [x.strip() for x in script.split(';') if x.strip()]:
            cur.execute(statement)
        return cur
    def commit(self): self.conn.commit()
    def rollback(self): self.conn.rollback()
    def close(self): self.conn.close()
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type: self.conn.rollback()
            else: self.conn.commit()
        finally: self.conn.close()

def db():
    if DATABASE_URL:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError('PostgreSQL mode requires psycopg[binary].') from exc
        return PostgresCompat(psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10, prepare_threshold=None))
    c = sqlite3.connect(DB_PATH, timeout=10, factory=ClosingSQLiteConnection)
    c.row_factory = sqlite3.Row
    return c

def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 210_000)
    return base64.urlsafe_b64encode(salt).decode() + '$' + base64.urlsafe_b64encode(digest).decode()

def verify_password(password, encoded):
    try:
        salt_b64, digest_b64 = encoded.split('$', 1)
        salt = base64.urlsafe_b64decode(salt_b64.encode())
        expected = base64.urlsafe_b64decode(digest_b64.encode())
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 210_000)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False

def hash_recovery_code(code):
    return hash_password(str(code))

def verify_recovery_code(code, encoded):
    stored=str(encoded or '')
    return verify_password(str(code),stored) or ('$' not in stored and hmac.compare_digest(str(code),stored))

def access_code_matches(code, row):
    submitted = str(code or '').strip().upper()
    encoded = row['access_code_hash'] if 'access_code_hash' in row.keys() else None
    if encoded:
        return verify_password(submitted, encoded)
    return workflow_code_matches(submitted, row['access_code'])

def sign(value):
    sig = hmac.new(SESSION_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()
    return value + '.' + sig

def unsign(value):
    try:
        raw, sig = value.rsplit('.', 1)
        expected = hmac.new(SESSION_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected): return None
        payload = json.loads(base64.urlsafe_b64decode(raw + '=' * (-len(raw) % 4)).decode())
        if payload.get('exp', 0) < time.time(): return None
        return payload
    except Exception:
        return None

def session_token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()

def create_session_record(connection, user_type, user_id, role='Community Member'):
    token = secrets.token_urlsafe(32)
    expires = int(time.time()) + SESSION_TTL
    connection.execute(
        'INSERT INTO sessions(token,type,user_id,role,expires) VALUES(?,?,?,?,?)',
        (session_token_hash(token), user_type, str(user_id), role, expires),
    )
    connection.execute('DELETE FROM sessions WHERE expires<=?', (int(time.time()),))
    return token

def create_session(user_type, user_id, role='Community Member'):
    with LOCK, db() as c:
        token = create_session_record(c, user_type, user_id, role)
        c.commit()
    return token

def sanitize_audit_details(connection, details):
    secret_values=bootstrap_secret_values(connection)
    session_token_hashes={str(row['token']) for row in connection.execute('SELECT token FROM sessions').fetchall() if row['token']}
    cleaned=sanitize_overview_value(details or {}, secret_values, session_token_hashes)
    return {} if cleaned is _OVERVIEW_OMIT else cleaned

def insert_audit(connection, session, action, target_type='', target_id='', details=None):
    connection.execute(
        'INSERT INTO audit_log(id,actor_type,actor_id,actor_role,action,target_type,target_id,created_at,details) VALUES(?,?,?,?,?,?,?,?,?)',
        (
            'A'+secrets.token_hex(8),
            session.get('type'),
            str(session.get('id')),
            session.get('role'),
            action,
            target_type,
            str(target_id or ''),
            now_iso(),
            json.dumps(sanitize_audit_details(connection, details), separators=(',', ':')),
        ),
    )

def init_db():
    with LOCK, db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS squad_members (
          id TEXT PRIMARY KEY, name TEXT, ign TEXT NOT NULL, game_id TEXT, server_id TEXT,
          role TEXT NOT NULL, lane TEXT, email TEXT, phone TEXT, birthday TEXT,
          access_code TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Offline', last_login TEXT,
          profile_complete INTEGER NOT NULL DEFAULT 1, account_activated INTEGER NOT NULL DEFAULT 1,
          recovery_pending INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS community_accounts (
          id TEXT PRIMARY KEY, squad_member_id TEXT, ign TEXT NOT NULL, game_id TEXT, server_id TEXT,
          email TEXT NOT NULL UNIQUE, phone TEXT, password_hash TEXT NOT NULL, role TEXT,
          lane TEXT, created_at TEXT, email_notifications INTEGER NOT NULL DEFAULT 1,
          reset_code TEXT, reset_expires INTEGER, linked_squad INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'Active'
        );
        CREATE TABLE IF NOT EXISTS app_state (
          key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, type TEXT, user_id TEXT, role TEXT, expires INTEGER);
        CREATE TABLE IF NOT EXISTS owner_accounts (id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit_log (id TEXT PRIMARY KEY, actor_type TEXT, actor_id TEXT, actor_role TEXT, action TEXT, target_type TEXT, target_id TEXT, created_at TEXT NOT NULL, details TEXT);
        CREATE TABLE IF NOT EXISTS login_throttle (key TEXT PRIMARY KEY, window_started INTEGER NOT NULL, attempts INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS login_throttle_window_started_idx ON login_throttle(window_started);
        CREATE TABLE IF NOT EXISTS notifications (id TEXT PRIMARY KEY, domain TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notification_reads (notification_id TEXT NOT NULL, recipient_type TEXT NOT NULL, recipient_id TEXT NOT NULL, read_at TEXT NOT NULL, PRIMARY KEY(notification_id,recipient_type,recipient_id));
        CREATE TABLE IF NOT EXISTS recovery_codes (
          id TEXT PRIMARY KEY, account_type TEXT NOT NULL, account_id TEXT NOT NULL,
          code_hash TEXT NOT NULL, expires_at INTEGER NOT NULL, used_at INTEGER, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS recovery_codes_account_idx ON recovery_codes(account_type,account_id,created_at);
        ''')
        if isinstance(c, PostgresCompat):
            columns = {
                row['column_name'] for row in c.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='community_accounts'"
                ).fetchall()
            }
        else:
            columns = {row['name'] for row in c.execute('PRAGMA table_info(community_accounts)').fetchall()}
        if 'status' not in columns:
            c.execute("ALTER TABLE community_accounts ADD COLUMN status TEXT NOT NULL DEFAULT 'Active'")
        if isinstance(c, PostgresCompat):
            squad_columns = {
                row['column_name'] for row in c.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='squad_members'"
                ).fetchall()
            }
        else:
            squad_columns = {row['name'] for row in c.execute('PRAGMA table_info(squad_members)').fetchall()}
        if 'access_code_hash' not in squad_columns:
            c.execute("ALTER TABLE squad_members ADD COLUMN access_code_hash TEXT")
        if 'recovery_pending' not in squad_columns:
            c.execute("ALTER TABLE squad_members ADD COLUMN recovery_pending INTEGER NOT NULL DEFAULT 0")
        duplicate_ign = c.execute(
            "SELECT lower(ign) FROM squad_members GROUP BY lower(ign) HAVING COUNT(*)>1 LIMIT 1"
        ).fetchone()
        if duplicate_ign:
            raise RuntimeError('Cannot apply Squad identity uniqueness migration while duplicate IGN records exist.')
        for column in ('game_id', 'server_id'):
            duplicate = c.execute(
                f"SELECT {column} FROM squad_members WHERE {column} IS NOT NULL AND {column}<>'' GROUP BY {column} HAVING COUNT(*)>1 LIMIT 1"
            ).fetchone()
            if duplicate:
                raise RuntimeError(f'Cannot apply Squad identity uniqueness migration while duplicate {column} records exist.')
        duplicate_owners = c.execute(
            "SELECT role FROM squad_members WHERE role='Squad Owner' GROUP BY role HAVING COUNT(*)>1"
        ).fetchone()
        if duplicate_owners:
            raise RuntimeError('Cannot apply Squad Owner uniqueness migration while multiple Squad Owners exist.')
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS squad_members_ign_ci_unique_idx ON squad_members(lower(ign))')
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS squad_members_game_id_unique_idx ON squad_members(game_id) WHERE game_id IS NOT NULL AND game_id<>''")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS squad_members_server_id_unique_idx ON squad_members(server_id) WHERE server_id IS NOT NULL AND server_id<>''")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS squad_members_one_owner_unique_idx ON squad_members(role) WHERE role='Squad Owner'")
        count = c.execute('SELECT COUNT(*) AS n FROM squad_members').fetchone()['n']
        if count == 0 and DEMO_DATA:
            seed = [
              ('1','Dark System Owner','OWNER','000000','0000','Squad Owner','','','','','DS-OWNER','Offline',None,1,1),
              ('2','Demo Leader','LEADER','111111','1111','Squad Leader','Mid Lane','','','','DS-LEADER','Offline',None,1,1),
              ('3','Demo Assistant','ASSIST','222222','2222','Assistant Squad Leader','Roam','','','','DS-ASSIST','Offline',None,1,1),
              ('4','Demo Member','MEMBER','333333','3333','Squad Member','Gold Lane','','','','DS-MEMBER','Offline',None,1,1),
              ('5','New Demo Member','NEWBIE','444444','4444','Squad Member','','','','','SQM-DEMO1','Offline',None,0,0),
            ]
            c.executemany('''INSERT INTO squad_members
              (id,name,ign,game_id,server_id,role,lane,email,phone,birthday,access_code,status,last_login,profile_complete,account_activated)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', seed)
            for member in seed:
                c.execute('UPDATE squad_members SET access_code_hash=?,access_code=? WHERE id=?',(hash_password(member[10]),'',member[0]))
        c.execute("INSERT INTO app_state(key,value) VALUES('owner_setup_complete','false') ON CONFLICT(key) DO NOTHING")
        for key, value in [
          ('announcements', json.dumps([{'id':1,'title':'Welcome to Dark System V4','body':'The squad portal is ready for testing.','author':'Dark System Owner','time':now_iso()}])),
          ('reports','[]'),('complaints','[]'),('events','[]'),('reportConfig', json.dumps({'title':'Squad Report','description':'Complete the current squad report format below.','fields':[{'id':'reportTitle','label':'Report Title','type':'text','required':True},{'id':'reportDetails','label':'Report Details','type':'textarea','required':True}]})),
          ('tournaments', json.dumps([
            {'id':'T1','title':'Dark System 1v1 Challenge','game':'Mobile Legends: Bang Bang','format':'1v1','date':'2026-09-05','time':'18:00','slots':32,'status':'Open','reward':'Grand Prize','rules':'Standard Dark System tournament rules apply.'},
            {'id':'T2','title':'Dark System Squad vs Squad','game':'Mobile Legends: Bang Bang','format':'5v5','date':'2026-09-12','time':'18:00','slots':10,'status':'Open','reward':'Tournament Rewards','rules':'Teams must register with eligible players.'}
          ])),
          ('registrations','[]'),('tournamentManagers','[]'),('seasonPoints','{}'),('seasonHistory','[]'),('seasonHallOfFame','[]'),('eventParticipation','[]'),('hallOfFame','[]'),('squadTournamentApprovals','[]'),('currentSeason','null'),('community_notifications','[]')
        ]:
            c.execute('INSERT INTO app_state(key,value) VALUES(?,?) ON CONFLICT(key) DO NOTHING', (key,value))
        c.commit()

def state_get(c, key, default):
    row = c.execute('SELECT value FROM app_state WHERE key=?', (key,)).fetchone()
    if not row: return default
    try: return json.loads(row['value'])
    except Exception: return default

def state_set(c, key, value):
    c.execute('INSERT INTO app_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, json.dumps(value, separators=(',', ':'))))

def lock_state_workflow(connection):
    """Serialize app_state read/modify/write workflows across processes."""
    if isinstance(connection, PostgresCompat):
        connection.execute('SELECT pg_advisory_xact_lock(?)', (1146313043,))
    else:
        connection.execute('BEGIN IMMEDIATE')

def remove_tournament_manager_permission(connection, member_id):
    member_id=str(member_id)
    managers=state_get(connection,'tournamentManagers',[])
    if not isinstance(managers,list):managers=[]
    def identity(item):
        if isinstance(item,dict):return str(item.get('id') or item.get('accountId') or '')
        return str(item)
    updated=[item for item in managers if identity(item)!=member_id]
    if len(updated)!=len(managers):state_set(connection,'tournamentManagers',updated)
    return len(updated)!=len(managers)

def safe_owner_content_item(domain, item):
    if domain not in OWNER_CONTENT_DOMAINS or not isinstance(item, dict):
        return None
    result={}
    for key in OWNER_CONTENT_FIELDS[domain]:
        if key not in item: continue
        clean=sanitize_content_metadata(item[key], string_limit=4000 if key in ('values','files') else 8000)
        if clean is not _CONTENT_OMIT: result[key]=clean
    return result

_CONTENT_OMIT = object()
_CONTENT_SECRET_KEY = re.compile(r'(?:password|access.?code|token|reset|secret|credential)', re.I)
def sanitize_content_metadata(value, depth=0, string_limit=8000):
    if depth > 5: return _CONTENT_OMIT
    if isinstance(value, str):
        return _CONTENT_OMIT if len(value) > string_limit or re.search(r'(?:access\s*code|password|reset\s*code|session\s*token)\s*[:=]', value, re.I) else value
    if value is None or isinstance(value, (bool, int, float)): return value
    if isinstance(value, list):
        if len(value) > 30: return _CONTENT_OMIT
        return [clean for item in value if (clean := sanitize_content_metadata(item, depth + 1, string_limit)) is not _CONTENT_OMIT]
    if isinstance(value, dict):
        if len(value) > 50: return _CONTENT_OMIT
        return {str(key): clean for key, item in value.items() if len(str(key)) <= 80 and not _CONTENT_SECRET_KEY.search(str(key)) and (clean := sanitize_content_metadata(item, depth + 1, string_limit)) is not _CONTENT_OMIT}
    return _CONTENT_OMIT

def validate_content_metadata(value, expected):
    if not isinstance(value, expected): return None
    clean=sanitize_content_metadata(value, string_limit=4000)
    if clean is _CONTENT_OMIT or clean != value or len(json.dumps(clean,separators=(',',':')).encode()) > 16000: return None
    return clean

def owner_content_items(connection, domain, notification_domain=None):
    if domain == 'notifications':
        items = []
        query = 'SELECT id,payload FROM notifications'
        params = ()
        if notification_domain:
            query += ' WHERE domain=?'; params = (notification_domain,)
        for row in connection.execute(query + ' ORDER BY id ASC', params).fetchall():
            try:
                payload = json.loads(row['payload'])
            except Exception:
                continue
            if isinstance(payload, dict):
                payload['id'] = str(row['id'])
                item = safe_owner_content_item(domain, payload)
                if item:
                    items.append(item)
        return items
    items = state_get(connection, domain, [])
    return [item for raw in items if (item := safe_owner_content_item(domain, raw))]

def owner_content_text(data, existing, key, required=False, maximum=4000):
    value = data[key] if key in data else existing.get(key, '')
    if not isinstance(value, str):
        return None, f'{key} must be text.'
    value = value.strip()
    if required and not value:
        return None, f'{key} is required.'
    if len(value) > maximum:
        return None, f'{key} is too long.'
    return value, None

def normalize_owner_content(domain, data, item_id, existing=None):
    if domain not in OWNER_CONTENT_DOMAINS:
        return None, 'Unsupported Squad content domain.'
    if item_id and not OWNER_CONTENT_ID.fullmatch(item_id):
        return None, 'Content id is invalid.'
    existing = existing if isinstance(existing, dict) else {}
    identifier = item_id or str(existing.get('id') or 'SC-' + secrets.token_hex(8))
    if not OWNER_CONTENT_ID.fullmatch(identifier):
        return None, 'Content id is invalid.'
    item = dict(existing)
    item.update({
        'id': identifier,
        'createdAt': str(existing.get('createdAt') or now_iso()),
        'updatedAt': now_iso(),
        'author': str(existing.get('author') or 'Overall Owner'),
    })
    if existing.get('authorId') is not None:
        item['authorId'] = str(existing['authorId'])
    if domain == 'announcements':
        for key, required, maximum in (('title', True, 180), ('body', True, 8000)):
            value, error = owner_content_text(data, existing, key, required, maximum)
            if error: return None, error
            item[key] = value
        time_value, error = owner_content_text(data, existing, 'time', False, 40)
        if error: return None, error
        item['time'] = time_value or str(existing.get('time') or item['createdAt'])
    elif domain == 'reports':
        title, error = owner_content_text(data, existing, 'title', False, 180)
        if error: return None, error
        body, error = owner_content_text(data, existing, 'body', True, 8000)
        if error: return None, error
        if title: item['title'] = title
        item['body'] = body
        for key in ('memberId', 'values', 'files', 'time'):
            value = data.get(key, existing.get(key))
            if key == 'values' and value is not None and (value := validate_content_metadata(value, dict)) is None: return None, 'values must be a safe object.'
            if key == 'files' and value is not None and (value := validate_content_metadata(value, list)) is None: return None, 'files must be a safe list.'
            if value is not None: item[key] = str(value) if key in ('memberId', 'time') else value
    elif domain == 'complaints':
        subject, error = owner_content_text(data, existing, 'subject', False, 180)
        if error: return None, error
        body, error = owner_content_text(data, existing, 'body', True, 8000)
        if error: return None, error
        if subject: item['subject'] = subject; item['title'] = subject
        item['body'] = body
        for key in ('memberId', 'files', 'time', 'response', 'respondedBy'):
            value = data.get(key, existing.get(key))
            if key == 'files' and value is not None and (value := validate_content_metadata(value, list)) is None: return None, 'files must be a safe list.'
            if value is not None: item[key] = str(value) if key in ('memberId', 'time', 'response', 'respondedBy') else value
    elif domain == 'events':
        title, error = owner_content_text(data, existing, 'title', True, 180)
        if error: return None, error
        date, error = owner_content_text(data, existing, 'date', True, 10)
        if error: return None, error
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
            return None, 'date must use YYYY-MM-DD.'
        time_value, error = owner_content_text(data, existing, 'time', False, 5)
        if error: return None, error
        if time_value and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', time_value):
            return None, 'time must use HH:MM.'
        description, error = owner_content_text(data, existing, 'description', False, 8000)
        if error: return None, error
        item.update(title=title, date=date)
        if time_value: item['time'] = time_value
        body, error = owner_content_text(data, existing, 'body', False, 8000)
        if error: return None, error
        rules, error = owner_content_text(data, existing, 'rules', False, 8000)
        if error: return None, error
        if body or description: item['body'] = body or description; item['description'] = description or body
        if rules: item['rules'] = rules
    else:
        title, error = owner_content_text(data, existing, 'title', True, 180)
        if error: return None, error
        message, error = owner_content_text(data, existing, 'message', True, 4000)
        if error: return None, error
        item.update(title=title, message=message)
        audience = data['audienceId'] if 'audienceId' in data else existing.get('audienceId')
        if audience is not None:
            if not isinstance(audience, (str, int)) or not str(audience).strip():
                return None, 'audienceId must be a non-empty identifier.'
            item['audienceId'] = str(audience).strip()
        read = data['read'] if 'read' in data else existing.get('read', False)
        if not isinstance(read, bool):
            return None, 'read must be true or false.'
        item['read'] = read
        for key in ('action', 'targetType', 'targetId'):
            if key in existing:
                item[key] = existing[key]
    return item, None

def notification_target_exists(connection, notification_domain, audience_id):
    if not audience_id:
        return True
    table = 'squad_members' if notification_domain == 'squad' else 'community_accounts'
    return bool(connection.execute(f'SELECT 1 FROM {table} WHERE id=?', (str(audience_id),)).fetchone())

def notification_portal_item(item):
    result = dict(item)
    result['body'] = str(item.get('body') or item.get('message') or '')
    result['time'] = str(item.get('time') or item.get('createdAt') or now_iso())
    result['type'] = str(item.get('type') or item.get('action') or 'notice')
    return result

def notification_for_recipient(connection, item, recipient_type, recipient_id):
    result=notification_portal_item(item)
    result['read']=notification_is_read(connection,str(item.get('id','')),recipient_type,recipient_id)
    return result

def notification_is_read(connection, notification_id, recipient_type, recipient_id):
    return bool(connection.execute('SELECT 1 FROM notification_reads WHERE notification_id=? AND recipient_type=? AND recipient_id=?',(notification_id,recipient_type,str(recipient_id))).fetchone())

def mark_notification_read(connection, notification_id, recipient_type, recipient_id):
    connection.execute('INSERT INTO notification_reads(notification_id,recipient_type,recipient_id,read_at) VALUES(?,?,?,?) ON CONFLICT(notification_id,recipient_type,recipient_id) DO UPDATE SET read_at=excluded.read_at',(notification_id,recipient_type,str(recipient_id),now_iso()))

def create_owner_notification(connection, session, action, target_type, target_id, title, message, notification_domain='squad', audience_id=None):
    item = {
        'id': 'ON-' + secrets.token_hex(8), 'title': title, 'message': message,
        'action': action, 'targetType': target_type, 'targetId': str(target_id),
        'author': 'Overall Owner', 'authorId': str(session.get('id')), 'read': False,
        'createdAt': now_iso(), 'updatedAt': now_iso(),
    }
    if audience_id is not None: item['audienceId'] = str(audience_id)
    connection.execute(
        'INSERT INTO notifications(id,domain,payload) VALUES(?,?,?)',
        (item['id'], notification_domain, json.dumps(item, separators=(',', ':'))),
    )
    return item

def safe_owner_tournament_value(connection, value):
    secret_values=bootstrap_secret_values(connection)
    session_hashes={str(row['token']) for row in connection.execute('SELECT token FROM sessions').fetchall() if row['token']}
    cleaned=sanitize_workflow_value(value,secret_values,session_hashes)
    return {} if cleaned is _OVERVIEW_OMIT else cleaned

def owner_tournament_by_id(tournaments, tournament_id):
    return next((item for item in tournaments if isinstance(item,dict) and str(item.get('id'))==str(tournament_id)),None)

def owner_tournament_projection(connection, tournament):
    tournament_id=str(tournament.get('id',''))
    registrations=[item for item in state_get(connection,'registrations',[]) if isinstance(item,dict) and str(item.get('tournamentId'))==tournament_id]
    approvals=[item for item in state_get(connection,'squadTournamentApprovals',[]) if isinstance(item,dict) and str(item.get('tournamentId'))==tournament_id]
    safe_tournament=safe_owner_tournament_value(connection,tournament)
    matches=safe_tournament.get('matches',[]) if isinstance(safe_tournament,dict) else []
    submissions=[]; disputes=[]
    for match in matches if isinstance(matches,list) else []:
        submission=match.get('submission') if isinstance(match,dict) else None
        if isinstance(submission,dict):
            record={'matchId':match.get('id'),**submission}; submissions.append(record)
            if overview_status(submission.get('status'))=='disputed':disputes.append(record)
    return {
        'tournament':safe_tournament,
        'registrations':safe_owner_tournament_value(connection,registrations),
        'approvals':safe_owner_tournament_value(connection,approvals),
        'bracket':{'ready':bool(tournament.get('bracketReady')),'generatedAt':tournament.get('bracketGeneratedAt'),'matches':matches},
        'matches':matches,'resultSubmissions':submissions,'disputes':disputes,
    }

def normalize_owner_tournament(data, existing=None):
    existing=existing if isinstance(existing,dict) else {}
    unknown=set(data)-set(OWNER_TOURNAMENT_FIELDS)
    if unknown:return None,'Unsupported tournament field.'
    item={key:existing[key] for key in OWNER_TOURNAMENT_FIELDS if key in existing}
    for key in OWNER_TOURNAMENT_TEXT_LIMITS:
        if key not in data:continue
        value=data[key]
        if not isinstance(value,str):return None,f'{key} must be text.'
        value=value.strip()
        if len(value)>OWNER_TOURNAMENT_TEXT_LIMITS[key]:return None,f'{key} is too long.'
        item[key]=value
    for key in ('slots','squadSlots','membersPerSquad'):
        if key not in data:continue
        value=data[key]
        if isinstance(value,bool) or not isinstance(value,int) or value<1 or value>1024:return None,f'{key} must be a positive integer.'
        item[key]=value
    for key in ('registrationOpen','squadRegistrationOpen'):
        if key not in data:continue
        if not isinstance(data[key],bool):return None,f'{key} must be true or false.'
        item[key]=data[key]
    if not existing:
        for key in ('title','game','format','date'):
            if not str(item.get(key,'')).strip():return None,f'{key} is required.'
        item.setdefault('slots',16); item.setdefault('registrationOpen',True)
        if item.get('format')=='Squad vs Squad':item.setdefault('squadRegistrationOpen',True)
    elif 'date' in item and item['date'] and not re.fullmatch(r'\d{4}-\d{2}-\d{2}',item['date']):
        return None,'date must use YYYY-MM-DD.'
    if item.get('date') and not re.fullmatch(r'\d{4}-\d{2}-\d{2}',item['date']):return None,'date must use YYYY-MM-DD.'
    return item,None

def generate_owner_bracket(tournament, registrations):
    entrants=[str(item.get('accountId')) for item in registrations if item.get('accountId') is not None and overview_status(item.get('status')) in ('registered','approved')]
    if len(entrants)<2:return None,'At least two eligible registrations are required.'
    size=1
    while size<len(entrants):size*=2
    entrants += [None]*(size-len(entrants))
    rounds=[]; round_size=size; match_number=1
    while round_size>1:
        current=[]
        for _ in range(round_size//2):
            current.append({'id':f"{tournament['id']}-M{match_number}",'number':match_number,'round':len(rounds)+1,'player1':None,'player2':None,'winner':None,'submission':None})
            match_number+=1
        rounds.append(current); round_size//=2
    for index,entrant in enumerate(entrants):
        rounds[0][index//2]['player1' if index%2==0 else 'player2']=entrant
    for round_index,current in enumerate(rounds[:-1]):
        for match_index,match in enumerate(current):
            target=rounds[round_index+1][match_index//2]
            match['nextMatchId']=target['id']; match['nextSlot']='player1' if match_index%2==0 else 'player2'
    matches=[match for current in rounds for match in current]
    for match in rounds[0]:
        if bool(match.get('player1')) != bool(match.get('player2')):
            match['winner']=match.get('player1') or match.get('player2')
            target=owner_tournament_by_id(matches,match.get('nextMatchId'))
            if target:target[match['nextSlot']]=match['winner']
    return matches,None

def public_member(r, include_secret=False):
    d = dict(r)
    d.pop('access_code_hash', None)
    d.pop('recovery_pending', None)
    d['profileComplete'] = bool(d.pop('profile_complete', 1))
    d['accountActivated'] = bool(d.pop('account_activated', 1))
    d['gameId'] = d.pop('game_id', '')
    d['serverId'] = d.pop('server_id', '')
    d['lastLogin'] = d.pop('last_login', None)
    if not include_secret: d.pop('access_code', None)
    else: d['accessCode'] = d.pop('access_code', '')
    return d

def public_account(r):
    d = dict(r)
    for k in ['password_hash','reset_code','reset_expires','status']:
        d.pop(k, None)
    d['squadMemberId'] = d.pop('squad_member_id', None)
    d['gameId'] = d.pop('game_id','')
    d['serverId'] = d.pop('server_id','')
    d['createdAt'] = d.pop('created_at', None)
    d['emailNotifications'] = bool(d.pop('email_notifications',1))
    d['linkedSquad'] = bool(d.pop('linked_squad',0))
    return d

def public_bootstrap_member(r):
    member = public_member(r)
    return {
        key: member[key]
        for key in ('id', 'name', 'ign', 'gameId', 'serverId', 'role', 'lane', 'status', 'profileComplete', 'accountActivated')
        if key in member
    }

def public_bootstrap_tournament(tournament):
    if not isinstance(tournament, dict):
        return None
    return {
        key: tournament[key]
        for key in ('id', 'title', 'game', 'format', 'date', 'time', 'slots', 'status', 'reward', 'rules')
        if key in tournament
    }

def safe_owner_squad_member(r):
    member = public_member(r)
    return {
        key: member[key]
        for key in ('id', 'name', 'ign', 'gameId', 'serverId', 'role', 'lane', 'email', 'phone', 'birthday', 'status', 'lastLogin', 'profileComplete', 'accountActivated')
        if key in member
    }

def safe_owner_community_account(r):
    account = public_account(r)
    account['status'] = dict(r).get('status', 'Active')
    return {
        key: account[key]
        for key in ('id', 'squadMemberId', 'ign', 'gameId', 'serverId', 'email', 'phone', 'role', 'lane', 'createdAt', 'emailNotifications', 'linkedSquad', 'status')
        if key in account
    }

def public_bootstrap_account(r):
    account = public_account(r)
    return {
        key: account[key]
        for key in ('id', 'squadMemberId', 'ign', 'gameId', 'serverId', 'role', 'lane', 'createdAt', 'linkedSquad')
        if key in account
    }

def bootstrap_secret_values(c):
    values=set()
    for query, column in (
        ('SELECT access_code FROM squad_members', 'access_code'),
        ('SELECT password_hash FROM community_accounts', 'password_hash'),
        ('SELECT reset_code FROM community_accounts WHERE reset_code IS NOT NULL', 'reset_code'),
        ('SELECT password_hash FROM owner_accounts', 'password_hash'),
    ):
        for row in c.execute(query).fetchall():
            if row[column]: values.add(str(row[column]))
    return values

def bootstrap(session):
    with LOCK, db() as c:
        members = [public_bootstrap_member(r) for r in c.execute('SELECT * FROM squad_members').fetchall()]
        accounts = [public_bootstrap_account(r) for r in c.execute('SELECT * FROM community_accounts').fetchall()]
        tournaments = [
            item for tournament in state_get(c, 'tournaments', [])
            if (item := public_bootstrap_tournament(tournament)) is not None
        ]
        community = {'accounts': accounts, 'tournaments': tournaments}
        squad = {
            'members': members,
            'announcements': state_get(c, 'announcements', []),
            'events': state_get(c, 'events', []),
        }
        if not session:
            return {'squad':squad,'community':community}

        secret_values=bootstrap_secret_values(c)
        session_token_hashes={str(row['token']) for row in c.execute('SELECT token FROM sessions').fetchall() if row['token']}
        sanitize=lambda value: sanitize_overview_value(value, secret_values, session_token_hashes)
        safe_state=lambda key, default: sanitize(state_get(c, key, default))
        session_type=session.get('type')
        session_id=str(session.get('id'))
        tournament_managers=safe_state('tournamentManagers', [])
        tournament_admin=tournament_manager_identity(session, tournament_managers)
        registrations=safe_state('registrations', [])
        raw_approvals=state_get(c, 'squadTournamentApprovals', [])
        if session_type == 'community' and not tournament_admin:
            raw_approvals=[
                item for item in raw_approvals
                if isinstance(item, dict) and str(item.get('leaderAccountId')) == session_id
            ]
            approvals=[
                sanitize_workflow_value(
                    item,
                    secret_values,
                    session_token_hashes,
                    {'memberAccessCode'} if item.get('status') == 'Approved' else frozenset(),
                )
                for item in raw_approvals
            ]
        else:
            approval_code_keys=_WORKFLOW_ACCESS_CODE_KEYS if tournament_admin else frozenset()
            approvals=sanitize_workflow_value(
                raw_approvals, secret_values, session_token_hashes, approval_code_keys
            )
        notifications=safe_state('community_notifications', [])
        event_participation=safe_state('eventParticipation', [])
        if session_type == 'community' and not tournament_admin:
            registrations=[item for item in registrations if isinstance(item, dict) and str(item.get('accountId')) == session_id]
            event_participation=[item for item in event_participation if isinstance(item, dict) and str(item.get('accountId')) == session_id]
        notifications=[
            item for item in notifications
            if isinstance(item, dict) and (not item.get('audienceId') or str(item.get('audienceId')) == session_id)
        ]
        notifications += [
            notification_for_recipient(c, item, 'community', session_id)
            for item in owner_content_items(c, 'notifications', 'community')
            if not item.get('audienceId') or str(item.get('audienceId')) == session_id
        ]
        community={
            'accounts':accounts,
            'tournaments':sanitize_workflow_value(
                state_get(c, 'tournaments', []),
                secret_values,
                session_token_hashes,
                {'leaderAccessCode'} if tournament_admin else frozenset(),
            ),
            'registrations':registrations,
            'tournamentManagers':tournament_managers,
            'notifications':notifications,
            'seasonPoints':safe_state('seasonPoints', {}),
            'seasonHistory':safe_state('seasonHistory', []),
            'seasonHallOfFame':safe_state('seasonHallOfFame', []),
            'eventParticipation':event_participation,
            'currentSeason':safe_state('currentSeason', None),
            'hallOfFame':safe_state('hallOfFame', []),
            'squadTournamentApprovals':approvals,
        }
        if session_type == 'squad':
            privileged=session.get('role') in ('Squad Owner', 'Squad Leader', 'Assistant Squad Leader')
            if privileged:
                squad['members']=[public_member(row, True) for row in c.execute('SELECT * FROM squad_members').fetchall()]
            reports=safe_state('reports', [])
            squad.update({
                'reports':reports if privileged else [item for item in reports if isinstance(item, dict) and str(item.get('memberId')) == session_id],
                'complaints':safe_state('complaints', []) if privileged else [],
                'reportConfig':safe_state('reportConfig', {}),
                'notifications':[
                    notification_for_recipient(c, item, 'squad', session_id)
                    for item in owner_content_items(c, 'notifications', 'squad')
                    if not item.get('audienceId') or str(item.get('audienceId')) == session_id
                ],
            })
        return {'squad':squad,'community':community}

def request_header(handler, name, default=''):
    value = handler.headers.get(name)
    if value is not None: return value
    wanted = name.lower()
    for key, value in handler.headers.items():
        if key.lower() == wanted: return value
    return default

def auth_from_cookie(handler):
    raw = request_header(handler, 'Cookie')
    c = SimpleCookie(); c.load(raw)
    morsel = c.get(COOKIE_NAME)
    if not morsel: return None
    token_hash = session_token_hash(morsel.value)
    with LOCK, db() as connection:
        row = connection.execute(
            'SELECT type,user_id,role,expires FROM sessions WHERE token=?', (token_hash,)
        ).fetchone()
        if not row: return None
        if int(row['expires']) <= int(time.time()):
            connection.execute('DELETE FROM sessions WHERE token=?', (token_hash,))
            connection.commit()
            return None
        user_type = row['type']
        user_id = str(row['user_id'])
        if user_type == 'owner':
            account = connection.execute(
                'SELECT id FROM owner_accounts WHERE id=?', (user_id,)
            ).fetchone()
            current_role = 'Overall Owner' if account else None
        elif user_type == 'squad':
            account = connection.execute(
                'SELECT role,status,account_activated FROM squad_members WHERE id=?', (user_id,)
            ).fetchone()
            unavailable = account and (str(account['status'] or '').strip().lower() == 'disabled' or not account['account_activated'])
            current_role = (account['role'] or 'Squad Member') if account and not unavailable else None
        elif user_type == 'community':
            account = connection.execute(
                'SELECT role,status FROM community_accounts WHERE id=?', (user_id,)
            ).fetchone()
            disabled = account and str(account['status'] or '').strip().lower() == 'disabled'
            current_role = (account['role'] or 'Community Member') if account and not disabled else None
        else:
            current_role = None
        if current_role is None:
            connection.execute('DELETE FROM sessions WHERE token=?', (token_hash,))
            connection.commit()
            return None
        if row['role'] != current_role:
            connection.execute(
                'UPDATE sessions SET role=? WHERE token=?', (current_role, token_hash)
            )
            connection.commit()
    return {'type': user_type, 'id': user_id, 'role': current_role, 'exp': int(row['expires'])}

def revoke_session(handler):
    raw = request_header(handler, 'Cookie')
    c = SimpleCookie(); c.load(raw)
    morsel = c.get(COOKIE_NAME)
    if not morsel: return
    with LOCK, db() as connection:
        connection.execute('DELETE FROM sessions WHERE token=?', (session_token_hash(morsel.value),))
        connection.commit()

def json_response(h, data, status=200, headers=None):
    raw = json.dumps(data, ensure_ascii=False).encode()
    h.send_response(status); h.send_header('Content-Type','application/json; charset=utf-8'); h.send_header('Content-Length',str(len(raw)))
    if headers:
        for k,v in headers.items(): h.send_header(k,v)
    h.end_headers(); h.wfile.write(raw)

def read_json(h):
    if hasattr(h, '_parsed_json'):
        return h._parsed_json
    n = int(request_header(h, 'Content-Length', '0') or 0)
    raw = h.rfile.read(n) if n else b'{}'
    try:
        value = json.loads(raw.decode() or '{}')
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}

def json_bool(data, key, current):
    if key not in data:
        return bool(current), None
    value = data[key]
    if isinstance(value, bool):
        return value, None
    if isinstance(value, int) and value in (0, 1):
        return bool(value), None
    return None, f'{key} must be true or false.'

def require_auth(h, types=None):
    s = auth_from_cookie(h)
    if not s or (types and s.get('type') not in types):
        json_response(h, {'error':'Authentication required'}, 401); return None
    return s

def require_overall_owner(h):
    session = require_auth(h)
    if not session:
        return None
    if session.get('type') != 'owner' or session.get('role') != 'Overall Owner':
        json_response(h, {'error':'Overall Owner permission required.'}, 403)
        return None
    return session

def revoke_user_sessions(connection, user_type, user_id):
    connection.execute(
        'DELETE FROM sessions WHERE type=? AND user_id=?', (user_type, str(user_id))
    )

def owner_list_options(handler, roles, statuses):
    query = parse_qs(urlparse(handler.path).query, keep_blank_values=True)
    search = str(query.get('search', [''])[0]).strip()
    role = str(query.get('role', [''])[0]).strip()
    status = str(query.get('status', [''])[0]).strip()
    cursor = str(query.get('cursor', [''])[0]).strip()
    raw_limit = str(query.get('limit', ['25'])[0]).strip()
    try:
        limit = int(raw_limit)
    except ValueError:
        return None, 'limit must be a whole number.'
    if not 1 <= limit <= 100:
        return None, 'limit must be between 1 and 100.'
    if role and role not in roles:
        return None, 'The requested role filter is invalid.'
    if status and status not in statuses:
        return None, 'The requested status filter is invalid.'
    return {
        'search': search, 'role': role, 'status': status,
        'cursor': cursor, 'limit': limit,
    }, None

def identity_conflict(connection, table, ign, game_id, server_id, excluded_id=None):
    clauses = ['(lower(ign)=? OR game_id=? OR server_id=?)']
    params = [str(ign).strip().lower(), str(game_id).strip(), str(server_id).strip()]
    if excluded_id is not None:
        clauses.append('id!=?')
        params.append(str(excluded_id))
    return connection.execute(
        f"SELECT id FROM {table} WHERE {' AND '.join(clauses)} LIMIT 1", tuple(params)
    ).fetchone() is not None

def unique_constraint_violation(error):
    if isinstance(error, sqlite3.IntegrityError):
        return True
    code = getattr(error, 'sqlstate', None) or getattr(error, 'pgcode', None)
    return code == '23505' or 'unique' in str(error).lower()

def request_is_https(h):
    forwarded_proto = request_header(h, 'X-Forwarded-Proto')
    return forwarded_proto.split(',', 1)[0].strip().lower() == 'https' or h.server.server_address[1] == 443

def session_cookie(h, token):
    secure = '; Secure' if request_is_https(h) else ''
    return f'{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL}{secure}'

def set_session(h, token):
    h.send_header('Set-Cookie', session_cookie(h, token))

def clear_session_cookie(h):
    secure = '; Secure' if request_is_https(h) else ''
    return f'{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0{secure}'

def clear_session(h):
    h.send_header('Set-Cookie', clear_session_cookie(h))

def overview_secret_key(key):
    normalized = ''.join(ch for ch in str(key).lower() if ch.isalnum())
    return any(part in normalized for part in ('password', 'accesscode', 'resetcode', 'recoverycode', 'token', 'credential', 'secret', 'code'))

_OVERVIEW_OMIT = object()
_EMBEDDED_AUDIT_SECRET = re.compile(
    r'(?i)(\b(?:password|passphrase|token|credential|secret|access[ _-]?code|reset[ _-]?code|recovery[ _-]?code|code)\b\s*(?:=|:|\bis\b|\bwas\b)\s*)([^\s,;]+)'
)

def redact_embedded_audit_secrets(value):
    return _EMBEDDED_AUDIT_SECRET.sub(r'\1[redacted]', value)

def sanitize_overview_value(value, secret_values, session_token_hashes):
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if overview_secret_key(key):
                continue
            safe_item = sanitize_overview_value(item, secret_values, session_token_hashes)
            if safe_item is not _OVERVIEW_OMIT:
                cleaned[str(key)] = safe_item
        return cleaned
    if isinstance(value, (list, tuple)):
        return [item for value_item in value if (item := sanitize_overview_value(value_item, secret_values, session_token_hashes)) is not _OVERVIEW_OMIT]
    if isinstance(value, str):
        if value in secret_values or session_token_hash(value) in session_token_hashes:
            return _OVERVIEW_OMIT
        return redact_embedded_audit_secrets(value)
    return value

_WORKFLOW_ACCESS_CODE_KEYS = {'leaderAccessCode', 'memberAccessCode'}

def sanitize_workflow_value(value, secret_values, session_token_hashes, allowed_code_keys=frozenset()):
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if key in allowed_code_keys and isinstance(item, str):
                cleaned[str(key)] = item
                continue
            if overview_secret_key(key):
                continue
            safe_item = sanitize_workflow_value(item, secret_values, session_token_hashes, allowed_code_keys)
            if safe_item is not _OVERVIEW_OMIT:
                cleaned[str(key)] = safe_item
        return cleaned
    if isinstance(value, (list, tuple)):
        return [item for value_item in value if (item := sanitize_workflow_value(value_item, secret_values, session_token_hashes, allowed_code_keys)) is not _OVERVIEW_OMIT]
    if isinstance(value, str):
        if value in secret_values or session_token_hash(value) in session_token_hashes:
            return _OVERVIEW_OMIT
        return redact_embedded_audit_secrets(value)
    return value

def overview_details(raw_details, secret_values, session_token_hashes):
    try:
        details = json.loads(raw_details or '{}')
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    details = sanitize_overview_value(details, secret_values, session_token_hashes)
    return {} if details is _OVERVIEW_OMIT else details

def overview_status(value):
    return ''.join(ch for ch in str(value or '').lower() if ch.isalnum())

def pending_overview_result(match):
    submission = match.get('submission')
    if isinstance(submission, dict):
        return overview_status(submission.get('status')) not in ('confirmed', 'ownerapproved', 'rejected')
    return overview_status(match.get('resultStatus')) in (
        'pending', 'pendingconfirmation', 'awaitingconfirmation', 'awaitingreview', 'disputed'
    )

def tournament_manager_identity(session, managers):
    if session.get('role') in ('Overall Owner', 'Squad Owner', 'Tournament Manager'):
        return True
    session_id = str(session.get('id'))
    for item in managers if isinstance(managers, (list, tuple)) else ():
        identities=(item.get('id'),item.get('accountId')) if isinstance(item,dict) else (item,)
        if any(identity is not None and str(identity)==session_id for identity in identities):
            return True
    return False

def registration_deadline_expired(value):
    deadline=str(value or '').strip()
    if not deadline:return False
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}',deadline):deadline=f'{deadline}T23:59:59Z'
    try: expires_at=datetime.fromisoformat(deadline.replace('Z','+00:00'))
    except ValueError:return True
    if expires_at.tzinfo is None:expires_at=expires_at.replace(tzinfo=timezone.utc)
    return expires_at.timestamp()<=time.time()

def workflow_code_matches(submitted, expected):
    submitted_code = str(submitted or '').strip().upper()
    expected_code = str(expected or '').strip().upper()
    return bool(submitted_code and expected_code) and hmac.compare_digest(submitted_code, expected_code)

def request_ip(h):
    return (request_header(h, 'X-Forwarded-For').split(',')[0].strip() or h.client_address[0])

def rate_limited(h, bucket):
    now=time.time(); key=(request_ip(h),bucket)
    with LOCK:
        hits=[t for t in RATE_LIMITS.get(key,[]) if now-t < RATE_LIMIT_WINDOW]
        hits.append(now); RATE_LIMITS[key]=hits
        return len(hits) > RATE_LIMIT_MAX

def durable_rate_limited(h, bucket, identity='', max_attempts=None):
    now = int(time.time())
    cutoff = now - RATE_LIMIT_WINDOW
    durable_key = hashlib.sha256(
        f'{request_ip(h)}\0{bucket}\0{str(identity).strip().lower()}'.encode('utf-8')
    ).hexdigest()
    with LOCK, db() as connection:
        connection.execute(
            'DELETE FROM login_throttle WHERE window_started<=?',
            (now - (RATE_LIMIT_WINDOW * 2),),
        )
        row = connection.execute(
            '''INSERT INTO login_throttle(key,window_started,attempts)
               VALUES(?,?,1)
               ON CONFLICT(key) DO UPDATE SET
                 attempts=CASE
                   WHEN login_throttle.window_started<=? THEN 1
                   ELSE login_throttle.attempts+1
                 END,
                 window_started=CASE
                   WHEN login_throttle.window_started<=? THEN excluded.window_started
                   ELSE login_throttle.window_started
                 END
               RETURNING attempts''',
            (durable_key, now, cutoff, cutoff),
        ).fetchone()
        connection.commit()
    return int(row['attempts']) > (RATE_LIMIT_MAX if max_attempts is None else max_attempts)

def valid_origin(h):
    origin=request_header(h, 'Origin')
    if not origin: return True
    host=request_header(h, 'Host')
    return origin in (f'http://{host}', f'https://{host}')

def smtp_send(to, subject, text):
    host=os.getenv('SMTP_HOST'); port=int(os.getenv('SMTP_PORT') or '587'); user=os.getenv('SMTP_USER'); password=os.getenv('SMTP_PASSWORD'); sender=os.getenv('SMTP_FROM',user or '')
    if not host or not sender: return False
    msg=EmailMessage(); msg['From']=sender; msg['To']=to; msg['Subject']=subject; msg.set_content(text)
    with smtplib.SMTP(host,port,timeout=15) as s:
        if os.getenv('SMTP_TLS','1')=='1': s.starttls()
        if user: s.login(user,password or '')
        s.send_message(msg)
    return True

class Handler(BaseHTTPRequestHandler):
    server_version='DarkSystemBackend/1.0'
    def log_message(self, fmt, *args):
        print('[%s] %s' % (self.log_date_time_string(), fmt%args))
    def do_GET(self): self.route('GET')
    def do_POST(self): self.route('POST')
    def do_PUT(self): self.route('PUT')
    def do_PATCH(self): self.route('PATCH')
    def do_DELETE(self): self.route('DELETE')
    def do_OPTIONS(self):
        self.send_response(204); self.send_header('Access-Control-Allow-Headers','Content-Type'); self.send_header('Access-Control-Allow-Methods','GET,POST,PUT,DELETE,OPTIONS'); self.send_header('Vary','Origin'); self.end_headers()
    def route(self, method):
        path=urlparse(self.path).path
        if method in ('POST','PUT','PATCH','DELETE') and not valid_origin(self):
            return json_response(self, {'error':'Cross-origin request blocked.'}, 403)
        if method in ('POST','PUT','PATCH','DELETE'):
            length = int(request_header(self, 'Content-Length', '0') or 0)
            raw = self.rfile.read(length) if length else b'{}'
            try:
                parsed = json.loads(raw.decode() or '{}')
            except Exception:
                return json_response(self, {'error': 'Request JSON must be an object.'}, 400)
            if not isinstance(parsed, dict):
                return json_response(self, {'error': 'Request JSON must be an object.'}, 400)
            self._parsed_json = parsed
        throttle_identity=''
        if path.startswith('/api/community/'):
            throttle_identity=str(self._parsed_json.get('email','')).strip().lower()
        elif path=='/api/squad/login':
            throttle_identity='\0'.join(str(self._parsed_json.get(key,'')).strip().lower() for key in ('ign','gameId','serverId'))
        elif path in ('/api/squad/forgot','/api/squad/reset'):
            throttle_identity='\0'.join(str(self._parsed_json.get(key,'')).strip().lower() for key in ('email','ign','gameId','serverId'))
        elif path=='/api/owner/login':
            throttle_identity=str(self._parsed_json.get('username','')).strip().lower()
        globally_limited=method=='POST' and path in ('/api/owner/login','/api/community/login','/api/squad/login','/api/community/forgot','/api/squad/forgot','/api/community/reset','/api/squad/reset') and durable_rate_limited(self,path+':ip','',RATE_LIMIT_MAX*4)
        if path=='/api/owner/login' and method=='POST' and (globally_limited or durable_rate_limited(self, path, throttle_identity)):
            return json_response(self, {'error':'Too many login attempts. Please wait a few minutes and try again.'}, 429)
        if path in ('/api/community/login','/api/squad/login') and method=='POST' and (globally_limited or durable_rate_limited(self, path, throttle_identity)):
            return json_response(self, {'error':'Too many login attempts. Please wait a few minutes and try again.'}, 429)
        if path in ('/api/community/forgot','/api/squad/forgot','/api/community/reset','/api/squad/reset') and method=='POST' and (globally_limited or durable_rate_limited(self, path, throttle_identity)):
            return json_response(self, {'error':'Too many password reset requests. Please wait a few minutes and try again.'}, 429)
        if path=='/api/health': return json_response(self, {'ok':True,'service':'Dark System backend','time':now_iso()})
        if path=='/api/bootstrap' and method=='GET': return json_response(self, bootstrap(auth_from_cookie(self)))
        if path=='/api/auth/me' and method=='GET': return json_response(self, {'authenticated':bool(auth_from_cookie(self)),'session':auth_from_cookie(self)})
        if path=='/api/owner/setup/status' and method=='GET': return self.owner_setup_status()
        if path=='/api/owner/setup' and method=='POST': return self.owner_setup()
        if path=='/api/owner/login' and method=='POST': return self.owner_login()
        if path=='/api/owner/overview' and method=='GET': return self.owner_overview()
        if path=='/api/owner/audit' and method=='GET': return self.owner_audit()
        if path=='/api/owner/settings' and method=='GET': return self.owner_settings()
        if path=='/api/owner/settings' and method=='PATCH': return self.owner_settings_update()
        if path=='/api/owner/squad-content' and method=='GET': return self.owner_squad_content_list()
        if path.startswith('/api/owner/squad-content/'):
            parts = [part for part in path[len('/api/owner/squad-content/'):].split('/') if part]
            if len(parts) in (1, 2):
                domain, item_id = parts[0], parts[1] if len(parts) == 2 else ''
                if method == 'POST': return self.owner_squad_content_create(domain, item_id)
                if method == 'PATCH': return self.owner_squad_content_update(domain, item_id)
                if method == 'DELETE': return self.owner_squad_content_delete(domain, item_id)
        if path=='/api/owner/squad-members' and method=='GET': return self.owner_squad_members()
        if path=='/api/owner/squad-members' and method=='POST': return self.owner_squad_member_create()
        if path.startswith('/api/owner/squad-members/'):
            member_id=path.rsplit('/', 1)[-1]
            if member_id and method=='PATCH': return self.owner_squad_member_update(member_id)
            if member_id and method=='DELETE': return self.owner_squad_member_delete(member_id)
        if path=='/api/owner/squad-owner' and method=='POST': return self.owner_squad_owner_appoint()
        if path=='/api/owner/community-accounts' and method=='GET': return self.owner_community_accounts()
        if path.startswith('/api/owner/community-accounts/') and method=='PATCH':
            account_id=path.rsplit('/', 1)[-1]
            if account_id: return self.owner_community_account_update(account_id)
        if path=='/api/owner/tournaments':
            if method=='GET':return self.owner_tournaments_list()
            if method=='POST':return self.owner_tournament_create()
        if path.startswith('/api/owner/tournaments/'):
            parts=[part for part in path[len('/api/owner/tournaments/'):].split('/') if part]
            if len(parts)==1:
                if method=='GET':return self.owner_tournament_detail(parts[0])
                if method=='PATCH':return self.owner_tournament_update(parts[0])
            if len(parts)==2 and method=='POST':
                if parts[1]=='matches':return self.owner_tournament_match_create(parts[0])
                if parts[1] in ('cancel','reinstate','bracket','complete','archive'):
                    return self.owner_tournament_transition(parts[0],parts[1])
            if len(parts)==4 and parts[1]=='registrations' and parts[3]=='decision' and method=='POST':
                return self.owner_tournament_registration_decision(parts[0],parts[2])
            if len(parts)==4 and parts[1]=='approvals' and parts[3]=='decision' and method=='POST':
                return self.owner_tournament_approval_decision(parts[0],parts[2])
            if len(parts)==3 and parts[1]=='matches' and method in ('PATCH','DELETE'):
                return self.owner_tournament_match_change(parts[0],parts[2],method)
            if len(parts)==4 and parts[1]=='matches' and parts[3]=='result' and method=='POST':
                return self.owner_tournament_result_change(parts[0],parts[2])
        if path.startswith('/api/owner/tournament-managers/') and method=='POST':
            parts=[part for part in path[len('/api/owner/tournament-managers/'):].split('/') if part]
            if parts:return self.owner_tournament_manager_change(parts[0],parts[1] if len(parts)>1 else '')
        if path=='/api/owner/seasons':
            if method=='GET':return self.owner_seasons()
            if method=='POST':return self.owner_season_create()
        if path.startswith('/api/owner/seasons/') and method=='POST':
            parts=[part for part in path[len('/api/owner/seasons/'):].split('/') if part]
            if len(parts)==2 and parts[1]=='complete':return self.owner_season_complete(parts[0])
        if path.startswith('/api/owner/season-points/') and method=='PATCH':
            account_id=path[len('/api/owner/season-points/'):].strip('/')
            if account_id:return self.owner_season_points_correct(account_id)
        if path=='/api/owner/history' and method=='GET':return self.owner_history()
        if path.startswith('/api/owner/history/') and method=='PATCH':
            parts=[part for part in path[len('/api/owner/history/'):].split('/') if part]
            if len(parts)==2:return self.owner_history_correct(parts[0],parts[1])
        if path=='/api/owner/events':
            if method=='GET':return self.owner_events()
            if method=='POST':return self.owner_event_create()
        if path.startswith('/api/owner/events/'):
            parts=[part for part in path[len('/api/owner/events/'):].split('/') if part]
            if len(parts)==1 and method=='PATCH':return self.owner_event_update(parts[0])
            if len(parts)==2 and method=='POST':
                if parts[1] in ('publish','close','archive'):return self.owner_event_transition(parts[0],parts[1])
                if parts[1]=='participation':return self.owner_event_participation(parts[0])
        if path=='/api/roles' and method=='GET': return self.roles_info()
        if path=='/api/squad/role' and method=='POST': return self.squad_role_change()
        if path=='/api/logout' and method=='POST':
            session = auth_from_cookie(self)
            if session and session.get('type') == 'owner':
                return self.owner_logout(session)
            if session and session.get('type') == 'squad':
                return self.squad_logout(session)
            revoke_session(self)
            return json_response(self, {'ok':True}, 200, {'Set-Cookie':clear_session_cookie(self)})
        if path=='/api/community/register' and method=='POST': return self.community_register()
        if path=='/api/community/login' and method=='POST': return self.community_login()
        if path=='/api/community/forgot' and method=='POST': return self.community_forgot()
        if path=='/api/community/reset' and method=='POST': return self.community_reset()
        if path=='/api/community/profile' and method=='PUT': return self.community_profile()
        if path=='/api/community/notifications/read' and method=='POST': return self.community_notification_read()
        if path=='/api/community/notifications/read-all' and method=='POST': return self.community_notifications_read_all()
        if path=='/api/squad/login' and method=='POST': return self.squad_login()
        if path=='/api/squad/forgot' and method=='POST': return self.squad_forgot()
        if path=='/api/squad/reset' and method=='POST': return self.squad_reset()
        if path=='/api/squad/notifications/read' and method=='POST': return self.squad_notification_read()
        if path=='/api/squad/notifications/read-all' and method=='POST': return self.squad_notifications_read_all()
        if path=='/api/squad/content' and method in ('POST','PUT'): return self.squad_content_write()
        if path=='/api/squad/content' and method=='DELETE': return self.squad_content_delete()
        if path=='/api/squad/profile' and method=='PUT': return self.squad_profile()
        if path=='/api/squad/members' and method=='POST': return self.api_member_create()
        if path=='/api/squad/members' and method=='PUT': return self.api_member_update()
        if path=='/api/squad/members' and method=='DELETE': return self.api_member_delete()
        if path=='/api/tournaments' and method=='POST': return self.api_tournament_write('create')
        if path=='/api/tournaments' and method=='PUT': return self.api_tournament_write('edit')
        if path=='/api/tournaments/cancel' and method=='POST': return self.api_tournament_write('cancel')
        if path=='/api/tournaments/reinstate' and method=='POST': return self.api_tournament_write('reinstate')
        if path=='/api/tournaments/register' and method=='POST': return self.api_registration('register')
        if path=='/api/tournaments/withdraw' and method=='POST': return self.api_registration('withdraw')
        if path=='/api/tournaments/approve' and method=='POST': return self.api_registration('approve')
        if path=='/api/tournaments/bracket' and method=='POST': return self.api_tournament_bracket()
        if path=='/api/tournaments/match' and method=='POST': return self.api_tournament_match('upsert')
        if path=='/api/tournaments/result' and method=='POST': return self.api_result_submit()
        if path=='/api/tournaments/complete' and method=='POST': return self.api_tournament_match('complete')
        if path=='/api/tournaments/squad-approval' and method=='POST': return self.api_squad_approval()
        if path=='/api/tournaments/result-review' and method=='POST': return self.api_result_review()
        if path=='/api/tournaments/result-confirm' and method=='POST': return self.api_result_confirm()
        if path=='/api/tournaments/result-dispute' and method=='POST': return self.api_result_dispute()
        if path=='/api/tournament-managers' and method=='POST': return self.api_tournament_manager_change()
        if path=='/api/community/event-participation' and method=='POST': return self.api_event_participation()
        if path=='/api/state' and method=='PUT': return self.sync_state()
        return self.static_or_404(path)
    def audit(self, session, action, target_type='', target_id='', details=None):
        try:
            with LOCK, db() as c:
                insert_audit(c, session, action, target_type, target_id, details)
                c.commit()
        except Exception:
            logging.exception(
                'Failed to write audit record for action=%s target_type=%s',
                action,
                target_type,
            )
            return False
        return True

    def owner_setup_status(self):
        with LOCK, db() as c:
            row=c.execute("SELECT value FROM app_state WHERE key='owner_setup_complete'").fetchone()
            complete=bool(row and row['value']=='true')
        return json_response(self, {'setupComplete':complete})

    def owner_setup(self):
        d=read_json(self)
        if not OWNER_SETUP_SECRET:
            return json_response(self, {'error':'Owner setup is unavailable because server configuration is incomplete.'},503)
        supplied_setup_secret=str(d.get('setupSecret',''))
        if not hmac.compare_digest(supplied_setup_secret, OWNER_SETUP_SECRET):
            return json_response(self, {'error':'Owner setup authorization failed.'},403)
        username=str(d.get('username','')).strip()
        password=str(d.get('password',''))
        squad=d.get('squadOwner') or {}
        required=['ign','gameId','serverId','accessCode']
        if len(username)<4 or len(password)<10 or any(not str(squad.get(k,'')).strip() for k in required):
            return json_response(self, {'error':'Owner username must be at least 4 characters, password at least 10 characters, and all Squad Owner credentials are required.'},400)
        try:
            with LOCK, db() as c:
                if c.execute('SELECT 1 FROM owner_accounts WHERE lower(username)=?',(username.lower(),)).fetchone():
                    return json_response(self, {'error':'That Owner username is already in use.'},409)
                claim=c.execute(
                    "UPDATE app_state SET value='true' WHERE key='owner_setup_complete' AND value='false'"
                )
                if claim.rowcount != 1:
                    return json_response(self, {'error':'Owner setup has already been completed and is locked.'},409)
                owner_id='OWNER-'+secrets.token_hex(6)
                owner_session={'type':'owner','id':owner_id,'role':'Overall Owner'}
                c.execute('INSERT INTO owner_accounts(id,username,password_hash,created_at) VALUES(?,?,?,?)',(owner_id,username,hash_password(password),now_iso()))
                existing=c.execute("SELECT id FROM squad_members WHERE id='1'").fetchone()
                if existing:
                    c.execute("UPDATE squad_members SET name=?,ign=?,game_id=?,server_id=?,access_code=?,role='Squad Owner',account_activated=1,profile_complete=1,recovery_pending=0 WHERE id='1'",('Dark System Owner',str(squad['ign']).strip(),str(squad['gameId']).strip(),str(squad['serverId']).strip(),str(squad['accessCode']).strip().upper()))
                else:
                    c.execute("INSERT INTO squad_members(id,name,ign,game_id,server_id,role,access_code,status,profile_complete,account_activated) VALUES('1','Dark System Owner',?,?,?,?,?,'Offline',1,1)",(str(squad['ign']).strip(),str(squad['gameId']).strip(),str(squad['serverId']).strip(),'Squad Owner',str(squad['accessCode']).strip().upper()))
                c.execute('UPDATE squad_members SET access_code_hash=?,access_code=? WHERE id=?',(hash_password(str(squad['accessCode']).strip().upper()),'','1'))
                insert_audit(c,owner_session,'owner_setup','system',owner_id,{'username':username})
                c.commit()
        except Exception:
            logging.exception('Owner setup transaction failed.')
            return json_response(self, {'error':'Owner setup could not be completed.'},503)
        return json_response(self, {'ok':True,'message':'Owner setup completed and locked.'})

    def owner_login(self):
        d=read_json(self); username=str(d.get('username','')).strip().lower(); password=str(d.get('password',''))
        with LOCK, db() as c: row=c.execute('SELECT * FROM owner_accounts WHERE lower(username)=?',(username,)).fetchone()
        if not row or not verify_password(password,row['password_hash']): return json_response(self, {'error':'The Owner username or password is incorrect.'},401)
        owner_session={'type':'owner','id':row['id'],'role':'Overall Owner'}
        try:
            with LOCK, db() as c:
                if not c.execute('SELECT 1 FROM owner_accounts WHERE id=?',(row['id'],)).fetchone():
                    return json_response(self, {'error':'The Owner username or password is incorrect.'},401)
                token=create_session_record(c,'owner',row['id'],'Overall Owner')
                insert_audit(c,owner_session,'owner_login','owner',row['id'])
                c.commit()
        except Exception:
            logging.exception('Owner login transaction failed.')
            return json_response(self, {'error':'Owner login could not be completed.'},503)
        return json_response(self, {'ok':True,'role':'Overall Owner'},200,{'Set-Cookie':session_cookie(self, token)})

    def owner_logout(self, session):
        raw=request_header(self, 'Cookie')
        cookies=SimpleCookie(); cookies.load(raw)
        morsel=cookies.get(COOKIE_NAME)
        try:
            with LOCK, db() as c:
                if morsel:
                    c.execute(
                        'DELETE FROM sessions WHERE token=?',
                        (session_token_hash(morsel.value),),
                    )
                insert_audit(c,session,'owner_logout','owner',session['id'])
                c.commit()
        except Exception:
            logging.exception('Owner logout transaction failed.')
            return json_response(self, {'error':'Owner logout could not be completed.'},503)
        return json_response(self, {'ok':True},200,{'Set-Cookie':clear_session_cookie(self)})

    def squad_logout(self, session):
        raw=request_header(self, 'Cookie')
        cookies=SimpleCookie(); cookies.load(raw)
        morsel=cookies.get(COOKIE_NAME)
        try:
            with LOCK, db() as c:
                c.execute(
                    'UPDATE squad_members SET status=? WHERE id=?',
                    ('Offline', str(session['id'])),
                )
                if morsel:
                    c.execute(
                        'DELETE FROM sessions WHERE token=?',
                        (session_token_hash(morsel.value),),
                    )
                c.commit()
        except Exception:
            logging.exception('Squad logout transaction failed.')
            return json_response(self, {'error':'Squad logout could not be completed.'},503)
        return json_response(self, {'ok':True},200,{'Set-Cookie':clear_session_cookie(self)})

    def owner_overview(self):
        s=require_overall_owner(self)
        if not s:return
        with LOCK, db() as c:
            tournaments=state_get(c,'tournaments',[])
            registrations=state_get(c,'registrations',[])
            approvals=state_get(c,'squadTournamentApprovals',[])
            tournaments=tournaments if isinstance(tournaments,list) else []
            registrations=registrations if isinstance(registrations,list) else []
            approvals=approvals if isinstance(approvals,list) else []
            secret_values=set()
            for query, column in (
                ('SELECT access_code FROM squad_members', 'access_code'),
                ('SELECT password_hash FROM community_accounts', 'password_hash'),
                ('SELECT reset_code FROM community_accounts WHERE reset_code IS NOT NULL', 'reset_code'),
                ('SELECT password_hash FROM owner_accounts', 'password_hash'),
            ):
                for row in c.execute(query).fetchall():
                    if row[column]: secret_values.add(str(row[column]))
            session_token_hashes={str(row['token']) for row in c.execute('SELECT token FROM sessions').fetchall() if row['token']}
            cookies=SimpleCookie(); cookies.load(request_header(self, 'Cookie'))
            if cookies.get(COOKIE_NAME): secret_values.add(cookies[COOKIE_NAME].value)
            audit=[]
            for row in c.execute('SELECT id,actor_type,actor_id,actor_role,action,target_type,target_id,created_at,details FROM audit_log ORDER BY created_at DESC, id DESC LIMIT 10').fetchall():
                item=sanitize_overview_value(dict(row), secret_values, session_token_hashes)
                item['details']=overview_details(item.get('details'), secret_values, session_token_hashes)
                audit.append(item)
            completed=lambda tournament: bool(tournament.get('completed')) or overview_status(tournament.get('status'))=='completed'
            counts={
                'communityMembers':c.execute('SELECT COUNT(*) AS n FROM community_accounts').fetchone()['n'],
                'squadMembers':c.execute('SELECT COUNT(*) AS n FROM squad_members').fetchone()['n'],
                'activeTournaments':sum(1 for tournament in tournaments if isinstance(tournament,dict) and not completed(tournament) and overview_status(tournament.get('status')) not in ('cancelled','canceled')),
                'completedTournaments':sum(1 for tournament in tournaments if isinstance(tournament,dict) and completed(tournament)),
            }
            pending={
                'registrations':sum(1 for registration in registrations if isinstance(registration,dict) and overview_status(registration.get('status') or 'Registered') in ('registered','pending','awaitingapproval')),
                'squadApprovals':sum(1 for approval in approvals if isinstance(approval,dict) and overview_status(approval.get('status') or 'Pending')=='pending'),
                'results':sum(1 for tournament in tournaments if isinstance(tournament,dict) for match in (tournament.get('matches') or []) if isinstance(match,dict) and pending_overview_result(match)),
            }
        return json_response(self,{'health':{'backend':'healthy','database':'healthy'},'counts':counts,'pending':pending,'recentAudit':audit})

    def owner_audit(self):
        s=require_overall_owner(self)
        if not s:return
        query=parse_qs(urlparse(self.path).query,keep_blank_values=True)
        action=str(query.get('action',[''])[0]).strip()
        actor=str(query.get('actor',[''])[0]).strip()
        target=str(query.get('target',[''])[0]).strip()
        start=str(query.get('from',[''])[0]).strip()
        end=str(query.get('to',[''])[0]).strip()
        cursor=str(query.get('cursor',[''])[0]).strip()
        try:limit=int(str(query.get('limit',['50'])[0]))
        except ValueError:return json_response(self,{'error':'limit must be a number.'},400)
        if limit<1 or limit>100:return json_response(self,{'error':'limit must be between 1 and 100.'},400)
        def audit_date(value,end_of_day=False):
            if not value:return None
            try:
                parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
                if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=timezone.utc)
                if end_of_day and len(value)==10:parsed=parsed.replace(hour=23,minute=59,second=59)
                return parsed.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            except ValueError:return False
        start_value=audit_date(start);end_value=audit_date(end,True)
        if start_value is False or end_value is False:return json_response(self,{'error':'Audit dates must be valid ISO dates.'},400)
        cursor_values=None
        if cursor:
            try:
                decoded=json.loads(base64.urlsafe_b64decode(cursor+'='*(-len(cursor)%4)).decode())
                cursor_values=(str(decoded['createdAt']),str(decoded['id']))
            except Exception:return json_response(self,{'error':'cursor is invalid.'},400)
        with LOCK, db() as c:
            secret_values=set()
            for query, column in (
                ('SELECT access_code FROM squad_members', 'access_code'),
                ('SELECT password_hash FROM community_accounts', 'password_hash'),
                ('SELECT reset_code FROM community_accounts WHERE reset_code IS NOT NULL', 'reset_code'),
                ('SELECT password_hash FROM owner_accounts', 'password_hash'),
            ):
                for row in c.execute(query).fetchall():
                    if row[column]: secret_values.add(str(row[column]))
            session_token_hashes={str(row['token']) for row in c.execute('SELECT token FROM sessions').fetchall() if row['token']}
            cookies=SimpleCookie(); cookies.load(request_header(self, 'Cookie'))
            if cookies.get(COOKIE_NAME): secret_values.add(cookies[COOKIE_NAME].value)
            clauses=[];params=[]
            if action:clauses.append('action=?');params.append(action)
            if actor:clauses.append('(actor_id=? OR actor_role=? OR actor_type=?)');params.extend((actor,actor,actor))
            if target:clauses.append('(target_id LIKE ? OR target_type=?)');params.extend((f'%{target}%',target))
            if start_value:clauses.append('created_at>=?');params.append(start_value)
            if end_value:clauses.append('created_at<=?');params.append(end_value)
            if cursor_values:
                clauses.append('(created_at<? OR (created_at=? AND id<?))');params.extend((cursor_values[0],cursor_values[0],cursor_values[1]))
            where=(' WHERE '+' AND '.join(clauses)) if clauses else ''
            fetched=c.execute(
                'SELECT id,actor_type,actor_id,actor_role,action,target_type,target_id,created_at,details FROM audit_log'+where+' ORDER BY created_at DESC, id DESC LIMIT ?',
                tuple(params+[limit+1]),
            ).fetchall()
            rows=[]
            for row in fetched[:limit]:
                item=sanitize_overview_value(dict(row), secret_values, session_token_hashes)
                item['details']=overview_details(item.get('details'), secret_values, session_token_hashes)
                rows.append(item)
            next_cursor=''
            if len(fetched)>limit and rows:
                marker=json.dumps({'createdAt':rows[-1]['created_at'],'id':rows[-1]['id']},separators=(',',':')).encode()
                next_cursor=base64.urlsafe_b64encode(marker).decode().rstrip('=')
        return json_response(self,{'audit':rows,'nextCursor':next_cursor})

    def owner_settings(self):
        session=require_overall_owner(self)
        if not session:return
        with LOCK,db() as c:
            row=c.execute('SELECT username,created_at FROM owner_accounts WHERE id=?',(session['id'],)).fetchone()
        if not row:return json_response(self,{'error':'Owner account not found.'},404)
        return json_response(self,{'settings':{'username':row['username'],'createdAt':row['created_at'],'sessionTtlSeconds':SESSION_TTL,'recoveryCodeTtlSeconds':RECOVERY_TTL}})

    def owner_settings_update(self):
        session=require_overall_owner(self)
        if not session:return
        data=read_json(self);current=str(data.get('currentPassword',''));new=str(data.get('newPassword',''))
        if len(new)<12:return json_response(self,{'error':'The new password must be at least 12 characters.'},400)
        cookies=SimpleCookie();cookies.load(request_header(self,'Cookie'));morsel=cookies.get(COOKIE_NAME)
        current_token_hash=session_token_hash(morsel.value) if morsel else ''
        try:
            with LOCK,db() as c:
                row=c.execute('SELECT password_hash FROM owner_accounts WHERE id=?',(session['id'],)).fetchone()
                if not row or not verify_password(current,row['password_hash']):
                    return json_response(self,{'error':'The current password is incorrect.'},403)
                c.execute('UPDATE owner_accounts SET password_hash=? WHERE id=?',(hash_password(new),session['id']))
                c.execute('DELETE FROM sessions WHERE type=? AND user_id=? AND token!=?',('owner',str(session['id']),current_token_hash))
                insert_audit(c,session,'owner_password_change','owner',session['id'],{'otherSessionsRevoked':True})
                c.commit()
        except Exception:
            logging.exception('Owner settings update failed.')
            return json_response(self,{'error':'Owner settings could not be updated.'},503)
        return self.owner_settings()

    def owner_squad_content_list(self):
        session = require_overall_owner(self)
        if not session:
            return
        domain = str(parse_qs(urlparse(self.path).query, keep_blank_values=True).get('domain', [''])[0]).strip()
        if domain not in OWNER_CONTENT_DOMAINS:
            return json_response(self, {'error': 'A supported Squad content domain is required.'}, 400)
        notification_domain = str(parse_qs(urlparse(self.path).query, keep_blank_values=True).get('audienceType', [''])[0]).strip()
        if notification_domain and notification_domain not in ('squad', 'community'):
            return json_response(self, {'error': 'audienceType must be squad or community.'}, 400)
        with LOCK, db() as c:
            items = owner_content_items(c, domain, notification_domain or None)
        return json_response(self, {'domain': domain, 'items': items})

    def owner_squad_content_create(self, domain, item_id):
        session = require_overall_owner(self)
        if not session:
            return
        data = read_json(self)
        item, error = normalize_owner_content(domain, data, item_id)
        if error:
            return json_response(self, {'error': error}, 400)
        try:
            with LOCK, db() as c:
                if domain == 'notifications':
                    notification_domain = str(data.get('audienceType', 'squad')).strip() or 'squad'
                    if notification_domain not in ('squad', 'community'):
                        return json_response(self, {'error': 'audienceType must be squad or community.'}, 400)
                    if not notification_target_exists(c, notification_domain, item.get('audienceId')):
                        return json_response(self, {'error': 'Notification audience was not found.'}, 404)
                    if c.execute('SELECT 1 FROM notifications WHERE id=?', (item['id'],)).fetchone():
                        return json_response(self, {'error': 'Content already exists.'}, 409)
                    c.execute('INSERT INTO notifications(id,domain,payload) VALUES(?,?,?)', (
                        item['id'], notification_domain, json.dumps(item, separators=(',', ':')),
                    ))
                else:
                    items = state_get(c, domain, [])
                    if not isinstance(items, list):
                        items = []
                    if any(isinstance(existing, dict) and str(existing.get('id')) == item['id'] for existing in items):
                        return json_response(self, {'error': 'Content already exists.'}, 409)
                    items.append(item)
                    state_set(c, domain, items)
                insert_audit(c, session, 'owner_squad_content_create', 'squad_content', item['id'], {'domain': domain})
                c.commit()
        except Exception:
            logging.exception('Owner Squad content creation failed.')
            return json_response(self, {'error': 'The Squad content could not be created.'}, 503)
        return json_response(self, {'item': safe_owner_content_item(domain, item)}, 201)

    def owner_squad_content_update(self, domain, item_id):
        session = require_overall_owner(self)
        if not session:
            return
        if domain not in OWNER_CONTENT_DOMAINS or not item_id:
            return json_response(self, {'error': 'A supported Squad content domain and id are required.'}, 400)
        try:
            with LOCK, db() as c:
                if domain == 'notifications':
                    requested_domain = str(parse_qs(urlparse(self.path).query, keep_blank_values=True).get('audienceType', [''])[0]).strip()
                    if requested_domain and requested_domain not in ('squad', 'community'):
                        return json_response(self, {'error': 'audienceType must be squad or community.'}, 400)
                    row = c.execute('SELECT domain,payload FROM notifications WHERE id=?', (item_id,)).fetchone()
                    if not row:
                        return json_response(self, {'error': 'Content not found.'}, 404)
                    if requested_domain and row['domain'] != requested_domain:
                        return json_response(self, {'error': 'Content not found.'}, 404)
                    try: existing = json.loads(row['payload'])
                    except Exception: existing = None
                    if not isinstance(existing, dict):
                        return json_response(self, {'error': 'Content not found.'}, 404)
                    item, error = normalize_owner_content(domain, read_json(self), item_id, existing)
                    if error:
                        return json_response(self, {'error': error}, 400)
                    if not notification_target_exists(c, row['domain'], item.get('audienceId')):
                        return json_response(self, {'error': 'Notification audience was not found.'}, 404)
                    c.execute('UPDATE notifications SET payload=? WHERE id=?', (json.dumps(item, separators=(',', ':')), item_id))
                else:
                    items = state_get(c, domain, [])
                    if not isinstance(items, list):
                        items = []
                    index = next((i for i, existing in enumerate(items) if isinstance(existing, dict) and str(existing.get('id')) == item_id), None)
                    if index is None:
                        return json_response(self, {'error': 'Content not found.'}, 404)
                    item, error = normalize_owner_content(domain, read_json(self), item_id, items[index])
                    if error:
                        return json_response(self, {'error': error}, 400)
                    items[index] = item
                    state_set(c, domain, items)
                insert_audit(c, session, 'owner_squad_content_update', 'squad_content', item_id, {'domain': domain})
                c.commit()
        except Exception:
            logging.exception('Owner Squad content update failed.')
            return json_response(self, {'error': 'The Squad content could not be updated.'}, 503)
        return json_response(self, {'item': safe_owner_content_item(domain, item)})

    def owner_squad_content_delete(self, domain, item_id):
        session = require_overall_owner(self)
        if not session:
            return
        if domain not in OWNER_CONTENT_DOMAINS or not item_id:
            return json_response(self, {'error': 'A supported Squad content domain and id are required.'}, 400)
        try:
            with LOCK, db() as c:
                if domain == 'notifications':
                    requested_domain = str(parse_qs(urlparse(self.path).query, keep_blank_values=True).get('audienceType', [''])[0]).strip()
                    if requested_domain and requested_domain not in ('squad', 'community'):
                        return json_response(self, {'error': 'audienceType must be squad or community.'}, 400)
                    row = c.execute('SELECT domain FROM notifications WHERE id=?', (item_id,)).fetchone()
                    if not row or (requested_domain and row['domain'] != requested_domain):
                        return json_response(self, {'error': 'Content not found.'}, 404)
                    c.execute('DELETE FROM notification_reads WHERE notification_id=?', (item_id,))
                    c.execute('DELETE FROM notifications WHERE id=?', (item_id,))
                else:
                    items = state_get(c, domain, [])
                    if not isinstance(items, list):
                        items = []
                    updated = [item for item in items if not isinstance(item, dict) or str(item.get('id')) != item_id]
                    if len(updated) == len(items):
                        return json_response(self, {'error': 'Content not found.'}, 404)
                    state_set(c, domain, updated)
                insert_audit(c, session, 'owner_squad_content_delete', 'squad_content', item_id, {'domain': domain})
                c.commit()
        except Exception:
            logging.exception('Owner Squad content deletion failed.')
            return json_response(self, {'error': 'The Squad content could not be deleted.'}, 503)
        return json_response(self, {'ok': True})

    def owner_squad_members(self):
        session = require_overall_owner(self)
        if not session:
            return
        options, error = owner_list_options(self, SQUAD_ROLES, SQUAD_MEMBER_STATUSES)
        if error:
            return json_response(self, {'error': error}, 400)
        where, params = [], []
        if options['search']:
            escaped = options['search'].replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_').lower()
            where.append("(lower(name) LIKE ? ESCAPE '\\' OR lower(ign) LIKE ? ESCAPE '\\' OR lower(id) LIKE ? ESCAPE '\\')")
            params.extend([f'%{escaped}%'] * 3)
        if options['role']:
            where.append('role=?'); params.append(options['role'])
        if options['status']:
            where.append('status=?'); params.append(options['status'])
        if options['cursor']:
            where.append('id>?'); params.append(options['cursor'])
        clause = (' WHERE ' + ' AND '.join(where)) if where else ''
        with LOCK, db() as c:
            rows = c.execute(
                f'SELECT * FROM squad_members{clause} ORDER BY id ASC LIMIT ?',
                tuple(params + [options['limit'] + 1]),
            ).fetchall()
        has_more = len(rows) > options['limit']
        members = [safe_owner_squad_member(row) for row in rows[:options['limit']]]
        return json_response(self, {
            'members': members,
            'nextCursor': members[-1]['id'] if has_more and members else None,
        })

    def owner_squad_member_create(self):
        session = require_overall_owner(self)
        if not session:
            return
        data = read_json(self)
        if 'accessCode' in data:
            return json_response(self,{'error':'Squad members establish credentials through self-service recovery.'},400)
        required = ('name', 'ign', 'gameId', 'serverId', 'email')
        if any(not str(data.get(key, '')).strip() for key in required):
            return json_response(self, {'error': 'Name, IGN, Game ID, Server ID and registered email are required.'}, 400)
        role = str(data.get('role', 'Squad Member')).strip() or 'Squad Member'
        if role not in SQUAD_ROLES or role == 'Squad Owner':
            return json_response(self, {'error': 'Use the Squad Owner appointment endpoint to appoint a Squad Owner.'}, 409)
        status = str(data.get('status', 'Offline')).strip() or 'Offline'
        if status not in SQUAD_MEMBER_STATUSES or status == 'Disabled':
            return json_response(self, {'error': 'New Squad members must start in an active online or offline state.'}, 400)
        profile_complete, error = json_bool(data, 'profileComplete', False)
        if error:
            return json_response(self, {'error': error}, 400)
        account_activated, error = json_bool(data, 'accountActivated', True)
        if error:
            return json_response(self, {'error': error}, 400)
        member_id = 'SM-' + secrets.token_hex(8)
        name, ign = str(data['name']).strip(), str(data['ign']).strip()
        game_id, server_id = str(data['gameId']).strip(), str(data['serverId']).strip()
        try:
            with LOCK, db() as c:
                if identity_conflict(c, 'squad_members', ign, game_id, server_id):
                    return json_response(self, {'error': 'A Squad member already uses that IGN, Game ID, or Server ID.'}, 409)
                c.execute(
                    '''INSERT INTO squad_members(id,name,ign,game_id,server_id,role,lane,email,phone,birthday,access_code,status,last_login,profile_complete,account_activated,recovery_pending)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (member_id, name, ign, game_id, server_id, role,
                     str(data.get('lane', '')).strip(), str(data.get('email', '')).strip(),
                     str(data.get('phone', '')).strip(), str(data.get('birthday', '')).strip(),
                     '', status, None,
                     1 if profile_complete else 0,
                     0, 1),
                )
                c.execute('UPDATE squad_members SET access_code_hash=? WHERE id=?',(hash_password(secrets.token_urlsafe(48)),member_id))
                row = c.execute('SELECT * FROM squad_members WHERE id=?', (member_id,)).fetchone()
                create_owner_notification(
                    c, session, 'owner_squad_member_create', 'squad_member', member_id,
                    'Squad member created', 'An Overall Owner created a Squad member.', 'squad', member_id,
                )
                insert_audit(c, session, 'owner_squad_member_create', 'squad_member', member_id, {'ign': ign, 'role': role})
                c.commit()
        except Exception as exc:
            if unique_constraint_violation(exc):
                return json_response(self, {'error': 'A Squad member already uses that IGN, Game ID, or Server ID.'}, 409)
            logging.exception('Owner Squad member creation failed.')
            return json_response(self, {'error': 'The Squad member could not be created.'}, 503)
        return json_response(self, {'member': safe_owner_squad_member(row)}, 201)

    def owner_squad_member_update(self, member_id):
        session = require_overall_owner(self)
        if not session:
            return
        data = read_json(self)
        if 'accessCode' in data:
            return json_response(self, {'error':'Squad members rotate credentials through self-service recovery.'},400)
        try:
            with LOCK, db() as c:
                row = c.execute('SELECT * FROM squad_members WHERE id=?', (member_id,)).fetchone()
                if not row:
                    return json_response(self, {'error': 'Squad member not found.'}, 404)
                profile_complete, error = json_bool(data, 'profileComplete', row['profile_complete'])
                if error:
                    return json_response(self, {'error': error}, 400)
                account_activated, error = json_bool(data, 'accountActivated', row['account_activated'])
                if error:
                    return json_response(self, {'error': error}, 400)
                values = {
                    'name': str(data.get('name', row['name'])).strip(),
                    'ign': str(data.get('ign', row['ign'])).strip(),
                    'game_id': str(data.get('gameId', row['game_id'])).strip(),
                    'server_id': str(data.get('serverId', row['server_id'])).strip(),
                    'role': str(data.get('role', row['role'])).strip(),
                    'lane': str(data.get('lane', row['lane'] or '')).strip(),
                    'email': str(data.get('email', row['email'] or '')).strip(),
                    'phone': str(data.get('phone', row['phone'] or '')).strip(),
                    'birthday': str(data.get('birthday', row['birthday'] or '')).strip(),
                    'access_code': str(data.get('accessCode', row['access_code'])).strip().upper(),
                    'status': str(data.get('status', row['status'])).strip(),
                    'profile_complete': 1 if profile_complete else 0,
                    'account_activated': 1 if account_activated else 0,
                }
                if not all(values[key] for key in ('name', 'ign', 'game_id', 'server_id')):
                    return json_response(self, {'error': 'Name, IGN, Game ID and Server ID cannot be empty.'}, 400)
                if values['role'] not in SQUAD_ROLES:
                    return json_response(self, {'error': 'The requested Squad role is invalid.'}, 400)
                if values['status'] not in SQUAD_MEMBER_STATUSES:
                    return json_response(self, {'error': 'The requested Squad status is invalid.'}, 400)
                if row['role'] == 'Squad Owner' and (
                    values['role'] != 'Squad Owner' or values['status'] == 'Disabled' or not values['account_activated']
                ):
                    return json_response(self, {'error': 'Appoint a replacement before changing the active Squad Owner.'}, 409)
                if values['role'] == 'Squad Owner' and row['role'] != 'Squad Owner':
                    return json_response(self, {'error': 'Use the Squad Owner appointment endpoint to appoint a Squad Owner.'}, 409)
                if identity_conflict(c, 'squad_members', values['ign'], values['game_id'], values['server_id'], member_id):
                    return json_response(self, {'error': 'A Squad member already uses that IGN, Game ID, or Server ID.'}, 409)
                new_access_hash=row['access_code_hash']
                recovery_pending = int(row['recovery_pending'] or 0)
                if values['status'] == 'Disabled' or 'accountActivated' in data:
                    recovery_pending = 0
                c.execute(
                    '''UPDATE squad_members SET name=?,ign=?,game_id=?,server_id=?,role=?,lane=?,email=?,phone=?,birthday=?,access_code=?,access_code_hash=?,status=?,profile_complete=?,account_activated=?,recovery_pending=? WHERE id=?''',
                    (values['name'], values['ign'], values['game_id'], values['server_id'], values['role'],
                     values['lane'], values['email'], values['phone'], values['birthday'], values['access_code'],
                     new_access_hash,values['status'], values['profile_complete'], values['account_activated'], recovery_pending, member_id),
                )
                authority_changed = values['role'] != row['role']
                credentials_changed = False
                unavailable = values['status'] == 'Disabled' or not values['account_activated']
                if authority_changed or credentials_changed or unavailable:
                    revoke_user_sessions(c, 'squad', member_id)
                if values['role'] not in ('Squad Leader', 'Assistant Squad Leader') or unavailable:
                    remove_tournament_manager_permission(c, member_id)
                updated = c.execute('SELECT * FROM squad_members WHERE id=?', (member_id,)).fetchone()
                create_owner_notification(
                    c, session, 'owner_squad_member_update', 'squad_member', member_id,
                    'Squad member updated', 'An Overall Owner updated a Squad member.', 'squad', member_id,
                )
                insert_audit(c, session, 'owner_squad_member_update', 'squad_member', member_id, {
                    'role': values['role'], 'status': values['status'], 'identityChanged': any(
                        values[key] != row[source] for key, source in (('ign', 'ign'), ('game_id', 'game_id'), ('server_id', 'server_id'))
                    ),
                })
                c.commit()
        except Exception as exc:
            if unique_constraint_violation(exc):
                return json_response(self, {'error': 'A Squad member already uses that IGN, Game ID, or Server ID.'}, 409)
            logging.exception('Owner Squad member update failed.')
            return json_response(self, {'error': 'The Squad member could not be updated.'}, 503)
        return json_response(self, {'member': safe_owner_squad_member(updated)})

    def owner_squad_member_delete(self, member_id):
        session = require_overall_owner(self)
        if not session:
            return
        try:
            with LOCK, db() as c:
                row = c.execute('SELECT role FROM squad_members WHERE id=?', (member_id,)).fetchone()
                if not row:
                    return json_response(self, {'error': 'Squad member not found.'}, 404)
                if row['role'] == 'Squad Owner':
                    return json_response(self, {'error': 'Appoint a replacement before removing the active Squad Owner.'}, 409)
                revoke_user_sessions(c, 'squad', member_id)
                remove_tournament_manager_permission(c, member_id)
                c.execute('DELETE FROM squad_members WHERE id=?', (member_id,))
                create_owner_notification(
                    c, session, 'owner_squad_member_delete', 'squad_member', member_id,
                    'Squad member removed', 'An Overall Owner removed a Squad member.',
                )
                insert_audit(c, session, 'owner_squad_member_delete', 'squad_member', member_id)
                c.commit()
        except Exception:
            logging.exception('Owner Squad member deletion failed.')
            return json_response(self, {'error': 'The Squad member could not be removed.'}, 503)
        return json_response(self, {'ok': True})

    def owner_squad_owner_appoint(self):
        session = require_overall_owner(self)
        if not session:
            return
        member_id = str(read_json(self).get('memberId', '')).strip()
        if not member_id:
            return json_response(self, {'error': 'A Squad member id is required.'}, 400)
        try:
            with LOCK, db() as c:
                candidate = c.execute('SELECT * FROM squad_members WHERE id=?', (member_id,)).fetchone()
                if not candidate:
                    return json_response(self, {'error': 'Squad member not found.'}, 404)
                if candidate['status'] == 'Disabled' or not candidate['account_activated']:
                    return json_response(self, {'error': 'Only an active Squad member can be appointed Squad Owner.'}, 409)
                former_rows = c.execute(
                    "SELECT id FROM squad_members WHERE role='Squad Owner' AND id!=?", (member_id,)
                ).fetchall()
                c.execute("UPDATE squad_members SET role='Squad Member' WHERE role='Squad Owner' AND id!=?", (member_id,))
                c.execute("UPDATE squad_members SET role='Squad Owner',status='Offline',account_activated=1,recovery_pending=0 WHERE id=?", (member_id,))
                remove_tournament_manager_permission(c, member_id)
                for former in former_rows:
                    revoke_user_sessions(c, 'squad', former['id'])
                updated = c.execute('SELECT * FROM squad_members WHERE id=?', (member_id,)).fetchone()
                create_owner_notification(
                    c, session, 'owner_squad_owner_appoint', 'squad_member', member_id,
                    'Squad Owner appointed', 'An Overall Owner appointed a Squad Owner.', 'squad', member_id,
                )
                insert_audit(c, session, 'owner_squad_owner_appoint', 'squad_member', member_id, {
                    'replacedMemberIds': [row['id'] for row in former_rows],
                })
                c.commit()
        except Exception:
            logging.exception('Owner Squad Owner appointment failed.')
            return json_response(self, {'error': 'The Squad Owner appointment could not be completed.'}, 503)
        return json_response(self, {'member': safe_owner_squad_member(updated)})

    def owner_community_accounts(self):
        session = require_overall_owner(self)
        if not session:
            return
        options, error = owner_list_options(self, ('Community Member', 'Tournament Manager'), COMMUNITY_ACCOUNT_STATUSES)
        if error:
            return json_response(self, {'error': error}, 400)
        where, params = [], []
        if options['search']:
            escaped = options['search'].replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_').lower()
            where.append("(lower(ign) LIKE ? ESCAPE '\\' OR lower(email) LIKE ? ESCAPE '\\' OR lower(id) LIKE ? ESCAPE '\\')")
            params.extend([f'%{escaped}%'] * 3)
        if options['role']:
            where.append('role=?'); params.append(options['role'])
        if options['status']:
            where.append('status=?'); params.append(options['status'])
        if options['cursor']:
            where.append('id>?'); params.append(options['cursor'])
        clause = (' WHERE ' + ' AND '.join(where)) if where else ''
        with LOCK, db() as c:
            rows = c.execute(
                f'SELECT * FROM community_accounts{clause} ORDER BY id ASC LIMIT ?',
                tuple(params + [options['limit'] + 1]),
            ).fetchall()
        has_more = len(rows) > options['limit']
        accounts = [safe_owner_community_account(row) for row in rows[:options['limit']]]
        return json_response(self, {
            'accounts': accounts,
            'nextCursor': accounts[-1]['id'] if has_more and accounts else None,
        })

    def owner_community_account_update(self, account_id):
        session = require_overall_owner(self)
        if not session:
            return
        data = read_json(self)
        try:
            with LOCK, db() as c:
                row = c.execute('SELECT * FROM community_accounts WHERE id=?', (account_id,)).fetchone()
                if not row:
                    return json_response(self, {'error': 'Community account not found.'}, 404)
                email_notifications, error = json_bool(data, 'emailNotifications', row['email_notifications'])
                if error:
                    return json_response(self, {'error': error}, 400)
                values = {
                    'ign': str(data.get('ign', row['ign'])).strip(),
                    'game_id': str(data.get('gameId', row['game_id'])).strip(),
                    'server_id': str(data.get('serverId', row['server_id'])).strip(),
                    'email': str(data.get('email', row['email'])).strip().lower(),
                    'phone': str(data.get('phone', row['phone'] or '')).strip(),
                    'lane': str(data.get('lane', row['lane'] or '')).strip(),
                    'email_notifications': 1 if email_notifications else 0,
                    'status': str(data.get('status', row['status'])).strip(),
                }
                if not all(values[key] for key in ('ign', 'game_id', 'server_id', 'email')):
                    return json_response(self, {'error': 'IGN, Game ID, Server ID and email cannot be empty.'}, 400)
                if values['status'] not in COMMUNITY_ACCOUNT_STATUSES:
                    return json_response(self, {'error': 'The requested Community account status is invalid.'}, 400)
                if c.execute('SELECT 1 FROM community_accounts WHERE lower(email)=? AND id!=?', (values['email'], account_id)).fetchone():
                    return json_response(self, {'error': 'That email is already in use.'}, 409)
                if identity_conflict(c, 'community_accounts', values['ign'], values['game_id'], values['server_id'], account_id):
                    return json_response(self, {'error': 'A Community account already uses that IGN, Game ID, or Server ID.'}, 409)
                c.execute(
                    'UPDATE community_accounts SET ign=?,game_id=?,server_id=?,email=?,phone=?,lane=?,email_notifications=?,status=? WHERE id=?',
                    (values['ign'], values['game_id'], values['server_id'], values['email'], values['phone'], values['lane'], values['email_notifications'], values['status'], account_id),
                )
                if values['status'] == 'Disabled':
                    revoke_user_sessions(c, 'community', account_id)
                updated = c.execute('SELECT * FROM community_accounts WHERE id=?', (account_id,)).fetchone()
                if values['status'] != row['status']:
                    create_owner_notification(
                        c, session, 'owner_community_account_update', 'community_account', account_id,
                        'Community account status updated', 'An Overall Owner updated a Community account status.', 'community', account_id,
                    )
                insert_audit(c, session, 'owner_community_account_update', 'community_account', account_id, {
                    'status': values['status'], 'identityChanged': any(
                        values[key] != row[source] for key, source in (('ign', 'ign'), ('game_id', 'game_id'), ('server_id', 'server_id'), ('email', 'email'))
                    ),
                })
                c.commit()
        except Exception as exc:
            if unique_constraint_violation(exc):
                return json_response(self, {'error': 'A Community account already uses that IGN, Game ID, Server ID, or email.'}, 409)
            logging.exception('Owner Community account update failed.')
            return json_response(self, {'error': 'The Community account could not be updated.'}, 503)
        return json_response(self, {'account': safe_owner_community_account(updated)})

    def _owner_leaderboard(self, connection, points=None):
        points = points if isinstance(points, dict) else state_get(connection, 'seasonPoints', {})
        if not isinstance(points, dict): points = {}
        accounts = {
            str(row['id']): row for row in connection.execute(
                'SELECT id,ign,game_id,server_id,status FROM community_accounts'
            ).fetchall()
        }
        rows=[]
        for account_id, value in points.items():
            try: score=int(value)
            except (TypeError,ValueError): score=0
            account=accounts.get(str(account_id))
            rows.append({
                'accountId':str(account_id), 'ign':str(account['ign'] if account else ''),
                'gameId':str(account['game_id'] if account else ''),
                'serverId':str(account['server_id'] if account else ''), 'points':score,
            })
        rows.sort(key=lambda item:(-item['points'],item['ign'].lower(),item['accountId']))
        for rank,item in enumerate(rows,1):item['rank']=rank
        return rows

    def owner_seasons(self):
        session=require_overall_owner(self)
        if not session:return
        with LOCK,db() as c:
            current=state_get(c,'currentSeason',None)
            history=state_get(c,'seasonHistory',[]) or []
            leaderboard=self._owner_leaderboard(c)
            safe_current=safe_owner_tournament_value(c,current) if current else None
            safe_history=safe_owner_tournament_value(c,history)
        return json_response(self,{'currentSeason':safe_current,'leaderboard':leaderboard,'seasons':safe_history})

    def owner_season_create(self):
        session=require_overall_owner(self)
        if not session:return
        data=read_json(self);name=data.get('name');request_id=data.get('requestId')
        if not isinstance(name,str) or not name.strip() or len(name.strip())>120:return json_response(self,{'error':'A valid season name is required.'},400)
        if request_id is not None and (not isinstance(request_id,str) or not request_id.strip() or len(request_id)>120):return json_response(self,{'error':'requestId must be a valid identifier.'},400)
        try:
            with LOCK,db() as c:
                lock_state_workflow(c)
                current=state_get(c,'currentSeason',None)
                if isinstance(current,dict):
                    if request_id and current.get('requestId')==request_id.strip():
                        return json_response(self,{'season':safe_owner_tournament_value(c,current)},200)
                    return json_response(self,{'error':'Complete the active season before starting another.'},409)
                history=state_get(c,'seasonHistory',[]) or []
                completed=next((item for item in history if isinstance(item,dict) and request_id and item.get('requestId')==request_id.strip()),None)
                if completed:
                    return json_response(self,{'season':{'id':completed.get('seasonId'),'name':completed.get('name'),'status':'Completed','completedAt':completed.get('completedAt')},'alreadyCompleted':True},200)
                season={'id':'S'+secrets.token_hex(7),'name':name.strip(),'status':'Active','startedAt':now_iso(),'startedBy':str(session.get('id'))}
                if request_id:season['requestId']=request_id.strip()
                state_set(c,'currentSeason',season);state_set(c,'seasonPoints',{})
                create_owner_notification(c,session,'owner_season_create','season',season['id'],'Season started','An Overall Owner started a new season.','community')
                insert_audit(c,session,'owner_season_create','season',season['id'],{'name':season['name']})
                c.commit();safe=safe_owner_tournament_value(c,season)
        except Exception:
            logging.exception('Owner season creation failed.')
            return json_response(self,{'error':'The season could not be started.'},503)
        return json_response(self,{'season':safe},201)

    def owner_season_points_correct(self,account_id):
        session=require_overall_owner(self)
        if not session:return
        data=read_json(self);points=data.get('points');reason=data.get('reason');request_id=data.get('requestId')
        if isinstance(points,bool) or not isinstance(points,int) or points<0 or points>100000000:return json_response(self,{'error':'points must be a non-negative integer.'},400)
        if not isinstance(reason,str) or not reason.strip() or len(reason.strip())>500:return json_response(self,{'error':'A correction reason is required.'},400)
        if request_id is not None and (not isinstance(request_id,str) or not request_id.strip() or len(request_id)>120):return json_response(self,{'error':'requestId must be a valid identifier.'},400)
        try:
            with LOCK,db() as c:
                lock_state_workflow(c)
                account=c.execute('SELECT id FROM community_accounts WHERE id=?',(account_id,)).fetchone()
                if not account:return json_response(self,{'error':'Community account not found.'},404)
                if not isinstance(state_get(c,'currentSeason',None),dict):return json_response(self,{'error':'Season points require an active season.'},409)
                operations=state_get(c,'ownerIdempotency',{}) or {};operation_key='season-points:'+request_id.strip() if request_id else ''
                if operation_key and operation_key in operations:
                    stored=operations[operation_key]
                    return json_response(self,{'accountId':str(stored.get('accountId')),'points':stored.get('points'),'leaderboard':self._owner_leaderboard(c),'alreadyApplied':True})
                values=state_get(c,'seasonPoints',{}) or {};previous=int(values.get(str(account_id),0) or 0);values[str(account_id)]=points
                state_set(c,'seasonPoints',values)
                create_owner_notification(c,session,'owner_season_points_correct','community_account',account_id,'Season points corrected','An Overall Owner corrected your season points.','community',account_id)
                insert_audit(c,session,'owner_season_points_correct','community_account',account_id,{'previousPoints':previous,'points':points,'reason':reason.strip()})
                if operation_key:
                    operations[operation_key]={'accountId':str(account_id),'points':points};state_set(c,'ownerIdempotency',operations)
                c.commit();leaderboard=self._owner_leaderboard(c,values)
        except Exception:
            logging.exception('Owner season points correction failed.')
            return json_response(self,{'error':'The season points could not be corrected.'},503)
        return json_response(self,{'accountId':str(account_id),'points':points,'leaderboard':leaderboard,'alreadyApplied':False})

    def owner_season_complete(self,season_id):
        session=require_overall_owner(self)
        if not session:return
        try:
            with LOCK,db() as c:
                lock_state_workflow(c)
                history=state_get(c,'seasonHistory',[]) or []
                existing=next((item for item in history if isinstance(item,dict) and str(item.get('seasonId'))==season_id),None)
                if existing:return json_response(self,{'history':safe_owner_tournament_value(c,existing),'alreadyCompleted':True})
                current=state_get(c,'currentSeason',None)
                if not isinstance(current,dict) or str(current.get('id'))!=season_id:return json_response(self,{'error':'Active season not found.'},404)
                leaderboard=self._owner_leaderboard(c)
                completed_at=now_iso();snapshot={
                    'id':'SH'+secrets.token_hex(7),'seasonId':season_id,'name':str(current.get('name','')),
                    'startedAt':current.get('startedAt'),'completedAt':completed_at,
                    'leaderboard':[dict(item) for item in leaderboard],
                }
                if current.get('requestId'):snapshot['requestId']=current['requestId']
                history.append(snapshot)
                hall=state_get(c,'seasonHallOfFame',[]) or []
                if leaderboard:
                    winner=leaderboard[0]
                    hall.append({'id':'SF'+secrets.token_hex(7),'seasonId':season_id,'seasonName':snapshot['name'],'accountId':winner['accountId'],'ign':winner['ign'],'points':winner['points'],'completedAt':completed_at})
                state_set(c,'seasonHistory',history);state_set(c,'seasonHallOfFame',hall);state_set(c,'currentSeason',None)
                create_owner_notification(c,session,'owner_season_complete','season',season_id,'Season completed','An Overall Owner completed the current season.','community')
                insert_audit(c,session,'owner_season_complete','season',season_id,{'leaderboardSize':len(leaderboard)})
                c.commit();safe=safe_owner_tournament_value(c,snapshot)
        except Exception:
            logging.exception('Owner season completion failed.')
            return json_response(self,{'error':'The season could not be completed.'},503)
        return json_response(self,{'history':safe,'alreadyCompleted':False})

    def owner_history(self):
        session=require_overall_owner(self)
        if not session:return
        with LOCK,db() as c:
            result={key:safe_owner_tournament_value(c,state_get(c,key,[]) or []) for key in ('seasonHistory','seasonHallOfFame','hallOfFame')}
        return json_response(self,result)

    def owner_history_correct(self,domain,entry_id):
        session=require_overall_owner(self)
        if not session:return
        domains={'hall-of-fame':('hallOfFame',{'title','champion','runnerUp','date'}),'season-hall-of-fame':('seasonHallOfFame',{'seasonName','accountId','ign','points'})}
        if domain not in domains:return json_response(self,{'error':'Unsupported history domain.'},400)
        data=read_json(self);reason=data.get('reason')
        if not isinstance(reason,str) or not reason.strip() or len(reason.strip())>500:return json_response(self,{'error':'A correction reason is required.'},400)
        state_key,allowed=domains[domain];changes={key:value for key,value in data.items() if key!='reason'}
        if not changes or set(changes)-allowed:return json_response(self,{'error':'Unsupported history correction field.'},400)
        text_limits={'title':200,'champion':120,'runnerUp':120,'date':10,'seasonName':120,'accountId':120,'ign':120}
        for key,value in changes.items():
            if key=='points':
                if isinstance(value,bool) or not isinstance(value,int) or value<0 or value>100000000:return json_response(self,{'error':'points must be an integer between 0 and 100000000.'},400)
            elif not isinstance(value,str) or not value.strip() or len(value.strip())>text_limits[key]:
                return json_response(self,{'error':f'{key} must be valid bounded text.'},400)
            else:changes[key]=value.strip()
        if 'date' in changes:
            try:datetime.strptime(changes['date'],'%Y-%m-%d')
            except ValueError:return json_response(self,{'error':'date must be a valid YYYY-MM-DD date.'},400)
        try:
            with LOCK,db() as c:
                lock_state_workflow(c)
                items=state_get(c,state_key,[]) or [];entry=next((item for item in items if isinstance(item,dict) and str(item.get('id'))==entry_id),None)
                if not entry:return json_response(self,{'error':'History entry not found.'},404)
                account_fields=('champion','runnerUp') if domain=='hall-of-fame' else ('accountId',)
                for key in account_fields:
                    if key in changes and not c.execute('SELECT 1 FROM community_accounts WHERE id=? OR ign=?',(changes[key],changes[key])).fetchone():
                        return json_response(self,{'error':f'{key} must identify a Community account.'},400)
                if domain=='season-hall-of-fame' and ('accountId' in changes or 'ign' in changes):
                    identity=str(changes.get('accountId') or entry.get('accountId') or '')
                    account=c.execute('SELECT ign FROM community_accounts WHERE id=?',(identity,)).fetchone()
                    if not account or ('ign' in changes and changes['ign']!=str(account['ign'])):
                        return json_response(self,{'error':'The Hall of Fame identity must match a Community account.'},400)
                    changes['accountId']=identity;changes['ign']=str(account['ign'])
                before={key:entry.get(key) for key in changes};entry.update(changes);entry['correctedAt']=now_iso();entry['correctedBy']=str(session.get('id'))
                state_set(c,state_key,items)
                insert_audit(c,session,'owner_hall_of_fame_correct','history',entry_id,{'domain':domain,'before':before,'changes':changes,'reason':reason.strip()})
                c.commit();safe=safe_owner_tournament_value(c,entry)
        except Exception:
            logging.exception('Owner history correction failed.')
            return json_response(self,{'error':'The history correction could not be saved.'},503)
        return json_response(self,{'entry':safe})

    def owner_events(self):
        session=require_overall_owner(self)
        if not session:return
        with LOCK,db() as c:
            events=state_get(c,'events',[]) or [];participation=state_get(c,'eventParticipation',[]) or []
            safe_events=safe_owner_tournament_value(c,events);safe_participation=safe_owner_tournament_value(c,participation)
        return json_response(self,{'events':safe_events,'participation':safe_participation})

    def _owner_event_values(self,data,existing=None):
        existing=existing if isinstance(existing,dict) else {};allowed={'title','date','time','description','rules','rewardPoints'}
        if set(data)-allowed:return None,'Unsupported event field.'
        item=dict(existing)
        for key,limit in (('title',180),('description',8000),('rules',8000)):
            if key in data:
                if not isinstance(data[key],str) or not data[key].strip() or len(data[key].strip())>limit:return None,f'{key} must be valid text.'
                item[key]=data[key].strip()
        if 'date' in data:
            if not isinstance(data['date'],str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',data['date']):return None,'date must use YYYY-MM-DD.'
            try:datetime.strptime(data['date'],'%Y-%m-%d')
            except ValueError:return None,'date must be a real calendar date.'
            item['date']=data['date']
        if 'time' in data:
            if not isinstance(data['time'],str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',data['time']):return None,'time must use HH:MM.'
            item['time']=data['time']
        if 'rewardPoints' in data:
            value=data['rewardPoints']
            if isinstance(value,bool) or not isinstance(value,int) or value<0 or value>1000000:return None,'rewardPoints must be a non-negative integer.'
            item['rewardPoints']=value
        if not existing and (not item.get('title') or not item.get('date')):return None,'title and date are required.'
        item.setdefault('rewardPoints',0)
        return item,None

    def owner_event_create(self):
        session=require_overall_owner(self)
        if not session:return
        data=read_json(self);request_id=data.pop('requestId',None)
        if request_id is not None and (not isinstance(request_id,str) or not request_id.strip() or len(request_id)>120):return json_response(self,{'error':'requestId must be a valid identifier.'},400)
        values,error=self._owner_event_values(data)
        if error:return json_response(self,{'error':error},400)
        event={**values,'id':'E'+secrets.token_hex(7),'status':'Draft','createdAt':now_iso(),'createdBy':str(session.get('id'))}
        if request_id:event['requestId']=request_id.strip()
        try:
            with LOCK,db() as c:
                lock_state_workflow(c)
                events=state_get(c,'events',[]) or []
                existing=next((item for item in events if isinstance(item,dict) and request_id and item.get('requestId')==request_id.strip()),None)
                if existing:return json_response(self,{'event':safe_owner_tournament_value(c,existing)},200)
                events.append(event);state_set(c,'events',events)
                insert_audit(c,session,'owner_event_create','event',event['id'],{'title':event['title']});c.commit();safe=safe_owner_tournament_value(c,event)
        except Exception:
            logging.exception('Owner event creation failed.');return json_response(self,{'error':'The event could not be created.'},503)
        return json_response(self,{'event':safe},201)

    def owner_event_update(self,event_id):
        session=require_overall_owner(self)
        if not session:return
        data=read_json(self)
        try:
            with LOCK,db() as c:
                lock_state_workflow(c)
                events=state_get(c,'events',[]) or [];event=owner_tournament_by_id(events,event_id)
                if not event:return json_response(self,{'error':'Event not found.'},404)
                if event.get('status') in ('Closed','Archived'):return json_response(self,{'error':'Event cannot be edited in its current state.'},409)
                values,error=self._owner_event_values(data,event)
                if error:return json_response(self,{'error':error},400)
                event.update(values,updatedAt=now_iso(),updatedBy=str(session.get('id')));state_set(c,'events',events)
                insert_audit(c,session,'owner_event_update','event',event_id,{'fields':sorted(data)});c.commit();safe=safe_owner_tournament_value(c,event)
        except Exception:
            logging.exception('Owner event update failed.');return json_response(self,{'error':'The event could not be updated.'},503)
        return json_response(self,{'event':safe})

    def owner_event_transition(self,event_id,action):
        session=require_overall_owner(self)
        if not session:return
        transitions={'publish':('Draft','Published'),'close':('Published','Closed'),'archive':('Closed','Archived')}
        before,after=transitions[action]
        try:
            with LOCK,db() as c:
                lock_state_workflow(c)
                events=state_get(c,'events',[]) or [];event=owner_tournament_by_id(events,event_id)
                if not event:return json_response(self,{'error':'Event not found.'},404)
                if event.get('status')!=before:return json_response(self,{'error':'Event cannot make that transition.'},409)
                event['status']=after;event[action+'edAt' if action!='close' else 'closedAt']=now_iso();state_set(c,'events',events)
                create_owner_notification(c,session,'owner_event_'+action,'event',event_id,f'Event {after.lower()}',f'An Overall Owner {action}ed an event.','community')
                insert_audit(c,session,'owner_event_'+action,'event',event_id,{'status':after});c.commit();safe=safe_owner_tournament_value(c,event)
        except Exception:
            logging.exception('Owner event transition failed.');return json_response(self,{'error':'The event transition could not be saved.'},503)
        return json_response(self,{'event':safe})

    def owner_event_participation(self,event_id):
        session=require_overall_owner(self)
        if not session:return
        account_id=str(read_json(self).get('accountId','')).strip()
        if not account_id:return json_response(self,{'error':'A Community account id is required.'},400)
        try:
            with LOCK,db() as c:
                lock_state_workflow(c)
                events=state_get(c,'events',[]) or [];event=owner_tournament_by_id(events,event_id)
                if not event:return json_response(self,{'error':'Event not found.'},404)
                if event.get('status')!='Published':return json_response(self,{'error':'Participation is only available for published events.'},409)
                account=c.execute("SELECT id FROM community_accounts WHERE id=? AND status='Active'",(account_id,)).fetchone()
                if not account:return json_response(self,{'error':'Active Community account not found.'},404)
                current=state_get(c,'currentSeason',None);season_id=str(current.get('id')) if isinstance(current,dict) else ''
                reward=int(event.get('rewardPoints',0) or 0)
                if reward and not season_id:return json_response(self,{'error':'Point-bearing participation requires an active season.'},409)
                items=state_get(c,'eventParticipation',[]) or []
                existing=next((item for item in items if isinstance(item,dict) and str(item.get('eventId'))==event_id and str(item.get('accountId'))==account_id and str(item.get('seasonId',''))==season_id),None)
                if existing:return json_response(self,{'participation':safe_owner_tournament_value(c,existing),'pointsAwarded':0,'created':False})
                record={'id':'EP'+secrets.token_hex(7),'eventId':event_id,'accountId':account_id,'seasonId':season_id,'pointsAwarded':reward,'createdAt':now_iso(),'createdBy':str(session.get('id'))}
                items.append(record);points=state_get(c,'seasonPoints',{}) or {};points[account_id]=int(points.get(account_id,0) or 0)+reward
                state_set(c,'eventParticipation',items);state_set(c,'seasonPoints',points)
                create_owner_notification(c,session,'owner_event_participation','event',event_id,'Event participation recorded','An Overall Owner recorded your event participation.','community',account_id)
                insert_audit(c,session,'owner_event_participation','event',event_id,{'accountId':account_id,'pointsAwarded':reward,'seasonId':season_id});c.commit();safe=safe_owner_tournament_value(c,record)
        except Exception:
            logging.exception('Owner event participation failed.');return json_response(self,{'error':'Event participation could not be recorded.'},503)
        return json_response(self,{'participation':safe,'pointsAwarded':reward,'created':True},201)

    def owner_tournaments_list(self):
        session=require_overall_owner(self)
        if not session:return
        with LOCK,db() as c:
            items=[]
            for tournament in state_get(c,'tournaments',[]):
                if not isinstance(tournament,dict):continue
                detail=owner_tournament_projection(c,tournament)
                items.append({**detail['tournament'],'registrations':detail['registrations'],'approvals':detail['approvals'],'bracket':detail['bracket'],'resultSubmissions':detail['resultSubmissions'],'disputes':detail['disputes']})
        return json_response(self,{'tournaments':items})

    def owner_tournament_detail(self,tournament_id):
        session=require_overall_owner(self)
        if not session:return
        with LOCK,db() as c:
            tournament=owner_tournament_by_id(state_get(c,'tournaments',[]),tournament_id)
            if not tournament:return json_response(self,{'error':'Tournament not found.'},404)
            detail=owner_tournament_projection(c,tournament)
        return json_response(self,detail)

    def owner_tournament_create(self):
        session=require_overall_owner(self)
        if not session:return
        normalized,error=normalize_owner_tournament(read_json(self))
        if error:return json_response(self,{'error':error},400)
        tournament={**normalized,'id':'T'+secrets.token_hex(7),'status':'Open','matches':[],'bracketReady':False,'createdAt':now_iso(),'createdBy':str(session.get('id'))}
        try:
            with LOCK,db() as c:
                tournaments=state_get(c,'tournaments',[])
                if not isinstance(tournaments,list):tournaments=[]
                tournaments.append(tournament);state_set(c,'tournaments',tournaments)
                create_owner_notification(c,session,'owner_tournament_create','tournament',tournament['id'],'Tournament created','An Overall Owner created a tournament.','community')
                insert_audit(c,session,'owner_tournament_create','tournament',tournament['id'],{'title':tournament['title']})
                c.commit();safe=safe_owner_tournament_value(c,tournament)
        except Exception:
            logging.exception('Owner tournament creation failed.')
            return json_response(self,{'error':'The tournament could not be created.'},503)
        return json_response(self,{'tournament':safe},201)

    def owner_tournament_update(self,tournament_id):
        session=require_overall_owner(self)
        if not session:return
        data=read_json(self)
        try:
            with LOCK,db() as c:
                lock_state_workflow(c)
                tournaments=state_get(c,'tournaments',[]);tournament=owner_tournament_by_id(tournaments,tournament_id)
                if not tournament:return json_response(self,{'error':'Tournament not found.'},404)
                if overview_status(tournament.get('status')) in ('completed','archived','cancelled','canceled'):
                    return json_response(self,{'error':'Tournament cannot be edited in its current state.'},409)
                normalized,error=normalize_owner_tournament(data,tournament)
                if error:return json_response(self,{'error':error},400)
                tournament.update(normalized);tournament.update(updatedAt=now_iso(),updatedBy=str(session.get('id')))
                state_set(c,'tournaments',tournaments)
                create_owner_notification(c,session,'owner_tournament_update','tournament',tournament_id,'Tournament updated','An Overall Owner updated tournament details.','community')
                insert_audit(c,session,'owner_tournament_update','tournament',tournament_id,{'fields':sorted(data)})
                c.commit();safe=safe_owner_tournament_value(c,tournament)
        except Exception:
            logging.exception('Owner tournament update failed.')
            return json_response(self,{'error':'The tournament could not be updated.'},503)
        return json_response(self,{'tournament':safe})

    def owner_tournament_registration_decision(self,tournament_id,registration_id):
        session=require_overall_owner(self)
        if not session:return
        action=str(read_json(self).get('action','')).strip().lower()
        if action not in ('approve','reject','withdraw','reinstate'):return json_response(self,{'error':'Unsupported registration decision.'},400)
        try:
            with LOCK,db() as c:
                tournament=owner_tournament_by_id(state_get(c,'tournaments',[]),tournament_id)
                if not tournament:return json_response(self,{'error':'Tournament not found.'},404)
                if overview_status(tournament.get('status'))!='open' or tournament.get('bracketReady'):
                    return json_response(self,{'error':'Registration decisions are closed.'},409)
                registrations=state_get(c,'registrations',[])
                registration=next((item for item in registrations if isinstance(item,dict) and str(item.get('id'))==registration_id and str(item.get('tournamentId'))==tournament_id),None)
                if not registration:return json_response(self,{'error':'Registration not found.'},404)
                allowed={'approve':('registered','pending'),'reject':('registered','pending'),'withdraw':('registered','pending','approved'),'reinstate':('withdrawn','rejected')}
                if overview_status(registration.get('status')) not in allowed[action]:return json_response(self,{'error':'Registration cannot make that transition.'},409)
                registration['status']={'approve':'Approved','reject':'Rejected','withdraw':'Withdrawn','reinstate':'Registered'}[action]
                registration.update(updatedAt=now_iso(),decidedBy=str(session.get('id')));state_set(c,'registrations',registrations)
                audit_action='owner_tournament_registration_'+action
                create_owner_notification(c,session,audit_action,'registration',registration_id,'Tournament registration updated','An Overall Owner updated your tournament registration.','community',registration.get('accountId'))
                insert_audit(c,session,audit_action,'registration',registration_id,{'tournamentId':tournament_id})
                c.commit();safe=safe_owner_tournament_value(c,registration)
        except Exception:
            logging.exception('Owner tournament registration decision failed.')
            return json_response(self,{'error':'The registration decision could not be saved.'},503)
        return json_response(self,{'registration':safe})

    def owner_tournament_approval_decision(self,tournament_id,approval_id):
        session=require_overall_owner(self)
        if not session:return
        action=str(read_json(self).get('action','')).strip().lower()
        if action not in ('approve','reject'):return json_response(self,{'error':'Unsupported Squad approval decision.'},400)
        try:
            with LOCK,db() as c:
                lock_state_workflow(c)
                tournaments=state_get(c,'tournaments',[]);tournament=owner_tournament_by_id(tournaments,tournament_id)
                if not tournament:return json_response(self,{'error':'Tournament not found.'},404)
                if tournament.get('format')!='Squad vs Squad':return json_response(self,{'error':'This is not a Squad tournament.'},400)
                if overview_status(tournament.get('status'))!='open' or tournament.get('bracketReady') or tournament.get('squadRegistrationOpen') is False:
                    return json_response(self,{'error':'Squad approval decisions are closed.'},409)
                approvals=state_get(c,'squadTournamentApprovals',[])
                approval=next((item for item in approvals if isinstance(item,dict) and str(item.get('id'))==approval_id and str(item.get('tournamentId'))==tournament_id),None)
                if not approval:return json_response(self,{'error':'Squad approval request not found.'},404)
                if overview_status(approval.get('status'))!='pending':return json_response(self,{'error':'Squad approval request was already decided.'},409)
                if action=='approve':
                    approved=sum(1 for item in approvals if isinstance(item,dict) and str(item.get('tournamentId'))==tournament_id and overview_status(item.get('status'))=='approved')
                    capacity=int(tournament.get('squadSlots') or 0)
                    if capacity and approved>=capacity:return json_response(self,{'error':'Squad slots are full.'},409)
                    approval.update(status='Approved',approvedAt=now_iso(),approvedBy=str(session.get('id')),memberAccessCode='DS-SQUAD-'+secrets.token_hex(4).upper(),memberAccessCodeCreatedAt=now_iso())
                    tournament['approvedSquadCount']=approved+1
                    if capacity and tournament['approvedSquadCount']>=capacity:tournament['squadRegistrationOpen']=False
                else:
                    approval.update(status='Rejected',rejectedAt=now_iso(),rejectedBy=str(session.get('id')))
                state_set(c,'squadTournamentApprovals',approvals);state_set(c,'tournaments',tournaments)
                audit_action='owner_tournament_approval_'+action
                create_owner_notification(c,session,audit_action,'approval',approval_id,'Squad tournament request updated','An Overall Owner decided your Squad tournament request.','community',approval.get('leaderAccountId'))
                insert_audit(c,session,audit_action,'approval',approval_id,{'tournamentId':tournament_id})
                c.commit();safe=safe_owner_tournament_value(c,approval);safe_tournament=safe_owner_tournament_value(c,tournament)
        except Exception:
            logging.exception('Owner Squad tournament approval decision failed.')
            return json_response(self,{'error':'The Squad approval decision could not be saved.'},503)
        return json_response(self,{'approval':safe,'tournament':safe_tournament})

    def owner_tournament_manager_change(self,member_id,path_action=''):
        session=require_overall_owner(self)
        if not session:return
        action=str(path_action or read_json(self).get('action','')).strip().lower()
        if action not in ('grant','revoke'):return json_response(self,{'error':'Action must be grant or revoke.'},400)
        try:
            with LOCK,db() as c:
                member=c.execute('SELECT * FROM squad_members WHERE id=?',(member_id,)).fetchone()
                if not member:return json_response(self,{'error':'Squad member not found.'},404)
                if member['role'] not in ('Squad Leader','Assistant Squad Leader'):
                    return json_response(self,{'error':'Only active Squad Leaders and Assistant Squad Leaders are eligible.'},400)
                if member['status']=='Disabled' or not member['account_activated']:
                    return json_response(self,{'error':'Only active Squad members are eligible.'},409)
                managers=state_get(c,'tournamentManagers',[])
                if not isinstance(managers,list):managers=[]
                granted=any(str(item)==str(member_id) or (isinstance(item,dict) and str(item.get('id') or item.get('accountId'))==str(member_id)) for item in managers)
                if action=='grant':
                    if granted:return json_response(self,{'error':'Tournament Manager permission is already granted.'},409)
                    managers.append(str(member_id))
                else:
                    if not granted:return json_response(self,{'error':'Tournament Manager permission is not granted.'},409)
                    managers=[item for item in managers if not (str(item)==str(member_id) or (isinstance(item,dict) and str(item.get('id') or item.get('accountId'))==str(member_id)))]
                    revoke_user_sessions(c,'squad',member_id)
                state_set(c,'tournamentManagers',managers);audit_action='owner_tournament_manager_'+action
                create_owner_notification(c,session,audit_action,'squad_member',member_id,'Tournament Manager permission updated','An Overall Owner updated Tournament Manager permission.','squad',member_id)
                insert_audit(c,session,audit_action,'squad_member',member_id)
                c.commit()
        except Exception:
            logging.exception('Owner Tournament Manager permission change failed.')
            return json_response(self,{'error':'Tournament Manager permission could not be changed.'},503)
        return json_response(self,{'ok':True,'memberId':str(member_id),'granted':action=='grant'})

    def owner_tournament_transition(self,tournament_id,action):
        session=require_overall_owner(self)
        if not session:return
        try:
            with LOCK,db() as c:
                tournaments=state_get(c,'tournaments',[]);tournament=owner_tournament_by_id(tournaments,tournament_id)
                if not tournament:return json_response(self,{'error':'Tournament not found.'},404)
                status=overview_status(tournament.get('status'))
                if action=='bracket':
                    if status!='open' or tournament.get('bracketReady'):return json_response(self,{'error':'The bracket cannot be generated in the current state.'},409)
                    registrations=[item for item in state_get(c,'registrations',[]) if isinstance(item,dict) and str(item.get('tournamentId'))==tournament_id]
                    matches,error=generate_owner_bracket(tournament,registrations)
                    if error:return json_response(self,{'error':error},400)
                    tournament.update(matches=matches,bracketReady=True,registrationOpen=False,squadRegistrationOpen=False,status='In Progress',bracketGeneratedAt=now_iso(),bracketGeneratedBy=str(session.get('id')))
                    audit_action='owner_tournament_bracket_generate';title='Tournament bracket generated'
                elif action=='complete':
                    if status not in ('inprogress','completed') or not tournament.get('bracketReady'):return json_response(self,{'error':'Tournament cannot be completed in its current state.'},409)
                    if status=='completed' and tournament.get('ownerCompletionReviewed'):return json_response(self,{'error':'Tournament completion was already reviewed.'},409)
                    matches=tournament.get('matches') or []
                    if any(match.get('player1') and match.get('player2') and not match.get('winner') for match in matches if isinstance(match,dict)):
                        return json_response(self,{'error':'Every played match must have a confirmed result.'},409)
                    final_round=max((int(match.get('round') or 1) for match in matches if isinstance(match,dict)),default=0)
                    final=next((match for match in reversed(matches) if isinstance(match,dict) and int(match.get('round') or 1)==final_round and match.get('winner')),None)
                    if not final:return json_response(self,{'error':'A confirmed final result is required.'},409)
                    runner_up=final.get('player2') if str(final.get('winner'))==str(final.get('player1')) else final.get('player1')
                    tournament.update(status='Completed',completed=True,ownerCompletionReviewed=True,registrationOpen=False,squadRegistrationOpen=False,champion=final.get('winner'),runnerUp=runner_up,completedAt=tournament.get('completedAt') or now_iso(),completedBy=str(session.get('id')))
                    hall=state_get(c,'hallOfFame',[]) or []
                    history=next((item for item in hall if isinstance(item,dict) and str(item.get('tournamentId'))==tournament_id),None)
                    history_values={'tournamentId':tournament_id,'title':tournament.get('title'),'champion':tournament.get('champion'),'runnerUp':runner_up,'date':tournament.get('date'),'completedAt':tournament.get('completedAt')}
                    if history:history.update(history_values)
                    else:hall.append({'id':'H'+secrets.token_hex(6),**history_values})
                    state_set(c,'hallOfFame',hall)
                    audit_action='owner_tournament_complete';title='Tournament completed'
                elif action=='archive':
                    if status!='completed':return json_response(self,{'error':'Only a completed tournament can be archived.'},409)
                    tournament.update(status='Archived',archivedAt=now_iso(),archivedBy=str(session.get('id')))
                    audit_action='owner_tournament_archive';title='Tournament archived'
                elif action=='cancel':
                    if status not in ('open','inprogress'):return json_response(self,{'error':'Tournament cannot be cancelled in its current state.'},409)
                    tournament.update(statusBeforeCancellation=tournament.get('status'),registrationOpenBeforeCancellation=bool(tournament.get('registrationOpen')),squadRegistrationOpenBeforeCancellation=bool(tournament.get('squadRegistrationOpen')),status='Cancelled',registrationOpen=False,squadRegistrationOpen=False,cancelledAt=now_iso(),cancelledBy=str(session.get('id')))
                    registrations=state_get(c,'registrations',[])
                    for registration in registrations:
                        if not isinstance(registration,dict) or str(registration.get('tournamentId'))!=tournament_id:continue
                        if overview_status(registration.get('status')) in ('registered','pending','approved'):
                            registration['statusBeforeCancellation']=registration.get('status') or 'Registered'
                            registration.update(status='Tournament Cancelled',cancelledAt=now_iso(),cancelledBy=str(session.get('id')))
                    approvals=state_get(c,'squadTournamentApprovals',[])
                    for approval in approvals:
                        if not isinstance(approval,dict) or str(approval.get('tournamentId'))!=tournament_id:continue
                        if overview_status(approval.get('status')) in ('pending','approved'):
                            approval['statusBeforeCancellation']=approval.get('status')
                            approval.update(status='Tournament Cancelled',cancelledAt=now_iso(),cancelledBy=str(session.get('id')))
                    state_set(c,'registrations',registrations);state_set(c,'squadTournamentApprovals',approvals)
                    audit_action='owner_tournament_cancel';title='Tournament cancelled'
                elif action=='reinstate':
                    if status!='cancelled':return json_response(self,{'error':'Only a cancelled tournament can be reinstated.'},409)
                    try:cancelled=datetime.fromisoformat(str(tournament.get('cancelledAt','')).replace('Z','+00:00')).timestamp()
                    except ValueError:return json_response(self,{'error':'The reinstatement window has expired.'},409)
                    if time.time()-cancelled>1800:return json_response(self,{'error':'The reinstatement window has expired.'},409)
                    tournament.update(status=tournament.get('statusBeforeCancellation') or 'Open',registrationOpen=bool(tournament.get('registrationOpenBeforeCancellation')),cancelledAt=None,cancelledBy=None)
                    if tournament.get('format')=='Squad vs Squad' and not tournament.get('bracketReady'):
                        tournament['squadRegistrationOpen']=bool(tournament.get('squadRegistrationOpenBeforeCancellation'))
                    registrations=state_get(c,'registrations',[])
                    for registration in registrations:
                        if not isinstance(registration,dict) or str(registration.get('tournamentId'))!=tournament_id:continue
                        if overview_status(registration.get('status'))=='tournamentcancelled' and overview_status(registration.get('statusBeforeCancellation')) in ('registered','pending','approved'):
                            registration['status']=registration.pop('statusBeforeCancellation')
                            registration.pop('cancelledAt',None);registration.pop('cancelledBy',None)
                    approvals=state_get(c,'squadTournamentApprovals',[])
                    for approval in approvals:
                        if not isinstance(approval,dict) or str(approval.get('tournamentId'))!=tournament_id:continue
                        if overview_status(approval.get('status'))=='tournamentcancelled' and overview_status(approval.get('statusBeforeCancellation')) in ('pending','approved'):
                            approval['status']=approval.pop('statusBeforeCancellation')
                            approval.pop('cancelledAt',None);approval.pop('cancelledBy',None)
                    state_set(c,'registrations',registrations);state_set(c,'squadTournamentApprovals',approvals)
                    audit_action='owner_tournament_reinstate';title='Tournament reinstated'
                state_set(c,'tournaments',tournaments)
                create_owner_notification(c,session,audit_action,'tournament',tournament_id,title,'An Overall Owner changed a tournament lifecycle state.','community')
                insert_audit(c,session,audit_action,'tournament',tournament_id)
                c.commit();safe=safe_owner_tournament_value(c,tournament)
        except Exception:
            logging.exception('Owner tournament transition failed.')
            return json_response(self,{'error':'The tournament transition could not be saved.'},503)
        return json_response(self,{'tournament':safe})

    def owner_tournament_match_change(self,tournament_id,match_id,method):
        session=require_overall_owner(self)
        if not session:return
        try:
            with LOCK,db() as c:
                tournaments=state_get(c,'tournaments',[]);tournament=owner_tournament_by_id(tournaments,tournament_id)
                if not tournament:return json_response(self,{'error':'Tournament not found.'},404)
                if overview_status(tournament.get('status'))!='inprogress':return json_response(self,{'error':'Matches can only change while a tournament is in progress.'},409)
                matches=tournament.get('matches') if isinstance(tournament.get('matches'),list) else []
                match=owner_tournament_by_id(matches,match_id)
                if not match:return json_response(self,{'error':'Match not found.'},404)
                if match.get('winner') or match.get('submission'):return json_response(self,{'error':'A match with result activity cannot be changed.'},409)
                if method=='DELETE':matches.remove(match);safe=None;action='delete'
                else:
                    data=read_json(self);allowed=('scheduledAt','venue','streamUrl','status')
                    if not data or set(data)-set(allowed):return json_response(self,{'error':'Unsupported match field.'},400)
                    if 'status' in data and data['status'] not in OWNER_MATCH_STATUSES:return json_response(self,{'error':'Match status is invalid.'},400)
                    for key,value in data.items():
                        if not isinstance(value,str) or len(value.strip())>500:return json_response(self,{'error':f'{key} must be bounded text.'},400)
                        match[key]=value.strip()
                    match.update(updatedAt=now_iso(),updatedBy=str(session.get('id')));safe=match;action='update'
                state_set(c,'tournaments',tournaments);audit_action='owner_tournament_match_'+action
                create_owner_notification(c,session,audit_action,'match',match_id,'Tournament match updated','An Overall Owner updated a tournament match.','community')
                insert_audit(c,session,audit_action,'match',match_id,{'tournamentId':tournament_id})
                c.commit();safe=safe_owner_tournament_value(c,safe) if safe else None
        except Exception:
            logging.exception('Owner tournament match change failed.')
            return json_response(self,{'error':'The match change could not be saved.'},503)
        return json_response(self,{'ok':True,'match':safe})

    def owner_tournament_match_create(self,tournament_id):
        session=require_overall_owner(self)
        if not session:return
        data=read_json(self);allowed={'id','player1','player2','round','number','scheduledAt','venue','streamUrl','status'}
        if set(data)-allowed:return json_response(self,{'error':'Unsupported match field.'},400)
        player1=str(data.get('player1','')).strip();player2=str(data.get('player2','')).strip()
        if not player1 or not player2 or player1==player2:return json_response(self,{'error':'Two distinct registered participants are required.'},400)
        round_number=data.get('round',1);match_number=data.get('number')
        if isinstance(round_number,bool) or not isinstance(round_number,int) or round_number<1:return json_response(self,{'error':'round must be a positive integer.'},400)
        if match_number is not None and (isinstance(match_number,bool) or not isinstance(match_number,int) or match_number<1):return json_response(self,{'error':'number must be a positive integer.'},400)
        for key in ('scheduledAt','venue','streamUrl','status'):
            if key in data and (not isinstance(data[key],str) or len(data[key].strip())>500):return json_response(self,{'error':f'{key} must be bounded text.'},400)
        if 'status' in data and data['status'] not in OWNER_MATCH_STATUSES:return json_response(self,{'error':'Match status is invalid.'},400)
        requested_id=str(data.get('id','')).strip()
        if requested_id and not OWNER_CONTENT_ID.fullmatch(requested_id):return json_response(self,{'error':'Match id is invalid.'},400)
        try:
            with LOCK,db() as c:
                tournaments=state_get(c,'tournaments',[]);tournament=owner_tournament_by_id(tournaments,tournament_id)
                if not tournament:return json_response(self,{'error':'Tournament not found.'},404)
                if overview_status(tournament.get('status'))!='inprogress':return json_response(self,{'error':'Matches can only be created while a tournament is in progress.'},409)
                eligible={str(item.get('accountId')) for item in state_get(c,'registrations',[]) if isinstance(item,dict) and str(item.get('tournamentId'))==tournament_id and overview_status(item.get('status')) in ('registered','approved')}
                if player1 not in eligible or player2 not in eligible:return json_response(self,{'error':'Match participants must have eligible tournament registrations.'},400)
                matches=tournament.get('matches') if isinstance(tournament.get('matches'),list) else []
                match_id=requested_id or f'{tournament_id}-M-{secrets.token_hex(4)}'
                if owner_tournament_by_id(matches,match_id):return json_response(self,{'error':'Match already exists.'},409)
                match={'id':match_id,'round':round_number,'number':match_number or (max((int(item.get('number') or 0) for item in matches if isinstance(item,dict)),default=0)+1),'player1':player1,'player2':player2,'winner':None,'submission':None,'createdAt':now_iso(),'createdBy':str(session.get('id'))}
                for key in ('scheduledAt','venue','streamUrl','status'):
                    if key in data:match[key]=data[key].strip()
                matches.append(match);tournament['matches']=matches;state_set(c,'tournaments',tournaments)
                create_owner_notification(c,session,'owner_tournament_match_create','match',match_id,'Tournament match created','An Overall Owner created a tournament match.','community')
                insert_audit(c,session,'owner_tournament_match_create','match',match_id,{'tournamentId':tournament_id})
                c.commit();safe=safe_owner_tournament_value(c,match)
        except Exception:
            logging.exception('Owner tournament match creation failed.')
            return json_response(self,{'error':'The match could not be created.'},503)
        return json_response(self,{'match':safe},201)

    def owner_tournament_result_change(self,tournament_id,match_id):
        session=require_overall_owner(self)
        if not session:return
        data=read_json(self);action=str(data.get('action','')).strip().lower()
        if action not in ('confirm','correct','resolve','reject'):return json_response(self,{'error':'Unsupported result action.'},400)
        try:
            with LOCK,db() as c:
                lock_state_workflow(c)
                tournaments=state_get(c,'tournaments',[]);tournament=owner_tournament_by_id(tournaments,tournament_id)
                if not tournament:return json_response(self,{'error':'Tournament not found.'},404)
                tournament_status=overview_status(tournament.get('status'))
                if tournament_status not in ('inprogress','completed') or (tournament_status=='completed' and action!='correct'):
                    return json_response(self,{'error':'Results cannot make that transition in the current tournament state.'},409)
                match=owner_tournament_by_id(tournament.get('matches') or [],match_id)
                if not match:return json_response(self,{'error':'Match not found.'},404)
                submission=match.get('submission')
                if action=='confirm':
                    if not isinstance(submission,dict) or overview_status(submission.get('status'))!='awaitingconfirmation' or match.get('winner'):
                        return json_response(self,{'error':'The result is not awaiting confirmation.'},409)
                    winner=str(submission.get('winner',''))
                elif action=='reject':
                    if not isinstance(submission,dict) or overview_status(submission.get('status')) not in ('awaitingconfirmation','disputed'):
                        return json_response(self,{'error':'The result is not open for rejection.'},409)
                    match['submission']=None
                    winner='';audit_action='owner_tournament_result_reject'
                else:
                    if action=='resolve' and (not isinstance(submission,dict) or overview_status(submission.get('status'))!='disputed'):
                        return json_response(self,{'error':'Only a disputed result can be resolved.'},409)
                    reason=str(data.get('reason','')).strip()
                    if not reason:return json_response(self,{'error':'A correction or resolution reason is required.'},400)
                    winner=str(data.get('winner',''))
                if action!='reject':
                    participants={str(match.get('player1')),str(match.get('player2'))}
                    if winner not in participants:return json_response(self,{'error':'Winner must be a match participant.'},400)
                    target=owner_tournament_by_id(tournament.get('matches') or [],match.get('nextMatchId'))
                    if action=='correct' and target and (target.get('winner') or target.get('submission') or target.get('result') or target.get('pointsAwarded')):
                        return json_response(self,{'error':'An upstream result cannot be corrected after downstream result activity.'},409)
                    previous=str(match.get('winner') or '');points=state_get(c,'seasonPoints',{}) or {}
                    if match.get('pointsAwarded') and previous:
                        old_loser=str(match.get('player2')) if previous==str(match.get('player1')) else str(match.get('player1'))
                        points[previous]=max(0,int(points.get(previous,0))-100)
                        if old_loser and old_loser!='None':points[old_loser]=max(0,int(points.get(old_loser,0))-50)
                    loser=str(match.get('player2')) if winner==str(match.get('player1')) else str(match.get('player1'))
                    points[winner]=int(points.get(winner,0))+100
                    if loser and loser!='None':points[loser]=int(points.get(loser,0))+50
                    state_set(c,'seasonPoints',points)
                    match.update(winner=winner,verifiedAt=now_iso(),verifiedBy=str(session.get('id')),pointsAwarded=True)
                    if not isinstance(submission,dict):submission={}
                    submission.update(winner=winner,status='Owner Confirmed' if action=='confirm' else 'Owner Corrected',reviewedAt=now_iso(),reviewedBy=str(session.get('id')))
                    if action in ('correct','resolve'):submission['reviewReason']=str(data.get('reason')).strip()
                    match['submission']=submission
                    if target:
                        slot=match.get('nextSlot') if match.get('nextSlot') in ('player1','player2') else ('player1' if not target.get('player1') else 'player2')
                        if previous and target.get(slot)==previous and previous!=winner:target[slot]=winner
                        elif not target.get(slot):target[slot]=winner
                    final_round=max((int(item.get('round') or 1) for item in tournament.get('matches',[]) if isinstance(item,dict)),default=0)
                    if tournament_status=='completed' and int(match.get('round') or 1)==final_round:
                        tournament['champion']=winner;tournament['runnerUp']=loser
                        hall=state_get(c,'hallOfFame',[]) or []
                        history_entry=next((item for item in hall if isinstance(item,dict) and str(item.get('tournamentId'))==tournament_id),None)
                        if history_entry:
                            history_entry.update(champion=winner,runnerUp=loser,correctedAt=now_iso(),correctedBy=str(session.get('id')))
                            state_set(c,'hallOfFame',hall)
                    audit_action='owner_tournament_result_'+action
                state_set(c,'tournaments',tournaments)
                create_owner_notification(c,session,audit_action,'match',match_id,'Tournament result reviewed','An Overall Owner reviewed a tournament result.','community')
                insert_audit(c,session,audit_action,'match',match_id,{'tournamentId':tournament_id,'reason':data.get('reason','')})
                c.commit();safe=safe_owner_tournament_value(c,match)
        except Exception:
            logging.exception('Owner tournament result change failed.')
            return json_response(self,{'error':'The result change could not be saved.'},503)
        return json_response(self,{'match':safe})

    def roles_info(self):
        return json_response(self, {'roles': {
            'Overall Owner': ['system:*','squad:*','tournament:*','community:*','audit:read'],
            'Squad Owner': ['squad:manage','squad:members','tournament:manage','tournament:approve'],
            'Squad Leader': ['squad:members:edit'],
            'Assistant Squad Leader': ['squad:members:edit'],
            'Squad Member': ['squad:profile:self'],
            'Community Member': ['community:profile:self','tournament:register'],
            'Tournament Manager': ['tournament:manage','tournament:approve']
        }})

    def squad_role_change(self):
        s=require_auth(self,['squad','owner'])
        if not s:return
        if s.get('role') not in ('Squad Owner','Overall Owner'):
            return json_response(self,{'error':'Only the Owner can change squad roles.'},403)
        d=read_json(self); mid=str(d.get('memberId','')); role=str(d.get('role','')).strip()
        if not mid or role not in SQUAD_ROLES:return json_response(self,{'error':'A valid member and squad role are required.'},400)
        if role=='Squad Owner' and s.get('role')!='Overall Owner':
            return json_response(self,{'error':'Only the Overall Owner can appoint another Squad Owner.'},403)
        try:
            with LOCK, db() as c:
                row=c.execute('SELECT * FROM squad_members WHERE id=?',(mid,)).fetchone()
                if not row:return json_response(self,{'error':'Member not found.'},404)
                if row['role']=='Squad Owner' and role!='Squad Owner':
                    return json_response(self, {'error':'Appoint a replacement before changing the active Squad Owner.'},409)
                if role=='Squad Owner':
                    if row['status']=='Disabled' or not row['account_activated']:
                        return json_response(self, {'error':'Only an active Squad member can be appointed Squad Owner.'},409)
                    former=c.execute("SELECT id FROM squad_members WHERE role='Squad Owner' AND id!=?",(mid,)).fetchall()
                    c.execute("UPDATE squad_members SET role='Squad Member' WHERE role='Squad Owner' AND id!=?",(mid,))
                    for old in former: revoke_user_sessions(c,'squad',old['id'])
                elif role != row['role']:
                    revoke_user_sessions(c,'squad',mid)
                if role not in ('Squad Leader','Assistant Squad Leader'):
                    remove_tournament_manager_permission(c,mid)
                c.execute('UPDATE squad_members SET role=? WHERE id=?',(role,mid))
                row=c.execute('SELECT * FROM squad_members WHERE id=?',(mid,)).fetchone()
                if s.get('type') == 'owner' and s.get('role') == 'Overall Owner':
                    create_owner_notification(
                        c, s, 'owner_squad_role_change', 'squad_member', mid,
                        'Squad role updated', 'An Overall Owner updated a Squad role.', 'squad', mid,
                    )
                insert_audit(c,s,'role_change','squad_member',mid,{'role':role})
                c.commit()
        except Exception:
            logging.exception('Squad role change failed.')
            return json_response(self, {'error':'The Squad role could not be changed.'},503)
        member=safe_owner_squad_member(row) if s.get('role')=='Overall Owner' else public_member(row,True)
        return json_response(self,{'member':member})

    def tournament_manager_allowed(self, session):
        with LOCK, db() as c:
            managers=state_get(c,'tournamentManagers',[])
        return tournament_manager_identity(session, managers)

    def community_register(self):
        d=read_json(self); email=str(d.get('email','')).strip().lower(); password=str(d.get('password',''))
        if not email or len(password)<8: return json_response(self, {'error':'Email and a password of at least 8 characters are required.'},400)
        with LOCK, db() as c:
            if c.execute('SELECT 1 FROM community_accounts WHERE lower(email)=?',(email,)).fetchone(): return json_response(self, {'error':'An account with this email already exists.'},409)
            aid=str(int(time.time()*1000)); created=now_iso()
            c.execute('INSERT INTO community_accounts(id,squad_member_id,ign,game_id,server_id,email,phone,password_hash,role,lane,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(aid,d.get('squadMemberId'),str(d.get('ign','')).strip(),str(d.get('gameId','')).strip(),str(d.get('serverId','')).strip(),email,str(d.get('phone','')).strip(),hash_password(password),'Community Member',d.get('lane',''),created))
            c.commit(); row=c.execute('SELECT * FROM community_accounts WHERE id=?',(aid,)).fetchone()
        token=create_session('community',aid,row['role'] or 'Community Member');
        return json_response(self, {'account':public_account(row)},200,{'Set-Cookie':session_cookie(self, token)})
    def community_login(self):
        d=read_json(self); email=str(d.get('email','')).strip().lower(); password=str(d.get('password',''))
        with LOCK, db() as c: row=c.execute('SELECT * FROM community_accounts WHERE lower(email)=?',(email,)).fetchone()
        if not row or str(row['status'] or '').strip().lower() == 'disabled' or not verify_password(password,row['password_hash']): return json_response(self, {'error':'The email or password is incorrect.'},401)
        token=create_session('community',row['id'],row['role'] or 'Community Member')
        return json_response(self, {'account':public_account(row)},200,{'Set-Cookie':session_cookie(self, token)})
    def community_forgot(self):
        d=read_json(self); email=str(d.get('email','')).strip().lower()
        with LOCK, db() as c: row=c.execute('SELECT * FROM community_accounts WHERE lower(email)=?',(email,)).fetchone()
        # Always return the same response to reduce account enumeration.
        if row and str(row['status'] or '').strip().lower()!='disabled':
            code=f'{secrets.randbelow(900000)+100000}'; exp=int(time.time())+600
            encoded=hash_recovery_code(code)
            with LOCK, db() as c:
                c.execute('UPDATE community_accounts SET reset_code=?,reset_expires=? WHERE id=?',(encoded,exp,row['id'])); c.commit()
            delivered=False
            try:delivered=bool(smtp_send(email,'Your Dark System password reset code',f'Your Dark System password reset code is {code}. It expires in 10 minutes.'))
            except Exception:logging.exception('Community recovery email delivery failed.')
            if not delivered:
                with LOCK,db() as c:
                    c.execute('UPDATE community_accounts SET reset_code=NULL,reset_expires=NULL WHERE id=? AND reset_code=?',(row['id'],encoded));c.commit()
        return json_response(self, {'ok':True,'message':'If that account exists, a reset code has been sent.'})
    def community_reset(self):
        d=read_json(self); email=str(d.get('email','')).strip().lower(); code=str(d.get('code','')).strip(); password=str(d.get('password',''))
        with LOCK, db() as c: row=c.execute('SELECT * FROM community_accounts WHERE lower(email)=?',(email,)).fetchone()
        if not row or not verify_recovery_code(code,row['reset_code']) or not row['reset_expires'] or int(row['reset_expires'])<int(time.time()): return json_response(self, {'error':'The reset code is invalid or expired.'},400)
        if len(password)<8:return json_response(self, {'error':'Password must be at least 8 characters.'},400)
        try:
            with LOCK, db() as c:
                current=c.execute('SELECT reset_code,reset_expires FROM community_accounts WHERE id=?',(row['id'],)).fetchone()
                if not current or not verify_recovery_code(code,current['reset_code']) or int(current['reset_expires'] or 0)<int(time.time()):
                    return json_response(self, {'error':'The reset code is invalid or expired.'},400)
                claimed=c.execute(
                    '''UPDATE community_accounts SET password_hash=?,reset_code=NULL,reset_expires=NULL
                       WHERE id=? AND reset_code=? AND reset_expires=?''',
                    (hash_password(password),row['id'],current['reset_code'],current['reset_expires']),
                )
                if claimed.rowcount!=1:
                    return json_response(self, {'error':'The reset code is invalid or expired.'},400)
                revoke_user_sessions(c,'community',row['id'])
                insert_audit(c,{'type':'community','id':row['id'],'role':row['role'] or 'Community Member'},'community_password_reset','community_account',row['id'])
                c.commit()
        except Exception:
            logging.exception('Community password reset failed.')
            return json_response(self,{'error':'The password could not be reset.'},503)
        return json_response(self, {'ok':True})
    def community_profile(self):
        s=require_auth(self,['community'])
        if not s:return
        d=read_json(self)
        with LOCK, db() as c:
            row=c.execute('SELECT * FROM community_accounts WHERE id=?',(s['id'],)).fetchone()
            if not row:return json_response(self,{'error':'Community account not found.'},404)
            email_notifications,error=json_bool(d,'emailNotifications',row['email_notifications'])
            if error:return json_response(self,{'error':error},400)
            email=str(d.get('email',row['email'])).strip().lower()
            if email!=row['email'].lower() and c.execute('SELECT 1 FROM community_accounts WHERE lower(email)=? AND id!=?',(email,s['id'])).fetchone():
                return json_response(self,{'error':'That email is already in use.'},409)
            c.execute("UPDATE community_accounts SET ign=?,game_id=?,server_id=?,phone=?,lane=?,email=?,email_notifications=? WHERE id=?", (str(d.get('ign',row['ign'])).strip(),str(d.get('gameId',row['game_id'])).strip(),str(d.get('serverId',row['server_id'])).strip(),str(d.get('phone',row['phone'])).strip(),str(d.get('lane',row['lane'])).strip(),email,1 if email_notifications else 0,s['id']))
            c.commit(); row=c.execute('SELECT * FROM community_accounts WHERE id=?',(s['id'],)).fetchone()
        self.audit(s,'community_profile_update','community_account',s['id'])
        return json_response(self,{'account':public_account(row)})

    def community_notifications_read_all(self):
        s=require_auth(self,['community'])
        if not s:return
        with LOCK, db() as c:
            notes=state_get(c,'community_notifications',[]); changed=0
            for n in notes:
                if not n.get('audienceId') or str(n.get('audienceId'))==str(s['id']):
                    if not n.get('read'): changed+=1
                    n['read']=True
            for row in c.execute("SELECT id,payload FROM notifications WHERE domain='community'").fetchall():
                try: payload=json.loads(row['payload'])
                except Exception: continue
                if not isinstance(payload,dict) or (payload.get('audienceId') and str(payload['audienceId'])!=str(s['id'])): continue
                if not notification_is_read(c,row['id'],'community',s['id']): changed+=1
                mark_notification_read(c,row['id'],'community',s['id'])
            state_set(c,'community_notifications',notes); c.commit()
        self.audit(s,'community_notifications_read_all','community_account',s['id'],{'changed':changed})
        return json_response(self,{'ok':True,'changed':changed})

    def community_notification_read(self):
        s=require_auth(self,['community'])
        if not s:return
        d=read_json(self); nid=str(d.get('id',''))
        with LOCK, db() as c:
            notes=state_get(c,'community_notifications',[]); changed=False
            for n in notes:
                if str(n.get('id'))==nid and (not n.get('audienceId') or str(n.get('audienceId'))==str(s['id'])):
                    n['read']=True; changed=True
            row=c.execute("SELECT payload FROM notifications WHERE id=? AND domain='community'",(nid,)).fetchone()
            if row:
                try: payload=json.loads(row['payload'])
                except Exception: payload=None
                if isinstance(payload,dict) and (not payload.get('audienceId') or str(payload['audienceId'])==str(s['id'])):
                    changed=not notification_is_read(c,nid,'community',s['id']); mark_notification_read(c,nid,'community',s['id'])
            if changed: state_set(c,'community_notifications',notes); c.commit()
        return json_response(self,{'ok':True,'changed':changed})

    def squad_notification_read(self):
        s=require_auth(self,['squad'])
        if not s:return
        nid=str(read_json(self).get('id',''))
        with LOCK, db() as c:
            row=c.execute("SELECT payload FROM notifications WHERE id=? AND domain='squad'",(nid,)).fetchone()
            if not row:return json_response(self,{'ok':True,'changed':False})
            try: payload=json.loads(row['payload'])
            except Exception: payload=None
            if not isinstance(payload,dict) or (payload.get('audienceId') and str(payload['audienceId'])!=str(s['id'])):
                return json_response(self,{'ok':True,'changed':False})
            changed=not notification_is_read(c,nid,'squad',s['id']); mark_notification_read(c,nid,'squad',s['id']); c.commit()
        return json_response(self,{'ok':True,'changed':changed})

    def squad_notifications_read_all(self):
        s=require_auth(self,['squad'])
        if not s:return
        changed=0
        with LOCK, db() as c:
            for row in c.execute("SELECT id,payload FROM notifications WHERE domain='squad'").fetchall():
                try: payload=json.loads(row['payload'])
                except Exception: continue
                if not isinstance(payload,dict) or (payload.get('audienceId') and str(payload['audienceId'])!=str(s['id'])): continue
                if not notification_is_read(c,row['id'],'squad',s['id']): changed+=1
                mark_notification_read(c,row['id'],'squad',s['id'])
            c.commit()
        return json_response(self,{'ok':True,'changed':changed})

    def squad_content_write(self):
        s=require_auth(self,['squad','owner'])
        if not s:return
        if s.get('role') not in ('Squad Owner','Squad Leader','Assistant Squad Leader','Overall Owner'):
            return json_response(self,{'error':'Squad leadership permission is required.'},403)
        d=read_json(self); kind=str(d.get('kind','')).strip(); key={'announcement':'announcements','event':'events','report':'reports','complaint':'complaints'}.get(kind)
        if not key:return json_response(self,{'error':'Unsupported squad content type.'},400)
        item=dict(d.get('item') or {}); item.pop('password',None); item['id']=item.get('id') or 'SC'+secrets.token_hex(6); item['authorId']=s['id']; item['updatedAt']=now_iso(); item.setdefault('createdAt',item['updatedAt'])
        with LOCK, db() as c:
            items=state_get(c,key,[]); replaced=False
            for i,x in enumerate(items):
                if str(x.get('id'))==str(item['id']): items[i]={**x,**item}; replaced=True; break
            if not replaced: items.append(item)
            state_set(c,key,items); c.commit()
        self.audit(s,'squad_'+kind+'_'+('update' if replaced else 'create'),key,item['id'])
        return json_response(self,{'item':item},200 if replaced else 201)

    def squad_content_delete(self):
        s=require_auth(self,['squad','owner'])
        if not s:return
        if s.get('role') not in ('Squad Owner','Overall Owner'):
            return json_response(self,{'error':'Owner permission is required to delete squad content.'},403)
        d=read_json(self); kind=str(d.get('kind','')).strip(); key={'announcement':'announcements','event':'events','report':'reports','complaint':'complaints'}.get(kind); iid=str(d.get('id',''))
        if not key or not iid:return json_response(self,{'error':'Content type and id are required.'},400)
        with LOCK, db() as c:
            items=state_get(c,key,[]); new=[x for x in items if str(x.get('id'))!=iid]
            if len(new)==len(items):return json_response(self,{'error':'Content not found.'},404)
            state_set(c,key,new); c.commit()
        self.audit(s,'squad_'+kind+'_delete',key,iid); return json_response(self,{'ok':True})

    def squad_login(self):
        d=read_json(self); ign=str(d.get('ign','')).strip().lower(); gid=str(d.get('gameId','')).strip(); sid=str(d.get('serverId','')).strip(); code=str(d.get('accessCode','')).strip().upper()
        with LOCK, db() as c: row=c.execute('SELECT * FROM squad_members WHERE lower(ign)=? AND game_id=? AND server_id=? AND status!=? AND account_activated=1',(ign,gid,sid,'Disabled')).fetchone()
        if not row or not access_code_matches(code,row):return json_response(self, {'error':'The In-Game Name, IDs or access code were not recognized.'},401)
        stamp=now_iso()
        with LOCK, db() as c:
            if not row['access_code_hash']:
                c.execute('UPDATE squad_members SET access_code_hash=?,access_code=? WHERE id=?',(hash_password(code),'',row['id']))
            c.execute('UPDATE squad_members SET status=?,last_login=? WHERE id=?',('Online',stamp,row['id'])); c.commit(); row=c.execute('SELECT * FROM squad_members WHERE id=?',(row['id'],)).fetchone()
        token=create_session('squad',row['id'],row['role'])
        return json_response(self, {'member':public_member(row,True)},200,{'Set-Cookie':session_cookie(self, token)})

    def squad_forgot(self):
        data=read_json(self)
        email=str(data.get('email','')).strip().lower();ign=str(data.get('ign','')).strip()
        game_id=str(data.get('gameId','')).strip();server_id=str(data.get('serverId','')).strip()
        with LOCK,db() as c:
            row=c.execute(
                '''SELECT * FROM squad_members WHERE lower(email)=? AND ign=? AND game_id=? AND server_id=?
                   AND status!=? AND (account_activated=1 OR recovery_pending=1)''',
                (email,ign,game_id,server_id,'Disabled'),
            ).fetchone()
        if row:
            code=f'{secrets.randbelow(900000)+100000}';expires=int(time.time())+RECOVERY_TTL
            recovery_id='RC'+secrets.token_hex(8)
            try:
                with LOCK,db() as c:
                    c.execute("UPDATE recovery_codes SET used_at=? WHERE account_type='squad' AND account_id=? AND used_at IS NULL",(int(time.time()),row['id']))
                    c.execute('INSERT INTO recovery_codes(id,account_type,account_id,code_hash,expires_at,used_at,created_at) VALUES(?,?,?,?,?,?,?)',(
                        recovery_id,'squad',row['id'],hash_recovery_code(code),expires,None,now_iso(),
                    ))
                    c.commit()
                delivered=bool(smtp_send(email,'Your Dark System Squad recovery code',f'Your Dark System Squad recovery code is {code}. It expires in 10 minutes.'))
                if not delivered:
                    with LOCK,db() as c:
                        c.execute('UPDATE recovery_codes SET used_at=? WHERE id=? AND used_at IS NULL',(int(time.time()),recovery_id));c.commit()
            except Exception:
                logging.exception('Squad recovery email delivery failed.')
                with LOCK,db() as c:
                    c.execute('UPDATE recovery_codes SET used_at=? WHERE id=? AND used_at IS NULL',(int(time.time()),recovery_id));c.commit()
        return json_response(self,{'ok':True,'message':'If those account details match, a recovery code has been sent.'})

    def squad_reset(self):
        data=read_json(self);email=str(data.get('email','')).strip().lower();ign=str(data.get('ign','')).strip()
        game_id=str(data.get('gameId','')).strip();server_id=str(data.get('serverId','')).strip()
        code=str(data.get('code','')).strip();new_code=str(data.get('accessCode','')).strip().upper()
        if len(new_code)<8:return json_response(self,{'error':'The new access code must be at least 8 characters.'},400)
        now=int(time.time())
        try:
            with LOCK,db() as c:
                row=c.execute(
                    '''SELECT * FROM squad_members WHERE lower(email)=? AND ign=? AND game_id=? AND server_id=?
                       AND status!=? AND (account_activated=1 OR recovery_pending=1)''',(email,ign,game_id,server_id,'Disabled'),
                ).fetchone()
                recovery=c.execute(
                    '''SELECT * FROM recovery_codes WHERE account_type='squad' AND account_id=? AND used_at IS NULL
                       ORDER BY created_at DESC,id DESC LIMIT 1''',(row['id'] if row else '',),
                ).fetchone()
                if not row or not recovery or int(recovery['expires_at'])<now or not verify_recovery_code(code,recovery['code_hash']):
                    return json_response(self,{'error':'The recovery code is invalid or expired.'},400)
                claimed=c.execute('UPDATE recovery_codes SET used_at=? WHERE id=? AND used_at IS NULL',(now,recovery['id']))
                if claimed.rowcount!=1:
                    return json_response(self,{'error':'The recovery code is invalid or expired.'},400)
                c.execute('UPDATE squad_members SET access_code=?,access_code_hash=?,status=?,account_activated=1,recovery_pending=0 WHERE id=?',('',hash_password(new_code),'Offline',row['id']))
                revoke_user_sessions(c,'squad',row['id'])
                insert_audit(c,{'type':'squad','id':row['id'],'role':row['role']},'squad_access_code_reset','squad_member',row['id'])
                c.commit()
        except Exception:
            logging.exception('Squad access code reset failed.')
            return json_response(self,{'error':'The access code could not be reset.'},503)
        return json_response(self,{'ok':True})
    def squad_profile(self):
        s=require_auth(self,['squad']);
        if not s:return
        d=read_json(self)
        with LOCK, db() as c:
            row=c.execute('SELECT * FROM squad_members WHERE id=?',(s['id'],)).fetchone()
            if not row:return json_response(self,{'error':'Squad profile not found.'},404)
            if not access_code_matches(d.get('accessCode',''),row):return json_response(self,{'error':'Access code verification failed.'},403)
            c.execute('UPDATE squad_members SET ign=?,game_id=?,server_id=?,lane=?,email=?,phone=?,birthday=?,profile_complete=1,account_activated=1,recovery_pending=0 WHERE id=?',(d.get('ign',''),d.get('gameId',''),d.get('serverId',''),d.get('lane',''),d.get('email',''),d.get('phone',''),d.get('birthday',''),s['id'])); c.commit(); row=c.execute('SELECT * FROM squad_members WHERE id=?',(s['id'],)).fetchone()
        return json_response(self, {'member':public_member(row,True)})
    def role_allowed(self, session, *roles):
        return session and session.get('role') in roles

    def state_write(self, key, value):
        with LOCK, db() as c:
            state_set(c, key, value)
            c.commit()

    def dedicated_write(self, domain):
        s=auth_from_cookie(self)
        if not s:
            json_response(self, {'error':'Authentication required'}, 401)
            return None
        return s

    def require_role(self, session, roles):
        if not session or session.get('role') not in roles:
            json_response(self, {'error':'You do not have permission to perform this action.'},403)
            return False
        return True

    def api_member_create(self):
        s=self.dedicated_write('members')
        if not s:return
        if not self.role_allowed(s,'Squad Owner','Overall Owner'):
            return json_response(self, {'error':'Owner permission is required to create squad members.'},403)
        d=read_json(self)
        required=['name','ign','gameId','serverId','accessCode']
        if any(not str(d.get(k,'')).strip() for k in required):
            return json_response(self, {'error':'Name, IGN, Game ID, Server ID and access code are required.'},400)
        submitted_access_code=str(d['accessCode']).strip().upper()
        if len(submitted_access_code)<8:
            return json_response(self,{'error':'Access code must be at least 8 characters.'},400)
        role=str(d.get('role','Squad Member')).strip() or 'Squad Member'
        status=str(d.get('status','Offline')).strip() or 'Offline'
        activated, error=json_bool(d,'accountActivated',False)
        if error:return json_response(self,{'error':error},400)
        if role not in SQUAD_ROLES or role=='Squad Owner':
            return json_response(self,{'error':'Use the Squad Owner appointment endpoint to appoint a Squad Owner.'},409)
        if status not in SQUAD_MEMBER_STATUSES:
            return json_response(self,{'error':'A valid Squad status is required.'},400)
        mid=str(int(time.time()*1000))
        try:
            with LOCK, db() as c:
                if identity_conflict(c,'squad_members',d['ign'],d['gameId'],d['serverId']):
                    return json_response(self, {'error':'A Squad member already uses that IGN, Game ID, or Server ID.'},409)
                c.execute("""INSERT INTO squad_members(id,name,ign,game_id,server_id,role,lane,email,phone,birthday,access_code,status,last_login,profile_complete,account_activated)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(mid,str(d['name']).strip(),str(d['ign']).strip(),str(d['gameId']).strip(),str(d['serverId']).strip(),role,str(d.get('lane','')),str(d.get('email','')),str(d.get('phone','')),str(d.get('birthday','')),'',status,None,0,1 if activated else 0))
                c.execute('UPDATE squad_members SET access_code_hash=? WHERE id=?',(hash_password(submitted_access_code),mid))
                row=c.execute('SELECT * FROM squad_members WHERE id=?',(mid,)).fetchone()
                insert_audit(c,s,'member_create','squad_member',mid,{'ign':row['ign'],'role':role})
                c.commit()
        except Exception as exc:
            if unique_constraint_violation(exc):
                return json_response(self, {'error':'A Squad member already uses that IGN, Game ID, or Server ID.'},409)
            logging.exception('Legacy Squad member creation failed.')
            return json_response(self, {'error':'The Squad member could not be created.'},503)
        member=safe_owner_squad_member(row) if s.get('role')=='Overall Owner' else public_member(row,True)
        if s.get('role')!='Overall Owner':member['accessCode']=submitted_access_code
        return json_response(self, {'member':member},201)

    def api_member_update(self):
        s=self.dedicated_write('members')
        if not s:return
        d=read_json(self); mid=str(d.get('id',''))
        if not mid:return json_response(self,{'error':'Member id is required.'},400)
        if 'accessCode' in d:
            return json_response(self,{'error':'Squad members rotate credentials through self-service recovery.'},400)
        if self.role_allowed(s,'Squad Owner','Overall Owner'):
            owner=True
        elif self.role_allowed(s,'Squad Leader','Assistant Squad Leader'):
            owner=False
        else:
            return json_response(self,{'error':'Leadership permission required.'},403)
        try:
            with LOCK, db() as c:
                row=c.execute('SELECT * FROM squad_members WHERE id=?',(mid,)).fetchone()
                if not row:return json_response(self,{'error':'Member not found.'},404)
                profile_complete, error=json_bool(d,'profileComplete',row['profile_complete'])
                if error:return json_response(self,{'error':error},400)
                account_activated, error=json_bool(d,'accountActivated',row['account_activated'])
                if error:return json_response(self,{'error':error},400)
                vals={
                  'name':str(d.get('name',row['name'])).strip(),'ign':str(d.get('ign',row['ign'])).strip(),'gameId':str(d.get('gameId',row['game_id'])).strip(),'serverId':str(d.get('serverId',row['server_id'])).strip(),
                  'role':str(d.get('role',row['role'])).strip(),'lane':str(d.get('lane',row['lane'] or '')).strip(),'email':str(d.get('email',row['email'] or '')).strip(),'phone':str(d.get('phone',row['phone'] or '')).strip(),
                  'birthday':str(d.get('birthday',row['birthday'] or '')).strip(),'accessCode':str(d.get('accessCode',row['access_code'])).strip().upper(),'status':str(d.get('status',row['status'])).strip(),
                  'profileComplete':1 if profile_complete else 0,'accountActivated':1 if account_activated else 0}
                if not owner:
                    vals['role']=row['role']; vals['accessCode']=row['access_code']; vals['profileComplete']=row['profile_complete']; vals['accountActivated']=row['account_activated']
                if not all(vals[key] for key in ('name','ign','gameId','serverId')) or not (vals['accessCode'] or row['access_code_hash']):
                    return json_response(self,{'error':'Name, IGN, Game ID, Server ID and access code cannot be empty.'},400)
                if vals['role'] not in SQUAD_ROLES or vals['status'] not in SQUAD_MEMBER_STATUSES:
                    return json_response(self,{'error':'A valid Squad role and status are required.'},400)
                if row['role']=='Squad Owner' and (vals['role']!='Squad Owner' or vals['status']=='Disabled' or not vals['accountActivated']):
                    return json_response(self,{'error':'Appoint a replacement before changing the active Squad Owner.'},409)
                if vals['role']=='Squad Owner' and row['role']!='Squad Owner':
                    if s.get('role')!='Overall Owner':
                        return json_response(self,{'error':'Only the Overall Owner can appoint another Squad Owner.'},403)
                    if vals['status']=='Disabled' or not vals['accountActivated']:
                        return json_response(self,{'error':'Only an active Squad member can be appointed Squad Owner.'},409)
                    former=c.execute("SELECT id FROM squad_members WHERE role='Squad Owner' AND id!=?",(mid,)).fetchall()
                    c.execute("UPDATE squad_members SET role='Squad Member' WHERE role='Squad Owner' AND id!=?",(mid,))
                    for old in former: revoke_user_sessions(c,'squad',old['id'])
                if identity_conflict(c,'squad_members',vals['ign'],vals['gameId'],vals['serverId'],mid):
                    return json_response(self,{'error':'A Squad member already uses that IGN, Game ID, or Server ID.'},409)
                new_access_hash=row['access_code_hash']
                recovery_pending=int(row['recovery_pending'] or 0)
                if vals['status']=='Disabled' or (owner and 'accountActivated' in d):
                    recovery_pending=0
                c.execute("""UPDATE squad_members SET name=?,ign=?,game_id=?,server_id=?,role=?,lane=?,email=?,phone=?,birthday=?,access_code=?,access_code_hash=?,status=?,profile_complete=?,account_activated=?,recovery_pending=? WHERE id=?""",(vals['name'],vals['ign'],vals['gameId'],vals['serverId'],vals['role'],vals['lane'],vals['email'],vals['phone'],vals['birthday'],vals['accessCode'],new_access_hash,vals['status'],vals['profileComplete'],vals['accountActivated'],recovery_pending,mid))
                if vals['role'] != row['role'] or vals['status']=='Disabled' or not vals['accountActivated']:
                    revoke_user_sessions(c,'squad',mid)
                if vals['role'] not in ('Squad Leader','Assistant Squad Leader') or vals['status']=='Disabled' or not vals['accountActivated']:
                    remove_tournament_manager_permission(c,mid)
                row=c.execute('SELECT * FROM squad_members WHERE id=?',(mid,)).fetchone()
                insert_audit(c,s,'member_update','squad_member',mid,{'role':vals['role'],'status':vals['status']})
                c.commit()
        except Exception as exc:
            if unique_constraint_violation(exc):
                return json_response(self, {'error':'A Squad member already uses that IGN, Game ID, or Server ID.'},409)
            logging.exception('Legacy Squad member update failed.')
            return json_response(self, {'error':'The Squad member could not be updated.'},503)
        member=safe_owner_squad_member(row) if s.get('role')=='Overall Owner' else public_member(row,True)
        return json_response(self, {'member':member})

    def api_member_delete(self):
        s=self.dedicated_write('members')
        if not s:return
        if not self.role_allowed(s,'Squad Owner','Overall Owner'):return json_response(self,{'error':'Owner permission is required to remove members.'},403)
        d=read_json(self); mid=str(d.get('id',''))
        if not mid:return json_response(self,{'error':'A valid member id is required.'},400)
        try:
            with LOCK, db() as c:
                row=c.execute('SELECT role FROM squad_members WHERE id=?',(mid,)).fetchone()
                if not row:return json_response(self,{'error':'Member not found.'},404)
                if row['role']=='Squad Owner':return json_response(self,{'error':'Appoint a replacement before removing the active Squad Owner.'},409)
                revoke_user_sessions(c,'squad',mid)
                remove_tournament_manager_permission(c,mid)
                c.execute('DELETE FROM squad_members WHERE id=?',(mid,))
                insert_audit(c,s,'member_delete','squad_member',mid)
                c.commit()
        except Exception:
            logging.exception('Legacy Squad member deletion failed.')
            return json_response(self, {'error':'The Squad member could not be removed.'},503)
        return json_response(self, {'ok':True})

    def api_tournament_write(self, action):
        s=self.dedicated_write('tournaments')
        if not s:return
        if not self.tournament_manager_allowed(s):
            return json_response(self,{'error':'Tournament Manager permission is required.'},403)
        d=read_json(self)
        with LOCK, db() as c:
            tours=state_get(c,'tournaments',[])
            if action=='create':
                t=dict(d); t['id']=t.get('id') or 'T'+secrets.token_hex(5); t.setdefault('status','Open'); t.setdefault('registrationOpen',True); t.setdefault('matches',[])
                tours.append(t); state_set(c,'tournaments',tours); c.commit(); self.audit(s,'tournament_create','tournament',t['id'],{'title':t.get('title','')}); return json_response(self,{'tournament':t},201)
            tid=str(d.get('id','')); t=next((x for x in tours if str(x.get('id'))==tid),None)
            if not t:return json_response(self,{'error':'Tournament not found.'},404)
            if action=='edit':
                for k,v in d.items():
                    if k not in {'id','matches','champion','runnerUp','completedAt'}:t[k]=v
            elif action=='cancel':
                if t.get('status') in ('Cancelled','Completed'):return json_response(self,{'error':'Tournament cannot be cancelled in its current state.'},409)
                t.update(status='Cancelled',registrationOpen=False,cancelledAt=now_iso(),cancelledBy=s['id'])
            elif action=='reinstate':
                if t.get('status')!='Cancelled':return json_response(self,{'error':'Tournament is not cancelled.'},409)
                if t.get('cancelledAt'):
                    try: age=time.time()-time.mktime(time.strptime(t['cancelledAt'],'%Y-%m-%dT%H:%M:%SZ'))
                    except Exception: age=10**9
                    if age>1800:return json_response(self,{'error':'The 30-minute reinstatement window has expired.'},409)
                t.update(status='Open',registrationOpen=True,cancelledAt=None,cancelledBy=None)
            state_set(c,'tournaments',tours); c.commit(); self.audit(s,'tournament_'+action,'tournament',tid); return json_response(self,{'tournament':t})

    def api_tournament_bracket(self):
        s=self.dedicated_write('tournament_bracket')
        if not s:return
        if not self.tournament_manager_allowed(s): return json_response(self,{'error':'Tournament Manager permission is required.'},403)
        d=read_json(self); tid=str(d.get('tournamentId',''))
        if not tid:return json_response(self,{'error':'Tournament id is required.'},400)
        with LOCK, db() as c:
            tours=state_get(c,'tournaments',[]); t=next((x for x in tours if str(x.get('id'))==tid),None)
            if not t:return json_response(self,{'error':'Tournament not found.'},404)
            regs=[r for r in state_get(c,'registrations',[]) if str(r.get('tournamentId'))==tid and str(r.get('status','')).lower() not in ('withdrawn','tournament cancelled','rejected')]
            ids=[r.get('accountId') for r in regs if r.get('accountId') is not None]
            if len(ids)<2:return json_response(self,{'error':'At least two registered players are needed.'},400)
            size=1
            while size<len(ids): size*=2
            ids += [None]*(size-len(ids))
            matches=[]; current=ids[:]; round_no=1; match_no=1
            while len(current)>1:
                nxt=[None]*((len(current)+1)//2)
                for i in range(0,len(current),2):
                    a,b=current[i],current[i+1]; mid=f'{tid}-M{match_no}'
                    winner=a if a and not b else b if b and not a else None
                    matches.append({'id':mid,'number':match_no,'round':round_no,'player1':a,'player2':b,'winner':winner,'submission':None})
                    nxt[i//2]=winner
                    match_no+=1
                current=nxt; round_no+=1
            for r in range(1,round_no):
                prev=[m for m in matches if m['round']==r]; nxt=[m for m in matches if m['round']==r+1]
                for m in prev:
                    if m.get('winner'):
                        target=nxt[(m['number']-1)//2] if nxt else None
                        if target and not target.get('player1'): target['player1']=m['winner']
                        elif target and not target.get('player2'): target['player2']=m['winner']
            t['matches']=matches; t['bracketReady']=True; t['registrationOpen']=False; t['status']=t.get('status') or 'Open'; t['bracketGeneratedAt']=now_iso()
            state_set(c,'tournaments',tours); c.commit()
        self.audit(s,'tournament_bracket_generate','tournament',tid,{'matches':len(matches)})
        return json_response(self,{'tournament':t})

    def api_tournament_match(self, action):
        s=self.dedicated_write('tournaments')
        if not s:return
        if not self.tournament_manager_allowed(s): return json_response(self,{'error':'Tournament Manager permission is required.'},403)
        d=read_json(self); tid=str(d.get('tournamentId','')); mid=str(d.get('matchId',''))
        if not tid:return json_response(self,{'error':'Tournament id is required.'},400)
        with LOCK, db() as c:
            tours=state_get(c,'tournaments',[]); t=next((x for x in tours if str(x.get('id'))==tid),None)
            if not t:return json_response(self,{'error':'Tournament not found.'},404)
            matches=t.setdefault('matches',[])
            if action=='upsert':
                if not mid: mid='M'+secrets.token_hex(5)
                match=dict(d.get('match') or {}); match['id']=mid; match['updatedAt']=now_iso(); found=False
                for i,m in enumerate(matches):
                    if str(m.get('id'))==mid: matches[i]={**m,**match}; found=True; break
                if not found: matches.append(match)
            else:
                match=next((m for m in matches if str(m.get('id'))==mid),None)
                if not match:return json_response(self,{'error':'Match not found.'},404)
                if action=='result': match.update(result=d.get('result') or {},resultStatus='Pending Confirmation',resultSubmittedAt=now_iso(),resultSubmittedBy=s['id'])
                else:
                    if not match.get('result'):return json_response(self,{'error':'A result must exist before completion.'},409)
                    match.update(resultStatus='Confirmed',completedAt=now_iso(),completedBy=s['id'])
            state_set(c,'tournaments',tours); c.commit()
        self.audit(s,'tournament_match_'+action,'tournament',tid,{'matchId':mid}); return json_response(self,{'tournament':t})

    def api_squad_approval(self):
        s=self.dedicated_write('squadTournamentApprovals')
        if not s:return
        d=read_json(self); action=str(d.get('action','')); tid=str(d.get('tournamentId','')); aid=str(d.get('approvalId',''))
        if action in ('submit_leader','join_member'):
            if s.get('type')!='community':return json_response(self,{'error':'Community authentication required.'},403)
        elif not self.tournament_manager_allowed(s):
            return json_response(self,{'error':'Tournament Manager permission is required.'},403)
        with LOCK, db() as c:
            lock_state_workflow(c)
            approvals=state_get(c,'squadTournamentApprovals',[]); tours=state_get(c,'tournaments',[])
            t=next((x for x in tours if str(x.get('id'))==tid),None)
            if not t:return json_response(self,{'error':'Tournament not found.'},404)
            if action=='submit_leader':
                if str(t.get('format'))!='Squad vs Squad':return json_response(self,{'error':'Invalid tournament type.'},400)
                if str(t.get('status','')).lower()!='open' or t.get('registrationOpen') is False or t.get('squadRegistrationOpen') is False or registration_deadline_expired(t.get('registrationDeadline')):return json_response(self,{'error':'Squad registration is closed.'},409)
                if not workflow_code_matches(d.get('accessCode'),t.get('leaderAccessCode')):return json_response(self,{'error':'The tournament invitation code is invalid.'},403)
                squad=d.get('squad') or {}; leader=str(s.get('id'))
                if not squad.get('squadName') or not squad.get('squadId'):return json_response(self,{'error':'Squad name and ID are required.'},400)
                account=c.execute('SELECT * FROM community_accounts WHERE id=?',(leader,)).fetchone()
                if not account:return json_response(self,{'error':'Community account not found.'},404)
                if any(str(a.get('tournamentId'))==tid and a.get('status') in ('Pending','Approved') and str(a.get('leaderAccountId'))==leader for a in approvals):return json_response(self,{'error':'Registration already submitted.'},409)
                if any(str(a.get('tournamentId'))==tid and a.get('status')=='Approved' and str(a.get('squadId','')).lower()==str(squad['squadId']).lower() for a in approvals):return json_response(self,{'error':'Squad already registered.'},409)
                approved=sum(1 for a in approvals if str(a.get('tournamentId'))==tid and a.get('status')=='Approved')
                if int(t.get('squadSlots') or 0) and approved>=int(t.get('squadSlots')):return json_response(self,{'error':'Squad slots are full.'},409)
                a={'id':'STA'+secrets.token_hex(7),'tournamentId':tid,'tournamentTitle':t.get('title'),'squadName':str(squad['squadName']).strip(),'squadId':str(squad['squadId']).strip(),'leaderAccountId':leader,'leaderIgn':str(account['ign'] or ''),'leaderGameId':str(account['game_id'] or ''),'leaderServerId':str(account['server_id'] or ''),'role':'Squad Leader','status':'Pending','createdAt':now_iso(),'maxSquads':int(t.get('squadSlots') or 0),'membersPerSquad':int(t.get('membersPerSquad') or 7)}
                approvals.append(a); state_set(c,'squadTournamentApprovals',approvals); c.commit()
                own_approvals=[item for item in approvals if str(item.get('leaderAccountId'))==leader]
                self.audit(s,'squad_tournament_submit','approval',a['id'],{'tournamentId':tid})
                return json_response(self,{'approval':a,'approvals':own_approvals},201)
            if action=='join_member':
                if str(t.get('format'))!='Squad vs Squad':return json_response(self,{'error':'Invalid tournament type.'},400)
                if str(t.get('status','')).lower()!='open' or t.get('registrationOpen') is False or registration_deadline_expired(t.get('registrationDeadline')):return json_response(self,{'error':'Squad registration is closed.'},409)
                a=next((item for item in approvals if str(item.get('tournamentId'))==tid and item.get('status')=='Approved' and workflow_code_matches(d.get('accessCode'),item.get('memberAccessCode'))),None)
                if not a:return json_response(self,{'error':'The squad member access code is invalid.'},403)
                regs=state_get(c,'registrations',[]); account_id=str(s.get('id'))
                if any(str(reg.get('tournamentId'))==tid and str(reg.get('accountId'))==account_id for reg in regs):return json_response(self,{'error':'You are already registered.'},409)
                squad_count=sum(1 for reg in regs if str(reg.get('tournamentId'))==tid and str(reg.get('squadApprovalId'))==str(a.get('id')))
                maximum=int(t.get('membersPerSquad') or a.get('membersPerSquad') or 7)
                if squad_count>=maximum:return json_response(self,{'error':'This squad is full.'},409)
                account=c.execute('SELECT * FROM community_accounts WHERE id=?',(account_id,)).fetchone()
                if not account:return json_response(self,{'error':'Community account not found.'},404)
                registration={'id':'R'+secrets.token_hex(6),'accountId':account_id,'tournamentId':tid,'ign':str(account['ign'] or ''),'gameId':str(account['game_id'] or ''),'serverId':str(account['server_id'] or ''),'status':'Registered','registeredAt':now_iso(),'squadApprovalId':a.get('id'),'squadName':a.get('squadName'),'squadId':a.get('squadId'),'squadRole':'Squad Leader' if account_id==str(a.get('leaderAccountId')) else 'Squad Member','isSubstitute':squad_count>=5}
                regs.append(registration); state_set(c,'registrations',regs); c.commit()
                own_regs=[reg for reg in regs if str(reg.get('accountId'))==account_id]
                self.audit(s,'squad_tournament_join','registration',registration['id'],{'tournamentId':tid,'approvalId':a.get('id')})
                return json_response(self,{'registration':registration,'registrations':own_regs},201)
            a=next((x for x in approvals if str(x.get('id'))==aid and str(x.get('tournamentId'))==tid),None)
            if not a:return json_response(self,{'error':'Approval request not found.'},404)
            if a.get('status')!='Pending':return json_response(self,{'error':'Request already decided.'},409)
            if action=='approve':
                approved=sum(1 for x in approvals if str(x.get('tournamentId'))==tid and x.get('status')=='Approved')
                if int(t.get('squadSlots') or 0) and approved>=int(t.get('squadSlots')):return json_response(self,{'error':'Squad slots are full.'},409)
                a.update(status='Approved',updatedAt=now_iso(),approvedBy=s.get('id'),memberAccessCode='DS-SQUAD-'+secrets.token_hex(4).upper(),memberAccessCodeCreatedAt=now_iso())
                t['approvedSquadCount']=approved+1
                if int(t.get('squadSlots') or 0) and t['approvedSquadCount']>=int(t.get('squadSlots')):t['squadRegistrationOpen']=False
            elif action=='reject': a.update(status='Rejected',updatedAt=now_iso(),rejectedBy=s.get('id'))
            else:return json_response(self,{'error':'Unsupported approval action.'},400)
            state_set(c,'squadTournamentApprovals',approvals); state_set(c,'tournaments',tours); c.commit()
        self.audit(s,'squad_tournament_'+action,'approval',aid,{'tournamentId':tid}); return json_response(self,{'approval':a,'tournament':t,'approvals':approvals})

    def api_result_submit(self):
        s=require_auth(self,['community'])
        if not s:return
        d=read_json(self); tid=str(d.get('tournamentId','')); mid=str(d.get('matchId','')); result=d.get('result') or {}
        with LOCK, db() as c:
            tours=state_get(c,'tournaments',[]); t=next((x for x in tours if str(x.get('id'))==tid),None)
            if not t:return json_response(self,{'error':'Tournament not found.'},404)
            m=next((x for x in t.get('matches',[]) if str(x.get('id'))==mid),None)
            if not m:return json_response(self,{'error':'Match not found.'},404)
            if str(s.get('id')) not in {str(m.get('player1')),str(m.get('player2'))}:return json_response(self,{'error':'Only a player in this match can submit the result.'},403)
            if m.get('winner') or m.get('submission'):return json_response(self,{'error':'This match already has a submitted or verified result.'},409)
            winner=str(result.get('winner',''))
            if winner not in {str(m.get('player1')),str(m.get('player2'))}:return json_response(self,{'error':'Winner must be one of the match participants.'},400)
            result['winner']=winner; result['submittedBy']=s.get('id'); result['status']='Awaiting Confirmation'; result['submittedAt']=now_iso()
            m['submission']=result; state_set(c,'tournaments',tours); c.commit()
        self.audit(s,'tournament_result_submit','match',mid,{'tournamentId':tid})
        return json_response(self,{'tournament':t})

    def api_result_confirm(self):
        s=require_auth(self,['community'])
        if not s:return
        d=read_json(self); tid=str(d.get('tournamentId','')); mid=str(d.get('matchId',''))
        with LOCK, db() as c:
            lock_state_workflow(c)
            tours=state_get(c,'tournaments',[]); t=next((x for x in tours if str(x.get('id'))==tid),None)
            if not t:return json_response(self,{'error':'Tournament not found.'},404)
            m=next((x for x in t.get('matches',[]) if str(x.get('id'))==mid),None)
            if not m or not m.get('submission'):return json_response(self,{'error':'Pending result not found.'},404)
            sub=m['submission']
            if str(s.get('id')) not in {str(m.get('player1')),str(m.get('player2'))}:return json_response(self,{'error':'Only match participants can confirm a result.'},403)
            if str(s.get('id'))==str(sub.get('submittedBy')):return json_response(self,{'error':'The submitting player cannot confirm their own result.'},403)
            if str(sub.get('status',''))!='Awaiting Confirmation':return json_response(self,{'error':'This result is no longer awaiting confirmation.'},409)
            winner=sub.get('winner'); m['winner']=winner; sub['status']='Confirmed'; m['verifiedAt']=now_iso()
            points=state_get(c,'seasonPoints',{}); loser=m.get('player2') if str(m.get('player1'))==str(winner) else m.get('player1')
            points[str(winner)]=points.get(str(winner),0)+100
            if loser is not None and str(loser)!='undefined': points[str(loser)]=points.get(str(loser),0)+50
            m['pointsAwarded']=True
            same=[x for x in t.get('matches',[]) if x.get('round')==m.get('round') and str(x.get('id'))!=mid]
            nxt=next((x for x in t.get('matches',[]) if x.get('round')==int(m.get('round',1))+1 and (not x.get('player1') or not x.get('player2'))),None)
            if nxt:
                if not nxt.get('player1'): nxt['player1']=winner
                elif not nxt.get('player2'): nxt['player2']=winner
            unfinished=any(not x.get('winner') and x.get('player1') and x.get('player2') for x in t.get('matches',[]))
            if not unfinished:
                finals=[x for x in t.get('matches',[]) if x.get('round')==max((z.get('round',1) for z in t.get('matches',[])),default=1) and x.get('winner')]
                if finals:
                    f=finals[-1]; t.update(completed=True,status='Completed',registrationOpen=False,champion=f.get('winner'),runnerUp=(f.get('player2') if str(f.get('winner'))==str(f.get('player1')) else f.get('player1')),completedAt=t.get('completedAt') or now_iso())
            state_set(c,'seasonPoints',points); state_set(c,'tournaments',tours); c.commit()
        self.audit(s,'tournament_result_confirm','tournament',tid,{'matchId':mid})
        return json_response(self,{'tournament':t})

    def api_result_dispute(self):
        s=require_auth(self,['community'])
        if not s:return
        d=read_json(self); tid=str(d.get('tournamentId','')); mid=str(d.get('matchId',''))
        with LOCK, db() as c:
            tours=state_get(c,'tournaments',[]); t=next((x for x in tours if str(x.get('id'))==tid),None)
            if not t:return json_response(self,{'error':'Tournament not found.'},404)
            m=next((x for x in t.get('matches',[]) if str(x.get('id'))==mid),None)
            if not m or not m.get('submission'):return json_response(self,{'error':'Pending result not found.'},404)
            participants={str(m.get('player1')),str(m.get('player2'))}
            if str(s.get('id')) not in participants:return json_response(self,{'error':'Only match participants can dispute a result.'},403)
            if str(m['submission'].get('status','')) not in ('Awaiting Confirmation','Disputed'):return json_response(self,{'error':'This result is no longer open for dispute.'},409)
            m['submission']['status']='Disputed'; m['submission']['disputedAt']=now_iso(); state_set(c,'tournaments',tours); c.commit()
        self.audit(s,'tournament_result_dispute','tournament',tid,{'matchId':mid})
        return json_response(self,{'tournament':t})

    def api_tournament_manager_change(self):
        s=self.dedicated_write('tournamentManagers')
        if not s:return
        if s.get('role') not in ('Overall Owner','Squad Owner'):return json_response(self,{'error':'Owner permission is required.'},403)
        d=read_json(self); action=str(d.get('action','')); mid=str(d.get('memberId',''))
        if action not in ('grant','revoke') or not mid:return json_response(self,{'error':'A valid action and member id are required.'},400)
        with LOCK, db() as c:
            row=c.execute('SELECT id,role FROM squad_members WHERE id=?',(mid,)).fetchone()
            if not row:return json_response(self,{'error':'Member not found.'},404)
            if row['role'] not in ('Squad Leader','Assistant Squad Leader'):return json_response(self,{'error':'Only Squad Leaders and Assistant Squad Leaders are eligible.'},400)
            managers=state_get(c,'tournamentManagers',[])
            if action=='grant' and not any(str(x)==mid or str((x or {}).get('id'))==mid for x in managers): managers.append(mid)
            if action=='revoke': managers=[x for x in managers if str(x)!=mid and str((x or {}).get('id'))!=mid]
            state_set(c,'tournamentManagers',managers); c.commit()
        self.audit(s,'tournament_manager_'+action,'squad_member',mid)
        return json_response(self,{'ok':True,'memberId':mid,'granted':action=='grant'})

    def api_result_review(self):
        s=self.dedicated_write('tournaments')
        if not s:return
        if not self.tournament_manager_allowed(s):return json_response(self,{'error':'Tournament Manager permission is required.'},403)
        d=read_json(self); tid=str(d.get('tournamentId','')); mid=str(d.get('matchId','')); action=str(d.get('action',''))
        with LOCK, db() as c:
            lock_state_workflow(c)
            tours=state_get(c,'tournaments',[]); t=next((x for x in tours if str(x.get('id'))==tid),None)
            if not t:return json_response(self,{'error':'Tournament not found.'},404)
            m=next((x for x in t.get('matches',[]) if str(x.get('id'))==mid),None)
            if not m or not m.get('submission'):return json_response(self,{'error':'Pending result not found.'},404)
            if action=='reject':m['submission']=None
            elif action=='approve':
                sub=m['submission']; m['winner']=sub.get('winner'); sub['status']='Owner Approved'; m['verifiedAt']=now_iso(); m['pointsAwarded']=True
                points=state_get(c,'seasonPoints',{}) or {}; winner=str(m.get('winner')); loser=str(m.get('player1')) if winner==str(m.get('player2')) else str(m.get('player2'))
                points[winner]=int(points.get(winner,0))+100
                if loser and loser!='None':points[loser]=int(points.get(loser,0))+50
                state_set(c,'seasonPoints',points)
                # Advance winner into the next available slot and complete final if applicable.
                nxt=next((x for x in t.get('matches',[]) if x.get('round')==(m.get('round',1)+1) and (not x.get('player1') or not x.get('player2'))),None)
                if nxt:
                    if not nxt.get('player1'):nxt['player1']=m['winner']
                    elif not nxt.get('player2'):nxt['player2']=m['winner']
                unfinished=any(not x.get('winner') and x.get('player1') and x.get('player2') for x in t.get('matches',[]))
                if not unfinished and t.get('matches'):
                    fr=max(int(x.get('round') or 1) for x in t['matches']); final=next((x for x in t['matches'] if int(x.get('round') or 1)==fr and x.get('winner')),None)
                    if final:
                        t.update(completed=True,status='Completed',registrationOpen=False,champion=final.get('winner'),runnerUp=(final.get('player2') if str(final.get('winner'))==str(final.get('player1')) else final.get('player1')),completedAt=t.get('completedAt') or now_iso())
                        hof=state_get(c,'hallOfFame',[]) or []
                        if not any(str(x.get('tournamentId'))==tid for x in hof):hof.append({'id':'H'+secrets.token_hex(6),'tournamentId':tid,'title':t.get('title'),'champion':t.get('champion'),'runnerUp':t.get('runnerUp'),'date':t.get('date'),'completedAt':t.get('completedAt')})
                        state_set(c,'hallOfFame',hof)
            else:return json_response(self,{'error':'Unsupported result action.'},400)
            state_set(c,'tournaments',tours); c.commit()
        self.audit(s,'tournament_result_'+action,'match',mid,{'tournamentId':tid}); return json_response(self,{'tournament':t})

    def api_event_participation(self):
        s=require_auth(self,['community'])
        if not s:return
        d=read_json(self); event_id=str(d.get('eventId',''))
        if not event_id:return json_response(self,{'error':'Event id is required.'},400)
        with LOCK, db() as c:
            lock_state_workflow(c)
            items=state_get(c,'eventParticipation',[]) or []; season=state_get(c,'currentSeason',None)
            if not isinstance(season,dict):return json_response(self,{'error':'Event participation rewards require an active season.'},409)
            if any(str(x.get('eventId'))==event_id and str(x.get('accountId'))==str(s['id']) and x.get('season')==season for x in items):return json_response(self,{'error':'Participation already recorded.'},409)
            items.append({'id':'EP'+secrets.token_hex(6),'eventId':event_id,'accountId':s['id'],'season':season,'time':now_iso()})
            points=state_get(c,'seasonPoints',{}) or {}; points[str(s['id'])]=int(points.get(str(s['id']),0))+50
            state_set(c,'eventParticipation',items); state_set(c,'seasonPoints',points); c.commit()
        self.audit(s,'event_participation','event',event_id); return json_response(self,{'ok':True,'eventParticipation':items,'seasonPoints':points})

    def api_registration(self, action):
        s=self.dedicated_write('registrations')
        if not s:return
        d=read_json(self); tid=str(d.get('tournamentId',''))
        with LOCK, db() as c:
            lock_state_workflow(c)
            tours=state_get(c,'tournaments',[]); regs=state_get(c,'registrations',[])
            t=next((x for x in tours if str(x.get('id'))==tid),None)
            if not t:return json_response(self,{'error':'Tournament not found.'},404)
            if action=='register':
                if s.get('type')!='community':return json_response(self,{'error':'Community authentication required.'},403)
                if t.get('registrationOpen') is False or str(t.get('status','')).lower()!='open':return json_response(self,{'error':'Registration is closed.'},409)
                if any(str(r.get('tournamentId'))==tid and str(r.get('accountId'))==str(s['id']) for r in regs):return json_response(self,{'error':'You are already registered.'},409)
                slots=int(t.get('slots') or 0)
                if slots and sum(1 for r in regs if str(r.get('tournamentId'))==tid)>=slots:return json_response(self,{'error':'Tournament is full.'},409)
                regs.append({'id':'R'+secrets.token_hex(6),'tournamentId':tid,'accountId':s['id'],'status':'Registered','time':now_iso()})
            elif action=='withdraw':
                before=len(regs); regs=[r for r in regs if not (str(r.get('tournamentId'))==tid and str(r.get('accountId'))==str(s['id']))]
                if len(regs)==before:return json_response(self,{'error':'Registration not found.'},404)
            elif action=='approve':
                if not self.tournament_manager_allowed(s):return json_response(self,{'error':'Tournament Manager permission is required.'},403)
                rid=str(d.get('registrationId','')); reg=next((r for r in regs if str(r.get('id'))==rid),None)
                if not reg:return json_response(self,{'error':'Registration not found.'},404)
                reg.update(status='Approved',approvedBy=s['id'],approvedAt=now_iso())
            state_set(c,'registrations',regs); c.commit(); return json_response(self,{'registrations':regs})

    def sync_state(self):
        s=auth_from_cookie(self)
        if not s:return json_response(self,{'error':'Authentication required'},401)
        d=read_json(self); squad=d.get('squad') or {}; community=d.get('community') or {}
        role=s.get('role','')
        with LOCK, db() as c:
            lock_state_workflow(c)
            def reject_sync(message, status):
                c.rollback()
                return json_response(self, {'error': message}, status)
            leadership=role in ('Squad Owner','Squad Leader','Assistant Squad Leader')
            owner=role in ('Squad Owner','Overall Owner')
            if leadership:
                for key in ['announcements','reports','complaints','events','reportConfig']:
                    if isinstance(squad.get(key), (list,dict)): state_set(c,key,squad[key])
                if isinstance(squad.get('notifications'),list): state_set(c,'squad_notifications',squad['notifications'])
            if owner:
                for key in ['tournaments','tournamentManagers','seasonPoints','seasonHistory','seasonHallOfFame','eventParticipation','currentSeason','hallOfFame','squadTournamentApprovals']:
                    if key in community: state_set(c,key,community[key])
                if isinstance(community.get('notifications'),list): state_set(c,'community_notifications',community['notifications'])
            elif role == 'Community Member':
                # Community members may only synchronize their own registration/notification state.
                account_id=str(s.get('id'))
                if isinstance(community.get('registrations'),list):
                    tournaments=state_get(c,'tournaments',[])
                    squad_tournament_ids={
                        str(tournament.get('id')) for tournament in tournaments
                        if isinstance(tournament,dict) and tournament.get('format')=='Squad vs Squad'
                    }
                    safe_regs=[
                        r for r in community['registrations']
                        if str(r.get('accountId'))==account_id
                        and str(r.get('tournamentId')) not in squad_tournament_ids
                    ]
                    existing=state_get(c,'registrations',[])
                    existing=[
                        r for r in existing
                        if str(r.get('accountId'))!=account_id
                        or str(r.get('tournamentId')) in squad_tournament_ids
                    ]
                    state_set(c,'registrations',existing+safe_regs)
                if isinstance(community.get('notifications'),list):
                    safe_notes=[n for n in community['notifications'] if not n.get('audienceId') or str(n.get('audienceId'))==account_id]
                    existing=state_get(c,'community_notifications',[])
                    existing=[n for n in existing if n.get('audienceId') and str(n.get('audienceId'))==account_id]
                    state_set(c,'community_notifications',safe_notes)
            # Member records are only synchronized by squad leadership. Passwords are never accepted here.
            if leadership:
                incoming_members=squad.get('members',[])
                if not isinstance(incoming_members,list):
                    return reject_sync('Squad members must be a list.',400)
                changes=[]
                for m in incoming_members:
                    if not isinstance(m,dict) or not m.get('id'):
                        return reject_sync('Each synchronized Squad member requires an object id.',400)
                    member_id=str(m['id'])
                    existing=c.execute('SELECT * FROM squad_members WHERE id=?',(member_id,)).fetchone()
                    if not existing or (role!='Squad Owner' and member_id!=str(s.get('id'))):
                        continue
                    profile_complete,error=json_bool(m,'profileComplete',existing['profile_complete'])
                    if error:return reject_sync(error,400)
                    account_activated,error=json_bool(m,'accountActivated',existing['account_activated'])
                    if error:return reject_sync(error,400)
                    status=str(m.get('status',existing['status'])).strip()
                    if status not in SQUAD_MEMBER_STATUSES:
                        return reject_sync('A valid Squad status is required.',400)
                    if existing['role']=='Squad Owner' and (status=='Disabled' or not account_activated):
                        return reject_sync('Appoint a replacement before changing the active Squad Owner.',409)
                    recovery_pending=int(existing['recovery_pending'] or 0)
                    if status=='Disabled' or 'accountActivated' in m:
                        recovery_pending=0
                    values=(str(m.get('name',existing['name'])).strip(),str(m.get('ign',existing['ign'])).strip(),str(m.get('gameId',existing['game_id'])).strip(),str(m.get('serverId',existing['server_id'])).strip(),str(m.get('lane',existing['lane'] or '')).strip(),str(m.get('email',existing['email'] or '')).strip(),str(m.get('phone',existing['phone'] or '')).strip(),str(m.get('birthday',existing['birthday'] or '')).strip(),status,m.get('lastLogin',existing['last_login']),1 if profile_complete else 0,1 if account_activated else 0,recovery_pending,member_id)
                    if not all(values[index] for index in (0,1,2,3)):
                        return reject_sync('Synchronized Squad identity fields cannot be empty.',400)
                    if identity_conflict(c,'squad_members',values[1],values[2],values[3],member_id):
                        return reject_sync('A Squad member already uses that IGN, Game ID, or Server ID.',409)
                    changes.append((existing,values))
                for existing,values in changes:
                    c.execute('UPDATE squad_members SET name=?,ign=?,game_id=?,server_id=?,lane=?,email=?,phone=?,birthday=?,status=?,last_login=?,profile_complete=?,account_activated=?,recovery_pending=? WHERE id=?',values)
                    if values[8]=='Disabled' or not values[11]:
                        revoke_user_sessions(c,'squad',values[13])
                        remove_tournament_manager_permission(c,values[13])
            if role=='Squad Owner':
                for member_id in (squad.get('__deletedMemberIds') or []):
                    row=c.execute('SELECT role FROM squad_members WHERE id=?',(str(member_id),)).fetchone()
                    if row and row['role']=='Squad Owner':
                        return reject_sync('Appoint a replacement before removing the active Squad Owner.',409)
                    if row:
                        revoke_user_sessions(c,'squad',member_id)
                        remove_tournament_manager_permission(c,member_id)
                        c.execute('DELETE FROM squad_members WHERE id=?',(str(member_id),))
            c.commit()
        self.audit(s,'legacy_state_sync','state','global',{'domains':list(squad.keys())+list(community.keys())})
        return json_response(self, {'ok':True,'authoritative':True})
    def static_or_404(self,path):
        rel=PUBLIC_STATIC_FILES.get(path)
        if not rel:
            return json_response(self,{'error':'Not found'},404)
        file=ROOT/rel
        if not file.exists() or not file.is_file(): return json_response(self,{'error':'Not found'},404)
        data=file.read_bytes(); ctype='text/plain'
        if file.suffix=='.html':ctype='text/html; charset=utf-8'
        elif file.suffix=='.css':ctype='text/css; charset=utf-8'
        elif file.suffix=='.js':ctype='application/javascript; charset=utf-8'
        elif file.suffix in ('.jpg','.jpeg'):ctype='image/jpeg'
        elif file.suffix=='.png':ctype='image/png'
        elif file.suffix=='.webp':ctype='image/webp'
        self.send_response(200);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

def main():
    if SESSION_SECRET == 'change-this-in-production' and os.getenv('DARK_SYSTEM_ALLOW_DEFAULT_SECRET','0') != '1':
        raise SystemExit('Set DARK_SYSTEM_SESSION_SECRET before running the server.')
    init_db(); print(f'Dark System backend running at http://{HOST}:{PORT}')
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
if __name__=='__main__': main()
