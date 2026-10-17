# Excel IDSE import — initial read-only audit
Date: 2026-10-17. Status: BLOCKED for field precedence; workbook audit PASS.
Branch: feat/idse-excel-dry-run-20261017. Base: 1a82beeada65d09a42f0104ab291cdeab1c95505.
Master prompt read in full from /tmp/882eef40-fdc5-4b0b-8c68-4618e4c1773c.md; named repo path absent. Previous master handoff read in full from /tmp/3b13cddf-e123-4836-a388-dcfb5c30eb3a.md.
Workbook actual upload: /tmp/ed6d65dd-42d8-4f79-ad79-4aad1de53ea7.xlsx
Bytes: 217646. SHA256: 8423e19a1376f999852c0237640d7b3b1eb0d4d1aea106eb04df2a39b388ec59.
25 sheets, Summary headers A:H exact, 21 SKU unique across detail sheets.
Conflicts requiring Owner precedence approval:
- PRD002 and PRD003: Summary FRESH BY MADE; respective detail B5 Product. Summary distribution 14 Product/4 Jasa/3 Fresh versus master/detail 16/4/1.
- PRD009: Summary price 95000, detail B6 blank; master requires blank and checkout blocked.
- PRD010: Summary price 125000, detail B6 blank; master requires blank and checkout blocked.
Do not silently choose either source. Do not evaluate arbitrary formulas or trust caches. Product B4 stock formula SUM(J9:J208); Fresh availability formula depends on B14 and B9. Recompute from validated content, never import formula strings.
Current production /api/ HTTP 200 observed during audit. No restart, config edit, database write, or deployment for this task. Existing importer backend/bulk_product_import.py is legacy format and generates descriptions: must not replace exact workbook descriptions with its generated text. Inventory encryption/reservation existing code needs reuse with safe idempotent identity mapping.
No workbook or credentials committed. Database mapping, complete source validator, dry-run diff, and UI audit still pending.
Next: confirm field precedence then parser/validator offline, SKU mapping read-only, reviewed dry-run, staged apply only after separate explicit confirmation.

## Document-specific status
Audit RUNNING; conflicts BLOCKED. No COMPLETE claim.

## Owner precedence decision — 2026-10-17 20:07 WIB
Owner explicitly selected newer Summary for the conflicting fields. Effective types: 14 Product, 4 Jasa, 3 FRESH BY MADE. PRD002/PRD003 become Fresh; PRD009 price_idr=95000 and PRD010 price_idr=125000. Detail sheet blank prices must not override these approved Summary prices. This supersedes the master 16/4/1 and two-blank-price assumptions for this workbook only. No approval to apply to production. Fresh custom-message and activation status still require validation; absence must keep availability zero.

Permanent importer requirement incorporated. Existing admin Products.jsx already has import dialog; existing backend import_workbook route is immediate legacy import and must not be reused as approved dry-run/apply without changes. Next implement reusable reader with dynamic SKU count and safe errors before persistent job/UI integration.

Implemented backend/idse_workbook_schema.py and tests/test_idse_workbook_schema.py: bounded XLSX container, macro/external-link rejection, standard header errors, dynamic row counts ignoring Summary J:K. Five tests PASS; actual structural preflight PASS. Admin upload/diff/confirm/apply/template and semantic reader still PENDING. No production writes.

## Permanent preview API staging implementation
Tenant-operator protected /api/v2/import-excel/preview and /template added to isolated server source. Template explicitly DRAFT structural template, not complete official template. Mandatory structural preview never applies data. 7 tests PASS; UI/semantic SKU diff/confirmed transactional apply remain pending. No production update or data import.
