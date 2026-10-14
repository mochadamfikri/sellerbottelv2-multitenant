"""Bounded hot journal + immutable fixed-prefix chunks, standalone Mongo safe.

A chunk is written before CAS removing its exact prefix. Concurrent append can
only extend the prefix. Generation N is visible only when the owner CAS commits
archive_generation >= N; an interrupted write is harmless and reused on retry.
No lease, transaction, unbounded owner array, or deletion of history is needed.
"""
import hashlib
from bson import json_util
from pymongo.errors import DuplicateKeyError
from commerce.fulfillment_types import CommerceError

CHUNK_SIZE = 256
HOT_LIMIT = 512

class Journal:
    def __init__(self, database, collection, field, version, archive):
        self.db=database; self.owners=database[collection]; self.field=field; self.version=version
        self.chunks=database[archive]

    async def compact(self, doc, delta_fields):
        events=doc.get(self.field,[])
        if len(events)<HOT_LIMIT: return doc
        generation=doc.get('archive_generation',0)+1
        prefix=events[:CHUNK_SIZE]
        totals=dict(doc.get('archive_totals',{}))
        for event in prefix:
            for key,value in delta_fields(event).items(): totals[key]=totals.get(key,0)+value
        chunk={'_id':f'{doc["_id"]}:{generation}', 'owner_id':doc['_id'], 'generation':generation,
               'events':prefix, 'previous_hash':doc.get('archive_hash','')}
        chunk['hash']=hashlib.sha256(json_util.dumps(chunk,sort_keys=True).encode()).hexdigest()
        try: await self.chunks.update_one({'_id':chunk['_id']},{'$setOnInsert':chunk},upsert=True)
        except DuplicateKeyError: pass
        stored=await self.chunks.find_one({'_id':chunk['_id']})
        if stored['hash']!=chunk['hash']: raise CommerceError('Journal archive prefix conflict')
        result=await self.owners.update_one({'_id':doc['_id'],self.version:doc.get(self.version,0)},
            {'$set':{self.field:events[CHUNK_SIZE:], 'archive_generation':generation,'archive_hash':chunk['hash'], 'archive_totals':totals},'$inc':{self.version:1}})
        return await self.owners.find_one({'_id':doc['_id']}) if result.modified_count else None

    async def relevant(self, doc, criteria):
        """Indexed historical lookup; no full-history read in normal mutations."""
        generation=doc.get('archive_generation',0)
        if not generation: return []
        if await self.chunks.count_documents({'owner_id':doc['_id'],'generation':{'$lte':generation}}) != generation:
            raise CommerceError('Journal archive missing; restore required')
        query={'owner_id':doc['_id'],'generation':{'$lte':generation},'$or':[{f'events.{k}':v} for k,v in criteria.items()]}
        chunks=await self.chunks.find(query).sort('generation',1).to_list(None)
        return [e for c in chunks for e in c['events'] if any(e.get(k)==v for k,v in criteria.items())]

    async def verify(self, doc, delta_fields, project=None):
        """Explicit audit/rebuild streams immutable chunks, then hot events."""
        previous=''; totals={}; count=0; generation=0
        async for chunk in self.chunks.find({'owner_id':doc['_id'],'generation':{'$lte':doc.get('archive_generation',0)}}).sort('generation',1):
            generation+=1
            body={k:v for k,v in chunk.items() if k!='hash'}
            if chunk['generation']!=generation or chunk['previous_hash']!=previous or hashlib.sha256(json_util.dumps(body,sort_keys=True).encode()).hexdigest()!=chunk['hash']:
                raise CommerceError('Journal archive verification failed')
            previous=chunk['hash']
            for e in chunk['events']:
                count+=1
                for k,v in delta_fields(e).items(): totals[k]=totals.get(k,0)+v
            if project: await project(chunk['events'])
        if generation!=doc.get('archive_generation',0) or previous!=doc.get('archive_hash','') or totals!=doc.get('archive_totals',{}):
            raise CommerceError('Journal archive snapshot mismatch')
        for e in doc.get(self.field,[]):
            count+=1
            for k,v in delta_fields(e).items(): totals[k]=totals.get(k,0)+v
        if project: await project(doc.get(self.field,[]))
        return {'events':count,'chunks':generation,'totals':totals,'verified':True}

async def ensure_archive_indexes(database):
    for name,fields in [('stock_journal_archive',['_id','reference_id','sale_reference']),('settlement_journal_archive',['reference','payment_id','payout_id'])]:
        for field in fields:
            await database[name].create_index([('owner_id',1),(f'events.{field}',1),('generation',1)],name='archive_'+field.lstrip('_'))

async def project_events(collection, events):
    """Append-only projection, bounded batches. Small effects retain one-write recovery."""
    from pymongo.errors import BulkWriteError
    for offset in range(0,len(events),256):
        batch=events[offset:offset+256]
        present={d['_id'] for d in await collection.find({'_id':{'$in':[e['_id'] for e in batch]}},{'_id':1}).to_list(None)}
        missing=[dict(e) for e in batch if e['_id'] not in present]
        if len(missing)>32:
            try: await collection.insert_many(missing,ordered=False)
            except BulkWriteError as error:
                if error.details.get('writeConcernErrors') or any(e.get('code')!=11000 for e in error.details.get('writeErrors',[])): raise
        else:
            for entry in missing:
                try: await collection.update_one({'_id':entry['_id']},{'$setOnInsert':entry},upsert=True)
                except DuplicateKeyError: pass
