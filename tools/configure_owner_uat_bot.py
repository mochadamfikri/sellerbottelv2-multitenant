"""Move the approved development bot to Digital Demo after old poller is stopped."""
import asyncio,json
from uat_runtime import configure,ROOT,PRIVATE
config=configure()
from dotenv import dotenv_values
import httpx
from cryptography.fernet import Fernet
from db import client,platform_db
async def main():
 token=dotenv_values(ROOT/'backend/.env').get('TELEGRAM_TOKEN','')
 async with httpx.AsyncClient(timeout=20) as http:
  me=(await http.get('https://api.telegram.org/bot'+token+'/getMe')).json()
  hook=(await http.get('https://api.telegram.org/bot'+token+'/getWebhookInfo')).json()
  assert me.get('ok') and hook.get('ok') and not hook.get('result',{}).get('url')
 bot={'token_encrypted':Fernet(config['INVENTORY_ENCRYPTION_KEY'].encode()).encrypt(token.encode()).decode(),'brand_name':'IDSE Digital Demo','reseller_enabled':False,'admin_ids':[],'bot_username':me['result']['username']}
 result=await platform_db().tenants.update_one({'slug':'digital-demo','status':'active'},{'$set':{'metadata.bot_config':bot}})
 assert result.matched_count==1
 report={'tenant':'digital-demo','username':me['result']['username'],'webhook_changed':False,'second_bot':'NOT RUN — disabled by owner'}
 (ROOT/'test_reports/full-development-uat-20261009/bot.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));client.close()
if __name__=='__main__':
 try:asyncio.run(main())
 except Exception as e:print(json.dumps({'error_type':type(e).__name__}));raise SystemExit(1)
