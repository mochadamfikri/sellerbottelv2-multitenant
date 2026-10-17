"""Permanent tenant-admin workbook preflight; apply intentionally unavailable."""
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Form
from fastapi.responses import Response
from tenant_context import get_tenant_context
from v2_commerce_routes import require_tenant_operator
from idse_workbook_schema import inspect_workbook, SUMMARY_HEADERS, DESCRIPTION_HEADERS
import io
import openpyxl

router = APIRouter(prefix='/api/v2/import-excel', tags=['idse-import'],
                   dependencies=[Depends(require_tenant_operator)])


@router.post('/preview')
async def preview(file: UploadFile = File(...), summary_precedence: bool = Form(False), context=Depends(get_tenant_context), actor=Depends(require_tenant_operator)):
    if not (file.filename or '').lower().endswith('.xlsx'):
        raise HTTPException(400, 'Unggah file .xlsx')
    data = await file.read(10 * 1024 * 1024 + 1)
    try:
        from idse_semantic_preview import semantic_preview
        result = semantic_preview(data, summary_precedence=summary_precedence)
    except Exception:
        # Parser exceptions may include XML/cell contents; never echo payload.
        raise HTTPException(400, 'XLSX tidak valid atau melewati batas keamanan.') from None
    if result.get('products'):
        from idse_import_plan import compare_products
        result['database_diff'] = await compare_products(context.database, context.tenant_id, result['products'])
        from idse_import_jobs import stage_plan
        from inventory import _fernet, InventoryConfigError
        try:
            cipher = _fernet()
        except InventoryConfigError:
            raise HTTPException(503, 'Penyimpanan preview terenkripsi belum dikonfigurasi.') from None
        actor_id = actor.get('_id') or actor.get('user_id')
        if not actor_id:
            raise HTTPException(403, 'Identitas admin tidak tersedia.')
        result['plan'] = await stage_plan(context.database, context.tenant_id,
            actor_id, data, result, cipher)
    return {**result, 'tenant_id': context.tenant_id,
            'phase': 'metadata_preview', 'apply_allowed': False,
            'message': 'Preview metadata; validasi inventory dan apply belum tersedia. Tidak ada perubahan database.'}


@router.get('/template')
async def template(context=Depends(get_tenant_context)):
    workbook = openpyxl.Workbook()
    summary = workbook.active
    summary.title = 'Summary'
    summary.append(SUMMARY_HEADERS)
    description = workbook.create_sheet('Deskripsi & Aktivasi')
    description.append(DESCRIPTION_HEADERS)
    mapping = workbook.create_sheet('Panduan & Mapping')
    mapping.append(['Template version', '1-draft'])
    mapping.append(['Status', 'Draft struktur; apply belum tersedia'])
    mapping.append(['Identitas', 'SKU stabil wajib; jangan gunakan nama sebagai identitas'])
    output = io.BytesIO()
    workbook.save(output)
    return Response(output.getvalue(), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition':'attachment; filename="IDSE_Template_Structure_Draft.xlsx"',
                             'Cache-Control':'no-store'})
