"""Targeted browser checks with synthetic APIs only; never touches production."""
import argparse
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote, parse_qs
from playwright.sync_api import sync_playwright, expect

parser=argparse.ArgumentParser()
parser.add_argument("--build", required=True)
parser.add_argument("--chrome", required=True)
args=parser.parse_args()
output=Path("/tmp/idse-upgrade-ui"); output.mkdir(exist_ok=True)
class SPA(SimpleHTTPRequestHandler):
    def do_GET(self):
        if not Path(self.translate_path(self.path)).is_file(): self.path="/index.html"
        try: super().do_GET()
        except (BrokenPipeError, ConnectionResetError): pass
    def log_message(self,*args): pass
server=ThreadingHTTPServer(("127.0.0.1",0),partial(SPA,directory=args.build))
threading.Thread(target=server.serve_forever,daemon=True).start()
base=f"http://127.0.0.1:{server.server_port}"
users=[{"_id":"web","wallet_target":"store:web","source":"web","first_name":"Web User","email":"web@example.test","balance_idr":200000},
       {"_id":"bot","wallet_target":"bot:bot","source":"telegram","first_name":"Bot User","telegram_id":123456789,"balance_idr":200000}]
history={"store:web":[],"bot:bot":[]}; campaigns=[]; errors=[]; requests=[]
def route(route):
    request=route.request; path=unquote(urlparse(request.url).path); data=[]
    if "/api/" not in path:
        return route.continue_() if request.url.startswith(base) else route.abort()
    if request.method != "GET": requests.append(path)
    if path=="/api/auth/me": data={"_id":"admin","email":"admin@example.test"}
    elif path=="/api/admin/user-directory":
        source=parse_qs(urlparse(request.url).query).get("source",["all"])[0]
        selected=[u for u in users if source=="all" or u["source"]==source]
        data={"items":selected,"total":len(selected),"page":1,"pages":1,"source_counts":{"all":2,"web":1,"telegram":1,"linked":0}}
    elif "/wallets/" in path:
        target=path.split("/wallets/")[1].split("/")[0]
        if path.endswith("/history"): data=history[target]
        else:
            body=request.post_data_json
            assert set(body)=={"direction","currency","amount","reason","request_id"}
            assert body["request_id"] and body["reason"]
            user=next(u for u in users if u["wallet_target"]==target)
            before=user["balance_idr"]; amount=body["amount"]*(1 if body["direction"]=="ADD" else -1)
            user["balance_idr"]+=amount
            entry={"_id":body["request_id"],"amount":amount,"currency":"IDR","balance_before":before,"balance_after":user["balance_idr"],"admin_id":"admin","reason":body["reason"],"created_at":"2026-09-28T18:00:00Z"}
            history[target].append(entry); data={"ok":True,"balance":user["balance_idr"],"adjustment":entry}
    elif path=="/api/admin/products": data=[{"_id":"p1","name":"Claude Pro 1 bulan","catalog_name":"Claude","product_kind":"digital","active":True,"stock":10}]
    elif path=="/api/admin/broadcasts/campaigns/options": data={"channels":["@offlinechannel"]}
    elif path=="/api/admin/broadcasts/campaigns":
        if request.method=="POST":
            body=request.post_data_json; assert body["minimum_interval"]==5 and body["maximum_interval"]==70
            data={**body,"_id":"c1","status":"active","sent":0,"remaining":30,"cursor":0,"next_scheduled_at":"2026-09-28T19:00:00Z","events":[{"_id":"e1","status":"pending"}]}
            campaigns.append(data)
        else: data=campaigns
    elif path.startswith("/api/admin/broadcasts/campaigns/c1"):
        if path.endswith("/allocations"): data=[]
        elif path.endswith("/action"):
            action=request.post_data_json["action"]
            campaigns[0]["status"]={"pause":"paused","resume":"active","stop":"stopped"}[action]; data=campaigns[0]
        else: data=campaigns[0]
    elif path.endswith("/daily-recap/config"): data={"enabled":False,"time":"00:05","target":"chats"}
    route.fulfill(status=200,content_type="application/json",body=json.dumps(data))

with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=args.chrome,headless=True,args=["--no-sandbox"])
    context=browser.new_context(viewport={"width":1440,"height":1000}); context.route("**/*",route)
    page=context.new_page(); page.on("pageerror",lambda e:errors.append(str(e)))
    page.goto(base+"/users")
    for source,name,direction,amount in [("Website saja","Web User","ADD","100000"),("Telegram saja","Bot User","SUBTRACT","50000")]:
        page.get_by_role("button",name=source,exact=False).click()
        row=page.get_by_role("row").filter(has=page.get_by_role("cell",name=name,exact=True))
        row.get_by_title("Sesuaikan saldo").click()
        modal=page.get_by_role("dialog")
        modal.get_by_label("Jenis",exact=True).select_option(direction)
        modal.get_by_label("Jumlah",exact=True).fill(amount)
        modal.get_by_label("Catatan",exact=True).fill("Offline admin correction")
        modal.get_by_role("button",name="Konfirmasi",exact=True).click()
        expect(modal.get_by_text("Manual Balance Adjustment",exact=False)).to_be_visible()
        expect(modal.get_by_text("Admin: admin",exact=False)).to_be_visible()
        page.screenshot(path=str(output/f"balance-{direction}.png"))
        modal.get_by_role("button",name="Tutup",exact=True).click()
    assert users[0]["balance_idr"]==300000 and users[1]["balance_idr"]==150000
    page.goto(base+"/broadcasts")
    page.get_by_text("Buat campaign",exact=True).click()
    page.get_by_label("Nama campaign",exact=True).fill("Offline Promo")
    page.get_by_role("button",name="Simpan & Aktifkan Campaign",exact=True).click()
    expect(page.get_by_role("heading",name="Offline Promo · Detail & alokasi")).to_be_visible()
    page.get_by_role("button",name="Pause",exact=True).click()
    expect(page.get_by_role("button",name="Resume",exact=True)).to_be_visible()
    page.reload()
    page.get_by_role("button",name="Offline Promo",exact=False).click()
    page.get_by_role("button",name="Resume",exact=True).click()
    expect(page.get_by_role("button",name="Pause",exact=True)).to_be_visible()
    page.on("dialog",lambda d:d.accept())
    page.get_by_role("button",name="Stop",exact=True).click()
    expect(page.get_by_text("STOPPED",exact=False)).to_be_visible()
    page.screenshot(path=str(output/"campaign.png"),full_page=True)
    assert not errors, errors
    report={"passed":["WEB add balance + history","BOT subtract balance + history","Server source filters","Campaign create with 5–70 minute range","Pause persists across refresh","Resume and Stop"],"browser_errors":errors,"mocked_mutations":requests}
    (output/"report.json").write_text(json.dumps(report,indent=2)); print(json.dumps(report,indent=2))
    browser.close()
server.shutdown()
