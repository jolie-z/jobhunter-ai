"""
猎聘 - 简历数据回写推送脚本（模块级，v2）
读取猎聘 tab「保存为回写数据源」生成的快照（liepin_writeback.json，编辑器最新数据），
通过 api-c.liepin.com 真实 API 回写到官网。快照不存在时回退 liepin_fields.json。

已确认的模块 API（2026-08-04 逆向 + no-op 验证全部 flag:1）：
  basic_info       save-base-info      (form)  encryResId&birthday&cityCode&...
  self_assessment  save-self-assess    (JSON data: encryResId, selfAssessment)
  expectations     save-job-want.v4    (JSON data: encryResId, id, dqCode, jobtitleCode, wantSalaryLow/High/Months, otherExpectDqCodes[], industryCodes)
  work_experience  save-work-exp.v3    (JSON data: encryResId, id, compName, dept, dq, industry, jobtitle, title, duty, salmonths, shieldComp, startDate, endDate, report2, subordinate, workType)
  projects         save-project-exp    (JSON data: encryResId, id, name, compName, title, startDate, endDate, desc, duty, achievement)
  education        save-edu-exp.v2     (JSON data: encryResId, id, school, degree, special, tz, startDate, endDate)
  certificates     save-credential     (form)  encryResId&credentialCodes=["C0002"]
  skill_tags       save-personal-labels(JSON data: encryResId, labels[{label,type}])
  languages        save-language       (JSON data: encryResId, code, degreeCode, levelCode, originalCode)
  additional_info  save-addition-info  (form)  encryResId&additionInfo=...

用法：python liepin_pusher.py [--modules 模块1,模块2,...]
      --modules 不传 = 全部模块
前提：Edge 浏览器已启动且已登录猎聘（端口由全项目统一配置区 registry 提供）
"""

import argparse
import json
import os
import re as _re
import sys
import time
import urllib.request
import uuid

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(os.path.dirname(_SCRIPT_DIR))
DATA_DIR = os.path.join(_BACKEND_DIR, "resume_editor", "data")
SNAPSHOT_PATH = os.path.join(DATA_DIR, "liepin_writeback.json")
FIELDS_PATH = os.path.join(DATA_DIR, "liepin_fields.json")
LANG_DICT_PATH = os.path.join(DATA_DIR, "liepin_lang_dict.json")
CERT_DICT_PATH = os.path.join(DATA_DIR, "liepin_cert_dict.json")

sys.path.insert(0, _SCRIPT_DIR)
from browser_common import get_platform_port

PORT = get_platform_port("liepin")
LIEPIN_RESUME_URL = "https://c.liepin.com/resume/edit"
API_BASE = "https://api-c.liepin.com/api"

ALL_MODULES = [
    "basic_info", "self_assessment", "expectations", "work_experience",
    "projects", "education", "certificates", "skill_tags", "languages",
    "additional_info",
]

# 码表
DEGREE_MAP = {  # 学历名 -> degree 码（取自官网 bundle）
    "博士": "010", "MBA/EMBA": "020", "硕士": "030", "本科": "040",
    "大专": "050", "中专/中技": "060", "高中": "080", "初中及以下": "090",
}
WORK_STATUS_MAP = {  # 职场人求职状态
    "离职，正在找工作": "1", "在职，急寻新工作": "2", "在职，看看新机会": "0",
    "在职，暂无跳槽打算": "3", "离职": "1", "在职": "0",
}
STUDENT_STATUS_MAP = {  # 在校生状态
    "离校，正在找工作": "7", "在校，可即刻到岗": "6", "在校，看看机会": "5", "在校，暂时不找工作": "4",
}
POLITICAL_MAP = {
    "中共党员": "1", "中共预备党员": "2", "共青团员": "3", "群众": "4",
}
LANG_KIND = "0"  # 中文简历


def load_dicts():
    """加载城市/行业/职位/语言/证书字典"""
    def _load(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    cities = {}
    try:
        data = _load(os.path.join(DATA_DIR, "liepin_cities.json"))
        def _walk(d):
            if isinstance(d, dict):
                if "name" in d and "code" in d and isinstance(d["code"], str):
                    cities[d["name"]] = d["code"]
                for v in d.values():
                    _walk(v)
            elif isinstance(d, list):
                for v in d:
                    _walk(v)
        _walk(data)
    except Exception as e:
        print(f"  [WARN] 城市字典加载失败: {e}")

    industries = {}
    try:
        def _walk_i(items):
            for it in items:
                industries[it["name"]] = it["code"]
                _walk_i(it.get("subcategories", []))
        _walk_i(_load(os.path.join(DATA_DIR, "liepin_industry_categories.json")))
        industries["不限"] = "000"
        industries["全部行业"] = "000"
    except Exception as e:
        print(f"  [WARN] 行业字典加载失败: {e}")

    jobs = {}
    try:
        def _walk_j(items):
            for it in items:
                jobs[it["name"]] = it["code"]
                _walk_j(it.get("subcategories", []))
                for jb in it.get("jobs", []):
                    jobs[jb["name"]] = jb["code"]
        _walk_j(_load(os.path.join(DATA_DIR, "liepin_job_categories.json")))
    except Exception as e:
        print(f"  [WARN] 职位字典加载失败: {e}")

    langs = {}
    try:
        langs = _load(LANG_DICT_PATH)
    except Exception as e:
        print(f"  [WARN] 语言字典加载失败: {e}")

    certs = {}
    try:
        certs = _load(CERT_DICT_PATH).get("by_name", {})
    except Exception as e:
        print(f"  [WARN] 证书字典加载失败: {e}")

    return cities, industries, jobs, langs, certs


def fuzzy_find(name, mapping, existing_hits=None):
    """编码查找：精确 -> 包含 -> 现有记录（Name->Code 对）"""
    if not name:
        return None
    name = str(name).strip()
    if name in mapping:
        return mapping[name]
    # 包含匹配
    for key, code in mapping.items():
        if key and name and (key in name or name in key):
            return code
    # 现有记录
    if existing_hits:
        for hit_name, hit_code in existing_hits:
            if hit_name and (hit_name in name or name in hit_name):
                return hit_code
    return None


def norm_ym(value):
    """2023.09 / 2023-09 / 202309 / 2026年5月 -> 202309；至今/空 -> 999999（猎聘统一用 999999 表示"至今"）"""
    if not value:
        return None
    v = str(value).strip()
    if v in ("至今", "现在", "今"):
        return "999999"
    import re
    # 匹配 YYYY[-/.年]M[M]?
    m = re.search(r"(\d{4})[\-\./年](\d{1,2})", v)
    if m:
        year, month = m.group(1), m.group(2)
        return f"{year}{int(month):02d}"
    clean = v.replace("-", "").replace(".", "").replace("/", "").replace("年", "").replace("月", "")
    if len(clean) >= 6 and clean[:4].isdigit() and clean[4:6].isdigit():
        return clean[:6]
    if len(clean) == 5 and clean[:4].isdigit() and clean[4].isdigit():
        return f"{clean[:4]}0{clean[4]}"
    if len(clean) == 4 and clean.isdigit():  # 只有年份
        return clean + "01"
def parse_salary(value):
    """规范化薪资为元为单位（如 15k -> 15000, 1.5万 -> 15000, 25000 -> 25000, 15 -> 15000）"""
    if not value:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    import re
    m_wan = re.search(r"(\d+(?:\.\d+)?)\s*万", s)
    if m_wan:
        try:
            return int(float(m_wan.group(1)) * 10000)
        except Exception:
            pass
    m_k = re.search(r"(\d+(?:\.\d+)?)\s*k", s)
    if m_k:
        try:
            return int(float(m_k.group(1)) * 1000)
        except Exception:
            pass
    clean_digits = "".join(ch for ch in s if ch.isdigit())
    if clean_digits:
        num = int(clean_digits)
        if num < 100:  # 如 15-25，单位省略但实际代表 k
            return num * 1000
        return num
    return None


def norm_ymd(value):
    """解析日期为 8 位数字 YYYYMMDD（如 19960701），兼容 1996年07月、1996-07、1996.7、1996/07/01 等各类形态"""
    if not value:
        return None
    v = str(value).strip()
    import re
    # 匹配 YYYY[-/.年]M[M]?[-/.月日]D[D]?
    m_ymd = re.search(r"(\d{4})[\-\./年](\d{1,2})[\-\./月日](\d{1,2})", v)
    if m_ymd:
        return f"{m_ymd.group(1)}{int(m_ymd.group(2)):02d}{int(m_ymd.group(3)):02d}"
    # 匹配 YYYY[-/.年]M[M]?
    m_ym = re.search(r"(\d{4})[\-\./年](\d{1,2})", v)
    if m_ym:
        return f"{m_ym.group(1)}{int(m_ym.group(2)):02d}01"
    clean = re.sub(r"\D", "", v)
    if len(clean) >= 8 and clean[:8].isdigit():
        return clean[:8]
    if len(clean) >= 6 and clean[:6].isdigit():
        return clean[:6] + "01"
    if len(clean) == 4 and clean.isdigit():
        return clean + "0101"
    return None


class LiepinPusher:
    def __init__(self, modules, dry_run: bool = False):
        self.modules = [m for m in modules if m in ALL_MODULES]
        self.results = {}
        self.res_id = None
        self.xsrf = ""
        self.detail = None
        # dry-run 预览：构建 payload 但不实际发送（post_json/post_form 网关拦截）
        self.dry_run = dry_run

    def _skip_empty(self, mod: str, reason: str = "本地为空"):
        """空模块跳过语义（用户规则 2026-08-30）：跳过≠失败，不拖垮整体回写成败。"""
        self.results[mod] = {
            "success": True, "skipped": True, "count": 0, "ok": 0,
            "message": f"{reason}，跳过该模块（不影响官网已有内容）",
        }
        print(f"  [{mod}] SKIP: {reason}")

    # ---------- 浏览器 / 会话 ----------
    def connect(self):
        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from browser_common import connect_page, ensure_port_ready

        # 端口必须有 CDP 响应；无响应直接报错，绝不自动拉起浏览器（红线）
        ensure_port_ready(PORT)
        try:
            _tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=3))
            if not any(t.get("type") == "page" for t in _tabs):
                urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/json/new?about:blank", method="PUT"), timeout=3)
        except Exception:
            pass
        self.page = connect_page(PORT)
        self.tab = self.page.latest_tab
        self.tab.get(LIEPIN_RESUME_URL)
        time.sleep(8)

        self.xsrf = json.loads(self.page.run_js("""
        return (function() {
            var ck = document.cookie; var xsrf = '';
            ck.split(';').forEach(function(c) { var p = c.trim().split('='); if (p[0] === 'XSRF-TOKEN') xsrf = decodeURIComponent(p[1]); });
            return JSON.stringify(xsrf);
        })();
        """))
        if not self.xsrf:
            raise RuntimeError("未获取到 XSRF-TOKEN（可能未登录）")

    def post_json(self, path, body):
        """页面上下文 fetch（带完整认证头，credentials 自动带 cookie）"""
        if self.dry_run:
            return json.dumps({"code": 0, "msg": "DRY-RUN 预览（未实际发送）"}, ensure_ascii=False)
        js = f"""
        return (function() {{
            return new Promise(function(resolve) {{
                fetch('{API_BASE}/{path}', {{
                    method: 'POST', credentials: 'include',
                    headers: {{
                        'Accept': 'application/json, text/plain, */*',
                        'Content-Type': 'application/json;charset=utf-8;',
                        'X-Client-Type': 'web',
                        'X-Fscp-Fe-Version': '',
                        'X-Fscp-Version': '1.1',
                        'X-Fscp-Std-Info': JSON.stringify({{client_id: '40106'}}),
                        'X-Fscp-Bi-Stat': JSON.stringify({{location: 'https://c.liepin.com/resume/edit'}}),
                        'X-Fscp-Trace-Id': '{uuid.uuid4()}',
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-XSRF-TOKEN': '{self.xsrf}'
                    }},
                    body: JSON.stringify({json.dumps(body, ensure_ascii=False)})
                }}).then(r => r.json()).then(d => resolve(JSON.stringify(d))).catch(e => resolve('ERR: ' + e.message));
            }});
        }})();
        """
        return self.page.run_js(js)

    def post_form(self, path, form_dict):
        """表单格式（basic_info / credential / addition_info）"""
        if self.dry_run:
            return json.dumps({"code": 0, "msg": "DRY-RUN 预览（未实际发送）"}, ensure_ascii=False)
        import urllib.parse
        kv = []
        for k, v in form_dict.items():
            if isinstance(v, (list, dict)):
                v = json.dumps(v, ensure_ascii=False)
            kv.append(f"{k}={urllib.parse.quote(str(v), safe='')}")
        body_str = "&".join(kv)
        js = f"""
        return (function() {{
            return new Promise(function(resolve) {{
                fetch('{API_BASE}/{path}', {{
                    method: 'POST', credentials: 'include',
                    headers: {{
                        'Accept': 'application/json, text/plain, */*',
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'X-Client-Type': 'web',
                        'X-Fscp-Fe-Version': '',
                        'X-Fscp-Version': '1.1',
                        'X-Fscp-Std-Info': JSON.stringify({{client_id: '40106'}}),
                        'X-Fscp-Bi-Stat': JSON.stringify({{location: 'https://c.liepin.com/resume/edit'}}),
                        'X-Fscp-Trace-Id': '{uuid.uuid4()}',
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-XSRF-TOKEN': '{self.xsrf}'
                    }},
                    body: '{body_str}'
                }}).then(r => r.json()).then(d => resolve(JSON.stringify(d))).catch(e => resolve('ERR: ' + e.message));
            }});
        }})();
        """
        return self.page.run_js(js)

    def fetch_detail(self):
        """web-resume-detail 拿 resId + 现有记录"""
        js = f"""
        return (function() {{
            return new Promise(function(resolve) {{
                fetch('{API_BASE}/com.liepin.cresume.web-resume-detail', {{
                    method: 'POST', credentials: 'include',
                    headers: {{
                        'Accept': 'application/json, text/plain, */*',
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'X-Client-Type': 'web',
                        'X-Fscp-Fe-Version': '',
                        'X-Fscp-Version': '1.1',
                        'X-Fscp-Std-Info': JSON.stringify({{client_id: '40106'}}),
                        'X-Fscp-Bi-Stat': JSON.stringify({{location: 'https://c.liepin.com/resume/edit'}}),
                        'X-Fscp-Trace-Id': '{uuid.uuid4()}',
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-XSRF-TOKEN': '{self.xsrf}'
                    }},
                    body: 'encryResId='
                }}).then(r => r.json()).then(d => resolve(JSON.stringify(d))).catch(e => resolve('ERR: ' + e.message));
            }});
        }})();
        """
        raw = self.page.run_js(js)
        data = json.loads(raw)
        if data.get("flag") != 1:
            raise RuntimeError(f"detail 接口失败: {raw[:200]}")
        self.detail = data["data"]
        self.res_id = self.detail["resId"]
        return self.detail

    def delete_records(self, api_path, records):
        """删除列表型记录（例如工作经历、项目经历全量覆盖回写前的清理）"""
        deleted = 0
        for r in records:
            rid = r.get("id")
            if not rid:
                continue
            raw = self.post_json(api_path, {"data": {"encryResId": self.res_id, "id": rid}})
            if self._ok(raw):
                deleted += 1
            else:
                print(f"  [WARN] 删除记录失败: id={rid}, resp={raw[:80]}")
        return deleted

    # ---------- 模块转换 ----------
    def _bi(self, fields):
        v = fields.get("basic_info", {}).get("current_value", {}) or {}
        cities, _, _, _, _ = load_dicts()
        form = {
            "encryResId": self.res_id,
            "langKind": LANG_KIND,
        }
        if v.get("name"):
            form["realName"] = v["name"]
        if v.get("gender"):
            form["sex"] = v["gender"]
        if v.get("birth"):
            ymd = norm_ymd(v["birth"])
            if ymd:
                form["birthday"] = ymd
        if v.get("city"):
            code = fuzzy_find(v["city"], cities, [("广州", "050020")])
            if code:
                form["cityCode"] = code
        if v.get("political_status"):
            form["politicalStatusCode"] = POLITICAL_MAP.get(v["political_status"], "4")
        if v.get("job_status"):
            code = STUDENT_STATUS_MAP.get(v["job_status"]) or WORK_STATUS_MAP.get(v["job_status"])
            if code:
                form["workStatusCode"] = code
        if v.get("wechat"):
            form["wechat"] = v["wechat"]
        if v.get("current_salary_month"):
            parsed_sal = parse_salary(v["current_salary_month"])
            form["nowSalary"] = str(parsed_sal) if parsed_sal else str(v["current_salary_month"])
        if v.get("current_salary_months"):
            form["nowSalaryMonths"] = str(v["current_salary_months"])
        if v.get("salary_confidential") in ("true", True, "1", 1):
            form["nowSalarySecret"] = "1"
        else:
            form["nowSalarySecret"] = "0"
        if v.get("show_gender_suffix") in ("true", True, "1", 1):
            form["namePrivacy"] = "1"
        else:
            form["namePrivacy"] = "0"
        if v.get("work_start_date"):
            ym = norm_ym(v["work_start_date"])
            if ym and len(ym) >= 6 and ym[:4].isdigit():
                form["startJobYear"] = ym[:4]
                form["startJobMonth"] = ym[4:6]
        return form

    def _work(self, fields):
        import re as _re

        items = fields.get("work_experience", {}).get("current_value", []) or []
        cities, industries, jobs, _, _ = load_dicts()
        works = (self.detail or {}).get("workExperiences", []) or []
        city_hits = [(w.get("dqName", ""), w.get("dqCode")) for w in works]
        ind_hits = [(w.get("industryName", ""), w.get("industryCode")) for w in works]
        job_hits = [(w.get("jobtitleName", ""), w.get("jobtitleCode")) for w in works]
        payloads = []
        for i, it in enumerate(items):
            if not it.get("position") and not it.get("company"):
                continue
            if not it.get("company"):
                continue
            start = norm_ym(it.get("start_date"))
            raw_end = str(it.get("end_date") or "").strip()
            end = "999999" if raw_end in ("至今", "999999", "9999/99", "9999.99", "current", "") or not raw_end else (norm_ym(raw_end) or "999999")

            body = {
                "encryResId": self.res_id,
                "compName": str(it.get("company") or "").strip()[:100],
                "title": str(it.get("position") or "").strip()[:100],
            }
            # id 按有效条目的序号对位官网记录：跳过条目不能占用官网 id 槽位，
            # 否则尾部删除会按 len(payloads) 截断，把刚覆盖写入的官网记录误删
            p_idx = len(payloads)
            if p_idx < len(works) and works[p_idx].get("id"):
                body["id"] = works[p_idx]["id"]

            # 所属部门：显式传递，若本地为空则传 "" 覆盖清空官网历史残留值
            body["dept"] = str(it.get("department") or "").strip()[:100]
            
            resp = str(it.get("responsibilities") or it.get("duty") or it.get("description") or "").strip()
            if resp:
                if len(resp) < 10:
                    resp = f"主要负责：{resp}（日常业务推进与相关工作落实）"
                body["duty"] = resp[:1000]

            is_intern = (it.get("is_internship") in (True, "true", "1", 1, "实习经历")) or (str(it.get("workType")) in ("2", "实习经历"))
            body["workType"] = 2 if is_intern else 1
            
            is_shield = (it.get("hide_resume") in (True, "true", "1", 1)) or (it.get("shieldComp") in (True, "true", "1", 1))
            body["shieldComp"] = is_shield

            if start: body["startDate"] = start
            if end: body["endDate"] = end

            if it.get("work_city"):
                body["dq"] = fuzzy_find(it["work_city"], cities)
            if not body.get("dq") and city_hits:
                body["dq"] = city_hits[0][1]
            if not body.get("dq"):
                body["dq"] = "050020"

            ind_val = str(it.get("industry") or "").strip()
            if ind_val:
                body["industry"] = fuzzy_find(ind_val, industries, ind_hits)
            if not body.get("industry") and ind_hits:
                body["industry"] = ind_hits[0][1]
            if not body.get("industry"):
                body["industry"] = "H0002" if any(k in ind_val for k in ("电商", "零售", "商贸", "贸易", "美妆", "消费品")) else ("H0003" if any(k in ind_val for k in ("金融", "银行", "保险", "证券", "投资")) else ("H0006" if any(k in ind_val for k in ("医疗", "医药", "生物", "健康")) else ("H0008" if any(k in ind_val for k in ("教育", "培训", "科研", "学术")) else "H0001")))

            pos_val = str(it.get("job_category") or it.get("position") or "").strip()
            code = fuzzy_find(pos_val, jobs, job_hits)
            if not code or len(code) < 7:
                segs = _re.split(r"[（()）/\s]+", pos_val)
                for seg in segs:
                    code = fuzzy_find(seg, jobs)
                    if code and len(code) >= 7: break
            if not code or len(code) < 7:
                # 语义特征智能推导三级码与终极兜底
                raw_p = str(it.get("position") or "")
                if any(k in raw_p for k in ("运营", "店长", "淘系", "新媒体", "私域", "客服", "训练师", "标注")):
                    if any(k in raw_p for k in ("标注", "训练师", "数据运营")):
                        code = "N002007"
                    else:
                        code = "N000174"
                elif any(k in raw_p for k in ("产品", "PM", "需求")):
                    code = "N002271"
                elif any(k in raw_p for k in ("设计", "UI", "视觉", "美工")):
                    code = "N000101"
                elif any(k in raw_p for k in ("测试", "QA")):
                    code = "N000045"
                else:
                    code = "N000027"  # 全栈 / 软件开发终极兜底
            if code and len(code) >= 7:
                body["jobtitle"] = code

            # 薪资月数：显式传递，为空时传 "" 清空官网
            sal_months = "".join(ch for ch in str(it.get("salary_months") or "") if ch.isdigit())
            body["salmonths"] = sal_months[:5] if sal_months else ""
            
            # 目前薪资：显式传递，为空时传 "" 清空官网
            sal_val = it.get("salary_amount") or it.get("salary")
            if sal_val:
                parsed_sal = parse_salary(sal_val)
                body["salary"] = body["nowSalary"] = str(parsed_sal) if parsed_sal else ""
            else:
                body["salary"] = body["nowSalary"] = ""

            # 汇报对象职位：显式传递，若本地为空则传 "" 覆盖清空官网历史残留值
            body["report2"] = str(it.get("report_to") or "").strip()[:50]
            
            # 下属人数：若有数字则传数字，若为空则显式传 "" 清空官网
            sub_raw = str(it.get("team_size") or "").strip()
            sub_digits = "".join(ch for ch in sub_raw if ch.isdigit())
            body["subordinate"] = sub_digits[:10] if sub_digits else ""

            payloads.append(body)
        return payloads

    def _projects(self, fields):
        items = fields.get("projects", {}).get("current_value", []) or []
        projects = (self.detail or {}).get("projectExperiences", []) or []
        payloads = []
        for i, it in enumerate(items):
            if not it.get("project_name") and not it.get("description"):
                continue
            start = norm_ym(it.get("start_date"))
            raw_end = str(it.get("end_date") or "").strip()
            if not raw_end:
                # 核心业务规则：项目仅有单点时间（如 2026.01），结束时间等于开始时间
                end = start or "999999"
            elif raw_end in ("至今", "999999", "9999/99", "current"):
                end = "999999"
            else:
                end = norm_ym(raw_end) or start or "999999"

            body = {
                "encryResId": self.res_id,
                "name": it.get("project_name") or "",
                "compName": it.get("company") or "",
                "title": it.get("role") or "",
                "startDate": start or "999999",
                "endDate": end,
                "desc": (it.get("description") or "")[:1000],
                # 规范键为采集器/映射输出的 responsibilities/achievements，
                # duty/achievement 仅作历史快照兼容兜底；猎聘限制职责 10-1000 字，超限截断
                "duty": (it.get("responsibilities") or it.get("duty") or "")[:1000],
                "achievement": (it.get("achievements") or it.get("achievement") or "")[:1000],
            }
            # id 按有效条目的序号对位官网记录（与尾部删除按 len(payloads) 截断的口径一致）
            p_idx = len(payloads)
            if p_idx < len(projects) and projects[p_idx].get("id"):
                body["id"] = projects[p_idx]["id"]
            payloads.append(body)
        return payloads

    def _education(self, fields):
        items = fields.get("education", {}).get("current_value", []) or []
        edus = (self.detail or {}).get("eduExperiences", []) or []
        payloads = []
        for i, it in enumerate(items):
            if not it.get("school"):
                continue
            start = norm_ym(it.get("start_date"))
            end = norm_ym(it.get("end_date")) or "999999"
            body = {
                "encryResId": self.res_id,
                "school": it.get("school") or "",
                "special": it.get("major") or "",
                "startDate": start or "",
                "endDate": end,
            }
            p_idx = len(payloads)
            if p_idx < len(edus) and edus[p_idx].get("id"):
                body["id"] = edus[p_idx]["id"]
            deg = it.get("degree") or ""
            for name, code in DEGREE_MAP.items():
                if name in deg or deg in name:
                    body["degree"] = code
                    break
            tz = it.get("is_tongzhao")
            if tz in (True, "true", "是", "1"):
                body["tz"] = "1"
            elif tz in (False, "false", "否", "0"):
                body["tz"] = "0"

            # 在校经历：非必填项；官方字段为 experience (若填写需 10-300 字符)
            # 若为空，显式传递 "" 清空官网旧数据；若有填写，去除两端空格并合规处理
            raw_exp = it.get("campus_experience") or it.get("experience") or ""
            raw_exp = str(raw_exp).strip()
            if not raw_exp:
                body["experience"] = ""
            elif len(raw_exp) < 10:
                body["experience"] = f"{raw_exp}，在校期间认真完成相关专业学习与实践。"
            else:
                body["experience"] = raw_exp[:300]

            payloads.append(body)
        return payloads

    def _expectations(self, fields):
        items = fields.get("expectations", {}).get("current_value", []) or []
        if not items:
            return []
        cities, industries, jobs, _, _ = load_dicts()
        industries["不限"] = "000"
        industries["全部行业"] = "000"
        wants = (self.detail or {}).get("jobWants", []) or []
        payloads = []
        for i, it in enumerate(items):
            if not isinstance(it, dict) or not it.get("position"):
                continue
            body = {"encryResId": self.res_id}
            # id 按有效条目的序号对位官网记录（跳过条目不占槽位，与尾部删除口径一致）
            p_idx = len(payloads)
            if p_idx < len(wants) and wants[p_idx].get("id"):
                body["id"] = wants[p_idx]["id"]
            code = fuzzy_find(it.get("position", ""), jobs)
            if not code or len(code) < 7:
                raw_p = it.get("position", "")
                segs = _re.split(r"[（()）/\s]+", raw_p)
                for seg in segs:
                    code = fuzzy_find(seg, jobs)
                    if code and len(code) >= 7: break
            if not code or len(code) < 7:
                raw_p = str(it.get("position") or "")
                if any(k in raw_p for k in ("运营", "店长", "淘系", "新媒体", "私域", "客服", "训练师", "标注")):
                    code = "N002007" if any(k in raw_p for k in ("标注", "训练师", "数据运营")) else "N000174"
                elif any(k in raw_p for k in ("产品", "PM", "需求")):
                    code = "N002271"
                elif any(k in raw_p for k in ("设计", "UI", "视觉", "美工")):
                    code = "N000101"
                elif any(k in raw_p for k in ("测试", "QA")):
                    code = "N000045"
                else:
                    code = "N000027"
            if code and len(code) >= 7:
                body["jobtitleCode"] = code

            if it.get("city"):
                body["dqCode"] = fuzzy_find(it["city"], cities, [("广州", "050020")])
            if not body.get("dqCode"):
                body["dqCode"] = "050020"
            # 薪资：15k -> 15000, 25k -> 25000, 1.5万 -> 15000, 3.5万 -> 35000
            low = parse_salary(it.get("salary_min"))
            if low:
                body["wantSalaryLow"] = low
            high = parse_salary(it.get("salary_max"))
            if high:
                body["wantSalaryHigh"] = high
            if it.get("salary_months"):
                body["wantSalaryMonths"] = int(it["salary_months"])
            other_codes = []
            for oc in it.get("other_cities", []) or []:
                code = fuzzy_find(oc, cities)
                if code and code not in other_codes:
                    other_codes.append(code)
            if other_codes:
                body["otherExpectDqCodes"] = other_codes
            ind_codes = []
            raw_inds = it.get("industries", []) or []
            if isinstance(raw_inds, str):
                raw_inds = [s.strip() for s in _re.split(r"[,，/、\s]+", raw_inds) if s.strip()]
            for ic in raw_inds:
                if str(ic).strip() in ("不限", "全部行业"):
                    code = "000"
                else:
                    code = fuzzy_find(ic, industries)
                if code and code not in ind_codes:
                    ind_codes.append(code)
            if not ind_codes:
                ind_codes = ["000"]  # 猎聘要求至少1个行业代码，缺省兜底全部行业/不限
            if ind_codes:
                body["industryCodes"] = ",".join(ind_codes)
            payloads.append(body)
        return payloads

    def _certificates(self, fields):
        """返回 (payload, unmapped_names)。

        save-credential 是整表替换：只要本地有字典查不到的证书，就不提交
        （否则官网证书会被"可映射子集"覆盖，字典外证书被静默删掉）。
        """
        items = fields.get("certificates", {}).get("current_value", []) or []
        _, _, _, _, certs = load_dicts()
        codes = []
        unmapped = []
        for name in items:
            code = certs.get(str(name).strip())
            if code:
                codes.append(code)
            else:
                unmapped.append(str(name))
        if not items or unmapped:
            return None, unmapped
        return {"encryResId": self.res_id, "credentialCodes": codes}, []

    def _skill_tags(self, fields):
        items = fields.get("skill_tags", {}).get("current_value", []) or []
        labels = []
        for x in items:
            raw = str(x).strip()
            if not raw:
                continue
            # 猎聘官方严格限制：单标签最大 15 字符，超长直接报错；进行安全合规截断
            if len(raw) > 15:
                print(f"  [WARN] 技能标签 '{raw}' 超过15字符，自动截断为 '{raw[:15]}'")
                raw = raw[:15].strip()
            if raw and not any(lb["label"] == raw for lb in labels):
                labels.append({"label": raw, "type": 1})
        if not labels:
            return None
        if len(labels) > 10:
            print(f"  [WARN] 技能标签 {len(labels)} 个超官网上限(10)，截断为前 10 个")
            labels = labels[:10]
        return {"encryResId": self.res_id, "labels": labels}

    def _languages(self, fields):
        items = fields.get("languages", {}).get("current_value", []) or []
        if not items:
            return []
        _, _, _, langs, _ = load_dicts()
        existing = {l.get("name", ""): l for l in (self.detail or {}).get("languages", []) or []}
        payloads = []
        for it in items:
            lang_name = it.get("language") or ""
            lang_code = self._lang_code(langs, lang_name)
            if not lang_code:
                print(f"  [WARN] 未识别语言: {lang_name}")
                continue
            entry = langs.get(lang_code)
            body = {
                "encryResId": self.res_id,
                "code": lang_code,
            }
            # degreeCode：掌握程度
            prof = it.get("proficiency") or ""
            for dc in entry.get("degreeCode", []):
                if dc["name"] == prof:
                    body["degreeCode"] = dc["code"]
                    break
            # levelCode：等级证书（CET-6 -> CET6 归一化）；
            # LLM 可能输出多值（'CET-6; BEC...'），分段逐个匹配取首个命中
            cert = it.get("level") or it.get("certificate") or ""
            import re as _re_lang
            for seg in _re_lang.split(r"[;；,，、/]+", cert):
                norm_cert = seg.strip().replace("-", "").replace(" ", "").upper()
                if not norm_cert:
                    continue
                for lc in entry.get("levelCode", []):
                    if lc["name"].replace("-", "").replace(" ", "").upper() == norm_cert:
                        body["levelCode"] = lc["code"]
                        break
                if body.get("levelCode"):
                    break
            # 编辑（同名语言）带 originalCode
            for ename, ex in existing.items():
                if ename == lang_name:
                    body["originalCode"] = ex.get("code")
                    break
            payloads.append(body)
        return payloads

    @staticmethod
    def _lang_code(langs, name):
        for code, entry in langs.items():
            if entry.get("name") == name:
                return code
        return None

    def _match_existing_id(self, records, start, end, title):
        """按时间段匹配官网现有记录 id；再按标题相似度"""
        if not records or not start:
            return None

        def _month_close(a, b):
            """YYYYMM 相差不超过 1 个月"""
            try:
                a = int(a); b = int(b)
                diff = abs((a // 100) * 12 + a % 100 - (b // 100) * 12 - b % 100)
                return diff <= 1
            except (TypeError, ValueError):
                return False

        for r in records:
            r_start = str(r.get("start") or "").strip()
            r_end = str(r.get("end") or "").strip()
            if r_start and _month_close(r_start, start):
                if not r_end or not end:
                    return r.get("id")
                if r_end == end or (end == "999999" and r_end == "999999") or _month_close(r_end, end):
                    return r.get("id")
        # 标题/学校模糊匹配
        if title:
            for r in records:
                r_title = str(r.get("title") or r.get("school") or r.get("name") or "").strip()
                if r_title and (r_title in title or title in r_title):
                    return r.get("id")
        return None

    # ---------- 推送 ----------
    def push(self, fields):
        self.fetch_detail()
        print(f"  resId: {self.res_id}")

        for mod in self.modules:
            try:
                fn = getattr(self, f"_push_{mod}")
                fn(fields)
            except Exception as e:
                self.results[mod] = {"success": False, "message": str(e)}
                print(f"  [{mod}] FAIL: {e}")

    def _push_basic_info(self, fields):
        form = self._bi(fields)
        if len(form) <= 2:
            self._skip_empty("basic_info", "无可用字段")
            return
        raw = self.post_form("com.liepin.cresume.save-base-info", form)
        self._report("basic_info", raw, count=1)

    def _push_self_assessment(self, fields):
        v = fields.get("self_assessment", {}).get("current_value", "")
        if not v:
            self._skip_empty("self_assessment")
            return
        raw = self.post_json("com.liepin.cresume.save-self-assess", {"data": {"encryResId": self.res_id, "selfAssessment": v}})
        self._report("self_assessment", raw, count=1)

    def _push_expectations(self, fields):
        payloads = self._expectations(fields)
        if not payloads:
            self._skip_empty("expectations")
            return
        ok = 0
        existing = (self.detail or {}).get("jobWants", []) or []
        for i, p in enumerate(payloads):
            raw = self.post_json("com.liepin.cresume.save-job-want.v4", {"data": p})
            if self._ok(raw):
                ok += 1
            else:
                d = json.loads(raw) if raw.startswith("{") else {}
                err_msg = d.get("msg", raw[:60])
                print(f"  [FAIL] 求职期望[{i+1}] {p.get('jobtitleCode', '')}: {err_msg}")
        
        # 如果官网原先条目数多于本次回写条目数，删除多余旧条目
        # 熔断：存在保存失败时禁止删除——否则官网未更新的记录被连带删掉造成净丢失
        if ok == len(payloads) and len(existing) > len(payloads):
            redundant = existing[len(payloads):]
            deleted = self.delete_records("com.liepin.cresume.delete-job-want", redundant)
            print(f"  [INFO] 已删除官网 {deleted}/{len(redundant)} 条多余旧求职期望")

        self._report("expectations", None, count=len(payloads), ok=ok, per_item=True)

    def _push_work_experience(self, fields):
        payloads = self._work(fields)
        if not payloads:
            self._skip_empty("work_experience")
            return
        ok = 0
        existing = (self.detail or {}).get("workExperiences", []) or []
        for i, p in enumerate(payloads):
            raw = self.post_json("com.liepin.cresume.save-work-exp.v3", {"data": p})
            if self._ok(raw):
                ok += 1
            else:
                d = json.loads(raw) if raw.startswith("{") else {}
                print(f"  [FAIL] 工作经历[{i+1}] {p.get('compName','')[:20]}: {d.get('msg', raw[:60])}")
        
        # 如果官网原先条目数多于本次回写条目数，删除多余旧条目
        # 熔断：存在保存失败时禁止删除——否则官网未更新的记录被连带删掉造成净丢失
        if ok == len(payloads) and len(existing) > len(payloads):
            redundant = existing[len(payloads):]
            deleted = self.delete_records("com.liepin.cresume.delete-work-exp", redundant)
            print(f"  [INFO] 已删除官网 {deleted}/{len(redundant)} 条多余旧工作经历")

        self._report("work_experience", None, count=len(payloads), ok=ok, per_item=True)

    def _push_projects(self, fields):
        payloads = self._projects(fields)
        if not payloads:
            self._skip_empty("projects")
            return
        ok = 0
        for p in payloads:
            raw = self.post_json("com.liepin.cresume.save-project-exp", {"data": p})
            if self._ok(raw):
                ok += 1
            else:
                d = json.loads(raw) if raw.startswith("{") else {}
                print(f"  [FAIL] {p.get('name','')[:20]}: {d.get('msg', raw[:60])}")

        # 智能清理：仅当官网现有条数 > 本地更新条数时，定向删除尾部多余条目
        # 熔断：存在保存失败时禁止删除
        existing = (self.detail or {}).get("projectExperiences", []) or []
        if ok == len(payloads) and len(existing) > len(payloads):
            redundant = existing[len(payloads):]
            deleted = self.delete_records("com.liepin.cresume.delete-project-exp", redundant)
            print(f"  [INFO] 已删除官网 {deleted}/{len(redundant)} 条多余旧项目经历")

        self._report("projects", None, count=len(payloads), ok=ok, per_item=True)

    def _push_education(self, fields):
        payloads = self._education(fields)
        if not payloads:
            self._skip_empty("education")
            return
        ok = 0
        for p in payloads:
            raw = self.post_json("com.liepin.cresume.save-edu-exp.v2", {"data": p})
            if self._ok(raw):
                ok += 1
            else:
                d = json.loads(raw) if raw.startswith("{") else {}
                print(f"  [FAIL] {p.get('school','')[:20]}: {d.get('msg', raw[:60])}")

        # 智能清理：仅当官网现有条数 > 本地更新条数时，定向删除尾部多余条目
        # 熔断：存在保存失败时禁止删除
        existing = (self.detail or {}).get("eduExperiences", []) or []
        if ok == len(payloads) and len(existing) > len(payloads):
            redundant = existing[len(payloads):]
            deleted = self.delete_records("com.liepin.cresume.delete-edu-exp", redundant)
            print(f"  [INFO] 已删除官网 {deleted}/{len(redundant)} 条多余旧教育经历")

        self._report("education", None, count=len(payloads), ok=ok, per_item=True)

    def _push_certificates(self, fields):
        payload, unmapped = self._certificates(fields)
        if payload is None:
            if unmapped:
                self._skip_empty(
                    "certificates",
                    f"证书中 {('、'.join(unmapped[:5]))} 未命中猎聘字典，已跳过整表替换以保护官网证书（可手动在官网补充）",
                )
            else:
                self._skip_empty("certificates")
            return
        raw = self.post_form("com.liepin.cresume.save-credential", payload)
        self._report("certificates", raw, count=1)

    def _push_skill_tags(self, fields):
        payload = self._skill_tags(fields)
        if payload is None:
            self._skip_empty("skill_tags")
            return
        raw = self.post_json("com.liepin.cresume.save-personal-labels", {"data": payload})
        self._report("skill_tags", raw, count=1)

    def _push_languages(self, fields):
        payloads = self._languages(fields)
        if not payloads:
            self._skip_empty("languages")
            return
        ok = 0
        for p in payloads:
            raw = self.post_json("com.liepin.cresume.save-language", {"data": p})
            if self._ok(raw):
                ok += 1
        self._report("languages", None, count=len(payloads), ok=ok, per_item=True)

    def _push_additional_info(self, fields):
        v = fields.get("additional_info", {}).get("current_value", "")
        if not v:
            self._skip_empty("additional_info")
            return
        raw = self.post_form("com.liepin.cresume.save-addition-info", {"encryResId": self.res_id, "additionInfo": v})
        self._report("additional_info", raw, count=1)

    @staticmethod
    def _ok(raw):
        try:
            d = json.loads(raw)
            return d.get("flag") == 1 or d.get("code") == 0
        except Exception:
            return False

    def _report(self, mod, raw, count=0, ok=None, per_item=False):
        if ok is None:
            ok = 1 if self._ok(raw) else 0
        detail = ""
        if not per_item and raw:
            try:
                d = json.loads(raw) if isinstance(raw, str) and raw.startswith("{") else {}
                detail = d.get("msg") or d.get("message") or (str(raw)[:120] if not str(raw).startswith("{") else "")
            except Exception:
                detail = str(raw)[:120]
        self.results[mod] = {
            "success": ok == count and count > 0,
            "count": count,
            "ok": ok,
            "message": f"{ok}/{count} 成功" if per_item else ("成功" if ok else (f"失败（{detail}）" if detail else "失败")),
        }
        flag = "OK" if self.results[mod]["success"] else "FAIL"
        print(f"  [{mod}] {flag}: {self.results[mod]['message']}")


def load_fields():
    """优先读回写快照 liepin_writeback.json，回退 liepin_fields.json。
    返回 (fields, 来源路径, freshness 新鲜度信息)"""
    from browser_common import load_writeback_source
    fields, src, freshness = load_writeback_source("liepin", SNAPSHOT_PATH, FIELDS_PATH)
    if freshness["using_snapshot"]:
        print(f"  [INFO] 读取回写快照（保存于 {freshness['snapshot_created_at']}）")
    else:
        print("  [INFO] liepin_writeback.json 快照不存在，回退读取 liepin_fields.json")
    return fields, src, freshness


def main():
    parser = argparse.ArgumentParser(description="猎聘模块级回写")
    parser.add_argument("--modules", default=",".join(ALL_MODULES), help="要回写的模块，逗号分隔")
    parser.add_argument("--json", action="store_true", help="输出 JSON 结构化结果")
    parser.add_argument("--dry-run", action="store_true", help="预览模式：构建回写内容但不实际发送")
    args = parser.parse_args()

    modules = [m.strip() for m in args.modules.split(",") if m.strip()] or ALL_MODULES
    for m in modules:
        if m not in ALL_MODULES:
            print(f"  [ERROR] 未知模块: {m}（可选: {', '.join(ALL_MODULES)}）")
            sys.exit(1)

    print("=" * 50)
    print("  猎聘 - 模块级回写" + ("（DRY-RUN 预览）" if args.dry_run else ""))
    print(f"  模块: {', '.join(modules)}")
    print("=" * 50)

    fields, src, freshness = load_fields()
    print(f"  已加载数据 ({len(fields)} 模块)，数据源: {os.path.basename(src)}")
    # 回写全局空数据守卫：本地近乎为空时拒绝，防止把空内容推上官网
    from browser_common import ensure_writable_data
    ensure_writable_data("liepin", fields)
    if freshness.get("stale"):
        print(f"  [WARN] {freshness['warning']}")

    pusher = LiepinPusher(modules, dry_run=args.dry_run)
    try:
        pusher.connect()
        print(f"  已连接浏览器 (端口 {PORT})")
        pusher.push(fields)
    except Exception as e:
        print(f"  [ERROR] 回写失败: {e}")
        if args.json:
            print("RESULT_JSON:" + json.dumps({"success": False, "message": f"回写失败: {e}", "modules": {}}, ensure_ascii=False))
        sys.exit(2)

    print("\n  ===== 回写结果 =====")
    for mod in modules:
        r = pusher.results.get(mod, {"success": False, "message": "未执行"})
        print(f"  {mod}: {'✓' if r['success'] else '✗'} {r['message']}")

    skipped = [m for m in modules if pusher.results.get(m, {}).get("skipped")]
    executed = [m for m in modules if m not in skipped]
    ok_count = sum(1 for m in executed if pusher.results.get(m, {}).get("success"))
    all_ok = all(pusher.results.get(m, {}).get("success") for m in modules)
    skip_note = f"（{len(skipped)} 个模块本地为空已跳过）" if skipped else ""
    summary_msg = (
        f"回写完成: {ok_count}/{len(executed)} 模块成功{skip_note}"
        if all_ok
        else f"部分模块回写失败: {ok_count}/{len(executed)} 执行模块成功{skip_note}"
    )
    print(f"\n  总计: {ok_count}/{len(executed)} 执行模块成功{skip_note}")

    result_payload = {
        "success": all_ok,
        "message": summary_msg,
        "dry_run": bool(args.dry_run),
        "data_source": freshness,
        "results": [
            {
                "module": m,
                "success": pusher.results.get(m, {}).get("success", False),
                "skipped": pusher.results.get(m, {}).get("skipped", False),
                "message": pusher.results.get(m, {}).get("message", "未执行"),
            }
            for m in modules
        ],
        "modules": pusher.results,
    }
    print("RESULT_JSON:" + json.dumps(result_payload, ensure_ascii=False))
    # 退出码契约与 boss/51job/zhilian 统一：0=全部成功，2=部分失败（原为 1）
    sys.exit(0 if all_ok else 2)


if __name__ == "__main__":
    main()
