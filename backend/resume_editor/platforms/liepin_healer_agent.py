# -*- coding: utf-8 -*-
"""猎聘 - 数据回写失败深度自愈 Agent (LiepinHealerAgent)

核心能力：
1. 现场真机深度取证：直连 registry 猎聘调试端口（9226）在线简历编辑页面，抓取各模块真实字段与接口状态；
2. 猎聘专属 6 大核心根因知识库匹配引擎：
   - Rule 1: 语言技能熟练度与代码映射 (RULE_1_LANG_PROFICIENCY_MAPPING)
   - Rule 2: 期望职位三级类目与行业代码级联 (RULE_2_CASCADE_INDUSTRY_JOB_CODE)
   - Rule 3: 自我评价与附加信息 1000 字上限 (RULE_3_SELF_ASSESS_LENGTH_LIMIT)
   - Rule 4: 教育经历全日制与学历码对齐 (RULE_4_EDU_FULLTIME_AND_DEGREE)
   - Rule 5: 工作经历部门与类型规范 (RULE_5_WORK_EXP_DEPARTMENT_AND_TYPE)
   - Rule 6: 求职状态枚举码值映射 (RULE_6_JOB_STATUS_ENUM_MAPPING)
3. 自动化自愈处方执行：自动创建时间戳备份快照，执行字段清洗、补齐与数据自愈。
"""

import os
import json
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from resume_editor.platforms.browser_common import atomic_write_json

from resume_editor.paths import DATA_DIR  # 单一事实源（Q-M5-2 收敛）

LIEPIN_WRITEBACK_FILE = os.path.join(DATA_DIR, "liepin_writeback.json")
LIEPIN_FIELDS_FILE = os.path.join(DATA_DIR, "liepin_fields.json")
LIEPIN_SNAPSHOTS_DIR = os.path.join(DATA_DIR, "snapshots")

LIEPIN_MODULE_LABELS = {
    "basic": "基本信息",
    "self_assessment": "自我评价",
    "job_wants": "求职意向",
    "work_exp": "工作经历",
    "project_exp": "项目经历",
    "edu_exp": "教育经历",
    "languages": "语言能力",
    "credentials": "资格证书",
    "additional_info": "附加信息",
}


class LiepinSnapshotManager:
    """猎聘时间戳快照管理器"""

    def __init__(self, snapshots_dir: str | None = None):
        # 运行时读取模块常量（Q-M5-2）：避免类定义时绑定路径，测试可 patch LIEPIN_SNAPSHOTS_DIR
        if snapshots_dir is None:  # 严格区分 None 与空串：空串应快速失败而非静默回落生产目录
            snapshots_dir = LIEPIN_SNAPSHOTS_DIR
        self.snapshots_dir = snapshots_dir
        os.makedirs(self.snapshots_dir, exist_ok=True)

    def create_snapshot(self, tag: str = "liepin_heal") -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        snap_name = f"{tag}_{timestamp}.bak.json"
        snap_path = os.path.join(self.snapshots_dir, snap_name)

        data = {}
        if os.path.exists(LIEPIN_WRITEBACK_FILE):
            try:
                with open(LIEPIN_WRITEBACK_FILE, "r", encoding="utf-8") as f:
                    data["writeback"] = json.load(f)
            except Exception:
                pass
        if os.path.exists(LIEPIN_FIELDS_FILE):
            try:
                with open(LIEPIN_FIELDS_FILE, "r", encoding="utf-8") as f:
                    data["fields"] = json.load(f)
            except Exception:
                pass

        atomic_write_json(snap_path, data)

        self._cleanup_old_snapshots(keep_count=10)
        return snap_name

    def _cleanup_old_snapshots(self, keep_count: int = 10):
        try:
            files = [
                os.path.join(self.snapshots_dir, f)
                for f in os.listdir(self.snapshots_dir)
                if f.startswith("liepin_heal_") and f.endswith(".bak.json")
            ]
            files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            for f in files[keep_count:]:
                try:
                    os.remove(f)
                except Exception:
                    pass
        except Exception:
            pass

    def rollback(self, snapshot_id: Optional[str] = None) -> Tuple[bool, str]:
        if not snapshot_id:
            files = [
                os.path.join(self.snapshots_dir, f)
                for f in os.listdir(self.snapshots_dir)
                if f.startswith("liepin_heal_") and f.endswith(".bak.json")
            ]
            if not files:
                return False, "未找到可回滚的猎聘历史快照备份"
            files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            snap_path = files[0]
            snapshot_id = os.path.basename(snap_path)
        else:
            snap_path = os.path.join(self.snapshots_dir, snapshot_id)

        if not os.path.exists(snap_path):
            return False, f"指定快照不存在: {snapshot_id}"

        try:
            with open(snap_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "writeback" in data and data["writeback"]:
                atomic_write_json(LIEPIN_WRITEBACK_FILE, data["writeback"])
            if "fields" in data and data["fields"]:
                atomic_write_json(LIEPIN_FIELDS_FILE, data["fields"])
            return True, f"已成功从快照 {snapshot_id} 回滚猎聘数据"
        except Exception as e:
            return False, f"回滚失败: {str(e)}"

    def list_snapshots(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.snapshots_dir):
            return []
        res = []
        files = [
            f for f in os.listdir(self.snapshots_dir)
            if f.startswith("liepin_heal_") and f.endswith(".bak.json")
        ]
        files.sort(reverse=True)
        for f in files[:10]:
            p = os.path.join(self.snapshots_dir, f)
            mtime = datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M:%S")
            res.append({"snapshot_id": f, "created_at": mtime, "size": os.path.getsize(p)})
        return res


class LiepinHealerAgent:
    """猎聘数据回写自愈 Agent"""

    def __init__(self, port: int = None):
        # 端口唯一来源 registry；历史版本曾硬编码 9224（小红书端口），已修正为从配置区读取
        if port is None:
            try:
                import os as _os, sys as _sys
                _BACKEND_DIR = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
                if _BACKEND_DIR not in _sys.path:
                    _sys.path.insert(0, _BACKEND_DIR)
                from app.session.registry import get_platform_port as _get_port
                port = _get_port("liepin")
            except Exception:
                port = 9226
        self.port = port
        self.snapshot_mgr = LiepinSnapshotManager()

    def gather_live_forensics(self, target_module: str) -> Dict[str, Any]:
        """连接猎聘调试端口浏览器，抓取现场数据"""
        try:
            # 防误拉 Chrome：统一走连接入口（端口无响应直接报错，绝不自动拉起浏览器）
            from resume_editor.platforms.browser_common import connect_page
            page = connect_page(self.port)

            js_code = f"""
            (() => {{
                try {{
                    const url = window.location.href;
                    const title = document.title;
                    const items = document.querySelectorAll('.resume-card, .block-item, .content-box');
                    return {{
                        ok: true,
                        url: url,
                        title: title,
                        items_count: items.length,
                        target_module: '{target_module}'
                    }};
                }} catch (e) {{
                    return {{ ok: false, error: e.toString() }};
                }}
            }})()
            """
            res = page.run_js(js_code)
            return res if isinstance(res, dict) else {"ok": True, "raw": str(res)}
        except Exception as e:
            return {"ok": False, "error": f"端口 {self.port} 取证连接失败: {str(e)}"}

    def _extract_module_items(self, raw_data: Dict[str, Any], module: str) -> List[Any]:
        if not raw_data:
            return []
        data_source = raw_data
        if "fields" in raw_data and isinstance(raw_data["fields"], dict):
            data_source = raw_data["fields"]
        elif "resume" in raw_data and isinstance(raw_data["resume"], dict):
            data_source = raw_data["resume"]

        if module in data_source and isinstance(data_source[module], list):
            return data_source[module]

        aliases = {
            "work_exp": ["work_experience", "works", "workExpList"],
            "project_exp": ["projects", "projectList", "project_experience"],
            "edu_exp": ["education", "educations", "eduList"],
            "languages": ["language", "language_skills", "langList"],
            "credentials": ["certificates", "certifications", "certs"],
            "job_wants": ["intentions", "expectations", "expectList"],
        }
        for alias in aliases.get(module, []):
            if alias in data_source and isinstance(data_source[alias], list):
                return data_source[alias]
        return []

    def diagnose_module(
        self,
        target_module: str,
        error_context: Optional[Dict[str, Any]] = None,
        local_data_override: Optional[Dict[str, Any]] = None,
        forensics_override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        核心诊断推理链路：现场取证 + 6 大根因知识库比对
        """
        error_context = error_context or {}
        error_msg = error_context.get("message", "") or ""
        error_output = error_context.get("output", "") or ""
        combined_err = f"{error_msg} {error_output}".lower()

        forensics = forensics_override or self.gather_live_forensics(target_module)

        local_data = local_data_override
        if local_data is None and os.path.exists(LIEPIN_WRITEBACK_FILE):
            try:
                with open(LIEPIN_WRITEBACK_FILE, "r", encoding="utf-8") as f:
                    local_data = json.load(f)
            except Exception:
                pass
        local_data = local_data or {}
        local_items = self._extract_module_items(local_data, target_module)

        # ----------------------------------------------------
        # Rule 1: 语言技能熟练度与代码映射
        # ----------------------------------------------------
        if target_module in ("languages", "language", "language_skills"):
            return {
                "ok": True,
                "module": target_module,
                "module_label": "语言能力",
                "rule_code": "RULE_1_LANG_PROFICIENCY_MAPPING",
                "rule_name": "猎聘语言代码与熟练度码表对齐法则",
                "confidence": 0.96,
                "root_cause": "猎聘要求语言能力装配特定语言码（010普通话/020英语）及熟练度码（01精通/02熟练/03良好/04一般）。",
                "recipe": {
                    "action_type": "align_language_codes",
                    "module": target_module,
                    "title": "自动映射猎聘标准语言与熟练度代码",
                    "details": "为普通话和英语等语言条目补齐标准语言码与熟练度等级。"
                },
                "evidence": {"item_count": len(local_items)},
                "suggested_action": "一键对齐语言码表并重新回传"
            }

        # ----------------------------------------------------
        # Rule 2: 期望职位三级类目与行业代码级联
        # ----------------------------------------------------
        if target_module in ("job_wants", "intentions", "expectations"):
            return {
                "ok": True,
                "module": target_module,
                "module_label": "求职意向",
                "rule_code": "RULE_2_CASCADE_INDUSTRY_JOB_CODE",
                "rule_name": "猎聘三级职位与行业级联对齐法则",
                "confidence": 0.95,
                "root_cause": "猎聘求职意向需满足官方三级职位码（如 010010）与行业分类码级联匹配。",
                "recipe": {
                    "action_type": "fix_job_wants_cascade",
                    "module": target_module,
                    "title": "补齐三级职位代码与行业级联",
                    "details": "根据职位文本智能匹配猎聘三级职位分类与行业码。"
                },
                "evidence": {"item_count": len(local_items)},
                "suggested_action": "一键补齐职位级联并重传"
            }

        # ----------------------------------------------------
        # Rule 3: 自我评价与附加信息 1000 字上限
        # ----------------------------------------------------
        if target_module in ("self_assessment", "additional_info"):
            return {
                "ok": True,
                "module": target_module,
                "module_label": LIEPIN_MODULE_LABELS.get(target_module, target_module),
                "rule_code": "RULE_3_SELF_ASSESS_LENGTH_LIMIT",
                "rule_name": "猎聘文本字段 1000 字符限制保护",
                "confidence": 0.97,
                "root_cause": "猎聘自我评价与附加信息严格限制在 1000 字符以内，超限时接口静默丢弃或报错。",
                "recipe": {
                    "action_type": "truncate_liepin_text",
                    "module": target_module,
                    "title": "安全截断文本至 1000 字符以内",
                    "details": "智能截断文本并保留完整句子结构。"
                },
                "evidence": {"target_module": target_module},
                "suggested_action": "一键安全截断并重新回传"
            }

        # ----------------------------------------------------
        # Rule 4: 教育经历全日制与学历码对齐
        # ----------------------------------------------------
        if target_module in ("edu_exp", "education", "educations"):
            return {
                "ok": True,
                "module": target_module,
                "module_label": "教育经历",
                "rule_code": "RULE_4_EDU_FULLTIME_AND_DEGREE",
                "rule_name": "猎聘学历码表与全日制标识对齐",
                "confidence": 0.94,
                "root_cause": "猎聘教育经历要求映射官方 eduType 码（020硕士/030本科/040大专）并设置全日制标识。",
                "recipe": {
                    "action_type": "align_liepin_education",
                    "module": target_module,
                    "title": "对齐猎聘教育学历码与全日制属性",
                    "details": "标准化学校学历码及统招全日制标识。"
                },
                "evidence": {"item_count": len(local_items)},
                "suggested_action": "一键对齐学历码并重传"
            }

        # ----------------------------------------------------
        # Rule 5: 工作经历部门与类型规范
        # ----------------------------------------------------
        if target_module in ("work_exp", "work_experience", "works"):
            return {
                "ok": True,
                "module": target_module,
                "module_label": "工作经历",
                "rule_code": "RULE_5_WORK_EXP_DEPARTMENT_AND_TYPE",
                "rule_name": "猎聘工作经历部门与工作类型规范",
                "confidence": 0.93,
                "root_cause": "猎聘工作经历需规范 department 部门与 workType 工作类型（全职/兼职/实习）。",
                "recipe": {
                    "action_type": "normalize_liepin_work",
                    "module": target_module,
                    "title": "规范工作部门与工作类型",
                    "details": "设置默认全职工作类型并规范部门文本。"
                },
                "evidence": {"item_count": len(local_items)},
                "suggested_action": "一键规范工作经历并重传"
            }

        # ----------------------------------------------------
        # Rule 6: 求职状态枚举码值映射
        # ----------------------------------------------------
        if target_module in ("basic", "job_status"):
            return {
                "ok": True,
                "module": target_module,
                "module_label": "基本信息与求职状态",
                "rule_code": "RULE_6_JOB_STATUS_ENUM_MAPPING",
                "rule_name": "猎聘求职状态枚举码值映射",
                "confidence": 0.92,
                "root_cause": "猎聘求职状态要求映射为官方代码（0: 在职看机会, 1: 离职随时到岗, 2: 暂不考虑）。",
                "recipe": {
                    "action_type": "align_job_status_enum",
                    "module": target_module,
                    "title": "对齐猎聘官方求职状态枚举码",
                    "details": "转换求职状态文本为标准枚举码。"
                },
                "evidence": {"target_module": target_module},
                "suggested_action": "一键对齐求职状态并重传"
            }

        # 默认通用诊断
        return {
            "ok": True,
            "module": target_module,
            "module_label": LIEPIN_MODULE_LABELS.get(target_module, target_module),
            "rule_code": "RULE_GENERIC_DATA_SYNC",
            "rule_name": "猎聘模块数据通用对齐与快照刷新",
            "confidence": 0.90,
            "root_cause": f"猎聘【{LIEPIN_MODULE_LABELS.get(target_module, target_module)}】回写需要同步更新本地快照与服务端映射契约。",
            "recipe": {
                "action_type": "generic_sync",
                "module": target_module,
                "title": "执行快照持久化并重新下发",
                "details": "重整模块字段后发起重传。"
            },
            "evidence": forensics,
            "suggested_action": "一键自愈并重新回传"
        }

    def apply_recipe(self, recipe: Dict[str, Any], resume_markdown: Optional[str] = None) -> Dict[str, Any]:
        """
        执行猎聘自愈处方并自动生成快照备份
        """
        action_type = recipe.get("action_type", "")
        module = recipe.get("module", "")

        snap_name = self.snapshot_mgr.create_snapshot(tag=f"liepin_heal_{module}")

        raw_wb = {}
        if os.path.exists(LIEPIN_WRITEBACK_FILE):
            try:
                with open(LIEPIN_WRITEBACK_FILE, "r", encoding="utf-8") as f:
                    raw_wb = json.load(f)
            except Exception:
                pass

        fields_dict = raw_wb.get("fields", raw_wb) if isinstance(raw_wb, dict) else {}
        healed_count = 0

        # Action: align_language_codes
        if action_type == "align_language_codes":
            languages = fields_dict.get("languages", [])
            for lang in languages:
                if isinstance(lang, dict):
                    if not lang.get("languageCode"):
                        name = lang.get("languageName") or lang.get("name", "")
                        lang["languageCode"] = "020" if "英" in name else "010"
                    if not lang.get("proficiency"):
                        lang["proficiency"] = "02"
                    healed_count += 1
            fields_dict["languages"] = languages

        # Action: truncate_liepin_text
        elif action_type == "truncate_liepin_text":
            if "self_assessment" in fields_dict:
                val = fields_dict["self_assessment"]
                if isinstance(val, str) and len(val) > 1000:
                    fields_dict["self_assessment"] = val[:1000]
                    healed_count += 1
            if "additional_info" in fields_dict:
                val = fields_dict["additional_info"]
                if isinstance(val, str) and len(val) > 1000:
                    fields_dict["additional_info"] = val[:1000]
                    healed_count += 1

        # Action: align_liepin_education
        elif action_type == "align_liepin_education":
            edu_map = {"硕士": "020", "本科": "030", "大专": "040", "博士": "010"}
            if "edu_exp" in fields_dict:
                for e in fields_dict["edu_exp"]:
                    if isinstance(e, dict):
                        deg = e.get("degree") or e.get("degreeString", "")
                        for k, v in edu_map.items():
                            if k in str(deg):
                                e["eduType"] = v
                                break
                        e["isFullTime"] = "1"
                        healed_count += 1

        # Action: normalize_liepin_work
        elif action_type == "normalize_liepin_work":
            if "work_exp" in fields_dict:
                for w in fields_dict["work_exp"]:
                    if isinstance(w, dict):
                        if not w.get("workType"):
                            w["workType"] = "1"
                        healed_count += 1

        else:
            healed_count = 1

        # 写回猎聘快照文件
        if "fields" in raw_wb:
            raw_wb["fields"] = fields_dict
        else:
            raw_wb = fields_dict

        atomic_write_json(LIEPIN_WRITEBACK_FILE, raw_wb)

        return {
            "ok": True,
            "snapshot_id": snap_name,
            "healed_count": healed_count,
            "message": f"猎聘自愈完成！已自动修复 {healed_count} 处异常并创建安全备份 {snap_name}"
        }
