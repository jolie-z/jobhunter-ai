"""回归守卫：Copilot / 面试入口必须走统一情报调度器。

只配置 BOCHA_API_KEY（国内直连）时，这两个入口如果仍直连 Serper 会抛
SERPER_NOT_CONFIGURED，与配置页「博查覆盖面试 Copilot / 面试前调研」的文案矛盾。
用 AST 静态检查导入名，避免为此拉起 copilot/interview 的重依赖。
"""
import ast
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _imported_names(relative_path: str) -> set[str]:
    tree = ast.parse((_BACKEND_ROOT / relative_path).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def test_copilot_and_interview_use_unified_intel_dispatcher():
    for relative_path in ("app/copilot/service.py", "app/interview/service.py"):
        names = _imported_names(relative_path)
        assert "fetch_company_intel" in names, f"{relative_path} 未接入统一情报调度器"
        assert "search_company_ai_news" not in names, (
            f"{relative_path} 仍直连 Serper；只配置 BOCHA_API_KEY 时该入口会失效"
        )
