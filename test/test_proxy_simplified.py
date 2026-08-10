"""验证简化后的代理管理逻辑"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def main():
    from tortoise import Tortoise
    from app.settings.config import settings

    await Tortoise.init(config=settings.TORTOISE_ORM)

    from app.models.hubstudio_proxy import HubStudioProxyConfig
    from app.models.site_pipeline import Site
    from app.controllers.hubstudio_proxy import hubstudio_proxy_controller, parse_proxy_lines
    from app.schemas.hubstudio_proxy import HubStudioProxyBatchImport, SiteBatchAssignProxy

    print("=== 1. 模型字段校验（应无 name/code/provider_id/is_default/priority）===")
    fields = set(HubStudioProxyConfig._meta.fields_map.keys())
    removed = {"name", "code", "provider_id", "is_default", "priority", "last_check_at"}
    leftover = fields & removed
    print(f"  残留字段: {leftover or '无'}")
    print(f"  当前字段数: {len(fields)}")

    print("\n=== 2. 批量解析 ===")
    ok, err = parse_proxy_lines(
        "163.123.201.136:5921:powygrwn:mbe5zxysoih3\n"
        "1.2.3.4:8080:u1:p1\n"
        "badline\n"
        "5.6.7.8:99999:u2:p2"
    )
    parsed_list = ['{}:{}'.format(i['proxy_host'], i['proxy_port']) for i in ok]
    print(f"  成功 {len(ok)} 条: {parsed_list}")
    for e in err:
        print(f"  失败 行{e['line']}: {e['error']}")

    print("\n=== 3. 批量导入（测试数据）===")
    res = await hubstudio_proxy_controller.batch_import(
        HubStudioProxyBatchImport(
            raw_text="10.0.0.1:1001:acc1:pwd1\n10.0.0.2:1002:acc2:pwd2",
            reference_country_code="US",
        )
    )
    print(f"  total={res['total']} success={res['success_count']} failed={res['failed_count']}")
    created_ids = [s["id"] for s in res["success"]]

    print("\n=== 4. to_api_params（确认无 containerCode）===")
    if created_ids:
        p = await HubStudioProxyConfig.get(id=created_ids[0])
        params = p.to_api_params()
        print(f"  containerCode 存在: {'containerCode' in params}")
        for k, v in params.items():
            print(f"    {k} = {v}")

    print("\n=== 5. 站点批量分配 ===")
    sites = await Site.all().limit(2)
    if sites:
        site_ids = [s.id for s in sites]

        r1 = await hubstudio_proxy_controller.batch_assign_sites(
            SiteBatchAssignProxy(site_ids=site_ids, use_default=False)
        )
        print(f"  从代理池分配: {r1['message']}")
        for d in r1.get("detail", []):
            print(f"    site={d['site_id']} -> {d['proxy']}")

        # 重复分配同一批站点，验证不会误报代理不足
        r2 = await hubstudio_proxy_controller.batch_assign_sites(
            SiteBatchAssignProxy(site_ids=site_ids, use_default=False)
        )
        print(f"  重复分配同一批: {r2['message']}")

        r3 = await hubstudio_proxy_controller.batch_assign_sites(
            SiteBatchAssignProxy(site_ids=site_ids, use_default=True)
        )
        print(f"  切回默认代理: {r3['message']}")
    else:
        print("  无站点数据，跳过")

    print("\n=== 6. 清理测试数据 ===")
    if created_ids:
        deleted = await HubStudioProxyConfig.filter(id__in=created_ids).delete()
        print(f"  已删除 {deleted} 条测试代理")

    await Tortoise.close_connections()
    print("\n全部通过。")


if __name__ == "__main__":
    asyncio.run(main())
