"""AgentGuard V3: offline, transactional *simulated* action enforcement.
No real payments or infrastructure modifications are performed.
"""
import hashlib, hmac, json, secrets, sqlite3, uuid
from datetime import datetime, timezone

POLICY_VERSION='contextlock-v3.0'
def now(): return datetime.now(timezone.utc).isoformat()
def connect(db):
    c=sqlite3.connect(str(db),timeout=20,isolation_level=None)
    c.execute('PRAGMA busy_timeout=20000');c.execute('PRAGMA journal_mode=WAL');return c

def init(db):
    with connect(db) as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS agents(agent_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS cases(case_id TEXT PRIMARY KEY, budget_paise INTEGER NOT NULL CHECK(budget_paise>=0));
        CREATE TABLE IF NOT EXISTS mandates(mandate_id TEXT PRIMARY KEY,agent_id TEXT NOT NULL,kind TEXT NOT NULL,case_id TEXT NOT NULL,environment TEXT NOT NULL DEFAULT '',resource TEXT NOT NULL DEFAULT '',action TEXT NOT NULL DEFAULT '',max_paise INTEGER NOT NULL DEFAULT 0,expires_at TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS approvals(approval_id TEXT PRIMARY KEY,request_id TEXT NOT NULL UNIQUE,agent_id TEXT NOT NULL,mandate_id TEXT NOT NULL, fingerprint TEXT NOT NULL,status TEXT NOT NULL, expires_at TEXT NOT NULL,reviewer TEXT,decided_at TEXT);
        CREATE TABLE IF NOT EXISTS decisions(decision_id TEXT PRIMARY KEY,request_id TEXT NOT NULL UNIQUE,fingerprint TEXT NOT NULL,agent_id TEXT NOT NULL,mandate_id TEXT NOT NULL,kind TEXT NOT NULL,verdict TEXT NOT NULL,reason TEXT NOT NULL,policy_version TEXT NOT NULL,timestamp TEXT NOT NULL,payload_json TEXT NOT NULL,execution_status TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS refunds(request_id TEXT PRIMARY KEY,case_id TEXT NOT NULL,mandate_id TEXT NOT NULL,amount_paise INTEGER NOT NULL,timestamp TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS changes(request_id TEXT PRIMARY KEY,case_id TEXT NOT NULL,environment TEXT NOT NULL,resource TEXT NOT NULL,action TEXT NOT NULL,timestamp TEXT NOT NULL);
        ''')
def hash_token(token): return hashlib.sha256(token.encode()).hexdigest()
def register_agent(db,agent_id,token):
    if not agent_id or len(token)<16: raise ValueError('Agent ID and token >=16 characters required')
    with connect(db) as c: c.execute('INSERT OR REPLACE INTO agents(agent_id,token_hash) VALUES (?,?)',(agent_id,hash_token(token)))
def identify(db,token):
    if not token: return None
    with connect(db) as c: rows=c.execute('SELECT agent_id,token_hash FROM agents WHERE active=1').fetchall()
    for agent_id,digest in rows:
        if hmac.compare_digest(hash_token(token),digest): return agent_id
    return None
def set_case_budget(db,case_id,budget_paise):
    if not case_id or type(budget_paise)!=int or budget_paise<0: raise ValueError('Invalid case budget')
    with connect(db) as c:
        c.execute('BEGIN IMMEDIATE')
        spent=c.execute('SELECT COALESCE(SUM(amount_paise),0) FROM refunds WHERE case_id=?',(case_id,)).fetchone()[0]
        if budget_paise<spent: c.execute('ROLLBACK');raise ValueError('Budget cannot be below already executed total')
        c.execute('INSERT INTO cases VALUES (?,?) ON CONFLICT(case_id) DO UPDATE SET budget_paise=excluded.budget_paise',(case_id,budget_paise));c.execute('COMMIT')
def create_mandate(db,mandate_id,agent_id,kind,case_id,expires_at,max_paise=0,environment='',resource='',action=''):
    if kind not in ('refund','change') or type(max_paise)!=int or max_paise<0: raise ValueError('Invalid mandate')
    expiry=datetime.fromisoformat(expires_at.replace('Z','+00:00'))
    if expiry.tzinfo is None: raise ValueError('Expiry must have timezone')
    with connect(db) as c:c.execute('INSERT INTO mandates(mandate_id,agent_id,kind,case_id,environment,resource,action,max_paise,expires_at) VALUES (?,?,?,?,?,?,?,?,?)',(mandate_id,agent_id,kind,case_id,environment,resource,action,max_paise,expires_at))
def fingerprint(agent_id,payload):return hashlib.sha256(json.dumps({'agent_id':agent_id,**payload},sort_keys=True,separators=(',',':')).encode()).hexdigest()
def review(db,approval_id,approve,reviewer):
    if not reviewer.strip(): raise ValueError('Reviewer required')
    c=connect(db)
    try:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT status,expires_at FROM approvals WHERE approval_id=?',(approval_id,)).fetchone()
        if not row: raise ValueError('Approval not found')
        if row[0]!='PENDING': raise ValueError('Approval already reviewed')
        if datetime.fromisoformat(row[1])<=datetime.now(timezone.utc): raise ValueError('Approval expired')
        status='APPROVED' if approve else 'REJECTED'
        c.execute('UPDATE approvals SET status=?,reviewer=?,decided_at=? WHERE approval_id=?',(status,reviewer,now(),approval_id));c.execute('COMMIT')
        return {'approval_id':approval_id,'status':status}
    except:
        if c.in_transaction:c.execute('ROLLBACK')
        raise
    finally:c.close()
def execute(db,agent_id,payload):
    required={'request_id','mandate_id','kind','case_id'}
    if not required.issubset(payload) or any(not isinstance(payload[k],str) or not payload[k] for k in required):raise ValueError('Missing required action fields')
    if payload['kind']=='refund' and (type(payload.get('amount_paise'))!=int or payload['amount_paise']<=0):raise ValueError('Invalid refund amount')
    if payload['kind']=='change' and any(not isinstance(payload.get(k),str) or not payload[k] for k in ('environment','resource','action')):raise ValueError('Invalid change scope')
    if payload['kind'] not in ('refund','change'):raise ValueError('Invalid kind')
    req=payload['request_id'];fp=fingerprint(agent_id,payload);mid=payload['mandate_id'];kind=payload['kind']
    c=connect(db)
    try:
        c.execute('BEGIN IMMEDIATE')
        prior=c.execute('SELECT decision_id,fingerprint,verdict,reason,execution_status FROM decisions WHERE request_id=?',(req,)).fetchone()
        if prior:
            c.execute('COMMIT')
            if prior[1]!=fp:return {'decision_id':prior[0],'verdict':'DENY','reason':'REQUEST_ID_COLLISION','execution_status':'NOT_EXECUTED','replayed':True}
            return dict(decision_id=prior[0],verdict=prior[2],reason=prior[3],execution_status=prior[4],replayed=True)
        pending=c.execute('SELECT fingerprint FROM approvals WHERE request_id=?',(req,)).fetchone()
        if pending and pending[0]!=fp:
            c.execute('COMMIT')
            return {'decision_id':None,'verdict':'DENY','reason':'REQUEST_ID_COLLISION','execution_status':'NOT_EXECUTED','replayed':True}
        m=c.execute('SELECT agent_id,kind,case_id,environment,resource,action,max_paise,expires_at,active FROM mandates WHERE mandate_id=?',(mid,)).fetchone()
        reason=None
        if not m:reason='MANDATE_NOT_FOUND'
        elif not m[8] or datetime.fromisoformat(m[7].replace('Z','+00:00'))<=datetime.now(timezone.utc):reason='MANDATE_EXPIRED_OR_DISABLED'
        elif m[0]!=agent_id:reason='WRONG_AGENT'
        elif m[1]!=kind:reason='WRONG_ACTION_TYPE'
        elif m[2]!=payload['case_id']:reason='WRONG_CASE'
        elif kind=='refund':
            case=c.execute('SELECT budget_paise FROM cases WHERE case_id=?',(payload['case_id'],)).fetchone()
            if not case:reason='CASE_BUDGET_NOT_FOUND'
            else:
                case_total=c.execute('SELECT COALESCE(SUM(amount_paise),0) FROM refunds WHERE case_id=?',(payload['case_id'],)).fetchone()[0]
                mandate_total=c.execute('SELECT COALESCE(SUM(amount_paise),0) FROM refunds WHERE mandate_id=?',(mid,)).fetchone()[0]
                if case_total+payload['amount_paise']>case[0]:reason='CASE_BUDGET_EXCEEDED'
                elif mandate_total+payload['amount_paise']>m[6]:reason='MANDATE_LIMIT_EXCEEDED'
        elif (payload['environment'],payload['resource'],payload['action'])!=(m[3],m[4],m[5]):reason='APPROVAL_SCOPE_MISMATCH'
        if reason is None and kind=='change' and payload['environment']=='production':
            a=c.execute('SELECT approval_id,fingerprint,status,expires_at FROM approvals WHERE request_id=?',(req,)).fetchone()
            if not a:
                from datetime import timedelta
                approval_id=str(uuid.uuid4());expires=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat()
                c.execute('INSERT INTO approvals(approval_id,request_id,agent_id,mandate_id,fingerprint,status,expires_at) VALUES (?,?,?,?,?,?,?)',(approval_id,req,agent_id,mid,fp,'PENDING',expires))
                c.execute('COMMIT');return {'decision_id':None,'approval_id':approval_id,'verdict':'REVIEW','reason':'HUMAN_APPROVAL_REQUIRED','execution_status':'NOT_EXECUTED','replayed':False}
            if a[1]!=fp:reason='REQUEST_ID_COLLISION'
            elif a[2]=='REJECTED':reason='HUMAN_REJECTED'
            elif datetime.fromisoformat(a[3])<=datetime.now(timezone.utc):reason='APPROVAL_EXPIRED'
            elif a[2]!='APPROVED':
                c.execute('COMMIT');return {'decision_id':None,'approval_id':a[0],'verdict':'REVIEW','reason':'HUMAN_APPROVAL_PENDING','execution_status':'NOT_EXECUTED','replayed':True}
        verdict='DENY' if reason else 'ALLOW';reason=reason or 'AUTHORIZED_AND_SIMULATED'
        if verdict=='ALLOW':
            if kind=='refund':c.execute('INSERT INTO refunds VALUES (?,?,?,?,?)',(req,payload['case_id'],mid,payload['amount_paise'],now()))
            else:c.execute('INSERT INTO changes VALUES (?,?,?,?,?,?)',(req,payload['case_id'],payload['environment'],payload['resource'],payload['action'],now()))
        status='SIMULATED_SUCCESS' if verdict=='ALLOW' else 'NOT_EXECUTED';did=str(uuid.uuid4())
        c.execute('INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(did,req,fp,agent_id,mid,kind,verdict,reason,POLICY_VERSION,now(),json.dumps(payload,sort_keys=True),status))
        c.execute('COMMIT');return dict(decision_id=did,verdict=verdict,reason=reason,execution_status=status,replayed=False)
    except:
        if c.in_transaction:c.execute('ROLLBACK')
        raise
    finally:c.close()
def evidence(db):
    with connect(db) as c:
        c.row_factory=sqlite3.Row;return [dict(r) for r in c.execute('SELECT * FROM decisions ORDER BY timestamp DESC').fetchall()]
def approvals(db):
    with connect(db) as c:
        c.row_factory=sqlite3.Row;return [dict(r) for r in c.execute('SELECT * FROM approvals ORDER BY rowid DESC').fetchall()]
def stats(db):
    with connect(db) as c:
        return {'decisions':c.execute('SELECT COUNT(*) FROM decisions').fetchone()[0], 'allowed':c.execute("SELECT COUNT(*) FROM decisions WHERE verdict='ALLOW'").fetchone()[0], 'blocked':c.execute("SELECT COUNT(*) FROM decisions WHERE verdict='DENY'").fetchone()[0], 'pending_reviews':c.execute("SELECT COUNT(*) FROM approvals WHERE status='PENDING'").fetchone()[0], 'refunded_paise':c.execute('SELECT COALESCE(SUM(amount_paise),0) FROM refunds').fetchone()[0]}
