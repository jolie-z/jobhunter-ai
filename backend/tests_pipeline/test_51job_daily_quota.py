"""51job 附件上传日配额（720721）止损 + 海投优先编排回归测试。

背景：51job 附件简历上传按日限次且无余量查询接口，撞墙（status=720721）是唯一信号。
2026-09-16 改造后的契约：
- upload_quota 模块持久化「今日是否撞墙 / 今日成功上传次数 / 海投「我的简历」是否当日新鲜」；
- 引擎只在「确需上传」决策点止损（附件可复用的岗位不受配额耗尽影响），720721 时失败日志写
  upload_quota.QUOTA_EXHAUSTED_ERROR（[风控] 前缀 → 当日持久性跳过；跨天自动恢复）；
- 手动批量：51job 桶先海投后精投，精投发射前预检配额；
- 定时波次：51job 精投岗后移到波次末尾，精投预检配额，往日配额失败跨天清零计数后恢复发射；
- 分诊器：配额标记 + failed_at 早于今天 → 不跳过（且不落入 failure_count 重试上限门禁）。
"""
import importlib
import json
import os
import sys
import threading
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest

import app.automation.delivery_tasks as dt
import app.automation.routes.delivery_router as dr
import app.automation.run_snapshot as run_snapshot
import app.automation.scheduler as sched
import app.services.feishu_service as feishu_service
from app.automation import failure_triage as triage
from app.automation import upload_quota

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BACKEND_DIR, "51job_scraper"))
engine = importlib.import_module("51job_auto_delivery")

TODAY = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
QUOTA_ERR = upload_quota.QUOTA_EXHAUSTED_ERROR


# =====================================================================
# c) upload_quota 状态模块
# =====================================================================

def test_quota_state_defaults_and_marks():
    assert upload_quota.get_state() == {"date": TODAY, "uploads_used": 0, "exhausted": False, "mass_resume_date": ""}
    assert not upload_quota.is_exhausted_today()
    assert not upload_quota.is_mass_resume_fresh_today()

    upload_quota.mark_upload_success()
    upload_quota.mark_upload_success()
    upload_quota.mark_mass_resume_uploaded_today()
    upload_quota.mark_quota_exhausted()

    state = upload_quota.get_state()
    assert state["uploads_used"] == 2
    assert state["exhausted"] is True
    assert state["mass_resume_date"] == TODAY
    assert upload_quota.is_exhausted_today()
    assert upload_quota.is_mass_resume_fresh_today()
    with open(upload_quota.QUOTA_STATE_FILE, encoding="utf-8") as f:
        assert json.load(f) == state


def test_quota_state_resets_on_new_day():
    with open(upload_quota.QUOTA_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"date": YESTERDAY, "uploads_used": 5, "exhausted": True, "mass_resume_date": YESTERDAY}, f)
    assert not upload_quota.is_exhausted_today()
    assert not upload_quota.is_mass_resume_fresh_today()
    assert upload_quota.get_state()["uploads_used"] == 0
    # 新一天首次写入应以今日为基准，不继承昨日计数
    upload_quota.mark_upload_success()
    assert upload_quota.get_state() == {"date": TODAY, "uploads_used": 1, "exhausted": False, "mass_resume_date": ""}


def test_quota_state_tolerates_corrupt_file():
    with open(upload_quota.QUOTA_STATE_FILE, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert not upload_quota.is_exhausted_today()
    upload_quota.mark_quota_exhausted()
    assert upload_quota.is_exhausted_today()


def test_quota_error_text_is_consistent_with_triage_marker():
    assert QUOTA_ERR.startswith("[风控]")
    assert triage.DAILY_UPLOAD_QUOTA_MARKER in QUOTA_ERR
    assert len(QUOTA_ERR) <= 120, "引擎 _log_error 回写飞书截断 120 字，文案必须完整落进失败日志"


def test_quota_state_concurrent_writes_keep_file_parseable():  # i)
    def _worker():
        for _ in range(50):
            upload_quota.mark_upload_success()

    threads = [threading.Thread(target=_worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with open(upload_quota.QUOTA_STATE_FILE, encoding="utf-8") as f:
        assert json.load(f)["uploads_used"] == 200
    assert not os.path.exists(f"{upload_quota.QUOTA_STATE_FILE}.{os.getpid()}.tmp")


# =====================================================================
# a) b) h) 分诊器：当日持久、跨天恢复
# =====================================================================

def test_classify_quota_error_persistent():  # a)
    assert triage.classify_delivery_failure(f"❌ 51job投递受阻：{QUOTA_ERR}") == "persistent"


def test_quota_failure_same_day_skipped():
    skip, reason = triage.should_skip_auto_delivery(
        {"error": QUOTA_ERR, "failure_count": 1, "failed_at": f"{TODAY} 10:00:00"})
    assert skip and "持久性" in reason


def test_quota_failure_crossday_restores_auto_delivery():
    skip, reason = triage.should_skip_auto_delivery(
        {"error": QUOTA_ERR, "failure_count": 1, "failed_at": f"{YESTERDAY} 10:00:00"})
    assert (skip, reason) == (False, "")


def test_quota_failure_crossday_bypasses_retry_cap():
    skip, _ = triage.should_skip_auto_delivery(
        {"error": QUOTA_ERR, "failure_count": 5, "failed_at": f"{YESTERDAY} 10:00:00"})
    assert not skip, "跨天豁免必须先于 failure_count 重试上限门禁返回"


def test_quota_failure_without_failed_at_stays_skipped():
    skip, _ = triage.should_skip_auto_delivery({"error": QUOTA_ERR, "failure_count": 1})
    assert skip


def test_other_persistent_failure_not_exempted_by_crossday():
    skip, _ = triage.should_skip_auto_delivery(
        {"error": "[物料] 缺少 PDF 备份附件", "failure_count": 1, "failed_at": f"{YESTERDAY} 10:00:00"})
    assert skip, "跨天豁免仅适用于日配额标记，其他持久性故障仍留人工"


def test_is_stale_quota_failure_matrix():
    assert triage.is_stale_quota_failure({"error": QUOTA_ERR, "failed_at": f"{YESTERDAY} 09:00:00"})
    assert not triage.is_stale_quota_failure({"error": QUOTA_ERR, "failed_at": f"{TODAY} 09:00:00"})
    assert not triage.is_stale_quota_failure({"error": QUOTA_ERR})
    assert not triage.is_stale_quota_failure({"error": "登录态失效", "failed_at": f"{YESTERDAY} 09:00:00"})
    assert not triage.is_stale_quota_failure(None)


def test_quota_failure_survives_snapshot_serialization_roundtrip(monkeypatch):  # h)
    """台账条目经 record_delivery_failure 登记 → JSON 序列化往返（与 run_snapshot._save_to_db/_load_from_db 同款）
    → 分诊，failed_at 全程保留，跨天后恢复发射。"""
    monkeypatch.setattr(run_snapshot, "_save_to_db", lambda: None)
    run_snapshot._delivery_failures.pop("rec_quota_rt", None)
    try:
        run_snapshot.record_delivery_failure("rec_quota_rt", error=QUOTA_ERR, platform="51job", job_name="精投岗")
        # 模拟两次真实重试失败之间跨越了 15 秒去重防抖时间窗
        from datetime import datetime, timedelta
        run_snapshot._delivery_failures["rec_quota_rt"]["failed_at"] = (datetime.now() - timedelta(seconds=20)).strftime("%Y-%m-%d %H:%M:%S")
        run_snapshot.record_delivery_failure("rec_quota_rt", error=QUOTA_ERR, platform="51job", job_name="精投岗")
        entry = json.loads(json.dumps(run_snapshot._delivery_failures["rec_quota_rt"], ensure_ascii=False))
        assert entry["failure_count"] == 2 and entry["failed_at"].startswith(TODAY)
        assert triage.should_skip_auto_delivery(entry)[0] is True
        entry["failed_at"] = f"{YESTERDAY} 23:59:59"
        assert triage.should_skip_auto_delivery(entry) == (False, "")
    finally:
        run_snapshot._delivery_failures.pop("rec_quota_rt", None)


# =====================================================================
# d) 引擎 _upload_resume_to_51job：720721 → 状态文件撞墙；status=1 → 计数
# =====================================================================

class _Loc:
    def __init__(self, n=1, visible=True):
        self._n, self._vis = n, visible
    first = last = property(lambda self: self)
    def nth(self, i): return self
    def locator(self, sel): return self
    def count(self): return self._n
    def is_visible(self, timeout=None): return self._vis
    def click(self, **k): pass
    def scroll_into_view_if_needed(self): pass
    def clear(self): pass
    def fill(self, v): pass


class _FileChooserInfo:
    class _Chooser:
        def __init__(self): self.files = None
        def set_files(self, p): self.files = p
    def __init__(self): self.value = self._Chooser()
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _UploadPage:
    """驱动 _upload_resume_to_51job 一路走到「确认添加」并返回指定 add 业务响应的最小页面桩。

    slot_count: `div.myFile.resume` DOM 数（≥ATTACH_LIMIT 时触发删旧腾位流程）
    events: 可选事件序列收集器（记录 patch/reload/delete 等调用顺序）
    reload_raises: reload 是否抛异常（模拟真机 networkidle 45s 超时）
    add_status="none": 轮询 add 业务响应恒为 None（模拟补丁被冲掉收不到响应）
    """
    def __init__(self, add_status: str, slot_count: int = 1, events: list | None = None,
                 reload_raises: bool = False):
        self.add_status = add_status
        self.slot_count = slot_count
        self.events = events if events is not None else []
        self.reload_raises = reload_raises
        self.url = engine.RESUME_MANAGE_URL
        self.chooser = _FileChooserInfo()
    def goto(self, *a, **k): self.events.append("goto")
    def reload(self, *a, **k):
        self.events.append("reload")
        if self.reload_raises:
            raise Exception("Page.reload: Timeout 45000ms exceeded")
    def wait_for_load_state(self, *a, **k): pass
    def title(self): return "简历中心"
    def locator(self, sel):
        if sel in (".close-btn", "text=我知道了", "text=关闭"):
            return _Loc(n=0, visible=False)
        if sel == "div.myFile.resume":
            return _Loc(n=self.slot_count)
        return _Loc(n=1, visible=True)
    def expect_file_chooser(self, timeout=None): return self.chooser
    def evaluate(self, js, *args):
        if "attachment-resume/add" in js:          # JS_PATCH_ADD（补丁安装时机是断言对象）
            self.events.append("patch")
            return {"ok": True}
        if "__addResp" in js:                       # 轮询 add 业务响应
            if self.add_status == "none":
                return None
            return {"status": self.add_status, "message": "今日上传次数达上限" if self.add_status == "720721" else "ok"}
        return {"ok": True}


@pytest.fixture
def fake_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(engine.time, "sleep", lambda *a, **k: None)
    pdf = tmp_path / "公司_岗位.pdf"
    pdf.write_bytes(b"%PDF-fake")
    return str(pdf)


def test_upload_720721_marks_quota_exhausted_and_fails(fake_pdf):
    page = _UploadPage("720721")
    assert engine._upload_resume_to_51job(page, fake_pdf, "公司_岗位") is False
    assert page.chooser.value.files == fake_pdf
    state = upload_quota.get_state()
    assert state["exhausted"] is True and state["uploads_used"] == 0


def test_upload_success_counts_quota(fake_pdf):
    assert engine._upload_resume_to_51job(_UploadPage("1"), fake_pdf, "公司_岗位") is True
    state = upload_quota.get_state()
    assert state["exhausted"] is False and state["uploads_used"] == 1


# =====================================================================
# e) 引擎 deliver_job：「确需上传」决策点止损 / 可复用附件穿透 / 失败日志嵌套判定
# =====================================================================

class _JobPage:
    url = "https://jobs.51job.com/guangzhou/1.html"
    def goto(self, *a, **k): pass
    def reload(self, *a, **k): pass
    def route(self, *a, **k): pass
    def unroute(self, *a, **k): pass
    def wait_for_load_state(self, *a, **k): pass
    def title(self): return "测试岗位"
    def locator(self, sel): return _Loc(n=0, visible=False)
    def evaluate(self, js, *args):
        if "directApply" in js:
            # 幂等提前终止：投递本身不是本组测试的对象
            return {"ok": False, "err": "already applied", "isApply": True}
        return {"ok": True}


class _Ctx:
    def new_page(self): return _JobPage()


@pytest.fixture
def engine_stubs(monkeypatch):
    calls = {"download": 0, "upload": 0, "feishu": []}
    monkeypatch.setattr(engine.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(engine, "_connect_browser", lambda p: (None, _Ctx()))
    monkeypatch.setattr(engine, "_close_popups", lambda page: None)
    monkeypatch.setattr(engine, "_extract_job_info_from_page", lambda page: ("", ""))
    monkeypatch.setattr(engine, "update_feishu_record", lambda rid, fields, *a, **k: calls["feishu"].append((rid, fields)) or True)
    monkeypatch.setattr(engine, "_MASS_FORCE_UPLOAD", False)

    def _download(token, path):
        calls["download"] += 1
        with open(path, "wb") as f:
            f.write(b"%PDF-fake")
        return True

    def _upload(page, path, name):
        calls["upload"] += 1
        return True

    monkeypatch.setattr(engine, "download_feishu_file", _download)
    monkeypatch.setattr(engine, "_upload_resume_to_51job", _upload)

    def _set_attach_list(items):
        monkeypatch.setattr(engine, "_get_attach_list", lambda page, *a, **k: list(items))

    calls["set_attach_list"] = _set_attach_list
    return calls


def _custom_job():
    return {"record_id": "rec_c1", "job_url": _JobPage.url, "file_token": "tok", "pdf_name": "公司_岗位", "mass_apply": False}


def _mass_job(batch_mass_uploaded=False):
    return {"record_id": "rec_m1", "job_url": _JobPage.url, "file_token": "tok", "pdf_name": "我的简历",
            "mass_apply": True, "batch_mass_uploaded": batch_mass_uploaded}


def test_custom_job_blocked_at_upload_decision_when_quota_exhausted(engine_stubs):
    upload_quota.mark_quota_exhausted()
    engine_stubs["set_attach_list"]([])
    job = _custom_job()
    assert engine.deliver_job(job) is False
    assert job["delivery_error"] == QUOTA_ERR
    assert engine_stubs["download"] == 0 and engine_stubs["upload"] == 0, "止损必须发生在下载/上传之前"
    assert ("rec_c1", {"自动投递失败日志": QUOTA_ERR[:120]}) in engine_stubs["feishu"]


def test_custom_job_with_reviewed_attachment_passes_quota_gate(engine_stubs):
    """精投重试岗：同名附件已过审 → 零配额，配额耗尽也照常投递。"""
    upload_quota.mark_quota_exhausted()
    engine_stubs["set_attach_list"]([{"id": "77", "name": "公司_岗位", "status": "01"}])
    job = _custom_job()
    assert engine.deliver_job(job) is True
    assert "delivery_error" not in job
    assert engine_stubs["upload"] == 0


def test_mass_job_fresh_today_passes_quota_gate(engine_stubs):
    upload_quota.mark_quota_exhausted()
    upload_quota.mark_mass_resume_uploaded_today()
    engine_stubs["set_attach_list"]([{"id": "999", "name": engine.MASS_RESUME_NAME, "status": "01"}])
    job = _mass_job()
    assert engine.deliver_job(job) is True
    assert "delivery_error" not in job
    assert engine_stubs["upload"] == 0


def test_mass_batch_flag_alone_does_not_make_remote_fresh(engine_stubs, monkeypatch):
    """第 5 轮审查 P1：首岗幂等早退也会让编排层置位 batch_mass_uploaded，它不能作为新鲜度依据——
    远端同名附件无法验证为今日（缺 createTime / 非今日）时必须重传，且先清理同名旧附件。"""
    deleted: list = []
    monkeypatch.setattr(engine, "_delete_attachment_api", lambda pg, att_id, name="": (deleted.append(str(att_id)), True)[1])
    engine_stubs["set_attach_list"]([_att(999, engine.MASS_RESUME_NAME, YESTERDAY)])
    assert engine.deliver_job(_mass_job(batch_mass_uploaded=True)) is True
    assert engine_stubs["upload"] == 1, "batch 标志不得豁免对非今日远端附件的重传"
    assert deleted == ["999"], "非今日同名旧附件应在上传前清理"


def test_mass_job_stale_remote_blocked_when_quota_exhausted(engine_stubs):
    """远端「我的简历」非今日上传 → 需重传 → 配额耗尽则止损（不复用陈旧母本）。"""
    upload_quota.mark_quota_exhausted()
    engine_stubs["set_attach_list"]([{"id": "999", "name": engine.MASS_RESUME_NAME, "status": "01"}])
    job = _mass_job()
    assert engine.deliver_job(job) is False
    assert job["delivery_error"] == QUOTA_ERR
    assert engine_stubs["upload"] == 0


def test_mass_job_stale_remote_reuploads_once_when_quota_available(engine_stubs):
    engine_stubs["set_attach_list"]([{"id": "999", "name": engine.MASS_RESUME_NAME, "status": "01"}])
    assert engine.deliver_job(_mass_job()) is True
    assert engine_stubs["upload"] == 1
    assert upload_quota.is_mass_resume_fresh_today(), "海投上传成功后必须回写当日新鲜度供后续岗位复用"
    # 同日第二个海投岗：直接复用
    assert engine.deliver_job(_mass_job()) is True
    assert engine_stubs["upload"] == 1


def test_force_upload_falls_back_to_fresh_reuse_when_quota_exhausted(engine_stubs, monkeypatch):
    """executor 要求刷新母本，但配额已耗尽且远端有今日版本 → 退回复用而非整批失败。"""
    upload_quota.mark_quota_exhausted()
    upload_quota.mark_mass_resume_uploaded_today()
    monkeypatch.setattr(engine, "_MASS_FORCE_UPLOAD", True)
    engine_stubs["set_attach_list"]([{"id": "999", "name": engine.MASS_RESUME_NAME, "status": "01"}])
    assert engine.deliver_job(_mass_job()) is True
    assert engine_stubs["upload"] == 0
    assert engine._MASS_FORCE_UPLOAD is False, "退回复用后应清除强制刷新标志，保持会话状态自洽"


def test_upload_failure_log_marks_quota_only_when_exhausted(engine_stubs, monkeypatch):
    """第 1 轮复核 P1 回归：上传失败分支的配额判定必须可达。"""
    engine_stubs["set_attach_list"]([])

    def _upload_hits_720721(page, path, name):
        upload_quota.mark_quota_exhausted()   # 与真实 720721 分支同款副作用
        return False

    monkeypatch.setattr(engine, "_upload_resume_to_51job", _upload_hits_720721)
    job = _custom_job()
    assert engine.deliver_job(job) is False
    assert job["delivery_error"] == QUOTA_ERR

    monkeypatch.setattr(upload_quota, "QUOTA_STATE_FILE", upload_quota.QUOTA_STATE_FILE + ".fresh")
    monkeypatch.setattr(engine, "_upload_resume_to_51job", lambda page, path, name: False)
    job = _custom_job()
    assert engine.deliver_job(job) is False
    assert job["delivery_error"] == "附件简历上传失败"


# =====================================================================
# f) 手动批量编排：51job 先海后精 + 精投配额预检
# =====================================================================

_ROUTER_RECORDS = {
    "z_custom": {"fields": {"招聘平台": "智联招聘", "综合评级 (A-F)": "A", "公司名称": "智联精投", "岗位名称": "架构师", "AI改写JSON": "{}"}},
    "z_mass": {"fields": {"招聘平台": "智联招聘", "综合评级 (A-F)": "D", "公司名称": "智联海投", "岗位名称": "运营"}},
    "j_custom_1": {"fields": {"招聘平台": "51job", "综合评级 (A-F)": "B", "公司名称": "51精投甲", "岗位名称": "开发", "AI改写JSON": "{}"}},
    "j_mass_1": {"fields": {"招聘平台": "51job", "综合评级 (A-F)": "D", "公司名称": "51海投甲", "岗位名称": "测试"}},
    "j_custom_2": {"fields": {"招聘平台": "51job", "综合评级 (A-F)": "A", "公司名称": "51精投乙", "岗位名称": "产品", "AI改写JSON": "{}"}},
    "j_mass_2": {"fields": {"招聘平台": "51job", "综合评级 (A-F)": "C", "公司名称": "51海投乙", "岗位名称": "客服"}},
}
_ROUTER_INPUT = ["j_custom_1", "z_mass", "j_mass_1", "z_custom", "j_custom_2", "j_mass_2"]


@pytest.fixture
def router_env(monkeypatch):
    executed, flags, failures, feishu_logs = [], [], [], []

    async def _helper(t_id, item, batch_mass_uploaded=False):
        executed.append(t_id)
        flags.append((t_id, batch_mass_uploaded))
        return True

    monkeypatch.setattr(feishu_service, "get_job_record_from_feishu", lambda t_id, tbl: _ROUTER_RECORDS.get(t_id))
    monkeypatch.setattr(feishu_service, "update_feishu_record", lambda rid, fields, *a, **k: feishu_logs.append((rid, fields)) or True)
    monkeypatch.setattr(dr, "_deliver_single_job_helper", _helper)
    monkeypatch.setattr(dr, "_record_batch_delivery_failure", lambda t_id, item, err: failures.append((t_id, err)))
    monkeypatch.setattr("app.automation.materials.refresh_mass_materials_for_jobs", AsyncMock(return_value=0))
    return {"executed": executed, "flags": flags, "failures": failures, "feishu_logs": feishu_logs}


@pytest.mark.asyncio
async def test_router_51job_bucket_runs_mass_before_custom(router_env):
    await dr._deliver_approved_worker(list(_ROUTER_INPUT))
    # 智联维持先精后海；51job 先海后精；平台顺序智联 → 51job 不变
    assert router_env["executed"] == ["z_custom", "z_mass", "j_mass_1", "j_mass_2", "j_custom_1", "j_custom_2"]
    flags = dict(router_env["flags"])
    assert flags["j_mass_1"] is False and flags["j_mass_2"] is True, "海投批次标志在 51job 桶内同样递增复用"
    assert flags["j_custom_1"] is False and flags["j_custom_2"] is False
    assert router_env["failures"] == []


@pytest.mark.asyncio
async def test_router_51job_custom_skipped_when_quota_exhausted(router_env):
    upload_quota.mark_quota_exhausted()
    await dr._deliver_approved_worker(list(_ROUTER_INPUT))
    assert router_env["executed"] == ["z_custom", "z_mass", "j_mass_1", "j_mass_2"], "海投仍交引擎按复用规则决策，精投不唤起引擎"
    # 新方案：配额耗尽自动中断精投队列，未执行岗位保留在待投递，不记失败台账也不写飞书错误日志
    assert router_env["failures"] == []
    assert router_env["feishu_logs"] == []


# =====================================================================
# g) 定时波次：51job 精投后移 + 精投预检 + 跨天清零计数
# =====================================================================

def test_prioritize_51job_mass_is_stable_partition():
    targets = [
        {"job_id": "a", "platform": "51job", "is_custom": True},
        {"job_id": "b", "platform": "boss", "is_custom": True},
        {"job_id": "c", "platform": "51job", "is_custom": False},
        {"job_id": "d", "platform": "zhilian", "is_custom": False},
        {"job_id": "e", "platform": "51job", "is_custom": True},
    ]
    assert [j["job_id"] for j in dt._prioritize_51job_mass(targets)] == ["b", "c", "d", "a", "e"]


def _wave_jobs():
    return [
        {"job_id": "rec_51c_a", "job_name": "精投甲", "company_name": "A", "platform": "51job", "is_custom": True, "grade": "A"},
        {"job_id": "rec_boss", "job_name": "BOSS海投", "company_name": "B", "platform": "boss", "is_custom": False, "grade": "D"},
        {"job_id": "rec_51m", "job_name": "海投丙", "company_name": "C", "platform": "51job", "is_custom": False, "grade": "D"},
        {"job_id": "rec_51c_b", "job_name": "精投丁", "company_name": "D", "platform": "51job", "is_custom": True, "grade": "B"},
    ]


@pytest.fixture
def wave_env(monkeypatch):
    resumed, recorded, removed, feishu_logs, events, sent_reports = [], [], [], [], [], []
    monkeypatch.setattr(sched, "_delivery_guard_ok", lambda label: True)
    monkeypatch.setattr(sched, "pipeline_app", None)
    monkeypatch.setattr(sched, "get_autopilot_config", lambda: {"auto_deliver_platforms": ["boss", "liepin", "51job", "zhilian"]})
    monkeypatch.setattr(feishu_service, "get_scheduled_delivery_jobs_from_feishu",
                        lambda max_pages=5, respect_scheduled_time=False: _wave_jobs())
    monkeypatch.setattr(feishu_service, "update_feishu_record", lambda rid, fields, *a, **k: feishu_logs.append((rid, fields)) or True)
    monkeypatch.setattr(run_snapshot, "get_delivery_failures", lambda: {})
    monkeypatch.setattr(run_snapshot, "remove_delivery_failure", lambda rid: (removed.append(rid), events.append(("remove", rid))))
    monkeypatch.setattr(run_snapshot, "record_delivery_failure", lambda **kw: recorded.append(kw))
    monkeypatch.setattr("app.automation.materials.refresh_mass_materials_for_jobs", AsyncMock(return_value=0))

    async def _fake_send_round_report(**kw):
        sent_reports.append(kw)
        return True

    monkeypatch.setattr("app.services.delivery_card_notifier.send_delivery_round_report", _fake_send_round_report)

    async def _fake_resume(job_id: str):
        resumed.append(job_id)
        events.append(("resume", job_id))
        return True, "ok"

    monkeypatch.setattr(sched, "_resume_job_delivery", _fake_resume)
    return {"resumed": resumed, "recorded": recorded, "removed": removed, "feishu_logs": feishu_logs,
            "events": events, "sent_reports": sent_reports, "mp": monkeypatch}


@pytest.mark.asyncio
async def test_wave_moves_51job_custom_after_mass(wave_env):
    await sched.scheduled_delivery_batch_task("配额波次-排序")
    assert wave_env["resumed"] == ["rec_boss", "rec_51m", "rec_51c_a", "rec_51c_b"]
    assert len(wave_env["sent_reports"]) == 1
    report = wave_env["sent_reports"][0]
    assert report["window_label"] == "配额波次-排序"
    assert report["total_targets"] == 4
    assert len(report["ok_jobs"]) == 4
    assert len(report["failed_jobs"]) == 0
    assert report["skipped_cnt"] == 0


@pytest.mark.asyncio
async def test_wave_51job_custom_precheck_records_quota_failure(wave_env):
    upload_quota.mark_quota_exhausted()
    await sched.scheduled_delivery_batch_task("配额波次-耗尽")
    assert wave_env["resumed"] == ["rec_boss", "rec_51m"]
    assert [(r["job_id"], r["error"]) for r in wave_env["recorded"]] == [("rec_51c_a", QUOTA_ERR), ("rec_51c_b", QUOTA_ERR)]
    assert ("rec_51c_a", {"自动投递失败日志": QUOTA_ERR[:120]}) in wave_env["feishu_logs"]
    assert len(wave_env["sent_reports"]) == 1
    report = wave_env["sent_reports"][0]
    assert report["window_label"] == "配额波次-耗尽"
    assert report["total_targets"] == 4
    assert len(report["ok_jobs"]) == 2
    assert len(report["failed_jobs"]) == 2
    assert report["skipped_cnt"] == 0


@pytest.mark.asyncio
async def test_wave_crossday_quota_failure_resets_count_and_fires(wave_env):
    wave_env["mp"].setattr(run_snapshot, "get_delivery_failures", lambda: {
        "rec_51c_a": {"error": QUOTA_ERR, "failure_count": 3, "failed_at": f"{YESTERDAY} 14:30:00"},
        "rec_51c_b": {"error": QUOTA_ERR, "failure_count": 1, "failed_at": f"{TODAY} 10:00:00"},
    })
    await sched.scheduled_delivery_batch_task("配额波次-跨天")
    assert "rec_51c_a" in wave_env["resumed"], "昨日配额失败跨天必须恢复发射（不受 failure_count=3 影响）"
    assert "rec_51c_b" not in wave_env["resumed"], "今日配额失败当日持久跳过"
    # rec_51c_a 会被 remove 两次：一次是跨天豁免的计数清零（发射前），一次是发射成功后的常规清理
    a_events = [kind for kind, rid in wave_env["events"] if rid == "rec_51c_a"]
    assert a_events == ["remove", "resume", "remove"], f"跨天豁免应先清零计数再发射，实际事件序: {a_events}"
    assert "rec_51c_b" not in wave_env["removed"]
    assert len(wave_env["sent_reports"]) == 1
    report = wave_env["sent_reports"][0]
    assert report["window_label"] == "配额波次-跨天"
    assert report["total_targets"] == 4
    assert len(report["ok_jobs"]) == 3
    assert len(report["failed_jobs"]) == 0
    assert report["skipped_cnt"] == 1


# =====================================================================
# 真机实测（2026-09-16）暴露缺陷回归：登录态失效 / 滑动验证 → 结构化 [登录] 止损
# 此前写裸文案「附件简历上传失败」，分诊器归 unknown，用户看不出根因是登录态
# =====================================================================

class _Probe:
    def __init__(self, url="https://jobs.51job.com/guangzhou/1.html", title="某岗位招聘 | 前程无忧"):
        self.url, self._title = url, title
    def title(self): return self._title


def test_detect_login_block_matrix():
    from app.session.registry import PLATFORM_CONFIGS
    assert engine.LOGIN_PAGE_DOMAINS == tuple(PLATFORM_CONFIGS["51job"].login_page_indicators), "登录域名应与 registry 单一真理源一致"
    assert engine._detect_login_block(_Probe()) == ""
    assert engine._detect_login_block(_Probe(url="https://login.51job.com/login.php?lang=c")) == engine.LOGIN_LOST_ERROR
    assert engine._detect_login_block(_Probe(url="https://passport.51job.com/x")) == engine.LOGIN_LOST_ERROR
    assert engine._detect_login_block(_Probe(title="滑动验证页面")) == engine.SLIDER_VERIFY_ERROR
    for msg in (engine.LOGIN_LOST_ERROR, engine.SLIDER_VERIFY_ERROR):
        assert msg.startswith("[登录]") and len(msg) <= 120
        assert triage.classify_delivery_failure(msg) == "transient", "登录类故障应可在用户重新登录后自动重试"


def test_slider_verification_page_fails_fast_with_login_marker(engine_stubs, monkeypatch):
    monkeypatch.setattr(_JobPage, "title", lambda self: "滑动验证页面")
    engine_stubs["set_attach_list"]([])
    job = _custom_job()
    assert engine.deliver_job(job) is False
    assert job["delivery_error"] == engine.SLIDER_VERIFY_ERROR
    assert engine_stubs["download"] == 0 and engine_stubs["upload"] == 0, "滑块页应在下载/上传之前止损"
    assert ("rec_c1", {"自动投递失败日志": engine.SLIDER_VERIFY_ERROR[:120]}) in engine_stubs["feishu"]


def test_login_redirect_on_job_page_fails_fast(engine_stubs, monkeypatch):
    monkeypatch.setattr(_JobPage, "url", "https://login.51job.com/login.php?lang=c&url=https%3A%2F%2Fjobs.51job.com")
    engine_stubs["set_attach_list"]([])
    job = _custom_job()
    assert engine.deliver_job(job) is False
    assert job["delivery_error"] == engine.LOGIN_LOST_ERROR
    assert engine_stubs["upload"] == 0


def test_upload_failure_after_login_redirect_logs_login_marker(engine_stubs, monkeypatch):
    """岗位页正常但简历中心跳登录页（真机实测现场路径）→ 上传失败分支写 [登录] 而非裸文案。"""
    engine_stubs["set_attach_list"]([])

    def _upload_redirected(page, path, name):
        page.url = "https://login.51job.com/login.php?lang=c&url=https%3A%2F%2Fwww.51job.com%2Fresume%2Fcenter"
        return False

    monkeypatch.setattr(engine, "_upload_resume_to_51job", _upload_redirected)
    job = _custom_job()
    assert engine.deliver_job(job) is False
    assert job["delivery_error"] == engine.LOGIN_LOST_ERROR


def test_quota_marker_takes_precedence_over_login_redirect(engine_stubs, monkeypatch):
    """当日已撞墙是天级阻塞，即便本次还叠加了登录跳转，也优先写配额标记。"""
    upload_quota.mark_quota_exhausted()
    engine_stubs["set_attach_list"]([])
    job = _custom_job()
    assert engine.deliver_job(job) is False
    assert job["delivery_error"] == QUOTA_ERR


# =====================================================================
# 2026-09-16 真机第二次实测（三岗连锁失败）暴露的「槽位满 3 份」路径缺陷回归
# =====================================================================

def test_patch_installed_after_slot_cleanup_reload(fake_pdf, monkeypatch):
    """补丁必须在「删旧腾位 + reload」之后安装：此前装在 reload 前，响应截获被冲掉，
    已成功的上传被误判失败（真机：如约出行 120s 无响应）。"""
    events: list = []
    page = _UploadPage("1", slot_count=3, events=events)
    monkeypatch.setattr(engine, "_free_attachment_slot", lambda pg: (events.append("delete"), True)[1])
    assert engine._upload_resume_to_51job(page, fake_pdf, "我的简历") is True
    assert events.index("delete") < events.index("reload") < events.index("patch"), \
        f"补丁安装必须晚于删旧与 reload，实际事件序: {events}"


def test_rename_failure_does_not_abort_upload(fake_pdf, monkeypatch):
    """重命名三点菜单点击超时不得把「附件已上传成功」整岗判死（真机：金穗丰）。"""
    def _boom(page, name):
        raise Exception("Locator.click: Timeout 30000ms exceeded")
    monkeypatch.setattr(engine, "_rename_latest_attachment", _boom)
    assert engine._upload_resume_to_51job(_UploadPage("1"), fake_pdf, "我的简历") is True
    assert upload_quota.get_state()["uploads_used"] == 1


def test_cleanup_reload_timeout_tolerated(fake_pdf, monkeypatch):
    """删旧后的 reload 超时只告警不中断（真机：康润生物 networkidle 45s 超时整岗中断）。"""
    events: list = []
    page = _UploadPage("1", slot_count=3, events=events, reload_raises=True)
    monkeypatch.setattr(engine, "_free_attachment_slot", lambda pg: True)
    assert engine._upload_resume_to_51job(page, fake_pdf, "我的简历") is True


def test_add_resp_lost_but_list_grew_today_counts_success(fake_pdf, monkeypatch):
    """收不到 add 响应时回查附件列表：数量增长 + 今日同名新附件 → 判成功并补记配额。"""
    from datetime import date as _date
    today = _date.today().isoformat()
    page = _UploadPage("none", slot_count=1)   # before_count=1
    monkeypatch.setattr(engine, "_get_attach_list", lambda pg, *a, **k: [
        {"id": "1", "name": "旧附件", "status": "01", "createTime": "2026-01-01"},
        {"id": "2", "name": "我的简历", "status": "01", "createTime": today},
    ])
    assert engine._upload_resume_to_51job(page, fake_pdf, "我的简历") is True
    assert upload_quota.get_state()["uploads_used"] == 1, "兜底确认成功必须补记配额"


def test_add_resp_lost_and_list_unchanged_still_fails(fake_pdf, monkeypatch):
    page = _UploadPage("none", slot_count=1)
    monkeypatch.setattr(engine, "_get_attach_list", lambda pg, *a, **k: [
        {"id": "1", "name": "旧附件", "status": "01", "createTime": "2026-01-01"},
    ])
    assert engine._upload_resume_to_51job(page, fake_pdf, "我的简历") is False


def test_mass_remote_create_time_today_reuses_and_heals_marker(engine_stubs):
    """本地新鲜标记丢失时，远端 createTime=今天 也能触发复用并回写本地标记（防重复烧配额）。"""
    from datetime import date as _date
    engine_stubs["set_attach_list"](
        [{"id": "999", "name": engine.MASS_RESUME_NAME, "status": "01", "createTime": _date.today().isoformat()}])
    assert engine.deliver_job(_mass_job()) is True
    assert engine_stubs["upload"] == 0
    assert upload_quota.is_mass_resume_fresh_today(), "远端今日信号应回写本地标记完成自愈"


# =====================================================================
# 2026-09-16 用户人工验收发现 P0：精投「清场」删掉当日海投附件 → 海投投递记录简历悬空
# 回退为默认（精投）简历。修复契约：绝不删今日附件；精投不再清场；上传前清理同名非今日旧附件
# =====================================================================

def _att(id_, name, create_time, status="01"):
    return {"id": str(id_), "name": name, "status": status, "createTime": create_time}


def test_free_slot_prefers_oldest_non_today_and_spares_today(monkeypatch):
    deleted: list = []
    monkeypatch.setattr(engine, "_delete_attachment_api", lambda pg, att_id, name="": (deleted.append(str(att_id)), True)[1])
    monkeypatch.setattr(engine, "_get_attach_list", lambda pg, *a, **k: [
        _att(1, "我的简历", TODAY), _att(2, "旧A", "2026-09-10"), _att(3, "旧B", "2026-09-14"),
    ])
    assert engine._free_attachment_slot(object()) is True
    assert deleted == ["2"], "应删除非今日中最旧的一份（2026-09-10），且绝不碰今日附件"


def test_free_slot_refuses_when_all_today(monkeypatch):
    deleted: list = []
    monkeypatch.setattr(engine, "_delete_attachment_api", lambda pg, att_id, name="": (deleted.append(str(att_id)), True)[1])
    monkeypatch.setattr(engine, "_get_attach_list", lambda pg, *a, **k: [
        _att(1, "我的简历", TODAY), _att(2, "甲_岗位", TODAY), _att(3, "乙_岗位", TODAY),
    ])
    assert engine._free_attachment_slot(object()) is False
    assert deleted == [], "全为今日附件时宁可放弃也不删除（保护今日投递记录的附件绑定）"
    assert engine._LAST_UPLOAD_BLOCK == engine.SLOTS_FULL_TODAY_ERROR


def test_free_slot_noop_when_not_full(monkeypatch):
    deleted: list = []
    monkeypatch.setattr(engine, "_delete_attachment_api", lambda pg, att_id, name="": (deleted.append(str(att_id)), True)[1])
    monkeypatch.setattr(engine, "_get_attach_list", lambda pg, *a, **k: [_att(1, "旧A", "2026-09-10")])
    assert engine._free_attachment_slot(object()) is True
    assert deleted == []


def test_upload_blocked_when_slots_full_of_today(fake_pdf, monkeypatch):
    page = _UploadPage("1", slot_count=3)
    monkeypatch.setattr(engine, "_get_attach_list", lambda pg, *a, **k: [
        _att(1, "我的简历", TODAY), _att(2, "甲_岗位", TODAY), _att(3, "乙_岗位", TODAY),
    ])
    assert engine._upload_resume_to_51job(page, fake_pdf, "丙_岗位") is False
    assert engine._LAST_UPLOAD_BLOCK == engine.SLOTS_FULL_TODAY_ERROR
    assert page.chooser.value.files is None, "放弃腾位时不得进入文件选择/上传"
    assert upload_quota.get_state()["uploads_used"] == 0
    assert triage.classify_delivery_failure(engine.SLOTS_FULL_TODAY_ERROR) == "persistent", "[简历] 标记 → 当日不再自动重试，转人工"


def test_upload_frees_non_today_slot_then_uploads(fake_pdf, monkeypatch):
    deleted: list = []
    monkeypatch.setattr(engine, "_delete_attachment_api", lambda pg, att_id, name="": (deleted.append(str(att_id)), True)[1])
    monkeypatch.setattr(engine, "_get_attach_list", lambda pg, *a, **k: [
        _att(1, "旧A", "2026-09-10"), _att(2, "我的简历", TODAY), _att(3, "甲_岗位", TODAY),
    ])
    page = _UploadPage("1", slot_count=3)
    assert engine._upload_resume_to_51job(page, fake_pdf, "丙_岗位") is True
    assert deleted == ["1"]
    assert engine._LAST_UPLOAD_BLOCK == ""


def test_deliver_job_writes_resume_marker_when_slots_full_today(engine_stubs, monkeypatch):
    engine_stubs["set_attach_list"]([])

    def _upload_blocked(page, path, name):
        engine._LAST_UPLOAD_BLOCK = engine.SLOTS_FULL_TODAY_ERROR
        return False

    monkeypatch.setattr(engine, "_upload_resume_to_51job", _upload_blocked)
    job = _custom_job()
    assert engine.deliver_job(job) is False
    assert job["delivery_error"] == engine.SLOTS_FULL_TODAY_ERROR


def test_mass_stale_same_name_deleted_before_upload(engine_stubs, monkeypatch):
    """用户契约：上传前先删同名非当日旧附件（防 V1/V2 堆叠），再传当日最新版；当日同名则复用不删。"""
    deleted: list = []
    monkeypatch.setattr(engine, "_delete_attachment_api", lambda pg, att_id, name="": (deleted.append(str(att_id)), True)[1])
    engine_stubs["set_attach_list"]([_att(11, "我的简历V1", "2026-09-14"), _att(12, "我的简历", YESTERDAY)])
    assert engine.deliver_job(_mass_job()) is True
    assert sorted(deleted) == ["11", "12"], "同名（含 V 后缀前缀匹配）非今日旧附件应在上传前全部删除"
    assert engine_stubs["upload"] == 1
    assert upload_quota.is_mass_resume_fresh_today()


def test_mass_today_same_name_reused_without_delete(engine_stubs, monkeypatch):
    deleted: list = []
    monkeypatch.setattr(engine, "_delete_attachment_api", lambda pg, att_id, name="": (deleted.append(str(att_id)), True)[1])
    engine_stubs["set_attach_list"]([_att(12, "我的简历", TODAY)])
    assert engine.deliver_job(_mass_job()) is True
    assert deleted == [] and engine_stubs["upload"] == 0


def test_custom_job_never_deletes_other_attachments(engine_stubs, monkeypatch):
    """精投不再「清场」：列表里的当日海投附件必须原样保留（它已绑定今日海投投递记录）。"""
    deleted: list = []
    monkeypatch.setattr(engine, "_delete_attachment_api", lambda pg, att_id, name="": (deleted.append(str(att_id)), True)[1])
    monkeypatch.setattr(engine, "_free_attachment_slot", lambda pg: (deleted.append("SLOT"), True)[1])
    engine_stubs["set_attach_list"]([_att(77, "公司_岗位", TODAY), _att(12, "我的简历", TODAY)])
    job = _custom_job()
    assert engine.deliver_job(job) is True
    assert deleted == [], "精投路径不得删除任何其他附件"
    assert engine_stubs["upload"] == 0


# =====================================================================
# 上传前幂等预检：此前已投过的岗位不再白烧一次上传配额
# =====================================================================

class _AppliedProbe:
    def __init__(self, results):
        self._results = list(results)
    def evaluate(self, js, *a):
        r = self._results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_check_already_applied_matrix(monkeypatch):
    monkeypatch.setattr(engine.time, "sleep", lambda *a, **k: None)
    assert engine._check_already_applied(_AppliedProbe([{"ok": True, "isApply": True}])) == (True, True)
    assert engine._check_already_applied(_AppliedProbe([{"ok": True, "isApply": False}])) == (True, False)
    # 组件未挂载：重试用尽后返回「组件不存在」，由调用方结合岗位信息判定是否下架
    assert engine._check_already_applied(_AppliedProbe([{"ok": False}, {"ok": False}, {"ok": False}]), tries=3) == (False, False)
    # 探测异常同样按「组件不存在」
    assert engine._check_already_applied(_AppliedProbe([RuntimeError("ctx destroyed")] * 3), tries=3) == (False, False)


def test_already_applied_job_exits_before_any_upload(engine_stubs, monkeypatch):
    def _evaluate(self, js, *a):
        if "CHECK_APPLIED" in js:
            return {"ok": True, "isApply": True, "jobId": "1"}
        return {"ok": True}
    monkeypatch.setattr(_JobPage, "evaluate", _evaluate)
    engine_stubs["set_attach_list"]([])
    job = _custom_job()
    assert engine.deliver_job(job) is True
    assert engine_stubs["download"] == 0 and engine_stubs["upload"] == 0, "已投岗位不得进入下载/上传"
    assert "delivery_error" not in job
    rid, fields = engine_stubs["feishu"][-1]
    assert rid == "rec_c1" and fields["跟进状态"] == "已投递" and fields["自动投递失败日志"] == ""
    assert upload_quota.get_state()["uploads_used"] == 0


def test_free_slot_gives_up_when_api_delete_fails(monkeypatch):
    """第 4 轮 P2：API 删除失败不再回退按 DOM 顺序的 UI 删除（无法保证删的是非今日附件）。"""
    monkeypatch.setattr(engine, "_delete_attachment_api", lambda pg, att_id, name="": False)
    monkeypatch.setattr(engine, "_get_attach_list", lambda pg, *a, **k: [
        _att(1, "旧A", "2026-09-10"), _att(2, "我的简历", TODAY), _att(3, "甲_岗位", TODAY),
    ])
    assert engine._free_attachment_slot(object()) is False
    assert engine._LAST_UPLOAD_BLOCK == engine.SLOT_FREE_FAILED_ERROR, "API 删除失败应给出区别于「全为今日」的精准文案"


# =====================================================================
# agy 真机实测（2026-09-16 23:5x）暴露：下架岗位页无投递组件仍上传白烧配额；海投新附件未过审无 ID 可挂
# =====================================================================

def test_invalid_job_page_fails_before_upload(engine_stubs, monkeypatch):
    """标题仅「招聘 | 前程无忧」且无投递组件 → [下架] 止损于上传之前（真机：广州发展集团岗）。"""
    def _evaluate(self, js, *a):
        if "CHECK_APPLIED" in js:
            return {"ok": False, "err": "no ApplyjobBtn/detailData"}
        return {"ok": True}
    monkeypatch.setattr(_JobPage, "evaluate", _evaluate)
    monkeypatch.setattr(_JobPage, "title", lambda self: "招聘 | 前程无忧")
    engine_stubs["set_attach_list"]([])
    job = _custom_job()
    assert engine.deliver_job(job) is False
    assert job["delivery_error"] == engine.JOB_PAGE_INVALID_ERROR
    assert engine_stubs["download"] == 0 and engine_stubs["upload"] == 0
    assert triage.classify_delivery_failure(engine.JOB_PAGE_INVALID_ERROR) == "persistent"


def test_component_missing_but_page_has_job_info_proceeds(engine_stubs, monkeypatch):
    """组件暂未挂载但页面有岗位信息（慢加载）→ 不误判下架，照常进入后续流程。"""
    def _evaluate(self, js, *a):
        if "CHECK_APPLIED" in js:
            return {"ok": False}
        if "directApply" in js:
            return {"ok": False, "err": "already applied", "isApply": True}
        return {"ok": True}
    monkeypatch.setattr(_JobPage, "evaluate", _evaluate)
    monkeypatch.setattr(engine, "_extract_job_info_from_page", lambda page: ("某公司", "某岗位"))
    engine_stubs["set_attach_list"]([_att(77, "公司_岗位", TODAY)])
    assert engine.deliver_job(_custom_job()) is True


def test_pick_target_attachment_only_considers_today():
    """第 5 轮审查 P1：上传后选目标只在今日附件里选，历史过审同名附件绝不截胡今日新版。"""
    lst = [_att(1, "我的简历", TODAY, status="02"), _att(2, "我的简历V2", "2026-09-10", status="01")]
    # 旧日期已过审的 V2 不得被选中；海投回退到今日审核中的那份
    assert engine._pick_target_attachment(lst, "我的简历", allow_unreviewed_today=True)["id"] == "1"
    # 精投不允许审核中 → 无今日已过审即 None（不会退到旧附件）
    assert engine._pick_target_attachment(lst, "我的简历", allow_unreviewed_today=False) is None
    # 今日已过审优先于今日审核中
    lst3 = [_att(1, "我的简历", TODAY, status="02"), _att(3, "我的简历", TODAY, status="01")]
    assert engine._pick_target_attachment(lst3, "我的简历", allow_unreviewed_today=True)["id"] == "3"
    # 昨日审核中的不算
    assert engine._pick_target_attachment([_att(1, "我的简历", YESTERDAY, status="02")], "我的简历", True) is None


def test_mass_upload_waits_for_review_to_resolve_attach_id(engine_stubs, monkeypatch):
    waited: list = []
    monkeypatch.setattr(engine, "_wait_until_reviewed_api", lambda page, name: (waited.append(name), True)[1])
    engine_stubs["set_attach_list"]([])   # 无「我的简历」→ 上传
    assert engine.deliver_job(_mass_job()) is True
    assert engine_stubs["upload"] == 1
    assert waited == [engine.MASS_RESUME_NAME], "海投上传后必须等待过审以拿到可挂接的附件 ID"


def test_offline_page_text_blocks_before_upload(engine_stubs, monkeypatch):
    """agy 真机复核建议：正文「当前职位审核中或已下线」即 [下架] 止损，即便组件探测结果为存在。"""
    class _OfflineLoc(_Loc):
        pass
    def _locator(self, sel):
        return _Loc(n=1, visible=True) if "已下线" in sel else _Loc(n=0, visible=False)
    monkeypatch.setattr(_JobPage, "locator", _locator)
    monkeypatch.setattr(engine, "_extract_job_info_from_page", lambda page: ("某公司", "某岗位"))
    engine_stubs["set_attach_list"]([])
    job = _custom_job()
    assert engine.deliver_job(job) is False
    assert job["delivery_error"] == engine.JOB_PAGE_INVALID_ERROR
    assert engine_stubs["upload"] == 0


def test_mass_step35_backfills_target_id(engine_stubs, monkeypatch):
    """海投上传后过审等待仍未拿到 ID 时，Step 3.5 体检列表出现同名今日附件即回填，Step 6 才有 ID 可挂。"""
    seen = {"attach_calls": []}
    monkeypatch.setattr(engine, "_wait_until_reviewed_api", lambda page, name: False)
    # 上传后第一次读列表为空（审核延迟），体检时已出现今日「我的简历」(审核中)
    calls = {"n": 0}
    def _attach_list(page, *a, **k):
        calls["n"] += 1
        return [] if calls["n"] <= 2 else [_att(555, engine.MASS_RESUME_NAME, TODAY, status="02")]
    monkeypatch.setattr(engine, "_get_attach_list", _attach_list)
    # 让 Step 5 走真实投递成功分支以到达 Step 6，再由挂接函数记录收到的 target_id
    def _evaluate(self, js, *a):
        if "CHECK_APPLIED" in js:
            return {"ok": True, "isApply": False}
        if "directApply" in js:
            return {"ok": True, "status": "1", "cvLogIds": ["cv1"], "popup": None, "message": ""}
        return {"ok": True}
    monkeypatch.setattr(_JobPage, "evaluate", _evaluate)
    monkeypatch.setattr(engine, "_attach_resume_to_apply",
                        lambda page, cv, popup, name, target_id=None, job_url="": (seen["attach_calls"].append(target_id), True)[1])
    assert engine.deliver_job(_mass_job()) is True
    assert seen["attach_calls"] == ["555"], "Step 6 必须拿到回填后的附件 ID"


def test_invalid_page_check_requires_both_company_and_title_missing(engine_stubs, monkeypatch):
    """第 5 轮审查 P1：组件未挂载 + 只解析出公司或岗位之一 → 视为慢加载，不得误判 [下架]。"""
    def _evaluate(self, js, *a):
        if "CHECK_APPLIED" in js:
            return {"ok": False}
        if "directApply" in js:
            return {"ok": False, "err": "already applied", "isApply": True}
        return {"ok": True}
    monkeypatch.setattr(_JobPage, "evaluate", _evaluate)
    monkeypatch.setattr(engine, "_extract_job_info_from_page", lambda page: ("某公司", None))
    engine_stubs["set_attach_list"]([_att(77, "公司_岗位", TODAY)])
    job = _custom_job()
    assert engine.deliver_job(job) is True
    assert "delivery_error" not in job
