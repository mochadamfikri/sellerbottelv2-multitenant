"""Durable, encrypted import plans bound to tenant and actor."""
import json
import secrets
from datetime import datetime, timezone, timedelta
from hashlib import sha256


async def stage_plan(database, tenant_id, actor_id, workbook, preview, cipher):
    token=secrets.token_urlsafe(32)
    job={'_id':secrets.token_hex(16),'tenant_id':tenant_id,'actor_id':str(actor_id),
         'status':'PREVIEW','workbook_sha256':sha256(workbook).hexdigest(),
         'confirmation_hash':sha256(token.encode()).hexdigest(),
         'workbook_encrypted':cipher.encrypt(workbook).decode(),
         'preview_encrypted':cipher.encrypt(json.dumps(preview,default=str).encode()).decode(),
         'created_at':datetime.now(timezone.utc),
         'expires_at':datetime.now(timezone.utc)+timedelta(hours=24)}
    await database.excel_import_jobs.insert_one(job)
    return {'job_id':job['_id'],'confirmation_token':token,'status':'PREVIEW','apply_allowed':False}


async def owned_plan(database, tenant_id, actor_id, job_id, token, cipher):
    job=await database.excel_import_jobs.find_one({'_id':job_id,'tenant_id':tenant_id,'actor_id':str(actor_id)})
    if not job or not secrets.compare_digest(job['confirmation_hash'],sha256(token.encode()).hexdigest()):
        raise ValueError('Import plan not found or confirmation invalid')
    expiry=job['expires_at']
    if expiry.tzinfo is None:expiry=expiry.replace(tzinfo=timezone.utc)
    if expiry < datetime.now(timezone.utc):raise ValueError('Import preview expired')
    return job, json.loads(cipher.decrypt(job['preview_encrypted'].encode()))
