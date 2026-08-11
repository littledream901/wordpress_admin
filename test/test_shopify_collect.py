"""测试 Shopify 采集 - 检查实际响应内容"""
import asyncio
import json
import httpx

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

async def test_url(label: str, url: str):
    print(f"\n{'='*80}")
    print(f"[{label}] {url}")
    print(f"{'='*80}")
    async with httpx.AsyncClient(http2=True, headers=REQUEST_HEADERS, follow_redirects=True) as client:
        try:
            resp = await client.get(url, timeout=30.0)
            print(f"状态码: {resp.status_code}")
            print(f"Content-Type: {resp.headers.get('content-type', 'N/A')}")
            try:
                data = resp.json()
                if 'product' in data:
                    p = data['product']
                    print(f"✓ 单品 JSON 解析成功: title={p.get('title')}, handle={p.get('handle')}")
                elif 'products' in data:
                    print(f"✓ 集合 JSON 解析成功: 产品数量={len(data['products'])}")
                else:
                    print(f"✓ JSON 解析成功，keys: {list(data.keys())}")
            except Exception as e:
                print(f"✗ JSON 解析失败: {e}")
                print(f"前 300 字符: {resp.text[:300]}")
        except Exception as e:
            print(f"✗ 请求失败: {e}")

async def main():
    test_cases = [
        # 单品页（源 URL）
        ("单品-源URL", "https://jonathanadler.com/products/us-soho-sofa-cumulus-smoke-35609"),
        # 单品 API 地址（加 .json）
        ("单品-API URL", "https://jonathanadler.com/products/us-soho-sofa-cumulus-smoke-35609.json"),
    ]
    for label, url in test_cases:
        await test_url(label, url)
        await asyncio.sleep(0.5)

if __name__ == "__main__":
    asyncio.run(main())
