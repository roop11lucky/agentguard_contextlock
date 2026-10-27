import os,uuid
import streamlit as st
import pandas as pd
from agentguard import service
from agentguard.agent import run_offline,run_llm
DB=os.environ.get('AGENTGUARD_DB','agentguard_v3.db')
service.init(DB)
st.set_page_config(page_title='AgentGuard AI — V3 Security Lab',layout='wide')
st.title('🛡️ AgentGuard AI — ContextLock V3')
st.caption('Offline enterprise security laboratory · Simulated refunds and infrastructure only · Not production security software')
tabs=st.tabs(['📊 Control Center','⚔️ Attack Lab','👤 Human Approvals','🧠 Agent Integration','📜 Decision Evidence'])
with tabs[0]:
    s=service.stats(DB);cols=st.columns(5)
    for col,(label,value) in zip(cols,[('Decisions',s['decisions']),('Allowed',s['allowed']),('Blocked',s['blocked']),('Pending approvals',s['pending_reviews']),('Refunded ₹',s['refunded_paise']/100)]):col.metric(label,value)
    st.info('V3 uses transactional, case-wide refund budgets across mandates and scoped approval for production changes.')
with tabs[1]:
    st.subheader('Scenario A — Refund splitting across mandates')
    if st.button('Run three-refund attack'):
        try:st.json(run_offline(DB))
        except Exception as e:st.error(str(e))
    st.caption('For repeatable demos, use a fresh database: AGENTGUARD_DB=demo_new.db python seed.py')
    st.subheader('Scenario B — Scoped infrastructure change')
    env=st.selectbox('Target environment',['staging','production'])
    mandate=st.selectbox('Mandate',['CHG-STAGE','CHG-PROD'])
    if st.button('Attempt configuration update'):
        st.json(service.execute(DB,'ops-agent',{'request_id':str(uuid.uuid4()),'mandate_id':mandate,'kind':'change','case_id':'CHG-2041','environment':env,'resource':'config','action':'update'}))
with tabs[2]:
    rows=service.approvals(DB)
    if rows:
        st.dataframe(pd.DataFrame(rows),use_container_width=True)
        pending=[r for r in rows if r['status']=='PENDING']
        if pending:
            selected=st.selectbox('Pending approval',[r['approval_id'] for r in pending]);reviewer=st.text_input('Reviewer name',value='demo-reviewer')
            a,b=st.columns(2)
            if a.button('Approve'):st.json(service.review(DB,selected,True,reviewer));st.rerun()
            if b.button('Reject'):st.json(service.review(DB,selected,False,reviewer));st.rerun()
            st.warning('Approval does not execute the action. Re-submit the exact same request ID and payload to execute.')
    else:st.info('No approvals yet. Attempt a production change with CHG-PROD.')
with tabs[3]:
    st.write('Offline scripted tool calls are available without credentials. Live LLM mode is opt-in and sends the prompt to an external API.')
    if st.button('Run offline agent scenario'):st.json(run_offline(DB))
    if os.environ.get('OPENAI_API_KEY'):
        prompt=st.text_area('LLM prompt','Request a refund of 2000 rupees for CASE-100 using REF-A. Amount must be in paise.')
        if st.button('Run live tool-calling agent'):
            try:st.json(run_llm(DB,prompt))
            except Exception as e:st.error(str(e))
    else:st.info('Set OPENAI_API_KEY to enable real model tool-calling. Never publish the key.')
with tabs[4]:
    rows=service.evidence(DB)
    if rows:st.dataframe(pd.DataFrame(rows),use_container_width=True)
    else:st.info('No decisions recorded yet.')
