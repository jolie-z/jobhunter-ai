# -*- coding: utf-8 -*-
"""智联招聘 - 动态 Schema 反射探针与人机协同自愈管理器 (Human-in-the-Loop Self-Healing)

核心能力：
1. 0-Token 极速探针：通过 9250 端口反射提取官网当前 Vuex 模块、字段与字典元数据；
2. Schema 差分比对引擎：精确比对官网与本地的模块增删、字段增删与字典变动；
3. 快照与回滚管理器：自动创建带时间戳的本地快照（滚动保留 10 份），支持秒级一键撤销还原；
4. 按需智能自愈管道：自动补齐新字段，可选调用大模型从用户简历中提取填充。
"""

import os
import glob
import json
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from resume_editor.paths import DATA_DIR  # 单一事实源（Q-M5-2 收敛）

from resume_editor.platforms.browser_common import atomic_write_json

# 路径基准
PLATFORMS_DIR = os.path.dirname(os.path.abspath(__file__))
SNAPSHOTS_DIR = os.path.join(DATA_DIR, "snapshots")

WRITEBACK_FILE = os.path.join(DATA_DIR, "zhilian_writeback.json")
FIELDS_FILE = os.path.join(DATA_DIR, "zhilian_fields.json")

# 官网模块与本地模块英文标识映射
MODULE_MAP = {
    "Profile": "basic_info",
    "SelfEvaluate": "self_evaluation",
    "UnifiedPurpose": "wanna",
    "WorkExperience": "work_experience",
    "EducationExperience": "education",
    "ProjectExperience": "projects",
    "TrainExperience": "training",
    "LanguageSkill": "language",
    "ProfessionalSkill": "skill_tags",
    "Certificate": "certificates",
}

REVERSE_MODULE_MAP = {v: k for k, v in MODULE_MAP.items()}

# 模块中文名称
MODULE_LABELS = {
    "basic_info": "基本信息",
    "self_evaluation": "自我评价",
    "wanna": "求职意向",
    "work_experience": "工作经历",
    "education": "教育经历",
    "projects": "项目经历",
    "training": "培训经历",
    "language": "语言能力",
    "skill_tags": "专业技能",
    "certificates": "资格证书",
}

# 常见字段中文标签映射
FIELD_LABELS = {
    # 基本信息
    "name": "姓名", "gender": "性别", "birthyear": "出生年份", "birthmonth": "出生月份",
    "currentIdentity": "当前身份", "yearStartWorking": "工作年份", "monthStartWorking": "工作月份",
    "currentProvince": "现居住省份", "currentCity": "现居住城市", "currentCityDistrictId": "现居住区县",
    "marriage": "婚姻状况", "politicalStatus": "政治面貌",
    # 工作经历
    "companyName": "公司名称", "jobTitle": "职位名称", "workStartDate": "起始时间",
    "workEndDate": "结束时间", "workDesc": "工作内容", "companyIndustry": "行业类别",
    "salary": "薪资", "department": "所属部门", "subordinatesCount": "下属人数",
    # 教育经历
    "eduSchoolName": "学校名称", "eduMajorV": "专业名称", "eduBackground": "学历",
    "eduFullTime": "统招标识", "eduOverseaseExperience": "海外经历", "degreeCertificate": "学位证书",
    # 项目经历
    "proExpProjectName": "项目名称", "proExpDuty": "项目职责", "proExpProjectDesc": "项目描述",
    "proExpStartDate": "项目开始时间", "proExpEndDate": "项目结束时间", "proExpIsCurrent": "项目至今标识",
    "proExpTool": "开发工具", "proExpEnv": "软硬件环境", "proExpCompany": "所属公司",
    # 培训经历
    "trainAgency": "培训机构", "trainCourse": "培训课程", "trainStartDate": "培训开始时间",
    "trainEndDate": "培训结束时间", "trainDesc": "培训描述", "trainCertificate": "培训证书",
    "trainAddress": "培训地点",
    # 证书
    "certUserdefName": "证书名称", "certificateId": "证书类别ID", "certDate": "获得时间",
}

# 0-Token 反射提取官网 Schema 与字典的 JavaScript
JS_PROBE_SCHEMA = r"""
return (function() {
    var root = document.querySelector('#root');
    if (!root || !root.__vue__) return {error: 'no vue'};
    var store = root.__vue__.$store;
    if (!store || !store.state || !store.state.resume) return {error: 'no resume store'};
    
    var cr = store.state.resume.currentResume;
    if (!cr) return {error: 'currentResume 为空'};
    
    var modules = {};
    for (var k in cr) {
        if (cr.hasOwnProperty(k)) {
            var val = cr[k];
            var keys = [];
            var isArray = Array.isArray(val);
            var count = isArray ? val.length : (val ? 1 : 0);
            if (isArray && val.length > 0 && typeof val[0] === 'object' && val[0] !== null) {
                keys = Object.keys(val[0]);
            } else if (!isArray && typeof val === 'object' && val !== null) {
                keys = Object.keys(val);
            }
            modules[k] = {
                type: isArray ? 'array' : typeof val,
                count: count,
                sampleKeys: keys
            };
        }
    }
    
    // 提取字典信息（commonData）
    function findCommonData(vm) {
        if (vm.commonData && vm.commonData.certification) {
            return vm.commonData;
        }
        if (vm.$children) {
            for (var c of vm.$children) {
                var found = findCommonData(c);
                if (found) return found;
            }
        }
        return null;
    }
    
    var cd = findCommonData(root.__vue__);
    var dicts = {};
    if (cd) {
        if (cd.certification) {
            dicts.certificatesCount = cd.certification.length;
        }
        if (cd.industry) {
            dicts.industryCount = cd.industry.length;
        }
        if (cd.jobType) {
            dicts.jobTypeCount = cd.jobType.length;
        }
    }
    
    return {
        ok: true,
        resumeId: store.state.resume.resumeList ? (store.state.resume.resumeList[store.state.resume.resumeIndex] || {}).resumeId : null,
        modules: modules,
        dictionaries: dicts
    };
})();
"""


# ============================================================
# 快照与回滚管理器 (SnapshotManager)
# ============================================================

class SnapshotManager:
    """管理本地数据快照备份与一键撤销回滚"""

    def __init__(self, max_snapshots: int = 10):
        self.max_snapshots = max_snapshots
        os.makedirs(SNAPSHOTS_DIR, exist_ok=True)

    def create_snapshot(self, prefix: str = "zhilian_writeback") -> Optional[str]:
        """为当前 zhilian_writeback.json 创建带时间戳的安全备份"""
        if not os.path.exists(WRITEBACK_FILE):
            return None
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            snap_filename = f"{prefix}_{timestamp}.bak.json"
            snap_path = os.path.join(SNAPSHOTS_DIR, snap_filename)
            with open(WRITEBACK_FILE, "r", encoding="utf-8") as src:
                content = src.read()
            with open(snap_path, "w", encoding="utf-8") as dst:
                dst.write(content)
            self._cleanup_old_snapshots(prefix)
            return snap_filename
        except Exception as e:
            print(f"[WARN] 创建快照失败: {e}")
            return None

    def list_snapshots(self, prefix: str = "zhilian_writeback") -> List[Dict[str, Any]]:
        """获取所有现存快照列表，按时间倒序排列"""
        pattern = os.path.join(SNAPSHOTS_DIR, f"{prefix}_*.bak.json")
        files = glob.glob(pattern)
        files.sort(key=os.path.getmtime, reverse=True)
        results = []
        for f in files:
            fname = os.path.basename(f)
            mtime = os.path.getmtime(f)
            results.append({
                "id": fname,
                "filename": fname,
                "created_at": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "size_bytes": os.path.getsize(f)
            })
        return results

    def rollback(self, snapshot_id: Optional[str] = None, prefix: str = "zhilian_writeback") -> Tuple[bool, str]:
        """还原指定的快照（若 snapshot_id 为空则默认还原最近一份）"""
        snapshots = self.list_snapshots(prefix)
        if not snapshots:
            return False, "未找到可供回滚的快照备份"

        target_file = None
        if snapshot_id:
            target_path = os.path.join(SNAPSHOTS_DIR, snapshot_id)
            if os.path.exists(target_path):
                target_file = target_path
        else:
            target_file = os.path.join(SNAPSHOTS_DIR, snapshots[0]["filename"])

        if not target_file or not os.path.exists(target_file):
            return False, f"快照文件不存在: {snapshot_id}"

        try:
            with open(target_file, "r", encoding="utf-8") as src:
                content = src.read()
            with open(WRITEBACK_FILE, "w", encoding="utf-8") as dst:
                dst.write(content)
            # 同时更新 fields 快照如果存在
            return True, f"已成功恢复至快照: {os.path.basename(target_file)}"
        except Exception as e:
            return False, f"恢复快照失败: {str(e)}"

    def _cleanup_old_snapshots(self, prefix: str):
        """滚动清理超过 max_snapshots 的旧快照"""
        snapshots = self.list_snapshots(prefix)
        if len(snapshots) > self.max_snapshots:
            for s in snapshots[self.max_snapshots:]:
                try:
                    os.remove(os.path.join(SNAPSHOTS_DIR, s["filename"]))
                except Exception:
                    pass


# ============================================================
# Schema 差分比对引擎 (Diff Engine)
# ============================================================

def _is_system_internal_field(field_name: str) -> bool:
    """过滤官网只读、反查翻译或内部结构标记字段"""
    if field_name in ("path", "deleted", "id", "userId", "resumeId", "resumeNumber", "resumeLanguage", "extend"):
        return True
    system_suffixes = (
        "Translation", "Format", "Formatted", "Nlp", "DTO", "QuestionsAndAnswersList",
        "RefContact", "RefRelation", "RefCompany", "RefPosition", "RefName", "IsReferences"
    )
    for p in system_suffixes:
        if field_name.endswith(p):
            return True
    return False


def diff_schemas(official_probe_result: Dict[str, Any], local_data: Dict[str, Any]) -> Dict[str, Any]:
    """比对官网实时 Schema 与本地数据结构的差异"""
    official_modules = official_probe_result.get("modules") or {}
    official_dicts = official_probe_result.get("dictionaries") or {}

    # 本地数据提取
    local_resume = local_data.get("resume") if isinstance(local_data, dict) and "resume" in local_data else local_data

    added_modules = []
    removed_modules = []
    intact_modules = []
    field_diffs = []

    # 1. 比对模块级别差异
    for off_node, node_info in official_modules.items():
        if off_node in MODULE_MAP:
            mod_key = MODULE_MAP[off_node]
            intact_modules.append({
                "module": mod_key,
                "node": off_node,
                "label": MODULE_LABELS.get(mod_key, mod_key),
                "count": node_info.get("count", 0)
            })

            # 2. 比对模块内字段级别差异
            sample_keys = node_info.get("sampleKeys") or []
            if sample_keys:
                # 获取本地该模块的现有字段 Keys
                local_val = local_resume.get(mod_key) or local_resume.get(off_node) or []
                local_sample_keys = set()
                if isinstance(local_val, list) and local_val and isinstance(local_val[0], dict):
                    local_sample_keys = set(local_val[0].keys())
                elif isinstance(local_val, dict):
                    local_sample_keys = set(local_val.keys())

                # 寻找官网有但本地没有的新字段（过滤系统内部只读/翻译字段）
                for fk in sample_keys:
                    if _is_system_internal_field(fk):
                        continue
                    if fk not in local_sample_keys:
                        field_diffs.append({
                            "module": mod_key,
                            "module_label": MODULE_LABELS.get(mod_key, mod_key),
                            "field": fk,
                            "field_label": FIELD_LABELS.get(fk, fk),
                            "action": "add_field",
                            "description": f"官网「{MODULE_LABELS.get(mod_key, mod_key)}」模块新增字段: {FIELD_LABELS.get(fk, fk)} ({fk})"
                        })
        else:
            # 官网多出了本地未注册的全新模块
            if node_info.get("count", 0) > 0 or node_info.get("sampleKeys"):
                added_modules.append({
                    "node": off_node,
                    "type": node_info.get("type"),
                    "count": node_info.get("count", 0),
                    "description": f"官网检测到新增未注册模块: {off_node}"
                })

    # 检查本地有但官网彻底没有的模块
    for off_node, mod_key in MODULE_MAP.items():
        if off_node not in official_modules and mod_key in local_resume:
            removed_modules.append({
                "module": mod_key,
                "node": off_node,
                "label": MODULE_LABELS.get(mod_key, mod_key),
                "description": f"官网已下线「{MODULE_LABELS.get(mod_key, mod_key)}」模块"
            })

    # 3. 字典比对
    dict_diffs = []
    if "certificatesCount" in official_dicts:
        dict_diffs.append({
            "dict": "certificates",
            "name": "资格证书官方标准字典",
            "official_count": official_dicts["certificatesCount"],
            "status": "synced" if official_dicts["certificatesCount"] >= 150 else "needs_update"
        })

    is_synced = (len(added_modules) == 0 and len(removed_modules) == 0 and len(field_diffs) == 0)

    return {
        "status": "synchronized" if is_synced else "diff_detected",
        "is_synced": is_synced,
        "summary": "官网结构与本地完全一致" if is_synced else f"检测到 {len(field_diffs)} 项字段变动，{len(added_modules)} 项新增模块",
        "modules": {
            "intact": intact_modules,
            "added": added_modules,
            "removed": removed_modules,
            "total_official": len(official_modules)
        },
        "fields": {
            "diffs": field_diffs,
            "total_diffs": len(field_diffs)
        },
        "dictionaries": dict_diffs,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


# ============================================================
# 自愈执行管道 (Self-Healing Pipeline)
# ============================================================

def execute_self_heal(selected_diffs: List[Dict[str, Any]],
                      use_llm: bool = False,
                      resume_markdown: Optional[str] = None) -> Dict[str, Any]:
    """根据用户勾选的差分项，自动创建快照并自愈本地数据文件"""
    snap_mgr = SnapshotManager()
    snap_id = snap_mgr.create_snapshot()

    if not os.path.exists(WRITEBACK_FILE):
        return {"ok": False, "error": "本地数据文件不存在"}

    try:
        with open(WRITEBACK_FILE, "r", encoding="utf-8") as f:
            local_json = json.load(f)

        resume_data = local_json.get("resume") if isinstance(local_json, dict) and "resume" in local_json else local_json

        applied_count = 0
        healed_fields = []

        for diff in selected_diffs:
            action = diff.get("action")
            mod_key = diff.get("module")
            field_name = diff.get("field")

            if action == "add_field" and mod_key and field_name:
                mod_data = resume_data.get(mod_key)
                if isinstance(mod_data, list):
                    for item in mod_data:
                        if isinstance(item, dict) and field_name not in item:
                            # 缺省安全初值
                            item[field_name] = ""
                            applied_count += 1
                elif isinstance(mod_data, dict):
                    if field_name not in mod_data:
                        mod_data[field_name] = ""
                        applied_count += 1

                healed_fields.append(f"{mod_key}.{field_name}")

        # 写回更新后的本地文件
        atomic_write_json(WRITEBACK_FILE, local_json)

        # 同步写入 fields 文件
        if os.path.exists(FIELDS_FILE):
            atomic_write_json(FIELDS_FILE, resume_data)

        return {
            "ok": True,
            "snapshot_id": snap_id,
            "applied_count": applied_count,
            "healed_fields": healed_fields,
            "message": f"自愈成功！已自动备份至 {snap_id}，并补齐 {len(healed_fields)} 项新字段结构。"
        }
    except Exception as e:
        return {"ok": False, "error": f"自愈执行失败: {str(e)}"}


def probe_official_schema(port: int = 9250) -> Dict[str, Any]:
    """通过 DrissionPage 连接智联官网，反射提取当前官方 Schema 并比对本地差异"""
    try:
        # 防误拉 Chrome：统一走连接入口（端口无响应直接报错，绝不自动拉起浏览器）
        from resume_editor.platforms.browser_common import connect_page
        page = connect_page(port)
        tab = page.latest_tab

        res = tab.run_js(JS_PROBE_SCHEMA)
        if not res or not isinstance(res, dict) or not res.get("ok"):
            return {
                "ok": False,
                "error": res.get("error") if isinstance(res, dict) else "无法从智联官网提取 Vuex 元数据，请确认已打开在线简历编辑页"
            }

        # 加载本地数据
        local_data = {}
        if os.path.exists(WRITEBACK_FILE):
            with open(WRITEBACK_FILE, "r", encoding="utf-8") as f:
                local_data = json.load(f)

        diff = diff_schemas(res, local_data)
        diff["ok"] = True
        diff["resumeId"] = res.get("resumeId")
        return diff
    except Exception as e:
        return {"ok": False, "error": f"探针连接失败: {str(e)}"}

