"""Optional real OpenAI-compatible tool-calling integration; no API key needed for offline demo.
Agent suggestions are always routed through the trusted gateway service.
"""
import json,os,uuid
from urllib.request import Request,urlopen
from . import service
TOOL={'type':'function','function':{'name':'request_refund','description':'Request a simulated refund, subject to independent authorization.','parameters':{'type':'object','properties':{'mandate_id':{'type':'string'},'case_id':{'type':'string'},'amount_paise':{'type':'integer'}},'required':['mandate_id','case_id','amount_paise']}}}
def run_offline(db,agent_id='refund-agent'):
    results=[]
    for mandate,amount in [('REF-A',600000),('REF-B',300000),('REF-A',400000)]:
        p={'request_id':str(uuid.uuid4()),'mandate_id':mandate,'case_id':'CASE-100','kind':'refund','amount_paise':amount}
        results.append({'proposed_tool_call':p,'gateway_result':service.execute(db,agent_id,p)})
    return results
def run_llm(db,prompt,model='gpt-4o-mini',agent_id='refund-agent'):
    """One tool-call round trip. Requires OPENAI_API_KEY and explicit opt-in."""
    key=os.environ.get('OPENAI_API_KEY')
    if not key:raise ValueError('OPENAI_API_KEY required for live LLM mode')
    body={'model':model,'messages':[{'role':'system','content':'You are a demo refund assistant. Use request_refund to propose a refund. Never claim a refund happened unless the tool result says SIMULATED_SUCCESS. No real payments occur.'},{'role':'user','content':prompt}],'tools':[TOOL],'tool_choice':'auto'}
    req=Request('https://api.openai.com/v1/chat/completions',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    with urlopen(req,timeout=30) as resp:out=json.load(resp)
    calls=out['choices'][0]['message'].get('tool_calls',[])
    results=[]
    for call in calls:
        if call.get('function',{}).get('name')!='request_refund':continue
        args=json.loads(call['function']['arguments'])
        p={'request_id':str(uuid.uuid4()),'kind':'refund','mandate_id':args['mandate_id'],'case_id':args['case_id'],'amount_paise':args['amount_paise']}
        results.append({'proposed_tool_call':p,'gateway_result':service.execute(db,agent_id,p)})
    return {'assistant_message':out['choices'][0]['message'].get('content'),'tool_results':results}
