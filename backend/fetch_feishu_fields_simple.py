#!/usr/bin/env python3
"""
获取飞书岗位表所有字段名称
运行方式：python fetch_feishu_fields_simple.py
"""

import sys
from pathlib import Path

# 添加正确的路径
project_root = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(project_root))

import requests
import json


def get_tenant_access_token():
    """获取飞书 token"""
    from app.core.config import settings
    
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    
    import time
    _token_cache = {"token": None, "expires_at": 0}
    current_time = time.time()
    
    if _token_cache["token"] and current_time < _token_cache["expires_at"] - 300:
        return _token_cache["token"]
    
    resp = requests.post(
        url,
        json={"app_id": settings.FEISHU_APP_ID, "app_secret": settings.FEISHU_APP_SECRET},
        timeout=15
    )
    resp.raise_for_status()
    data = resp.json()
    
    if data.get("code") != 0:
        msg = data.get('msg', 'unknown')
        raise Exception(f"飞书鉴权失败：{msg}")
        
    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expires_at"] = current_time + data.get("expire", 7200)
    return _token_cache["token"]


def main():
    print("="*80)
    print("📊 获取飞书岗位表字段列表")
    print("="*80)
    
    try:
        from app.core.config import settings
        
        table_id = settings.FEISHU_TABLE_ID_JOBS
        app_token = settings.FEISHU_APP_TOKEN
        
        if not table_id or not app_token:
            print("❌ FEISHU_TABLE_ID_JOBS 或 FEISHU_APP_TOKEN 未配置")
            return
        
        print(f"\n📋 表 ID: {table_id}")
        print(f"🔑 App Token: {app_token[:20]}...")
        
        print("\n⏳ 正在获取 Token...")
        token = get_tenant_access_token()
        print(f"✅ Token 获取成功！")
        
        print("\n⏳ 正在获取字段信息...")
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/metadata"
        
        response = requests.get(url, headers=headers, timeout=30)
        data = response.json()
        
        if data.get("code") != 0:
            msg = data.get('msg')
            raise Exception(f"获取表格元数据失败：{msg}")
        
        metadata = data.get("data", {})
        fields = metadata.get("field_matrix", [])
        
        if not fields:
            print("⚠️  未找到字段数据")
            return
        
        print(f"\n✅ 共找到 {len(fields)} 个字段：\n")
        
        print("-"*80)
        print(f"{'序号':<6} {'字段名':<40} {'类型':<20}")
        print("-"*80)
        
        for idx, field in enumerate(fields, 1):
            field_name = field.get("name", "")
            field_type = field.get("type", "").upper()
            
            if len(field_name) > 38:
                field_name = field_name[:35] + "..."
            
            print(f"{idx:<6} {field_name:<40} {field_type:<20}")
        
        print("-"*80)
        
        # 保存为 JSON 和 CSV
        output_file = "./feishu_fields_list.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        print(f"\n💾 完整元数据已保存到：{output_file}")
        
        csv_output = ["序号，字段名，字段类型\n"]
        
        for idx, field in enumerate(fields, 1):
            field_name = field.get("name", "")
            field_type = field.get("type", "")
            csv_output.append(f'{idx},"{field_name}","{field_type}"\n')
        
        csv_file = "./feishu_fields_list.csv"
        with open(csv_file, "w", encoding="utf-8-sig") as f:
            f.writelines(csv_output)
        
        print(f"📄 CSV 格式已保存到：{csv_file}")
        print("\n✨ 完成！")
        print("="*80)
        
    except Exception as e:
        print(f"\n❌ 错误：{e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
