"""已投递卡片物料与打招呼回执判定的回归测试（2026-09-15，纯逻辑无网络）。

覆盖 get_delivered_jobs_from_feishu 的四处收敛：
1. 长图简历仅 BOSS 专属：猎聘/智联/51job 已投递记录一律屏蔽，杜绝猎聘误展【长图简历】；
2. 打招呼回执只认明确的微聊受阻标记（智联真实回执），登录态残留等历史旧账不再误判「未送达」；
3. 返回结构补齐 is_custom / greeting_msg / job_url，供已投递快照推导精投/海投与欢迎语预览。
4. PDF 简历仅附件投递平台（猎聘/智联/51job）真实外发：BOSS 微聊只发长图，
   归档「PDF 备份」不得反推为已送达回执，杜绝 BOSS 误展【PDF简历】。
"""
import time
import pytest

from app.services import feishu_service as fs


class _FakeResp:
    def __init__(self, items):
        self._payload = {"code": 0, "data": {"items": items, "has_more": False, "page_token": None}}

    def json(self):
        return self._payload


_TODAY_TS = int(time.time() * 1000)


def _delivered_fields(**overrides):
    base = {
        "岗位名称": "智能座舱产品经理",
        "公司名称": "华勤技术",
        "招聘平台": "猎聘",
        "跟进状态": "已投递",
        "投递日期": _TODAY_TS,
        "打招呼语": "您好，看到贵司岗位与我的背景高度匹配，期待进一步沟通！",
        "图片保存": [{"file_token": "img1", "name": "通用简历-最新-长图.jpg"}],
        "PDF 备份": [{"file_token": "pdf1", "name": "通用简历-最新.pdf"}],
    }
    base.update(overrides)
    return base


def _run_delivered_query(monkeypatch, records):
    monkeypatch.setattr(fs, "get_tenant_access_token", lambda: "tok")
    monkeypatch.setattr(fs, "safe_feishu_request", lambda *a, **k: _FakeResp(records))
    return fs.get_delivered_jobs_from_feishu(max_pages=1, today_only=True)


def test_liepin_masks_image_and_stale_log_keeps_greeting_delivered(monkeypatch):
    """华勤现场还原：登录态残留日志 + 长图附件沉淀，修复后应屏蔽长图且打招呼判已送达"""
    fields = _delivered_fields()
    fields["自动投递失败日志"] = "猎聘登录态失效，请先在 9226 端口浏览器登录后重试"
    jobs = _run_delivered_query(monkeypatch, [{"record_id": "recL", "fields": fields}])

    assert len(jobs) == 1
    j = jobs[0]
    assert j["platform"] == "liepin"
    assert j["has_image"] is False, "猎聘为纯附件 PDF 投递平台，长图简历必须屏蔽（仅 BOSS 专属）"
    assert j["has_pdf"] is True
    assert j["has_greeting"] is True
    assert j["greeting_delivered"] is True, "登录态残留等历史旧账不得把真实送达误判为未送达"
    assert j["greeting_msg"].startswith("您好")
    assert j["is_custom"] is False, "无 AI改写JSON 且非 A/B 评级，应判海投"
    assert j["job_url"] == ""


def test_zhilian_blocked_marker_still_flags_greeting_undelivered(monkeypatch):
    """智联真实回执「[微聊受阻] ... 打招呼语未成功发送」必须如实判未送达，不得被新判定放过"""
    fields = _delivered_fields(招聘平台="智联招聘")
    fields["自动投递失败日志"] = "[微聊受阻] 附件简历已成功送达，打招呼语未成功发送"
    jobs = _run_delivered_query(monkeypatch, [{"record_id": "recZ", "fields": fields}])

    j = jobs[0]
    assert j["platform"] == "zhilian"
    assert j["has_image"] is False
    assert j["greeting_delivered"] is False, "微聊受阻真实回执必须判未送达，供台账补发打招呼"


def test_boss_keeps_image_and_masks_pdf_and_clean_log_delivers_greeting(monkeypatch):
    """BOSS 长图为专属物料应保留展示；归档 PDF 备份不得误判为已送达；无失败日志时打招呼判已送达"""
    fields = _delivered_fields(招聘平台="BOSS直聘")
    jobs = _run_delivered_query(monkeypatch, [{"record_id": "recB", "fields": fields}])

    j = jobs[0]
    assert j["platform"] == "boss"
    assert j["has_image"] is True, "BOSS 长图简历为专属物料，不得误屏蔽"
    assert j["has_pdf"] is False, "BOSS 微聊投递不外发 PDF，归档「PDF 备份」不得反推为已送达回执"
    assert j["greeting_delivered"] is True


def test_custom_record_exposes_is_custom_for_delivered_review_type(monkeypatch):
    """带 AI改写JSON 的已投递记录应透出 is_custom=True，供快照映射为精投物料"""
    fields = _delivered_fields(招聘平台="智联", AI改写JSON='{"summary": "定制改写产物"}')
    jobs = _run_delivered_query(monkeypatch, [{"record_id": "recC", "fields": fields}])

    assert jobs[0]["is_custom"] is True
    assert jobs[0]["has_image"] is False


def test_51job_strictly_masks_greeting_even_with_feishu_greeting_text(monkeypatch):
    """51job 为纯附件投递平台（中文「前程无忧」与英文「51job」），飞书即使残留打招呼语也必须严格屏蔽"""
    # 场景 1: 前程无忧 (中文) 海投
    fields_cn = _delivered_fields(招聘平台="前程无忧")
    jobs_cn = _run_delivered_query(monkeypatch, [{"record_id": "rec51_cn", "fields": fields_cn}])
    assert len(jobs_cn) == 1
    j_cn = jobs_cn[0]
    assert j_cn["platform"] == "51job"
    assert j_cn["has_pdf"] is True
    assert j_cn["has_image"] is False
    assert j_cn["has_greeting"] is False, "51job 不支持微聊外发，has_greeting 必须严格为 False"
    assert j_cn["greeting_delivered"] is False, "无打招呼语时 greeting_delivered 必须自洽为 False"

    # 场景 2: 51job (英文) 精投
    fields_en = _delivered_fields(招聘平台="51job", AI改写JSON='{"summary": "51job定制"}')
    jobs_en = _run_delivered_query(monkeypatch, [{"record_id": "rec51_en", "fields": fields_en}])
    assert len(jobs_en) == 1
    j_en = jobs_en[0]
    assert j_en["platform"] == "51job"
    assert j_en["is_custom"] is True
    assert j_en["has_greeting"] is False
    assert j_en["greeting_delivered"] is False


def test_positive_platforms_greeting_delivered_normal(monkeypatch):
    """正向防回归：BOSS直聘、智联招聘、猎聘带有打招呼语且未受阻时，必须保持 has_greeting=True 且 greeting_delivered=True"""
    records = [
        {"record_id": "rec_b", "fields": _delivered_fields(招聘平台="BOSS直聘")},
        {"record_id": "rec_z", "fields": _delivered_fields(招聘平台="智联招聘")},
        {"record_id": "rec_l", "fields": _delivered_fields(招聘平台="猎聘")},
    ]
    jobs = _run_delivered_query(monkeypatch, records)
    assert len(jobs) == 3

    b, z, l = jobs[0], jobs[1], jobs[2]
    assert b["platform"] == "boss" and b["has_greeting"] is True and b["greeting_delivered"] is True
    assert z["platform"] == "zhilian" and z["has_greeting"] is True and z["greeting_delivered"] is True
    assert l["platform"] == "liepin" and l["has_greeting"] is True and l["greeting_delivered"] is True


@pytest.mark.asyncio
async def test_build_jobs_snapshot_delivered_materials_and_ctime_integrity(monkeypatch):
    """验证 build_jobs_snapshot 装配已投递岗位时 c_time 正常赋值无 NameError，且 51job 严格屏蔽微聊物料"""
    from app.automation.snapshot_service import build_jobs_snapshot
    from app.services import feishu_service

    mock_delivered = [
        {
            "job_id": "rec_51",
            "job_name": "51产品经理",
            "company_name": "测试前程公司",
            "platform": "51job",
            "grade": "B",
            "salary": "15-20K",
            "city": "广州",
            "job_url": "https://jobs.51job.com/123.html",
            "company_scale": "500人",
            "is_custom": True,
            "has_pdf": True,
            "has_image": False,
            "has_greeting": False,
            "greeting_delivered": False,
            "delivered_at": "2026-09-17 10:00:00",
        },
        {
            "job_id": "rec_boss",
            "job_name": "BOSS产品经理",
            "company_name": "测试BOSS公司",
            "platform": "boss",
            "grade": "A",
            "salary": "25-35K",
            "city": "北京",
            "job_url": "https://zhipin.com/job/456.html",
            "company_scale": "1000人",
            "is_custom": True,
            "has_pdf": True,
            "has_image": True,
            "has_greeting": True,
            "greeting_delivered": True,
            "delivered_at": "2026-09-17 11:00:00",
        },
    ]

    monkeypatch.setattr(feishu_service, "get_delivered_jobs_from_feishu", lambda *args, **kwargs: mock_delivered)
    monkeypatch.setattr(feishu_service, "get_scheduled_delivery_jobs_from_feishu", lambda *args, **kwargs: [])
    monkeypatch.setattr(feishu_service, "get_pending_review_jobs_from_feishu", lambda *args, **kwargs: [])
    monkeypatch.setattr(feishu_service, "get_manual_rejected_jobs_from_feishu", lambda *args, **kwargs: [])

    snapshot = await build_jobs_snapshot()
    delivered_jobs = [j for j in snapshot.get("data", []) if j.get("status") == "delivered"]
    assert len(delivered_jobs) == 2

    job51 = next(j for j in delivered_jobs if j["job_id"] == "rec_51")
    assert "crawl_time" in job51
    assert job51["last_action_time"] == "2026-09-17 10:00:00"
    assert job51["delivery_materials"]["pdf"] is True
    assert job51["delivery_materials"]["image"] is False
    assert job51["delivery_materials"]["greeting"] is False
    assert job51["delivery_materials"]["greeting_failed"] is False

    job_boss = next(j for j in delivered_jobs if j["job_id"] == "rec_boss")
    assert job_boss["delivery_materials"]["pdf"] is False
    assert job_boss["delivery_materials"]["image"] is True
    assert job_boss["delivery_materials"]["greeting"] is True
    assert job_boss["delivery_materials"]["greeting_failed"] is False

