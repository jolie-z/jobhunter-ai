"""自定义 Skill 输出契约扫描与 token 预估。

目标：不再把“11 份产物 + 06 简历主稿”写死在执行器里，而是从技能包
（SKILL.md / meta.json）推断输出契约：

- outputs：预计会产出哪些文件（通常 md，也支持 json/txt）；
- final_artifact：哪个文件是最终交付物；
- output_kind：resume / markdown / json；
- postprocess：resume_json（解析写回简历） / markdown_only（只归档）；
- writeback：resume_or_job / none；
- expected_artifact_count：预期产物数（用于部分成功 N/M）。

扫描结果会写回技能包 meta.json 的 `contract` 字段；没有显式清单时给
保守的通用 markdown 契约，绝不阻止用户执行（token 是用户自己的）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("skill_contract")

OFFICIAL_RESUME_IDS = {"", "resume_rewrite", "default"}
_OFFICIAL_CONTRACT = {
    "engine": "official",
    "output_kind": "resume",
    "final_artifact": "06_targeted_resume.md",
    "postprocess": "resume_json",
    "writeback": "resume_or_job",
    "outputs": [
        {
            "filename": "06_targeted_resume.md",
            "title": "最终定制简历",
            "required": True,
            "is_final": True,
            "kind": "markdown",
            "is_resume": True,
        }
    ],
    "expected_artifact_count": 1,
    "has_resume_output": True,
    "resume_output_files": ["06_targeted_resume.md"],
    "output_count_source": "official",
    "final_source": "official",
    "warnings": [],
    "scan_version": 1,
}

_FILENAME_RE = re.compile(
    r"(?<![\w./-])((?:[\w\u4e00-\u9fff.-]+/)*[\w\u4e00-\u9fff.-]+\.(?:md|markdown|json|txt|csv|ya?ml))",
    re.IGNORECASE,
)
_OUTPUT_HEADING_RE = re.compile(
    r"(?im)^#{1,6}\s*(?:output files?|outputs?|deliverables?|产出|输出文件|交付物|交付文件|最终产物|产物清单)\b.*$"
)
_ANY_HEADING_RE = re.compile(r"(?m)^#{1,6}\s+")

_IGNORED_NAMES = {
    "skill.md", "readme.md", "readme_en.md", "meta.json", "package.json",
    "requirements.txt", "license", "license.md", ".gitignore", "agents.md",
}
_INPUT_PATH_MARKERS = (
    "references/", "skill-references/", "templates/", "materials/",
    "examples/", "docs/", "agents/", "scripts/", "assets/", "node_modules/",
)
_RESUME_NAME_MARKERS = (
    "resume", "cv", "简历", "targeted_resume", "polished_resume", "定制简历", "求职简历",
)
_RESUME_SKILL_MARKERS = (
    "resume", "cv", "简历", "tailor", "job application", "求职", "定制简历",
)
_FINAL_NAME_MARKERS = ("final", "最终", "总览", "交付", "summary", "report")

_CONTRACT_CACHE: Dict[tuple, Dict[str, Any]] = {}


@dataclass
class SkillOutputSpec:
    filename: str
    title: str = ""
    required: bool = True
    is_final: bool = False
    kind: str = "markdown"
    is_resume: bool = False

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "title": self.title,
            "required": self.required,
            "is_final": self.is_final,
            "kind": self.kind,
            "is_resume": self.is_resume,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SkillOutputSpec":
        return cls(
            filename=str(data.get("filename") or ""),
            title=str(data.get("title") or ""),
            required=bool(data.get("required", True)),
            is_final=bool(data.get("is_final", False)),
            kind=str(data.get("kind") or "markdown"),
            is_resume=bool(data.get("is_resume", False)),
        )


@dataclass
class SkillContract:
    engine: str = "agent"
    output_kind: str = "markdown"
    final_artifact: Optional[str] = None
    postprocess: str = "markdown_only"
    writeback: str = "none"
    outputs: List[SkillOutputSpec] = field(default_factory=list)
    expected_artifact_count: int = 0
    has_resume_output: bool = False
    resume_output_files: List[str] = field(default_factory=list)
    output_count_source: str = "unknown"
    final_source: str = "unknown"
    content_hash: str = ""
    warnings: List[str] = field(default_factory=list)
    scan_version: int = 1

    def to_dict(self) -> dict:
        return {
            "engine": self.engine,
            "output_kind": self.output_kind,
            "final_artifact": self.final_artifact,
            "postprocess": self.postprocess,
            "writeback": self.writeback,
            "outputs": [o.to_dict() for o in self.outputs],
            "expected_artifact_count": self.expected_artifact_count,
            "has_resume_output": self.has_resume_output,
            "resume_output_files": list(self.resume_output_files),
            "output_count_source": self.output_count_source,
            "final_source": self.final_source,
            "content_hash": self.content_hash,
            "warnings": list(self.warnings),
            "scan_version": self.scan_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SkillContract":
        return cls(
            engine=str(data.get("engine") or "agent"),
            output_kind=str(data.get("output_kind") or "markdown"),
            final_artifact=data.get("final_artifact") or None,
            postprocess=str(data.get("postprocess") or "markdown_only"),
            writeback=str(data.get("writeback") or "none"),
            outputs=[SkillOutputSpec.from_dict(x) for x in (data.get("outputs") or [])],
            expected_artifact_count=int(data.get("expected_artifact_count") or 0),
            has_resume_output=bool(data.get("has_resume_output", False)),
            resume_output_files=list(data.get("resume_output_files") or []),
            output_count_source=str(data.get("output_count_source") or "unknown"),
            final_source=str(data.get("final_source") or "unknown"),
            content_hash=str(data.get("content_hash") or ""),
            warnings=list(data.get("warnings") or []),
            scan_version=int(data.get("scan_version") or 1),
        )


def _kind_for(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".json"):
        return "json"
    if lower.endswith((".md", ".markdown")):
        return "markdown"
    return "text"


def _is_resume_name(filename: str, title: str = "") -> bool:
    haystack = f"{filename} {title}".lower()
    return any(marker in haystack for marker in _RESUME_NAME_MARKERS)


def _looks_like_resume_skill(skill_id: str, name: str, description: str, main_content: str) -> bool:
    haystack = f"{skill_id} {name} {description} {main_content[:5000]}".lower()
    return any(marker in haystack for marker in _RESUME_SKILL_MARKERS)


def _is_output_candidate(path: str) -> bool:
    raw = (path or "").strip().strip("`'\"")
    low = raw.replace("\\", "/").lower()
    if not low:
        return False
    if Path(low).name in _IGNORED_NAMES:
        return False
    if any(marker in low for marker in _INPUT_PATH_MARKERS):
        return False
    if "/" in low and not low.startswith("output/"):
        return False
    return True


def _normalize_output_name(path: str) -> str:
    clean = (path or "").strip().strip("`'\"").replace("\\", "/")
    if clean.lower().startswith("output/"):
        clean = clean[len("output/"):]
    return clean.split("/")[-1]


def _extract_title(line: str, filename: str) -> str:
    text = line.strip()
    text = re.sub(r"^[\s>*\-、)）├└│─]+", "", text)
    text = re.sub(r"^\d+[.、)）]\s*", "", text)
    text = text.replace("`", "")
    paren = re.search(r"[（(]([^）)]+)[）)]", text)
    if paren:
        return paren.group(1).strip()
    text = text.replace(filename, "")
    text = re.sub(r"^[\s：:=\-—]+|[\s：:=\-—]+$", "", text)
    return text[:80]


def _output_sections(main_content: str) -> List[str]:
    matches = list(_OUTPUT_HEADING_RE.finditer(main_content))
    sections: List[str] = []
    for match in matches:
        start = match.end()
        next_heading = _ANY_HEADING_RE.search(main_content, start)
        end = next_heading.start() if next_heading else len(main_content)
        sections.append(main_content[start:end])
    return sections


def _collect_outputs(text: str, require_hint: bool = False) -> List[SkillOutputSpec]:
    found: Dict[str, SkillOutputSpec] = {}
    for line in text.splitlines():
        for match in _FILENAME_RE.finditer(line):
            raw = match.group(1)
            if not _is_output_candidate(raw):
                continue
            raw_low = raw.replace("\\", "/").lower()
            line_low = line.lower()
            if require_hint and not (
                raw_low.startswith("output/")
                or re.match(r"^\d{2}[_-]", Path(raw_low).name)
                or any(marker in raw_low for marker in ("final", "output", "report", "deliverable"))
                or any(marker in line_low for marker in ("save", "write", "create", "output", "保存", "输出", "生成", "写入", "交付"))
            ):
                continue
            filename = _normalize_output_name(raw)
            if not filename:
                continue
            key = filename.lower()
            if key in found:
                continue
            title = _extract_title(line, raw)
            found[key] = SkillOutputSpec(
                filename=filename,
                title=title,
                kind=_kind_for(filename),
                is_resume=_is_resume_name(filename, title),
            )
    return list(found.values())


def _infer_outputs_from_whole_doc(main_content: str) -> List[SkillOutputSpec]:
    """没有显式 Output Files 段时的保守推断。

    只接受 output/ 路径、两位编号文件（01_xxx.md）或名称含 final/output/report
    的文件；避免把 Inputs 段里的 resume.md / notes.md 误当产物。
    """
    return _collect_outputs(main_content, require_hint=True)


def scan_skill_contract(
    skill_id: str,
    main_content: str,
    reference_map: Optional[Dict[str, str]] = None,
    *,
    name: str = "",
    description: str = "",
    is_package: bool = False,
    references_count: int = 0,
) -> SkillContract:
    """扫描 SKILL.md，生成输出契约。找不到清单时返回通用 markdown 契约。"""
    reference_map = reference_map or {}
    warnings: List[str] = []

    sections = _output_sections(main_content)
    outputs: List[SkillOutputSpec] = []
    source = "unknown"
    if sections:
        for section in sections:
            outputs.extend(_collect_outputs(section))
        if outputs:
            source = "skill_md"
    if not outputs:
        outputs = _infer_outputs_from_whole_doc(main_content)
        if outputs:
            source = "inferred"

    # 去重（按文件名）并保留顺序
    deduped: Dict[str, SkillOutputSpec] = {}
    for item in outputs:
        deduped.setdefault(item.filename.lower(), item)
    outputs = list(deduped.values())

    resume_skill = _looks_like_resume_skill(skill_id, name, description, main_content)
    resume_files = [o.filename for o in outputs if o.is_resume]
    has_resume_output = bool(resume_files)
    # 有显式产物清单时以清单为准：列表里没有简历文件，就按通用 skill 处理，
    # 避免“求职信里提到 resume”被误判成简历改写、写坏简历库。
    if resume_skill and not has_resume_output and not outputs:
        has_resume_output = True
        warnings.append("未识别到明确的产物清单，但技能内容看起来与简历相关，已按简历类技能处理。")

    if has_resume_output:
        output_kind = "resume"
    elif outputs and all(o.kind == "json" for o in outputs):
        output_kind = "json"
    else:
        output_kind = "markdown"

    final_artifact: Optional[str] = None
    final_source = "unknown"
    if outputs:
        if has_resume_output:
            canonical = next(
                (o for o in outputs if o.filename.lower() == "06_targeted_resume.md"),
                None,
            )
            final_spec = canonical or next(
                (o for o in reversed(outputs) if o.is_resume), None
            )
            final_source = "explicit_06" if canonical else "resume_output"
        else:
            marked = next(
                (
                    o for o in outputs
                    if any(marker in f"{o.filename} {o.title}".lower() for marker in _FINAL_NAME_MARKERS)
                ),
                None,
            )
            final_spec = marked or (outputs[-1] if outputs else None)
            final_source = "final_marker" if marked else "inferred_last"
        if final_spec:
            final_artifact = final_spec.filename
            final_spec.is_final = True
            if final_source == "inferred_last":
                warnings.append(
                    f"最终产物按启发式选择 `{final_artifact}`；模型可用 is_final_resume=True 覆盖。"
                )
    else:
        warnings.append("未在 SKILL.md 中识别到明确的产物清单，执行时将按 SKILL.md 与模型自报的最终产物处理。")

    if output_kind != "resume":
        warnings.append("未检测到简历改写产物；执行结果将只归档到产物库，不会写回简历库。")

    expected_count = len([o for o in outputs if o.required]) if outputs else 0
    output_count_source = source

    if skill_id in OFFICIAL_RESUME_IDS:
        engine = "official"
    elif is_package and references_count > 0:
        engine = "agent"
    elif output_kind != "resume":
        # 单文件但明显不是简历改写：也交给渐进式 agent，避免被官方简历引擎误处理
        engine = "agent"
    else:
        engine = "official"

    postprocess = "resume_json" if output_kind == "resume" else "markdown_only"
    writeback = "resume_or_job" if output_kind == "resume" else "none"

    return SkillContract(
        engine=engine,
        output_kind=output_kind,
        final_artifact=final_artifact,
        postprocess=postprocess,
        writeback=writeback,
        outputs=outputs,
        expected_artifact_count=expected_count,
        has_resume_output=has_resume_output,
        resume_output_files=resume_files,
        output_count_source=output_count_source,
        final_source=final_source,
        content_hash=hashlib.md5(main_content.encode("utf-8")).hexdigest(),
        warnings=warnings,
    )


def _meta_json_path(meta: Any) -> Optional[Path]:
    file_path = Path(getattr(meta, "file_path"))
    if getattr(meta, "is_package", False):
        return file_path / "meta.json"
    return file_path.with_suffix(".json")


def persist_contract(meta: Any, contract: SkillContract) -> None:
    """把契约写回技能包 meta.json；失败只记日志，不影响执行。

    内置（官方）技能不落盘：其 .json 旁车会写进随包分发的内置技能目录（打包态即安装目录，
    macOS 只读时每次启动告警），而契约每次由 SKILL.md 重算且有进程内缓存，落盘无收益。"""
    if getattr(meta, "is_official", False):
        return
    path = _meta_json_path(meta)
    if not path:
        return
    try:
        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    data = {}
            except Exception:
                data = {}
        data["contract"] = contract.to_dict()
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"持久化 Skill 契约失败 ({path}): {e}")


def _cache_key(meta: Any) -> tuple:
    return (
        getattr(meta, "id", ""),
        str(getattr(meta, "file_path", "")),
        int(getattr(meta, "references_count", 0) or 0),
        str(getattr(meta, "version", "")),
    )


def reset_contract_cache() -> None:
    _CONTRACT_CACHE.clear()


def get_skill_contract(skill_id: str) -> Dict[str, Any]:
    """获取技能输出契约（缓存 + 首次扫描并持久化）。返回 dict 便于跨模块传递。"""
    if skill_id in OFFICIAL_RESUME_IDS:
        return dict(_OFFICIAL_CONTRACT)

    try:
        from .skill_loader import get_skill_manager

        manager = get_skill_manager()
        meta = manager.skills.get(skill_id)
        if not meta:
            return dict(_OFFICIAL_CONTRACT)

        main_content = manager.loaded_contents.get(skill_id, "")
        content_hash = hashlib.md5(main_content.encode("utf-8")).hexdigest()
        key = _cache_key(meta) + (content_hash,)
        if key in _CONTRACT_CACHE:
            return dict(_CONTRACT_CACHE[key])

        cached = getattr(meta, "contract", None)
        cached_hash = str(cached.get("content_hash") or "") if isinstance(cached, dict) else ""
        if (
            isinstance(cached, dict)
            and cached.get("outputs") is not None
            and cached_hash == content_hash
        ):
            contract = SkillContract.from_dict(cached)
        else:
            contract = scan_skill_contract(
                skill_id=meta.id,
                main_content=main_content,
                reference_map=manager.reference_maps.get(skill_id, {}),
                name=meta.name,
                description=meta.description,
                is_package=meta.is_package,
                references_count=meta.references_count,
            )
            try:
                meta.contract = contract.to_dict()
            except Exception:
                pass
            if not getattr(meta, "is_official", False):
                persist_contract(meta, contract)

        result = contract.to_dict()
        _CONTRACT_CACHE[key] = result
        return dict(result)
    except Exception as e:
        logger.warning(f"扫描 Skill 契约失败，回退官方简历契约: {e}")
        return dict(_OFFICIAL_CONTRACT)


def contract_summary(contract: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "engine": contract.get("engine", "official"),
        "output_kind": contract.get("output_kind", "resume"),
        "expected_output_count": contract.get("expected_artifact_count", 0),
        "has_resume_output": bool(contract.get("has_resume_output", False)),
        "final_artifact": contract.get("final_artifact"),
        "postprocess": contract.get("postprocess", "resume_json"),
        "final_source": contract.get("final_source", "unknown"),
    }


from .skill_contract_estimate import estimate_skill_run  # noqa: E402,F401  (re-export)
