#!/usr/bin/env python3
"""
Skill Upload Policy - 上传防护策略（覆盖确认 + 数量上限）
========================================================
用户拍板（2026-09-19）：
1. 上传/导入命中已存在技能（同 id）时不得静默覆盖，返回确认消息（409），
   用户确认后带 force 重发才覆盖——防止精心调好的技能被同名新上传无声删掉。
2. 自定义技能数量上限 CUSTOM_SKILL_CAP，超限拒绝新增（400）；替换已有不受限。

本模块只做纯判定（目录/文件操作，无 FastAPI 依赖），供 skills_upload 端点调用。
"""
import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger("skill_upload_policy")

CUSTOM_SKILL_CAP = 20


def resolve_custom_id(raw_skill_id: str) -> str:
    """统一自定义技能 id 前缀规则（与 _persist_sanitized_package 保持一致）"""
    safe_id = raw_skill_id
    return safe_id if safe_id.startswith("custom_") else f"custom_{safe_id}"


def find_existing_skill_path(skills_base: Path, custom_id: str) -> Path | None:
    """定位已存在技能：目录包 custom_<id>/ 或单文件 custom_<id>.md，两者取其一"""
    dir_form = skills_base / custom_id
    if dir_form.is_dir():
        return dir_form
    file_form = skills_base / f"{custom_id}.md"
    if file_form.exists():
        return file_form
    return None


def _main_entry_of(existing: Path) -> Path | None:
    """已存在技能的主文件：目录包找 SKILL.md（大小写兼容），单文件即 .md 本身"""
    if existing.is_file():
        return existing
    for candidate in ["SKILL.md", "skill.md", "prompt.md", "main.md"]:
        p = existing / candidate
        if p.exists():
            return p
    md_files = sorted(existing.glob("*.md"))
    return md_files[0] if md_files else None


def is_content_identical(existing: Path, incoming_main_content: str) -> bool | None:
    """对比已存在技能主文件与 incoming 内容的 md5。

    返回 True/False；读不了（权限/编码/主文件缺失）返回 None，由调用方按"无法判定"处理。
    """
    try:
        main_entry = _main_entry_of(existing)
        if not main_entry:
            return None
        existing_bytes = main_entry.read_bytes()
        incoming_bytes = incoming_main_content.encode("utf-8")
        return hashlib.md5(existing_bytes).hexdigest() == hashlib.md5(incoming_bytes).hexdigest()
    except Exception as e:
        logger.warning("is_content_identical 读取失败，按『无法判定』处理: %s", e)
        return None


def _display_name_of(existing: Path) -> str:
    """从 meta.json 取展示名，取不到回退路径名"""
    try:
        if existing.is_dir():
            meta_path = existing / "meta.json"
            if meta_path.exists():
                return str(json.loads(meta_path.read_text(encoding="utf-8")).get("name") or existing.name)
        return existing.stem
    except Exception as e:
        logger.warning("_display_name_of 读取 meta.json 失败，回退路径名: %s", e)
        return existing.name


def check_upload_conflict(
    skills_base: Path, raw_skill_id: str, incoming_main_content: str
) -> str | None:
    """覆盖冲突检查。返回确认消息（HTTP 409 用）或 None（无冲突，可落盘）。

    任何内部异常按"无法判定冲突"处理返回 None——防护不得误伤正常上传。
    """
    try:
        custom_id = resolve_custom_id(raw_skill_id)
        existing = find_existing_skill_path(skills_base, custom_id)
        if not existing:
            return None
        display = _display_name_of(existing)
        identical = is_content_identical(existing, incoming_main_content)
        if identical:
            return (
                f"已存在内容完全相同的技能「{display}」（{custom_id}），无需重复上传。"
                "如仍要替换覆盖，请点击确认。"
            )
        if identical is False:
            return (
                f"已存在同名/同源技能「{display}」（{custom_id}），但内容不同——"
                "替换将永久覆盖旧版本。是否继续？"
            )
        return f"已存在技能「{display}」（{custom_id}），是否替换覆盖？"
    except Exception:
        return None


def count_custom_skills(skills_base: Path) -> int:
    """统计现有自定义技能数：custom_ 前缀的目录 + 单 .md 文件（meta.json 等附属不计）"""
    if not skills_base.exists():
        return 0
    count = 0
    for p in skills_base.iterdir():
        if p.name.startswith("custom_"):
            if p.is_dir():
                count += 1
            elif p.suffix == ".md":
                count += 1
    return count


def check_upload_quota(skills_base: Path, raw_skill_id: str) -> str | None:
    """数量上限检查。返回拒绝消息（HTTP 400 用）或 None（放行）。

    替换已有技能（同 id 冲突存在）不占新名额，不受上限约束。
    内部异常按放行处理（防护不得误伤）。
    """
    try:
        custom_id = resolve_custom_id(raw_skill_id)
        if find_existing_skill_path(skills_base, custom_id):
            return None
        if count_custom_skills(skills_base) >= CUSTOM_SKILL_CAP:
            return (
                f"自定义技能数量已达上限（{CUSTOM_SKILL_CAP} 个），"
                "请先在技能详情中删除不需要的技能后再上传。"
            )
        return None
    except Exception as e:
        logger.warning("check_upload_quota 内部异常，按未达上限放行: %s", e)
        return None
