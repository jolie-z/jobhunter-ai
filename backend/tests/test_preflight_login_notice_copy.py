"""登录提醒文案回归（2026-10-30 工单：文案太潦草 / 暴露内部诊断术语）。

锁定用户可见文案的三条底线：
1. 不出现端口号、「存疑放行」、`liepin_cookie_harvester.py` 等内部术语/路径；
2. 每个平台给出明确动作，并说明「登录完不用回复，系统会自动继续」；
3. 有截止时间与逾期后果，浏览器未唤起时给会话条兜底入口。
"""
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.session import preflight  # noqa: E402
from app.session.models import PlatformConfig, SessionState, SessionStatus  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _status(name: str, message: str, state: SessionState = SessionState.EXPIRED) -> SessionStatus:
    return SessionStatus(platform=name, state=state, message=message)


def _config(name: str, display_name: str, **kwargs) -> PlatformConfig:
    return PlatformConfig(name=name, display_name=display_name, **kwargs)


def test_login_notice_is_actionable_and_hides_internal_jargon(monkeypatch):
    monkeypatch.setattr(preflight, "_poll_seconds", lambda: 10)
    boss = _config("boss", "BOSS直聘", port=19222)
    zhilian = _config("zhilian", "智联招聘", port=9250)
    liepin = _config("liepin", "猎聘", port=9226, legacy_cookie_file="/tmp/liepin_cookies.json")
    items = [
        (boss, _status("boss", "已在平台站点内但未命中登录标识（免导航预检，可能只是不在登录页），存疑放行", SessionState.UNKNOWN), preflight._PENDING_KIND_LOGIN),
        (zhilian, _status("zhilian", "DOM 级校验未命中任何登录标识，登录态已失效"), preflight._PENDING_KIND_LOGIN),
        (liepin, _status("liepin", "缺少本地 Cookie 文件: /tmp/liepin_cookies.json"), preflight._PENDING_KIND_COOKIE_FILE),
    ]

    sent: list[str] = []

    async def fake_send(text: str) -> bool:
        sent.append(text)
        return True

    import app.automation.pipeline_report as pr
    monkeypatch.setattr(pr, "send_pipeline_report", fake_send)

    _run(preflight._notify_login_needed(items, wait_s=300, launched={"liepin"}))

    assert len(sent) == 1
    text = sent[0]
    # 用户能看懂的动作与节奏
    assert "需要你登录" in text
    assert "BOSS直聘" in text and "智联招聘" in text and "猎聘" in text
    assert "登录完成后不用回复" in text
    assert "每 10 秒自动检查一次" in text
    assert "请在" in text and "前完成" in text
    assert "逾期" in text and "自动跳过" in text
    assert "唤起浏览器" in text
    # 状态优先于关键字：UNKNOWN 的“存疑放行”与 EXPIRED 的“登录已失效”不能混
    assert "BOSS直聘：暂时没确认到登录状态" in text
    assert "智联招聘：登录已失效" in text
    # 不再泄露内部诊断/路径/端口
    assert "存疑放行" not in text
    assert "端口" not in text
    assert "liepin_cookie_harvester" not in text
    assert "/tmp/liepin_cookies.json" not in text


def test_login_notice_points_to_session_bar_when_browser_not_launched(monkeypatch):
    liepin = _config("liepin", "猎聘", port=9226, legacy_cookie_file="/tmp/liepin_cookies.json")
    items = [
        (liepin, _status("liepin", "缺少本地 Cookie 文件"), preflight._PENDING_KIND_COOKIE_FILE),
    ]

    sent: list[str] = []

    async def fake_send(text: str) -> bool:
        sent.append(text)
        return True

    import app.automation.pipeline_report as pr
    monkeypatch.setattr(pr, "send_pipeline_report", fake_send)

    _run(preflight._notify_login_needed(items, wait_s=0, launched=set()))

    text = sent[0]
    assert "本轮不等待" in text
    assert "本轮不轮询登录状态" in text
    assert "检测到就会继续" not in text  # 不承诺系统会自动继续（P1 回归）
    assert "每 10 秒" not in text
    assert "浏览器没能自动打开" in text
    assert "「平台会话」" in text
    assert "「唤起浏览器」" in text
