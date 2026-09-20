#!/usr/bin/env python3
"""
飞书多维表格字段使用分析工具
用于检测项目中哪些飞书岗位表字段实际上没有被使用
"""

import re
import os
from pathlib import Path
from collections import defaultdict


def extract_field_references():
    """从代码中提取所有对飞书字段的引用"""
    
    # 要扫描的文件目录（相对于当前脚本位置）
    script_dir = Path(__file__).parent
    backend_dir = script_dir.parent / "app"
    
    if not backend_dir.exists():
        print(f"❌ 找不到后端目录：{backend_dir}")
        return
    
    # 存储所有发现的字段引用
    field_usages = defaultdict(list)
    
    # 遍历所有 Python 文件
    for py_file in backend_dir.rglob("*.py"):
        try:
            content = py_file.read_text(encoding="utf-8")
            
            # 匹配 fields.get("字段名") 或 .get("字段名") 的模式
            patterns = [
                r'fields\.get\(["\']([^"\']+)["\']',
                r'\.get\(["\']([^"\']{3,20})["\']',
            ]
            
            for pattern in patterns:
                matches = re.finditer(pattern, content)
                
                for match in matches:
                    field_name = match.group(1)
                    
                    # 跳过一些配置相关的字段名（不是数据字段）
                    skip_keywords = [
                        "filter", "page_size", "page_token", "conditions",
                        "conjunction", "operator", "value", "field_name",
                        "authorization", "content-type", "receive_id_type"
                    ]
                    
                    if any(kw in field_name.lower() for kw in skip_keywords):
                        continue
                    
                    # 记录文件和行号
                    line_num = content[:match.start()].count('\n') + 1
                    rel_path = py_file.relative_to(backend_dir)
                    
                    key = (str(rel_path), line_num)
                    field_usages[field_name].append(key)
                    
        except Exception as e:
            print(f"⚠️ 读取 {py_file} 失败：{e}")
    
    return field_usages


def find_potentially_unused_fields(field_usages):
    """找出可能未使用的字段（通过关键词推断）"""
    
    # 常见可能的字段类别（基于招聘平台通用字段）
    common_job_fields = [
        # 基本信息
        "公司名称", "岗位名称", "招聘平台", "岗位链接", "发布日期", "抓取时间",
        
        # 位置相关
        "城市", "工作地址", "面试地点", "高德导航直达",
        
        # 薪资福利
        "薪资",
        
        # 要求类
        "经验要求", "学历要求", "技能要求", "证书要求",
        
        # 公司规模
        "公司规模", "公司阶段", "公司业务情报",
        
        # 状态跟踪
        "跟进状态", "我的复核", "定时投递时间",
        
        # JD 内容
        "岗位详情", "职责描述", "任职要求",
        
        # AI 评估相关
        "初步打分", "综合评级", "AI 评估详情", "加分词", "减分词",
        "核心 - 角色匹配", "核心 - 技能重合",
        "高权 - 职级资历", "高权 - 薪资契合", "高权 - 面试概率",
        "中权 - 工作模式", "中权 - 公司阶段", "中权 - 赛道前景",
        "中权 - 成长空间", "低权 - 招聘周期",
        
        # 面试相关
        "面试预测", "专属面试预测", "反问环节建议", "QA 评估报告",
        "现场面试记录", "简历专项 QA", "面试时间",
        "面试辅导报告",
        
        # 附件类
        "PDF 备份", "图片保存", "附件",
        
        # 改写相关
        "AI 改写 JSON", "多 agent 简历改写", "打招呼语",
        
        # 猎头相关
        "猎头推荐语", "猎头备注",
        
        # 其他历史字段（可能是以前用的）
        "候选人状态", "优先级", "来源渠道", "是否外包",
        "远程工作", "股票期权", "五险一金", "带薪年假",
        "团队规模", "融资阶段", "行业领域",
    ]
    
    # 简历库相关字段
    resume_fields = [
        "个人信息", "简历内容", "结构化数据", "照片", "简历版本",
        "当前状态", "教育背景", "工作经历", "项目经验", "技能清单",
        "自我评价", "求职意向", "手动精修版简历",
        "深度分析诊断报告 (AI)", "理想画像与能力信号", "核心能力词典",
        "简历逐行审计", "高杠杆匹配点", "致命硬伤与毒点", "破局行动计划"
    ]
    
    all_possible_fields = set(common_job_fields + resume_fields)
    
    # 找出未在代码中使用的字段
    unused_fields = []
    used_fields = []
    
    for field in sorted(all_possible_fields):
        if field in field_usages:
            used_fields.append((field, len(field_usages[field])))
        else:
            unused_fields.append(field)
    
    return unused_fields, used_fields


def generate_report(field_usages):
    """生成分析报告"""
    
    unused_fields, used_fields = find_potentially_unused_fields(field_usages)
    
    print("\n" + "="*80)
    print("📊 飞书多维表格字段使用分析报告")
    print("="*80)
    
    print("\n✅ 已确认使用的字段（共{}个）:".format(len(used_fields)))
    print("-"*80)
    for field, count in sorted(used_fields, key=lambda x: -x[1]):
        print(f"\n  📌 {field} (被引用{count}次)")
        locations = field_usages[field]
        for location in sorted(locations, key=lambda x: (str(x[0]), x[1]))[:3]:  # 只显示前 3 个
            print(f"     → {location[0]}:{location[1]}")
        if len(locations) > 3:
            print(f"     ... 还有{len(locations) - 3}处引用")
    
    print("\n\n⚠️  可能未使用的字段（共{}个）- 建议检查:".format(len(unused_fields)))
    print("-"*80)
    
    # 分类展示未使用字段
    categories = {
        "评估打分相关": [],
        "面试管理相关": [],
        "附件资源相关": [],
        "状态追踪相关": [],
        "JD 补充字段": [],
        "其他": []
    }
    
    for field in unused_fields:
        if any(word in field for word in ["打分", "评级", "匹配", "加分", "减分"]):
            categories["评估打分相关"].append(field)
        elif any(word in field for word in ["面试", "QA", "辅导"]):
            categories["面试管理相关"].append(field)
        elif any(word in field for word in ["PDF", "图片", "附件", "备份"]):
            categories["附件资源相关"].append(field)
        elif any(word in field for word in ["状态", "复核", "优先级", "定时"]):
            categories["状态追踪相关"].append(field)
        elif any(word in field for word in ["描述", "要求", "详情"]):
            categories["JD 补充字段"].append(field)
        else:
            categories["其他"].append(field)
    
    for category, fields in categories.items():
        if fields:
            print(f"\n  🔹 {category}:")
            for field in sorted(fields):
                print(f"      └─ {field}")
    
    print("\n\n💡 建议操作:")
    print("-"*80)
    print("  1. 先在飞书多维表格中隐藏这些字段，观察 1-2 周是否有异常")
    print("  2. 检查前端界面是否还依赖这些字段显示")
    print("  3. 确认没有外部系统集成使用这些字段")
    print("  4. 如果确认无影响，再考虑批量删除")
    print("  5. 建议先导出备份再删除")
    
    print("\n" + "="*80)
    
    return unused_fields, used_fields


def main():
    """主函数"""
    print("🔍 开始分析代码中的飞书字段引用...\n")
    
    field_usages = extract_field_references()
    
    if not field_usages:
        print("❌ 未找到任何字段引用")
        return
    
    print(f"✓ 共发现 {len(field_usages)} 个不同字段被引用\n")
    
    generate_report(field_usages)


if __name__ == "__main__":
    main()
