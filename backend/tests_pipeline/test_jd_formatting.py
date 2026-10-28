"""2026-10-07 JD 排版修复回归：BOSS/猎聘岗位详情保留换行结构。

真机实证（0.1.6）：51job/智联的 jd_text 带换行渲染正常，BOSS（textContent 无
<p>/<br> 换行）与猎聘（' '.join(split()) 抹平换行）渲染成一团。本文件锁定修复行为。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 根（engine_guard 等顶层模块）


# ---------- 猎聘：clean_job_description 保留段落 ----------

def test_liepin_preserves_paragraphs():
    from liepin_scraper.liepin_crawler import clean_job_description

    raw = "职位介绍\n岗位职责\n1、参与 AI Agent 核心功能设计\n2、开发 Tool/MCP 工具\n\n\n任职要求\n1、本科以上\n猎聘温馨提示：投递须知"
    out = clean_job_description(raw)
    # "职位介绍" 是起始标记被剥离；"岗位职责" 是正文段落标题，应保留
    assert out.startswith("岗位职责"), out
    assert "\n1、参与 AI Agent 核心功能设计" in out, f"换行丢失: {out!r}"
    assert "猎聘温馨提示" not in out
    assert "\n\n任职要求" in out, f"段间距空行缺失: {out!r}"


def test_liepin_single_line_stays_single():
    from liepin_scraper.liepin_crawler import clean_job_description

    out = clean_job_description("职位介绍 负责A   与   B 的开发 猎聘温馨提示xx")
    assert "\n" not in out
    assert "  " not in out  # 行内多空白仍压缩
    assert out.startswith("负责A")


# ---------- BOSS：_extract_clean_jd 从 HTML 重建换行 ----------

class _FakeEle:
    def __init__(self, html: str = "", text: str = ""):
        self._html, self.text = html, text

    @property
    def html(self):
        return self._html


class _FakeBox:
    def __init__(self, ele):
        self._ele = ele

    def ele(self, *args, **kwargs):
        return self._ele


def test_boss_jd_html_to_newlines():
    from boss_scraper.boss_collector import _extract_clean_jd

    box = _FakeBox(_FakeEle(
        html='<style>.jd{color:red}</style><div><p>职责描述：</p><p>1、负责 Web 及 App 端测试<br>2、编写测试用例</p>'
             '<p>任职要求：本科以上</p><span>kanzhun 水印</span><script>var a=1;</script></div>'
    ))
    out = _extract_clean_jd(box)
    assert "职责描述：" in out and "1、负责 Web 及 App 端测试" in out
    assert "\n2、编写测试用例" in out, f"<br> 换行丢失: {out!r}"
    assert "\n任职要求：本科以上" in out or "\n\n任职要求：本科以上" in out, f"</p> 换行丢失: {out!r}"
    assert "kanzhun" not in out and "<" not in out, f"水印/标签残留: {out!r}"
    assert "color:red" not in out and "var a=1" not in out, f"script/style 正文残留: {out!r}"


def test_boss_jd_fallback_to_text():
    from boss_scraper.boss_collector import _extract_clean_jd

    box = _FakeBox(_FakeEle(html="", text="纯文本兜底内容"))
    out = _extract_clean_jd(box)
    assert out == "纯文本兜底内容", out


def test_boss_jd_empty():
    from boss_scraper.boss_collector import _extract_clean_jd

    assert _extract_clean_jd(_FakeBox(_FakeEle())) == ""
    assert _extract_clean_jd(_FakeBox(None)) == ""
