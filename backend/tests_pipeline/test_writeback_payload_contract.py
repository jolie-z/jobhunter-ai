"""
回写载荷契约测试（用户案例 2026-08-30）
======================================
背景：统一路由 /api/unified/sync-back 按 data["success"] 判定成败，而
boss/51job/zhilian 的 RESULT_JSON 历史载荷没有顶层 success/message 键，
导致批量回写把成功误判为失败（toast 出现「回写完成」却标红的自相矛盾）。

双向防护：
1. AST 契约：四个脚本的结果载荷必须包含 success/message 顶层键（改动载荷形状时此测试会红）；
2. 路由行为：对「无 success/message 键的历史载荷」（真实旧形状），
   路由必须以退出码 + results/verify 推导判定，不再误判。
"""
import ast
import json
import os
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "resume_editor", "platforms",
)


# ---------- 1. AST 契约：脚本载荷必须带 success/message ----------

def _return_dict_keys(path: str, func_name: str) -> list:
    """提取函数体内「包含 verify 或 plan 键的结果 Dict」的字面量键列表。"""
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Dict):
                    keys = [k.value for k in sub.value.keys if isinstance(k, ast.Constant)]
                    if "verify" in keys or "plan" in keys:
                        return keys
    return []


def _assign_dict_keys(path: str, var_name: str) -> list:
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == var_name and isinstance(node.value, ast.Dict):
                    return [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
    return []


def test_script_payloads_contain_success_and_message():
    for script in ("boss_write_back.py", "job51_write_back.py", "zhilian_write_back.py"):
        keys = _return_dict_keys(os.path.join(SCRIPTS_DIR, script), "run_write_back")
        assert "success" in keys, f"{script} 载荷缺顶层 success 键：{keys}"
        assert "message" in keys, f"{script} 载荷缺顶层 message 键：{keys}"
        assert "data_source" in keys, f"{script} 载荷缺 data_source（快照新鲜度）：{keys}"

    liepin_keys = _assign_dict_keys(os.path.join(SCRIPTS_DIR, "liepin_pusher.py"), "result_payload")
    assert "success" in liepin_keys and "message" in liepin_keys, liepin_keys


# ---------- 2. 路由行为：历史无键载荷按退出码/results/verify 推导 ----------

def _client():
    from app.main import app
    return TestClient(app)


def _run_route(client, fake_stdout: str, returncode: int):
    import app.api.resume_editor.unified_routes as ur
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        r = MagicMock()
        r.returncode = returncode
        r.stdout = fake_stdout + "\n"
        r.stderr = "Traceback (most recent call last):\nRuntimeError: mock boom\n" if returncode else ""
        return r

    with patch.object(ur, "precheck_writeback_login", lambda p: (True, "mock 登录正常")), \
         patch.object(ur, "subprocess") as m_sub:
        m_sub.run = fake_run
        m_sub.TimeoutExpired = Exception
        resp = client.post("/api/unified/sync-back", json={"platforms": ["boss"]}).json()
    return resp, captured


def test_legacy_payload_without_success_key_rc0_is_success():
    """真实历史形状：载荷无 success/message 键 + 退出码 0 → 判成功，message 从 results/verify 推导"""
    legacy = "RESULT_JSON:" + json.dumps({
        "plan": {}, "results": [{"module": "personal_advantage", "ok": True}],
        "verify": [{"module": "personal_advantage", "match": True}], "data_source": {"using_snapshot": True},
    })
    client = _client()
    resp, _ = _run_route(client, legacy, returncode=0)
    entry = resp["results"][0]
    assert entry["success"] is True, entry
    assert "1/1" in entry["message"], entry
    assert entry["returncode"] == 0


def test_legacy_payload_rc2_verify_bad_is_failure():
    legacy = "RESULT_JSON:" + json.dumps({
        "plan": {}, "results": [{"module": "a", "ok": True}, {"module": "b", "ok": True}],
        "verify": [{"module": "a", "match": True}, {"module": "b", "match": False}],
    })
    client = _client()
    resp, _ = _run_route(client, legacy, returncode=2)
    entry = resp["results"][0]
    assert entry["success"] is False
    assert "复核异常" in entry["message"], entry


def test_crash_without_result_json_surfaces_stderr():
    """脚本中途崩溃（无 RESULT_JSON）：失败原因取日志行，stderr traceback 随响应透出"""
    stdout = "  [✓ 成功] training training add（本地新增条目[0]）\n"
    client = _client()
    resp, _ = _run_route(client, stdout, returncode=1)
    entry = resp["results"][0]
    assert entry["success"] is False
    assert "training" in entry["message"]
    assert "RuntimeError: mock boom" in entry["stderr"], entry
    assert entry["returncode"] == 1
