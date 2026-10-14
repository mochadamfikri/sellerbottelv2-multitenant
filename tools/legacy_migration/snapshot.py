"""Immutable BSON source reader. Never accepts a Mongo URI or application env."""
import json
from pathlib import Path
from .codec import digest, json_hash, bson_records, census
from .safety import require, MigrationError, allowed_databases

COLLECTIONS = tuple('admins balance_adjustments bot_users store_customers products product_catalogs inventory_items purchases deposits gopay_payments settings counters coupons discounts promo_coupons promo_coupon_redemptions promo_coupon_usage promo_events promo_suppressions promo_campaigns prospects traffic_sources tg_accounts tg_groups outreach_jobs outreach_campaigns broadcasts daily_recaps stock_events post_purchase_actions bot_chat_messages freeze_log bot_messages bot_message_history required_channels bot2_restock_requests processed_updates processed_updates_bot2 reseller_bots reseller_bot_users reseller_updates reseller_payments reseller_commissions reseller_payouts reseller_contests login_attempts store_email_codes'.split())
RECOVERY = ('sellerbottel_catalog_recovery','sellerbottel_final_probe','sellerbottel_recovery_probe')

class Snapshot:
    def __init__(self, directory):
        self.root=Path(directory).resolve()
        require(self.root.is_dir(), 'SNAPSHOT_DIRECTORY_REQUIRED')
        self.manifest=json.loads((self.root/'manifest.json').read_text())
        m=self.manifest
        require(m.get('version')==1 and m.get('source_type') in ('synthetic','real_snapshot'), 'SNAPSHOT_VERSION_REQUIRED')
        for key in ('snapshot_id','timestamp','fence_marker','runtime_bundle','ownership','files','collections','schema_decisions','recovery_decisions','escrow_references'):
            require(key in m, 'SNAPSHOT_MANIFEST_INCOMPLETE')
        require(bool(m['fence_marker']) and bool(m['timestamp']), 'FENCE_REQUIRED')
        require(all(k in m['runtime_bundle'] for k in ('commit','dirty_patch_hash','bundle_hash')), 'ROLLBACK_BUNDLE_METADATA_REQUIRED')
        self.owner=m['ownership'];allowed_databases(self.owner)
        require((m['source_type']=='synthetic') == (self.owner.get('synthetic') is True), 'SYNTHETIC_OWNERSHIP_MISMATCH')
        self.hash=json_hash(m)
        self._load()

    def file(self, rel):
        require(isinstance(rel,str) and rel and not Path(rel).is_absolute() and '..' not in Path(rel).parts, 'SNAPSHOT_PATH_REJECTED')
        p=self.root/rel
        require(not any(x.is_symlink() for x in [p,*p.parents] if x != self.root.parent), 'SNAPSHOT_SYMLINK_REJECTED')
        require(p.is_file() and p.resolve().is_relative_to(self.root), 'SNAPSHOT_FILE_REQUIRED')
        return p

    def _load(self):
        m=self.manifest
        for rel,h in m['files'].items(): require(digest(self.file(rel).read_bytes())==h, 'SOURCE_SNAPSHOT_DRIFT')
        present={str(p.relative_to(self.root)) for p in self.root.rglob('*') if p.is_file()}
        require(present == set(m['files'])|{'manifest.json'}, 'UNMANIFESTED_SNAPSHOT_FILE')
        self.collections={};self.raw={};self.metadata={}
        for entry in m['collections']:
            db,c=entry['database'],entry['collection'];key=(db,c)
            require(db in ('sellerbottel',*RECOVERY) and c in COLLECTIONS, 'UNKNOWN_COLLECTION')
            require(key not in self.collections, 'DUPLICATE_COLLECTION')
            require(entry['bson'] in m['files'] and entry['metadata'] in m['files'], 'UNHASHED_COLLECTION_FILE')
            records=list(bson_records(self.file(entry['bson']).read_bytes()))
            require(len(records)==entry['count'], 'SOURCE_COUNT_MISMATCH')
            self.raw[key]=[r for r,d in records];self.collections[key]=[d for r,d in records]
            meta=json.loads(self.file(entry['metadata']).read_text())
            require(isinstance(meta.get('indexes'),list) and isinstance(meta.get('options'),dict), 'INDEX_OPTIONS_REQUIRED')
            self.metadata[key]=meta
        require({c for db,c in self.collections if db=='sellerbottel'}==set(COLLECTIONS), 'MAIN_47_COLLECTIONS_REQUIRED')
        require(set(RECOVERY).issubset({db for db,c in self.collections}), 'RECOVERY_ARCHIVES_REQUIRED')

    def check(self):
        newer=Snapshot(self.root)
        require(newer.hash==self.hash, 'SOURCE_SNAPSHOT_DRIFT')

    def schema(self):
        return {db+'.'+c:census(docs) for (db,c),docs in self.collections.items()}

    def validate_schema(self):
        decisions=self.manifest['schema_decisions']
        for key,fields in self.schema().items():
            for field in fields:
                decision=decisions.get(key,{}).get(field['path'])
                require(decision in ('preserve','preserve_critical'), 'UNKNOWN_CRITICAL_SCHEMA_DECISION')

    def inventory(self):
        return {'source_type':self.manifest['source_type'],'snapshot_hash':self.hash,
                'coverage':{db+'.'+c:len(d) for (db,c),d in self.collections.items()},
                'field_type_census':self.schema(),
                'index_options':{db+'.'+c:m for (db,c),m in self.metadata.items()}}
