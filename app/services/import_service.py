"""
统一导入服务 (ImportService)

提供 CSV/XLSX 文件解析、字段映射、去重、批量写入、错误报告生成等能力。
"""
from __future__ import annotations

import csv
import io
import json
import traceback
from typing import Optional

from app.controllers.import_job import import_job_controller
from app.models.gmail_account import GmailAccount
from app.models.import_job import ImportJob
from app.models.shopify_collect import ShopifyProduct, ShopifySource
from app.models.site_pipeline import Site

# 各导入类型的字段映射（CSV列名 → 模型字段名）
FIELD_MAPS = {
    "sites": {
        "domain": "domain", "Domain": "domain", "域名": "domain",
        "server_ip": "server_ip", "server ip": "server_ip", "ip": "ip",
        "IP": "server_ip", "服务器IP": "server_ip",
    },
    "gmail": {
        "username": "username", "Username": "username", "Email": "username",
        "password": "password", "Password": "password", "密码": "password",
        "last_name": "last_name", "last name": "last_name",
        "first_name": "first_name", "first name": "first_name",
        "full_name": "full_name", "full name": "full_name",
        "zip_code": "zip_code", "zip code": "zip_code", "zip": "zip_code",
        "shipping_address_1": "shipping_address_1", "Shipping address 1": "shipping_address_1",
        "shipping_address_2": "shipping_address_2", "Shipping address 2": "shipping_address_2",
        "country": "country", "Country": "country", "国家": "country",
        "province_state": "province_state", "Province/State": "province_state", "省份": "province_state",
        "city": "city", "City": "city", "城市": "city",
        "phone": "phone", "Phone": "phone", "电话": "phone",
        "two_fa_key": "two_fa_key", "2FA Key": "two_fa_key", "2fa": "two_fa_key",
        "link_to_generate_login_code": "link_to_generate_login_code",
        "Link To Generate Login Code from 2FA Key": "link_to_generate_login_code",
        "recovery_email": "recovery_email", "Recovery Email": "recovery_email",
    },
    "shopify_sources": {
        "source_url": "source_url", "url": "source_url", "shopify url": "source_url",
        "source_type": "source_type", "type": "source_type", "类型": "source_type",
        "max_products": "max_products", "max products": "max_products", "最大数量": "max_products",
        "remark": "remark", "备注": "remark",
    },
    "shopify_products": {
        "product_url": "product_url", "product url": "product_url",
        "handle": "handle", "title": "title", "标题": "title",
        "vendor": "vendor", "product_type": "product_type", "类型": "product_type",
        "tags": "tags", "标签": "tags",
    },
}

# 各导入类型对应的唯一键字段
_UNIQUE_KEYS = {
    "sites": "domain",
    "gmail": "username",
    "shopify_sources": "source_url",
    "shopify_products": "product_url",
}


class ImportService:
    """统一导入服务"""

    # ── 文件解析 ──

    @staticmethod
    def parse_csv(content: str) -> list[dict]:
        """解析 CSV 文本"""
        reader = csv.DictReader(io.StringIO(content))
        return [row for row in reader]

    @staticmethod
    def parse_xlsx(data: bytes) -> list[dict]:
        """解析 XLSX 文件"""
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(h).strip() if h else "" for h in rows[0]]
        result = []
        for row in rows[1:]:
            record = {}
            for i, cell in enumerate(row):
                if i < len(headers) and headers[i]:
                    record[headers[i]] = str(cell).strip() if cell is not None else ""
            if any(v for v in record.values()):
                result.append(record)
        return result

    @staticmethod
    def parse_file(filename: str, data: bytes) -> list[dict]:
        """根据文件名自动选择解析器"""
        if filename.endswith('.xlsx'):
            return ImportService.parse_xlsx(data)
        else:
            return ImportService.parse_csv(data.decode("utf-8-sig"))

    # ── 字段映射 ──

    @staticmethod
    def map_fields(raw: dict, field_map: dict) -> dict:
        """按字段映射表转换原始行（大小写不敏感匹配）"""
        # 构建 small_case → model_field 索引
        _ci_map = {k.lower(): v for k, v in field_map.items()}
        _ci_keys = set(_ci_map.keys())
        result = {}
        for key, value in raw.items():
            cleaned = key.strip().lower()
            if cleaned in _ci_keys:
                result[_ci_map[cleaned]] = value.strip()
        return result

    # ── 数据校验与类型转换 ──

    @staticmethod
    def _apply_type_conversion(import_type: str, mapped: dict) -> dict:
        """进行必要的类型转换"""
        if import_type == "shopify_sources" and "max_products" in mapped:
            try:
                mapped["max_products"] = int(mapped["max_products"]) if mapped["max_products"] else 0
            except ValueError:
                mapped["max_products"] = 0
        return mapped

    # ── 执行导入 ──

    @staticmethod
    async def import_data(
        import_type: str,
        filename: str,
        file_data: bytes,
    ) -> dict:
        """执行完整导入流程，返回 {job_id, success, fail, total, errors}"""
        # 1. 格式校验
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        if ext not in ('csv', 'xlsx'):
            raise ValueError(f"不支持的文件格式: .{ext}，仅支持 .csv .xlsx")

        # 2. 创建导入任务并标记为处理中
        job = await import_job_controller.create(obj_in={
            "import_type": import_type,
            "file_name": filename,
        })
        await ImportJob.filter(id=job.id).update(status="processing")

        try:
            result = await ImportService._process_rows(job.id, import_type, filename, file_data)
        except Exception as e:
            # 确保任何异常都触发 finish，避免 status 卡在 processing
            await import_job_controller.finish(
                job.id, 0, 0,
                json.dumps([{"error": str(e), "traceback": traceback.format_exc()}], ensure_ascii=False)
            )
            raise
        return result

    @staticmethod
    async def _process_rows(
        job_id: int,
        import_type: str,
        filename: str,
        file_data: bytes,
    ) -> dict:
        """核心处理逻辑，解析文件并逐行写入"""

        # 3. 解析文件
        rows = ImportService.parse_file(filename, file_data)
        if not rows:
            await import_job_controller.finish(job_id, 0, 0, "空文件或无有效数据")
            return {"id": job_id, "success": 0, "fail": 0, "total": 0, "errors": []}

        # 4. 获取模型和字段映射
        model_cls = ImportService._get_model(import_type)
        field_map = FIELD_MAPS.get(import_type, {})
        unique_key = _UNIQUE_KEYS.get(import_type)

        success = 0
        failures: list[dict] = []

        for i, row in enumerate(rows):
            try:
                mapped = ImportService.map_fields(row, field_map)
                if not mapped:
                    failures.append({"row": i + 1, "field": "", "error": "无可映射字段"})
                    continue

                # 去重检查
                if unique_key and mapped.get(unique_key):
                    existing = await model_cls.filter(**{unique_key: mapped[unique_key]}).first()
                    if existing:
                        failures.append({"row": i + 1, "field": "", "error": "已存在（跳过）"})
                        continue

                # 类型转换
                mapped = ImportService._apply_type_conversion(import_type, mapped)

                await model_cls.create(**mapped)
                success += 1
            except Exception as e:
                failures.append({"row": i + 1, "field": "", "error": str(e)})

        # 5. 完成任务
        await import_job_controller.finish(
            job_id, success, len(failures),
            json.dumps(failures, ensure_ascii=False) if failures else ""
        )

        return {
            "id": job_id,
            "success": success,
            "fail": len(failures),
            "total": len(rows),
            "errors": failures[:20],
        }

    # ── 辅助 ──

    @staticmethod
    def _get_model(import_type: str):
        """根据导入类型返回对应模型"""
        models = {
            "sites": Site,
            "gmail": GmailAccount,
            "shopify_sources": ShopifySource,
            "shopify_products": ShopifyProduct,
        }
        if import_type not in models:
            raise ValueError(f"不支持的导入类型: {import_type}")
        return models[import_type]

    @staticmethod
    def get_field_map(import_type: str) -> dict:
        """获取某类型的字段映射表"""
        return FIELD_MAPS.get(import_type, {})

    @staticmethod
    def preview(filename: str, file_data: bytes, max_rows: int = 10) -> list[dict]:
        """预览导入文件的前 N 行（仅解析，不写入）"""
        rows = ImportService.parse_file(filename, file_data)
        return rows[:max_rows]


# 全局单例
import_service = ImportService()
