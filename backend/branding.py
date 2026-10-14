"""One tenant identity, capabilities owned by the platform registry, no billing logic."""
import re
from html import escape
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from db import _resolve_db
from bot_tenant_scope import get_current_scope
from physical_routes import owner_scope

FONTS = {'system': 'system-ui, sans-serif', 'serif': 'Georgia, serif', 'mono': 'monospace'}
class Branding(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    mode: str = Field(default='co_branded', pattern='^(platform|co_branded|tenant_only)$')
    brand_name: str = Field(default='', max_length=100)
    logo: str = Field(default='', max_length=500)
    favicon: str = Field(default='', max_length=500)
    invoice_logo: str = Field(default='', max_length=500)
    primary_color: str = Field(default='#065f46', pattern='^#[0-9a-fA-F]{6}$')
    secondary_color: str = Field(default='#ecfdf5', pattern='^#[0-9a-fA-F]{6}$')
    font: str = Field(default='system', pattern='^(system|serif|mono)$')
    store_description: str = Field(default='', max_length=500)
    domain: str = Field(default='', max_length=253)
    telegram_bot: str = Field(default='', max_length=32, pattern='^@?[a-zA-Z0-9_]*$')
    whatsapp: str = Field(default='', max_length=20, pattern='^[+0-9]*$')
    email_sender_name: str = Field(default='', max_length=100)
    receipt_footer: str = Field(default='', max_length=500)
    social_links: dict[str, str] = Field(default_factory=dict, max_length=8)

    @field_validator('brand_name', 'store_description', 'email_sender_name', 'receipt_footer')
    @classmethod
    def plain_text(cls, value):
        if any(ord(c)<32 or ord(c)==127 or c in '<>' for c in value):
            raise ValueError('Plain text required')
        return value

    @field_validator('logo', 'favicon', 'invoice_logo')
    @classmethod
    def safe_url(cls, value):
        if not value: return value
        u=urlsplit(value)
        if u.scheme!='https' or not u.hostname or u.username or u.password or any(c in value for c in '\\<>"\r\n'):
            raise ValueError('HTTPS URL without credentials required')
        return value

    @field_validator('social_links')
    @classmethod
    def links(cls, value):
        for k,v in value.items():
            if not re.fullmatch('[a-zA-Z0-9 _-]{1,30}', k): raise ValueError('Invalid social label')
            cls.safe_url(v)
        return value

    @field_validator('domain')
    @classmethod
    def disabled_domain(cls, value):
        if value: raise ValueError('Custom domains disabled pending ownership and TLS verification')
        return value

async def context(database=None, tenant=None):
    database=database if database is not None else _resolve_db()
    scope=get_current_scope()
    if tenant is None and scope and scope.database_name==database.name:
        from dependencies import get_tenant_registry
        tenant=await get_tenant_registry().get_tenant(scope.slug)
    tenant=tenant or {}
    caps=(tenant.get('metadata') or {}).get('capabilities') or {}
    # No owner route can write these registry-controlled entitlements.
    allowed=['platform','co_branded']
    if caps.get('can_white_label') is True: allowed.append('tenant_only')
    configured=caps.get('branding_mode_allowed')
    if isinstance(configured,list): allowed=[m for m in allowed if m in configured] or ['platform']
    capabilities={'can_white_label': 'tenant_only' in allowed, 'branding_mode_allowed': allowed,
                  'custom_domain_enabled': False, 'custom_email_branding_enabled': caps.get('custom_email_branding_enabled') is True}
    settings=await database.settings.find_one({'_id':'main'}) or {}
    saved=await database.branding.find_one({'_id':'main'}) or {}
    raw={k:v for k,v in saved.items() if k in Branding.model_fields}
    identity=Branding(**raw).model_dump()
    identity['brand_name']=identity['brand_name'] or settings.get('store_name') or tenant.get('name') or 'SellerBottel'
    if identity['mode'] not in allowed: identity['mode']=allowed[0]
    if identity['mode']=='platform':
        identity.update(brand_name='SellerBottel',logo='',favicon='',invoice_logo='',primary_color='#065f46',secondary_color='#ecfdf5',font='system',receipt_footer='')
    identity['attribution']='Powered by SellerBottel' if identity['mode']=='co_branded' else ''
    identity['sender_name']=(identity['email_sender_name'] or identity['brand_name']) if capabilities['custom_email_branding_enabled'] else 'SellerBottel'
    identity['font_family']=FONTS[identity['font']]
    return identity,capabilities

async def email_identity():
    identity,_=await context()
    return identity

def receipt_html(identity, order):
    logo=identity.get('invoice_logo') or identity.get('logo')
    image=f'<img alt="Logo" width="96" src="{escape(logo, quote=True)}">' if logo else ''
    rows=''.join(f'<li>{escape(str(i.get("name", "Produk")))} × {int(i.get("qty",0))}</li>' for i in order.get('items',[]))
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>Receipt</title></head><body>{image}'
            f'<h1>{escape(identity["brand_name"])}</h1><p>{escape(str(order.get("invoice_id") or order["_id"]))}</p>'
            f'<ul>{rows}</ul><p>{escape(str(order.get("currency","IDR")))} {escape(str(order.get("total",0)))}</p>'
            f'<p>Status: {escape(str(order.get("status","")))}</p><footer>{escape(identity["receipt_footer"])}<br>{escape(identity["attribution"])}</footer></body></html>')

router=APIRouter(prefix='/api/public/tenant/full/branding',dependencies=[Depends(owner_scope)])
@router.get('')
async def read_branding():
    identity,caps=await context()
    return {'branding':identity,'capabilities':caps}

@router.put('')
async def save_branding(body:Branding):
    _,caps=await context()
    if body.mode not in caps['branding_mode_allowed']:
        raise HTTPException(403,'Branding mode requires platform entitlement')
    if body.email_sender_name and not caps['custom_email_branding_enabled']:
        raise HTTPException(403,'Custom email branding requires platform entitlement')
    await _resolve_db().branding.update_one({'_id':'main'},{'$set':body.model_dump()},upsert=True)
    return await read_branding()

@router.post('/preview')
async def preview_branding(body:Branding):
    _,caps=await context()
    if body.mode not in caps['branding_mode_allowed']: raise HTTPException(403,'Branding mode requires platform entitlement')
    identity=body.model_dump(); identity['attribution']='Powered by SellerBottel' if body.mode=='co_branded' else ''
    if body.mode=='platform': identity.update(brand_name='SellerBottel',logo='',invoice_logo='')
    return {'receipt_html':receipt_html(identity,{'_id':'PREVIEW','items':[],'total':0}), 'branding':identity}
