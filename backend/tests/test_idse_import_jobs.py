import asyncio
import pytest
from cryptography.fernet import Fernet
from mongomock_motor import AsyncMongoMockClient
from idse_import_jobs import stage_plan, owned_plan


def test_durable_encrypted_plan_actor_tenant_and_confirmation():
    async def run():
        db=AsyncMongoMockClient()['jobs'];cipher=Fernet(Fernet.generate_key())
        result=await stage_plan(db,'t','admin',b'PRIVATE_WORKBOOK',{'private':'PRIVATE_METADATA'},cipher)
        stored=await db.excel_import_jobs.find_one({'_id':result['job_id']})
        assert 'PRIVATE_WORKBOOK' not in str(stored) and 'PRIVATE_METADATA' not in str(stored)
        assert result['confirmation_token'] not in str(stored)
        _,plan=await owned_plan(db,'t','admin',result['job_id'],result['confirmation_token'],cipher)
        assert plan['private']=='PRIVATE_METADATA'
        for tenant,actor,token in [('other','admin',result['confirmation_token']),('t','other',result['confirmation_token']),('t','admin','bad')]:
            with pytest.raises(ValueError):await owned_plan(db,tenant,actor,result['job_id'],token,cipher)
    asyncio.run(run())
