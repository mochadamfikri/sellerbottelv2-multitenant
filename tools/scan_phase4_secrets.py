"""Secret-safe source/evidence scan. Findings contain paths/rule names, never values."""
import json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'test_reports/phase-4-final-hardening-20261008'
keys=Path('/tmp/seller-phase4-sandbox-keys.json')
known=list(json.loads(keys.read_text()).values()) if keys.exists() else []
rules={'gateway_key':re.compile(rb'kp_(?:live|test)_[A-Za-z0-9_-]{24,}'),'biteship_token':re.compile(rb'biteship_(?:live|test)\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+'),'private_key':re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')}
files=set(subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0'))
findings=[];scanned=0
for name in sorted(files):
 p=ROOT/name
 if not name or not p.is_file(): continue
 if p.suffix.lower() in {'.png','.jpg','.jpeg','.webp','.gif','.ico','.woff','.woff2','.ttf','.pdf'}: continue
 if p.stat().st_size>20*1024*1024: continue
 data=p.read_bytes();scanned+=1
 for label,pattern in rules.items():
  if pattern.search(data): findings.append({'path':name,'rule':label})
 if any(value.encode() in data for value in known): findings.append({'path':name,'rule':'supplied_sandbox_secret'})
result={'files_scanned':scanned,'findings':findings,'supplied_test_keys_checked':len(known),'result':'PASS' if not findings else 'FAIL','scope':'tracked and nonignored source/evidence; binary screenshots excluded; runtime separately checked against generated secrets by harness'}
EVIDENCE.mkdir(parents=True,exist_ok=True);(EVIDENCE/'secret-scan.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));raise SystemExit(bool(findings))
