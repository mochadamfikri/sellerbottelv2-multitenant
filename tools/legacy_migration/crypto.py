"""Dedicated offline verifier. Never configures application Fernet or bot clients."""
import base64
import json
from cryptography.fernet import Fernet
from .safety import private_file, require, MigrationError

class OfflineKeys:
    ALLOWED={'INVENTORY_ENCRYPTION_KEY','TG_SESSION_KEY','JWT_SECRET','RESELLER_ENCRYPTION_KEY'}
    def __init__(self, path):
        try:
            self.keys=json.loads(private_file(path).read_text())
            require(set(self.keys).issubset(self.ALLOWED), 'LIVE_KEY_MATERIAL_REJECTED')
            self.ciphers={k:Fernet(v.encode()) for k,v in self.keys.items() if k!='JWT_SECRET'}
        except MigrationError: raise
        except Exception: raise MigrationError('OFFLINE_KEY_BUNDLE_INVALID') from None

    def decrypt(self, purpose, value):
        key='RESELLER_ENCRYPTION_KEY' if purpose=='reseller' and 'RESELLER_ENCRYPTION_KEY' in self.ciphers else ('TG_SESSION_KEY' if purpose=='session' else 'INVENTORY_ENCRYPTION_KEY')
        require(key in self.ciphers, 'OFFLINE_DECRYPT_KEY_MISSING')
        try: return self.ciphers[key].decrypt(value.encode())
        except Exception: raise MigrationError('OFFLINE_DECRYPT_FAILED') from None

    def verify(self, collections):
        counts={'inventory':0,'reseller_tokens':0,'sessions':0,'file_names':0,'file_payloads':0}
        for doc in collections.get(('sellerbottel','inventory_items'),[]):
            require(isinstance(doc.get('secret'),str), 'INVENTORY_SECRET_REQUIRED')
            raw=self.decrypt('inventory',doc['secret'])
            try:
                payload=json.loads(raw)
                require(isinstance(payload,dict), 'INVENTORY_PAYLOAD_INVALID')
                if payload.get('__file_name'):counts['file_names']+=1
                if payload.get('__file_data_b64'):
                    base64.b64decode(payload['__file_data_b64'],validate=True);counts['file_payloads']+=1
            except MigrationError:raise
            except Exception:raise MigrationError('INVENTORY_PAYLOAD_INVALID') from None
            counts['inventory']+=1
        for doc in collections.get(('sellerbottel','reseller_bots'),[]):
            if doc.get('token_encrypted'):self.decrypt('reseller',doc['token_encrypted']);counts['reseller_tokens']+=1
        for doc in collections.get(('sellerbottel','tg_accounts'),[]):
            if doc.get('session_encrypted'):self.decrypt('session',doc['session_encrypted']);counts['sessions']+=1
        return counts
