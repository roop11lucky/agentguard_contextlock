import os,hmac
from fastapi import FastAPI,Header,HTTPException,Depends
from pydantic import BaseModel,Field
from typing import Literal
from . import service
DB=os.environ.get('AGENTGUARD_DB','agentguard_v3.db')
app=FastAPI(title='AgentGuard ContextLock Security Lab',version='3.0.0',description='SIMULATED systems only. Do not expose this demo to the public internet.')
class Action(BaseModel):
    request_id:str=Field(min_length=1);mandate_id:str=Field(min_length=1);kind:Literal['refund','change'];case_id:str=Field(min_length=1)
    amount_paise:int|None=None;environment:str|None=None;resource:str|None=None;action:str|None=None
class Mandate(BaseModel):
    mandate_id:str;agent_id:str;kind:Literal['refund','change'];case_id:str;expires_at:str;max_paise:int=0;environment:str='';resource:str='';action:str=''
class Budget(BaseModel):
    case_id:str;budget_paise:int=Field(ge=0)
class Review(BaseModel):
    approve:bool;reviewer:str=Field(min_length=1)
def admin(x_admin_token:str|None=Header(None)):
    expected=os.environ.get('AGENTGUARD_ADMIN_TOKEN','')
    if len(expected)<16 or not x_admin_token or not hmac.compare_digest(expected,x_admin_token):raise HTTPException(401,'Admin authorization required')
def agent(authorization:str|None=Header(None)):
    if not authorization or not authorization.startswith('Bearer '):raise HTTPException(401,'Bearer token required')
    who=service.identify(DB,authorization[7:])
    if not who:raise HTTPException(401,'Invalid token')
    return who
@app.on_event('startup')
def startup():service.init(DB)
@app.get('/health')
def health():return {'status':'ok','simulation_only':True,'version':service.POLICY_VERSION}
@app.post('/admin/budgets',dependencies=[Depends(admin)])
def budget(b:Budget):service.set_case_budget(DB,**b.model_dump());return {'updated':b.case_id}
@app.post('/admin/mandates',dependencies=[Depends(admin)])
def mandate(m:Mandate):service.create_mandate(DB,**m.model_dump());return {'created':m.mandate_id}
@app.get('/admin/evidence',dependencies=[Depends(admin)])
def evidence():return service.evidence(DB)
@app.get('/admin/stats',dependencies=[Depends(admin)])
def stats():return service.stats(DB)
@app.get('/admin/approvals',dependencies=[Depends(admin)])
def approvals():return service.approvals(DB)
@app.post('/admin/approvals/{approval_id}/review',dependencies=[Depends(admin)])
def review(approval_id:str,r:Review):
    try:return service.review(DB,approval_id,r.approve,r.reviewer)
    except ValueError as e:raise HTTPException(409,str(e))
@app.post('/gateway/execute')
def execute(a:Action,who:str=Depends(agent)):
    try:return service.execute(DB,who,a.model_dump(exclude_none=True))
    except ValueError as e:raise HTTPException(422,str(e))
