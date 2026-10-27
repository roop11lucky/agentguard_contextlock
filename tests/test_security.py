import concurrent.futures,uuid
from datetime import datetime,timedelta,timezone
import pytest
from agentguard import service as s
@pytest.fixture
def db(tmp_path):
    path=str(tmp_path/'test.db');s.init(path)
    s.register_agent(path,'a','a'*20);s.register_agent(path,'b','b'*20)
    s.set_case_budget(path,'C',1000)
    exp=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    for m,agent,kind,env in [('M1','a','refund',''),('M2','a','refund',''),('ST','a','change','staging'),('PR','a','change','production'),('OTHER','b','refund','')]:
        s.create_mandate(path,m,agent,kind,'C',exp,max_paise=1000,environment=env,resource='cfg',action='update')
    return path
def refund(db,amount,mandate='M1',request=None,agent='a'):
    return s.execute(db,agent,dict(request_id=request or str(uuid.uuid4()),mandate_id=mandate,kind='refund',case_id='C',amount_paise=amount))
def change(db,env='staging',mandate='ST',request=None):
    return s.execute(db,'a',dict(request_id=request or str(uuid.uuid4()),mandate_id=mandate,kind='change',case_id='C',environment=env,resource='cfg',action='update'))
def test_refund_allowed(db):assert refund(db,600)['verdict']=='ALLOW'
def test_case_limit_across_mandates(db):
    assert refund(db,600)['verdict']=='ALLOW';assert refund(db,300,'M2')['verdict']=='ALLOW'
    assert refund(db,200,'M1')['reason']=='CASE_BUDGET_EXCEEDED'
def test_limit_boundary(db):assert refund(db,1000)['verdict']=='ALLOW'
def test_invalid_amount(db):
    with pytest.raises(ValueError):refund(db,-1)
def test_bool_invalid(db):
    with pytest.raises(ValueError):refund(db,True)
def test_wrong_agent(db):assert refund(db,10,agent='b')['reason']=='WRONG_AGENT'
def test_wrong_case(db):
    p=dict(request_id=str(uuid.uuid4()),mandate_id='M1',kind='refund',case_id='OTHER',amount_paise=10)
    assert s.execute(db,'a',p)['reason']=='WRONG_CASE'
def test_wrong_environment(db):assert change(db,'production')['reason']=='APPROVAL_SCOPE_MISMATCH'
def test_staging(db):assert change(db)['verdict']=='ALLOW'
def test_production_review(db):assert change(db,'production','PR')['verdict']=='REVIEW'
def test_approve_then_retry(db):
    req=str(uuid.uuid4());r=change(db,'production','PR',req)
    assert r['verdict']=='REVIEW'
    assert s.review(db,r['approval_id'],True,'reviewer')['status']=='APPROVED'
    assert change(db,'production','PR',req)['verdict']=='ALLOW'
    assert change(db,'production','PR',req)['replayed']
def test_reject(db):
    req=str(uuid.uuid4());r=change(db,'production','PR',req)
    s.review(db,r['approval_id'],False,'reviewer')
    assert change(db,'production','PR',req)['reason']=='HUMAN_REJECTED'
def test_double_review(db):
    r=change(db,'production','PR');s.review(db,r['approval_id'],True,'reviewer')
    with pytest.raises(ValueError):s.review(db,r['approval_id'],False,'reviewer')
def test_idempotent(db):
    req=str(uuid.uuid4());a=refund(db,500,request=req);b=refund(db,500,request=req)
    assert a['decision_id']==b['decision_id'] and b['replayed'] and s.stats(db)['refunded_paise']==500
def test_collision(db):
    req=str(uuid.uuid4());refund(db,500,request=req)
    assert refund(db,600,request=req)['reason']=='REQUEST_ID_COLLISION'
def test_concurrency(db):
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:results=list(ex.map(lambda _:refund(db,300,mandate='M2'),range(8)))
    assert sum(r['verdict']=='ALLOW' for r in results)==3
    assert s.stats(db)['refunded_paise']==900
def test_cannot_lower_budget_below_spend(db):
    refund(db,700)
    with pytest.raises(ValueError):s.set_case_budget(db,'C',600)
def test_authentication(db):
    assert s.identify(db,'a'*20)=='a';assert s.identify(db,'bad') is None
def test_evidence(db):
    refund(db,100);assert len(s.evidence(db))==1
def test_approval_replay_payload_collision(db):
    req=str(uuid.uuid4());r=change(db,'production','PR',req)
    p=dict(request_id=req,mandate_id='PR',kind='change',case_id='C',environment='production',resource='different',action='update')
    assert s.execute(db,'a',p)['verdict']=='DENY'
    assert change(db,'production','PR',req)['verdict']=='REVIEW'
