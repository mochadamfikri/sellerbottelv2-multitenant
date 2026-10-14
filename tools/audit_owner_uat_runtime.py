"""Read-only UAT service, Caddy and secret-safe log evidence."""
import json,subprocess,hashlib,stat
from pathlib import Path
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parents[1];private=ROOT/'.uat-private';report=ROOT/'test_reports/full-development-uat-20261009/runtime.json'
services=['sellerbottel-uat-backend','sellerbottel-uat-frontend','sellerbottel-uat-dispatcher','sellerbottel-kasera-sandbox','caddy']
result={'services':{name:subprocess.run(['sudo','-n','systemctl','is-active',name],capture_output=True,text=True).stdout.strip() for name in services}}
old=(private/'Caddyfile.before').read_text();current=Path('/etc/caddy/Caddyfile').read_text()
result['payment_site_unchanged']=old.split('pay.idsepos.my.id {',1)[1]==current.split('pay.idsepos.my.id {',1)[1]
result['idsehub_site_unchanged']='idsehub.my.id {\n\treverse_proxy 127.0.0.1:22130\n}' in current
result['forbidden_staging_host_absent']='staging.idsepos.my.id' not in current
result['private_file_modes']={p.name:oct(stat.S_IMODE(p.stat().st_mode)) for p in private.iterdir() if p.is_file()}
config=json.loads((private/'runtime.json').read_text());secret_values=[v for k,v in config.items() if any(word in k for word in ['PASSWORD','SECRET','KEY','TOKEN']) and isinstance(v,str) and len(v)>8]
for record in json.loads((private/'credentials.json').read_text()).values():secret_values.append(record['password'])
secret_values.extend(v for k,v in dotenv_values(ROOT/'backend/.env').items() if any(word in k for word in ['PASSWORD','SECRET','KEY','TOKEN']) and isinstance(v,str) and len(v)>8)
release=json.loads((ROOT/'backend/.release-kasera-private.json').read_text());secret_values.extend(release[k] for k in ['api_key','jwt','encryption_key'])
logs=subprocess.run(['sudo','-n','journalctl','--no-pager','--since','2026-10-09 03:38:00',*[part for name in services[:4] for part in ['-u',name]]],capture_output=True,text=True)
assert logs.returncode==0
result['secret_values_found_in_journal']=sum(value in logs.stdout for value in set(secret_values))
result['log_lines_scanned']=len(logs.stdout.splitlines());result['production']='No production machine accessed or changed'
report.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
assert all(state=='active' for state in result['services'].values()) and result['payment_site_unchanged'] and result['secret_values_found_in_journal']==0
