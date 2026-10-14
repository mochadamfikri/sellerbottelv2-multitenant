"""Android-size browser smoke; no password screenshots or traces."""
import asyncio,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
os.environ['PLAYWRIGHT_BROWSERS_PATH']='/home/ubuntu/.cache/ms-playwright'
from playwright.async_api import async_playwright
async def main():
 accounts=json.loads((ROOT/'.uat-private/credentials.json').read_text());results=[]
 target=ROOT/'test_reports/full-development-uat-20261009';target.mkdir(exist_ok=True)
 async with async_playwright() as pw:
  browser=await pw.chromium.launch(headless=True,args=['--no-sandbox','--host-resolver-rules=MAP fashion-demo.idsestock.my.id 16.78.106.9'])
  context=await browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,device_scale_factor=1)
  page=await context.new_page()
  errors=[];page.on('pageerror',lambda error:errors.append(type(error).__name__))
  for name,url in [('platform','https://idseconnect.my.id'),('fashion-store','https://fashion-demo.idseconnect.my.id'),('digital-store','https://digital-demo.idseconnect.my.id'),('tenant-login','https://digital-demo.idsestock.my.id')]:
   response=await page.goto(url,wait_until='networkidle');await page.screenshot(path=str(target/(name+'.png')),full_page=True)
   body=await page.locator('body').inner_text()
   results.append({'page':name,'https_status':response.status,'body_present':len(body)>20,'test_banner':'DEVELOPMENT / TEST' in body,'mobile_overflow':await page.evaluate('document.documentElement.scrollWidth > window.innerWidth'),'page_errors':list(errors)})
  await page.locator('input[type=email]').fill(accounts['tenant_b']['email']);await page.locator('input[type=password]').fill(accounts['tenant_b']['password']);await page.get_by_role('button',name='Masuk',exact=True).click();await page.wait_for_timeout(1200)
  await page.screenshot(path=str(target/'tenant-dashboard.png'),full_page=True)
  results.append({'page':'tenant-dashboard','login_success':'IDSE Digital Demo' in await page.locator('body').inner_text(),'page_errors':list(errors)})
  await page.goto('https://idseconnect.my.id/login',wait_until='networkidle')
  await page.get_by_test_id('admin-email-input').fill(accounts['platform_owner']['email'])
  await page.get_by_test_id('admin-password-input').fill(accounts['platform_owner']['password'])
  await page.get_by_test_id('admin-login-submit').click()
  await page.wait_for_timeout(1000)
  await page.goto('https://idseconnect.my.id/platform-control',wait_until='networkidle')
  await page.screenshot(path=str(target/'platform-control.png'),full_page=True)
  body=await page.locator('body').inner_text()
  results.append({'page':'platform-control','fee_control_visible':'Fee gateway IDSE' in body,'page_errors':list(errors)})
  (target/'android-browser.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results));await browser.close()
if __name__=='__main__':asyncio.run(main())
