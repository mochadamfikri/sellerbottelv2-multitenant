"""Additive product warranty validation and purchase-time snapshots."""
from copy import deepcopy
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class WarrantyMetadata(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: StrictBool
    duration: str | None = Field(default=None, max_length=120)
    coverage: str | None = Field(default=None, max_length=4000)
    terms: str | None = Field(default=None, max_length=4000)
    claim_process: str | None = Field(default=None, max_length=4000)

    @model_validator(mode='after')
    def valid_terms(self):
        for field in ('duration', 'coverage', 'terms', 'claim_process'):
            value = getattr(self, field)
            if value is not None:
                setattr(self, field, value.strip() or None)
        if self.enabled and not self.duration:
            raise ValueError('Durasi garansi wajib jika garansi aktif')
        if not self.enabled and any(getattr(self, key) for key in ('duration','coverage','terms','claim_process')):
            raise ValueError('Produk tanpa garansi tidak boleh menyertakan ketentuan garansi')
        return self


def warranty_snapshot(product):
    # Legacy unknown remains unknown; do not backfill invented entitlements.
    data = product.get('warranty')
    if not isinstance(data, dict) or not isinstance(data.get('enabled'), bool):
        return None
    return deepcopy({k: data[k] for k in ('enabled','duration','coverage','terms','claim_process') if k in data})
