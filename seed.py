import os,secrets
from datetime import datetime,timedelta,timezone
from agentguard import service
DB=os.environ.get('AGENTGUARD_DB','agentguard_v3.db')
service.init(DB)
token=secrets.token_urlsafe(32)
service.register_agent(DB,'refund-agent',token)
service.register_agent(DB,'ops-agent',token)
service.set_case_budget(DB,'CASE-100',1000000)
expiry=(datetime.now(timezone.utc)+timedelta(days=7)).isoformat()
for m in [('REF-A','refund-agent','refund','CASE-100',1000000,'','',''),('REF-B','refund-agent','refund','CASE-100',1000000,'','',''),('CHG-STAGE','ops-agent','change','CHG-2041',0,'staging','config','update'),('CHG-PROD','ops-agent','change','CHG-2041',0,'production','config','update')]:
    try:service.create_mandate(DB,m[0],m[1],m[2],m[3],expiry,max_paise=m[4],environment=m[5],resource=m[6],action=m[7])
    except Exception as e:
        if 'UNIQUE constraint' not in str(e):raise
print('Demo seeded. Agent token (save locally; do not commit):',token)
