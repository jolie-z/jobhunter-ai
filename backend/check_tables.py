import asyncio
import httpx
from app.core.config import settings
from app.core.feishu_client import feishu_client

async def main():
    token = await feishu_client.get_tenant_access_token()
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)
        data = resp.json()
        for item in data.get("data", {}).get("items", []):
            print(f"Table Name: {item['name']}, Table ID: {item['table_id']}")

if __name__ == "__main__":
    asyncio.run(main())
