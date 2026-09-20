#!/usr/bin/env python3
"""调试脚本 - 直接打印 API 响应"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(project_root))

import requests
from app.core.config import settings
from app.core.feishu_utils import get_tenant_access_token


def main():
    print("获取 Token...")
    token = get_tenant_access_token()
    
    table_id = settings.FEISHU_TABLE_ID_JOBS
    app_token = settings.FEISHU_APP_TOKEN
    
    print(f"表 ID: {table_id}")
    print(f"App Token: {app_token[:20]}...")
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/metadata"
    
    print(f"\n请求 URL: {url}")
    
    response = requests.get(url, headers=headers, timeout=30)
    
    print(f"\n状态码：{response.status_code}")
    print(f"响应头：{response.headers}")
    print(f"\n原始响应内容:")
    print(response.text)
    
    try:
        data = response.json()
        print(f"\n✅ JSON 解析成功！")
        print(data)
    except Exception as e:
        print(f"\n❌ JSON 解析失败：{e}")


if __name__ == "__main__":
    main()
