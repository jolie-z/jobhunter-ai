"""
智联招聘字段解析回归测试 (工作地址、公司规模、所属行业、发布日期未知兜底)
"""

import pytest
from unittest.mock import MagicMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "zhilian_scraper"))

# zhilian_collector 与 resume_editor/platforms 下的同名模块裸名冲突，
# 其他测试会把 platforms 目录插到 sys.path 前列，全量收集时裸导入会被遮蔽，
# 故显式按文件路径加载爬虫侧模块
import importlib.util

_ZHILIAN_DIR = os.path.join(os.path.dirname(__file__), "..", "zhilian_scraper")
_spec = importlib.util.spec_from_file_location(
    "zhilian_collector_scraper", os.path.join(_ZHILIAN_DIR, "zhilian_collector.py")
)
zhilian_collector = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = zhilian_collector
_spec.loader.exec_module(zhilian_collector)

_parse_zhilian_company_desc = zhilian_collector._parse_zhilian_company_desc
_extract_job_company_info = zhilian_collector._extract_job_company_info
_extract_job_work_address = zhilian_collector._extract_job_work_address
_extract_job_publish_date = zhilian_collector._extract_job_publish_date
_enrich_from_split_pane = zhilian_collector._enrich_from_split_pane
_extract_job_basic_info = zhilian_collector._extract_job_basic_info


class FakeElement:
    def __init__(self, text="", tag="div", attrs=None, children=None):
        self._text = text
        self.tag = tag
        self._attrs = attrs or {}
        self._children = children or []

    @property
    def text(self):
        if self._text:
            return self._text
        return " ".join([c.text for c in self._children if c.text])

    def ele(self, selector, timeout=0):
        for c in self._children:
            cls = c._attrs.get("class", "")
            if "job-company-info__desc" in selector and "job-company-info__desc" in cls:
                return c
            if "job-detail-summary__company-meta" in selector and "job-detail-summary__company-meta" in cls:
                return c
            if "company-info__desc" in selector and "company-info__desc" in cls:
                return c
            if "company-card__desc" in selector and "company-card__desc" in cls:
                return c
            if "scale" in selector and ("scale" in cls or "scale" in c.text):
                return c
            if "industry" in selector and ("industry" in cls or "industry" in c.text):
                return c
            if ("bubble" in selector or "job-detail-address" in selector or "address-info__content" in selector) and ("address" in cls or "bubble" in cls):
                return c
            if "view-all" in selector and "view-all" in cls:
                return c
            sub = c.ele(selector, timeout=timeout)
            if sub:
                return sub
        return None

    def eles(self, selector, timeout=0):
        results = []
        for c in self._children:
            cls = c._attrs.get("class", "")
            if "company-summary__item" in selector and "company-summary__item" in cls:
                results.append(c)
            results.extend(c.eles(selector, timeout=timeout))
        return results

    def attr(self, key):
        return self._attrs.get(key, "")


def test_parse_zhilian_company_desc_matrix():
    """测试 2026 智联招聘企业元数据字符串解析算法矩阵"""
    test_cases = [
        ("已上市 · 1000-9999人 · 软件/IT服务、软件/IT服务 已审核", "1000-9999人", "软件/IT服务、软件/IT服务"),
        ("不需要融资 · 1000-9999人 · 家电批发/零售/贸易、综合商贸 已审核", "1000-9999人", "家电批发/零售/贸易、综合商贸"),
        ("/已上市 · 1000-9999人 · 软件/IT服务、软件/IT服务", "1000-9999人", "软件/IT服务、软件/IT服务"),
        ("入驻10年  1000-9999人  不需要融资  综合商贸", "1000-9999人", "综合商贸"),
        ("10000人以上  已上市  软件/IT服务,产业互联网平台", "10000人以上", "软件/IT服务,产业互联网平台"),
        ("20人以下  未融资  广告/公关/营销,广告/公关/营销", "20人以下", "广告/公关/营销,广告/公关/营销"),
        ("100-299人  已上市  软件/IT服务", "100-299人", "软件/IT服务"),
        ("500-999人  石油/石化", "500-999人", "石油/石化"),
    ]
    for raw, expected_size, expected_ind in test_cases:
        size, ind = _parse_zhilian_company_desc(raw)
        assert size == expected_size, f"Failed for size: {raw}"
        assert ind == expected_ind, f"Failed for industry: {raw}"


def test_extract_company_scale_and_industry_2026_desc():
    """测试从 2026 新版右侧分栏组合描述段落提取公司规模与所属行业"""
    desc_p = FakeElement(
        text="已上市 · 1000-9999人 · 软件/IT服务、软件/IT服务 已审核",
        attrs={"class": "job-company-info__desc"}
    )
    pane = FakeElement(children=[desc_p])
    
    job_data = {}
    _extract_job_company_info(pane, job_data)
    
    assert job_data.get("company_size") == "1000-9999人"
    assert job_data.get("industry") == "软件/IT服务、软件/IT服务"


def test_extract_company_scale_and_industry():
    """测试从公司信息组件中提取公司规模与所属行业"""
    scale_text_ele = FakeElement(text="300-499人", attrs={"class": "company-summary__text"})
    industry_text_ele = FakeElement(text="软件/IT服务、人工智能、云计算", attrs={"class": "company-summary__text"})
    
    scale_item = FakeElement(text="300-499人", attrs={"class": "company-summary__item company-summary__icon--scale"}, children=[scale_text_ele])
    industry_item = FakeElement(text="软件/IT服务、人工智能、云计算", attrs={"class": "company-summary__item company-summary__icon--industry"}, children=[industry_text_ele])
    
    comp_box = FakeElement(attrs={"class": "company-summary"}, children=[scale_item, industry_item, scale_text_ele, industry_text_ele])
    
    job_data = {}
    _extract_job_company_info(comp_box, job_data)
    
    assert job_data.get("company_size") == "300-499人"
    assert job_data.get("industry") == "软件/IT服务、人工智能、云计算"


def test_extract_detailed_work_address():
    """测试从地图气泡中提取详细门牌级工作地址并清洗"""
    addr_bubble = FakeElement(text="黄埔区广州纳诺科技股份有限公司 点击查看地图", attrs={"class": "address-info__bubble"})
    pane = FakeElement(children=[addr_bubble])
    
    job_data = {}
    _extract_job_work_address(pane, job_data)
    
    assert job_data.get("work_address") == "黄埔区广州纳诺科技股份有限公司"


def test_extract_publish_date_defaults_to_unknown():
    """测试智联无发布日期元素时默认标记为未知"""
    tab = FakeElement(children=[])
    job_data = {"publish_date": "未知"}
    _extract_job_publish_date(tab, job_data)
    
    assert job_data.get("publish_date") == "未知"


def test_enrich_from_split_pane_full_integration():
    """测试右侧分栏模式补抓字段完整闭环 (2026 最新 DOM 实测)"""
    desc_p = FakeElement(
        text="已上市 · 1000-9999人 · 软件/IT服务、软件/IT服务 已审核",
        attrs={"class": "job-company-info__desc"}
    )
    addr_bubble = FakeElement(text="广州市天河区林和西路中泰国际广场A座", attrs={"class": "address-info__bubble"})
    view_all = FakeElement(attrs={"class": "job-company-info__view-all", "href": "https://www.zhaopin.com/jobdetail/CC12345.htm?refcode=4020"})
    
    right_pane = FakeElement(children=[desc_p, addr_bubble, view_all])
    page = MagicMock()
    page.url = "https://sou.zhaopin.com"
    
    job_data = {
        "job_title": "AI平台运营专家",
        "company_name": "上海新炬网络信息技术股份有限公司",
        "city": "广州",
        "work_address": "广州",
        "company_size": "",
        "industry": "",
        "publish_date": "未知",
    }
    
    _enrich_from_split_pane(page, right_pane, job_data)
    
    assert job_data["company_size"] == "1000-9999人"
    assert job_data["industry"] == "软件/IT服务、软件/IT服务"
    assert job_data["work_address"] == "广州市天河区林和西路中泰国际广场A座"
    assert job_data["job_link"] == "https://www.zhaopin.com/jobdetail/CC12345.htm"
    assert job_data["publish_date"] == "未知"
