"""
多平台在线简历编辑器 - 批量采集与回写 API 路由 (/api/unified/*)
"""

import json
import os
import subprocess
import sys

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.session.health_checker import probe_port
from app.session.registry import PLATFORM_CONFIGS

from .common import (
    DATA_DIR,
    PLATFORMS,
    SCRIPTS_DIR,
    claim_writeback_slot,
    persist_writeback_log,
    precheck_writeback_login,
    release_writeback_slot,
)

router = APIRouter(prefix="/api/unified", tags=["简历编辑器-批量操作"])

PLATFORM_PORTS = {p: PLATFORM_CONFIGS[p].port for p in PLATFORMS}


@router.post("/collect")
def collect_platforms(request: dict):
    """
    触发多平台数据采集（前端顶部操作栏调用）
    Body: { "platforms": ["boss", "liepin", "51job", "zhilian"] }
    """
    platforms = request.get("platforms", [])
    if not platforms:
        return JSONResponse(content={"success": False, "message": "未指定平台"}, status_code=400)

    results = []
    for platform in platforms:
        if platform not in PLATFORMS:
            results.append({"platform": platform, "success": False, "message": "不支持的平台"})
            continue

        # 预检：浏览器未启动直接跳过，不白跑脚本（脚本对未启动浏览器 2 秒即失败，
        # 但逐个跑完再失败用户只知道"失败"，不知道要先点「启动」）
        port = PLATFORM_PORTS[platform]
        if not probe_port(port):
            results.append({
                "platform": platform,
                "success": False,
                "message": f"浏览器未启动（端口 {port} 无响应），请先在「登录状态」栏点击「启动」",
            })
            continue

        script_map = {
            "boss": "boss_collector.py",
            "liepin": "liepin_collector.py",
            "51job": "job51_collector.py",
            "zhilian": "zhilian_collector.py",
        }
        script_name = script_map.get(platform)
        script_path = os.path.join(SCRIPTS_DIR, script_name)

        if not os.path.exists(script_path):
            results.append({"platform": platform, "success": False, "message": f"采集脚本不存在: {script_name}"})
            continue

        # 与 sync-back 同口径：子进程绕代理连 127.0.0.1（代理环境下 DrissionPage/urllib
        # 曾因请求走代理而连不上本机调试端口）
        env = {**os.environ, "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
        try:
            result = subprocess.run(
                [sys.executable, script_path],
                capture_output=True, text=True, timeout=120, env=env
            )
            if result.returncode == 0:
                # 采集成功：前置执行 Schema Diff 差分探针检查
                schema_diff = None
                fields_file = os.path.join(DATA_DIR, f"{platform}_fields.json")
                if os.path.exists(fields_file):
                    try:
                        from resume_editor.schema_diff_engine import (
                            diff_platform_schema,
                        )
                        with open(fields_file, encoding="utf-8") as f:
                            fresh_data = json.load(f)
                        schema_diff = diff_platform_schema(platform, fresh_data)
                    except Exception as de:
                        print(f"[{platform}] Schema Diff 检测异常: {de}")
                # 采集落地了新的平台原值：重置该平台映射报告的变更标注
                # （否则上一轮映射的「已修改/已变更」会跨采集存活，误导用户）
                try:
                    from resume_editor.agent_mapper import reset_report_change_flags
                    reset_report_change_flags(platform)
                except Exception as re_err:
                    print(f"[{platform}] 映射变更标注重置异常: {re_err}")

                results.append({
                    "platform": platform,
                    "success": True,
                    "message": "采集完成",
                    "output": result.stdout[-500:],
                    "schema_diff": schema_diff,
                })
            else:
                full_err = (result.stderr or result.stdout or "未知错误").strip()
                # 提取 [ERROR] 关键行（去掉前缀），避免 stdout 里的 banner/步骤日志淹没真正原因
                err_lines = [line.strip() for line in full_err.splitlines() if "[ERROR]" in line]
                err_msg = (err_lines[-1].replace("[ERROR]", "").strip() if err_lines else full_err)[-500:]
                results.append({"platform": platform, "success": False, "message": err_msg})
        except subprocess.TimeoutExpired:
            results.append({"platform": platform, "success": False, "message": "采集超时(120s)"})
        except Exception as e:
            results.append({"platform": platform, "success": False, "message": str(e)})

    all_success = all(r["success"] for r in results)
    return JSONResponse(content={"success": all_success, "results": results})


@router.post("/sync-back")
def sync_back_platforms(request: dict):
    """
    触发多平台同步回写（前端顶部操作栏调用）
    Body: { "platforms": ["boss", "liepin", "51job", "zhilian"], "paths": ["work_experience", ...], "dry_run": false }
    """
    platforms = request.get("platforms", [])
    if not platforms:
        return JSONResponse(content={"success": False, "message": "未指定平台"}, status_code=400)
    dry_run = bool(request.get("dry_run", False))

    results = []
    for platform in platforms:
        if platform not in PLATFORMS:
            results.append({"platform": platform, "success": False, "message": "不支持的平台"})
            continue

        script_map = {
            "boss": "boss_write_back.py",
            "liepin": "liepin_pusher.py",
            "51job": "job51_write_back.py",
            "zhilian": "zhilian_write_back.py",
        }
        script_name = script_map.get(platform)
        script_path = os.path.join(SCRIPTS_DIR, script_name)

        if not os.path.exists(script_path):
            results.append({"platform": platform, "success": False, "message": f"推送脚本不存在: {script_name}"})
            continue

        # 回写前 DOM 级登录预检：确证失效直接拦截，不白跑脚本（存疑放行，脚本层有二次校验）
        precheck_ok, precheck_msg = precheck_writeback_login(platform)
        if not precheck_ok:
            results.append({"platform": platform, "success": False, "message": precheck_msg})
            continue

        # 同平台回写互斥：批量与 Tab 内回写/并发请求不再互踩 CDP 会话
        if not claim_writeback_slot(platform):
            results.append({"platform": platform, "success": False, "message": f"{platform} 已有回写任务进行中，请稍后再试"})
            continue

        cmd = [sys.executable, script_path, "--json"]
        if dry_run:
            cmd.append("--dry-run")
        paths = request.get("paths") or []
        if platform == "liepin":
            if paths:
                cmd += ["--modules", ",".join(paths)]
        elif platform in ("boss", "51job", "zhilian"):
            if paths:
                cmd += ["--paths", ",".join(paths)]

        env = {**os.environ, "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}

        try:
            result = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=300, env=env
            )
            data = None
            stdout_lines = (result.stdout or "").splitlines()
            for line in stdout_lines:
                if line.startswith("RESULT_JSON:"):
                    try:
                        data = json.loads(line[len("RESULT_JSON:"):])
                        break
                    except Exception:
                        continue

            if data is not None:
                # success/message 契约兼容（用户案例 2026-08-30）：boss/51job/zhilian 历史载荷
                # 无顶层 success/message 键——缺键时以退出码与 results/verify 推导，
                # 不再把成功误判为失败（契约测试 test_writeback_payload_contract.py 双向防护）
                # 回写日志落盘（用户案例 2026-08-31）：完整输出含官网逐操作原话返回
                try:
                    log_file = persist_writeback_log(
                        platform, stdout=result.stdout or "", stderr=result.stderr or "",
                        returncode=result.returncode, data=data, dry_run=dry_run)
                except Exception:
                    log_file = None
                ok_flag = data.get("success")
                if ok_flag is None:
                    ok_flag = result.returncode == 0
                results_msg = data.get("message")
                if not results_msg:
                    entries = [r for r in (data.get("results") or []) if isinstance(r, dict)]
                    ok_n = sum(1 for r in entries if r.get("ok"))
                    verify_bad = sum(1 for v in (data.get("verify") or []) if isinstance(v, dict) and not v.get("match"))
                    if not entries:
                        results_msg = "回写完成" if result.returncode == 0 else "回写失败"
                    elif not verify_bad and ok_n == len(entries):
                        results_msg = f"回写成功 {ok_n}/{len(entries)}"
                    elif verify_bad:
                        results_msg = f"回写完成 {ok_n}/{len(entries)}，复核异常 {verify_bad} 项"
                    else:
                        results_msg = f"部分模块回写失败：{ok_n}/{len(entries)} 成功"
                results.append({
                    "platform": platform,
                    "success": bool(ok_flag),
                    "message": results_msg,
                    "returncode": result.returncode,
                    "stderr": (result.stderr or "")[-800:],
                    "log_file": log_file,
                    "dry_run": bool(data.get("dry_run")),
                    "data_source": data.get("data_source"),
                    "details": data.get("results") or data.get("modules"),
                    # 复核明细逐模块透出（哪个模块没生效、差在哪），前端与排查都可直接定位
                    "verify": data.get("verify"),
                    "output": (result.stdout or "")[-1000:],
                })
            elif result.returncode == 0:
                results.append({"platform": platform, "success": True, "message": "回写完成", "returncode": 0, "output": (result.stdout or "")[-500:]})
            else:
                # 崩溃/解析失败也要落盘：真因在完整 stdout/stderr 里（如智联 training 后崩溃）
                try:
                    log_file = persist_writeback_log(
                        platform, stdout=result.stdout or "", stderr=result.stderr or "",
                        returncode=result.returncode, data=None, dry_run=dry_run)
                except Exception:
                    log_file = None
                err_lines = [line.strip() for line in stdout_lines if line.strip() and not line.strip().startswith("=") and not line.strip().startswith("RESULT_JSON:")]
                clean_err = err_lines[-1] if err_lines else "回写失败（脚本异常退出，详见 stderr）"
                results.append({
                    "platform": platform,
                    "success": False,
                    "message": clean_err,
                    "returncode": result.returncode,
                    # 崩溃类失败的真因在 stderr（如智联 training 后崩溃的 traceback）
                    "stderr": (result.stderr or "")[-800:],
                    "log_file": log_file,
                    "output": (result.stdout or "")[-1000:],
                })
        except subprocess.TimeoutExpired:
            try:
                log_file = persist_writeback_log(platform, stdout="(超时，无输出)", stderr="", returncode=None, data=None, dry_run=dry_run)
            except Exception:
                log_file = None
            results.append({"platform": platform, "success": False, "message": "回写超时(300s)", "log_file": log_file})
        except Exception as e:
            results.append({"platform": platform, "success": False, "message": str(e)})
        finally:
            release_writeback_slot(platform)

    all_success = bool(results) and all(r["success"] for r in results)
    # 顶层 message 聚合：部分失败时前端可直接展示，不再只有笼统提示
    failed = [r for r in results if not r.get("success")]
    if not results:
        summary = "未执行任何平台"
    elif failed:
        summary = f"回写完成 {len(results) - len(failed)}/{len(results)} 个平台成功；" + "；".join(
            f"{r['platform']}：{str(r.get('message') or '失败')[:60]}" for r in failed
        )
    else:
        summary = f"回写完成：全部 {len(results)} 个平台成功"
    return JSONResponse(content={"success": all_success, "message": summary, "results": results})
