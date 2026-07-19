"""统一导入框架 — 支持 CSV / Excel 导入站点、Gmail、采集源、商品

所有导入逻辑委托给 app.services.import_service.ImportService
"""
import csv
import io

from fastapi import APIRouter, File, Query, UploadFile
from starlette.responses import Response

from app.controllers.import_job import import_job_controller
from app.schemas.base import Fail, Success, SuccessExtra
from app.services.import_service import import_service
from app.utils.db_utils import safe_count

router = APIRouter(tags=["Import"])
template_router = APIRouter(tags=["Template"])  # 无认证，模板下载用


# 模板表头定义
_TEMPLATE_HEADERS = {
    "sites": ["domain", "server_ip"],
    "gmail": ["Last name", "First name", "Full name", "Zip code",
              "Shipping address 1", "Shipping address 2", "Country", "Province/State",
              "City", "Phone", "Username", "Password", "2FA Key",
              "Link To Generate Login Code from 2FA Key", "Recovery Email"],
    "shopify_sources": ["source_url", "source_type", "max_products", "remark"],
    "shopify_products": ["product_url", "handle", "title", "vendor", "product_type", "tags"],
}

_TEMPLATE_NAMES = {
    "sites": "站点导入模板",
    "gmail": "Gmail导入模板",
    "shopify_sources": "采集源导入模板",
    "shopify_products": "商品导入模板",
}


@router.get('/list', summary='导入任务列表')
async def list_imports(import_type: str = Query(''), page: int = Query(1), page_size: int = Query(20)):
    qs = import_job_controller.model.all()
    if import_type:
        qs = qs.filter(import_type=import_type)
    total = await safe_count(qs)
    objs = await qs.order_by('-created_at').offset((page - 1) * page_size).limit(page_size)
    data = [await obj.to_dict() for obj in objs]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.post('/sites', summary='导入站点（CSV/XLSX）')
async def import_sites(file: UploadFile = File(...)):
    try:
        data = await file.read()
        result = await import_service.import_data("sites", file.filename, data)
        return Success(data=result)
    except BaseException as e:
        return Fail(code=500, msg=f"导入失败: {e}")


@router.post('/gmail', summary='导入 Gmail 账号（CSV/XLSX）')
async def import_gmail(file: UploadFile = File(...)):
    try:
        data = await file.read()
        result = await import_service.import_data("gmail", file.filename, data)
        return Success(data=result)
    except BaseException as e:
        return Fail(code=500, msg=f"导入失败: {e}")


@router.post('/shopify-sources', summary='导入 Shopify 采集源（CSV/XLSX）')
async def import_shopify_sources(file: UploadFile = File(...)):
    try:
        data = await file.read()
        result = await import_service.import_data("shopify_sources", file.filename, data)
        return Success(data=result)
    except BaseException as e:
        return Fail(code=500, msg=f"导入失败: {e}")


@router.post('/shopify-products', summary='导入 Shopify 商品（CSV/XLSX）')
async def import_shopify_products(file: UploadFile = File(...)):
    try:
        data = await file.read()
        result = await import_service.import_data("shopify_products", file.filename, data)
        return Success(data=result)
    except BaseException as e:
        return Fail(code=500, msg=f"导入失败: {e}")


@template_router.get('/template/{import_type}', summary='下载导入模板 CSV')
async def download_template(import_type: str):
    """下载指定类型的 CSV 导入模板"""
    if import_type not in _TEMPLATE_HEADERS:
        return Fail(code=404, msg=f"不支持的模板类型: {import_type}")
    headers = _TEMPLATE_HEADERS[import_type]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    if import_type == "sites":
        writer.writerow(["example.com", "127.0.0.1"])
    elif import_type == "gmail":
        writer.writerow(["Thakkar", "Kirit", "Kirit Thakkar", "60563-3726",
                         "1204 Snapper Rd", "", "US", "Illinois", "Naperville", "+1 8479628308",
                         "example@gmail.com", "password123",
                         "s6porf4qe2kmn7yl5izwp6lebkukij3d",
                         "https://2fa.dad/s6porf4qe2kmn7yl5izwp6lebkukij3d",
                         "recovery@outlook.com"])
    elif import_type == "shopify_sources":
        writer.writerow(["https://example.myshopify.com/collections/all", "collection", "100", ""])
    elif import_type == "shopify_products":
        writer.writerow(["https://example.myshopify.com/products/test", "test-handle", "Test Product", "VendorName", "T-Shirt", "red,large"])
    output.seek(0)
    content = output.getvalue().encode('utf-8-sig')
    from urllib.parse import quote
    safe_name = _TEMPLATE_NAMES.get(import_type, import_type) + ".csv"
    encoded_filename = quote(safe_name)
    return Response(
        content=content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
        }
    )
