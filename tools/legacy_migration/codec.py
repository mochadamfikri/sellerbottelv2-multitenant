import hashlib
import json
import struct
from collections import Counter
from datetime import datetime
from pathlib import Path
from bson import BSON, Binary, Decimal128, Int64, ObjectId
from .safety import require


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def doc_hash(doc):
    return digest(BSON.encode(doc))


def identity(value):
    return doc_hash({'id': value})


def json_hash(value):
    return digest(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


def bson_records(raw):
    pos = 0
    while pos < len(raw):
        require(len(raw)-pos >= 4, 'INVALID_BSON')
        size = struct.unpack('<i', raw[pos:pos+4])[0]
        require(5 <= size <= 16*1024*1024 and pos+size <= len(raw), 'INVALID_BSON')
        data = raw[pos:pos+size]
        try:
            doc = BSON(data).decode()
        except Exception:
            require(False, 'INVALID_BSON')
        require('_id' in doc, 'DOCUMENT_ID_REQUIRED')
        yield data, doc
        pos += size


def bson_type(value):
    if value is None: return 'null'
    if isinstance(value, bool): return 'bool'
    if isinstance(value, Int64): return 'int64'
    if isinstance(value, int): return 'int32' if -(2**31) <= value < 2**31 else 'int64'
    if isinstance(value, float): return 'double'
    if isinstance(value, Decimal128): return 'decimal128'
    if isinstance(value, ObjectId): return 'objectId'
    if isinstance(value, datetime): return 'date'
    if isinstance(value, str): return 'string'
    if isinstance(value, (Binary, bytes)): return 'binary'
    if isinstance(value, list): return 'array'
    if isinstance(value, dict): return 'object'
    return type(value).__name__


def paths(doc, prefix=''):
    for k,v in doc.items():
        path = prefix + k
        yield path, bson_type(v)
        if isinstance(v, dict): yield from paths(v, path+'.')
        elif isinstance(v, list):
            for item in v:
                yield path+'[]', bson_type(item)
                if isinstance(item, dict): yield from paths(item, path+'[].')


def census(docs):
    counts=Counter(); present=Counter()
    for doc in docs:
        pairs=list(paths(doc));counts.update(pairs);present.update(set(p for p,_ in pairs))
    return [{'path':p,'type':t,'occurrences':n,'documents_present':present[p],
             'documents_missing':len(docs)-present[p]} for (p,t),n in sorted(counts.items())]


def safe_json(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n');path.chmod(0o600)
