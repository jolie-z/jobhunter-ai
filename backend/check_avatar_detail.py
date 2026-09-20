import asyncio
from app.core.config import settings
from app.core.feishu_client import feishu_client

async def main():
    resumes = await feishu_client.fetch_bitable_records(settings.FEISHU_TABLE_ID_RESUMES)
    for r in resumes:
        field_val = r.get("fields", {}).get("照片")
        if field_val:
            print(f"Resume: {r.get('fields', {}).get('简历版本')}")
            print(f"照片 Field: {field_val}")

if __name__ == "__main__":
    asyncio.run(main())
