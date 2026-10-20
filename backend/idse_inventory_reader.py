"""Read inventory safely; secrets remain memory-only and repr-hidden."""
from dataclasses import dataclass, field
import hashlib
import json
from urllib.parse import urlsplit

HEADERS = ('Stock ID','Status','Format','Email','Password','Redeem / Link','License / Kode','Data Bebas','Catatan','Valid Stock')

@dataclass(repr=False)
class InventoryRead:
    units: list = field(default_factory=list, repr=False)
    issues: list = field(default_factory=list)
    skipped: int = 0
    def public(self):
        return {'valid_available':len(self.units),'skipped':self.skipped,'issues':self.issues}


def read_inventory(sheet):
    out = InventoryRead()
    if sheet.max_row > 10000 or sheet.max_column > 100:
        out.issues.append({'code':'INVENTORY_DIMENSION_LIMIT','sheet':sheet.title});return out
    if tuple(sheet.cell(8,c).value for c in range(1,11)) != HEADERS:
        out.issues.append({'code':'INVENTORY_HEADER_MISMATCH','sheet':sheet.title,'row':8});return out
    fingerprints, identities = set(), set()
    for rownum, cells in enumerate(sheet.iter_rows(min_row=9,max_col=10),9):
        values=[c.value for c in cells]
        # Formula-only validity columns and prefilled identifiers are not stock.
        if not any(values[i] is not None and str(values[i]).strip() for i in range(3,8)):
            continue
        if any(c.data_type == 'f' for c in cells[:9]):
            out.issues.append({'code':'INVENTORY_FORMULA_FORBIDDEN','sheet':sheet.title,'row':rownum});continue
        stock_id,status,fmt,email,password,link,license_code,free,_,valid=values
        if str(status or '').strip().upper() != 'AVAILABLE':
            out.skipped+=1;continue
        payload={}
        # Require one unambiguous fulfillment payload; never echo invalid data.
        candidates=int(bool(email or password))+int(bool(link))+int(bool(license_code))+int(bool(free))
        code=None
        if candidates != 1:code='AMBIGUOUS_OR_EMPTY_PAYLOAD'
        elif email or password:
            if not email or not password or '@' not in str(email):code='INCOMPLETE_CREDENTIAL_PAIR'
            else:payload={'email':str(email).strip(),'password':str(password)}
        elif link:
            parsed=urlsplit(str(link).strip())
            if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password:code='INVALID_REDEEM_URL'
            else:payload={'redeem_link':str(link).strip()}
        elif license_code:payload={'license':str(license_code).strip()}
        else:payload={'value':str(free).strip()}
        if code:
            out.issues.append({'code':code,'sheet':sheet.title,'row':rownum});continue
        fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        identity=str(stock_id).strip() if stock_id is not None else fingerprint
        if fingerprint in fingerprints or identity in identities:
            out.skipped+=1;continue
        fingerprints.add(fingerprint);identities.add(identity)
        out.units.append({'source_id':identity,'fingerprint':fingerprint,'payload':payload,'row':rownum})
    return out
