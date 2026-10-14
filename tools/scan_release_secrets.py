"""Scan source and release evidence for actual development secrets, never values."""
import json,os,re,stat,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
private=ROOT/'backend/.release-kasera-private.json'
config=json.loads(private.read_text())
values=[config[k].encode() for k in ('jwt','encryption_key','api_key')]
secret=ROOT/'backend/.secretkaserapay';values.append(secret.read_bytes().strip())
paths=set(subprocess.check_output(['git','ls-files','-co','--exclude-standard','-z'],cwd=ROOT).decode().split('\0'))-{''}
leaks=[];pattern_hits=[]
pattern=re.compile(rb'(?:kp_(?:live|test)_[A-Za-z0-9_-]{25,}|biteship_(?:live|test)\.[A-Za-z0-9_.-]{40,})')
for name in sorted(paths):
 p=ROOT/name
 if not p.is_file():continue
 data=p.read_bytes()
 if any(v and v in data for v in values):leaks.append(name)
 if pattern.search(data):pattern_hits.append(name)
for p in (private,secret):
 assert stat.S_IMODE(p.stat().st_mode)==0o600
 assert subprocess.run(['git','check-ignore','-q',str(p)],cwd=ROOT).returncode==0
result={'actual_secret_leaks':leaks,'provider_token_pattern_hits':pattern_hits,'files_scanned':len(paths),'private_files_mode':'0600','private_files_ignored':True}
out=ROOT/'test_reports/release-blocker-kasera-20261009/secret-scan.json';out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));assert not leaks and not pattern_hits
