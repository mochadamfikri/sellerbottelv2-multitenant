import pytest
from pydantic import ValidationError
from product_metadata import WarrantyMetadata, warranty_snapshot


def test_warranty_validation_and_unknown_legacy():
    assert warranty_snapshot({}) is None
    assert WarrantyMetadata(enabled=False).enabled is False
    with pytest.raises(ValidationError):
        WarrantyMetadata(enabled=True)
    with pytest.raises(ValidationError):
        WarrantyMetadata(enabled=False, coverage='replace')
    with pytest.raises(ValidationError):
        WarrantyMetadata(enabled='false')


def test_snapshot_is_independent_and_allowlisted():
    product = {'warranty': {'enabled':True, 'duration':'7 hari', 'secret':'NOT_COPY'}}
    snapshot = warranty_snapshot(product)
    product['warranty']['duration'] = '30 hari'
    assert snapshot == {'enabled':True, 'duration':'7 hari'}
