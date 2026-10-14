"""Stable isolated owner UAT runtime. Private config is never sourced from .env."""
import json
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PRIVATE=ROOT/'.uat-private'
RUNTIME=ROOT/'.uat-runtime'

def configure():
    config=json.loads((PRIVATE/'runtime.json').read_text())
    if config.get('ENVIRONMENT')!='development' or config.get('SELLERBOTTEL_UAT')!='true' or config.get('PLATFORM_DB_NAME')!='sellerbottel_uat_platform' or not config.get('MONGO_URL','').startswith('mongodb://127.0.0.1:27020/'):
        raise RuntimeError('Unsafe UAT runtime configuration')
    os.environ.clear();os.environ.update(config)
    sys.path.insert(0,str(ROOT/'backend'))
    return config

def frontend():
    from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
    directory=RUNTIME/'frontend'
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(directory),**kwargs)
        def do_GET(self):
            clean=self.path.split('?',1)[0]
            if not (directory/clean.lstrip('/')).is_file() and not clean.startswith('/static/'):
                self.path='/index.html'
            super().do_GET()
        def log_message(self,*args):pass
    ThreadingHTTPServer(('127.0.0.1',3010),Handler).serve_forever()

if __name__=='__main__':
    mode=sys.argv[1] if len(sys.argv)>1 else 'backend'
    if mode=='frontend':frontend()
    else:
        configure()
        if mode=='dispatcher':
            import bot_dispatcher
            sys.argv = [sys.argv[0]]
            bot_dispatcher.main()
        else:
            import uvicorn
            from server import app
            # Full application routes, without public interactive API documentation.
            app.router.routes[:]=[r for r in app.router.routes if getattr(r,'path','') not in {'/docs','/redoc','/openapi.json','/docs/oauth2-redirect'}]
            uvicorn.run(app,host='127.0.0.1',port=8010,access_log=False,proxy_headers=True,forwarded_allow_ips='127.0.0.1')
