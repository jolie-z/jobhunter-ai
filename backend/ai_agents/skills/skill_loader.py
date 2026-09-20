#!/usr/bin/env python3
"""
Dynamic Skill Manager - 动态简历改写技能管理系统
===============================================
功能:
1. 从 backend/ai_agents/skills 目录动态加载单文件 (.md) 与 目录级 Skill 技能包
2. 支持 references/ 附属资料库的自动扫描与运行时 Prompt 深度装配
3. 解析 skill 元数据（name, version, description, references_count 等）
4. 提供 skill 的注册、卸载、切换与物理删除能力
5. 官方内置技能保护（禁止误删官方技能）
"""

import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class SkillMetadata:
    """Skill 元数据"""
    id: str
    name: str
    version: str
    description: str
    file_path: Path
    created_at: datetime
    is_package: bool = False             # 是否为包含 references 的多文件技能包
    references_count: int = 0            # 附属参考资料文件数
    reference_names: List[str] = field(default_factory=list)
    compatible: bool = True              # 是否兼容当前系统
    is_official: bool = False            # 是否为系统官方内置技能


class DynamicSkillManager:
    """动态技能管理器"""
    
    SKILLS_DIR = Path(__file__).parent
    
    def __init__(self):
        self.skills: Dict[str, SkillMetadata] = {}
        self.loaded_contents: Dict[str, str] = {}
        self.reference_maps: Dict[str, Dict[str, str]] = {}  # skill_id -> {rel_path: content}
        self.current_skill_id: Optional[str] = None
        self.load_all_skills()
    
    def load_all_skills(self) -> None:
        """加载 skills 目录下的所有单文件技能与目录技能包"""
        if not self.SKILLS_DIR.exists():
            print(f"⚠️  Skills directory not found: {self.SKILLS_DIR}")
            return
        
        # 1. 扫描单文件技能 (*.md)
        for md_file in self.SKILLS_DIR.glob("*.md"):
            name = md_file.name.lower()
            if name.startswith("resume_") or name.startswith("custom_") or name.startswith("greeting_"):
                try:
                    self.load_single_file_skill(md_file)
                except Exception as e:
                    print(f"❌ Failed to load single skill {md_file.name}: {e}")
        
        # 2. 扫描目录级技能包 (custom_*/ 或包含 SKILL.md 的目录)
        for sub_dir in self.SKILLS_DIR.iterdir():
            if sub_dir.is_dir() and not sub_dir.name.startswith(('.', '__')) and sub_dir.name != "references":
                try:
                    self.load_directory_skill(sub_dir)
                except Exception as e:
                    print(f"❌ Failed to load package skill from {sub_dir.name}: {e}")
    
    def load_single_file_skill(self, file_path: Path) -> SkillMetadata:
        """加载单个 .md 技能文件"""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 优先从同名 .json 读取自定义元数据
        json_meta_path = file_path.with_suffix('.json')
        custom_name = None
        if json_meta_path.exists():
            try:
                import json
                with open(json_meta_path, 'r', encoding='utf-8') as jf:
                    jdata = json.load(jf)
                    custom_name = jdata.get("name")
            except Exception as e:
                print(f"⚠️ Could not read {json_meta_path}: {e}")

        metadata = self._parse_metadata_from_text(content, file_path.stem.lower(), file_path, is_package=False)
        if custom_name:
            metadata.name = custom_name

        self.skills[metadata.id] = metadata
        self.loaded_contents[metadata.id] = content
        self.reference_maps[metadata.id] = {}
        
        print(f"✅ Loaded single skill: {metadata.name} (v{metadata.version}) [{metadata.id}]")
        return metadata
    
    def load_directory_skill(self, dir_path: Path) -> SkillMetadata:
        """加载包含 SKILL.md 与 references/ 的目录级技能包"""
        # 寻找主入口文件
        main_entry = None
        for candidate in ["SKILL.md", "skill.md", "prompt.md", "resume_rewrite.md", "sop.md", "main.md"]:
            p = dir_path / candidate
            if p.exists() and p.is_file():
                main_entry = p
                break
        
        # 如果没有标准命名的入口，寻找根目录下的第一个 .md
        if not main_entry:
            root_mds = [p for p in dir_path.glob("*.md") if not p.name.lower().startswith("readme")]
            if root_mds:
                main_entry = root_mds[0]
            else:
                all_mds = list(dir_path.rglob("*.md"))
                if all_mds:
                    main_entry = all_mds[0]

        if not main_entry:
            raise ValueError(f"Directory {dir_path.name} does not contain any valid .md entry point.")

        with open(main_entry, 'r', encoding='utf-8') as f:
            main_content = f.read()

        # 收集所有附属 reference 文件 (纯文本)
        ref_map: Dict[str, str] = {}
        for ext in ["*.md", "*.markdown", "*.txt", "*.json", "*.yaml", "*.yml"]:
            for ref_file in dir_path.rglob(ext):
                if ref_file.resolve() == main_entry.resolve() or ref_file.name == "meta.json":
                    continue
                try:
                    rel_name = str(ref_file.relative_to(dir_path))
                    with open(ref_file, 'r', encoding='utf-8') as rf:
                        ref_map[rel_name] = rf.read()
                except Exception as e:
                    print(f"⚠️ Could not read reference file {ref_file}: {e}")

        # 优先从 meta.json 加载自定义元数据
        meta_json_path = dir_path / "meta.json"
        custom_name = None
        if meta_json_path.exists():
            try:
                import json
                with open(meta_json_path, 'r', encoding='utf-8') as mf:
                    mdata = json.load(mf)
                    custom_name = mdata.get("name")
            except Exception as e:
                print(f"⚠️ Could not read meta.json in {dir_path}: {e}")

        raw_id = dir_path.name.lower()
        metadata = self._parse_metadata_from_text(
            main_content,
            raw_id,
            dir_path,
            is_package=True,
            references=list(ref_map.keys())
        )
        if custom_name:
            metadata.name = custom_name
        
        self.skills[metadata.id] = metadata
        self.loaded_contents[metadata.id] = main_content
        self.reference_maps[metadata.id] = ref_map
        
        print(f"📦 Loaded package skill: {metadata.name} (v{metadata.version}) [{metadata.id}] with {len(ref_map)} references")
        return metadata

    def _parse_metadata_from_text(
        self,
        content: str,
        suggested_id: str,
        file_path: Path,
        is_package: bool = False,
        references: List[str] = None
    ) -> SkillMetadata:
        """从内容中解析元数据"""
        # 从文件名/目录名清洗出 skill_id
        skill_id = suggested_id.replace(' ', '_').replace('-', '_')
        
        # 尝试从 # 标题提取名称
        title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        skill_name = title_match.group(1).strip() if title_match else file_path.stem
        
        # 版本号（默认 1.0.0）
        version_match = re.search(r'version[:\s]+(\d+\.\d+\.\d+)', content, re.IGNORECASE)
        version = version_match.group(1) if version_match else "1.0.0"
        
        # 描述提取
        lines = content.split('\n')
        description = ""
        for line in lines[1:]:
            s = line.strip()
            if s and not s.startswith('#') and not s.lower().startswith('version:'):
                description = s
                break
        
        # 官方/自定义判定只看 id 前缀与「相对 SKILLS_DIR 的路径」——绝不能用绝对路径
        # 子串匹配：worktree 目录名（如 qa-custom-panel）含 "custom" 会把全部官方技能
        # 误判为自定义，导致官方剧本在详情弹窗里挂出删除按钮。
        try:
            rel_path = file_path.relative_to(self.SKILLS_DIR).as_posix().lower()
        except ValueError:
            rel_path = file_path.name.lower()
        is_official = not (skill_id.startswith("custom_") or rel_path.startswith("custom"))

        return SkillMetadata(
            id=skill_id,
            name=skill_name,
            version=version,
            description=description or "自定义求职改写技能剧本",
            file_path=file_path,
            created_at=datetime.now(),
            is_package=is_package,
            references_count=len(references or []),
            reference_names=references or [],
            compatible=True,
            is_official=is_official
        )
    
    def get_skill_content(self, skill_id: str, max_ref_total_chars: int = 50000) -> Optional[str]:
        """
        获取指定 skill 的完整 Prompt 上下文（含 References 自动智能拼装）
        自动控制参考资料容量上限，优先装配规则/边界/核心方法论文档，避免大模型超长耗尽输出Token。
        """
        main_content = self.loaded_contents.get(skill_id)
        if not main_content:
            return None
        
        ref_map = self.reference_maps.get(skill_id, {})
        if not ref_map:
            return main_content
        
        # 📚 深度装配：排序，优先核心规范与边界文件
        def _score_key(name: str) -> int:
            nl = name.lower()
            if any(k in nl for k in ["truth", "boundary", "真实", "边界", "rule", "规则", "sop", "01", "02", "03"]):
                return 0
            if any(k in nl for k in ["guide", "verb", "ats", "rubric", "score", "standard"]):
                return 1
            return 2

        sorted_refs = sorted(ref_map.items(), key=lambda x: (_score_key(x[0]), x[0]))

        assembled_parts = [main_content.strip(), "\n\n---\n## 📚 附属参考资料与行业边界规范 (References & Knowledge Base)\n"]
        current_len = 0

        for rel_name, ref_text in sorted_refs:
            clean_text = ref_text.strip()
            # 单个文件若过长（如题库长篇），截取前 3500 字符保留精华
            if len(clean_text) > 3500:
                clean_text = clean_text[:3500] + "\n...(篇幅过长，已自动截取核心规则)..."
            
            chunk = f"\n### 📄 参考资料: {rel_name}\n```markdown\n{clean_text}\n```\n"
            if current_len + len(chunk) > max_ref_total_chars:
                assembled_parts.append(f"\n> 💡 已载入核心参考规范集（共 {len(sorted_refs)} 篇中的核心高杠杆资料已装配完成）。\n")
                break
            
            assembled_parts.append(chunk)
            current_len += len(chunk)
        
        return "".join(assembled_parts)

    def delete_skill(self, skill_id: str) -> bool:
        """物理删除 skill（支持单文件或多文件目录包）"""
        if skill_id not in self.skills:
            raise ValueError(f"Skill not found: {skill_id}")
        
        meta = self.skills[skill_id]
        if meta.is_official:
            raise PermissionError(f"无法删除系统官方内置技能：{meta.name}")
        
        target_path = meta.file_path
        try:
            if target_path.is_dir():
                shutil.rmtree(target_path)
                print(f"🗑️  Skill package directory deleted: {target_path}")
            elif target_path.is_file():
                os.remove(target_path)
                print(f"🗑️  Skill single file deleted: {target_path}")
            
            # 从内存中彻底注销
            if skill_id in self.skills:
                del self.skills[skill_id]
            if skill_id in self.loaded_contents:
                del self.loaded_contents[skill_id]
            if skill_id in self.reference_maps:
                del self.reference_maps[skill_id]
            
            return True
        except Exception as e:
            print(f"❌ Failed to delete skill {skill_id}: {e}")
            raise e

    def list_skills(self) -> List[Dict]:
        """列出所有可用 skill"""
        return [
            {
                "id": meta.id,
                "name": meta.name,
                "version": meta.version,
                "description": meta.description,
                "file": meta.file_path.name,
                "is_package": meta.is_package,
                "references_count": meta.references_count,
                "reference_names": meta.reference_names,
                "is_official": meta.is_official,
                "compatible": meta.compatible
            }
            for meta in self.skills.values()
        ]

    def unload_skill(self, skill_id: str) -> bool:
        """从内存注销指定技能"""
        if skill_id in self.skills:
            del self.skills[skill_id]
            self.loaded_contents.pop(skill_id, None)
            self.reference_maps.pop(skill_id, None)
            print(f"🗑️  Unloaded skill from memory: {skill_id}")
            return True
        return False

    def get_default_skill(self) -> Optional[SkillMetadata]:
        """获取默认 skill"""
        for skill_id in self.skills:
            if "rewrite" in skill_id and "resume" in skill_id:
                return self.skills[skill_id]
        return next(iter(self.skills.values()), None)


# 全局实例
_skill_manager: Optional[DynamicSkillManager] = None


def get_skill_manager() -> DynamicSkillManager:
    """获取全局 skill manager 实例"""
    global _skill_manager
    if _skill_manager is None:
        _skill_manager = DynamicSkillManager()
    return _skill_manager


def reset_skill_manager() -> None:
    """重置全局实例"""
    global _skill_manager
    _skill_manager = None
