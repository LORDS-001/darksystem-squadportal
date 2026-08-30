#!/usr/bin/env python3
import base64, hashlib, hmac, json, logging, os, re, secrets, smtplib, sqlite3, threading, time
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
RATE_LIMITS = {}

PUBLIC_STATIC_FILES = {
    '/': 'index.html',
    '/index.html': 'index.html',
    '/owner-admin': 'owner-admin.html',
    '/owner-admin/': 'owner-admin.html',
    '/style.css': 'style.css',
    '/script.js': 'script.js',
    '/owner-admin.css': 'owner-admin.css',
    '/owner-admin.js': 'owner-admin.js',
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
          profile_complete INTEGER NOT NULL DEFAULT 1, account_activated INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS community_accounts (
          id TEXT PRIMARY KEY, squad_member_id TEXT, ign TEXT NOT NULL, game_id TEXT, server_id TEXT,
          email TEXT NOT NULL UNIQUE, phone TEXT, password_hash TEXT NOT NULL, role TEXT,
          lane TEXT, created_at TEXT, email_notifications INTEGER NOT NULL DEFAULT 1,
          reset_code TEXT, reset_expires INTEGER, linked_squad INTEGER NOT NULL DEFAULT 0
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
        ''')
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

def public_member(r, include_secret=False):
    d = dict(r)
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
    for k in ['password_hash','reset_code','reset_expires']:
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
    return {
        key: account[key]
        for key in ('id', 'squadMemberId', 'ign', 'gameId', 'serverId', 'email', 'phone', 'role', 'lane', 'createdAt', 'emailNotifications', 'linkedSquad')
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
        safe_workflow_state=lambda key, default: sanitize_workflow_value(state_get(c, key, default), secret_values, session_token_hashes)
        session_type=session.get('type')
        session_id=str(session.get('id'))
        registrations=safe_state('registrations', [])
        approvals=safe_workflow_state('squadTournamentApprovals', [])
        notifications=safe_state('community_notifications', [])
        event_participation=safe_state('eventParticipation', [])
        community_privileged=session_type == 'squad' or session.get('role') == 'Tournament Manager'
        if session_type == 'community' and not community_privileged:
            registrations=[item for item in registrations if isinstance(item, dict) and str(item.get('accountId')) == session_id]
            approvals=[item for item in approvals if isinstance(item, dict) and str(item.get('leaderAccountId')) == session_id]
            event_participation=[item for item in event_participation if isinstance(item, dict) and str(item.get('accountId')) == session_id]
        notifications=[
            item for item in notifications
            if isinstance(item, dict) and (not item.get('audienceId') or str(item.get('audienceId')) == session_id)
        ]
        community={
            'accounts':accounts,
            'tournaments':safe_workflow_state('tournaments', []),
            'registrations':registrations,
            'tournamentManagers':safe_state('tournamentManagers', []),
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
                'notifications':[],
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
                'SELECT role,status FROM squad_members WHERE id=?', (user_id,)
            ).fetchone()
            disabled = account and str(account['status'] or '').strip().lower() == 'disabled'
            current_role = (account['role'] or 'Squad Member') if account and not disabled else None
        elif user_type == 'community':
            account = connection.execute(
                'SELECT role FROM community_accounts WHERE id=?', (user_id,)
            ).fetchone()
            current_role = (account['role'] or 'Community Member') if account else None
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
    n = int(request_header(h, 'Content-Length', '0') or 0)
    raw = h.rfile.read(n) if n else b'{}'
    try: return json.loads(raw.decode() or '{}')
    except Exception: return {}

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

def sanitize_workflow_value(value, secret_values, session_token_hashes):
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if key in _WORKFLOW_ACCESS_CODE_KEYS and isinstance(item, str):
                cleaned[str(key)] = item
                continue
            if overview_secret_key(key):
                continue
            safe_item = sanitize_workflow_value(item, secret_values, session_token_hashes)
            if safe_item is not _OVERVIEW_OMIT:
                cleaned[str(key)] = safe_item
        return cleaned
    if isinstance(value, (list, tuple)):
        return [item for value_item in value if (item := sanitize_workflow_value(value_item, secret_values, session_token_hashes)) is not _OVERVIEW_OMIT]
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

def request_ip(h):
    return (request_header(h, 'X-Forwarded-For').split(',')[0].strip() or h.client_address[0])

def rate_limited(h, bucket):
    now=time.time(); key=(request_ip(h),bucket)
    with LOCK:
        hits=[t for t in RATE_LIMITS.get(key,[]) if now-t < RATE_LIMIT_WINDOW]
        hits.append(now); RATE_LIMITS[key]=hits
        return len(hits) > RATE_LIMIT_MAX

def durable_rate_limited(h, bucket):
    now = int(time.time())
    cutoff = now - RATE_LIMIT_WINDOW
    durable_key = hashlib.sha256(
        f'{request_ip(h)}\0{bucket}'.encode('utf-8')
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
    return int(row['attempts']) > RATE_LIMIT_MAX

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
    def do_DELETE(self): self.route('DELETE')
    def do_OPTIONS(self):
        self.send_response(204); self.send_header('Access-Control-Allow-Headers','Content-Type'); self.send_header('Access-Control-Allow-Methods','GET,POST,PUT,DELETE,OPTIONS'); self.send_header('Vary','Origin'); self.end_headers()
    def route(self, method):
        path=urlparse(self.path).path
        if method in ('POST','PUT','DELETE') and not valid_origin(self):
            return json_response(self, {'error':'Cross-origin request blocked.'}, 403)
        if path=='/api/owner/login' and method=='POST' and durable_rate_limited(self, path):
            return json_response(self, {'error':'Too many login attempts. Please wait a few minutes and try again.'}, 429)
        if path in ('/api/community/login','/api/squad/login') and method=='POST' and rate_limited(self, path):
            return json_response(self, {'error':'Too many login attempts. Please wait a few minutes and try again.'}, 429)
        if path=='/api/community/forgot' and method=='POST' and rate_limited(self, path):
            return json_response(self, {'error':'Too many password reset requests. Please wait a few minutes and try again.'}, 429)
        if path=='/api/health': return json_response(self, {'ok':True,'service':'Dark System backend','time':now_iso()})
        if path=='/api/bootstrap' and method=='GET': return json_response(self, bootstrap(auth_from_cookie(self)))
        if path=='/api/auth/me' and method=='GET': return json_response(self, {'authenticated':bool(auth_from_cookie(self)),'session':auth_from_cookie(self)})
        if path=='/api/owner/setup/status' and method=='GET': return self.owner_setup_status()
        if path=='/api/owner/setup' and method=='POST': return self.owner_setup()
        if path=='/api/owner/login' and method=='POST': return self.owner_login()
        if path=='/api/owner/overview' and method=='GET': return self.owner_overview()
        if path=='/api/owner/audit' and method=='GET': return self.owner_audit()
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
                    c.execute("UPDATE squad_members SET name=?,ign=?,game_id=?,server_id=?,access_code=?,role='Squad Owner',account_activated=1,profile_complete=1 WHERE id='1'",('Dark System Owner',str(squad['ign']).strip(),str(squad['gameId']).strip(),str(squad['serverId']).strip(),str(squad['accessCode']).strip().upper()))
                else:
                    c.execute("INSERT INTO squad_members(id,name,ign,game_id,server_id,role,access_code,status,profile_complete,account_activated) VALUES('1','Dark System Owner',?,?,?,?,?,'Offline',1,1)",(str(squad['ign']).strip(),str(squad['gameId']).strip(),str(squad['serverId']).strip(),'Squad Owner',str(squad['accessCode']).strip().upper()))
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
            rows=[]
            for row in c.execute('SELECT id,actor_type,actor_id,actor_role,action,target_type,target_id,created_at,details FROM audit_log ORDER BY created_at DESC, id DESC LIMIT 500').fetchall():
                item=sanitize_overview_value(dict(row), secret_values, session_token_hashes)
                item['details']=overview_details(item.get('details'), secret_values, session_token_hashes)
                rows.append(item)
        return json_response(self,{'audit':rows})

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
        allowed={'Squad Owner','Squad Leader','Assistant Squad Leader','Squad Member'}
        if not mid or role not in allowed:return json_response(self,{'error':'A valid member and squad role are required.'},400)
        if role=='Squad Owner' and s.get('role')!='Overall Owner':
            return json_response(self,{'error':'Only the Overall Owner can appoint another Squad Owner.'},403)
        with LOCK, db() as c:
            row=c.execute('SELECT * FROM squad_members WHERE id=?',(mid,)).fetchone()
            if not row:return json_response(self,{'error':'Member not found.'},404)
            if role=='Squad Owner':
                c.execute("UPDATE squad_members SET role='Squad Member' WHERE role='Squad Owner' AND id!=?",(mid,))
            c.execute('UPDATE squad_members SET role=? WHERE id=?',(role,mid)); c.commit(); row=c.execute('SELECT * FROM squad_members WHERE id=?',(mid,)).fetchone()
        self.audit(s,'role_change','squad_member',mid,{'role':role})
        return json_response(self,{'member':public_member(row,True)})

    def tournament_manager_allowed(self, session):
        if session.get('role') in ('Overall Owner','Squad Owner','Tournament Manager'): return True
        with LOCK, db() as c:
            managers=state_get(c,'tournamentManagers',[])
        sid=str(session.get('id'))
        return any(str(x)==sid or str((x or {}).get('id'))==sid or str((x or {}).get('accountId'))==sid for x in managers)

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
        if not row or not verify_password(password,row['password_hash']): return json_response(self, {'error':'The email or password is incorrect.'},401)
        token=create_session('community',row['id'],row['role'] or 'Community Member')
        return json_response(self, {'account':public_account(row)},200,{'Set-Cookie':session_cookie(self, token)})
    def community_forgot(self):
        d=read_json(self); email=str(d.get('email','')).strip().lower()
        with LOCK, db() as c: row=c.execute('SELECT * FROM community_accounts WHERE lower(email)=?',(email,)).fetchone()
        # Always return the same response to reduce account enumeration.
        if row:
            code=f'{secrets.randbelow(900000)+100000}'; exp=int(time.time())+600
            with LOCK, db() as c:
                c.execute('UPDATE community_accounts SET reset_code=?,reset_expires=? WHERE id=?',(code,exp,row['id'])); c.commit()
            try: smtp_send(email,'Your Dark System password reset code',f'Your Dark System password reset code is {code}. It expires in 10 minutes.')
            except Exception: pass
        return json_response(self, {'ok':True,'message':'If that account exists, a reset code has been sent.'})
    def community_reset(self):
        d=read_json(self); email=str(d.get('email','')).strip().lower(); code=str(d.get('code','')).strip(); password=str(d.get('password',''))
        with LOCK, db() as c: row=c.execute('SELECT * FROM community_accounts WHERE lower(email)=?',(email,)).fetchone()
        if not row or row['reset_code']!=code or not row['reset_expires'] or int(row['reset_expires'])<int(time.time()): return json_response(self, {'error':'The reset code is invalid or expired.'},400)
        if len(password)<8:return json_response(self, {'error':'Password must be at least 8 characters.'},400)
        with LOCK, db() as c:
            c.execute('UPDATE community_accounts SET password_hash=?,reset_code=NULL,reset_expires=NULL WHERE id=?',(hash_password(password),row['id']))
            c.execute('DELETE FROM sessions WHERE type=? AND user_id=?',('community',str(row['id'])))
            c.commit()
        return json_response(self, {'ok':True})
    def community_profile(self):
        s=require_auth(self,['community'])
        if not s:return
        d=read_json(self)
        with LOCK, db() as c:
            row=c.execute('SELECT * FROM community_accounts WHERE id=?',(s['id'],)).fetchone()
            if not row:return json_response(self,{'error':'Community account not found.'},404)
            email=str(d.get('email',row['email'])).strip().lower()
            if email!=row['email'].lower() and c.execute('SELECT 1 FROM community_accounts WHERE lower(email)=? AND id!=?',(email,s['id'])).fetchone():
                return json_response(self,{'error':'That email is already in use.'},409)
            c.execute("UPDATE community_accounts SET ign=?,game_id=?,server_id=?,phone=?,lane=?,email=?,email_notifications=? WHERE id=?", (str(d.get('ign',row['ign'])).strip(),str(d.get('gameId',row['game_id'])).strip(),str(d.get('serverId',row['server_id'])).strip(),str(d.get('phone',row['phone'])).strip(),str(d.get('lane',row['lane'])).strip(),email,1 if d.get('emailNotifications',bool(row['email_notifications'])) else 0,s['id']))
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
                if str(n.get('id'))==nid and (not n.get('accountId') or str(n.get('accountId'))==str(s['id'])):
                    n['read']=True; changed=True
            if changed: state_set(c,'community_notifications',notes); c.commit()
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
        with LOCK, db() as c: row=c.execute('SELECT * FROM squad_members WHERE lower(ign)=? AND game_id=? AND server_id=? AND upper(access_code)=? AND status!=?',(ign,gid,sid,code,'Disabled')).fetchone()
        if not row:return json_response(self, {'error':'The In-Game Name, IDs or access code were not recognized.'},401)
        stamp=now_iso()
        with LOCK, db() as c:
            c.execute('UPDATE squad_members SET status=?,last_login=? WHERE id=?',('Online',stamp,row['id'])); c.commit(); row=c.execute('SELECT * FROM squad_members WHERE id=?',(row['id'],)).fetchone()
        token=create_session('squad',row['id'],row['role'])
        return json_response(self, {'member':public_member(row,True)},200,{'Set-Cookie':session_cookie(self, token)})
    def squad_profile(self):
        s=require_auth(self,['squad']);
        if not s:return
        d=read_json(self)
        with LOCK, db() as c:
            row=c.execute('SELECT * FROM squad_members WHERE id=?',(s['id'],)).fetchone()
            if not row:return json_response(self,{'error':'Squad profile not found.'},404)
            if str(d.get('accessCode','')).upper()!=str(row['access_code']).upper():return json_response(self,{'error':'Access code verification failed.'},403)
            c.execute('UPDATE squad_members SET ign=?,game_id=?,server_id=?,lane=?,email=?,phone=?,birthday=?,profile_complete=1,account_activated=1 WHERE id=?',(d.get('ign',''),d.get('gameId',''),d.get('serverId',''),d.get('lane',''),d.get('email',''),d.get('phone',''),d.get('birthday',''),s['id'])); c.commit(); row=c.execute('SELECT * FROM squad_members WHERE id=?',(s['id'],)).fetchone()
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
        mid=str(int(time.time()*1000))
        with LOCK, db() as c:
            if c.execute('SELECT 1 FROM squad_members WHERE lower(ign)=?',(str(d['ign']).strip().lower(),)).fetchone():
                return json_response(self, {'error':'A squad member with that IGN already exists.'},409)
            c.execute("""INSERT INTO squad_members(id,name,ign,game_id,server_id,role,lane,email,phone,birthday,access_code,status,last_login,profile_complete,account_activated)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(mid,str(d['name']).strip(),str(d['ign']).strip(),str(d['gameId']).strip(),str(d['serverId']).strip(),str(d.get('role','Squad Member')),str(d.get('lane','')),str(d.get('email','')),str(d.get('phone','')),str(d.get('birthday','')),str(d['accessCode']).strip().upper(),'Offline',None,0,0))
            c.commit(); row=c.execute('SELECT * FROM squad_members WHERE id=?',(mid,)).fetchone()
        self.audit(s,'member_create','squad_member',mid,{'ign':row['ign']})
        return json_response(self, {'member':public_member(row,True)},201)

    def api_member_update(self):
        s=self.dedicated_write('members')
        if not s:return
        d=read_json(self); mid=str(d.get('id',''))
        if not mid:return json_response(self,{'error':'Member id is required.'},400)
        if self.role_allowed(s,'Squad Owner','Overall Owner'):
            owner=True
        elif self.role_allowed(s,'Squad Leader','Assistant Squad Leader'):
            owner=False
        else:
            return json_response(self,{'error':'Leadership permission required.'},403)
        with LOCK, db() as c:
            row=c.execute('SELECT * FROM squad_members WHERE id=?',(mid,)).fetchone()
            if not row:return json_response(self,{'error':'Member not found.'},404)
            vals={
              'name':d.get('name',row['name']),'ign':d.get('ign',row['ign']),'gameId':d.get('gameId',row['game_id']),'serverId':d.get('serverId',row['server_id']),
              'role':d.get('role',row['role']),'lane':d.get('lane',row['lane']),'email':d.get('email',row['email']),'phone':d.get('phone',row['phone']),
              'birthday':d.get('birthday',row['birthday']),'accessCode':d.get('accessCode',row['access_code']),'status':d.get('status',row['status']),
              'profileComplete':1 if d.get('profileComplete',bool(row['profile_complete'])) else 0,'accountActivated':1 if d.get('accountActivated',bool(row['account_activated'])) else 0}
            if not owner:
                vals['role']=row['role']; vals['accessCode']=row['access_code']; vals['profileComplete']=row['profile_complete']; vals['accountActivated']=row['account_activated']
            c.execute("""UPDATE squad_members SET name=?,ign=?,game_id=?,server_id=?,role=?,lane=?,email=?,phone=?,birthday=?,access_code=?,status=?,profile_complete=?,account_activated=? WHERE id=?""",(vals['name'],vals['ign'],vals['gameId'],vals['serverId'],vals['role'],vals['lane'],vals['email'],vals['phone'],vals['birthday'],vals['accessCode'],vals['status'],vals['profileComplete'],vals['accountActivated'],mid))
            if str(vals['accessCode']).upper() != str(row['access_code']).upper():
                c.execute('DELETE FROM sessions WHERE type=? AND user_id=?',('squad',mid))
            c.commit(); row=c.execute('SELECT * FROM squad_members WHERE id=?',(mid,)).fetchone()
        self.audit(s,'member_update','squad_member',mid)
        return json_response(self, {'member':public_member(row,True)})

    def api_member_delete(self):
        s=self.dedicated_write('members')
        if not s:return
        if not self.role_allowed(s,'Squad Owner','Overall Owner'):return json_response(self,{'error':'Owner permission is required to remove members.'},403)
        d=read_json(self); mid=str(d.get('id',''))
        if not mid or mid==str(s['id']):return json_response(self,{'error':'A valid member id other than the owner is required.'},400)
        with LOCK, db() as c:
            if not c.execute('SELECT 1 FROM squad_members WHERE id=?',(mid,)).fetchone():return json_response(self,{'error':'Member not found.'},404)
            c.execute('DELETE FROM squad_members WHERE id=?',(mid,)); c.commit()
        self.audit(s,'member_delete','squad_member',mid)
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
        if not self.tournament_manager_allowed(s): return json_response(self,{'error':'Tournament Manager permission is required.'},403)
        d=read_json(self); action=str(d.get('action','')); tid=str(d.get('tournamentId','')); aid=str(d.get('approvalId',''))
        with LOCK, db() as c:
            approvals=state_get(c,'squadTournamentApprovals',[]); tours=state_get(c,'tournaments',[])
            t=next((x for x in tours if str(x.get('id'))==tid),None)
            if not t:return json_response(self,{'error':'Tournament not found.'},404)
            if action=='submit_leader':
                if str(t.get('format'))!='Squad vs Squad':return json_response(self,{'error':'Invalid tournament type.'},400)
                squad=d.get('squad') or {}; leader=str(d.get('leaderAccountId') or s.get('id'))
                if not squad.get('squadName') or not squad.get('squadId'):return json_response(self,{'error':'Squad name and ID are required.'},400)
                if any(str(a.get('tournamentId'))==tid and a.get('status')=='Pending' and str(a.get('leaderAccountId'))==leader for a in approvals):return json_response(self,{'error':'Registration already pending.'},409)
                if any(str(a.get('tournamentId'))==tid and a.get('status')=='Approved' and str(a.get('squadId','')).lower()==str(squad['squadId']).lower() for a in approvals):return json_response(self,{'error':'Squad already registered.'},409)
                approved=sum(1 for a in approvals if str(a.get('tournamentId'))==tid and a.get('status')=='Approved')
                if int(t.get('squadSlots') or 0) and approved>=int(t.get('squadSlots')):return json_response(self,{'error':'Squad slots are full.'},409)
                a={'id':'STA'+secrets.token_hex(7),'tournamentId':tid,'tournamentTitle':t.get('title'),'squadName':str(squad['squadName']).strip(),'squadId':str(squad['squadId']).strip(),'leaderAccountId':leader,'leaderIgn':str(squad.get('leaderIgn','')),'leaderGameId':str(squad.get('leaderGameId','')),'leaderServerId':str(squad.get('leaderServerId','')),'role':'Squad Leader','status':'Pending','createdAt':now_iso(),'maxSquads':int(t.get('squadSlots') or 0),'membersPerSquad':int(t.get('membersPerSquad') or 7)}
                approvals.append(a); state_set(c,'squadTournamentApprovals',approvals); c.commit(); self.audit(s,'squad_tournament_submit','approval',a['id'],{'tournamentId':tid}); return json_response(self,{'approval':a,'approvals':approvals},201)
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
            items=state_get(c,'eventParticipation',[]) or []; season=state_get(c,'currentSeason',None)
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
                    safe_regs=[r for r in community['registrations'] if str(r.get('accountId'))==account_id]
                    existing=state_get(c,'registrations',[])
                    existing=[r for r in existing if str(r.get('accountId'))!=account_id]
                    state_set(c,'registrations',existing+safe_regs)
                if isinstance(community.get('notifications'),list):
                    safe_notes=[n for n in community['notifications'] if not n.get('audienceId') or str(n.get('audienceId'))==account_id]
                    existing=state_get(c,'community_notifications',[])
                    existing=[n for n in existing if n.get('audienceId') and str(n.get('audienceId'))==account_id]
                    state_set(c,'community_notifications',safe_notes)
            # Member records are only synchronized by squad leadership. Passwords are never accepted here.
            if leadership:
                for m in squad.get('members',[]):
                    if not isinstance(m,dict) or not m.get('id'): continue
                    existing=c.execute('SELECT access_code FROM squad_members WHERE id=?',(str(m['id']),)).fetchone()
                    if existing and (role=='Squad Owner' or str(m['id'])==str(s.get('id'))):
                        c.execute('UPDATE squad_members SET name=?,ign=?,game_id=?,server_id=?,lane=?,email=?,phone=?,birthday=?,status=?,last_login=?,profile_complete=?,account_activated=? WHERE id=?',(m.get('name',''),m.get('ign',''),m.get('gameId',''),m.get('serverId',''),m.get('lane',''),m.get('email',''),m.get('phone',''),m.get('birthday',''),m.get('status','Offline'),m.get('lastLogin'),1 if m.get('profileComplete') else 0,1 if m.get('accountActivated') else 0,str(m['id'])))
            if role=='Squad Owner':
                for member_id in (squad.get('__deletedMemberIds') or []):
                    if str(member_id)!=str(s.get('id')): c.execute('DELETE FROM squad_members WHERE id=?',(str(member_id),))
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
