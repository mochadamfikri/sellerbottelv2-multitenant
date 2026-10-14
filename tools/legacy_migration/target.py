from copy import deepcopy
from urllib.parse import quote
from .codec import identity, doc_hash
from .safety import require, MigrationError, SOCKET, AUDIT, allowed_databases, isolated_namespace

class MemoryTarget:
    """Injected target for adversarial/offline tests only; no network support."""
    def __init__(self, owner, instance='synthetic-instance'):
        self.allowed=allowed_databases(owner);self.instance=instance;self.data={}
    def docs(self,db,c):
        require(db in self.allowed,'DATABASE_REJECTED')
        return deepcopy(list(self.data.get((db,c),{}).values()))
    def names(self,db):return [c for d,c in self.data if d==db]
    def get(self,db,c,id):return next((d for d in self.docs(db,c) if identity(d['_id'])==identity(id)),None)
    def put(self,db,c,doc):
        require(db in self.allowed,'DATABASE_REJECTED')
        old=self.get(db,c,doc['_id'])
        require(old is None or doc_hash(old)==doc_hash(doc),'TARGET_CONFLICT')
        if old is not None:return False
        self.data.setdefault((db,c),{})[identity(doc['_id'])]=deepcopy(doc);return True
    def replace(self,db,c,old,new):
        require(self.get(db,c,old['_id'])==old,'TARGET_CAS_CONFLICT')
        self.data[(db,c)][identity(old['_id'])]=deepcopy(new)
    def delete(self,db,c,doc):
        require(doc_hash(self.get(db,c,doc['_id']))==doc_hash(doc),'ROLLBACK_CONFLICT')
        del self.data[(db,c)][identity(doc['_id'])]
    def drop_empty(self,db,c):
        if not self.docs(db,c):self.data.pop((db,c),None)

class MongoTarget(MemoryTarget):
    def __init__(self,owner,instance):
        require(isolated_namespace(),'ISOLATED_NETWORK_NAMESPACE_REQUIRED')
        require(not SOCKET.is_symlink() and SOCKET.is_socket() and SOCKET.resolve()==SOCKET,'REHEARSAL_SOCKET_REQUIRED')
        from pymongo import MongoClient
        self.allowed=allowed_databases(owner);self.instance=instance
        self.client=MongoClient('mongodb://'+quote(str(SOCKET),safe='')+'/?directConnection=true',serverSelectionTimeoutMS=4000)
        try:
            marker=self.client[AUDIT].migration_instance.find_one({'_id':'isolated'})
            require(marker and marker.get('instance_id')==instance and marker.get('network_mode')=='none','INSTANCE_NOT_APPROVED')
            require(set(self.client.list_database_names()).issubset(self.allowed|{'admin','config','local'}),'UNAPPROVED_DATABASE_ON_INSTANCE')
        except MigrationError:raise
        except Exception:raise MigrationError('REHEARSAL_MONGO_UNAVAILABLE') from None
    def docs(self,db,c):
        require(db in self.allowed,'DATABASE_REJECTED');return list(self.client[db][c].find())
    def names(self,db):
        require(db in self.allowed,'DATABASE_REJECTED');return self.client[db].list_collection_names()
    def get(self,db,c,id):
        require(db in self.allowed,'DATABASE_REJECTED');return self.client[db][c].find_one({'_id':id})
    def put(self,db,c,doc):
        require(db in self.allowed,'DATABASE_REJECTED')
        old=self.get(db,c,doc['_id'])
        require(old is None or doc_hash(old)==doc_hash(doc),'TARGET_CONFLICT')
        if old is not None:return False
        self.client[db][c].insert_one(deepcopy(doc));return True
    def replace(self,db,c,old,new):
        require(db in self.allowed,'DATABASE_REJECTED')
        require(doc_hash(self.get(db,c,old['_id']))==doc_hash(old),'TARGET_CAS_CONFLICT')
        result=self.client[db][c].replace_one(old,deepcopy(new));require(result.modified_count==1,'TARGET_CAS_CONFLICT')
    def delete(self,db,c,doc):
        require(db in self.allowed,'DATABASE_REJECTED')
        require(doc_hash(self.get(db,c,doc['_id']))==doc_hash(doc),'ROLLBACK_CONFLICT')
        require(self.client[db][c].delete_one(doc).deleted_count==1,'ROLLBACK_CONFLICT')
    def drop_empty(self,db,c):
        require(db in self.allowed,'DATABASE_REJECTED')
        if self.client[db][c].find_one({}, {'_id':1}) is None:self.client[db].drop_collection(c)
