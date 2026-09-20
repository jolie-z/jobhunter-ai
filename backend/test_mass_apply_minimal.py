#!/usr/bin/env python3
"""
四平台海投最小可行性测试脚本

功能：
- 从飞书多维表格中拉取待投递岗位
- 每平台至少成功海投 3 个岗位
- 生成测试报告（Markdown 格式）

使用方式：
    cd backend && python test_mass_apply_minimal.py --platforms boss 51job liepin zhilian --count 3
"""

import argparse
import asyncio
import sys
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

# 添加项目路径
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.services.feishu_service import get_jobs_to_deliver
from app.automation.tools import deliver_boss_job, deliver_liepin_job, deliver_51job_job, deliver_zhilian_job


async def test_platform_mass_apply(platform: str, count: int = 3) -> Dict[str, Any]:
    """
    测试单个平台的海投功能
    
    Args:
        platform: 平台名称 (boss/51job/liepin/zhilian)
        count: 需要测试的岗位数量
    
    Returns:
        测试结果字典
    """
    
    print(f"\n{'='*60}")
    print(f"🎯 开始测试 {platform.upper()} 平台海投（目标：{count} 个岗位）")
    print(f"{'='*60}\n")
    
    # Step 1: 从飞书获取该平台未投递的海投候选岗位
    try:
        jobs = get_jobs_to_deliver(target_platform=platform, target_status="待海投")
        
        if len(jobs) < count:
            print(f"⚠️ 可用岗位不足 {count} 个，仅有 {len(jobs)} 个")
            return {
                "platform": platform,
                "status": "insufficient_jobs",
                "total": len(jobs),
                "target": count,
                "success": False,
                "details": [],
                "message": f"可用岗位不足 ({len(jobs)}/{count})"
            }
        
        candidates = jobs[:count]
        
    except Exception as e:
        error_msg = f"拉取岗位失败：{str(e)}"
        print(f"❌ {error_msg}")
        return {
            "platform": platform,
            "status": "fetch_failed",
            "total": 0,
            "target": count,
            "success": False,
            "details": [],
            "message": error_msg
        }
    
    results = []
    
    for idx, job in enumerate(candidates, 1):
        print(f"\n[ {idx}/{count} ] 测试岗位：{job.get('company', '未知')} - {job.get('job_title', '未知')}")
        print(f"   岗位 ID: {job.get('record_id', 'N/A')}")
        print(f"   岗位链接：{job.get('job_url', 'N/A')[:80]}...")
        
        try:
            # Step 2: 组装 job_data
            file_token = None
            pdf_name = "海投简历"
            
            # 提取 PDF 备份 token
            pdf_backup = job.get("PDF 备份", [])
            if isinstance(pdf_backup, list) and len(pdf_backup) > 0:
                file_token = pdf_backup[0].get("file_token")
            
            # 对于 Boss/猎聘，还需要打招呼语
            greeting = ""
            if platform in ["boss", "liepin"]:
                greeting = job.get("打招呼语", "") or "您好，我对这个职位很感兴趣..."
            
            image_items = []
            image_save = job.get("图片保存", [])
            if isinstance(image_save, list):
                for item in image_save:
                    if isinstance(item, dict) and item.get("file_token"):
                        image_items.append({
                            "token": item.get("file_token"),
                            "name": item.get("name", "image.jpg")
                        })
            
            job_data = {
                "record_id": job.get("record_id"),
                "job_url": job.get("岗位链接", ""),
                "file_token": file_token,
                "pdf_name": pdf_name,
                "greeting": greeting,
                "image_items": image_items,
                "mass_apply": True,  # 关键标志：海投模式
            }
            
            print(f"   ✅ 准备投递数据：PDF={pdf_name}, Greeting={'有' if greeting else '无'}")
            
            # Step 3: 调用对应平台的投递函数
            delivery_ok = False
            
            if platform == "boss":
                result = await deliver_boss_job(job_data)
                delivery_ok = "成功" in result
            
            elif platform == "51job":
                result = await deliver_51job_job(job_data)
                delivery_ok = "成功" in result
            
            elif platform == "liepin":
                result = await deliver_liepin_job(job_data)
                delivery_ok = "成功" in result
            
            elif platform == "zhilian":
                result = await deliver_zhilian_job(job_data)
                delivery_ok = "成功" in result
            
            else:
                result = f"❌ 不支持的平台：{platform}"
                delivery_ok = False
            
            # Step 4: 记录结果
            if delivery_ok:
                status = "success"
                message = "投递成功"
                print(f"      ✅ {message}")
            else:
                status = "failed"
                message = f"投递失败：{result}"
                print(f"      ❌ {message}")
            
            results.append({
                "job_idx": idx,
                "company": job.get("company"),
                "job_title": job.get("job_title"),
                "status": status,
                "message": message,
                "raw_result": result
            })
            
            # Step 5: 冷却时间（模拟真实场景）
            if idx < count:
                print(f"   ⏱️ 冷却 10 秒...")
                await asyncio.sleep(10)
        
        except Exception as e:
            error_msg = f"异常：{str(e)}"
            print(f"      ❌ {error_msg}")
            
            results.append({
                "job_idx": idx,
                "company": job.get("company"),
                "job_title": job.get("job_title"),
                "status": "error",
                "message": error_msg,
                "raw_result": None
            })
    
    # Step 6: 生成测试报告
    success_count = sum(1 for r in results if r["status"] == "success")
    total_attempted = len(results)
    
    summary = {
        "platform": platform,
        "target": count,
        "attempted": total_attempted,
        "success": success_count,
        "failure": total_attempted - success_count,
        "success_rate": f"{success_count}/{total_attempted}" if total_attempted > 0 else "0/0",
        "passed": success_count == count,
        "details": results,
        "test_time": datetime.now().isoformat(),
    }
    
    print(f"\n{'='*60}")
    print(f"📊 [{platform}] 测试结果汇总")
    print(f"{'='*60}")
    print(f"   目标数量：{count}")
    print(f"   实际测试：{total_attempted}")
    print(f"   成功：{success_count}")
    print(f"   失败：{total_attempted - success_count}")
    print(f"   成功率：{summary['success_rate']}")
    
    if success_count == count:
        print(f"   🎉 [PASS] {platform} 海投测试通过！")
        summary["message"] = f"✅ {platform} 海投测试通过 ({success_count}/{count})"
    else:
        print(f"   💥 [FAIL] {platform} 海投测试失败")
        summary["message"] = f"❌ {platform} 海投测试失败 ({success_count}/{count})"
    
    print(f"{'='*60}\n")
    
    return summary


def generate_test_report(all_results: List[Dict[str, Any]]) -> str:
    """
    生成完整的测试报告（Markdown 格式）
    
    Args:
        all_results: 所有平台的测试结果列表
    
    Returns:
        Markdown 格式的测试报告
    """
    
    report_lines = [
        "# 🧪 四平台海投测试报告",
        "",
        f"**测试时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 📋 测试摘要",
        "",
    ]
    
    total_passed = 0
    total_failed = 0
    
    for result in all_results:
        platform = result.get("platform", "unknown")
        passed = result.get("passed", False)
        
        if passed:
            total_passed += 1
        else:
            total_failed += 1
        
        report_lines.extend([
            f"### {platform.upper()} 平台",
            "",
            f"- **目标数量**: {result.get('target', 0)}",
            f"- **实际测试**: {result.get('attempted', 0)}",
            f"- **成功**: {result.get('success', 0)}",
            f"- **失败**: {result.get('failure', 0)}",
            f"- **通过率**: {result.get('success_rate', 'N/A')}",
            f"- **状态**: {'✅ PASS' if passed else '❌ FAIL'}",
            "",
            "#### 详细信息",
            "",
            "| 序号 | 公司 | 岗位 | 结果 |",
            "|------|------|------|------|",
        ])
        
        for detail in result.get("details", []):
            status_icon = "✅" if detail.get("status") == "success" else "❌"
            company = detail.get("company", "N/A")[:20]
            job_title = detail.get("job_title", "N/A")[:30]
            message = detail.get("message", "N/A")[:40]
            
            report_lines.append(
                f"| {detail.get('job_idx', '-')} | {company} | {job_title} | {status_icon} {message} |"
            )
        
        report_lines.append("")
    
    # 总体总结
    report_lines.extend([
        "## 🎯 总体总结",
        "",
        f"### 通过平台数：{total_passed}/4",
        f"### 失败平台数：{total_failed}/4",
        "",
    ])
    
    if total_passed == 4:
        report_lines.append("🎉 **恭喜！所有平台海投测试全部通过！**")
    elif total_passed >= 2:
        report_lines.append("🟡 **部分平台通过，建议人工排查失败平台的问题**")
    else:
        report_lines.append("💥 **多数平台失败，需要重点优化后再测试**")
    
    report_lines.extend([
        "",
        "---",
        "",
        "*本报告由自动测试脚本生成*",
    ])
    
    return "\n".join(report_lines)


async def main():
    """主函数"""
    
    parser = argparse.ArgumentParser(description="四平台海投最小可行性测试")
    parser.add_argument(
        "--platforms", 
        nargs="+", 
        default=["boss", "51job", "liepin", "zhilian"],
        help="要测试的平台列表 (默认：boss 51job liepin zhilian)"
    )
    parser.add_argument(
        "--count", 
        type=int, 
        default=3, 
        help="每平台需要测试的岗位数量 (默认：3)"
    )
    
    args = parser.parse_args()
    
    print("\n" + "="*60)
    print("🎯 四平台海投最小可行性测试")
    print("="*60)
    print(f"测试平台：{', '.join(args.platforms)}")
    print(f"每平台岗位数：{args.count}")
    print("="*60 + "\n")
    
    # 并行测试所有平台
    tasks = [test_platform_mass_apply(p, args.count) for p in args.platforms]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 处理异常结果
    clean_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            platform = args.platforms[i]
            error_result = {
                "platform": platform,
                "status": "exception",
                "target": args.count,
                "attempted": 0,
                "success": 0,
                "failure": 0,
                "success_rate": "0/0",
                "passed": False,
                "details": [],
                "message": f"测试过程异常：{str(result)}"
            }
            clean_results.append(error_result)
            print(f"❌ {platform} 测试失败：{str(result)}\n")
        else:
            clean_results.append(result)
    
    # 生成测试报告
    report = generate_test_report(clean_results)
    
    # 保存到文件
    report_filename = f"mass_apply_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    report_path = BASE_DIR / report_filename
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    
    print("\n" + "="*60)
    print("📄 测试报告已保存至:")
    print(f"   {report_path}")
    print("="*60 + "\n")
    
    # 输出到控制台
    print(report)
    
    # 返回退出码
    failed_count = sum(1 for r in clean_results if not r.get("passed", False))
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
