#!/usr/bin/env python3
"""新机器体检脚本 — 一条命令回答「这台机器能不能跑全链路」
====================================================

只读体检，不写任何数据、不播种任何业务记录：
- 【抓取就绪】9 大模块配置判定（与指挥中心 config_status 同源）+ Edge 浏览器
  + 各平台本地 Cookie 文件 → 有任何缺失则 exit 1
- 【投递就绪】各平台 CDP 调试端口连通性探针 → 仅输出 Warning 与登录指引，
  不影响退出码（新机首次体检尚未唤起浏览器属正常状态，不应阻断判定）

用法（任意工作目录均可）:
    python3 backend/scripts/newmachine_check.py

缺失项的「怎么补」全部内联在输出里；配合 README「新机自检」小节使用。
"""
import os
import sys
import time

# 任意 cwd 可执行：按脚本位置定位 backend 根并注入 sys.path
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

_PROJECT_ROOT = os.path.dirname(_BACKEND_ROOT)

# 缺失项 → 修复指引（与 README/文档口径一致）
_MODULE_GUIDES = {
    "scraping": "到指挥中心「抓取配置」或策略实验室填写搜索关键词并启用平台、设置计划上限",
    "cleaning": "到策略实验室创建并启用至少一条清洗策略（或运行 backend/job_processor/init_strategy_db.py 播种）",
    "feishu_sync": "填齐飞书凭证：配置大盘 → 系统底层配置 → 飞书（拿到哪 5 个值见 README 第 0 步 / docs/feishu-setup.md）",
    "evaluating": "到策略实验室「评估权重」保存一次（任意保存动作即写入权重行）",
    "rewriting": "上传一份简历并设为生效（简历库 / 在线简历同步中心）。注：本项按本地 resumes/*.md 判定，简历存飞书简历库时以页面显示为准",
    "greeting": "到指挥中心「投递配置 → 海投招呼语」生成或填写通用打招呼语",
    "review": "到指挥中心「投递配置」设置单轮最多投递人数（mass_apply_max_headcount > 0）",
    "delivering": "到指挥中心「投递配置」选择自动投递平台（auto_deliver_platforms 非空）",
}


def _check_modules() -> list[tuple[str, bool, str]]:
    """9 模块判定。CLI 语境下跳过飞书活跃简历的网络判定（预热缓存为 None），
    rewriting 按本地 resumes/*.md 文件判定；飞书简历库请在页面上看。"""
    from app.pipeline import config_status_service as svc

    svc._ACTIVE_RESUME_META_CACHE["ts"] = time.time()
    svc._ACTIVE_RESUME_META_CACHE["value"] = None

    result = svc.compute_config_status()
    modules = result["data"]["modules"]
    rows = []
    for key in result["data"]["required_keys"]:
        rows.append((key, bool(modules.get(key)), _MODULE_GUIDES.get(key, "")))
    rows.append(("deep_eval", bool(modules.get("deep_eval")), ""))  # 默认就绪，仅展示
    return rows


def _check_edge() -> tuple[bool, str]:
    from app.session.browser import find_edge_path

    try:
        path = find_edge_path()
        return True, path
    except Exception as e:
        return False, str(e)


def _check_cookie_files() -> list[tuple[str, str, bool]]:
    """各平台 legacy cookie 文件存在性（registry 构造即绝对路径，禁自行拼接）。"""
    rows = []
    for key, config in _iter_platform_configs():
        if not config.legacy_cookie_file:
            continue
        try:
            exists = os.path.exists(config.legacy_cookie_file)
        except OSError:
            exists = False
        rows.append((config.display_name, config.legacy_cookie_file, exists))
    return rows


def _iter_platform_configs():
    from app.session.registry import PLATFORM_CONFIGS

    return PLATFORM_CONFIGS.items()


def _check_delivery_ports() -> list[tuple[str, int, bool]]:
    """投递就绪：平台 CDP 调试端口连通性（仅 Warning，不影响退出码）。"""
    from app.session.health_checker import probe_port

    rows = []
    for _, config in _iter_platform_configs():
        if not config.port:
            continue
        try:
            ok = probe_port(config.port)
        except Exception:
            ok = False
        rows.append((config.display_name, config.port, ok))
    return rows


def main() -> int:
    print("=" * 64)
    print("🔍 新机体检 — 抓取就绪")
    print("=" * 64)

    failed = False

    for key, ok, guide in _check_modules():
        mark = "✅" if ok else "❌"
        print(f"  {mark} {key}")
        if not ok and guide:
            print(f"       ↳ 怎么补：{guide}")
            failed = True

    edge_ok, edge_msg = _check_edge()
    print(f"  {'✅' if edge_ok else '❌'} Edge 浏览器（{edge_msg}）")
    if not edge_ok:
        failed = True

    for name, path, exists in _check_cookie_files():
        mark = "✅" if exists else "❌"
        print(f"  {mark} {name} Cookie 文件（{path}）")
        if not exists:
            short = os.path.basename(path)
            print(f"       ↳ 怎么补：在后端终端运行扫码脚本生成（如 liepin_cookie_harvester.py 生成 {short}）")
            failed = True

    print()
    print("=" * 64)
    print("📡 新机体检 — 投递就绪（仅提示，不影响退出码）")
    print("=" * 64)

    for name, port, ok in _check_delivery_ports():
        mark = "✅" if ok else "⚠️ "
        state = "已监听" if ok else "未监听（投递前需唤起浏览器并扫码登录）"
        print(f"  {mark} {name} CDP 端口 {port} {state}")

    print()
    if failed:
        print("❌ 抓取资产存在缺失，补齐上方 ❌ 项后重跑本命令")
        return 1
    print("✅ 抓取与投递资产齐备。投递登录态以投递引擎登录门实测为准；")
    print("   平台未唤起浏览器的，可在指挥中心「平台会话」唤起并扫码。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
