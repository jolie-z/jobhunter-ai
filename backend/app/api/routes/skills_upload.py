"""
Skills Upload Router - 自定义技能导入（.md / .zip / 文件夹 / GitHub）
====================================================================
自 skills.py 拆出（500 行纪律）：上传/导入端点 + 落盘持久化 + 覆盖确认/配额守卫。
路由无前缀，由 skills.py 的 include_router 挂到 /resume-editor/skills 下。
"""

import json
import os
import re
import shutil
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from fastapi import (
    Body,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from fastapi import APIRouter

from ai_agents.skills.skill_loader import get_skill_manager, reset_skill_manager
from ai_agents.skills.skill_upload_policy import (
    check_upload_conflict,
    check_upload_quota,
    resolve_custom_id,
)
from ai_agents.skills.skill_validator import (
    SanitizedSkillPackage,
    SkillValidationError,
    safe_extract_zip_package,
    validate_and_sanitize_package,
)

router = APIRouter(tags=["动态技能管理"])


class GitHubImportRequest(BaseModel):
    repo_url: str
    mode: str = "clean"  # "clean" or "strict"
    suggested_name: str | None = None
    force: bool = False  # 覆盖确认后的重发标记


def _persist_sanitized_package(package: SanitizedSkillPackage, custom_name: str | None = None) -> Path:
    """将经过安全校验的技能包写入技能目录，并保存自定义显示名称"""
    manager = get_skill_manager()
    skills_base = manager.SKILLS_DIR
    skills_base.mkdir(parents=True, exist_ok=True)

    # 规范技能 ID 前缀
    safe_id = resolve_custom_id(package.skill_id)

    display_name = custom_name or package.display_name or safe_id

    if package.references:
        # 📦 存在 reference 附属文件：保存为目录级技能包
        target_dir = skills_base / safe_id
        # force 覆盖原子性：先把旧目录 rename 为临时备份，落盘成功才清理，失败还原——
        # 防止"确认替换后落盘中途失败，旧技能已删且无备份"
        backup_dir: Path | None = None
        if target_dir.exists():
            backup_dir = skills_base / f".bak-{safe_id}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            target_dir.rename(backup_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 写入主文件 (SKILL.md)
            main_file_path = target_dir / "SKILL.md"
            with open(main_file_path, 'w', encoding='utf-8') as f:
                f.write(package.main_file_content)

            # 写入所有 reference 参考资料
            for ref in package.references:
                ref_path = target_dir / ref["name"]
                ref_path.parent.mkdir(parents=True, exist_ok=True)
                with open(ref_path, 'w', encoding='utf-8') as rf:
                    rf.write(ref["content"])

            # 写入 meta.json 持久化自定义命名
            meta_info = {
                "id": safe_id,
                "name": display_name,
                "version": "1.0.0",
                "is_package": True,
                "created_at": datetime.now().isoformat()
            }
            with open(target_dir / "meta.json", 'w', encoding='utf-8') as mf:
                json.dump(meta_info, mf, ensure_ascii=False, indent=2)
        except Exception:
            # 落盘失败：还原旧目录，把异常抛回给调用方
            if backup_dir is not None:
                shutil.rmtree(target_dir, ignore_errors=True)
                backup_dir.rename(target_dir)
            raise
        if backup_dir is not None:
            shutil.rmtree(backup_dir, ignore_errors=True)

        return target_dir
    else:
        # 📄 单文件技能：保存为单 .md 文件 + 同名 .json 元数据（覆盖前备份，失败还原）
        file_path = skills_base / f"{safe_id}.md"
        meta_path = skills_base / f"{safe_id}.json"
        backups: list[tuple[Path, Path]] = []
        try:
            for target in (file_path, meta_path):
                if target.exists():
                    bak = skills_base / f".bak-{target.name}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
                    target.rename(bak)
                    backups.append((bak, target))
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(package.main_file_content)

            meta_info = {
                "id": safe_id,
                "name": display_name,
                "version": "1.0.0",
                "is_package": False,
                "created_at": datetime.now().isoformat()
            }
            with open(meta_path, 'w', encoding='utf-8') as mf:
                json.dump(meta_info, mf, ensure_ascii=False, indent=2)
        except Exception:
            # 对称还原：删两个半成品再还原备份（目录形态 rmtree+rename 的单文件等价物）
            file_path.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            for bak, target in backups:
                if not target.exists():
                    bak.rename(target)
            raise
        for bak, _target in backups:
            bak.unlink(missing_ok=True)

        return file_path


def enforce_upload_guards(sanitized_pkg: SanitizedSkillPackage, force: bool) -> None:
    """上传防护共用入口：conflict 命中且非 force 抛 409；quota 命中一律抛 400（force 不豁免）。"""
    manager = get_skill_manager()
    conflict_msg = check_upload_conflict(manager.SKILLS_DIR, sanitized_pkg.skill_id, sanitized_pkg.main_file_content)
    if conflict_msg and not force:
        raise HTTPException(status_code=409, detail=conflict_msg)
    quota_msg = check_upload_quota(manager.SKILLS_DIR, sanitized_pkg.skill_id)
    if quota_msg:
        raise HTTPException(status_code=400, detail=quota_msg)


@router.post("/upload")
async def upload_custom_skill(
    file: UploadFile | None = File(None),
    files: list[UploadFile] | None = File(None),
    name: str | None = Form(None),
    mode: str = Form("clean"),  # "clean" or "strict"
    force: bool = Form(False),  # 覆盖确认后的重发标记（FastAPI 解析 "true"/"false"）
):
    """
    全能多格式技能上传接口：
    - 支持单个 .md / .txt / .json 文件
    - 支持 .zip 压缩包（自动解压、安全过滤、识别 references）
    - 支持文件夹批量拖拽上传 (multipart files)
    """
    try:
        mode = mode.lower().strip()
        if mode not in {"clean", "strict"}:
            mode = "clean"

        sanitized_pkg: SanitizedSkillPackage | None = None

        # 1. 优先处理单 zip 文件或单个 md 文件
        if file is not None and (not files or len(files) <= 1):
            filename = file.filename or "skill.md"
            content_bytes = await file.read()
            ext = os.path.splitext(filename)[1].lower()

            if ext == ".zip":
                # 📦 ZIP 压缩包安全解压
                sanitized_pkg = safe_extract_zip_package(
                    content_bytes,
                    suggested_id=name or filename,
                    mode=mode
                )
            else:
                # 📄 单文件
                sanitized_pkg = validate_and_sanitize_package(
                    [(filename, content_bytes)],
                    suggested_id=name or filename,
                    mode=mode
                )

        # 2. 处理文件夹批量上传 (多文件)
        elif files and len(files) > 0:
            raw_file_tuples = []
            for f in files:
                f_bytes = await f.read()
                raw_file_tuples.append((f.filename, f_bytes))

            sanitized_pkg = validate_and_sanitize_package(
                raw_file_tuples,
                suggested_id=name or "custom_package",
                mode=mode
            )
        else:
            raise HTTPException(status_code=400, detail="未提供任何上传文件。")

        # 3. 上传防护：覆盖确认（409）+ 数量上限（400）——用户确认后带 force 才放行
        enforce_upload_guards(sanitized_pkg, force)

        # 4. 落地存储并热加载
        _persist_sanitized_package(sanitized_pkg, custom_name=name)
        reset_skill_manager()
        manager = get_skill_manager()

        registered_meta = None
        target_id = sanitized_pkg.skill_id if sanitized_pkg.skill_id.startswith("custom_") else f"custom_{sanitized_pkg.skill_id}"
        if target_id in manager.skills:
            registered_meta = manager.skills[target_id]
        else:
            for meta in manager.skills.values():
                if meta.id == sanitized_pkg.skill_id or meta.id == target_id:
                    registered_meta = meta
                    break

        if not registered_meta:
            registered_meta = manager.get_default_skill()

        return {
            "success": True,
            "message": f"技能包「{registered_meta.name if registered_meta else sanitized_pkg.skill_id}」导入成功！",
            "skill": {
                "id": registered_meta.id if registered_meta else sanitized_pkg.skill_id,
                "name": registered_meta.name if registered_meta else (name or sanitized_pkg.skill_id),
                "version": registered_meta.version if registered_meta else "1.0.0",
                "is_package": sanitized_pkg.references is not None and len(sanitized_pkg.references) > 0,
                "references_count": len(sanitized_pkg.references)
            },
            "audit_report": {
                "main_entry": sanitized_pkg.main_file_name,
                "references_count": len(sanitized_pkg.references),
                "references": [r["name"] for r in sanitized_pkg.references[:15]],
                "ignored_scripts_count": len(sanitized_pkg.ignored_scripts),
                "ignored_scripts": sanitized_pkg.ignored_scripts[:10],
                "mode_used": sanitized_pkg.mode_used,
                "total_valid_size_kb": round(sanitized_pkg.total_valid_size / 1024, 2)
            }
        }

    except SkillValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(
            content={"success": False, "error": f"上传失败: {str(e)}"},
            status_code=500
        )


@router.post("/import-github")
async def import_github_skill(payload: GitHubImportRequest = Body(...)):
    """
    从 GitHub 开源仓库 URL 一键导入 Skill 技能包
    例如: https://github.com/wanyichen06/LLMInternSkill
    """
    try:
        raw_url = payload.repo_url.strip()
        if not raw_url:
            raise HTTPException(status_code=400, detail="GitHub 仓库地址不能为空。")

        # 正则提取 owner 和 repo
        match = re.search(r'github\.com/([^/]+)/([^/#?]+)', raw_url)
        if not match:
            # 兼容输入 owner/repo 格式
            match = re.match(r'^([^/]+)/([^/#?]+)$', raw_url)
            if not match:
                raise HTTPException(status_code=400, detail="无效的 GitHub 仓库地址，格式需为: https://github.com/owner/repo")

        owner, repo = match.group(1), match.group(2).replace('.git', '')
        custom_name = payload.suggested_name.strip() if payload.suggested_name else None
        suggested_id = repo

        # 构建下载地址
        zip_urls = [
            f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/main",
            f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/master",
            f"https://github.com/{owner}/{repo}/archive/refs/heads/main.zip"
        ]

        zip_bytes = None
        last_err = None

        # 安全下载（绕过本地代理干扰）
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        headers = {
            "User-Agent": "JobHunter-Skill-Importer/1.0",
            "Accept": "application/vnd.github+json, application/zip"
        }

        for url in zip_urls:
            try:
                req = urllib.request.Request(url, headers=headers)
                with opener.open(req, timeout=30) as resp:
                    if resp.status == 200:
                        zip_bytes = resp.read()
                        break
            except Exception as e:
                last_err = e
                continue

        if not zip_bytes:
            raise HTTPException(
                status_code=502,
                detail=f"无法从 GitHub 下载仓库压缩包 ({owner}/{repo})，请检查网络连接或仓库是否为公开仓库。详情: {last_err}"
            )

        # 安全沙箱解压并过滤
        sanitized_pkg = safe_extract_zip_package(
            zip_bytes,
            suggested_id=suggested_id,
            mode=payload.mode
        )
        if custom_name:
            sanitized_pkg.display_name = custom_name

        # 上传防护：覆盖确认（409）+ 数量上限（400）——与 /upload 同口径
        enforce_upload_guards(sanitized_pkg, payload.force)

        # 落地存储并热重载
        _persist_sanitized_package(sanitized_pkg, custom_name=custom_name)
        reset_skill_manager()
        manager = get_skill_manager()

        registered_meta = None
        target_id = sanitized_pkg.skill_id if sanitized_pkg.skill_id.startswith("custom_") else f"custom_{sanitized_pkg.skill_id}"
        if target_id in manager.skills:
            registered_meta = manager.skills[target_id]
        else:
            for meta in manager.skills.values():
                if meta.id == sanitized_pkg.skill_id or meta.id == target_id:
                    registered_meta = meta
                    break

        final_skill_name = registered_meta.name if registered_meta else (custom_name or repo)

        return {
            "success": True,
            "message": f"成功从 GitHub 导入技能包「{final_skill_name}」！",
            "skill": {
                "id": registered_meta.id if registered_meta else sanitized_pkg.skill_id,
                "name": final_skill_name,
                "version": registered_meta.version if registered_meta else "1.0.0",
                "is_package": True,
                "references_count": len(sanitized_pkg.references)
            },
            "audit_report": {
                "source": f"{owner}/{repo}",
                "main_entry": sanitized_pkg.main_file_name,
                "references_count": len(sanitized_pkg.references),
                "references": [r["name"] for r in sanitized_pkg.references[:15]],
                "ignored_scripts_count": len(sanitized_pkg.ignored_scripts),
                "ignored_scripts": sanitized_pkg.ignored_scripts[:10],
                "mode_used": sanitized_pkg.mode_used,
                "total_valid_size_kb": round(sanitized_pkg.total_valid_size / 1024, 2)
            }
        }

    except SkillValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(
            content={"success": False, "error": f"GitHub 导入失败: {str(e)}"},
            status_code=500
        )


@router.delete("/{skill_id}")
async def delete_custom_skill(skill_id: str):
    """物理删除自定义技能（支持单文件或多文件目录技能包）"""
    try:
        manager = get_skill_manager()

        if skill_id not in manager.skills:
            raise HTTPException(
                status_code=404,
                detail=f"Skill not found: {skill_id}"
            )

        skill_meta = manager.skills[skill_id]
        if skill_meta.is_official:
            raise HTTPException(
                status_code=400,
                detail="无法删除系统官方内置技能"
            )

        manager.delete_skill(skill_id)

        return {
            "success": True,
            "message": f"自定义技能「{skill_meta.name}」已安全删除"
        }
    except HTTPException:
        raise
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
