"""
Backward Compatibility: Create a comprehensive backwrite report system
Displays status of each module after backwriting to BOSS website
"""

def create_backwrite_report(plan, results, file_path=None):
    """
    Generate detailed backwrite report showing success/failure for each module
    
    Args:
        plan: List of actions being executed
        results: Execution results from each action
        file_path: Optional file path to save report
    
    Returns:
        dict: Report object with HTML and text versions
    """
    
    # Group by module
    modules = {}
    for i, a in enumerate(plan.get("actions", [])):
        module_name = a["module"]
        
        if module_name not in modules:
            modules[module_name] = {
                "status": "success",
                "count": 0,
                "failed_count": 0,
                "details": []
            }
        
        modules[module_name]["count"] += 1
        
        # Check result
        if i < len(results):
            resp = results[i]
            code = resp.get("code")
            ok = (code == 0) or (code == 200082)
            
            modules[module_name]["details"].append({
                "action": a.get("detail", ""),
                "endpoint": a.get("endpoint", ""),
                "code": code,
                "message": resp.get("message", ""),
                "success": ok,
                "payload": a.get("payload", {})
            })
            
            if not ok:
                modules[module_name]["status"] = "partial_failure"
                modules[module_name]["failed_count"] += 1
            elif modules[module_name]["status"] != "failure":
                modules[module_name]["status"] = "success"
    
    # Add skipped items
    for s in plan.get("skipped", []):
        module_name = s["module"]
        if module_name not in modules:
            modules[module_name] = {
                "status": "skipped",
                "count": 0,
                "failed_count": 0,
                "details": [{"action": f"Skipped: {s['reason']}", "success": True, "code": 0, "message": "", "payload": {}}]
            }
    
    # Build summary
    total = sum(m["count"] for m in modules.values())
    failed = sum(1 for m in modules.values() if m["failed_count"] > 0)
    passed = total - failed
    
    report_summary = {
        "total_actions": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": f"{passed/total*100:.0f}%" if total > 0 else "N/A",
        "modules": modules,
        "timestamp": "August 15, 2026",
    }
    
    # Generate text report
    text_lines = [
        "=" * 70,
        "BOSS 官网回写报告 / Backwrite Report",
        f"时间 / Date: {report_summary['timestamp']}",
        "-" * 70,
        f"总计 / Total: {report_summary['total_actions']} 项",
        f"成功 / Passed: {report_summary['passed']}",
        f"失败 / Failed: {report_summary['failed']}",
        f"通过率 / Success Rate: {report_summary['pass_rate']}",
        "",
        "详细报告 / Details:",
        "-" * 70,
    ]
    
    for module_name, data in sorted(modules.items()):
        icon = "✅" if data["failed_count"] == 0 else "⚠️"
        status_text = "SUCCESS" if data["failed_count"] == 0 else "PARTIAL FAILURE"
        text_lines.append(f"\n{icon} [{data['status'].upper()}] {module_name}: {status_text}")
        text_lines.append(f"   操作数 / Actions: {data['count']} | 失败 / Failed: {data['failed_count']}")
        
        for detail in data["details"]:
            icon = "✅" if detail["success"] else "❌"
            text_lines.append(f"   {icon} {detail['action'][:50]}...")
            if not detail["success"]:
                text_lines.append(f"       Code: {detail['code']} | Message: {detail['message']}")
                if "salary" in detail["action"].lower() or "期望" in str(detail.get("payload", {}).get("position", "")):
                    text_lines.append(f"       PAYLOAD DETAILS:")
                    payload = detail["payload"]
                    if "lowSalary" in payload:
                        text_lines.append(f"           lowSalary: {payload.get('lowSalary')}")
                        text_lines.append(f"           highSalary: {payload.get('highSalary')}")
                    if "otherLocationCodeStr" in payload:
                        text_lines.append(f"           otherLocations: {len(payload['otherLocationCodeStr'].split(',')) if payload['otherLocationCodeStr'] else 0} cities")
    
    report_text = "\n".join(text_lines)
    report_text += "\n\n" + "=" * 70
    
    # Generate HTML version
    html_parts = [
        "<!DOCTYPE html>",
        "<html><head><title>BOSS 官网回写报告</title>",
        "<style>",
        "body { font-family: Arial; margin: 20px; }",
        ".header { background: #f5f5f5; padding: 15px; border-radius: 5px; }",
        ".summary { margin: 15px 0; }",
        ".summary-item { display: inline-block; margin-right: 30px; padding: 10px; border-radius: 5px; }",
        ".pass { background: #d4edda; color: #155724; }",
        ".fail { background: #f8d7da; color: #721c24; }",
        ".warning { background: #fff3cd; color: #856404; }",
        ".module { margin: 10px 0; padding: 15px; border-left: 4px solid #ddd; }",
        ".success { border-color: #28a745; }",
        ".partial-fail { border-color: #ffc107; }",
        "pre { white-space: pre-wrap; word-wrap: break-word; }",
        "</style>",
        "</head>",
        "<body>",
        '<div class="header">',
        f"<h1>📊 BOSS 官网回写报告 / Backwrite Report</h1>",
        f"<p><strong>时间:</strong> {report_summary['timestamp']}</p>",
        '</div>',
        '<div class="summary">',
        f'<span class="summary-item pass">✅ 通过: {report_summary["passed"]} 项</span>',
        f'<span class="summary-item fail">❌ 失败：{report_summary["failed"]} 项</span>',
        f'<span class="summary-item warning">📈 成功率：{report_summary["pass_rate"]}</span>',
        '</div>',
    ]
    
    for module_name, data in sorted(modules.items()):
        html_parts.append(f"<div class='module {'success' if data['failed_count'] == 0 else 'partial-fail'}'>")
        icon = "✅" if data["failed_count"] == 0 else "⚠️"
        status = "SUCCESS" if data["failed_count"] == 0 else "PARTIAL FAILURE"
        html_parts.append(f"<h3>{icon} [{status}] {module_name}</h3>")
        html_parts.append(f"<p><strong>Actions:</strong> {data['count']} | <strong>Failed:</strong> {data['failed_count']}</p>")
        
        for detail in data["details"]:
            icon = "✅" if detail["success"] else "❌"
            html_parts.append(f"<div style='margin-left: 20px;'>{icon} {detail['action'][:60]}</div>")
            if not detail["success"]:
                html_parts.append(f"<div style='margin-left: 40px; color: red;'>Code: {detail['code']} | {detail['message']}</div>")
                # Highlight salary/city issues
                payload = detail.get("payload", {})
                if payload.get("lowSalary", 0) == 0 and payload.get("highSalary", 0) == 0:
                    html_parts.append(f"<div style='margin-left: 60px; color: red; font-weight: bold;'>⚠️ Salary issue: both values are 0!</div>")
                if "otherLocationCodeStr" in payload:
                    cities_count = len(payload['otherLocationCodeStr'].split(',')) if payload['otherLocationCodeStr'] else 0
                    original_cities = data["details"][0].get("payload", {}).get("city", "")
                    html_parts.append(f"<div style='margin-left: 60px;'>Cities mapped: {cities_count}</div>")
        
        html_parts.append("</div>")
    
    html_parts.extend([
        "</body></html>"
    ])
    
    report_html = "".join(html_parts)
    
    # Save to file if needed
    if file_path:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(report_text)
            f.write("\n\n")
            f.write(report_html)
        print(f"💾 Report saved to: {file_path}")
    
    return {
        "text": report_text,
        "html": report_html,
        "summary": report_summary,
        "passed": passed,
        "failed": failed,
    }


# Test the function
if __name__ == "__main__":
    test_plan = {
        "actions": [
            {"module": "expectations", "detail": "期望 0 全栈工程师 (更新官网 0)", "payload": {"lowSalary": 15, "highSalary": 25, "otherLocationCodeStr": "801000,802000,803000"}},
            {"module": "expectations", "detail": "期望 1AI 产品经理 (新增)", "payload": {"lowSalary": 0, "highSalary": 0, "otherLocationCodeStr": "801000"}},  # FAILED!
            {"module": "work_experience", "detail": "工作 0 自由职业者", "payload": {}},
        ],
        "skipped": [
            {"module": "education", "reason": "本地无教育数据"}
        ]
    }
    
    test_results = [
        {"code": 0, "message": "OK"},
        {"code": 500, "message": "Internal Error"},  # FAILED
        {"code": 0, "message": "OK"},
    ]
    
    report = create_backwrite_report(test_plan, test_results)
    print(report["text"])
