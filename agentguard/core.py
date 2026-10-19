"""ContextLock reference POC. No real financial transactions are performed."""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = 'agentguard.db'

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def connect(db=DEFAULT_DB):
    c = sqlite3.connect(str(db), timeout=20, isolation_level=None)
    c.execute('PRAGMA busy_timeout=20000')
    c.execute('PRAGMA journal_mode=WAL')
    return c

def init_db(db=DEFAULT_DB):
    with connect(db) as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS mandates (
          case_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL,
          limit_paise INTEGER NOT NULL CHECK(limit_paise >= 0),
          expires_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS refunds (
          action_id TEXT PRIMARY KEY, case_id TEXT NOT NULL,
          agent_id TEXT NOT NULL, amount_paise INTEGER NOT NULL,
          created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS decisions (
          decision_id TEXT PRIMARY KEY, action_id TEXT NOT NULL UNIQUE,
          case_id TEXT, agent_id TEXT, amount_paise INTEGER,
          verdict TEXT NOT NULL, reason TEXT NOT NULL,
          policy_version TEXT NOT NULL, timestamp TEXT NOT NULL,
          request_fingerprint TEXT NOT NULL);
        ''')

def grant_mandate(case_id, agent_id, limit_paise, expires_at, db=DEFAULT_DB):
    if not isinstance(limit_paise, int) or isinstance(limit_paise, bool) or limit_paise < 0:
        raise ValueError('limit_paise must be a nonnegative integer')
    with connect(db) as c:
        c.execute('INSERT INTO mandates(case_id,agent_id,limit_paise,expires_at) VALUES(?,?,?,?) ON CONFLICT(case_id) DO UPDATE SET agent_id=excluded.agent_id,limit_paise=excluded.limit_paise,expires_at=excluded.expires_at,active=1', (case_id, agent_id, limit_paise, expires_at))

def authorize_refund(action_id, case_id, agent_id, amount_paise, db=DEFAULT_DB):
    """Atomically evaluate and record a simulated refund, including idempotency."""
    if not isinstance(amount_paise, int) or isinstance(amount_paise, bool) or amount_paise <= 0:
        raise ValueError('amount_paise must be a positive integer')
    if not all(isinstance(v, str) and v.strip() for v in (action_id, case_id, agent_id)):
        raise ValueError('action_id, case_id and agent_id must be nonempty strings')
    fingerprint = json.dumps([case_id,agent_id,amount_paise], separators=(',',':'))
    c = connect(db)
    try:
        c.execute('BEGIN IMMEDIATE')
        prior = c.execute('SELECT decision_id,verdict,reason,request_fingerprint FROM decisions WHERE action_id=?', (action_id,)).fetchone()
        if prior:
            c.execute('COMMIT')
            if prior[3] != fingerprint:
                return {'decision_id':prior[0],'verdict':'DENY','reason':'ACTION_ID_REUSED_WITH_DIFFERENT_REQUEST','replayed':True}
            return {'decision_id':prior[0],'verdict':prior[1],'reason':prior[2],'replayed':True}
        mandate = c.execute('SELECT agent_id,limit_paise,expires_at,active FROM mandates WHERE case_id=?', (case_id,)).fetchone()
        total = c.execute('SELECT COALESCE(SUM(amount_paise),0) FROM refunds WHERE case_id=?',(case_id,)).fetchone()[0]
        if not mandate:
            verdict, reason = 'DENY','MANDATE_NOT_FOUND'
        elif not mandate[3] or mandate[2] <= utcnow():
            verdict, reason = 'DENY','MANDATE_INACTIVE_OR_EXPIRED'
        elif mandate[0] != agent_id:
            verdict, reason = 'DENY','AGENT_NOT_AUTHORIZED'
        elif total + amount_paise > mandate[1]:
            verdict, reason = 'DENY','CUMULATIVE_LIMIT_EXCEEDED'
        else:
            verdict, reason = 'ALLOW','WITHIN_MANDATE'
            c.execute('INSERT INTO refunds VALUES(?,?,?,?,?)',(action_id,case_id,agent_id,amount_paise,utcnow()))
        decision_id = str(uuid.uuid4())
        c.execute('INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?,?)', (decision_id,action_id,case_id,agent_id,amount_paise,verdict,reason,'contextlock-v1',utcnow(),fingerprint))
        c.execute('COMMIT')
        return {'decision_id':decision_id,'verdict':verdict,'reason':reason,'replayed':False,'previous_total_paise':total,'proposed_total_paise':total+amount_paise}
    except Exception:
        if c.in_transaction: c.execute('ROLLBACK')
        raise
    finally:
        c.close()

def read_decisions(db=DEFAULT_DB):
    with connect(db) as c:
        return [dict(zip(['decision_id','action_id','case_id','agent_id','amount_paise','verdict','reason','policy_version','timestamp'],row)) for row in c.execute('SELECT decision_id,action_id,case_id,agent_id,amount_paise,verdict,reason,policy_version,timestamp FROM decisions ORDER BY timestamp DESC').fetchall()]
