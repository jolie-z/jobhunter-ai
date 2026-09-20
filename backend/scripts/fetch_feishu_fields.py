#!/usr/bin/env python3
"""
获取飞书岗位表所有字段名称
运行方式：python scripts/fetch_feishu_fields.py
"""

import sys
from pathlib import Path

# 添加 backend/app 到路径
backend_dir = Path(__file__).parent.parent / "app"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import requests
import json

# 从 core 模块导入
import os
os.chdir(Path(__file__).parent.parent)
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.core.config import settings
from app.core.feishu_utils import get_tenant_access_token


def get_feishu_token(app_id, app_secret):
    """获取飞书 token"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    headers = {"Content-Type": "application/json"}
    payload = {
        "app_id": app_id,
        "app_secret": app_secret
    }
    
    response = requests.post(url, json=payload)
    data = response.json()
    
    if data.get("code") != 0:
        raise Exception(f"获取 token 失败：{data.get('msg')}")
    
    return data["tenant_access_token"]


def get_feishu_table_fields(table_id, app_token):
    """获取飞书表格的所有字段"""
    headers = {
        "Authorization": f"Bearer {get_tenant_access_token_from_env()}",
        "Content-Type": "application/json"
    }
    
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/metadata"
    
    response = requests.get(url, headers=headers)
    data = response.json()
    
    if data.get("code") != 0:
        raise Exception(f"获取表格元数据失败：{data.get('msg')}")
    
    return data.get("data", {})


def load_env_config():
    """从.env 文件加载配置 - 实际上不需要，因为 settings 已经自动读取了.env"""
    return {}


def main():
    print("="*80)
    print("📊 获取飞书岗位表字段列表")
    print("="*80)
    
    try:
        # 直接从 settings 读取配置
        table_id = settings.FEISHU_TABLE_ID_JOBS
        app_token = settings.FEISHU_APP_TOKEN
        
        if not table_id or not app_token:
            print("❌ FEISHU_TABLE_ID_JOBS 或 FEISHU_APP_TOKEN 未配置")
            print("\n请检查 backend/.env 文件中的飞书配置项")
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
            raise Exception(f"获取表格元数据失败：{data.get('msg')}")
        
        metadata = data.get("data", {})
        
        # 获取字段列表
        fields = metadata.get("field_matrix", [])
        
        if not fields:
            print("⚠️  未找到字段数据")
            return
        
        print(f"\n✅ 共找到 {len(fields)} 个字段：\n")
        
        # 打印字段列表
        print("-"*80)
        print(f"{'序号':<6} {'字段名':<40} {'类型':<20}")
        print("-"*80)
        
        for idx, field in enumerate(fields, 1):
            field_name = field.get("name", "")
            field_type = field.get("type", "").upper()
            
            # 截断过长的字段名
            if len(field_name) > 38:
                field_name = field_name[:35] + "..."
            
            print(f"{idx:<6} {field_name:<40} {field_type:<20}")
        
        print("-"*80)
        
        # 保存为 JSON 文件
        output_file = "./feishu_fields_list.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        print(f"\n💾 完整元数据已保存到：{output_file}")
        
        # 生成 CSV 格式
        csv_output = []
        csv_output.append("序号，字段名，字段类型\n")
        
        for idx, field in enumerate(fields, 1):
            field_name = field.get("name", "")
            field_type = field.get("type", "")
            csv_output.append(f'{idx},"{field_name}","{field_type}"\n')
        
        csv_file = "./feishu_fields_list.csv"
        with open(csv_file, "w", encoding="utf-8-sig") as f:
            f.writelines(csv_output)
        
        print(f"📄 CSV 格式已保存到：{csv_file}")
        print("\n✨ 完成！你可以在当前目录查看生成的文件")
        print("="*80)
        
    except Exception as e:
        print(f"\n❌ 错误：{e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
