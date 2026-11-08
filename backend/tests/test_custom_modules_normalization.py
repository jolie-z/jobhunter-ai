"""自定义模块条目出口归一化测试（2026-10-28 原文保真改造）。

背景：自定义模块（论文/获奖/开源等）字段语义不通用，LLM 把内容塞进 company/title/years
的位置随机，而编辑器对自定义条目默认不渲染这三个字段行——曾经导致「PDF 预览有、
编辑器没有」。归一化在结构化唯一出口把非空标准字段折叠进 description，保证编辑器
可见 ≡ 打印可见。

全部 mock OpenAI client，不触网；被测模块在用例内 import（与 test_resume_structurer_progress 同规）。
"""
import json

import pytest


class _Delta:
    def __init__(self, content):
        self.content = content


class _Chunk:
    def __init__(self, content):
        self.choices = [type("C", (), {})()]
        self.choices[0].delta = _Delta(content)


class _StreamCompletions:
    """流式与非流式两条通道都返回同一份 reply（parse_resume_to_json 无 progress_cb 时走非流式）。"""

    def __init__(self, reply):
        self._reply = reply

    def create(self, **kwargs):
        if kwargs.get("stream"):
            return iter([_Chunk(self._reply)])
        resp = type("R", (), {})()
        resp.choices = [type("C", (), {})()]
        resp.choices[0].message = type("M", (), {})()
        resp.choices[0].message.content = self._reply
        return resp


class _FakeClient:
    def __init__(self, completions):
        self.chat = type("Chat", (), {})()
        self.chat.completions = completions


@pytest.fixture
def fake_llm(monkeypatch):
    def _install(reply):
        from app.core import resume_structurer
        monkeypatch.setattr(
            resume_structurer, "get_openai_client", lambda: _FakeClient(_StreamCompletions(reply))
        )
    return _install


def _parse(fake_llm, structured: dict) -> dict:
    import asyncio

    from app.core import resume_structurer
    fake_llm(json.dumps(structured, ensure_ascii=False))
    return asyncio.run(resume_structurer.parse_resume_to_json("MD"))


def test_normalize_folds_std_fields_into_description(fake_llm):
    """LLM 把期刊/论文题名塞进 company/title → 折叠进 description 头部（按 company→title→years 序）并清空。"""
    result = _parse(fake_llm, {
        "moduleOrder": ["publications"],
        "moduleTitles": {"publications": "论文及专著"},
        "customModules": {
            "publications": [
                {
                    # 外审 R3-P1-2：不得使用真实论文题名/卷期号（可反查定位自然人），一律虚构占位
                    "company": "Journal of Synthetic Studies 10(1): e0000001",
                    "title": "A synthetic study on resume module normalization pipelines",
                    "years": "",
                    "description": ["Journal of Synthetic Studies 10(1): e0000001"],
                }
            ]
        },
    })

    item = result["customModules"]["publications"][0]
    assert item["description"] == [
        "Journal of Synthetic Studies 10(1): e0000001",
        "A synthetic study on resume module normalization pipelines",
        "Journal of Synthetic Studies 10(1): e0000001",
    ]
    assert item["company"] == ""
    assert item["title"] == ""
    assert item["years"] == ""


def test_normalize_keeps_description_order_and_extras(fake_llm):
    """已有 description 保持原序追加在折叠行之后；用户自建 KV 等额外字段原样保留。"""
    result = _parse(fake_llm, {
        "moduleOrder": ["awards"],
        "moduleTitles": {"awards": "获奖经历"},
        "customModules": {
            "awards": [
                {
                    "title": "国家奖学金",
                    "description": ["2021 年度，覆盖率 1%"],
                    "颁发机构": "教育部",
                }
            ]
        },
    })

    item = result["customModules"]["awards"][0]
    assert item["description"] == ["国家奖学金", "2021 年度，覆盖率 1%"]
    assert item["颁发机构"] == "教育部"
    assert item["title"] == ""


def test_normalize_skips_already_clean_items(fake_llm):
    """归一化后的干净条目（纯 description）零改动——幂等，重试流水线二次进入不重复折叠。"""
    result = _parse(fake_llm, {
        "moduleOrder": ["publications"],
        "moduleTitles": {"publications": "论文及专著"},
        "customModules": {
            "publications": [{"company": "", "title": "", "years": "", "description": ["第一作者 (In preparation)"]}]
        },
    })
    item = result["customModules"]["publications"][0]
    # Pydantic 会补 location=None 等 schema 默认值，只断言业务字段
    assert item["description"] == ["第一作者 (In preparation)"]
    assert (item["company"], item["title"], item["years"]) == ("", "", "")


def test_normalize_tolerates_malformed_entries():
    """纯函数防御：非 list 的模块值 / 非 dict 的条目直接跳过，不抛错。

    经 parse_resume_to_json 时 Pydantic 已拦掉这类形态，这里直测函数本体，
    保证被其他调用方喂原始 dict 时同样稳。
    """
    from app.core.resume_structurer import _normalize_custom_modules

    data = {
        "customModules": {
            "a": "纯字符串旧形态",
            "b": ["字符串条目", {"title": "T", "description": []}],
        }
    }
    result = _normalize_custom_modules(data)
    assert result["customModules"]["a"] == "纯字符串旧形态"
    assert result["customModules"]["b"][0] == "字符串条目"
    assert result["customModules"]["b"][1]["description"] == ["T"]
    assert result["customModules"]["b"][1]["title"] == ""

    # customModules 缺失 / 非 dict 原样返回
    assert _normalize_custom_modules({"summary": "x"}) == {"summary": "x"}
    assert _normalize_custom_modules({"customModules": []}) == {"customModules": []}


def test_normalize_clears_whitespace_only_std_fields():
    """纯空白的 company/title/years 即便无可折叠内容也清成 ""（前端按真值画行，" " 会被当成有内容）。"""
    from app.core.resume_structurer import _normalize_custom_modules

    data = {"customModules": {"x": [{"company": "   ", "title": "\t", "years": "", "description": ["正文"]}]}}
    item = _normalize_custom_modules(data)["customModules"]["x"][0]
    assert (item["company"], item["title"], item["years"]) == ("", "", "")
    assert item["description"] == ["正文"]  # 没有东西被折叠进去


def test_normalize_no_custom_modules_noop(fake_llm):
    """无自定义模块的常规简历零影响。"""
    result = _parse(fake_llm, {
        "moduleOrder": ["summary"],
        "moduleTitles": {"summary": "个人总结"},
        "summary": "hello",
        "workExperience": [{"company": "某公司", "title": "工程师", "years": "2020-2023", "description": ["做事"]}],
    })
    # 标准模块字段不受归一化影响
    assert result["workExperience"][0]["company"] == "某公司"
    assert result["summary"] == "hello"


# ---------------------------------------------------------------------------
# 后端 HTML 渲染器（投递材料链路）对自定义模块的对齐
# ---------------------------------------------------------------------------
def _build_html(custom_modules: dict) -> str:
    from app.core.resume_html_builder import build_resume_html

    # personalInfo.name 必填：为空会触发向飞书拉基准简历的容错网络请求
    return build_resume_html({
        "personalInfo": {"name": "测试者"},
        "moduleOrder": list(custom_modules.keys()),
        "moduleTitles": {k: k for k in custom_modules},
        "customModules": custom_modules,
    })


def test_html_builder_renders_custom_items_structurally():
    """此前对条目列表 str() 直出 Python 字典原文；现应逐条渲染且不出现 dict 形态碎片。"""
    html = _build_html({
        "publications": [
            {"company": "", "title": "", "years": "", "description": ["第一作者 (In preparation)", "JSS 10(1)"]},
        ]
    })
    assert "第一作者 (In preparation)" in html
    assert "JSS 10(1)" in html
    assert "{'" not in html and "'description'" not in html
    # 纯 description 条目：不渲染空表头行
    assert 'class="item-grid"' not in html


def test_html_builder_custom_item_header_and_extras():
    """老数据非空 company/title 仍渲染表头行；用户自建 KV 字段拼副标题行；原件标量键不重复。"""
    html = _build_html({
        "awards": [
            {"company": "教育部", "title": "国家奖学金", "years": "2021", "description": ["覆盖率 1%"], "级别": "国家级"},
        ]
    })
    assert 'class="item-grid"' in html
    assert "教育部" in html and "国家奖学金" in html and "2021" in html
    assert '<div class="item-subtitle">级别：国家级</div>' in html
    assert "覆盖率 1%" in html


def test_html_builder_escapes_header_and_renders_location():
    """表头/副标题原文须 html.escape（论文题名常含 `<`、`&`）；location 不得被静默丢弃，进副标题行首。"""
    html = _build_html({
        "publications": [
            {
                "company": "A & B Lab",
                "title": "Effect size p < 0.05 in <cohort>",
                "years": "2024",
                "location": "Boston",
                "description": [],
                "影响因子": "11.1",
            },
        ]
    })
    assert "A &amp; B Lab" in html
    assert "p &lt; 0.05 in &lt;cohort&gt;" in html
    assert "<cohort>" not in html  # 原始尖括号不得以标签形态落入 HTML
    assert '<div class="item-subtitle">Boston · 影响因子：11.1</div>' in html


def test_html_builder_skips_blank_extras():
    """值为空/纯空白的自建字段不渲染，避免悬空的「字段名：」；纯空白的标准字段也不得撑出空表头行。"""
    html = _build_html({
        "awards": [{"company": "   ", "title": "\t", "years": "", "description": ["正文"], "备注": "   ", "级别": ""}],
    })
    assert "备注" not in html and "级别" not in html
    assert 'class="item-subtitle"' not in html  # 样式表里的 .item-subtitle 定义不算，断言渲染出的元素
    assert 'class="item-grid"' not in html  # 纯空白 company/title 在 Python 里为真值，必须 strip 后再判
