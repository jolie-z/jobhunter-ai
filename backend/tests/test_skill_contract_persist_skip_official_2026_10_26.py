"""persist_contract 对内置（官方）技能不落盘（agy plan-review 2026-10-26 round1 P2）：
其 .json 旁车会写进随包分发的内置技能目录（打包态即安装目录，macOS 只读时每次启动告警），
而契约每次由 SKILL.md 重算且有进程内缓存，落盘无收益；自定义技能照常写入 contract 键。
"""

import json
from types import SimpleNamespace

from ai_agents.skills import skill_contract as sc


def test_persist_contract_skips_official_but_writes_custom(tmp_path):
    contract = sc.SkillContract()

    official_md = tmp_path / "resume_rewrite.md"
    official_md.write_text("# 官方\n", encoding="utf-8")
    sc.persist_contract(
        SimpleNamespace(id="resume_rewrite", file_path=official_md, is_package=False, is_official=True), contract
    )
    assert not official_md.with_suffix(".json").exists()

    custom_md = tmp_path / "custom_x.md"
    custom_md.write_text("# 自定义\n", encoding="utf-8")
    sc.persist_contract(SimpleNamespace(id="custom_x", file_path=custom_md, is_package=False, is_official=False), contract)
    assert "contract" in json.loads(custom_md.with_suffix(".json").read_text(encoding="utf-8"))

    pkg_dir = tmp_path / "custom_pkg"
    pkg_dir.mkdir()
    sc.persist_contract(SimpleNamespace(id="custom_pkg", file_path=pkg_dir, is_package=True, is_official=False), contract)
    assert "contract" in json.loads((pkg_dir / "meta.json").read_text(encoding="utf-8"))
