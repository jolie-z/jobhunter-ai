"""打印分页大空白回归测试（2026-11-03 用户工单：猎聘/智联/51job 改写简历 PDF 页中大段空白）

背景：后端 build_resume_html 的投递 PDF 渲染链路未同步前端打印模板的「三弹修复」——
  弹1 .resume-items flex column → block（Chromium 对 flex column 容器分页支持差，
       整容器被推到下页致前一页留大白，前端修复 c9d437a2）
  弹2 .item-grid grid → flex（grid 容器跨页特性与 flex 同病，前端修复同 commit）
  弹3 .section-title page-break-after: avoid → auto（标题与内容捆死，页底放不下
       「标题+首条」整捆时连标题带位置让给下页，前页整段空白）
本文件用样式断言锁定三处规则不回退（真渲染分页度量另有对照实验脚本验证：
非末页最大空白 124pt → 36pt）。
"""
import re

from app.core.resume_html_builder import build_resume_html


def _build() -> str:
    return build_resume_html({
        "personalInfo": {"name": "测试", "jobIntent": "AI应用工程师",
                          "contactsList": [{"label": "电话", "value": "13800000000"}]},
        "moduleOrder": ["workExperience", "education"],
        "moduleTitles": {"workExperience": "工作经历", "education": "教育经历"},
        "workExperience": [
            {"company": "公司A", "title": "工程师", "years": "2024.04-至今",
             "description": "- 要点一\n- 要点二"},
        ],
        "education": [{"institution": "某大学", "major": "计算机", "years": "2018-2022"}],
    })


def test_items_container_not_flex_column():
    """弹1：.resume-items 不得是 flex column 容器（整容器让位 = 前页大段空白）。"""
    html = _build()
    m = re.search(r"\.resume-items\s*\{([^}]*)\}", html)
    assert m, "缺少 .resume-items 样式定义"
    body = m.group(1)
    assert "flex-direction: column" not in body, \
        ".resume-items 回退成了 flex column——Chromium 打印分页会把整容器推到下页（历史事故复燃）"
    assert "display: block" in body


def test_item_grid_uses_flex_not_grid():
    """弹2：.item-grid 不得是 grid 布局（grid 整块让位同病）。"""
    html = _build()
    m = re.search(r"\.item-grid\s*\{([^}]*)\}", html)
    assert m, "缺少 .item-grid 样式定义"
    body = m.group(1)
    assert "display: grid" not in body, \
        ".item-grid 回退成了 grid——跨页时整块推到下页致前页留白（历史事故复燃）"
    assert "display: flex" in body


def test_section_title_not_glued_to_content():
    """弹3：@media print 内所有含 .section-title 的规则（含 h1,h2,h3,.section-title
    合并选择器）都不得出现 page-break-after: avoid（标题+首条整捆让位 = 页中空白）。"""
    html = _build()
    print_block = re.search(r"@media print\s*\{.*$", html, re.S)
    assert print_block, "缺少 @media print 块"
    title_rules = re.findall(r"[^{}]*\.section-title[^{]*\{([^}]*)\}", print_block.group(0))
    assert title_rules, "打印上下文中未找到 .section-title 规则"
    for body in title_rules:
        assert "page-break-after: avoid" not in body, \
            f".section-title 在打印上下文捆死了后续内容（历史事故复燃）: {body!r}"
    # 显式断言弹3修复存在：打印上下文中标题规则含 page-break-after: auto
    assert any("page-break-after: auto" in body for body in title_rules), \
        "打印上下文中 .section-title 缺少 page-break-after: auto（弹3修复缺失）"


def test_oversized_item_allowed_to_break():
    """超大条目允许跨页：.resume-item 若 page-break-inside: avoid，页底剩余空间
    放不下整条（实测单条可达 248pt）时整条让位，前页出现大段空白。
    修复口径：条目内部用 orphans/widows 防孤儿行，但不再整条捆死。"""
    html = _build()
    m = re.search(r"\.resume-item\s*\{([^}]*)\}", html)
    assert m, "缺少 .resume-item 样式定义"
    assert "page-break-inside" not in m.group(1), \
        ".resume-item 基础样式不应包含 page-break-inside（由打印上下文统一管理）"
    # 基础样式里无 page-break-inside；@media print 里若有必须为 auto
    print_block = re.search(r"@media print\s*\{.*$", html, re.S)
    assert print_block, "缺少 @media print 块"
    item_rules = re.findall(r"\.resume-item\s*\{([^}]*)\}", print_block.group(0))
    assert item_rules, "打印上下文中未找到 .resume-item 规则（选择器改名会导致本测试空转假阳性）"
    for body in item_rules:
        if "page-break-inside" in body:
            assert "avoid" not in body, \
                ".resume-item 在打印上下文捆死为不跨页——大条目会让位产生页中大段空白（历史事故复燃）"
