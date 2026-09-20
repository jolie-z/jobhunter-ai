"""全渠道极速录入双步式闭环与查重管线测试 (@TestDriven)。

覆盖：
1. 平台判定单一事实源（含 xhslink / xiaohongshu / 规范名与别名归一）；
2. 解析质量评估（P0 硬缺失阻断 / 软缺失区分度 / 链接缺失预警）；
3. 图文混合合并（视觉打底，文本非占位值覆盖）；
4. 本地 JobCache 毫秒级查重与飞书降级查重；
5. confirm 确认落库（三层查重防线、SQLite raw_jobs 历史池同步、JobCache 打脏）；
6. FastAPI 路由契约（/parse 与 /confirm 状态码 422 / 409 / 200）。
"""
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.cache import JobCache
from app.jobs import service
from app.jobs.router import router as jobs_router
from app.session.registry import canonicalize_platform_name, detect_platform_by_url


# ==========================================
# 1. 平台判定与口径归一测试
# ==========================================
def test_platform_detection_by_url():
    assert detect_platform_by_url("https://www.zhipin.com/job_detail/abc123.html") == "BOSS直聘"
    assert detect_platform_by_url("https://m.zhipin.com/mpa/html/weijd/weijd-job/abc123") == "BOSS直聘"
    assert detect_platform_by_url("https://www.xiaohongshu.com/discovery/item/xyz") == "小红书"
    assert detect_platform_by_url("http://xhslink.com/a/abc123") == "小红书"
    assert detect_platform_by_url("https://www.zhaopin.com/jobs/999.htm") == "智联招聘"
    assert detect_platform_by_url("https://jobs.51job.com/shanghai/123.html") == "前程无忧"
    assert detect_platform_by_url("https://www.liepin.com/job/888.shtml") == "猎聘"
    assert detect_platform_by_url("https://unknown-platform.com/post/1") == "未知"
    assert detect_platform_by_url("") == "未知"


def test_platform_canonicalization():
    assert canonicalize_platform_name("boss直聘") == "BOSS直聘"
    assert canonicalize_platform_name("BOSS") == "BOSS直聘"
    assert canonicalize_platform_name("51job") == "前程无忧"
    assert canonicalize_platform_name("前程无忧51job") == "前程无忧"
    assert canonicalize_platform_name("智联") == "智联招聘"
    assert canonicalize_platform_name("zhilian") == "智联招聘"
    assert canonicalize_platform_name("xhs") == "小红书"
    assert canonicalize_platform_name("截图解析") == "未知"
    assert canonicalize_platform_name("未知") == "未知"
    assert canonicalize_platform_name("-") == "未知"
    assert canonicalize_platform_name("") == "未知"
    assert canonicalize_platform_name("微信朋友圈") == "微信朋友圈"


# ==========================================
# 2. 字段质量与缺失评估测试
# ==========================================
def test_assess_parse_quality():
    # 正常全量字段
    full_fields = {
        "公司名称": "测试科技",
        "岗位名称": "Python开发工程师",
        "岗位详情": "负责后端架构开发...",
        "薪资": "25-35K",
        "城市": "北京",
        "经验要求": "3-5年",
        "学历要求": "本科",
        "岗位链接": "https://www.zhipin.com/job_detail/123.html",
    }
    q1 = service.assess_parse_quality(full_fields)
    assert q1["hard_missing"] == []
    assert q1["soft_missing"] == []
    assert q1["link_missing"] is False

    # 硬缺失与占位符测试
    broken_fields = {
        "公司名称": "未知猎头/公司",  # 命中占位符
        "岗位名称": "-",              # 命中占位符
        "岗位详情": "",               # 空值
        "薪资": "未知",               # 软缺失
        "城市": "上海",
        "经验要求": "-",              # 软缺失
        "学历要求": "本科",
    }
    q2 = service.assess_parse_quality(broken_fields)
    assert set(q2["hard_missing"]) == {"公司名称", "岗位名称", "岗位详情"}
    assert set(q2["soft_missing"]) == {"薪资", "经验要求"}
    assert q2["link_missing"] is True


# ==========================================
# 3. 图文混合合并逻辑测试
# ==========================================
def test_merge_parsed_fields():
    vision_fields = {
        "公司名称": "视觉真实公司",
        "岗位名称": "全栈开发工程师",
        "城市": "广州",
        "薪资": "15-20K",
        "岗位详情": "视觉长文本职责与任职资格详细内容，字数远远超过五十个字，坚决不能被文本覆盖！" * 2,
        "招聘平台": "智联招聘",
    }
    # 场景 1：文本路为虚假公司/岗位，但未识别薪资 -> 视觉核心事实完好保护
    text_fields_fake = {
        "公司名称": "文本虚假公司",  # 视觉已有真实公司，坚决保留视觉真实公司，防止被文本覆盖
        "岗位名称": "产品专家",      # 视觉已有真实岗位，坚决保留视觉
        "薪资": "-",                 # 文本未识别，保留视觉
        "工作地址": "广州黄埔区华美国际中心", # 视觉缺失，由文本补齐
        "岗位链接": "https://m.zhaopin.com/jobs/123.html", # 视觉缺失，由文本补齐
    }
    merged1 = service._merge_parsed_fields(vision_fields, text_fields_fake)
    assert merged1["公司名称"] == "视觉真实公司"
    assert merged1["岗位名称"] == "全栈开发工程师"
    assert merged1["城市"] == "广州"
    assert merged1["薪资"] == "15-20K"
    assert "视觉长文本职责" in merged1["岗位详情"]
    assert merged1["工作地址"] == "广州黄埔区华美国际中心"
    assert merged1["岗位链接"] == "https://m.zhaopin.com/jobs/123.html"

    # 场景 2：TODO.md Step 6 图文同传无损合并（文本手写明确补充薪资 50-70K 与岗位链接）
    text_fields_supplement = {
        "公司名称": "-",
        "岗位名称": "-",
        "薪资": "50-70K",
        "岗位链接": "https://www.zhipin.com/job_detail/test123.html",
        "岗位详情": "-",
    }
    merged2 = service._merge_parsed_fields(vision_fields, text_fields_supplement)
    assert merged2["公司名称"] == "视觉真实公司"  # 视觉公司保留
    assert merged2["岗位名称"] == "全栈开发工程师"  # 视觉岗位保留
    assert merged2["薪资"] == "50-70K"           # 文本手写补充薪资成功覆盖！
    assert merged2["岗位链接"] == "https://www.zhipin.com/job_detail/test123.html" # 链接成功补充
    assert "视觉长文本职责" in merged2["岗位详情"]   # 截图长文本 100% 保真


# ==========================================
# 4. 本地 JobCache 加速查重测试
# ==========================================
@pytest.mark.asyncio
async def test_find_duplicate_job_via_cache(monkeypatch):
    cached = [
        {
            "record_id": "rec_001",
            "company_name": "[猎头] 字节跳动",
            "job_name": "后端架构师",
            "follow_status": "新线索",
            "job_link": "https://www.zhipin.com/job_detail/123.html",
        },
        {
            "record_id": "rec_002",
            "company_name": "阿里巴巴",
            "job_name": "Java专家",
            "follow_status": "一面",
            "job_link": "https://www.zhipin.com/job_detail/456.html",
        },
    ]
    monkeypatch.setattr(JobCache, "get_stale", classmethod(lambda cls: cached))

    # 1) 公司+岗位命中（剥离[猎头]前缀后归一命中）
    dup1 = await service.find_duplicate_job({
        "公司名称": "字节跳动",
        "岗位名称": "后端架构师",
    })
    assert dup1 is not None
    assert dup1["record_id"] == "rec_001"
    assert "字节跳动" in dup1["公司名称"]

    # 2) 链接命中（带尾部斜杠归一化后命中）
    dup2 = await service.find_duplicate_job({
        "公司名称": "不同名测试",
        "岗位名称": "不同岗位",
        "岗位链接": "https://www.zhipin.com/job_detail/456.html/",
    })
    assert dup2 is not None
    assert dup2["record_id"] == "rec_002"

    # 3) 不重复
    dup3 = await service.find_duplicate_job({
        "公司名称": "腾讯科技",
        "岗位名称": "微信产品经理",
        "岗位链接": "https://careers.tencent.com/job/789.html",
    })
    assert dup3 is None


# ==========================================
# 5. confirm_job_import 落库与 raw_jobs 闭环测试（走真实 _sync_to_raw_jobs SQL 路径）
# ==========================================
@pytest.mark.asyncio
async def test_confirm_job_import_full_lifecycle(monkeypatch, tmp_path):
    # 模拟外部飞书 client
    fake_create = AsyncMock(return_value={"data": {"record": {"record_id": "rec_mock_888"}}})
    monkeypatch.setattr(service.feishu_client, "create_record", fake_create)
    monkeypatch.setattr(service, "find_duplicate_job", AsyncMock(return_value=None))

    # 🌟 flaky 三件套（2026-09-07 教训：本测试曾约 20% 概率偶发失败）：
    # 1. 快照落盘重定向到 tmp，隔离生产 job_cache_snapshot.json
    #    （JobCache.clear() 会真实 unlink 生产快照，且与本机运行中的后端进程互踩同一文件）
    monkeypatch.setattr(JobCache, "_snapshot_path", tmp_path / "job_cache_snapshot.json")
    # 2. 显式重置内存缓存残留（上一条 monkeypatch.get_stale 的 cached 仍在类属性里）
    monkeypatch.setattr(JobCache, "_data", None)
    monkeypatch.setattr(JobCache, "_timestamp", 0.0)

    # 重定向数据库到 tmp 目录（_sync_to_raw_jobs 读模块级 PROJECT_ROOT），
    # 并预建空库文件模拟生产环境（真实实现发现库文件不存在时会直接跳过同步）
    (tmp_path / "data").mkdir(exist_ok=True)
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    sqlite3.connect(str(tmp_path / "data" / "job_hunter.db")).close()

    JobCache.clear()
    assert JobCache.is_dirty() is False

    fields = {
        "公司名称": "小红书科技有限公司",
        "岗位名称": "社区搜索推荐专家",
        "岗位详情": "负责小红书双列 Feed 流推荐算法...",
        "薪资": "40-60K",
        "城市": "上海",
        "岗位链接": "http://xhslink.com/a/test12345",
        "招聘平台": "小红书",
    }

    # 执行确认落库
    result = await service.confirm_job_import(fields)
    assert result["record_id"] == "rec_mock_888"
    assert result["招聘平台"] == "小红书"
    assert JobCache.is_dirty() is True  # 🌟 验证缓存被打脏

    # 🌟 验证 SQLite raw_jobs 母本池：真实 SQL 写入，岗位链接 dict 已还原为裸 URL
    with sqlite3.connect(str(tmp_path / "data" / "job_hunter.db")) as conn:
        row = conn.execute(
            "SELECT feishu_record_id, company_name, job_title, platform, job_link, is_synced, process_status "
            "FROM raw_jobs WHERE feishu_record_id = ?",
            ("rec_mock_888",),
        ).fetchone()
        assert row is not None
        assert row[0] == "rec_mock_888"
        assert row[1] == "小红书科技有限公司"
        assert row[2] == "社区搜索推荐专家"
        assert row[3] == "小红书"
        assert row[4] == "http://xhslink.com/a/test12345"
        assert row[5] == 1
        assert row[6] == "已同步"


# ==========================================
# 6. FastAPI 路由异常与拦截契约测试
# ==========================================
def test_jobs_import_router_contracts(monkeypatch):
    app = FastAPI()
    app.include_router(jobs_router)
    client = TestClient(app)

    # A) /api/jobs/import/confirm - 硬缺失返回 422
    res_missing = client.post("/api/jobs/import/confirm", json={
        "fields": {
            "公司名称": "", # 硬缺失
            "岗位名称": "测试",
            "岗位详情": "描述",
        },
        "force_duplicate": False,
    })
    assert res_missing.status_code == 422
    assert "公司名称" in res_missing.json()["detail"]["missing"]

    # B) /api/jobs/import/confirm - 重复且未 force 返回 409
    dup_info = {
        "record_id": "rec_exist_1",
        "公司名称": "重复公司",
        "岗位名称": "重复岗位",
        "跟进状态": "新线索",
        "review_url": "https://feishu.cn/base/xxx",
    }
    monkeypatch.setattr(service, "find_duplicate_job", AsyncMock(return_value=dup_info))

    res_dup = client.post("/api/jobs/import/confirm", json={
        "fields": {
            "公司名称": "重复公司",
            "岗位名称": "重复岗位",
            "岗位详情": "详情内容完整提供",
        },
        "force_duplicate": False,
    })
    assert res_dup.status_code == 409
    assert res_dup.json()["detail"]["existing"]["record_id"] == "rec_exist_1"

    # C) /api/jobs/import/confirm - force_duplicate=True 时放行 200
    fake_create = AsyncMock(return_value={"data": {"record": {"record_id": "rec_forced_222"}}})
    monkeypatch.setattr(service.feishu_client, "create_record", fake_create)
    monkeypatch.setattr(service, "_sync_to_raw_jobs", MagicMock())

    res_force = client.post("/api/jobs/import/confirm", json={
        "fields": {
            "公司名称": "重复公司",
            "岗位名称": "重复岗位",
            "岗位详情": "详情内容完整提供",
        },
        "force_duplicate": True,
    })
    assert res_force.status_code == 200
    assert res_force.json()["status"] == "success"
    assert res_force.json()["data"]["record_id"] == "rec_forced_222"


# ==========================================
# 7. 发布日期解析与归一化全场景测试
# ==========================================
def test_resolve_publish_date():
    from datetime import datetime, timedelta
    now = datetime.now()
    cur_year = now.year

    # 1. 猎聘移动端典型标签：月日+更新/发布
    assert service._resolve_publish_date("8月17日更新") == f"{cur_year}-08-17"
    assert service._resolve_publish_date("8月17日") == f"{cur_year}-08-17"
    assert service._resolve_publish_date("08-17") == f"{cur_year}-08-17"
    assert service._resolve_publish_date("8.17") == f"{cur_year}-08-17"

    # 2. 相对时间转换
    assert service._resolve_publish_date("今日更新") == now.strftime("%Y-%m-%d")
    assert service._resolve_publish_date("今天") == now.strftime("%Y-%m-%d")
    assert service._resolve_publish_date("刚刚更新") == now.strftime("%Y-%m-%d")
    assert service._resolve_publish_date("昨天") == (now - timedelta(days=1)).strftime("%Y-%m-%d")
    assert service._resolve_publish_date("前天") == (now - timedelta(days=2)).strftime("%Y-%m-%d")
    assert service._resolve_publish_date("3天前更新") == (now - timedelta(days=3)).strftime("%Y-%m-%d")
    assert service._resolve_publish_date("5天前") == (now - timedelta(days=5)).strftime("%Y-%m-%d")

    # 3. 完整绝对日期归一化
    assert service._resolve_publish_date("2026-08-17") == "2026-08-17"
    assert service._resolve_publish_date("2026.08.17") == "2026-08-17"
    assert service._resolve_publish_date("2026/08/17") == "2026-08-17"
    assert service._resolve_publish_date("2026年8月17日更新") == "2026-08-17"

    # 4. 占位与异常空值兜底
    assert service._resolve_publish_date("-") == "-"
    assert service._resolve_publish_date("") == "-"
    assert service._resolve_publish_date("未知") == "-"
    assert service._resolve_publish_date(None) == "-"


# ==========================================
# 8. 实质性招聘正文判定与防幻觉短路测试
# ==========================================
def test_has_substantial_job_text():
    # 纯 URL 链接
    assert service._has_substantial_job_text("https://m.zhaopin.com/jobs/CC249499810J40840417311.html?share=1") is False
    assert service._has_substantial_job_text("https://www.zhipin.com/job_detail/123.html") is False
    assert service._has_substantial_job_text("https://msearch.51job.com/jobs/all/173358279.html") is False
    # 仅微信小程序口令
    assert service._has_substantial_job_text("#小程序://猎聘招聘/职位详情/vf3XBJrNDtIIQay") is False
    # 主流平台分享套话与带标签链接（无实质岗位正文）
    assert service._has_substantial_job_text("帮我录入链接 https://m.zhaopin.com/jobs/123") is False
    assert service._has_substantial_job_text("链接：https://msearch.51job.com/jobs/all/173358279.html") is False
    assert service._has_substantial_job_text("岗位链接: https://m.zhipin.com/mpa/html/weijd/123") is False
    assert service._has_substantial_job_text("【BOSS直聘】复制整段，打开BOSS直聘App查看详情：https://m.zhipin.com/mpa/html/weijd/123") is False
    assert service._has_substantial_job_text("【智联招聘】点击链接查看岗位详情：https://m.zhaopin.com/jobs/123") is False
    # TODO.md Step 6 用户手写补充信息（图文同传时不能丢弃）
    assert service._has_substantial_job_text("补充薪资：50-70K，岗位链接：https://www.zhipin.com/job_detail/test123.html") is True
    assert service._has_substantial_job_text("薪资20-30k") is True
    assert service._has_substantial_job_text("补充工作地点在广州黄埔") is True
    # 真实有效长文本招聘正文
    real_text = "【岗位职责】1. 负责核心系统研发，包括 Web 后台与微信小程序；2. 熟练掌握 Python 与 TypeScript。"
    assert service._has_substantial_job_text(real_text) is True


@pytest.mark.asyncio
async def test_parse_job_from_sources_pure_url_avoids_llm(monkeypatch):
    """纯 URL 输入时严禁调用文本大模型产生幻觉，必须直接返回链接与平台，其余置为 '-'"""
    fake_llm = MagicMock(side_effect=AssertionError("严禁在纯 URL 时调用文本 LLM！"))
    monkeypatch.setattr(service, "_call_llm_for_job_parsing", fake_llm)

    res = await service.parse_job_from_sources(
        raw_text="https://m.zhaopin.com/jobs/CC249499810J40840417311.html?share=1"
    )
    assert res["招聘平台"] == "智联招聘"
    assert "https://m.zhaopin.com/jobs/CC249499810J40840417311.html" in res["岗位链接"]
    assert res["公司名称"] == "-"
    assert res["岗位名称"] == "-"
    assert res["岗位详情"] == "-"
    assert fake_llm.call_count == 0


# ==========================================
# 9. 移动端分享链接转 PC 电脑端详情页链接测试 (BOSS + 51job)
# ==========================================
def test_normalize_job_url_51job_and_boss():
    # 1. BOSS 直聘手机链接转电脑端
    boss_m1 = "https://m.zhipin.com/mpa/html/weijd/weijd-job/abc123_xyz--456?trace=1"
    assert service.normalize_job_url(boss_m1) == "https://www.zhipin.com/job_detail/abc123_xyz--456.html"

    # 2. 51job (前程无忧) 手机链接转电脑端
    job51_m1 = "https://msearch.51job.com/jobs/all/173358279.html"
    assert service.normalize_job_url(job51_m1) == "https://jobs.51job.com/all/173358279.html"

    job51_m2 = "https://msearch.51job.com/jobs/all/173358279.html?job_type=1&share=copy"
    assert service.normalize_job_url(job51_m2) == "https://jobs.51job.com/all/173358279.html"

    job51_m3 = "https://msearch.51job.com/jobs/guangzhou/173358279.html"
    assert service.normalize_job_url(job51_m3) == "https://jobs.51job.com/guangzhou/173358279.html"

    job51_m4 = "https://m.51job.com/jobs/173358279.html"
    assert service.normalize_job_url(job51_m4) == "https://jobs.51job.com/all/173358279.html"

    # 3. 原生 PC 链接与非匹配 URL 保持不变
    pc_51 = "https://jobs.51job.com/all/173358279.html"
    assert service.normalize_job_url(pc_51) == pc_51
    unknown = "https://example.com/job/123"
    assert service.normalize_job_url(unknown) == unknown


# ==========================================
# 10. 视觉路调用链回归守卫：P0 教训（重构曾把 _parse_fields_by_vision
#     指向不存在的 app.services.multimodal_service，纯图/图文录入全崩）。
#     本测试 mock 视觉客户端，走完整真实链路：客户端获取 → 消息组装 →
#     JSON 清洗 → 平台归一 → 英文字段别名转中文 → 发布日期归一。
# ==========================================
def test_parse_fields_by_vision_full_chain(monkeypatch):
    from datetime import datetime

    from app.jobs import import_parser

    # 捕获视觉客户端收到的请求，校验多模态消息契约
    fake_response = MagicMock()
    fake_response.choices = [MagicMock()]
    fake_response.choices[0].message.content = '''{
        "company_name": "视觉真实公司",
        "job_name": "视觉测试岗位",
        "薪资": "20-35K·14薪",
        "城市": "深圳",
        "经验要求": "3-5年",
        "学历要求": "本科",
        "岗位详情": "负责视觉链路回归守卫测试",
        "招聘平台": "boss直聘",
        "发布日期": "8月17日更新"
    }'''

    fake_client = MagicMock()
    fake_client.chat.completions.create = MagicMock(return_value=fake_response)

    import common.config as common_config
    monkeypatch.setattr(common_config, "get_vision_llm_client", lambda caller="": fake_client)
    # 双保险：旧实现从 common.config 导入（函数内 import），mock 模块属性即可命中

    result = import_parser._parse_fields_by_vision([
        "data:image/jpeg;base64,AAAA",
        "BBBB",  # 无 data: 前缀的裸 base64，验证自动补 JPEG 头
    ])

    # 1. 视觉客户端被真实调用一次
    assert fake_client.chat.completions.create.call_count == 1
    kwargs = fake_client.chat.completions.create.call_args.kwargs
    # 2. 多模态消息契约：图片 part 在前、文字 part 在后（MiMo 多模态路由要求）
    user_content = kwargs["messages"][1]["content"]
    assert user_content[-1]["type"] == "text"
    assert user_content[0]["type"] == "image_url"
    assert user_content[0]["image_url"]["url"] == "data:image/jpeg;base64,AAAA"
    assert user_content[1]["image_url"]["url"] == "data:image/jpeg;base64,BBBB"
    # 3. system prompt 为视觉解析铁律 prompt
    assert "招聘信息文本提取引擎" in kwargs["messages"][0]["content"]
    # 4. 英文字段别名已转中文 + 平台已归一为注册表规范名
    assert result["公司名称"] == "视觉真实公司"
    assert result["岗位名称"] == "视觉测试岗位"
    assert result["招聘平台"] == "BOSS直聘"
    # 5. 发布日期相对格式已归一为 YYYY-MM-DD
    assert result["发布日期"] == f"{datetime.now().year:04d}-08-17"


def test_parse_fields_by_vision_rejects_non_dict(monkeypatch):
    """视觉模型返回 JSON 数组等非对象结构时，视觉路必须显式报错而非静默产出脏数据。"""
    from app.jobs import import_parser

    fake_response = MagicMock()
    fake_response.choices = [MagicMock()]
    fake_response.choices[0].message.content = '["not", "a", "dict"]'

    fake_client = MagicMock()
    fake_client.chat.completions.create = MagicMock(return_value=fake_response)

    import common.config as common_config
    monkeypatch.setattr(common_config, "get_vision_llm_client", lambda caller="": fake_client)

    with pytest.raises(ValueError, match="非有效 JSON 对象"):
        import_parser._parse_fields_by_vision(["data:image/jpeg;base64,AAAA"])


# ==========================================
# 11. 文本路调用链回归守卫：P0 教训（2026-09-07 质检抓到 fd8a648 重构把
#     _call_llm_for_job_parsing 写成 "client, model_name = get_openai_client()"
#     解包元组，而该工厂只返回单客户端，纯文本/图文同传/聊天框文字录入全 500；
#     既有测试对 LLM 全 mock 掩盖了坏契约）。本测试 mock 真实 common.config
#     工厂，走完整文本链路：客户端获取 → create 调用契约 → JSON 清洗 → 中文字段。
# ==========================================
def test_call_llm_for_job_parsing_full_chain(monkeypatch):
    from datetime import datetime

    from app.jobs import import_parser

    fake_response = MagicMock()
    fake_response.choices = [MagicMock()]
    fake_response.choices[0].message.content = '''```json
{"company_name": "文本真实公司", "job_name": "文本测试岗位", "salary": "25-40K",
 "city": "北京", "job_detail": "负责文本链路回归守卫测试", "publish_date": "8月17日更新"}
```'''

    captured = {}

    class _FactoryCapturedClient:
        """模拟 common.config.get_openai_client 的单客户端返回契约。"""
        def __init__(self, client):
            self._client = client

        def __getattr__(self, name):
            return getattr(self._client, name)

    fake_client = MagicMock()
    fake_client.chat.completions.create = MagicMock(
        side_effect=lambda **kw: captured.update(kwargs=kw) or fake_response
    )

    import common.config as common_config
    monkeypatch.setattr(common_config, "get_openai_client", lambda caller="": fake_client)
    monkeypatch.setattr(import_parser, "get_openai_client", lambda caller="": fake_client)

    raw = import_parser._call_llm_for_job_parsing("某公司招人")
    assert "company_name" in raw  # 原始返回未被破坏

    # 1. 单客户端契约：若实现仍错误解包元组，本行之前的调用已抛 TypeError，测试直接失败
    assert fake_client.chat.completions.create.call_count == 1
    kwargs = captured["kwargs"]
    # 2. create 契约：model 为 settings.OPENAI_MODEL 回落值、system 为文本解析铁律 prompt
    assert kwargs["model"] in ("gpt-4o", import_parser.settings.OPENAI_MODEL)
    assert "招聘信息解析引擎" in kwargs["messages"][0]["content"]
    assert kwargs["messages"][1]["content"] == "某公司招人"

    # 3. 下游 _parse_fields_by_text 联动：markdown 代码块清洗 + 中文字段映射 + 日期归一
    fields = import_parser._parse_fields_by_text("某公司招人", "", "未知")
    assert fields["公司名称"] == "文本真实公司"
    assert fields["岗位名称"] == "文本测试岗位"
    assert fields["发布日期"] == f"{datetime.now().year:04d}-08-17"
