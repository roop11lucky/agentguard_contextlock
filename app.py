import uuid
from datetime import datetime, timedelta, timezone
import streamlit as st
from agentguard.core import init_db, grant_mandate, authorize_refund, read_decisions

st.set_page_config(page_title='AgentGuard AI | ContextLock', page_icon='🛡️', layout='wide')
init_db()
st.title('🛡️ AgentGuard AI — ContextLock')
st.caption('V1 research prototype • simulated refunds only • not production authorization')
st.info('A trusted gateway must intercept every protected tool call. This demo simulates the authorization decision and records allowed actions; it does not issue real refunds.')
with st.sidebar:
    st.header('Mandate')
    case_id = st.text_input('Business case', 'CASE-1001')
    agent_id = st.text_input('Agent identity', 'refund-agent-01')
    limit_rupees = st.number_input('Cumulative refund limit (₹)', min_value=0, value=10000, step=500)
    if st.button('Create / reset mandate', use_container_width=True):
        grant_mandate(case_id,agent_id,int(limit_rupees*100), (datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
        st.success('Mandate saved. Previous allowed refunds remain recorded.')
st.subheader('Live authorization simulator')
amount = st.number_input('Proposed refund amount (₹)', min_value=1, value=6000, step=500)
if st.button('Evaluate proposed refund', type='primary'):
    result=authorize_refund(str(uuid.uuid4()),case_id,agent_id,int(amount*100))
    if result['verdict']=='ALLOW': st.success(f"ALLOWED — {result['reason']}")
    else: st.error(f"BLOCKED — {result['reason']}")
    st.json(result)
st.subheader('One-click adversarial demonstration')
if st.button('Run refund splitting attack (₹6,000 + ₹3,000 + ₹4,000)'):
    demo_case='DEMO-'+uuid.uuid4().hex[:8]
    grant_mandate(demo_case,'refund-agent-01',1_000_000,(datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
    outcomes=[]
    for n in [600000,300000,400000]:
        result=authorize_refund(str(uuid.uuid4()),demo_case,'refund-agent-01',n)
        outcomes.append({'amount':f'₹{n/100:,.0f}','verdict':result['verdict'],'reason':result['reason']})
    st.table(outcomes)
st.subheader('Decision evidence')
rows=read_decisions()
if rows: st.dataframe(rows, use_container_width=True, hide_index=True)
else: st.caption('No decisions yet. Run a scenario to generate evidence.')
