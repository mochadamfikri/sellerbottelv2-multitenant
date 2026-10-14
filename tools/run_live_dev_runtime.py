"""Serve the disposable E2E backend and frontend using ignored private config.

Only localhost:8002/3002 and the dedicated Mongo on localhost:27019 are allowed.
Ctrl-C stops only the processes started here. Existing .env is never loaded.
"""
import http.client
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
config=dotenv_values(ROOT/"backend/.env.live-e2e")
if config.get("ENVIRONMENT")!="development" or not config.get("MONGO_URL", "").startswith("mongodb://127.0.0.1:27019/") or config.get("DB_NAME")!="sellerbottel_live_e2e_dev":
    raise SystemExit("Dedicated E2E configuration is missing or unsafe; run live_dev_e2e.py first")
config["PYTHON_DOTENV_DISABLED"]="1"
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(ROOT/"frontend/build"),**kwargs)
    def log_message(self,*args):
        pass
    def forward(self):
        connection=http.client.HTTPConnection("127.0.0.1",8002,timeout=30)
        body=self.rfile.read(int(self.headers.get("Content-Length","0")))
        connection.request(self.command,self.path,body=body,headers={k:v for k,v in self.headers.items() if k.lower() not in {"host","connection"}})
        response=connection.getresponse(); content=response.read()
        self.send_response(response.status)
        for k,v in response.getheaders():
            if k.lower() not in {"transfer-encoding","connection","content-length"}:
                self.send_header(k,v)
        self.send_header("Content-Length",str(len(content))); self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError,ConnectionResetError):
            pass
        finally:
            connection.close()
    def do_GET(self):
        if self.path.startswith("/api/"):
            return self.forward()
        if not self.path.startswith("/static/") and not (ROOT/"frontend/build"/self.path.split("?")[0].lstrip("/")).is_file():
            self.path="/index.html"
        super().do_GET()
    do_POST=forward
    do_PUT=forward
    do_PATCH=forward
    do_DELETE=forward

if __name__=="__main__":
    if "--check" in sys.argv:
        print("Dedicated runtime configuration: valid; secrets withheld")
        raise SystemExit(0)
    backend=subprocess.Popen([sys.executable,"-m","uvicorn","server:app","--host","127.0.0.1","--port","8002"],cwd=ROOT/"backend",env=config)
    server=ThreadingHTTPServer(("127.0.0.1",3002),Handler)
    try:
        print("Development frontend: http://127.0.0.1:3002; backend: localhost:8002",flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close(); backend.terminate()
        try:
            backend.wait(timeout=15)
        except subprocess.TimeoutExpired:
            backend.kill(); backend.wait()
