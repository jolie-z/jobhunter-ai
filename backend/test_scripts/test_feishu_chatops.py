"""
飞书 ChatOps 指令批量测试脚本
===============================
用于验证 ChatOps 系统能否正确解析和执行各类指令

支持模式：
- 单指令测试：python test_feishu_chatops.py "抓取 boss 平台的 Python 岗位"
- 批量测试：python test_feishu_chatops.py --batch
"""
import os
import sys
import json
import asyncio
import requests
from typing import Dict, Any

# 从项目根目录添加 backend 到 path
project_root = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(project_root, "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.api.routes.chatops import parse_chat_intent, ChatCommandRequest
from app.core.config import settings


async def test_single_command_async(command: str, history: list = None) -> Dict[str, Any]:
    """测试单个指令的解析结果（异步版本）"""
    print(f"\n{'='*60}")
    print(f"📝 测试指令：{command}")
    print(f"{'='*60}")
    
    try:
        # 调用意图解析函数（异步）
        intent = await parse_chat_intent(command, history=history)
        result = {
            "command": command,
            "success": True,
            "parsed_intent": intent
        }
        
        # 打印关键字段
        action = intent.get("action", "N/A")

        # 平台归一化（与 handle_chat_command 保持一致）
        platforms = intent.get("platforms")
        if not platforms:
            single_platform = intent.get("platform")
            platforms = [single_platform] if single_platform else []
        platform_alias = {"智联": "zhaopin", "zhilian": "zhaopin", "前程无忧": "51job", "猎聘": "liepin"}
        platforms = [platform_alias.get(p, p) for p in platforms]

        target_count = intent.get("target_count") or intent.get("target_jobs")
        
        print(f"\n✅ 解析成功!")
        print(f"   Action: {action}")
        print(f"   Platforms: {', '.join(platforms) if platforms else '无'}")
        print(f"   Target Count: {target_count}")
        print(f"   Keyword: {intent.get('keyword', '无')}")
        print(f"   City: {intent.get('city', '无')}")
        print(f"   Specific Page: {intent.get('specific_page', '无')}")
        print(f"   Start Page: {intent.get('start_page', '无')}")
        
        result["normalized_platforms"] = platforms
        return result
        
    except Exception as e:
        error_msg = str(e)
        result = {
            "command": command,
            "success": False,
            "error": error_msg
        }
        print(f"\n❌ 解析失败：{error_msg}")
        return result


def test_single_command(command: str, history: list = None) -> Dict[str, Any]:
    """同步包装器（用于命令行调用）"""
    return asyncio.run(test_single_command_async(command, history))


def test_chatops_api_endpoint(command: str) -> Dict[str, Any]:
    """通过 HTTP API 测试（如果后端已启动）"""
    try:
        url = f"{settings.MAIN_API_BASE}/chatops/command"
        payload = {"command": command, "history": []}
        response = requests.post(url, json=payload, timeout=30)
        return {
            "success": response.status_code == 200,
            "status_code": response.status_code,
            "response": response.json() if response.ok else {"error": response.text}
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def run_batch_tests_async():
    """运行预定义的测试用例集（异步版本）"""
    test_cases = [
        # 基础爬虫指令
        {"command": "抓取 boss 平台的 Python 后端岗位", "expect": {"action": "scrape", "platforms": ["boss"]}},
        {"command": "51job 爬北京 Java 开发第 5 页", "expect": {"action": "scrape", "platforms": ["51job"], "specific_page": 5}},
        {"command": "liepin 抓取上海游戏开发", "expect": {"action": "scrape", "platforms": ["liepin"]}},
        {"command": "zhaopin 深圳 C++ 工程师从第 3 页开始抓", "expect": {"action": "scrape", "platforms": ["zhaopin"], "start_page": 3}},
        
        # 目标数量指定
        {"command": "boss 抓广州 30 个 Python 岗位", "expect": {"action": "scrape", "target_count": 30}},
        
        # 清洗过滤
        {"command": "清洗所有平台入库数据", "expect": {"action": "clean"}},
        {"command": "打分并过滤 (>80 分)", "expect": {"action": "evaluate"}},
        
        # 推送指令
        {"command": "将筛选结果推送至飞书", "expect": {"action": "push"}},
        {"command": "push_to_feishu crawl_date=2026-08-13 min_score=75 limit=50", "expect": {"action": "push_to_feishu"}},
        
        # 查询指令
        {"command": "查本地数据库中 Python 相关岗位", "expect": {"action": "query_db"}},
        {"command": "查飞书表格中 2026-08-13 新增数据", "expect": {"action": "query_feishu"}},
        
        # 停止指令
        {"command": "终止当前抓取任务", "expect": {"action": "stop_scrape"}},
        
        # AI 评估
        {"command": "触发 AI 深度评估", "expect": {"action": "ai_evaluate"}},
    ]
    
    print("\n" + "="*80)
    print("🚀 开始批量测试 ChatOps 指令解析")
    print("="*80)
    
    results = []
    for i, case in enumerate(test_cases, 1):
        print(f"\n[{i}/{len(test_cases)}]", end=" ")
        result = await test_single_command_async(case["command"])
        result["expected"] = case["expect"]
        results.append(result)
    
    # 统计结果
    success_count = sum(1 for r in results if r["success"])
    print("\n" + "="*80)
    print(f"✅ 测试完成：{success_count}/{len(results)} 通过")
    print("="*80)
    
    # 输出详细报告
    failures = [r for r in results if not r["success"]]
    if failures:
        print("\n❌ 失败的指令:")
        for f in failures:
            print(f"  - {f['command']}: {f.get('error', '未知错误')}")
    
    return results


def run_batch_tests():
    """同步入口"""
    return asyncio.run(run_batch_tests_async())


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--batch":
        run_batch_tests()
    elif len(sys.argv) > 1:
        command = " ".join(sys.argv[1:])
        test_single_command(command)
    else:
        print("用法:")
        print("  单指令测试：python test_feishu_chatops.py '你的指令'")
        print("  批量测试：python test_feishu_chatops.py --batch")
