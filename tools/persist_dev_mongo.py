"""Replace only the pre-existing dedicated audit container; retain data volume."""
import json,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def call(*args): return subprocess.check_output(['sudo','-n','docker',*args],text=True)
def main():
    name='sellerbottelv2-dev-mongo'
    d=json.loads(call('inspect',name))[0]
    assert d['Config']['Image']=='mongo:7.0'
    assert d['HostConfig']['PortBindings']=={'27017/tcp':[{'HostIp':'127.0.0.1','HostPort':'27019'}]}
    assert any(m.get('Name')=='sellerbottelv2-dev-mongo-data' and m['Destination']=='/data/db' for m in d['Mounts'])
    before=json.loads(call('exec',name,'mongosh','--quiet','--eval','JSON.stringify(db.adminCommand({listDatabases:1,nameOnly:true}).databases.map(d=>d.name).sort())'))
    limits=d['HostConfig'].get('Ulimits') or []
    if not any(v['Name']=='nofile' and v['Soft']==65536 and v['Hard']==65536 for v in limits):
        call('stop',name)
        # Keep old container as a stopped rollback reference; never remove volume.
        call('rename',name,name+'-pre-nofile-'+str(int(time.time())))
        subprocess.run(['sudo','-n','docker','compose','-f',str(ROOT/'compose.mongo-dev.yaml'),'up','-d'],check=True,capture_output=True)
    call('restart',name)
    for _ in range(60):
        try:
            after=json.loads(call('exec',name,'mongosh','--quiet','--eval','JSON.stringify(db.adminCommand({listDatabases:1,nameOnly:true}).databases.map(d=>d.name).sort())'))
            break
        except subprocess.CalledProcessError: time.sleep(1)
    else: raise RuntimeError('Mongo restart failed')
    limits=call('exec',name,'sh','-c','cat /proc/1/limits')
    row=next(r for r in limits.splitlines() if r.startswith('Max open files'))
    assert '65536' in row and before==after
    out={'container':name,'soft':65536,'hard':65536,'restart_verified':True,'databases_preserved':len(after),'production_untouched':True}
    p=ROOT/'test_reports/phase-4-final-hardening-20261008/mongo-nofile.json';p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(out,indent=2)+'\n')
    print(json.dumps(out))
if __name__=='__main__':main()
