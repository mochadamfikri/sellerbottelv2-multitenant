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
Phases: reader -> validator -> mapping -> metadata -> Product stock -> Jasa -> Fresh -> UI -> history -> regression. Production apply is not authorized.

## Permanent reusable importer — Owner requirement 2026-10-17 20:08 WIB
Importer is a durable admin feature, not a one-off script. Future valid workbooks may contain different sheet/SKU counts; 25/21 is only the initial fixture. Required UI flow: download official template -> upload -> schema validation/mapping errors -> tenant-scoped SKU diff -> mandatory dry-run -> explicit confirmation -> idempotent batched apply -> result/audit/rollback. No name-only matching, missing-record deletion, silent precedence, or credential exposure. Preserve checkout/inventory business logic.
Template version and SKU linkage must be explicit. Unrecognized columns return actionable sheet/cell errors; do not infer ambiguous fields. Approval bound to workbook digest, tenant, actor and database version; reject stale preview. Stage uploads privately/encrypted; publish no raw inventory. Retry resumes confirmed batch, never resets sold/reserved units. Rollback compare-and-set only unchanged metadata/new unsold units; never reverse later sales.
Acceptance: first upload, replay, price update, new inventory, malformed schema, partial failure/recovery, cross-tenant denial, template round-trip; production remains blocked pending tests and fresh Owner approval. UI must operate without AI/terminal.
