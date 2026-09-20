#!/usr/bin/env python3
"""获取飞书岗位表所有字段名称 - 使用记录的 search API"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(project_root))

import requests
import json
from app.core.config import settings
from app.core.feishu_utils import get_tenant_access_token


def main():
    print("="*80)
    print("📊 获取飞书岗位表字段列表")
    print("="*80)
    
    try:
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
        
        print("\n⏳ 正在获取第一条记录以提取字段名...\n")
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        # 使用 search API 获取第一条记录
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
        
        params = {"page_size": 1}
        
        response = requests.get(url, headers=headers, params=params, timeout=30)
        
        if response.status_code != 200:
            raise Exception(f"请求失败：{response.status_code}\n{response.text}")
        
        data = response.json()
        
        if data.get("code") != 0:
            msg = data.get('msg')
            raise Exception(f"API 错误：{msg}")
        
        items = data.get("data", {}).get("items", [])
        
        if not items:
            print("⚠️  表中没有数据")
            return
        
        record = items[0]
        fields = record.get("fields", {})
        
        field_names = list(fields.keys())
        
        print(f"✅ 从第一条记录中提取到 {len(field_names)} 个字段：\n")
        
        # 打印字段列表
        print("-"*80)
        print(f"{'序号':<6} {'字段名':<40} {'值示例'}")
        print("-"*80)
        
        for idx, field_name in enumerate(field_names, 1):
            value = fields[field_name]
            
            # 格式化显示值
            if isinstance(value, dict):
                value_str = str(value.get("text", value.get("name", value.get("link", ""))))[:30]
            elif isinstance(value, list):
                if len(value) > 0:
                    item = value[0]
                    if isinstance(item, dict):
                        value_str = str(item.get("text", item.get("name", "")))[:30]
                    else:
                        value_str = str(value[0])[:30]
                else:
                    value_str = "[]"
            else:
                value_str = str(value)[:30]
            
            # 截断过长字段名
            display_name = field_name if len(field_name) <= 38 else field_name[:35] + "..."
            
            print(f"{idx:<6} {display_name:<40} {value_str}")
        
        print("-"*80)
        
        # 保存为 JSON 和 CSV
        output_file = "./feishu_fields_list.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump({
                "total_fields": len(field_names),
                "field_names": field_names,
                "sample_value": fields
            }, f, ensure_ascii=False, indent=2)
        
        print(f"\n💾 完整元数据已保存到：{output_file}")
        
        csv_output = ["序号，字段名，值示例\n"]
        
        for idx, field_name in enumerate(field_names, 1):
            value = fields[field_name]
            value_str = str(value)[:50].replace(",", ";").replace("\n", " ")
            csv_output.append(f'{idx},"{field_name}","{value_str}"\n')
        
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
