#!/usr/bin/env python3
"""Rehearsal-only CLI; immutable local BSON input, no production apply mode."""
import argparse
import fcntl
import json
import os
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from legacy_migration.safety import PRIVATE, MigrationError, require, guard_environment, block_network, private_file
from legacy_migration.snapshot import Snapshot
from legacy_migration.codec import safe_json
from legacy_migration import engine


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['inventory','plan','validate-plan','apply-rehearsal','verify','resume','rollback-rehearsal'])
    parser.add_argument('--snapshot',required=True)
    parser.add_argument('--plan')
    parser.add_argument('--output')
    parser.add_argument('--keys')
    parser.add_argument('--instance-file')
    parser.add_argument('--crash-after',type=int)
    args=parser.parse_args()
    guard_environment();block_network()
    snap=Snapshot(args.snapshot)
    if args.command=='inventory': result=snap.inventory()
    elif args.command=='plan': result=engine.plan(snap)
    else:
        require(args.plan is not None,'PLAN_FILE_REQUIRED')
        p=json.loads(private_file(args.plan).read_text());engine.validate(snap,p)
        if args.command=='validate-plan':result={'status':'PASS','plan_hash':p['plan_hash']}
        else:
            from legacy_migration.target import MongoTarget
            from legacy_migration.crypto import OfflineKeys
            require(args.instance_file is not None,'INSTANCE_FILE_REQUIRED')
            instance=json.loads(private_file(args.instance_file).read_text())['instance_id']
            PRIVATE.mkdir(mode=0o700,parents=True,exist_ok=True)
            with (PRIVATE/'writer.lock').open('w') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                target=MongoTarget(snap.owner,instance)
                if args.command=='rollback-rehearsal':result=engine.rollback(snap,p,target)
                else:
                    require(args.keys is not None,'OFFLINE_KEYS_REQUIRED')
                    keys=OfflineKeys(args.keys)
                    if args.command=='verify':result=engine.verify(snap,p,target,keys)
                    else:result=engine.apply(snap,p,target,keys,crash_after=args.crash_after)
    if args.output:
        output=Path(args.output).resolve()
        require(output.is_relative_to(PRIVATE),'PRIVATE_OUTPUT_DIRECTORY_REQUIRED')
        require(not output.is_relative_to(snap.root),'OUTPUT_CANNOT_MODIFY_SOURCE')
        protected=[Path(x).resolve() for x in (args.keys,args.instance_file,args.plan) if x]
        require(output not in protected,'OUTPUT_CANNOT_OVERWRITE_INPUT')
        safe_json(output,result)
    # Never print plan BSON, census values or source exception details.
    print(json.dumps({k:v for k,v in result.items() if k in ('status','source_type','snapshot_hash','plan_hash','transform_hash','new_writes','target_hash','business_baseline_restored')}))
    return 0

if __name__=='__main__':
    try: sys.exit(main())
    except MigrationError as e:
        print(json.dumps({'status':'FAIL','code':str(e)}));sys.exit(2)
    except Exception:
        print(json.dumps({'status':'FAIL','code':'UNEXPECTED_FAILURE_REDACTED'}));sys.exit(3)
