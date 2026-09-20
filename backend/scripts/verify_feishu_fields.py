#!/usr/bin/env python3
"""
飞书字段验证工具
用于深度检查特定字段是否在代码中被实际引用
"""

import re
import os
from pathlib import Path
from collections import defaultdict


def check_field_usage(field_name, backend_dir=None):
    """
    深度检查某个字段的使用情况
    
    Args:
        field_name: 要检查的字段名（支持部分匹配）
        backend_dir: 后端目录路径
    
    Returns:
        dict: 包含详细信息的结果
    """
    
    if backend_dir is None:
        # 从 scripts 目录向上两级到达 project root，然后进入 backend/app
        script_dir = Path(__file__).resolve().parent
        backend_dir = script_dir / ".." / "app"
        backend_dir = backend_dir.resolve()
    
    print(f"🔍 检查目录：{backend_dir}")
    
    if not backend_dir.exists():
        return {"error": f"找不到目录：{backend_dir}"}
    
    results = {
        "field_name": field_name,
        "exact_matches": [],
        "partial_matches": [],
        "total_count": 0,
        "files_checked": 0
    }
    
    # 遍历所有 Python 文件
    for py_file in backend_dir.rglob("*.py"):
        try:
            content = py_file.read_text(encoding="utf-8")
            lines = content.split('\n')
            
            for line_num, line in enumerate(lines, 1):
                # 精确匹配（排除配置类的字段）
                exact_pattern = rf'["\']{{0,2}}{re.escape(field_name)}["\']{{0,2}}'
                
                matches = list(re.finditer(exact_pattern, line))
                
                if matches:
                    # 跳过一些配置相关的模式
                    skip_keywords = [
                        'filter', 'page_size', 'page_token', 
                        'conditions', 'conjunction', 'operator', 
                        'value', 'field_name', 'authorization',
                        'content-type', 'receive_id_type'
                    ]
                    
                    if any(kw in line.lower() for kw in skip_keywords):
                        continue
                    
                    rel_path = py_file.relative_to(backend_dir)
                    context = line.strip()
                    
                    result_item = {
                        "file": str(rel_path),
                        "line": line_num,
                        "context": context,
                        "match_type": "exact" if field_name in line else "partial"
                    }
                    
                    if match_type := "exact" if field_name in line else "partial":
                        if match_type == "exact":
                            results["exact_matches"].append(result_item)
                        else:
                            results["partial_matches"].append(result_item)
                    
                    results["total_count"] += 1
            
            results["files_checked"] += 1
            
        except Exception as e:
            print(f"⚠️ 读取 {py_file} 失败：{e}")
    
    return results


def batch_check_fields(field_list, backend_dir=None):
    """批量检查多个字段"""
    
    results = {}
    for field in field_list:
        print(f"🔍 正在检查字段：{field}")
        results[field] = check_field_usage(field, backend_dir)
    
    return results


def print_detailed_report(results):
    """打印详细报告"""
    
    for field_name, result in results.items():
        if "error" in result:
            print(f"\n❌ {field_name}: {result['error']}")
            continue
        
        total = result["total_count"]
        exact = len(result["exact_matches"])
        partial = len(result["partial_matches"])
        
        print(f"\n{'='*80}")
        print(f"📋 字段：{field_name}")
        print(f"{'='*80}")
        print(f"总匹配次数：{total}")
        print(f"  - 精确匹配：{exact} 次")
        print(f"  - 模糊匹配：{partial} 次")
        
        if exact > 0:
            print(f"\n✅ 精确匹配位置:")
            for item in sorted(result["exact_matches"], key=lambda x: (x["file"], x["line"]))[:5]:
                print(f"   📄 {item['file']}:{item['line']}")
                print(f"      → {item['context'][:80]}")
            
            if len(result["exact_matches"]) > 5:
                print(f"   ... 还有{len(result['exact_matches']) - 5}处")
        
        if partial > 0:
            print(f"\n⚠️  模糊匹配位置:")
            for item in sorted(result["partial_matches"], key=lambda x: (x["file"], x["line"]))[:3]:
                print(f"   📄 {item['file']}:{item['line']}")
                print(f"      → {item['context'][:80]}")
            
            if len(result["partial_matches"]) > 3:
                print(f"   ... 还有{len(result['partial_matches']) - 3}处")
        
        # 判断建议
        print(f"\n💡 建议:")
        if total == 0:
            print(f"   ⚠️  未找到任何引用，可考虑删除")
        elif exact == 0 and partial > 0:
            print(f"   ⚠️  只有模糊匹配，建议人工确认")
        elif exact > 0:
            print(f"   ✅ 有实际引用，请勿删除")
            if exact <= 2:
                print(f"   💭 引用较少，可能可以合并或重构")


def main():
    """主函数"""
    
    print("="*80)
    print("🔍 飞书字段深度验证工具")
    print("="*80)
    
    # 要检查的字段列表（根据分析报告中的可疑字段）
    suspicious_fields = [
        # 权重评分字段
        "低权 - 招聘周期",
        "中权 - 工作模式",
        "中权 - 公司阶段",
        "中权 - 赛道前景",
        "中权 - 成长空间",
        "高权 - 职级资历",
        "高权 - 薪资契合",
        "高权 - 面试概率",
        
        # 简历历史字段
        "教育背景",
        "工作经历",
        "项目经验",
        "技能清单",
        "自我评价",
        "求职意向",
        "手动精修版简历",
        
        # AI 评估打分
        "减分词",
        "初步打分",
        "加分词",
        "核心 - 角色匹配",
        "综合评级",
        
        # 其他
        "附件",
        "优先级",
        "候选人状态",
        "我的复核",
        "猎头推荐语",
        "猎头备注",
        "是否外包",
    ]
    
    backend_dir = Path(__file__).parent / "app"
    
    # 批量检查
    results = batch_check_fields(suspicious_fields, backend_dir)
    
    # 打印报告
    print_detailed_report(results)
    
    # 生成总结
    print("\n\n" + "="*80)
    print("📊 总结")
    print("="*80)
    
    can_delete = []
    keep_checking = []
    must_keep = []
    
    for field_name, result in results.items():
        if "error" in result:
            continue
        
        exact = len(result["exact_matches"])
        
        if exact == 0:
            can_delete.append(field_name)
        elif exact <= 2:
            keep_checking.append(field_name)
        else:
            must_keep.append(field_name)
    
    print(f"\n🗑️  可安全删除的字段 ({len(can_delete)}个):")
    for field in sorted(can_delete):
        print(f"   ├─ {field}")
    
    print(f"\n⚠️  需进一步确认的字段 ({len(keep_checking)}个):")
    for field in sorted(keep_checking):
        count = len(results[field]["exact_matches"])
        print(f"   ├─ {field} (引用{count}次)")
    
    print(f"\n✅ 必须保留的字段 ({len(must_keep)}个):")
    for field in sorted(must_keep):
        count = len(results[field]["exact_matches"])
        print(f"   ├─ {field} (引用{count}次)")


if __name__ == "__main__":
    main()
