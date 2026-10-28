"""Skill 运行 token 预估（历史样本优先 + 启发式兜底）。"""

from __future__ import annotations

import json
import statistics
from typing import Any, Dict, List, Optional


def estimate_skill_run(
    skill_id: str,
    contract: Dict[str, Any],
    main_content: str = "",
    reference_map: Optional[Dict[str, str]] = None,
    jd_chars: int = 0,
    resume_chars: int = 0,
    diagnosis_chars: int = 0,
) -> Dict[str, Any]:
    """预估一次执行的 token 消耗。

    优先用同技能历史运行 meta.json 的 total_tokens；没有历史则用
    “输入字符 × 轮次 + 输出预算”的保守启发式。返回区间，不承诺精确。
    """
    history = _history_tokens(skill_id)
    if history:
        point = int(statistics.median(history))
        return {
            "point": point,
            "low": int(min(history)),
            "high": int(max(history)) if len(history) > 1 else int(point * 1.4),
            "source": "history",
            "sample_count": len(history),
        }

    reference_map = reference_map or {}
    input_chars = (
        len(main_content)
        + sum(len(v) for v in reference_map.values())
        + int(jd_chars)
        + int(resume_chars)
        + int(diagnosis_chars)
    )
    input_tokens = max(1000, int(input_chars / 2))
    expected = int(contract.get("expected_artifact_count") or 1)
    engine = contract.get("engine", "agent")
    turns = max(4, min(16, expected + 3)) if engine == "agent" else 1
    output_tokens = max(1500, expected * 1200)
    point = int(input_tokens * turns + output_tokens)
    return {
        "point": point,
        "low": int(point * 0.6),
        "high": int(point * 1.6),
        "source": "heuristic",
        "sample_count": 0,
    }


def _history_tokens(skill_id: str) -> List[int]:
    try:
        from .skill_dirs import SKILLS_RUNS_DIR, is_safe_segment

        if not is_safe_segment(skill_id) or skill_id.startswith("."):
            return []
        totals: List[int] = []
        for job_dir in SKILLS_RUNS_DIR.iterdir():
            if not job_dir.is_dir():
                continue
            meta_path = job_dir / skill_id / "meta.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                total = (meta.get("token_usage") or {}).get("total_tokens")
                if isinstance(total, (int, float)) and total > 0:
                    totals.append(int(total))
            except Exception:
                continue
        return totals
    except Exception:
        return []
