"""Project Pruner 提示词保底约束防回归（W-2 裁剪护栏）。

背景：2026-09-19 QA 实测 Project Pruner 对 4 个项目全判 kill，用户一键确认后
「项目经历」板块清空，下游初改报错。修复在系统提示追加"至少保留"保底约束——
本用例锁定关键句，防止提示词被改回无保底版本。纯源码断言，不调用 LLM。
"""
import inspect

from app.strategy.ai_diagnosis_service import filter_projects_service


def test_project_pruner_prompt_has_keep_floor():
    src = inspect.getsource(filter_projects_service)
    assert "保底约束" in src, "Project Pruner 系统提示缺少【保底约束】段"
    assert "允许全部 kill" in src, "缺少全 kill 唯一豁免条款"
    assert "至少保留相关度最高的" in src, "缺少'至少保留相关度最高的 1-2 个'保底规则"
    assert "保底保留" in src, "缺少低分场景'保底保留'标注要求"
    assert "优先级最高" in src, "缺少保底约束优先级声明"
