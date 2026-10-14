import asyncio
import pytest
from pydantic import ValidationError
from payments.launch import select_platform_fee, payment_snapshot
from v2_platform_routes import IdseGatewayFeeBody
from tests.test_v2_platform_routes import _request, _seed_admin, _admin_headers

TIERS=[{'min_amount':10000,'max_amount':20000,'fee':250},{'min_amount':20001,'max_amount':50000,'fee':500},{'min_amount':50001,'max_amount':None,'fee':750}]

@pytest.mark.parametrize('amount,fee',[(9999,250),(10000,250),(20000,250),(20001,500),(50000,500),(50001,750),(10**12,750)])
def test_fee_tier_boundaries(amount,fee):
    assert select_platform_fee({'platform_fee':250,'tiers':TIERS},amount)[0]==fee

@pytest.mark.parametrize('tiers',[
    [{'min_amount':10000,'max_amount':20000,'fee':250},{'min_amount':20000,'max_amount':50000,'fee':500}],
    [{'min_amount':10000,'max_amount':None,'fee':250},{'min_amount':20001,'max_amount':50000,'fee':500}],
    [{'min_amount':20000,'max_amount':10000,'fee':250}],
    [{'min_amount':0,'max_amount':10000,'fee':250}],
    [{'min_amount':1,'max_amount':10000,'fee':-1}],
    [{'min_amount':1,'max_amount':10000,'fee':True}],
    [{'min_amount':1,'max_amount':10000,'fee':250.5}],
])
def test_invalid_or_overlapping_ranges_rejected(tiers):
    with pytest.raises(ValidationError):IdseGatewayFeeBody(platform_fee=250,tiers=tiers)


def test_only_platform_owner_can_change_fee_and_existing_snapshot_is_frozen(monkeypatch):
    from db import platform_db
    async def run():
        platform=platform_db();await platform.platform_payment_settings.delete_one({'_id':'kasera'})
        path='/api/v2/platform/payments/kasera/fee'
        assert (await _request('GET',path)).status_code==401
        assert (await _request('PUT',path,json={'platform_fee':500})).status_code==401
        await _seed_admin('fee-tenant',role='admin',platform_role='tenant_owner')
        headers=_admin_headers('fee-tenant')
        assert (await _request('PUT',path,headers=headers,json={'platform_fee':500})).status_code==403
        await _seed_admin('fee-platform',role='admin',platform_role='platform_admin')
        headers=_admin_headers('fee-platform')
        default=await _request('GET',path,headers=headers)
        assert default.json()['platform_fee']==250 and default.json()['tiers']==[]
        await platform.platform_payment_settings.update_one({'_id':'kasera'},{'$set':{'credential_id':'retained','capabilities':{'marker':'retained'}}},upsert=True)
        body={'platform_fee':250,'tiers':TIERS}
        result=await _request('PUT',path,headers=headers,json=body)
        assert result.status_code==200,result.text
        assert result.json()['tiers']==TIERS
        saved=await platform.platform_payment_settings.find_one({'_id':'kasera'})
        assert saved['credential_id']=='retained' and saved['capabilities']=={'marker':'retained'}
        detail={'fee':{'percent_bps':70,'flat':250}}
        monkeypatch.setenv('COMMERCE_LAUNCH_PROFILE','v1_kasera')
        original=await payment_snapshot(platform,'kasera','qris',detail,payment_mode='platform_settlement',base_amount=25000)
        assert original['fee_policy']['platform']==500
        assert original['fee_policy']['platform_fee_rule']==TIERS[1]
        changed=await _request('PUT',path,headers=headers,json={'platform_fee':1000,'tiers':[]})
        assert changed.status_code==200
        newer=await payment_snapshot(platform,'kasera','qris',detail,payment_mode='platform_settlement',base_amount=25000)
        assert newer['fee_policy']['platform']==1000 and original['fee_policy']['platform']==500
        own=await payment_snapshot(platform,'kasera','qris',detail,payment_mode='self_gateway',base_amount=25000)
        assert own['fee_policy']['platform']==0
        for invalid in [-1,True,2.5,1000001]:
            assert (await _request('PUT',path,headers=headers,json={'platform_fee':invalid})).status_code==422
        assert (await _request('GET',path,headers=headers)).json()['platform_fee']==1000
        assert await platform.audit_events.count_documents({'action':'idse_gateway_fee.updated'})>=1
    asyncio.run(run())
