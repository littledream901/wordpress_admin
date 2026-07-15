"""Google Feed 文件管理 API
- 上传 Feed 源文件
- 创建新 Feed（域名替换）
- 下载替换后的文件（按文件名路由，无需 feed_id）
- 处理后的文件默认 3 天后过期自动删除
"""
import logging
import os
import random
import re
import shutil
import string
import uuid
from datetime import datetime, timedelta
from typing import Optional

_log = logging.getLogger(__name__)

from fastapi import APIRouter, Body, Query, UploadFile, File
from fastapi.responses import FileResponse

from app.models.feed_file import FeedFile
from app.schemas.base import Fail, Success, SuccessExtra

router = APIRouter(tags=["Feed"])
feed_download_router = APIRouter()  # 公开下载路由，无需认证

# feed.py → app/api/v1/site_pipeline/ → 5层到项目根目录
_UPLOAD_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
UPLOAD_DIR = os.path.join(_UPLOAD_BASE, "uploads", "feeds")
CHUNK_DIR = os.path.join(UPLOAD_DIR, "chunks")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(CHUNK_DIR, exist_ok=True)
CHUNK_SIZE = 5 * 1024 * 1024  # 5MB per chunk

DEFAULT_TARGET_DOMAIN = os.getenv("FEED_DEFAULT_TARGET_DOMAIN", "")
# feed_expire_days 优先读 provider 配置，回退到环境变量
FEED_EXPIRE_DAYS_DEFAULT = int(os.getenv("FEED_EXPIRE_DAYS", "3"))


async def _get_feed_expire_days() -> int:
    """从 pipeline provider 配置读取有效期，回退到环境变量"""
    try:
        from app.utils.provider_resolver import ProviderResolver
        val = ProviderResolver.sync_get_config("pipeline", "feed_expire_days")
        if val is not None:
            return int(val)
    except Exception:
        pass
    return FEED_EXPIRE_DAYS_DEFAULT


# ═══════════════════════  工具函数  ═══════════════════════

def _random_suffix(length: int = 6) -> str:
    return ''.join(random.choices(string.digits, k=length))


def _safe_filename(original: str) -> str:
    ext = os.path.splitext(original)[1] or ".txt"
    return f"{uuid.uuid4().hex[:12]}_{_random_suffix(4)}{ext}"


def _make_processed_name(target_domain: str, ext: str) -> str:
    """生成处理后的文件名：替换后域名_随机数字码.扩展名（域名中的 . 改为 _）"""
    safe_domain = re.sub(r'[^a-zA-Z0-9.\-]', '_', target_domain).strip('._')
    safe_domain = safe_domain.replace('.', '_')
    return f"{safe_domain}_{_random_suffix(8)}{ext}"


def _detect_platform(content: str) -> str:
    """识别 Feed 来源平台类型，用于决定域名替换策略。
    - wordpress: 产品图在同域名下（/wp-content/uploads/），需一起替换
    - shopify:   图片在 CDN（cdn.shopify.com），不替换
    - shopoem:   图片在外部 CDN（moncontentcache 等），不替换
    - generic:   无法识别，保守策略只替换产品链接
    """
    # 取前 500KB 分析，避免大文件性能问题
    sample = content[:500000]

    # Shopify: /products/ 路径 + cdn.shopify.com 图片
    if re.search(r'/products/', sample) and re.search(r'cdn\.shopify\.com', sample):
        return "shopify"

    # WordPress/WooCommerce: /product/ 路径 + wp-content/uploads 图片路径
    if re.search(r'/product/', sample) and re.search(r'/wp-content/uploads/', sample):
        return "wordpress"

    # ShopOem: /products/ 路径 + moncontentcache 或其他 CDN 图片
    if re.search(r'/products/', sample) and re.search(r'moncontentcache', sample):
        return "shopoem"

    # 通用判别的二级特征
    if re.search(r'/wp-content/', sample):
        return "wordpress"

    if re.search(r'cdn\.shopify\.com|myshopify\.com', sample):
        return "shopify"

    if re.search(r'moncontentcache|cdn\d*\.', sample):
        return "shopoem"

    return "generic"


# 各平台的替换标签规则（正则中的捕获组名，长标签在前）
_PLATFORM_TAG_PATTERNS = {
    # WordPress: 图片在同域名，需要一起替换
    "wordpress": r'<(g:canonical_link|canonical_link|g:additional_image_link|additional_image_link|g:image_link|image_link|g:link|link)([\s>]).*?</\1>',

    # Shopify / ShopOem: 图片在 CDN，不替换图片标签
    "shopify":  r'<(g:canonical_link|canonical_link|g:link|link)([\s>]).*?</\1>',
    "shopoem":  r'<(g:canonical_link|canonical_link|g:link|link)([\s>]).*?</\1>',

    # Generic: 保守策略
    "generic":  r'<(g:canonical_link|canonical_link|g:link|link)([\s>]).*?</\1>',
}


def _count_and_replace_domain(file_path: str, source_domain: str, target_domain: str, file_type: str = "xml") -> int:
    """替换 Feed 文件中的域名。
    先识别平台，再根据平台策略替换不同标签。
    - XML: 按平台标签策略替换
    - CSV: 全局替换
    """
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    count = 0
    escaped = re.escape(source_domain)

    if file_type == "xml":
        platform = _detect_platform(content)
        tag_pattern = _PLATFORM_TAG_PATTERNS.get(platform, _PLATFORM_TAG_PATTERNS["generic"])

        def _replace_in_tag(m):
            nonlocal count
            tag_text = m.group(0)
            new_text, n = re.subn(escaped, target_domain, tag_text)
            count += n
            return new_text

        content = re.sub(
            tag_pattern,
            _replace_in_tag,
            content,
            flags=re.DOTALL,
        )
        _log.info(f"[feed] 平台={platform}, 替换域名 {source_domain} -> {target_domain}, {count} 处")
    else:
        # CSV: 全局替换
        new_content, count = re.subn(escaped, target_domain, content)
        content = new_content
        _log.info(f"[feed] CSV 全局替换域名 {source_domain} -> {target_domain}, {count} 处")

    if count > 0:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
    return count


# 已知 CDN 域名特征，检测时排除
_CDN_PATTERNS = [re.compile(p) for p in [
    r'^cdn\d*\.',           # cdn.xxx  /  cdn1.xxx
    r'\.cloudfront\.net$',
    r'\.cdn\d*\.',
    r'moncontentcache\.',   # 用户 feed 中的 CDN
]]


def _is_cdn_domain(domain: str) -> bool:
    return any(p.search(domain) for p in _CDN_PATTERNS)


def _detect_domain_from_file(file_path: str, file_type: str) -> Optional[str]:
    """自动检测 Feed 文件中的主要域名（排除 CDN）"""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return None

    from collections import Counter
    found = []

    # 1. <link> / <g:link> 标签中的域名（产品链接，最可靠）
    for pattern in [
        r'<(?:g:)?link[^>]*>\s*https?://((?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,})',
    ]:
        found.extend(re.findall(pattern, content))

    # 2. 如果用 link 标签没找到，再匹配全局 URL（排除 image_link 中的）
    if not found:
        # 先去掉 image_link 标签内容，只从非图片链接中检测
        no_images = re.sub(r'<(?:g:)?image_link[^>]*>.*?</(?:g:)?image_link>', '', content, flags=re.DOTALL)
        found.extend(re.findall(
            r'https?://((?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,})',
            no_images,
        ))

    # 3. CSV 裸域名兜底
    if not found and file_type == "csv":
        bare = re.findall(
            r'(?<![a-zA-Z0-9\-.])((?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,})',
            content,
        )
        found.extend([d for d in bare if len(d) > 8])

    # 排除 CDN 域名
    found = [d for d in found if not _is_cdn_domain(d)]

    return Counter(found).most_common(1)[0][0] if found else None


def _make_download_url(filename: str) -> str:
    """根据文件名生成下载链接"""
    from urllib.parse import quote
    return f"/api/v1/site-pipeline/feed/download/{quote(filename, safe='')}"


async def _feed_row(feed) -> dict:
    d = await feed.to_dict()
    d["is_expired"] = feed.is_expired
    d["expires_in_minutes"] = feed.expires_in_minutes
    if feed.processed_file and os.path.exists(feed.processed_file):
        d["download_url"] = _make_download_url(os.path.basename(feed.processed_file))
        d["processed_name"] = os.path.basename(feed.processed_file)
    # 检测平台类型
    fpath = feed.source_file or feed.processed_file or ""
    if fpath and os.path.exists(fpath):
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                d["platform"] = _detect_platform(f.read(500000))
        except Exception:
            d["platform"] = ""
    else:
        d["platform"] = ""
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

    # 创建新记录（设置过期时间）
    expire_days = await _get_feed_expire_days()
    new_feed = await FeedFile.create(
        original_name=source.original_name,
        file_type=source.file_type,
        file_size=source.file_size,
        source_domain=source_domain,
        target_domain=target_domain,
        status="replaced",
        expires_at=datetime.now() + timedelta(days=expire_days),
    )

    # 平铺存储，文件名 = 新域名_随机码.扩展名
    ext = f".{source.file_type}" if source.file_type else ".txt"
    processed_name = _make_processed_name(target_domain, ext)
    output_path = os.path.join(UPLOAD_DIR, processed_name)
    shutil.copy2(source.source_file, output_path)

    count = _count_and_replace_domain(output_path, source_domain, target_domain, source.file_type)

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
    """按文件名下载，校验过期时间"""
    target = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(target):
        return Fail(msg="文件不存在")

    # 查 FeedFile 记录校验过期
    feed = await FeedFile.filter(processed_file=target).first()
    if feed and feed.is_expired:
        return Fail(msg="文件已过期，无法下载")

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


@router.post("/cleanup", summary="清理过期文件")
async def cleanup_expired():
    """清理已过期的处理文件及其记录"""
    expired = await FeedFile.filter(
        status="replaced",
        expires_at__isnull=False,
        expires_at__lt=datetime.now(),
    ).all()

    deleted_count = 0
    for feed in expired:
        for fpath in (feed.processed_file,):
            if fpath and os.path.exists(fpath):
                os.remove(fpath)
        await feed.delete()
        deleted_count += 1

    _log.info(f"[feed] 清理过期文件: {deleted_count} 个")
    return Success(data={"deleted": deleted_count}, msg=f"已清理 {deleted_count} 个过期文件")


# ═══════════════════════  分片上传  ═══════════════════════

import json as _json


def _session_path(upload_id: str) -> str:
    return os.path.join(CHUNK_DIR, upload_id)


def _meta_path(upload_id: str) -> str:
    return os.path.join(_session_path(upload_id), "meta.json")


@router.post("/chunk/init", summary="初始化分片上传")
async def chunk_init(
    filename: str = Body(...),
    total_size: int = Body(...),
    total_chunks: int = Body(...),
):
    """初始化分片上传会话，返回 upload_id"""
    ext = (os.path.splitext(filename)[1] or "").lower()
    if ext not in (".csv", ".xml", ".txt"):
        return Fail(msg=f"不支持的文件类型: {ext}，仅支持 CSV/XML/TXT")

    upload_id = uuid.uuid4().hex
    session_dir = _session_path(upload_id)
    os.makedirs(session_dir, exist_ok=True)

    meta = {
        "filename": filename,
        "total_size": total_size,
        "total_chunks": total_chunks,
        "uploaded_chunks": [],
    }
    with open(_meta_path(upload_id), "w") as f:
        _json.dump(meta, f)

    _log.info(f"[feed] 分片上传初始化: id={upload_id}, file={filename}, chunks={total_chunks}")
    return Success(data={"upload_id": upload_id})


@router.post("/chunk/upload", summary="上传分片")
async def chunk_upload(
    upload_id: str = Body(...),
    chunk_index: int = Body(...),
    chunk: UploadFile = File(...),
):
    """上传单个分片"""
    session_dir = _session_path(upload_id)
    if not os.path.exists(session_dir):
        return Fail(msg="上传会话不存在或已过期")

    chunk_path = os.path.join(session_dir, str(chunk_index))
    content = await chunk.read()
    with open(chunk_path, "wb") as f:
        f.write(content)

    # 更新元数据
    meta_file = _meta_path(upload_id)
    if os.path.exists(meta_file):
        with open(meta_file, "r") as f:
            meta = _json.load(f)
        if chunk_index not in meta["uploaded_chunks"]:
            meta["uploaded_chunks"].append(chunk_index)
        with open(meta_file, "w") as f:
            _json.dump(meta, f)

    return Success(data={"chunk_index": chunk_index, "uploaded": len(meta.get("uploaded_chunks", []))})


@router.post("/chunk/complete", summary="合并分片完成上传")
async def chunk_complete(upload_id: str = Body(..., embed=True)):
    """合并所有分片，创建 FeedFile 记录"""
    session_dir = _session_path(upload_id)
    meta_file = _meta_path(upload_id)

    if not os.path.exists(meta_file):
        return Fail(msg="上传会话不存在或已过期")

    with open(meta_file, "r") as f:
        meta = _json.load(f)

    total_chunks = meta["total_chunks"]
    uploaded = meta["uploaded_chunks"]
    if len(uploaded) < total_chunks:
        missing = [i for i in range(total_chunks) if i not in uploaded]
        return Fail(msg=f"分片不完整，缺少 {len(missing)} 个分片: {missing[:5]}...")

    filename = meta["filename"]
    ext = (os.path.splitext(filename)[1] or "").lower()

    # 创建 FeedFile 记录
    feed = await FeedFile.create(
        original_name=filename,
        file_type=ext.lstrip("."),
        file_size=0,
        status="uploaded",
    )

    # 合并分片
    safe_name = _safe_filename(filename)
    dest_path = os.path.join(UPLOAD_DIR, safe_name)
    total_bytes = 0
    with open(dest_path, "wb") as out:
        for i in range(total_chunks):
            chunk_path = os.path.join(session_dir, str(i))
            with open(chunk_path, "rb") as cin:
                total_bytes += out.write(cin.read())

    feed.source_file = dest_path
    feed.file_size = total_bytes

    # 检测域名
    detected = _detect_domain_from_file(dest_path, ext.lstrip("."))
    if detected:
        feed.source_domain = detected

    await feed.save()

    # 清理分片临时目录
    shutil.rmtree(session_dir, ignore_errors=True)

    _log.info(f"[feed] 分片上传完成: id={feed.id}, file={filename}, size={total_bytes}, domain={detected}")
    return Success(data=await _feed_row(feed), msg="上传成功")
