"""Google Feed 文件管理 API
- 上传 Feed 源文件
- 创建新 Feed（域名替换）
- 下载替换后的文件（按文件名路由，无需 feed_id）
"""
import logging
import os
import random
import re
import shutil
import string
import uuid
from typing import Optional

_log = logging.getLogger(__name__)

from fastapi import APIRouter, Body, Query, UploadFile, File
from fastapi.responses import FileResponse

from app.models.feed_file import FeedFile
from app.schemas.base import Fail, Success, SuccessExtra

router = APIRouter(tags=["Feed"])
feed_download_router = APIRouter()  # 公开下载路由，无需认证

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "uploads", "feeds")
os.makedirs(UPLOAD_DIR, exist_ok=True)

DEFAULT_TARGET_DOMAIN = os.getenv("FEED_DEFAULT_TARGET_DOMAIN", "")


# ═══════════════════════  工具函数  ═══════════════════════

def _random_suffix(length: int = 6) -> str:
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


def _safe_filename(original: str) -> str:
    ext = os.path.splitext(original)[1] or ".txt"
    return f"{uuid.uuid4().hex[:12]}_{_random_suffix(4)}{ext}"


def _make_processed_name(target_domain: str, ext: str) -> str:
    """生成处理后的文件名：替换后域名_随机码.扩展名（域名中的 . 改为 _）"""
    safe_domain = re.sub(r'[^a-zA-Z0-9.\-]', '_', target_domain).strip('._')
    safe_domain = safe_domain.replace('.', '_')
    return f"{safe_domain}_{_random_suffix(6)}{ext}"


def _count_and_replace_domain(file_path: str, source_domain: str, target_domain: str) -> int:
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    escaped = re.escape(source_domain)
    new_content, count = re.subn(escaped, target_domain, content)
    if count > 0:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
    return count


def _detect_domain_from_file(file_path: str, file_type: str) -> Optional[str]:
    """自动检测 Feed 文件中的主要域名"""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return None

    from collections import Counter
    found = []

    # 1. XML 标签内域名
    for pattern in [
        r'<(?:g:)?link[^>]*>\s*https?://((?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,})',
        r'<(?:g:)?image_link[^>]*>\s*https?://((?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,})',
    ]:
        found.extend(re.findall(pattern, content))

    # 2. 全局 URL
    found.extend(re.findall(
        r'https?://((?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,})',
        content,
    ))

    # 3. CSV 裸域名兜底
    if not found and file_type == "csv":
        bare = re.findall(
            r'(?<![a-zA-Z0-9\-.])((?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,})',
            content,
        )
        found.extend([d for d in bare if len(d) > 8])

    return Counter(found).most_common(1)[0][0] if found else None


def _make_download_url(filename: str) -> str:
    """根据文件名生成下载链接"""
    from urllib.parse import quote
    return f"/api/v1/site-pipeline/feed/download/{quote(filename, safe='')}"


async def _feed_row(feed) -> dict:
    d = await feed.to_dict()
    if feed.processed_file and os.path.exists(feed.processed_file):
        d["download_url"] = _make_download_url(os.path.basename(feed.processed_file))
        d["processed_name"] = os.path.basename(feed.processed_file)
    return d


# ═══════════════════════  API  ═══════════════════════


@router.post("/upload", summary="上传 Feed 源文件")
async def upload_feed(file: UploadFile = File(...)):
    if not file.filename:
        return Fail(msg="文件名不能为空")

    ext = (os.path.splitext(file.filename)[1] or "").lower()
    if ext not in (".csv", ".xml", ".txt"):
        return Fail(msg=f"不支持的文件类型: {ext}，仅支持 CSV/XML")

    feed = await FeedFile.create(
        original_name=file.filename,
        file_type=ext.lstrip("."),
        file_size=0,
        status="uploaded",
    )

    safe_name = _safe_filename(file.filename)
    dest_path = os.path.join(UPLOAD_DIR, safe_name)

    content = await file.read()
    with open(dest_path, "wb") as f:
        f.write(content)

    feed.source_file = dest_path
    feed.file_size = len(content)

    detected = _detect_domain_from_file(dest_path, ext.lstrip("."))
    if detected:
        feed.source_domain = detected

    await feed.save()
    _log.info(f"[feed] 上传: id={feed.id}, name={file.filename}, domain={detected}")

    return Success(data=await _feed_row(feed), msg="上传成功")


@router.post("/{feed_id}/create-feed", summary="创建新 Feed")
async def create_feed(
    feed_id: int,
    target_domain: str = Body("", embed=True, description="新域名"),
    source_domain: str = Body("", embed=True, description="旧域名（为空则自动检测）"),
):
    """对源文件执行域名替换，生成新 Feed 文件（新建记录，源文件保留在原列表）"""
    source = await FeedFile.filter(id=feed_id).first()
    if not source:
        return Fail(msg=f"源文件不存在: {feed_id}")
    if not source.source_file or not os.path.exists(source.source_file):
        return Fail(msg="源文件不存在")

    if not target_domain:
        target_domain = DEFAULT_TARGET_DOMAIN
    if not target_domain:
        return Fail(msg="请输入新域名，或设置 FEED_DEFAULT_TARGET_DOMAIN 环境变量")

    if not source_domain:
        source_domain = source.source_domain or _detect_domain_from_file(source.source_file, source.file_type)
    if not source_domain:
        return Fail(msg="无法自动检测旧域名，请手动指定")

    # 创建新记录
    new_feed = await FeedFile.create(
        original_name=source.original_name,
        file_type=source.file_type,
        file_size=source.file_size,
        source_domain=source_domain,
        target_domain=target_domain,
        status="replaced",
    )

    # 平铺存储，文件名 = 新域名_随机码.扩展名
    ext = f".{source.file_type}" if source.file_type else ".txt"
    processed_name = _make_processed_name(target_domain, ext)
    output_path = os.path.join(UPLOAD_DIR, processed_name)
    shutil.copy2(source.source_file, output_path)

    count = _count_and_replace_domain(output_path, source_domain, target_domain)

    new_feed.processed_file = output_path
    new_feed.replace_count = count
    await new_feed.save()

    _log.info(f"[feed] 新Feed创建: source={feed_id}, new={new_feed.id}, {source_domain}→{target_domain}, {count}处, file={processed_name}")

    return Success(data={
        **(await _feed_row(new_feed)),
        "download_url": _make_download_url(processed_name),
    }, msg=f"新 Feed 创建完成，共替换 {count} 处")


@router.get("/source-list", summary="源文件列表")
async def list_source(page: int = Query(1), page_size: int = Query(20)):
    qs = FeedFile.filter(status="uploaded")
    total = await qs.count()
    feeds = await qs.offset((page - 1) * page_size).limit(page_size).order_by("-id")
    data = [await _feed_row(f) for f in feeds]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.get("/processed-list", summary="已处理文件列表")
async def list_processed(page: int = Query(1), page_size: int = Query(20)):
    qs = FeedFile.filter(status="replaced")
    total = await qs.count()
    feeds = await qs.offset((page - 1) * page_size).limit(page_size).order_by("-id")
    data = [await _feed_row(f) for f in feeds]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@feed_download_router.get("/download/{filename}", summary="下载文件")
async def download_feed(filename: str):
    """按文件名下载，无需 feed_id"""
    target = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(target):
        return Fail(msg="文件不存在")

    return FileResponse(path=target, filename=filename, media_type="application/octet-stream")


@router.delete("/{feed_id}", summary="删除文件")
async def delete_feed(feed_id: int):
    feed = await FeedFile.filter(id=feed_id).first()
    if not feed:
        return Fail(msg=f"文件不存在: {feed_id}")

    # 删除平铺的文件
    for fpath in (feed.source_file, feed.processed_file):
        if fpath and os.path.exists(fpath):
            os.remove(fpath)
            _log.info(f"[feed] 删除文件: {fpath}")

    await feed.delete()
    _log.info(f"[feed] 已删除记录: id={feed_id}")
    return Success(msg="已删除")


@router.get("/config/default-domain", summary="获取默认替换域名")
async def get_default_domain():
    return Success(data={"domain": DEFAULT_TARGET_DOMAIN})
