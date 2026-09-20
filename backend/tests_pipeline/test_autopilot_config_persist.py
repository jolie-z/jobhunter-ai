"""autopilot 配置持久化：greeting_platforms 读写 + schema 覆盖保护 + preflight 环境变量

背景：
- 打招呼生成平台开关（greeting_platforms）持久化到 automation_configs；
- /api/automation/config 是整体覆盖式接口，旧客户端不带新字段时必须保留库里已有值
  （靠 pydantic model_fields_set 判定）；
- 登录态预检等待窗口由 PIPELINE_LOGIN_WAIT_S / PIPELINE_LOGIN_POLL_S 控制。
"""
import app.automation.db as adb
from app.automation.schemas import AutopilotConfigSchema
from app.session import preflight


def test_greeting_platforms_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(adb, "DB_PATH", str(tmp_path / "autopilot.db"))
    adb.init_autopilot_db()

    cfg = adb.get_autopilot_config()
    assert cfg["greeting_platforms"] == {"boss": True, "liepin": True, "zhilian": True, "51job": False}

    new_gp = {"boss": False, "liepin": True, "51job": True, "zhilian": False}
    ok = adb.update_autopilot_config(
        "09:30", ["C", "D"], ["boss"], True, {},
        20, "", "", 1000, "", new_gp,
    )
    assert ok
    cfg2 = adb.get_autopilot_config()
    assert cfg2["greeting_platforms"] == new_gp
    assert cfg2["cron_time"] == "09:30"
    assert cfg2["auto_deliver_grades"] == ["C", "D"]


def test_schema_fields_set_guard():
    """旧客户端请求不带 greeting_platforms 时，model_fields_set 不含该字段（防覆盖判定依据）"""
    req = AutopilotConfigSchema.model_validate({"cron_time": "08:00"})
    assert "greeting_platforms" not in req.model_fields_set

    req2 = AutopilotConfigSchema.model_validate({"greeting_platforms": {"boss": False}})
    assert "greeting_platforms" in req2.model_fields_set
    assert req2.greeting_platforms == {"boss": False}


def test_preflight_env_parsing(monkeypatch):
    monkeypatch.setenv("PIPELINE_LOGIN_WAIT_S", "60")
    monkeypatch.setenv("PIPELINE_LOGIN_POLL_S", "5")
    assert preflight._wait_seconds() == 60
    assert preflight._poll_seconds() == 5

    # 非法值回退默认
    monkeypatch.setenv("PIPELINE_LOGIN_WAIT_S", "abc")
    assert preflight._wait_seconds() == 300
    monkeypatch.delenv("PIPELINE_LOGIN_WAIT_S", raising=False)
    monkeypatch.delenv("PIPELINE_LOGIN_POLL_S", raising=False)
    assert preflight._wait_seconds() == 300
    assert preflight._poll_seconds() == 10
