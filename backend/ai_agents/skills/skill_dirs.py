#!/usr/bin/env python3
"""
Skill Run Directory Manager - 技能运行结果目录管理器

功能:
1. 为每次 skill 执行创建独立的目录结构
2. 支持多文件保存
3. 自动保存元数据 (token、时间、文件清单)
"""

from pathlib import Path
from typing import List, Dict, Optional
import json
from datetime import datetime


# 根目录：backend/data/skill_runs
SKILLS_RUNS_DIR = Path(__file__).parent.parent / "data" / "skill_runs"


def ensure_base_dir() -> Path:
    """确保基础目录存在"""
    SKILLS_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    return SKILLS_RUNS_DIR


def is_safe_segment(part: str) -> bool:
    """路径段安全校验：拒绝空串、./..、路径分隔符与盘符，防止目录穿越。

    公开 API：产物 router 等外部模块的 fail-closed 校验也依赖此函数，
    重命名或改动实现前请同步调用方。"""
    if not part or part in (".", ".."):
        return False
    return "/" not in part and "\\" not in part and ":" not in part


# 兼容别名：历史内部调用沿用下划线名
_is_safe_segment = is_safe_segment


def get_skill_run_dir(job_record_id: str, skill_id: str) -> Path:
    """
    获取或创建某次 skill 运行的完整路径

    Args:
        job_record_id: 岗位记录的 record_id（飞书表）
        skill_id: 技能的唯一 ID

    Returns:
        完整的目录路径，如:
        backend/data/skill_runs/appXXXXXXXXXXX/llm-intern-skill/
    """
    if not _is_safe_segment(job_record_id) or not _is_safe_segment(skill_id):
        raise ValueError(f"非法路径参数: job_record_id={job_record_id!r}, skill_id={skill_id!r}")

    job_dir = SKILLS_RUNS_DIR / job_record_id

    # 如果 job 目录不存在，创建它
    if not job_dir.exists():
        job_dir.mkdir(parents=True)

    # 返回 skill 子目录路径（不立即创建，等保存时再创建）
    return job_dir / skill_id


def save_skill_result(
    job_record_id: str,
    skill_id: str,
    files: List[Dict],  # [{"name": "01_xxx.md", "content": "..."}]
    token_usage: Dict[str, int],  # {"prompt_tokens": 1000, "completion_tokens": 500}
    output_type: str = "multi_markdown"  # single/markdown | multi_markdown | json
) -> Dict:
    """
    保存 skill 执行结果到文件系统
    
    Args:
        job_record_id: 岗位记录 ID
        skill_id: 技能 ID
        files: 文件列表，每个文件有 name 和 content
        token_usage: token 使用统计
        output_type: 输出类型
    
    Returns:
        {
            "success": True,
            "dir_path": "/path/to/skill/run/dir",
            "files_saved": [...],
            "meta": {...}
        }
    """
    
    # 确保基础目录存在
    ensure_base_dir()
    
    # 获取目标目录
    skill_dir = get_skill_run_dir(job_record_id, skill_id)
    skill_dir.mkdir(parents=True, exist_ok=True)
    
    saved_files = []
    
    # 保存所有文件
    for file in files:
        file_path = skill_dir / file["name"]
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(file["content"])
        
        saved_files.append({
            "name": file["name"],
            "size": len(file["content"]),
            "path": str(file_path.relative_to(SKILLS_RUNS_DIR))
        })
        print(f"  📄 Saved: {file['name']} ({len(file['content'])} bytes)")
    
    # 构建元数据
    meta = {
        "job_record_id": job_record_id,
        "skill_id": skill_id,
        "executed_at": datetime.now().isoformat(),
        "token_usage": token_usage,
        "output_type": output_type,
        "file_count": len(files),
        "files": saved_files
    }
    
    # 保存元数据
    meta_file_path = skill_dir / "meta.json"
    with open(meta_file_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ Skill result saved to: {skill_dir}")
    print(f"   Files: {len(saved_files)}")
    print(f"   Tokens: {sum(token_usage.values())}")
    
    return {
        "success": True,
        "dir_path": str(skill_dir),
        "files_saved": saved_files,
        "meta": meta
    }


def load_latest_result(job_record_id: str, skill_id: str) -> Optional[Dict]:
    """
    加载指定 job+skill 的最新执行结果
    
    Returns:
        None or {
            "files": [...],
            "meta": {...},
            "dir_path": "..."
        }
    """
    skill_dir = get_skill_run_dir(job_record_id, skill_id)
    
    if not skill_dir.exists():
        return None
    
    # 读取 meta.json
    meta_path = skill_dir / "meta.json"
    if not meta_path.exists():
        return None
    
    with open(meta_path, 'r', encoding='utf-8') as f:
        meta = json.load(f)
    
    # 读取所有 md 文件
    files = []
    for file_meta in meta.get("files", []):
        file_path = skill_dir / file_meta["name"]
        if file_path.exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            files.append({
                "name": file_meta["name"],
                "content": content
            })
    
    return {
        "files": files,
        "meta": meta,
        "dir_path": str(skill_dir)
    }


def get_storage_stats() -> Dict:
    """
    获取存储空间使用情况
    
    Returns:
        {
            "total_jobs": 0,
            "total_storage_mb": 0,
            "jobs": [
                {"job_id": "...", "count": 0, "size_mb": 0}
            ]
        }
    """
    ensure_base_dir()
    
    total_storage_bytes = 0
    jobs = []
    
    if not SKILLS_RUNS_DIR.exists():
        return {
            "total_jobs": 0,
            "total_storage_mb": 0,
            "jobs": []
        }
    
    for job_dir in SKILLS_RUNS_DIR.iterdir():
        if job_dir.is_dir():
            job_size = sum(f.stat().st_size for f in job_dir.rglob("*") if f.is_file())
            total_storage_bytes += job_size
            
            jobs.append({
                "job_id": job_dir.name,
                "size_mb": round(job_size / (1024 * 1024), 2)
            })
    
    return {
        "total_jobs": len(jobs),
        "total_storage_mb": round(total_storage_bytes / (1024 * 1024), 2),
        "jobs": sorted(jobs, key=lambda x: x["size_mb"], reverse=True)[:10]  # Top 10
    }


def extract_files_from_skill_output(markdown_content: str) -> List[Dict[str, str]]:
    """
    智能拆解 Skill 输出的 Markdown：
    如果包含多阶段产物（如 ## 1. 岗位诊断 / ## 2. 真实性边界 / ## 6. 定制简历），自动切分为多份独立的 .md 文件
    """
    import re
    if not markdown_content or not markdown_content.strip():
        return [{"name": "06_targeted_resume.md", "content": ""}]

    # 检查是否包含多级章节（形如 ## 1. 或 ## 一、 或 ## [Step 1] 或 --- \n ## 等）
    pattern = re.compile(r'(?m)^##\s+(\d+[\.\、\:\s]|Step\s*\d+[\:\s]|第[一二三四五六七八九十]+[部分步节][\:\s]|JD|真实性|面试|简历|ATS|匹配点|毒点|诊断).*$')
    matches = list(pattern.finditer(markdown_content))

    if len(matches) < 2:
        # 单篇完整文档
        return [{"name": "06_targeted_resume.md", "content": markdown_content}]

    files: List[Dict[str, str]] = []
    # 00: 完整总报告
    files.append({
        "name": "00_全套作战研报总汇.md",
        "content": markdown_content
    })

    for idx, match in enumerate(matches):
        header_line = match.group(0).strip()
        start_pos = match.start()
        end_pos = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown_content)
        section_text = markdown_content[start_pos:end_pos].strip()

        # 生成规范文件名
        clean_title = re.sub(r'^##\s*', '', header_line)
        clean_title = re.sub(r'[\\/*?:"<>|]', '_', clean_title).strip()
        filename = f"{idx+1:02d}_{clean_title[:30]}.md"

        files.append({
            "name": filename,
            "content": f"# {clean_title}\n\n{section_text}"
        })

    return files


def is_resume_filename(filename: str) -> bool:
    """智能判断文件名是否为简历候选主稿"""
    name_lower = filename.lower()
    keywords = ["resume", "cv", "简历", "targeted_resume", "06_", "final_resume", "polished_resume", "定制简历", "精修"]
    return any(kw in name_lower for kw in keywords)


def list_job_skill_artifacts(job_record_id: str, skill_id: Optional[str] = None) -> List[Dict]:
    """
    列出指定 job 下所有 skill 的多产物文件清单
    
    Args:
        job_record_id: 岗位记录 ID
        skill_id: 可选，指定 skill_id 过滤；为空时扫描该岗位下的所有 skill
        
    Returns:
        文件元数据列表，按文件名或执行时间排序
    """
    ensure_base_dir()
    if not _is_safe_segment(job_record_id):
        return []
    job_dir = SKILLS_RUNS_DIR / job_record_id
    if not job_dir.exists() or not job_dir.is_dir():
        return []

    artifacts = []
    skill_dirs_to_scan = [job_dir / skill_id] if (skill_id and (job_dir / skill_id).exists()) else [d for d in job_dir.iterdir() if d.is_dir()]

    for s_dir in skill_dirs_to_scan:
        current_skill_id = s_dir.name
        meta_file = s_dir / "meta.json"
        executed_at = ""
        if meta_file.exists():
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                    executed_at = meta.get("executed_at", "")
            except Exception:
                pass

        for md_file in sorted(s_dir.glob("*.md")):
            try:
                content = md_file.read_text(encoding="utf-8")
                preview = content[:200].replace("\n", " ")
                artifacts.append({
                    "skill_id": current_skill_id,
                    "name": md_file.name,
                    "size": md_file.stat().st_size,
                    "is_resume_candidate": is_resume_filename(md_file.name),
                    "executed_at": executed_at,
                    "preview": preview,
                    "path": str(md_file.relative_to(SKILLS_RUNS_DIR))
                })
            except Exception as e:
                print(f"⚠️ Error reading artifact {md_file}: {e}")

    # 排序：推荐简历置顶，其余按文件名升序排列
    artifacts.sort(key=lambda x: (not x["is_resume_candidate"], x["name"]))
    return artifacts


def get_artifact_content(job_record_id: str, skill_id: str, filename: str) -> Optional[str]:
    """
    安全读取指定产物 Markdown 内容
    """
    # 路径安全检查，防止目录遍历（filename 与 job/skill 路径段都要防）
    if ".." in filename or "/" in filename or "\\" in filename:
        return None
    if not _is_safe_segment(job_record_id) or not _is_safe_segment(skill_id):
        return None
    file_path = SKILLS_RUNS_DIR / job_record_id / skill_id / filename
    if not file_path.exists() or not file_path.is_file():
        return None
    try:
        return file_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"❌ Failed to read artifact content {file_path}: {e}")
        return None


def delete_job_results(job_record_id: str) -> bool:
    """
    删除某个岗位的所有技能运行结果

    Args:
        job_record_id: 岗位记录 ID

    Returns:
        True if deleted successfully, False otherwise
    """
    if not _is_safe_segment(job_record_id):
        return False
    job_dir = SKILLS_RUNS_DIR / job_record_id

    if not job_dir.exists():
        return False
    
    try:
        import shutil
        shutil.rmtree(job_dir)
        print(f"🗑️  Deleted job results: {job_record_id}")
        return True
    except Exception as e:
        print(f"❌ Failed to delete {job_record_id}: {e}")
        return False


def delete_skill_result(job_record_id: str, skill_id: str) -> bool:
    """
    删除某个岗位下指定技能的所有运行产物
    """
    if not _is_safe_segment(job_record_id) or not _is_safe_segment(skill_id):
        return False
    skill_dir = SKILLS_RUNS_DIR / job_record_id / skill_id
    if not skill_dir.exists():
        return False
    try:
        import shutil
        shutil.rmtree(skill_dir)
        print(f"🗑️  Deleted skill results: {job_record_id}/{skill_id}")
        return True
    except Exception as e:
        print(f"❌ Failed to delete skill {skill_id}: {e}")
        return False


def delete_single_artifact(job_record_id: str, skill_id: str, filename: str) -> bool:
    """
    删除单个产物文件并更新 meta.json
    """
    if ".." in filename or "/" in filename or "\\" in filename:
        return False
    if not _is_safe_segment(job_record_id) or not _is_safe_segment(skill_id):
        return False
    file_path = SKILLS_RUNS_DIR / job_record_id / skill_id / filename
    if not file_path.exists() or not file_path.is_file():
        return False
    try:
        file_path.unlink()
        # 更新 meta.json
        meta_file = SKILLS_RUNS_DIR / job_record_id / skill_id / "meta.json"
        if meta_file.exists():
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                meta["files"] = [f for f in meta.get("files", []) if f.get("name") != filename]
                meta["file_count"] = len(meta["files"])
                with open(meta_file, 'w', encoding='utf-8') as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        print(f"🗑️  Deleted single artifact: {job_record_id}/{skill_id}/{filename}")
        return True
    except Exception as e:
        print(f"❌ Failed to delete single artifact {filename}: {e}")
        return False


if __name__ == "__main__":
    # 测试代码
    test_result = save_skill_result(
        job_record_id="test-job-001",
        skill_id="test-skill",
        files=[
            {"name": "01_test.md", "content": "# Test\nThis is a test file.\n"},
            {"name": "02_results.md", "content": "# Results\nMore content here.\n"}
        ],
        token_usage={
            "prompt_tokens": 1000,
            "completion_tokens": 500,
            "total_tokens": 1500
        },
        output_type="single_markdown"
    )
    
    print("\n" + "="*60)
    print("Result:", test_result)
    
    print("\nLoading latest result:")
    latest = load_latest_result("test-job-001", "test-skill")
    if latest:
        print(f"Files: {len(latest['files'])}")
        print(f"Meta: {latest['meta']}")
