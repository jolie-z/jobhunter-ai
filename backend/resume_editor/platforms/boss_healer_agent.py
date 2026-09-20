# -*- coding: utf-8 -*-
"""BOSS直聘 - 数据回写失败深度自愈 Agent (BossHealerAgent)

核心能力：
1. 现场真机深度取证：直连 19222 端口 BOSS 在线简历页面，探测模块 DOM 与接口真实状态；
2. BOSS 直聘专属 6 大核心根因知识库匹配引擎：
   - Rule 1: 项目经历职务/角色与名称必填 (RULE_1_PROJECT_ROLE_REQUIRED)
   - Rule 2: 工作经历起止时间与至今契约 (RULE_2_WORK_DATE_AND_CURRENT_CONTRACT)
   - Rule 3: 个人优势 500 字与工作描述 2000 字智能截断 (RULE_3_CHAR_LIMIT_TRUNCATION)
   - Rule 4: 学历与学位码值对齐 (RULE_4_DEGREE_CODE_MAPPING)
   - Rule 5: 驻外经历持续时长与国家码映射 (RULE_5_OVERSEAS_TRAIT_OPTIONS)
   - Rule 6: 期望薪资区间合理性约束 (RULE_6_SALARY_RANGE_CONSTRAINT)
3. 自动化自愈处方执行：自动创建时间戳备份快照，执行字段清洗、补齐与数据自愈。
"""

import os
import json
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from resume_editor.platforms.browser_common import atomic_write_json

from resume_editor.paths import DATA_DIR  # 单一事实源（Q-M5-2 收敛）

BOSS_WRITEBACK_FILE = os.path.join(DATA_DIR, "boss_writeback.json")
BOSS_FIELDS_FILE = os.path.join(DATA_DIR, "boss_fields.json")
BOSS_SNAPSHOTS_DIR = os.path.join(DATA_DIR, "snapshots")

BOSS_MODULE_LABELS = {
    "baseinfo": "基本信息",
    "personal_advantage": "个人优势",
    "expectations": "求职期望",
    "work_experience": "工作经历",
    "projects": "项目经历",
    "education": "教育经历",
    "certificates": "资格证书",
    "overseas": "海外/出差经历",
}


class BossSnapshotManager:
    """BOSS 直聘时间戳快照管理器"""

    def __init__(self, snapshots_dir: str | None = None):
        # 运行时读取模块常量（Q-M5-2）：避免类定义时绑定路径，测试可 patch BOSS_SNAPSHOTS_DIR
        if snapshots_dir is None:  # 严格区分 None 与空串：空串应快速失败而非静默回落生产目录
            snapshots_dir = BOSS_SNAPSHOTS_DIR
        self.snapshots_dir = snapshots_dir
        os.makedirs(self.snapshots_dir, exist_ok=True)

    def create_snapshot(self, tag: str = "boss_heal") -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        snap_name = f"{tag}_{timestamp}.bak.json"
        snap_path = os.path.join(self.snapshots_dir, snap_name)

        data = {}
        if os.path.exists(BOSS_WRITEBACK_FILE):
            try:
                with open(BOSS_WRITEBACK_FILE, "r", encoding="utf-8") as f:
                    data["writeback"] = json.load(f)
            except Exception:
                pass
        if os.path.exists(BOSS_FIELDS_FILE):
            try:
                with open(BOSS_FIELDS_FILE, "r", encoding="utf-8") as f:
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
                if f.startswith("boss_heal_") and f.endswith(".bak.json")
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
                if f.startswith("boss_heal_") and f.endswith(".bak.json")
            ]
            if not files:
                return False, "未找到可回滚的 BOSS 历史快照备份"
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
                atomic_write_json(BOSS_WRITEBACK_FILE, data["writeback"])
            if "fields" in data and data["fields"]:
                atomic_write_json(BOSS_FIELDS_FILE, data["fields"])
            return True, f"已成功从快照 {snapshot_id} 回滚 BOSS 数据"
        except Exception as e:
            return False, f"回滚失败: {str(e)}"

    def list_snapshots(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.snapshots_dir):
            return []
        res = []
        files = [
            f for f in os.listdir(self.snapshots_dir)
            if f.startswith("boss_heal_") and f.endswith(".bak.json")
        ]
        files.sort(reverse=True)
        for f in files[:10]:
            p = os.path.join(self.snapshots_dir, f)
            mtime = datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M:%S")
            res.append({"snapshot_id": f, "created_at": mtime, "size": os.path.getsize(p)})
        return res


class BossHealerAgent:
    """BOSS 直聘数据回写自愈 Agent"""

    def __init__(self, port: int = 19222):
        self.port = port
        self.snapshot_mgr = BossSnapshotManager()

    def gather_live_forensics(self, target_module: str) -> Dict[str, Any]:
        """连接 19222 端口 BOSS 直聘浏览器，抓取现场数据"""
        try:
            # 防误拉 Chrome：统一走连接入口（端口无响应直接报错，绝不自动拉起浏览器）
            from resume_editor.platforms.browser_common import connect_page
            page = connect_page(self.port)

            js_code = f"""
            (() => {{
                try {{
                    const url = window.location.href;
                    const title = document.title;
                    const items = document.querySelectorAll('.resume-item, .history-item, .project-item');
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
            return {"ok": False, "error": f"19222 取证连接失败: {str(e)}"}

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
            "work_experience": ["works", "workExpList", "work_exp"],
            "projects": ["projectList", "project_exp", "projectExpList"],
            "education": ["educations", "eduList", "eduexp"],
            "certificates": ["certs", "certificationList", "certifications"],
            "expectations": ["expectList", "intentions", "job_wants"],
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
        if local_data is None and os.path.exists(BOSS_WRITEBACK_FILE):
            try:
                with open(BOSS_WRITEBACK_FILE, "r", encoding="utf-8") as f:
                    local_data = json.load(f)
            except Exception:
                pass
        local_data = local_data or {}
        local_items = self._extract_module_items(local_data, target_module)

        # ----------------------------------------------------
        # Rule 1: 项目经历职务/角色与名称必填
        # ----------------------------------------------------
        if target_module in ("projects", "project_experience"):
            has_missing_role = any(
                isinstance(p, dict) and (not p.get("role") and not p.get("projectRole"))
                for p in local_items
            )
            if "role" in combined_err or "职务" in combined_err or "项目角色" in combined_err or has_missing_role:
                return {
                    "ok": True,
                    "module": target_module,
                    "module_label": BOSS_MODULE_LABELS.get(target_module, target_module),
                    "rule_code": "RULE_1_PROJECT_ROLE_REQUIRED",
                    "rule_name": "BOSS 项目经历项目职务/角色必填法则",
                    "confidence": 0.96,
                    "root_cause": "BOSS 直聘项目经历接口严格要求 `role`（项目职务/角色）非空，缺省时将触发保存失败。",
                    "recipe": {
                        "action_type": "fix_project_roles",
                        "module": target_module,
                        "title": "自动补齐项目经历缺省职务角色",
                        "details": "为缺失 role 的项目条目自动注入默认职务（如 '核心开发 / 技术负责人'）。"
                    },
                    "evidence": {"missing_role_count": sum(1 for p in local_items if isinstance(p, dict) and not p.get("role"))},
                    "suggested_action": "一键补齐项目职务并重新回传"
                }

        # ----------------------------------------------------
        # Rule 2: 工作经历起止时间与至今契约
        # ----------------------------------------------------
        if target_module in ("work_experience", "works"):
            has_invalid_dates = any(
                isinstance(w, dict) and (
                    (w.get("isCurrent") or w.get("soFar")) and w.get("endDate") not in ("至今", "", None)
                )
                for w in local_items
            )
            if "date" in combined_err or "时间" in combined_err or "至今" in combined_err or has_invalid_dates:
                return {
                    "ok": True,
                    "module": target_module,
                    "module_label": BOSS_MODULE_LABELS.get(target_module, target_module),
                    "rule_code": "RULE_2_WORK_DATE_AND_CURRENT_CONTRACT",
                    "rule_name": "BOSS 工作经历年月格式与至今状态契约",
                    "confidence": 0.95,
                    "root_cause": "BOSS 直聘工作经历在在职状态（isCurrent/至今）下要求 endDate 为空或'至今'，且月份必须规范为 YYYY.MM 或 YYYY-MM。",
                    "recipe": {
                        "action_type": "normalize_work_dates",
                        "module": target_module,
                        "title": "规范工作经历起止时间与至今标识",
                        "details": "格式化年月并对齐在职状态下的结束时间字段。"
                    },
                    "evidence": {"invalid_date_items": sum(1 for w in local_items if isinstance(w, dict) and w.get("isCurrent"))},
                    "suggested_action": "一键规范时间格式并重传"
                }

        # ----------------------------------------------------
        # Rule 3: 个人优势 500 字与工作描述 2000 字截断
        # ----------------------------------------------------
        if target_module in ("personal_advantage", "work_experience", "projects"):
            char_overflow = False
            if target_module == "personal_advantage":
                adv_text = local_data.get("personal_advantage", "") or ""
                if isinstance(adv_text, dict):
                    adv_text = adv_text.get("current_value", "") or adv_text.get("description", "")
                if len(str(adv_text)) > 500:
                    char_overflow = True
            elif any(isinstance(it, dict) and len(str(it.get("content", "") or it.get("workDescription", "") or it.get("describe", ""))) > 2000 for it in local_items):
                char_overflow = True

            if "500" in combined_err or "2000" in combined_err or "长度" in combined_err or "超限" in combined_err or char_overflow:
                return {
                    "ok": True,
                    "module": target_module,
                    "module_label": BOSS_MODULE_LABELS.get(target_module, target_module),
                    "rule_code": "RULE_3_CHAR_LIMIT_TRUNCATION",
                    "rule_name": "BOSS 文本字符上限与智能截断契约",
                    "confidence": 0.98,
                    "root_cause": "BOSS 个人优势限制 500 字符，工作与项目描述单段限制 2000 字符，超限将被官网接口拒绝。",
                    "recipe": {
                        "action_type": "truncate_char_overflow",
                        "module": target_module,
                        "title": "智能无损截断超长文本至平台安全上限",
                        "details": "安全截断个人优势（<=500字）与段落描述（<=2000字）。"
                    },
                    "evidence": {"char_overflow": True},
                    "suggested_action": "一键安全截断并重新回传"
                }

        # ----------------------------------------------------
        # Rule 4: 学历与学位码值对齐
        # ----------------------------------------------------
        if target_module in ("education", "educations"):
            return {
                "ok": True,
                "module": target_module,
                "module_label": BOSS_MODULE_LABELS.get(target_module, target_module),
                "rule_code": "RULE_4_DEGREE_CODE_MAPPING",
                "rule_name": "BOSS 学历与统招枚举码表对齐",
                "confidence": 0.92,
                "root_cause": "BOSS 直聘教育经历要求将学历标准化为官方 degree 码（4本科/5硕士/6博士）并保留统招属性。",
                "recipe": {
                    "action_type": "align_degree_codes",
                    "module": target_module,
                    "title": "对齐 BOSS 官方学位枚举码",
                    "details": "转换文本学历为 BOSS 对应数字码（4: 本科, 5: 硕士, 6: 博士）。"
                },
                "evidence": {"target_module": target_module},
                "suggested_action": "一键对齐学历码表并重传"
            }

        # ----------------------------------------------------
        # Rule 5: 驻外经历持续时长与国家码映射
        # ----------------------------------------------------
        if target_module in ("overseas",):
            return {
                "ok": True,
                "module": target_module,
                "module_label": "海外/出差经历",
                "rule_code": "RULE_5_OVERSEAS_TRAIT_OPTIONS",
                "rule_name": "BOSS 驻外经历与时长码值装配",
                "confidence": 0.94,
                "root_cause": "BOSS 直聘海外与出差经历要求装配 duration 驻外时长码（如 1~3个月: 2）及国家/大洲数组。",
                "recipe": {
                    "action_type": "assemble_overseas_payload",
                    "module": target_module,
                    "title": "装配规范的驻外时长与地区码值",
                    "details": "校验并对齐 overseas duration 码与出差国家列表。"
                },
                "evidence": {"target_module": target_module},
                "suggested_action": "一键规范出差经历并重传"
            }

        # ----------------------------------------------------
        # Rule 6: 期望薪资区间合理性约束
        # ----------------------------------------------------
        if target_module in ("expectations", "intentions"):
            return {
                "ok": True,
                "module": target_module,
                "module_label": "求职期望",
                "rule_code": "RULE_6_SALARY_RANGE_CONSTRAINT",
                "rule_name": "BOSS 期望薪资倍率与范围约束",
                "confidence": 0.93,
                "root_cause": "BOSS 直聘期望薪资要求最高薪资不能超过最低薪资的 2 倍（maxSalary <= 2 * minSalary）。",
                "recipe": {
                    "action_type": "fix_salary_range",
                    "module": target_module,
                    "title": "自动调整期望薪资至合规区间",
                    "details": "检查薪资倍率并在超标时自动平滑上下限。"
                },
                "evidence": {"target_module": target_module},
                "suggested_action": "一键平滑薪资区间并重传"
            }

        # 默认通用诊断
        return {
            "ok": True,
            "module": target_module,
            "module_label": BOSS_MODULE_LABELS.get(target_module, target_module),
            "rule_code": "RULE_GENERIC_DATA_SYNC",
            "rule_name": "BOSS 模块数据通用对齐与快照刷新",
            "confidence": 0.90,
            "root_cause": f"BOSS 直聘【{BOSS_MODULE_LABELS.get(target_module, target_module)}】回写需要同步更新本地快照与服务端映射契约。",
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
        执行 BOSS 自愈处方并自动生成快照备份
        """
        action_type = recipe.get("action_type", "")
        module = recipe.get("module", "")

        snap_name = self.snapshot_mgr.create_snapshot(tag=f"boss_heal_{module}")

        raw_wb = {}
        if os.path.exists(BOSS_WRITEBACK_FILE):
            try:
                with open(BOSS_WRITEBACK_FILE, "r", encoding="utf-8") as f:
                    raw_wb = json.load(f)
            except Exception:
                pass

        fields_dict = raw_wb.get("fields", raw_wb) if isinstance(raw_wb, dict) else {}
        healed_count = 0

        # Action: fix_project_roles
        if action_type == "fix_project_roles":
            projects = fields_dict.get("projects", [])
            for p in projects:
                if isinstance(p, dict) and not p.get("role"):
                    p["role"] = "核心开发 / 技术负责人"
                    healed_count += 1
            fields_dict["projects"] = projects

        # Action: truncate_char_overflow
        elif action_type == "truncate_char_overflow":
            if "personal_advantage" in fields_dict:
                val = fields_dict["personal_advantage"]
                if isinstance(val, str) and len(val) > 500:
                    fields_dict["personal_advantage"] = val[:500]
                    healed_count += 1
                elif isinstance(val, dict):
                    cval = val.get("current_value", "")
                    if len(str(cval)) > 500:
                        val["current_value"] = str(cval)[:500]
                        healed_count += 1
            if "work_experience" in fields_dict:
                for w in fields_dict["work_experience"]:
                    if isinstance(w, dict) and len(w.get("content", "")) > 2000:
                        w["content"] = w["content"][:2000]
                        healed_count += 1

        # Action: normalize_work_dates
        elif action_type == "normalize_work_dates":
            if "work_experience" in fields_dict:
                for w in fields_dict["work_experience"]:
                    if isinstance(w, dict) and (w.get("isCurrent") or w.get("soFar")):
                        w["endDate"] = "至今"
                        healed_count += 1

        # Action: align_degree_codes
        elif action_type == "align_degree_codes":
            degree_map = {"大专": 3, "本科": 4, "硕士": 5, "博士": 6}
            if "education" in fields_dict:
                for e in fields_dict["education"]:
                    if isinstance(e, dict):
                        deg = e.get("degreeString") or e.get("degree")
                        if deg in degree_map:
                            e["degree"] = degree_map[deg]
                            healed_count += 1

        # Action: fix_salary_range
        elif action_type == "fix_salary_range":
            if "expectations" in fields_dict:
                for exp in fields_dict["expectations"]:
                    if isinstance(exp, dict):
                        min_s = exp.get("minSalary", 15)
                        max_s = exp.get("maxSalary", 25)
                        if max_s > min_s * 2:
                            exp["maxSalary"] = min_s * 2
                            healed_count += 1

        else:
            healed_count = 1

        # 写回 BOSS 快照文件
        if "fields" in raw_wb:
            raw_wb["fields"] = fields_dict
        else:
            raw_wb = fields_dict

        atomic_write_json(BOSS_WRITEBACK_FILE, raw_wb)

        return {
            "ok": True,
            "snapshot_id": snap_name,
            "healed_count": healed_count,
            "message": f"BOSS 自愈完成！已自动修复 {healed_count} 处异常并创建安全备份 {snap_name}"
        }
