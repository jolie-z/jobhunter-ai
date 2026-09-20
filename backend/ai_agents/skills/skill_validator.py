#!/usr/bin/env python3
"""
Skill Security Validator & Package Sanitizer - 技能包安全校验与纯净提取器
=======================================================================
功能:
1. 纯文本白名单过滤：仅允许 .md, .markdown, .txt, .json, .yaml, .yml
2. 物理拦截/剔除可执行脚本：.py, .sh, .js, .ts, .exe, .bat, .dll 等
3. 压缩包安全防御：防范 Zip Slip 路径穿越、超大解压炸弹 (Zip Bomb)
4. 双模式支持：
   - clean 模式（默认）：自动过滤非文本脚本，安全提取所有 SOP 与 References
   - strict 模式：若发现任何脚本即刻全量拒绝
5. 智能识别主入口：自动锁定 SKILL.md / prompt.md / 主 Markdown 剧本
"""

import os
import re
import zipfile
from io import BytesIO
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field


class SkillValidationError(Exception):
    """技能上传安全验证失败异常"""
    pass


# 🛡️ 纯文本安全扩展名白名单（只允许这些格式入库）
ALLOWED_EXTENSIONS = {'.md', '.markdown', '.txt', '.json', '.yaml', '.yml'}

# 🚫 明确被拦截的脚本与可执行文件后缀
SCRIPT_EXTENSIONS = {
    '.py', '.sh', '.bash', '.zsh', '.js', '.ts', '.jsx', '.tsx',
    '.exe', '.bin', '.bat', '.cmd', '.ps1', '.vbs',
    '.dll', '.so', '.dylib', '.jar', '.wasm', '.php', '.rb',
    '.lua', '.c', '.cpp', '.h', '.go', '.rs', '.java', '.class'
}

# 🚫 禁止的路径与系统目录
FORBIDDEN_DIR_PARTS = {'__pycache__', 'node_modules', '.git', '.github', '.venv', 'venv'}

# ⚙️ 安全阈值
MAX_UNCOMPRESSED_SIZE_BYTES = 15 * 1024 * 1024  # 最大 15MB
MAX_FILE_COUNT = 150  # 最多 150 个文件


@dataclass
class SanitizedSkillPackage:
    """经过安全扫描与纯净提取的 Skill 资源包"""
    skill_id: str
    main_file_name: str
    main_file_content: str
    display_name: str = ""                                          # 用户自定义或提取的显示名称
    references: List[Dict[str, str]] = field(default_factory=list)  # [{"name": "...", "content": "...", "size": ...}]
    ignored_scripts: List[str] = field(default_factory=list)        # 被安全剔除的文件列表
    mode_used: str = "clean"
    total_valid_size: int = 0


def get_safe_skill_id(raw_name: str) -> str:
    """从原始文件名或文件夹名提取安全规范的 skill_id（支持中文名哈希兜底）"""
    base = os.path.splitext(raw_name)[0]
    base = re.sub(r'-(main|master|latest)$', '', base, flags=re.IGNORECASE)
    base = re.sub(r'^(custom_|resume_)', '', base, flags=re.IGNORECASE)
    safe_id = base.lower().replace(' ', '_').replace('-', '_')
    safe_id = re.sub(r'[^a-z0-9_]', '', safe_id).strip('_')
    if not safe_id:
        import hashlib
        h = hashlib.md5(raw_name.encode('utf-8')).hexdigest()[:8]
        safe_id = f"skill_{h}"
    return safe_id


def sanitize_relative_path(raw_path: str) -> Optional[str]:
    """
    清理并规范化相对路径，防御 Zip Slip 路径穿越
    """
    clean_path = raw_path.replace('\\', '/').strip()
    if clean_path.startswith('/'):
        clean_path = clean_path.lstrip('/')
    
    parts = [p for p in clean_path.split('/') if p and p != '.']
    if any(p == '..' for p in parts):
        return None  # 存在路径穿越
    
    # 过滤掉系统内部目录
    if any(p.lower() in FORBIDDEN_DIR_PARTS for p in parts):
        return None
    
    return "/".join(parts)


def validate_and_sanitize_package(
    files_list: List[Tuple[str, bytes]],
    suggested_id: str = "",
    mode: str = "clean"
) -> SanitizedSkillPackage:
    """
    对多文件清单进行安全扫描、白名单过滤与入口智能装配
    
    Args:
        files_list: [(relative_path, content_bytes), ...]
        suggested_id: 建议的技能标识
        mode: "clean"（过滤脚本）或 "strict"（遇脚本即报错）
    """
    if not files_list:
        raise SkillValidationError("上传的文件列表为空。")

    if len(files_list) > MAX_FILE_COUNT:
        raise SkillValidationError(f"文件数量过多（{len(files_list)}），单技能包最多允许包含 {MAX_FILE_COUNT} 个文件。")

    valid_text_files: List[Tuple[str, str]] = []
    ignored_scripts: List[str] = []
    total_size = 0

    for raw_path, content_bytes in files_list:
        clean_path = sanitize_relative_path(raw_path)
        if not clean_path:
            continue
        
        # 忽略空文件或目录标记
        if clean_path.endswith('/') or not content_bytes:
            continue

        ext = os.path.splitext(clean_path)[1].lower()
        file_size = len(content_bytes)
        total_size += file_size

        if total_size > MAX_UNCOMPRESSED_SIZE_BYTES:
            raise SkillValidationError(f"技能包总解压体积超过安全限制（最大 15MB）。")

        # 1. 检查是否为被禁止的脚本/可执行文件
        if ext in SCRIPT_EXTENSIONS or ext not in ALLOWED_EXTENSIONS:
            ignored_scripts.append(clean_path)
            if mode == "strict":
                raise SkillValidationError(
                    f"【安全拦截 (严格模式)】检测到非文本或可执行脚本文件: '{clean_path}' (后缀: {ext})。\n"
                    "JobHunter 仅允许导入纯文本 Markdown/JSON 技能剧本。"
                )
            continue

        # 2. 纯文本 UTF-8 解码与内容检查
        try:
            text = content_bytes.decode('utf-8')
        except UnicodeDecodeError:
            try:
                text = content_bytes.decode('gbk')
            except Exception:
                ignored_scripts.append(f"{clean_path} (非UTF-8二进制)")
                continue

        valid_text_files.append((clean_path, text))

    if not valid_text_files:
        if ignored_scripts:
            raise SkillValidationError(
                f"未能提取到合法的纯文本技能文件。已拦截/忽略的文件: {', '.join(ignored_scripts[:5])}"
            )
        raise SkillValidationError("没有找到任何合法的 Markdown 或文本技能文件。")

    # 3. 智能寻找主入口文件 (Main Entry)
    # 寻找策略优先级:
    # 1) SKILL.md / skill.md (标准 Codex / Claude Code 技能主入口)
    # 2) prompt.md / resume_rewrite.md / SOP.md
    # 3) 根目录下的任意 .md 文件
    # 4) 体积最大的 .md 文件
    main_file_idx = -1
    
    # 优先匹配命名
    for idx, (path, _) in enumerate(valid_text_files):
        fname = os.path.basename(path).lower()
        if fname in {'skill.md', 'prompt.md', 'sop.md', 'resume_rewrite.md', 'main.md'}:
            main_file_idx = idx
            break

    # 次选根目录下的 .md
    if main_file_idx == -1:
        for idx, (path, _) in enumerate(valid_text_files):
            if '/' not in path and path.lower().endswith('.md') and not os.path.basename(path).lower().startswith('readme'):
                main_file_idx = idx
                break

    # 兜底：选第一个或最大的 .md
    if main_file_idx == -1:
        md_indices = [i for i, (p, _) in enumerate(valid_text_files) if p.lower().endswith('.md')]
        if md_indices:
            # 选最长文本作为主剧本
            main_file_idx = max(md_indices, key=lambda i: len(valid_text_files[i][1]))
        else:
            main_file_idx = 0

    main_path, main_content = valid_text_files[main_file_idx]

    # 4. 其余文件全量作为 Reference 参考资料
    references: List[Dict[str, str]] = []
    for idx, (path, text) in enumerate(valid_text_files):
        if idx == main_file_idx:
            continue
        references.append({
            "name": path,
            "content": text,
            "size": len(text)
        })

    # 确定最终 skill_id 与 display_name
    final_id = get_safe_skill_id(suggested_id or os.path.basename(main_path))
    display_name = suggested_id or os.path.splitext(os.path.basename(main_path))[0]

    return SanitizedSkillPackage(
        skill_id=final_id,
        display_name=display_name,
        main_file_name=main_path,
        main_file_content=main_content,
        references=references,
        ignored_scripts=ignored_scripts,
        mode_used=mode,
        total_valid_size=sum(len(t) for _, t in valid_text_files)
    )


def safe_extract_zip_package(
    zip_bytes: bytes,
    suggested_id: str = "",
    mode: str = "clean"
) -> SanitizedSkillPackage:
    """
    安全解压 ZIP 压缩包并执行白名单沙箱审计与智能装配
    """
    raw_files: List[Tuple[str, bytes]] = []

    try:
        with zipfile.ZipFile(BytesIO(zip_bytes), 'r') as z:
            # 第一轮：防解压炸弹与危险检查
            infolist = z.infolist()
            if len(infolist) > MAX_FILE_COUNT:
                raise SkillValidationError(f"压缩包包含文件过多（{len(infolist)}），超过安全限制。")

            uncompressed_sum = sum(info.file_size for info in infolist)
            if uncompressed_sum > MAX_UNCOMPRESSED_SIZE_BYTES:
                raise SkillValidationError(f"压缩包总解压体积（{uncompressed_sum / 1024 / 1024:.1f}MB）超过限制（最大 15MB）。")

            # 剔除 GitHub 打包顶层的单一主目录前缀 (如 LLMInternSkill-main/)
            prefix_to_strip = ""
            names = [info.filename for info in infolist if not info.is_dir()]
            if names and all('/' in n for n in names):
                common_prefix = os.path.commonprefix(names)
                if '/' in common_prefix:
                    prefix_to_strip = common_prefix.rsplit('/', 1)[0] + '/'

            for info in infolist:
                if info.is_dir():
                    continue
                filename = info.filename
                if prefix_to_strip and filename.startswith(prefix_to_strip):
                    filename = filename[len(prefix_to_strip):]
                
                content = z.read(info.filename)
                raw_files.append((filename, content))

    except zipfile.BadZipFile:
        raise SkillValidationError("上传的文件损坏或不是一个合法的 ZIP 压缩包。")
    except Exception as e:
        if isinstance(e, SkillValidationError):
            raise
        raise SkillValidationError(f"解压技能包失败: {str(e)}")

    return validate_and_sanitize_package(raw_files, suggested_id=suggested_id, mode=mode)


def validate_upload_file(file_content: bytes, filename: str = "skill.md") -> Tuple[bool, str]:
    """单文件快捷校验（向后兼容）"""
    try:
        validate_and_sanitize_package([(filename, file_content)], suggested_id=filename, mode="clean")
        return True, ""
    except SkillValidationError as e:
        return False, str(e)
