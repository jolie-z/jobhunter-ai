import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
from app.core.feishu_client import feishu_client
from app.core.config import settings

async def main():
    token = await feishu_client.get_tenant_access_token()
    import httpx
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_JOBS}/fields"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        print([item["field_name"] for item in resp.json().get("data", {}).get("items", [])])

asyncio.run(main())
