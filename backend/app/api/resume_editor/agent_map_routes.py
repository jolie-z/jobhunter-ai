"""
多平台在线简历编辑器 - Agent 智能映射与真机回写 API 路由 (/api/agent-map/*)
"""

import json
import os
import subprocess
import sys
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from resume_editor import agent_mapper as am

from .common import (
    DATA_DIR,
    PLATFORMS,
    SCRIPTS_DIR,
    atomic_write_json,
    claim_writeback_slot,
    persist_writeback_log,
    precheck_writeback_login,
    release_writeback_slot,
)

router = APIRouter(prefix="/api/agent-map", tags=["简历编辑器-Agent映射与回写"])


@router.get("/resumes")
def agent_map_resumes():
    """列出飞书简历库全部简历（含停用），供「主简历来源」下拉选择"""
    result = am.list_feishu_resumes()
    return JSONResponse(content={
        "success": result["ok"],
        "ok": result["ok"],
        "resumes": result["resumes"],
        "message": result["message"],
        "selected_master_record_id": am.get_selected_master_record(),
    })


@router.get("/master")
def agent_map_master(record_id: str = None, use_active: bool = False):
    """预览主简历来源"""
    rid = None if use_active else (record_id or am.get_selected_master_record())
    master = am.load_master_resume(record_id=rid)
    return JSONResponse(content={
        "success": master["ok"],
        "source": master["source"],
        "record_id": master.get("record_id"),
        "name": master.get("name"),
        "char_count": master["char_count"],
        "message": master["message"],
        "sections": list(master["data"].keys()) if isinstance(master["data"], dict) else [],
        "personal_info_preview": master.get("personal_info", "")[:200],
    })


@router.post("/generate")
def agent_map_generate(request: dict):
    """
    生成执行报告：主简历 → 各平台字段映射
    Body: { "platforms": ["boss", "zhilian"], "record_id": "recXXX", "selected_modules": ["work_experience", "projects"] }
    """
    platforms = [p for p in request.get("platforms", []) if p in PLATFORMS]
    if not platforms:
        return JSONResponse(content={"success": False, "message": "未指定有效平台"}, status_code=400)

    selected_modules = request.get("selected_modules") or request.get("modules")
    if selected_modules and isinstance(selected_modules, list):
        selected_modules = [str(m).strip() for m in selected_modules if str(m).strip()]
    else:
        selected_modules = None

    record_id = request["record_id"] if "record_id" in request else am.get_selected_master_record()
    master = am.load_master_resume(record_id=record_id)
    if not master["ok"]:
        return JSONResponse(content={"success": False, "message": master["message"]})

    print(f"▶ [Agent映射] 开始执行映射: platforms={platforms}, modules={selected_modules or '全部模块'}, record_id={record_id}")

    reports = {}
    for platform in platforms:
        file_path = os.path.join(DATA_DIR, f"{platform}_fields.json")
        if not os.path.exists(file_path):
            reports[platform] = {
                "success": False,
                "platform": platform,
                "fields": [],
                "unfilled": [],
                "warnings": [],
                "message": f"{platform} 字段数据不存在，请先采集",
            }
            continue
        with open(file_path, encoding="utf-8") as f:
            fields_data = json.load(f)
        report = am.map_platform(platform, fields_data, master, selected_modules=selected_modules)
        if report.get("success"):
            am.save_report(platform, report, selected_modules=selected_modules)
        reports[platform] = report

    am.set_selected_master_record(record_id)

    # 顶层 success 反映真实聚合结果：任一平台映射失败（如 BOSS 无 LLM 时）
    # 不再被硬编码的 True 掩盖，前端据此区分成功/部分失败提示
    ok_all = all(isinstance(reports.get(p), dict) and reports[p].get("success") for p in platforms)
    return JSONResponse(content={
        "success": ok_all,
        "master": {
            "source": master["source"],
            "char_count": master["char_count"],
            "record_id": master.get("record_id"),
            "name": master.get("name"),
            "message": master["message"],
        },
        "reports": reports,
    })


@router.get("/reports")
def agent_map_reports():
    """恢复上次生成的映射报告（不调 LLM）"""
    restored = {}
    for platform in PLATFORMS:
        file_path = os.path.join(DATA_DIR, f"{platform}_fields.json")
        if not os.path.exists(file_path):
            continue
        with open(file_path, encoding="utf-8") as f:
            fields_data = json.load(f)
        report = am.restore_report(platform, fields_data)
        if report:
            restored[platform] = report
    return JSONResponse(content={
        "success": True,
        "reports": restored,
        "selected_master_record_id": am.get_selected_master_record(),
    })


@router.post("/apply")
def agent_map_apply(request: dict):
    """
    人工确认后写入：把映射条目写入 {platform}_fields.json
    Body: { "platform": "boss", "entries": [{"path": "name", "value": "..."}] }
    """
    platform = request.get("platform", "")
    entries = request.get("entries", [])
    if platform not in PLATFORMS:
        return JSONResponse(content={"success": False, "message": f"不支持的平台: {platform}"}, status_code=400)
    if not entries:
        return JSONResponse(content={"success": False, "message": "无可写入条目"}, status_code=400)

    file_path = os.path.join(DATA_DIR, f"{platform}_fields.json")
    if not os.path.exists(file_path):
        return JSONResponse(content={"success": False, "message": f"{platform} 字段数据不存在"}, status_code=404)

    with open(file_path, encoding="utf-8") as f:
        fields_data = json.load(f)

    result = am.apply_mapping(fields_data, entries)

    # 原子写：临时文件 + os.replace，写一半崩溃不留损坏 JSON
    atomic_write_json(file_path, fields_data)

    # 写入后长度复检（apply 环节不再零复检）：超限值已写入但明确警告到响应
    length_warnings = []
    if result["applied"]:
        try:
            mini = {"fields": [{"path": p, "value": am.get_path(fields_data, p)} for p in result["applied"]]}
            length_warnings = am._check_field_length_limits(mini, platform).get("warnings", [])
        except Exception:
            pass

    if result["applied"]:
        applied_values = {e["path"]: e["value"] for e in entries if e.get("path") in result["applied"]}
        slim = am.load_reports().get(platform)
        if slim:
            for f in slim.get("fields", []):
                if f["path"] in applied_values:
                    f["value"] = applied_values[f["path"]]
            prev = slim.get("applied_paths", [])
            slim["applied_paths"] = prev + [p for p in result["applied"] if p not in prev]
            am.save_report(platform, slim)

    message = f"已写入 {len(result['applied'])} 项" + (f"，跳过 {len(result['skipped'])} 项" if result["skipped"] else "")
    if length_warnings:
        message += "；⚠️ " + "；".join(length_warnings[:3])
    return JSONResponse(content={
        "success": True,
        "platform": platform,
        "applied": result["applied"],
        "skipped": result["skipped"],
        "warnings": length_warnings,
        "message": message,
    })


@router.post("/save-edits")
def agent_map_save_edits(request: dict):
    """
    保存编辑状态：把前端编辑后的字段值写回落盘报告（agent_map_reports.json）
    Body: { "platform": "boss", "entries": [{"path": "name", "value": "..."}] }
    """
    platform = request.get("platform", "")
    entries = request.get("entries", [])
    if platform not in PLATFORMS:
        return JSONResponse(content={"success": False, "message": f"不支持的平台: {platform}"}, status_code=400)
    if not entries:
        return JSONResponse(content={"success": False, "message": "无可保存条目"}, status_code=400)

    data = am.load_reports()
    slim = data.get(platform)
    if not slim:
        return JSONResponse(content={"success": False, "message": "该平台暂无已生成报告"}, status_code=404)

    by_path = {str(e.get("path", "")): e.get("value") for e in entries if e.get("path")}
    saved = 0
    for f in slim.get("fields", []):
        if f["path"] in by_path:
            f["value"] = by_path[f["path"]]
            saved += 1
    am._write_reports_file(data)

    return JSONResponse(content={
        "success": True,
        "platform": platform,
        "saved": saved,
        "message": f"已保存 {saved} 项编辑（未写入平台数据）",
    })


@router.post("/writeback-save")
def agent_map_writeback_save(request: dict):
    """
    保存「回写数据源」快照：把 {platform}_fields.json 复制为 {platform}_writeback.json
    Body: { "platform": "liepin" }
    """
    platform = request.get("platform", "")
    if platform not in PLATFORMS:
        return JSONResponse(content={"success": False, "message": f"不支持的平台: {platform}"}, status_code=400)

    file_path = os.path.join(DATA_DIR, f"{platform}_fields.json")
    if not os.path.exists(file_path):
        return JSONResponse(content={"success": False, "message": f"{platform} 字段数据不存在，请先采集"}, status_code=404)

    with open(file_path, encoding="utf-8") as f:
        fields_data = json.load(f)

    # 空数据拒绝（质检 C5 2026-08-30）：近乎为空的数据不能作为回写源，防止空内容推上官网
    from resume_editor.platforms.browser_common import backup_json_file, data_richness
    non_empty, total = data_richness(fields_data)
    if non_empty < 3:
        return JSONResponse(content={
            "success": False,
            "message": f"{platform} 本地数据近乎为空（{non_empty} 个非空模块，共 {total} 项），已拒绝保存为回写数据源。请先采集或应用映射。",
        }, status_code=400)

    snapshot = {
        "meta": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source": f"{platform}_fields.json（编辑器最新数据，含主简历映射结果）",
        },
        "fields": fields_data,
    }
    snapshot_path = os.path.join(DATA_DIR, f"{platform}_writeback.json")
    # 覆盖前备份旧快照（与采集落盘同一保险机制，误保存可回滚）
    try:
        backup_json_file(snapshot_path, f"{platform}_writeback")
    except Exception:
        pass
    # 原子写（质检 A3 2026-08-30）：写一半被杀不会留下损坏回写源
    atomic_write_json(snapshot_path, snapshot)

    return JSONResponse(content={
        "success": True,
        "platform": platform,
        "saved_at": snapshot["meta"]["created_at"],
        "message": f"已保存回写数据源（{platform}_writeback.json），顶部「回写数据」将读取该快照",
    })


@router.post("/write-back")
def agent_map_write_back(request: dict):
    """
    把本地数据回写到平台官网在线简历（支持 boss / 51job / zhilian）
    Body: { "platform": "boss"|"51job"|"zhilian", "dry_run": false, "paths": ["work_experience", ...] }
    """
    WRITE_BACK_SCRIPTS = {
        "boss": "boss_write_back.py",
        "51job": "job51_write_back.py",
        "zhilian": "zhilian_write_back.py",
    }

    platform = request.get("platform", "")
    dry_run = bool(request.get("dry_run", False))
    paths = [str(p) for p in (request.get("paths") or []) if str(p).strip()]
    script_name = WRITE_BACK_SCRIPTS.get(platform)
    if not script_name:
        supported = "、".join(WRITE_BACK_SCRIPTS.keys())
        return JSONResponse(
            content={"success": False, "message": f"暂不支持回写平台: {platform}（目前支持 {supported}）"},
            status_code=400,
        )

    script_path = os.path.join(SCRIPTS_DIR, script_name)
    if not os.path.exists(script_path):
        return JSONResponse(content={"success": False, "message": f"回写脚本不存在: {script_name}"}, status_code=500)

    # 回写前 DOM 级登录预检：确证失效直接拦截（与 unified/sync-back 同口径）
    precheck_ok, precheck_msg = precheck_writeback_login(platform)
    if not precheck_ok:
        return JSONResponse(content={"success": False, "platform": platform, "error": precheck_msg, "message": precheck_msg}, status_code=400)

    # 同平台回写互斥：批量回写与 Tab 内回写并发时拒绝后者
    if not claim_writeback_slot(platform):
        return JSONResponse(content={"success": False, "platform": platform, "message": f"{platform} 已有回写任务进行中，请稍后再试"}, status_code=409)

    env = {**os.environ, "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}

    try:
        cmd = [sys.executable, script_path, "--json"]
        if dry_run:
            cmd.append("--dry-run")
        if paths:
            cmd += ["--paths", ",".join(paths)]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
        except subprocess.TimeoutExpired:
            return JSONResponse(content={"success": False, "message": "回写超时(300s)"}, status_code=504)
        except Exception as e:
            return JSONResponse(content={"success": False, "message": str(e)}, status_code=500)
    finally:
        release_writeback_slot(platform)

    data = None
    stdout_lines = (result.stdout or "").splitlines()
    stderr_content = (result.stderr or "")[-1000:]
    for line in stdout_lines:
        if line.startswith("RESULT_JSON:"):
            try:
                data = json.loads(line[len("RESULT_JSON:"):])
                break
            except Exception as e:
                print(f"Failed to parse RESULT_JSON: {e}")
                continue

    # 回写日志落盘（用户案例 2026-08-31）：完整输出含官网逐操作原话返回，
    # 「接口回执成功、官网没生效」类问题靠它拿拒绝原话；落盘失败不影响回写
    try:
        log_file = persist_writeback_log(
            platform, stdout=result.stdout or "", stderr=result.stderr or "",
            returncode=result.returncode, data=data, dry_run=dry_run)
    except Exception:
        log_file = None

    if data is None:
        return JSONResponse(content={
            "success": False,
            "message": "回写结果解析失败 - 脚本未正常输出结果",
            "log_file": log_file,
            "output": (result.stdout or "")[-1500:],
            "stderr": stderr_content,
            "returncode": result.returncode,
            "command": " ".join(cmd),
        }, status_code=500)

    if dry_run:
        return JSONResponse(content={"success": True, "dry_run": True, "plan": data})

    if data.get("success") is False or data.get("error"):
        err_msg = data.get("message") or data.get("error") or "回写执行异常"
        return JSONResponse(content={
            "success": False,
            "platform": platform,
            "error": err_msg,
            "message": err_msg,
            "log_file": log_file,
            "diagnostic": data.get("diagnostic"),
            "overflow_violations": data.get("overflow_violations"),
            "details": data.get("details") or data.get("traceback"),
            "output": result.stdout,
            "stderr": stderr_content,
            "returncode": result.returncode,
        }, status_code=400 if data.get("overflow_violations") else 500)

    results = data.get("results", [])
    succ = sum(1 for r in results if r.get("ok"))
    verify = data.get("verify", [])
    verify_bad = [v for v in verify if not v.get("match")]
    success = result.returncode == 0 and not verify_bad
    fail_n = len(results) - succ

    if not success and not results:
        msg = f"回写未完成 (code={result.returncode})"
    elif not success and fail_n and verify_bad:
        msg = f"写入成功 {succ}/{len(results)}、失败 {fail_n} 项；复核不一致 {len(verify_bad)} 项"
    elif not success and fail_n:
        msg = f"写入失败 {fail_n}/{len(results)} 项"
    elif not success and verify_bad:
        msg = f"回写完成 {succ}/{len(results)}，复核不一致 {len(verify_bad)} 项"
    elif not results:
        msg = "无需回写（全部与官网一致）"
    else:
        msg = f"回写成功 {succ}/{len(results)}"

    return JSONResponse(content={
        "success": success,
        "platform": platform,
        "plan": data.get("plan", {}),
        "results": [{k: r.get(k) for k in ("module", "detail", "resp_code", "resp_status", "resp_message", "ok")} for r in results],
        "verify": verify,
        "log_file": log_file,
        "diagnostic": data.get("diagnostic"),
        "overflow_violations": data.get("overflow_violations"),
        "message": msg,
        "output": result.stdout,
    })
