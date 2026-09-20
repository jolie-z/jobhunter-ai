"""
测试智联招聘 URL 构建与翻页参数规范化，防止搜索框输入被数字覆盖
"""
import sys
import os
import urllib.parse
import pytest

CURRENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZHILIAN_DIR = os.path.join(CURRENT_DIR, "zhilian_scraper")
if ZHILIAN_DIR not in sys.path:
    sys.path.insert(0, ZHILIAN_DIR)

# zhilian_collector 与 resume_editor/platforms 下同名模块裸名冲突，显式按路径加载爬虫侧模块
import importlib.util

_collector_spec = importlib.util.spec_from_file_location(
    "zhilian_collector_scraper", os.path.join(ZHILIAN_DIR, "zhilian_collector.py")
)
zhilian_collector = importlib.util.module_from_spec(_collector_spec)
sys.modules[_collector_spec.name] = zhilian_collector
_collector_spec.loader.exec_module(zhilian_collector)

_build_zhilian_jobs_url = zhilian_collector._build_zhilian_jobs_url
get_city_code = zhilian_collector.get_city_code
from zhilian_nl_controller import _build_crawler_cmd


def test_build_zhilian_jobs_url_page_1():
    url = _build_zhilian_jobs_url(city="广州", keyword="AI产品经理", page_num=1)
    assert "jl=763" in url
    assert "kw=" + urllib.parse.quote("AI产品经理") in url
    assert "&p=" not in url


def test_build_zhilian_jobs_url_page_10():
    url = _build_zhilian_jobs_url(city="广州", keyword="AI产品经理", page_num=10)
    assert "jl=763" in url
    assert "kw=" + urllib.parse.quote("AI产品经理") in url
    assert "&p=10" in url


def test_build_zhilian_crawler_cmd():
    cmd = _build_crawler_cmd(
        crawler_path="/path/to/zhilian_collector.py",
        keyword="AI产品经理",
        city="广州",
        start_page=1,
        target_jobs=10,
        salary="15K-25K"
    )
    assert "-p" in cmd and "1" in cmd
    assert "--keyword" in cmd and "AI产品经理" in cmd
    assert "--target" in cmd and "10" in cmd
    assert "--city" in cmd and "广州" in cmd
    assert "--salary" in cmd and "15K-25K" in cmd
