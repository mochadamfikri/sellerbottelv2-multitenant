"""Explicit V1 launch policy; historical payments retain their snapshots."""
import os
from commerce.fulfillment_types import CommerceError
from .models import money


def enabled():
    return os.getenv('COMMERCE_LAUNCH_PROFILE') == 'v1_kasera'


def require_provider(name):
    if enabled() and name != 'kasera':
        raise CommerceError('V1 tenant payments require Kasera')


def require_shipping(mode):
    if enabled() and mode != 'manual_shipping':
        raise CommerceError('V1 requires manual shipping')


def snapshot(provider, method, detail, *, payment_mode="platform_settlement", platform_fee=250):
    if not enabled():
        return {}
    require_provider(provider)
    # The approved percentage policy is QRIS-specific, not Kasera VA pricing.
    fee = (detail or {}).get('fee', {})
    if method != 'qris' or fee.get('percent_bps') != 70 or fee.get('flat') != 250:
        raise CommerceError('NEEDS PROVIDER FEE RULE CONFIRMATION')
    return {'fee_policy': {'version': 'v1_kasera', 'percent_bps': 70,
                           'fixed': 250, 'platform': money(platform_fee) if payment_mode == 'platform_settlement' else 0, 'rounding': 'ceil'}}


def breakdown(payment):
    policy = payment['fee_policy']
    gross = money(payment['amount'])
    percentage = (gross * policy['percent_bps'] + 9999) // 10000
    gateway = money(payment['gateway_fee'])
    if gateway != percentage + policy['fixed']:
        raise CommerceError('NEEDS PROVIDER FEE RULE CONFIRMATION')
    platform = policy['platform']
    quote = payment.get('fee_quote')
    if quote and (gross != quote['total'] or gateway != quote['gateway_fee'] or gross-gateway-platform != quote['net_settlement']):
        raise CommerceError('Settlement fee quote mismatch')
    if gross < gateway + platform:
        raise CommerceError('Fees exceed payment')
    return [('PAYMENT_GROSS', gross, {}), ('KASERA_PERCENT_FEE', percentage, {}),
            ('KASERA_FIXED_FEE', policy['fixed'], {}),
            ('SELLERBOTTEL_PLATFORM_FEE', platform, {}),
            ('NET_SETTLEMENT', gross-gateway-platform, {'pending': gross-gateway-platform})]


def buyer_quote(base_amount, fee_snapshot):
    """Smallest whole-rupiah gross whose provider net equals the cart price.

    Kasera documents ceil(percentage * gross) + flat. The owner selected B:
    buyer pays Kasera, tenant pays SellerBottel only for IDSE settlement.
    """
    base = money(base_amount, positive=True)
    policy = fee_snapshot['fee_policy']
    divisor = 10000 - policy['percent_bps']
    total = money(((base + policy['fixed']) * 10000 + divisor - 1) // divisor)
    percentage = (total * policy['percent_bps'] + 9999) // 10000
    gateway = percentage + policy['fixed']
    if total - gateway != base or base < policy['platform']:
        raise CommerceError('Invalid fee quote')
    return {'base_amount': base, 'gateway_percent_fee': percentage,
            'gateway_fixed_fee': policy['fixed'], 'gateway_fee': gateway,
            'platform_fee': policy['platform'], 'payment_fee': gateway,
            'total': total, 'net_settlement': base-policy['platform'],
            'gateway_bearer': 'buyer', 'platform_bearer': 'tenant'}


async def platform_fee_policy(platform):
    settings = await platform.platform_payment_settings.find_one({'_id': 'kasera'}) or {}
    return {'platform_fee': money(settings.get('platform_fee', 250)),
            'tiers': settings.get('platform_fee_tiers', [])}


def select_platform_fee(policy, base_amount):
    base = money(base_amount, positive=True)
    for tier in policy['tiers']:
        if tier['min_amount'] <= base and (tier['max_amount'] is None or base <= tier['max_amount']):
            return money(tier['fee']), dict(tier)
    return money(policy['platform_fee']), {'default': True}


async def platform_fee(platform):
    return (await platform_fee_policy(platform))['platform_fee']


async def payment_snapshot(platform, provider, method, detail, *, payment_mode, base_amount):
    fee, rule = 0, {'self_gateway': True}
    if enabled() and payment_mode == 'platform_settlement':
        fee, rule = select_platform_fee(await platform_fee_policy(platform), base_amount)
    result = snapshot(provider, method, detail, payment_mode=payment_mode, platform_fee=fee)
    if result:
        result['fee_policy'].update({'platform_fee_basis': base_amount, 'platform_fee_rule': rule})
    return result
