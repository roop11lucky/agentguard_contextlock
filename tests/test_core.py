import concurrent.futures
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from agentguard.core import init_db, grant_mandate, authorize_refund, read_decisions

class ContextLockTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=str(Path(self.temp.name)/'test.db')
        init_db(self.db)
        self.exp=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
        grant_mandate('CASE','agent',1000000,self.exp,self.db)
    def tearDown(self): self.temp.cleanup()
    def run_action(self,amount,case='CASE',agent='agent',action=None):
        return authorize_refund(action or str(uuid.uuid4()),case,agent,amount,self.db)
    def test_split_attack(self):
        self.assertEqual([self.run_action(n)['verdict'] for n in [600000,300000,400000]],['ALLOW','ALLOW','DENY'])
    def test_unauthorized_agent(self):
        self.assertEqual(self.run_action(100,'CASE','attacker')['reason'],'AGENT_NOT_AUTHORIZED')
    def test_missing_mandate(self):
        self.assertEqual(self.run_action(100,'UNKNOWN')['reason'],'MANDATE_NOT_FOUND')
    def test_expired_mandate(self):
        grant_mandate('OLD','agent',1000,(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(),self.db)
        self.assertEqual(self.run_action(100,'OLD')['reason'],'MANDATE_INACTIVE_OR_EXPIRED')
    def test_boundary(self):
        self.assertEqual(self.run_action(1000000)['verdict'],'ALLOW')
        self.assertEqual(self.run_action(1)['verdict'],'DENY')
    def test_idempotency(self):
        a=str(uuid.uuid4())
        self.assertEqual(self.run_action(100,action=a)['verdict'],'ALLOW')
        self.assertTrue(self.run_action(100,action=a)['replayed'])
        self.assertEqual(self.run_action(200,action=a)['reason'],'ACTION_ID_REUSED_WITH_DIFFERENT_REQUEST')
        self.assertEqual(self.run_action(999901)['verdict'],'DENY')
    def test_concurrent_limit(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(self.run_action,[300000]*8))
        self.assertEqual(sum(x['verdict']=='ALLOW' for x in results),3)
    def test_evidence(self):
        self.run_action(100)
        self.assertEqual(len(read_decisions(self.db)),1)
    def test_invalid_amount(self):
        with self.assertRaises(ValueError): self.run_action(0)
        with self.assertRaises(ValueError): self.run_action(True)

if __name__=='__main__': unittest.main()
