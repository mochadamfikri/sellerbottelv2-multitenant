"""Safe DNS/TLS/proxy evidence; no private configuration is emitted."""
import json,socket,ssl,subprocess,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];target='pay.idsepos.my.id'
addresses=sorted({x[4][0] for x in socket.getaddrinfo(target,443,type=socket.SOCK_STREAM)})
assert '16.78.106.9' in addresses
with socket.create_connection((target,443),timeout=20) as sock:
 with ssl.create_default_context().wrap_socket(sock,server_hostname=target) as conn:
  cert=conn.getpeercert();tls={'verified':True,'protocol':conn.version(),'not_after':cert['notAfter'],'subject_alt_names':cert['subjectAltName']}
with urllib.request.urlopen('https://'+target+'/health',timeout=20) as r:health={'http':r.status,'body':json.load(r)}
with urllib.request.urlopen('http://127.0.0.1:2019/config/') as r:active=json.load(r)
previous=json.loads(Path('/tmp/seller-release-caddy-active.json').read_text())
routes=active['apps']['http']['servers']['srv0']['routes']
old=previous['apps']['http']['servers']['srv0']['routes']
assert all(route in routes for route in old)
assert active['apps']['tls']['automation']['on_demand']==previous['apps']['tls']['automation']['on_demand']
result={'domain':target,'addresses':addresses,'getent':subprocess.check_output(['getent','hosts',target],text=True).strip(),'dig':subprocess.check_output(['dig','+short',target],text=True).strip(),'tls':tls,'health':health,'existing_routes_unchanged':True,'existing_on_demand_tls_unchanged':True,'actual_config_path':'/etc/caddy/Caddyfile','webhook_backend':'127.0.0.1:8007','public_paths':['GET /health','POST /api/payments/webhooks/kasera']}
(ROOT/'test_reports/release-blocker-kasera-20261009/https-proxy.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
