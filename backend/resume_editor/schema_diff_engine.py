#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多平台在线简历编辑器 - Schema Diff 差分探针与元数据模版自愈引擎
在数据采集完成后，前置对比官网最新数据与本地模版结构，识别新增/废弃字段、子列表变动与新模块。
"""

import copy
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from resume_editor.paths import DATA_DIR  # 单一事实源（Q-M5-2 收敛）

from resume_editor.platforms.browser_common import atomic_write_json

SNAPSHOTS_DIR = os.path.join(DATA_DIR, "schema_snapshots")

# 运行时噪音属性黑名单（前端渲染/状态/临时缓存变量，绝非业务字段）
_NOISE_KEYS = {
    "_isHover", "_hover", "isHover", "_selected", "selected", "_editing", "isEditing",
    "editing", "_open", "isOpen", "_expanded", "isExpanded", "_loading", "isLoading",
    "_error", "errorMsg", "_checked", "isChecked", "_uid", "_key", "key", "__ob__",
    "_vnode", "_staticTrees", "_events", "_hasNormalLsnr", "$vnode", "$options",
    "toToday", "toNow", "isNow", "isCurrentShow", "proExpIsCurrentShow",
}

_NOISE_PATTERNS = [
    re.compile(r".*Translation$"),      # 枚举翻译字段（如 *Translation）
    re.compile(r".*String$"),           # 纯文本派生字段（如 industryString）
    re.compile(r"^_.*"),                # 下划线开头的私有变量
    re.compile(r"^temp_.*"),            # 临时变量
    re.compile(r"^mock_.*"),            # 测试桩
]


def is_runtime_noise(key: str) -> bool:
    """判断是否为前端运行态噪音属性"""
    if not key or not isinstance(key, str):
        return True
    k = key.strip()
    if k in _NOISE_KEYS:
        return True
    return any(p.match(k) for p in _NOISE_PATTERNS)


def is_system_metadata(key: str, value: Any = None, parent_dict: Optional[dict] = None) -> bool:
    """
    启发式动态识别平台底层元数据/内部运行时影子属性（拒绝枚举死列表）
    根据命名模式、时间戳格式、长串流水ID、图床URL与影子冗余进行自动特征分类
    """
    if not key or not isinstance(key, str):
        return True
    k = key.strip()

    if is_runtime_noise(k):
        return True

    if k.startswith("_") or k.startswith("$") or k.endswith("Translation") or k.endswith("String") or k.endswith("Format"):
        return True

    if k in ("id", "path", "key", "_deprecated_fields", "subType", "index", "sort", "order", "dailyWage", "durationInMonths", "workdays", "workYear", "salaryConfidentiality", "salaryTimes"):
        return True

    # 1. 启发式时间戳识别
    if re.search(r"(Time|_time|Date|_date|modify|create|verify)", k, re.I):
        if isinstance(value, str) and re.match(r"^\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}", value.strip()):
            return True

    # 2. 启发式系统主键/流水号识别
    if re.search(r"(Id|_id|ID|moduleId|licenseId|securityId|encryptId|sortId|orderId|token|uuid|Serial|kgId)", k, re.I):
        if isinstance(value, str):
            v = value.strip()
            if re.match(r"^\d{4,}$", v) or re.match(r"^[0-9A-Z]{15,20}$", v) or re.match(r"^[a-f0-9-]{32,}$", v, re.I) or v == "":
                return True
        elif isinstance(value, int):
            return True

    # 3. 启发式 CDN 静态资源图床
    if re.search(r"(logo|avatar|icon|thumb|image|img|Url|_url)$", k, re.I):
        if isinstance(value, str) and re.match(r"^https?://.*(cdn|homelogo|avatar|default|\.png|\.jpg|\.jpeg|\.svg)", value):
            return True

    # 4. 启发式平台系统标志位与服务端标签识别 (包含 51job/BOSS/智联/猎聘的服务端标签)
    if re.match(r"^(complete|isComplete|isEnglish|isOverseas|seekType|isLock|anonymous|showRealName|disAgreePrivacy|personalization|isVerify|isMobileVerify|toToday|toNow|isNow|is211|is985|isMba|isFullTime|is_211|is_985|is_mba|is_full_time|label|labels|tag|tags|logoUrl|avatarUrl|isHiddenForB|workIsReferences|proExpIsCurrent|academicCertificateNumber|academicCertificateVerifyState|eduCampusFullTime|eduDegree|eduMajorSmallType|eduMajorT|newEduMajorT|eduMinorName|eduOverseaseExperienceYear|eduRank|eduResearchArea|eduSchoolCode|eduSpecializedCourses|schoolLogo|schoolTag|majorKgId|schoolNameKgId)$", k, re.I):
        return True

    # 5. 问答与背调专属字段过滤
    if re.search(r"(Question|Answer|workRef)", k, re.I):
        return True

    # 6. 动态影子镜像冗余字段
    if parent_dict and isinstance(parent_dict, dict):
        if k == "trainAgency" and "trainName" in parent_dict:
            return True
        if k == "title" and ("jobTitle" in parent_dict or "proExpProjectName" in parent_dict):
            return True
        if k.startswith("new") and (("w" + k) in parent_dict or ("p" + k) in parent_dict or ("edu" + k) in parent_dict):
            return True
        if k == "wnewJobType" and "wnewJobSubType" in parent_dict:
            return True
        if k in ("industry", "jobType", "jobSubType") and ("wnewIndustry" in parent_dict or "wnewJobSubType" in parent_dict or "pnewPreferredIndustry" in parent_dict):
            return True
        if isinstance(value, list) and isinstance(parent_dict.get("skills"), list):
            skills = parent_dict["skills"]
            if value and all(
                (isinstance(item, str) and item in skills) or
                (isinstance(item, dict) and item.get("skill") in skills)
                for item in value
            ):
                return True
        if k.endswith("Labels") and isinstance(value, list) and len(value) == 0:
            return True
        if k.endswith("New") and (k[:-3] in parent_dict or "industry" in parent_dict):
            return True

    return False


def clean_runtime_noise(data: Any) -> Any:
    """递归清洗字典/列表中的运行态噪音属性，保留纯净业务数据结构"""
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if is_runtime_noise(k):
                continue
            out[k] = clean_runtime_noise(v)
        return out
    elif isinstance(data, list):
        return [clean_runtime_noise(x) for x in data]
    return data


def _extract_module_schema(node: Any, module_name: str) -> Dict[str, Any]:
    """提取单个模块的 Schema 特征（标量字段、列表 item_keys、子列表等）"""
    if isinstance(node, list):
        item_keys: Set[str] = set()
        sub_lists: Dict[str, List[str]] = {}
        sample_item = None
        for item in node:
            if isinstance(item, dict):
                sample_item = item
                break
        if sample_item:
            for k, v in sample_item.items():
                if is_runtime_noise(k):
                    continue
                item_keys.add(k)
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    sub_keys = [sk for sk in v[0].keys() if not is_runtime_noise(sk)]
                    sub_lists[k] = sub_keys
        return {
            "type": "array",
            "item_keys": sorted(list(item_keys)),
            "sub_lists": sub_lists,
            "count": len(node),
        }
    elif isinstance(node, dict):
        scalar_keys = [k for k in node.keys() if not is_runtime_noise(k)]
        return {
            "type": "object",
            "keys": sorted(scalar_keys),
        }
    else:
        return {
            "type": "scalar",
            "value_type": type(node).__name__,
        }


def diff_platform_schema(platform: str, fresh_data: dict, baseline_template: Optional[dict] = None) -> Dict[str, Any]:
    """
    对比官网采集到的最新数据 (fresh_data) 与本地模版基准 (baseline_template)。
    返回结构化的差分报告：
    {
      "platform": platform,
      "has_changes": bool,
      "summary": str,
      "added_fields": [{"module": str, "field": str, "type": str, "sample": Any}],
      "removed_fields": [{"module": str, "field": str, "last_value": Any}],
      "new_modules": [{"module": str, "type": str, "item_count": int}],
      "removed_modules": [{"module": str}],
      "sub_list_changes": [{"module": str, "parent_field": str, "added_keys": list, "removed_keys": list}],
    }
    """
    if baseline_template is None:
        file_path = os.path.join(DATA_DIR, f"{platform}_fields.json")
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                try:
                    baseline_template = json.load(f)
                except Exception:
                    baseline_template = {}
        else:
            baseline_template = {}

    fresh_clean = clean_runtime_noise(fresh_data or {})
    base_clean = clean_runtime_noise(baseline_template or {})

    added_fields: List[Dict[str, Any]] = []
    removed_fields: List[Dict[str, Any]] = []
    new_modules: List[Dict[str, Any]] = []
    removed_modules: List[Dict[str, Any]] = []
    sub_list_changes: List[Dict[str, Any]] = []

    fresh_modules = set(fresh_clean.keys())
    base_modules = set(base_clean.keys())

    # 1. 检查全新模块新增
    for mod in fresh_modules - base_modules:
        val = fresh_clean[mod]
        mod_type = "array" if isinstance(val, list) else ("object" if isinstance(val, dict) else "scalar")
        new_modules.append({
            "module": mod,
            "type": mod_type,
            "item_count": len(val) if isinstance(val, list) else 1,
        })

    # 2. 检查模块下线删除
    for mod in base_modules - fresh_modules:
        removed_modules.append({
            "module": mod,
        })

    # 3. 共同模块内字段级与子列表比对
    for mod in fresh_modules & base_modules:
        fresh_node = fresh_clean[mod]
        base_node = base_clean[mod]

        fresh_schema = _extract_module_schema(fresh_node, mod)
        base_schema = _extract_module_schema(base_node, mod)

        # A) 数组模块内部字段比对
        if fresh_schema["type"] == "array" and base_schema["type"] == "array":
            f_keys = set(fresh_schema.get("item_keys", []))
            b_keys = set(base_schema.get("item_keys", []))

            # 仅当两端都有条目时才判断字段增删，避免空数组导致的误报
            if fresh_schema["count"] > 0 and base_schema["count"] > 0:
                for k in f_keys - b_keys:
                    sample_val = fresh_node[0].get(k) if fresh_node and isinstance(fresh_node[0], dict) else None
                    added_fields.append({
                        "module": mod,
                        "field": k,
                        "type": "array_item_field",
                        "sample": sample_val,
                    })
                for k in b_keys - f_keys:
                    sample_val = base_node[0].get(k) if base_node and isinstance(base_node[0], dict) else None
                    removed_fields.append({
                        "module": mod,
                        "field": k,
                        "last_value": sample_val,
                    })

            # 子列表嵌套结构比对
            f_sub = fresh_schema.get("sub_lists", {})
            b_sub = base_schema.get("sub_lists", {})
            all_sub_keys = set(f_sub.keys()) | set(b_sub.keys())
            for sub_k in all_sub_keys:
                f_sub_items = set(f_sub.get(sub_k, []))
                b_sub_items = set(b_sub.get(sub_k, []))
                if f_sub_items != b_sub_items:
                    sub_list_changes.append({
                        "module": mod,
                        "parent_field": sub_k,
                        "added_keys": sorted(list(f_sub_items - b_sub_items)),
                        "removed_keys": sorted(list(b_sub_items - f_sub_items)),
                    })

        # B) 对象节点标量字段比对（如 profile）
        elif fresh_schema["type"] == "object" and base_schema["type"] == "object":
            f_keys = set(fresh_schema.get("keys", []))
            b_keys = set(base_schema.get("keys", []))
            for k in f_keys - b_keys:
                added_fields.append({
                    "module": mod,
                    "field": k,
                    "type": "object_property",
                    "sample": fresh_node.get(k),
                })
            for k in b_keys - f_keys:
                removed_fields.append({
                    "module": mod,
                    "field": k,
                    "last_value": base_node.get(k),
                })

    has_changes = bool(added_fields or removed_fields or new_modules or removed_modules or sub_list_changes)

    # 生成人话可读摘要
    summary_parts = []
    if new_modules:
        mod_names = ", ".join(m["module"] for m in new_modules)
        summary_parts.append(f"新增 {len(new_modules)} 个模块（{mod_names}）")
    if removed_modules:
        rm_names = ", ".join(m["module"] for m in removed_modules)
        summary_parts.append(f"下线 {len(removed_modules)} 个模块（{rm_names}）")
    if added_fields:
        f_names = ", ".join(f"{f['module']}.{f['field']}" for f in added_fields[:3])
        suffix = "等" if len(added_fields) > 3 else ""
        summary_parts.append(f"新增 {len(added_fields)} 个字段（{f_names}{suffix}）")
    if removed_fields:
        rf_names = ", ".join(f"{f['module']}.{f['field']}" for f in removed_fields[:3])
        suffix = "等" if len(removed_fields) > 3 else ""
        summary_parts.append(f"下线 {len(removed_fields)} 个废弃字段（{rf_names}{suffix}）")
    if sub_list_changes:
        summary_parts.append(f"检测到 {len(sub_list_changes)} 项子列表结构变动")

    summary = "；".join(summary_parts) if summary_parts else "官网结构与本地模版 100% 保持一致"

    return {
        "platform": platform,
        "has_changes": has_changes,
        "summary": summary,
        "added_fields": added_fields,
        "removed_fields": removed_fields,
        "new_modules": new_modules,
        "removed_modules": removed_modules,
        "sub_list_changes": sub_list_changes,
        "timestamp": int(time.time()),
    }


def save_schema_snapshot(platform: str, data: dict, note: str = "") -> str:
    """保存一份带时间戳的 Schema 模版快照，支持无损回滚"""
    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    snapshot_filename = f"{platform}_schema_{ts}.json"
    snapshot_path = os.path.join(SNAPSHOTS_DIR, snapshot_filename)
    payload = {
        "platform": platform,
        "timestamp": ts,
        "note": note,
        "data": data,
    }
    atomic_write_json(snapshot_path, payload)

    # 滚动保留最近 15 份快照
    try:
        files = sorted([f for f in os.listdir(SNAPSHOTS_DIR) if f.startswith(f"{platform}_schema_")])
        while len(files) > 15:
            oldest = files.pop(0)
            os.remove(os.path.join(SNAPSHOTS_DIR, oldest))
    except Exception:
        pass

    return snapshot_path


def apply_schema_patch(platform: str, diff_result: dict, fresh_data: Optional[dict] = None) -> Dict[str, Any]:
    """
    用户确认后，将 Schema 变动原子级合并并同步到本地模版文件 {platform}_fields.json 中。
    自动备份快照，软归档废弃字段。
    """
    file_path = os.path.join(DATA_DIR, f"{platform}_fields.json")
    if not os.path.exists(file_path):
        return {"success": False, "message": f"{platform}_fields.json 不存在"}

    with open(file_path, "r", encoding="utf-8") as f:
        current_data = json.load(f)

    # 1. 备份当前模版快照
    snapshot_path = save_schema_snapshot(platform, current_data, note=f"执行 Schema 对齐补丁: {diff_result.get('summary', '')}")

    updated_data = copy.deepcopy(current_data)
    fresh_clean = clean_runtime_noise(fresh_data or {})

    # 2. 合并全新模块
    for mod_info in diff_result.get("new_modules", []):
        mod = mod_info["module"]
        if mod in fresh_clean:
            updated_data[mod] = copy.deepcopy(fresh_clean[mod])

    # 3. 软归档/移除已下线模块
    for mod_info in diff_result.get("removed_modules", []):
        mod = mod_info["module"]
        if mod in updated_data:
            # 存入归档区后移除活跃区
            archived = updated_data.setdefault("__deprecated_archive__", {})
            archived[mod] = updated_data.pop(mod)

    # 4. 补齐新增字段
    for f_info in diff_result.get("added_fields", []):
        mod = f_info["module"]
        field = f_info["field"]
        sample_val = f_info.get("sample")
        if mod in updated_data:
            if isinstance(updated_data[mod], list):
                for item in updated_data[mod]:
                    if isinstance(item, dict) and field not in item:
                        item[field] = copy.deepcopy(sample_val) if sample_val is not None else ""
            elif isinstance(updated_data[mod], dict):
                if field not in updated_data[mod]:
                    updated_data[mod][field] = copy.deepcopy(sample_val) if sample_val is not None else ""

    # 5. 软归档已下线字段
    for f_info in diff_result.get("removed_fields", []):
        mod = f_info["module"]
        field = f_info["field"]
        if mod in updated_data:
            if isinstance(updated_data[mod], list):
                for item in updated_data[mod]:
                    if isinstance(item, dict) and field in item:
                        # 记录到条目内的 _deprecated 备份区后移除
                        dep = item.setdefault("_deprecated_fields", {})
                        dep[field] = item.pop(field)
            elif isinstance(updated_data[mod], dict):
                if field in updated_data[mod]:
                    dep = updated_data[mod].setdefault("_deprecated_fields", {})
                    dep[field] = updated_data[mod].pop(field)

    # 6. 保存更新后的模版文件
    atomic_write_json(file_path, updated_data)

    return {
        "success": True,
        "platform": platform,
        "message": f"模版已成功对齐（{diff_result.get('summary', '无结构变动')}）",
        "snapshot_path": snapshot_path,
        "updated_modules_count": len(updated_data),
    }
