"""
自动化测试：双阀门动态路由联动 (精投流转阈值 vs 海投自动投递等级)
1. 测试 route_after_evaluate 动态读取 get_auto_eval_threshold
   - threshold="A" 时：A级走 rewrite_node，B/C级走 quick_greeting_node
   - threshold="B" 时：A/B级走 rewrite_node，C级走 quick_greeting_node
2. 测试 route_before_delivery 动态读取 auto_deliver_grades 与大厂规模
   - 命中白名单且规模<1000人 -> delivery_node
   - 未在白名单中 -> manual_review_node
   - 海投大厂 (规模>=1000人) -> manual_review_node
"""

import pytest
from app.automation.workflow import route_after_evaluate, route_before_delivery
from app.automation.db import update_autopilot_config


def test_route_after_evaluate_threshold_A(monkeypatch):
    import ai_agents.ai_evaluator as evaluator
    monkeypatch.setattr(evaluator, "get_auto_eval_threshold", lambda: "A")

    # A 级 -> 精投
    state_a = {"grade": "A", "error": ""}
    assert route_after_evaluate(state_a) == "rewrite_node"

    # B 级 -> 动态降级为海投
    state_b = {"grade": "B", "error": ""}
    assert route_after_evaluate(state_b) == "quick_greeting_node"

    # C 级 -> 海投
    state_c = {"grade": "C", "error": ""}
    assert route_after_evaluate(state_c) == "quick_greeting_node"


def test_route_after_evaluate_threshold_B(monkeypatch):
    import ai_agents.ai_evaluator as evaluator
    monkeypatch.setattr(evaluator, "get_auto_eval_threshold", lambda: "B")

    # A 级 -> 精投
    state_a = {"grade": "A", "error": ""}
    assert route_after_evaluate(state_a) == "rewrite_node"

    # B 级 -> 精投
    state_b = {"grade": "B", "error": ""}
    assert route_after_evaluate(state_b) == "rewrite_node"

    # C 级 -> 海投
    state_c = {"grade": "C", "error": ""}
    assert route_after_evaluate(state_c) == "quick_greeting_node"

    # 门禁只看评级：高分 C 不能越级进精投，低分 B 仍应进精投。
    state_c_high_score = {"grade": "C", "ai_score": 99, "error": ""}
    assert route_after_evaluate(state_c_high_score) == "quick_greeting_node"
    state_b_low_score = {"grade": "B", "ai_score": 10, "error": ""}
    assert route_after_evaluate(state_b_low_score) == "rewrite_node"


def test_route_before_delivery_auto_grades_and_scale(tmp_path, monkeypatch):
    import app.automation.db as adb
    monkeypatch.setattr(adb, "DB_PATH", str(tmp_path / "autopilot.db"))
    adb.init_autopilot_db()

    # 配置白名单仅包含 C、D，海投门槛 1000 人
    update_autopilot_config(
        auto_deliver_grades=["C", "D", "E", "F"],
        auto_deliver_platforms=["zhilian", "boss"],
        mass_apply_max_headcount=1000,
    )

    # 1. C 级中小厂 (规模 100-499人) -> 命中白名单，直接投递
    state_c_small = {
        "grade": "C",
        "platform": "zhilian",
        "final_markdown": "",
        "feishu_fields": {"公司规模": "100-499人"},
        "error": "",
    }
    assert route_before_delivery(state_c_small) == "delivery_node"

    # 2. C 级大厂 (规模 10000人以上) -> 命中大厂门槛，挂起审批
    state_c_big = {
        "grade": "C",
        "platform": "zhilian",
        "final_markdown": "",
        "feishu_fields": {"公司规模": "10000人以上"},
        "error": "",
    }
    assert route_before_delivery(state_c_big) == "manual_review_node"

    # 3. B 级岗位 (未在 auto_deliver_grades 中) -> 未选挂审，挂起审批
    state_b_custom = {
        "grade": "B",
        "platform": "zhilian",
        "final_markdown": "定制改写简历正文...",
        "feishu_fields": {"公司规模": "100-499人"},
        "error": "",
    }
    assert route_before_delivery(state_b_custom) == "manual_review_node"
