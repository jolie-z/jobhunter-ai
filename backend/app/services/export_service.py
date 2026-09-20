"""飞书附件上传服务。

历史上这里还承载过 Word 模板渲染（docxtpl）与三件套导出流水线，
Word附件字段废弃后已整体移除，仅保留文件上传能力供 PDF/图片导出复用。
"""
from pathlib import Path

import httpx

from app.core.config import settings
from app.core.feishu_client import feishu_client


async def upload_file_to_feishu_async(file_path: Path, file_name: str = None) -> str:
    """异步并发上传文件到飞书云文档"""
    token = await feishu_client.get_tenant_access_token()
    url = "https://open.feishu.cn/open-apis/drive/v1/medias/upload_all"
    headers = {"Authorization": f"Bearer {token}"}

    display_name = file_name if file_name else file_path.name
    content_type = "application/octet-stream"
    ext = file_path.suffix.lower()
    if ext == ".docx":
        content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif ext == ".pdf":
        content_type = "application/pdf"
    elif ext in {".jpg", ".jpeg"}:
        content_type = "image/jpeg"

    data = {
        "file_name": display_name,
        "parent_type": "bitable_file",
        "parent_node": settings.FEISHU_APP_TOKEN,
        "size": str(file_path.stat().st_size),
    }

    async with httpx.AsyncClient() as client:
        with file_path.open("rb") as f:
            files = {"file": (display_name, f, content_type)}
            resp = await client.post(url, headers=headers, data=data, files=files, timeout=60.0)
            resp.raise_for_status()
            result = resp.json()

        if result.get("code") != 0:
            raise ValueError(f"上传文件失败({display_name}): {result.get('msg')}")
        return result["data"]["file_token"]
