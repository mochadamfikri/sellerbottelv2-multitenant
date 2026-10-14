import importlib.util
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('reset_owner_uat',Path(__file__).resolve().parents[2]/'tools/reset_owner_uat.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
config={'ENVIRONMENT':'development','SELLERBOTTEL_UAT':'true','PLATFORM_DB_NAME':'sellerbottel_uat_platform','MONGO_URL':'mongodb://127.0.0.1:27020/?serverSelectionTimeoutMS=3000'}
manifest=[{'slug':s,'tenant_id':'11111111-1111-4111-8111-111111111111','database_name':'sellerbottel_tenant_'+s.replace('-','_')} for s in ['fashion-demo','digital-demo']]
@pytest.mark.parametrize('key,value',[('ENVIRONMENT','production'),('MONGO_URL','mongodb://127.0.0.1:27019/'),('PLATFORM_DB_NAME','sellerbottel'),('SELLERBOTTEL_UAT','false')])
def test_reset_rejects_non_uat_targets(key,value):
 with pytest.raises(ValueError):module.validate_targets({**config,key:value},manifest)
def test_reset_rejects_arbitrary_or_wrong_database():
 assert module.validate_targets(config,manifest)==manifest
 for rows in [manifest[:1],[{**manifest[0],'slug':'customer-real'},manifest[1]],[{**manifest[0],'database_name':'production'},manifest[1]]]:
  with pytest.raises(ValueError):module.validate_targets(config,rows)
