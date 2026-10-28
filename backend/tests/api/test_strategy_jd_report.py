"""JD 能力画像接口测试（纯离线：飞书/LLM 全部在 service 边界 mock，DB 用 tmp 隔离）。

接缝说明（2026-10-11 本地事实源重构后）：
- generate 的岗位池拉取/计数走 httpx.AsyncClient（patch 该类，按评级条件路由响应）；
- 异步 token / 同步 token 分别 patch app.strategy.service.feishu_client.get_tenant_access_token
  与 app.strategy.service.get_tenant_access_token（patch 源模块无效，service 经 facade 消费）；
- 镜像写与飞书迁移的同步 requests patch app.strategy.service.requests；
- LLM patch app.strategy.service.get_openai_client；
- 本地存储 patch jd_report_service._get_report_db_path 指向 tmp 库（惰性建表）。
"""
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

REPORT = (
    "# AI应用类岗位能力画像\n\n"
    "样本说明：基于 20 条 A 级岗位提炼共性。\n\n"
    "## 一、硬技能\n\n"
    "**大模型应用能力**（16/20 岗位）\n熟悉 LLM API、RAG、Agent 框架。〔来源:1,5,16〕\n\n"
    + "细节补充。" * 30 + "\n\n"
    "## 二、软技能\n\n**跨部门协作**（18/20 岗位）〔来源:2,3〕\n\n"
    "## 三、业务经验\n\n**AI 应用落地**（15/20 岗位）〔来源:1,2〕\n\n"
    "### 行业分布\n\n- 电商（6 个岗位）：要求熟悉电商交易链路。\n- 客服（4 个岗位）：智能客服场景。\n\n"
    "## 四、加分项\n\n- 向量数据库经验（岗位 9）\n\n"
    "## 画像一句话总结\n\n懂业务 + 会用 AI 的复合型人才。\n\n"
    "## 附：下游速览\n\n"
    "- 硬技能：LLM API/RAG/Agent 框架，AI 编程工具深度使用。\n"
    "- 软技能：跨部门协作、问题拆解。\n"
    "- 业务经验：AI 应用落地，行业以电商、客服为主。\n"
    "- 加分项：向量数据库、英文能力。"
)
# 详细版落库/镜像形态 = LLM 全文拆掉速览区块（split_brief 的 value 侧）
REPORT_VALUE = REPORT.split("## 附：下游速览")[0].rstrip()
REPORT_BRIEF = "- 硬技能：LLM API/RAG/Agent 框架，AI 编程工具深度使用。\n" \
    "- 软技能：跨部门协作、问题拆解。\n" \
    "- 业务经验：AI 应用落地，行业以电商、客服为主。\n" \
    "- 加分项：向量数据库、英文能力。"
_DIM_FIELDS = [
    "核心-角色匹配", "核心-技能重合", "高权-职级资历", "高权-薪资契合",
    "高权-面试概率", "中权-公司阶段", "中权-赛道前景", "中权-成长空间",
]


@pytest.fixture(autouse=True)
def _isolate_jd_report_env(tmp_path, monkeypatch):
    """DB 隔离（bootstrap 蓝本建表，与服务同源）+ 用例间缓存清零。"""
    from app.core.db_bootstrap import ensure_main_db_schema
    from app.strategy import jd_report_service as jds

    db = tmp_path / "test_jd.db"
    ensure_main_db_schema(str(db))
    monkeypatch.setattr(jds, "_get_report_db_path", lambda: str(db))
    monkeypatch.setattr(jds, "_LLM_BACKOFF_SECONDS", (0, 0))
    with jds._jd_report_cache_lock:
        jds._JD_REPORT_CACHE.update(value=None, meta=None, at=0.0, neg=False)
    yield
    with jds._jd_report_cache_lock:
        jds._JD_REPORT_CACHE.update(value=None, meta=None, at=0.0, neg=False)


def _job_item(record_id: str, title: str, company: str = "某公司", dims: dict | None = None,
              crawl: str | None = None, detail: str = "FastAPI React Pytest") -> dict:
    fields = {"岗位名称": title, "岗位详情": detail, "公司名称": company}
    for f in _DIM_FIELDS:
        fields[f] = 0
    for f, v in (dims or {}).items():
        fields[f] = v
    if crawl:
        fields["抓取时间"] = crawl
    return {"record_id": record_id, "fields": fields}


def _search_response(items: list[dict], total: int | None = None) -> dict:
    return {"code": 0, "data": {"items": items, "has_more": False,
                                "total": total if total is not None else len(items)}}


@pytest.fixture
def mock_httpx_client():
    """岗位池拉取/计数共用；_route_grades 按请求体的评级条件路由响应并记录调用。"""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_instance = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_instance
        mock_instance._grade_calls = []

        def _route_grades(a_items, total_a=None, b_items=None):
            async def post(_url, _headers=None, json=None, _timeout=None, **_kw):
                grade = json["filter"]["conditions"][0]["value"][0]
                mock_instance._grade_calls.append(grade)
                resp = MagicMock()
                if grade == "A":
                    resp.json.return_value = _search_response(a_items, total_a)
                else:
                    resp.json.return_value = _search_response(b_items or [])
                return resp
            mock_instance.post.side_effect = post

        mock_instance._route_grades = _route_grades
        yield mock_instance


@pytest.fixture
def mock_openai():
    with patch("app.strategy.service.get_openai_client") as mock:
        yield mock


@pytest.fixture
def mock_feishu_token():
    with patch("app.strategy.service.feishu_client.get_tenant_access_token", new_callable=AsyncMock) as mock_async:
        mock_async.return_value = "fake_token"
        with patch("app.strategy.service.get_tenant_access_token") as mock_sync:
            mock_sync.return_value = "fake_token"
            yield mock_async


@pytest.fixture
def mock_service_requests():
    """镜像写/迁移的同步 requests。默认无启用简历（put 不应被调用）。"""
    with patch("app.strategy.service.requests") as mock_requests:
        mock_requests.post.return_value = MagicMock(
            status_code=200, raise_for_status=MagicMock(),
            json=MagicMock(return_value={"code": 0, "data": {"items": [], "has_more": False}}),
        )
        mock_requests.put.return_value = MagicMock(
            status_code=200, raise_for_status=MagicMock(),
            json=MagicMock(return_value={"code": 0}),
        )
        yield mock_requests


def _set_llm(mock_openai, outputs: list[str]):
    mock_llm_resp_list = [MagicMock(choices=[MagicMock(message=MagicMock(content=o))]) for o in outputs]
    mock_openai.return_value.chat.completions.create.side_effect = mock_llm_resp_list


# ---------- 生成：本地事实源 + 三阶段取样 ----------

@pytest.mark.usefixtures("mock_feishu_token")
def test_generate_persists_locally_without_active_resume(mock_httpx_client, mock_openai, mock_service_requests):
    """P0 回归：简历库无启用记录时，画像仍落本地且下游可读（旧实现结果被静默丢弃）。"""
    mock_httpx_client._route_grades([_job_item("rec1", "AI Engineer", dims={"核心-角色匹配": 5})], total_a=1)
    _set_llm(mock_openai, [REPORT])

    response = client.post("/api/strategy/generate_jd_report")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["data"] == REPORT_VALUE  # 弹窗拿详细版（速览区块已拆出）
    assert mock_service_requests.put.call_count == 0  # 无启用简历：镜像跳过，但本地已落库
    # 本地事实源（详细版 value 落库，速览区块拆进 meta.llm_brief）
    from app.strategy import jd_report_service as jds
    value, meta = jds._load_local_report_sync()
    assert value == REPORT_VALUE
    assert meta["llm_brief"] == REPORT_BRIEF
    assert meta["a_count"] == 1 and meta["b_count"] == 0 and meta["stage"] == "mixed"
    assert meta["total_a_in_pool"] == 1 and meta["generated_at"]
    assert meta["format"] == "detailed_v2"
    # 来源映射与样本编号同序（1 条 A 级样本 → idx=1，含 record_id 供前端深链）
    assert meta["sample_jobs"][0] == {
        "idx": 1, "grade": "A", "company": "某公司", "title": "AI Engineer", "record_id": "rec1",
    }
    # 双轨契约：弹窗路由（with_meta）拿详细版，下游入口拿速览版
    assert mock_service_requests.post.call_count == 1  # 仅镜像的启用简历搜索
    resp = client.get("/api/strategy/get_jd_report")
    assert resp.json()["data"] == REPORT_VALUE
    downstream = asyncio.run(jds.get_global_jd_report())
    assert downstream == REPORT_BRIEF


@pytest.mark.usefixtures("mock_feishu_token", "mock_service_requests")
def test_generate_client_getter_passes_zero_sdk_retries(mock_httpx_client, mock_openai):
    """画像链路 SDK 级重试归零 + 埋点标签：外层已有 _LLM_ATTEMPTS 次退避重试，
    SDK 再叠加重试只放大持续超时时的挂死时长（2026-10-13 实测 37 分钟马拉松）。"""
    mock_httpx_client._route_grades([_job_item("rec1", "AI Engineer")], total_a=1)
    _set_llm(mock_openai, [REPORT])

    response = client.post("/api/strategy/generate_jd_report")

    assert response.status_code == 200
    assert mock_openai.call_args.kwargs == {"caller": "jd_report", "max_retries": 0}


@pytest.mark.usefixtures("mock_feishu_token")
def test_generate_mirror_writes_enabled_resume(mock_httpx_client, mock_openai, mock_service_requests):
    """有启用简历时 best-effort 镜像写飞书（读已不依赖它）。"""
    mock_httpx_client._route_grades([_job_item("rec1", "AI Engineer")], total_a=1)
    _set_llm(mock_openai, [REPORT])
    mock_service_requests.post.return_value = MagicMock(
        status_code=200, raise_for_status=MagicMock(),
        json=MagicMock(return_value={"code": 0, "data": {"items": [{"record_id": "res_rec_1"}]}}),
    )

    response = client.post("/api/strategy/generate_jd_report")

    assert response.json()["status"] == "success"
    assert mock_service_requests.put.call_count == 1
    put_fields = mock_service_requests.put.call_args.kwargs["json"]["fields"]
    assert put_fields["全局A级JD能力画像"] == REPORT_VALUE  # 镜像写详细版（人肉可见）


@pytest.mark.usefixtures("mock_feishu_token", "mock_service_requests")
def test_mixed_stage_dedup_and_layer_labels(mock_httpx_client, mock_openai):
    """两级取样：A<20 一律补 B（用户 2026-10-12 拍板，无成长期）+ 同公司同名去重
    + 层级显式标注 + 样本标题带公司名 + 来源标记语法进 prompt。"""
    a_items = [
        _job_item("rec_a1", "AI Engineer", company="甲公司", dims={"核心-角色匹配": 5}),
        _job_item("rec_a2", "AI Engineer", company="甲公司", dims={"核心-角色匹配": 1}),  # 同名同司→去重
    ]
    b_items = [
        _job_item("rec_b1", "Backend", company="乙公司", dims={"核心-技能重合": 3}),
        _job_item("rec_b2", "Fullstack", company="丙公司", dims={"核心-技能重合": 2}),
        _job_item("rec_b3", "Data", company="丁公司", dims={"核心-技能重合": 1}),
    ]
    mock_httpx_client._route_grades(a_items, total_a=2, b_items=b_items)
    _set_llm(mock_openai, [REPORT])

    response = client.post("/api/strategy/generate_jd_report")

    data = response.json()
    assert data["status"] == "success"
    meta = data["meta"]
    assert meta["a_count"] == 1 and meta["b_count"] == 3 and meta["stage"] == "mixed"
    # sample_jobs 全局连续编号（A 先 B 后）与 record_id 映射
    assert [j["idx"] for j in meta["sample_jobs"]] == [1, 2, 3, 4]
    assert meta["sample_jobs"][1]["record_id"] == "rec_b1" and meta["sample_jobs"][1]["grade"] == "B"
    # 层级标注（含公司名）与来源标记语法进 LLM 输入
    create_kwargs = mock_openai.return_value.chat.completions.create.call_args.kwargs
    user_content = create_kwargs["messages"][1]["content"]
    assert "【A级岗位 1：甲公司·AI Engineer】" in user_content
    assert "【B级岗位 2：乙公司·Backend】" in user_content
    assert "以 A 级为准" in create_kwargs["messages"][0]["content"]
    assert "〔来源:" in create_kwargs["messages"][0]["content"]
    assert "行业分布" in create_kwargs["messages"][0]["content"]


@pytest.mark.usefixtures("mock_feishu_token", "mock_service_requests")
def test_mature_stage_top_selection_skips_b_pool(mock_httpx_client, mock_openai):
    """A≥20：纯 A 精选 top20，不拉 B 池（B 被踢出——用户两级取样规则）。"""
    a_items = [_job_item(f"rec_{i}", f"岗位{i}", company=f"公司{i}", dims={"核心-角色匹配": 5})
               for i in range(20)]
    a_items += [_job_item(f"low_{i}", f"低分岗{i}", company=f"低司{i}") for i in range(5)]  # 全 0 维
    mock_httpx_client._route_grades(a_items, total_a=25)
    _set_llm(mock_openai, [REPORT])

    response = client.post("/api/strategy/generate_jd_report")

    meta = response.json()["meta"]
    assert meta["stage"] == "mature"
    assert meta["a_count"] == 20 and meta["total_a_in_pool"] == 25 and meta["b_count"] == 0
    assert all(not rid.startswith("low_") for rid in meta["a_record_ids"])
    assert "B" not in mock_httpx_client._grade_calls  # 成熟期不发 B 池请求


@pytest.mark.usefixtures("mock_feishu_token", "mock_service_requests")
def test_recency_window_beats_score(mock_httpx_client, mock_openai):
    """新鲜度窗口优先：近期低分岗位挤掉陈旧高分岗位（画像跟市场走）。"""
    recent_crawl = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    a_items = [_job_item("rec_recent", "新鲜岗", company="新司", crawl=recent_crawl)]  # 全 0 维但新鲜
    a_items += [_job_item(f"old_{i}", f"陈旧岗{i}", company=f"旧司{i}", dims={"核心-角色匹配": 5})
                for i in range(21)]
    mock_httpx_client._route_grades(a_items, total_a=22)
    _set_llm(mock_openai, [REPORT])

    response = client.post("/api/strategy/generate_jd_report")

    meta = response.json()["meta"]
    assert meta["stage"] == "mature" and meta["a_count"] == 20
    assert "rec_recent" in meta["a_record_ids"]  # 新鲜者入选，2 条陈旧高分被挤出


# ---------- 写前校验 + 重试 ----------

@pytest.mark.usefixtures("mock_feishu_token", "mock_service_requests")
def test_validation_retry_then_success(mock_httpx_client, mock_openai):
    mock_httpx_client._route_grades([_job_item("rec1", "AI Engineer")], total_a=1)
    _set_llm(mock_openai, ["太短", REPORT])

    response = client.post("/api/strategy/generate_jd_report")

    assert response.json()["data"] == REPORT_VALUE
    assert mock_openai.return_value.chat.completions.create.call_count == 2


@pytest.mark.usefixtures("mock_feishu_token", "mock_service_requests")
def test_validation_all_fail_never_writes(mock_httpx_client, mock_openai):
    """连续失败：明确报错且绝不把空值/乱码写库（旧实现空报告会静默清空画像）。"""
    mock_httpx_client._route_grades([_job_item("rec1", "AI Engineer")], total_a=1)
    _set_llm(mock_openai, ["", "❌ 出错了", "短"])

    response = client.post("/api/strategy/generate_jd_report")

    assert response.json()["status"] == "error"
    assert "连续 3 次未通过质量校验" in response.json()["message"]
    assert mock_openai.return_value.chat.completions.create.call_count == 3
    from app.strategy import jd_report_service as jds
    assert jds._load_local_report_sync()[0] is None  # 本地无任何写入


@pytest.mark.usefixtures("mock_feishu_token", "mock_service_requests")
def test_empty_feishu_pools_clear_error(mock_httpx_client, mock_openai):
    mock_httpx_client._route_grades([], total_a=0, b_items=[])
    _set_llm(mock_openai, [REPORT])

    response = client.post("/api/strategy/generate_jd_report")

    assert response.json()["status"] == "error"
    assert "岗位池为空" in response.json()["message"]
    assert mock_openai.return_value.chat.completions.create.call_count == 0


# ---------- 读取与一次性迁移 ----------

@pytest.mark.usefixtures("mock_feishu_token")
def test_get_migrates_from_feishu_once(mock_service_requests):
    """本地无值 → 两段式迁移（启用优先，兜底按 last_modified_time 最新）→ 之后读本地不再打飞书。"""
    migration_item = {
        "record_id": "res_old", "last_modified_time": 1234567890,
        "fields": {"全局A级JD能力画像": "历史画像内容"},
    }

    def migration_post(_url, _headers=None, json=None, _timeout=None, **_kw):
        conds = json["filter"]["conditions"]
        resp = MagicMock(status_code=200, raise_for_status=MagicMock())
        if len(conds) == 2:  # 启用 + 画像非空
            resp.json.return_value = {"code": 0, "data": {"items": [], "has_more": False}}
        else:  # 兜底：画像非空全查
            resp.json.return_value = {"code": 0, "data": {"items": [migration_item], "has_more": False}}
        return resp

    mock_service_requests.post.side_effect = migration_post

    first = client.get("/api/strategy/get_jd_report").json()
    assert first["data"] == "历史画像内容"
    assert first["meta"]["migrated_from_feishu"] is True
    assert first["meta"]["generated_at"] is None

    calls_after_first = mock_service_requests.post.call_count
    second = client.get("/api/strategy/get_jd_report").json()
    assert second["data"] == "历史画像内容"
    assert mock_service_requests.post.call_count == calls_after_first  # 本地接管，迁移仅一次


@pytest.mark.usefixtures("mock_feishu_token", "mock_service_requests")
def test_get_empty_after_failed_migration():
    """飞书也无值 → data 为 null（前端走「尚未生成」分支）。"""
    response = client.get("/api/strategy/get_jd_report")
    assert response.json()["status"] == "success"
    assert response.json()["data"] is None


@pytest.mark.usefixtures("mock_feishu_token")
def test_definitive_empty_writes_tombstone_and_stops_hitting_feishu(mock_service_requests):
    """飞书明确无画像 → 本地写墓碑，后续读取零飞书请求（审查 P1-1 缓存穿透）。"""
    first = client.get("/api/strategy/get_jd_report").json()
    assert first["data"] is None
    calls_after_first = mock_service_requests.post.call_count

    second = client.get("/api/strategy/get_jd_report").json()
    assert second["data"] is None
    assert mock_service_requests.post.call_count == calls_after_first  # 墓碑生效

    from app.strategy import jd_report_service as jds
    value, meta = jds._load_local_report_sync()
    assert value is None and meta.get("tombstone") is True
    # 生成可覆盖墓碑
    assert jds._has_local_row() is True


@pytest.mark.usefixtures("mock_feishu_token")
def test_transient_migration_failure_not_tombstoned(mock_service_requests):
    """飞书瞬态失败不写墓碑：下次读取仍会重试迁移（区别于明确无画像）。"""
    mock_service_requests.post.side_effect = RuntimeError("网络炸了")
    response = client.get("/api/strategy/get_jd_report").json()
    assert response["data"] is None
    from app.strategy import jd_report_service as jds
    assert jds._has_local_row() is False  # 无墓碑


@pytest.mark.usefixtures("mock_feishu_token", "mock_service_requests")
def test_llm_exception_counts_as_attempt(mock_httpx_client, mock_openai):
    """网关超时/429/5xx 与内容不合格同权：计入重试（审查 P1-3）。"""
    mock_httpx_client._route_grades([_job_item("rec1", "AI Engineer")], total_a=1)
    mock_openai.return_value.chat.completions.create.side_effect = [
        RuntimeError("gateway timeout"),
        MagicMock(choices=[MagicMock(message=MagicMock(content=REPORT))]),
    ]

    response = client.post("/api/strategy/generate_jd_report")

    assert response.json()["data"] == REPORT_VALUE
    assert mock_openai.return_value.chat.completions.create.call_count == 2


@pytest.mark.usefixtures("mock_feishu_token", "mock_service_requests")
def test_cross_pool_dedup_same_company_title(mock_httpx_client, mock_openai):
    """冷启动 B 补位时排除 A 池已选键：同公司同名岗位 A/B 并存不双份入样（审查 P2）。"""
    a_items = [_job_item("rec_a1", "AI Engineer", company="甲公司", dims={"核心-角色匹配": 5})]
    b_items = [_job_item("rec_b1", "AI Engineer", company="甲公司", dims={"核心-技能重合": 4})]
    mock_httpx_client._route_grades(a_items, total_a=1, b_items=b_items)
    _set_llm(mock_openai, [REPORT])

    response = client.post("/api/strategy/generate_jd_report")

    meta = response.json()["meta"]
    assert meta["a_count"] == 1 and meta["b_count"] == 0  # B 份被跨池去重剔除
    assert meta["a_record_ids"] == ["rec_a1"]


@pytest.mark.usefixtures("mock_feishu_token", "mock_service_requests")
def test_growing_pool_now_gets_b_supplement(mock_httpx_client, mock_openai):
    """两级取样回归：A=6（原成长期不补 B）现在必须补 B 至 20（用户 2026-10-12 拍板）。"""
    a_items = [_job_item(f"rec_a{i}", f"岗位A{i}", company=f"司A{i}", dims={"核心-角色匹配": 5})
               for i in range(6)]
    b_items = [_job_item(f"rec_b{i}", f"岗位B{i}", company=f"司B{i}") for i in range(30)]
    mock_httpx_client._route_grades(a_items, total_a=6, b_items=b_items)
    _set_llm(mock_openai, [REPORT])

    meta = client.post("/api/strategy/generate_jd_report").json()["meta"]

    assert meta["stage"] == "mixed"
    assert meta["a_count"] == 6 and meta["b_count"] == 14  # 补位至 20
    assert [j["idx"] for j in meta["sample_jobs"]] == list(range(1, 21))


def test_unknown_crawl_time_ranks_below_stale():
    """三档新鲜度：未知时间垫底，不挤掉已知年龄样本（审查 P1-5）。"""
    from app.strategy import jd_report_sampling as smp

    old_crawl = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d %H:%M:%S")
    a_items = [
        _job_item("rec_unknown", "未知时间岗", company="司A", dims={"核心-角色匹配": 5}),  # 无抓取时间
        _job_item("rec_stale", "陈旧岗", company="司B", dims={"核心-角色匹配": 5}, crawl=old_crawl),
    ]
    selection = asyncio.run(smp.select_samples(
        a_items, 2, max_jobs=1, recency_days=90,
        b_items=[],
    ))
    assert selection["stage"] == "mature"
    assert selection["a_selected"][0]["record_id"] == "rec_stale"  # 未知时间垫底被挤出


# ---------- 幂等守卫与写前校验（单元；每日自动重建已移除，无刷新判定） ----------

def test_reuse_guard_during_wait():
    from app.strategy import jd_report_service as jds
    assert jds._should_reuse_during_wait("T1", {"generated_at": "T1"}) is False
    assert jds._should_reuse_during_wait("T1", {"generated_at": "T2"}) is True  # 等锁期间已有新生成
    # 冷启动并发：等锁期间他人完成首次生成 → 复用，不重复烧 token（审查 P1-2）
    assert jds._should_reuse_during_wait(None, {"generated_at": "T2"}) is True
    assert jds._should_reuse_during_wait(None, {}) is False
    assert jds._should_reuse_during_wait("T1", {}) is False


def test_validate_report_rules():
    """写前校验（详细核对版）：基础闸 + 分类齐备/行业分布/末节总结/下游速览四闸。"""
    from app.strategy import jd_report_prompts as prompts

    assert not prompts.validate_report("")[0]
    assert not prompts.validate_report("短")[0]
    assert not prompts.validate_report("❌ 错误" + "x" * 300)[0]
    assert not prompts.validate_report("没有标题开头" + "x" * 300)[0]
    assert prompts.validate_report(REPORT)[0]

    # 缺任一必需章节（含行业分布/末节总结/下游速览——后两者兼作尾部截断特征）→ 拦截
    body = "## 一、硬技能\n\n## 二、软技能\n\n## 三、业务经验\n\n## 四、加分项\n\n" + "x" * 200
    assert not prompts.validate_report("# 标题\n\n" + body)[0]  # 无行业分布/总结/速览
    assert not prompts.validate_report(REPORT.replace("### 行业分布", "### 领域列表"))[0]
    assert not prompts.validate_report(REPORT.replace("## 画像一句话总结", "## 总结"))[0]
    assert not prompts.validate_report(REPORT.replace("## 附：下游速览", "## 速览"))[0]


def test_split_brief_dual_track():
    """双轨拆分：value 剥离速览区块（含其前分隔线），brief 去标题并清理来源标记。"""
    from app.strategy import jd_report_prompts as prompts

    value, brief = prompts.split_brief(REPORT)
    assert value == REPORT_VALUE
    assert brief == REPORT_BRIEF
    assert "下游速览" not in value  # 详细版不含速览区块
    # 无区块（旧报告）→ brief 空，value 原样
    v2, b2 = prompts.split_brief("# 旧报告\n\n正文内容")
    assert v2 == "# 旧报告\n\n正文内容" and b2 == ""
    # brief 意外携带来源标记 → 清理
    v3, b3 = prompts.split_brief(REPORT.replace("- 硬技能：LLM", "- 硬技能〔来源:1,2〕：LLM"))
    assert "〔来源" not in b3


def test_validate_source_marker_extraction():
    """来源标记提取：半角严格 + 全角容错（前端正则的同族协议）。"""
    from app.strategy.jd_report_prompts import extract_source_indices
    assert extract_source_indices("a〔来源:1,5,16〕b〔来源:2〕") == [[1, 5, 16], [2]]
    assert extract_source_indices("全角〔来源：3，9〕") == [[3, 9]]
    assert extract_source_indices("没有标记") == []


def test_build_sample_jobs_order_and_mapping():
    """sample_jobs 全局连续编号（A 先 B 后）与 record_id/company 映射。"""
    from app.strategy import jd_report_sampling as smp
    selection = {
        "a_selected": [_job_item("recA", "岗位甲", company="甲公司")],
        "b_selected": [_job_item("recB", "岗位乙", company="乙公司"), _job_item("recB2", "岗位丙", company="")],
    }
    jobs = smp.build_sample_jobs(selection)
    assert [j["idx"] for j in jobs] == [1, 2, 3]
    assert jobs[0] == {"idx": 1, "grade": "A", "company": "甲公司", "title": "岗位甲", "record_id": "recA"}
    assert jobs[2]["company"] == ""  # 公司缺失不阻塞映射


def test_build_sample_text_company_heading():
    """样本标题带公司名（LLM 需据此写差异例外；编号与 sample_jobs 同序）。"""
    from app.strategy import jd_report_sampling as smp
    selection = {
        "a_selected": [_job_item("recA", "岗位甲", company="甲公司")],
        "b_selected": [_job_item("recB", "岗位乙", company="乙公司")],
    }
    text = smp.build_sample_text(selection)
    assert "【A级岗位 1：甲公司·岗位甲】" in text
    assert "【B级岗位 2：乙公司·岗位乙】" in text
