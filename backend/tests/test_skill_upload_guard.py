"""Skill 上传防护（覆盖确认 + 数量上限）回归测试。

对应方案：docs/reports/2026-09-19_Skill上传防护方案_覆盖确认与数量上限.md
用户拍板：同 id 重传不得静默覆盖（409→force）；自定义技能上限 20（400）。
"""
import io
import sys
import zipfile as _zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app
from ai_agents.skills.skill_validator import get_safe_skill_id

from ai_agents.skills.skill_upload_policy import (
    CUSTOM_SKILL_CAP,
    check_upload_conflict,
    check_upload_quota,
    count_custom_skills,
    find_existing_skill_path,
    is_content_identical,
)

CONTENT_A = "# 测试技能A\n内容A"
CONTENT_B = "# 测试技能B\n内容B"


def _make_package_dir(skills_base: Path, custom_id: str, main_content: str):
    d = skills_base / custom_id
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(main_content, encoding="utf-8")
    (d / "meta.json").write_text(
        f'{{"id": "{custom_id}", "name": "{custom_id}-显示名", "version": "1.0.0", "is_package": true, "created_at": "2026-01-01T00:00:00"}}',
        encoding="utf-8",
    )
    return d


def _make_single_file(skills_base: Path, custom_id: str, main_content: str):
    p = skills_base / f"{custom_id}.md"
    p.write_text(main_content, encoding="utf-8")
    return p


# ── find_existing_skill_path ───────────────────────────────────────────────

def test_find_existing_dir_and_file_forms(tmp_path):
    _make_package_dir(tmp_path, "custom_pkg", CONTENT_A)
    assert find_existing_skill_path(tmp_path, "custom_pkg") == tmp_path / "custom_pkg"
    _make_single_file(tmp_path, "custom_single", CONTENT_A)
    assert find_existing_skill_path(tmp_path, "custom_single") == tmp_path / "custom_single.md"
    assert find_existing_skill_path(tmp_path, "custom_absent") is None


# ── is_content_identical ───────────────────────────────────────────────────

def test_content_identical_true_false_unreadable(tmp_path):
    d = _make_package_dir(tmp_path, "custom_pkg", CONTENT_A)
    assert is_content_identical(d, CONTENT_A) is True
    assert is_content_identical(d, CONTENT_B) is False
    # 主文件缺失（SKILL.md 被换成目录）→ None 而非抛异常
    (d / "SKILL.md").unlink()
    (d / "SKILL.md").mkdir()
    assert is_content_identical(d, CONTENT_A) is None


# ── check_upload_conflict ──────────────────────────────────────────────────

def test_conflict_none_when_absent(tmp_path):
    assert check_upload_conflict(tmp_path, "custom_new", CONTENT_A) is None


def test_conflict_identical_and_different_messages(tmp_path):
    _make_package_dir(tmp_path, "custom_pkg", CONTENT_A)
    msg_same = check_upload_conflict(tmp_path, "custom_pkg", CONTENT_A)
    assert msg_same and "内容完全相同" in msg_same
    msg_diff = check_upload_conflict(tmp_path, "custom_pkg", CONTENT_B)
    assert msg_diff and "内容不同" in msg_diff and "永久覆盖" in msg_diff


def test_conflict_prefix_normalization(tmp_path):
    """传入 id 不带 custom_ 前缀也能命中（与 _persist 的 resolve 规则一致）"""
    _make_package_dir(tmp_path, "custom_pkg", CONTENT_A)
    assert check_upload_conflict(tmp_path, "pkg", CONTENT_B) is not None


# ── check_upload_quota ─────────────────────────────────────────────────────

def test_quota_allows_under_and_replacement_blocks_at_cap(tmp_path):
    for i in range(CUSTOM_SKILL_CAP - 1):
        _make_single_file(tmp_path, f"custom_s{i}", CONTENT_A)
    # 19 个 < 20：放行
    assert check_upload_quota(tmp_path, "custom_new") is None
    # 第 20 个：达上限拒绝
    _make_single_file(tmp_path, f"custom_s{CUSTOM_SKILL_CAP - 1}", CONTENT_A)
    msg = check_upload_quota(tmp_path, "custom_new")
    assert msg and str(CUSTOM_SKILL_CAP) in msg
    # 但替换已有技能不受限
    assert check_upload_quota(tmp_path, "custom_s0") is None


def test_quota_counts_dirs_and_files_only(tmp_path):
    _make_package_dir(tmp_path, "custom_pkg", CONTENT_A)
    _make_single_file(tmp_path, "custom_single", CONTENT_A)
    (tmp_path / "custom_stale.json").write_text("{}", encoding="utf-8")  # 非 .md 附属不计
    (tmp_path / "resume_rewrite.md").write_text("official", encoding="utf-8")  # 官方不计
    assert count_custom_skills(tmp_path) == 2


# ── 端点级：409 → force 覆盖；配额 400 ─────────────────────────────────────


class _FakeMeta:
    def __init__(self, skill_id: str):
        self.id = skill_id
        self.name = skill_id
        self.version = "1.0.0"


class _FakeManager:
    """SKILLS_DIR 指向 tmp_path 的假 manager：端点内 get_skill_manager 全部命中它"""

    def __init__(self, skills_dir: Path):
        self.SKILLS_DIR = skills_dir
        self.skills = {}
        self.loaded_contents = {}
        self.reference_maps = {}
        self.current_skill_id = None

    def get_default_skill(self):
        return _FakeMeta("resume_rewrite")


@pytest.fixture()
def isolated_skills_dir(tmp_path, monkeypatch):
    fake = _FakeManager(tmp_path)
    import app.api.routes.skills_upload as upload_mod

    monkeypatch.setattr(upload_mod, "get_skill_manager", lambda: fake)
    monkeypatch.setattr(upload_mod, "reset_skill_manager", lambda: None)
    return tmp_path


def _upload_md(client: TestClient, filename: str, content: str, force: bool = False):
    return client.post(
        "/api/resume-editor/skills/upload",
        files={"file": (filename, io.BytesIO(content.encode("utf-8")), "text/markdown")},
        data={"name": filename.replace(".md", ""), "force": "true" if force else "false"},
    )


def test_upload_duplicate_409_then_force_replaces(isolated_skills_dir, tmp_path):
    client = TestClient(app)
    md_name = "测试技能.md"
    # 中文名会被 md5 哈希兜底成 custom_<hash8>（与 custom_skill_db06c78d.json 同机制）
    landed_id = f"custom_{get_safe_skill_id('测试技能')}"

    r1 = _upload_md(client, md_name, CONTENT_A)
    assert r1.status_code == 200, r1.text
    # 目录包 or 单文件形态都已落盘
    assert find_existing_skill_path(tmp_path, landed_id) is not None

    # 同内容重传 → 409 + "内容完全相同"确认语
    r2 = _upload_md(client, md_name, CONTENT_A)
    assert r2.status_code == 409
    assert "内容完全相同" in r2.json()["detail"]

    # 用户确认（force=true）→ 覆盖成功，且不留 .bak 残留
    r3 = _upload_md(client, md_name, CONTENT_A, force=True)
    assert r3.status_code == 200, r3.text
    leftovers = list(tmp_path.glob("**/.bak-*"))  # 匹配 .bak-<id>-<ts> 目录与 .bak-<id>.md-<ts> 文件
    assert leftovers == []

    # 不同内容重传 → 409 提示"内容不同"，force 覆盖后 meta 更新
    r4 = _upload_md(client, md_name, CONTENT_B)
    assert r4.status_code == 409
    assert "内容不同" in r4.json()["detail"]
    r5 = _upload_md(client, md_name, CONTENT_B, force=True)
    assert r5.status_code == 200
    meta = (tmp_path / f"{landed_id}.json").read_text(encoding="utf-8")
    assert "测试技能" in meta


def test_upload_quota_400_blocks_new_but_not_replacement(isolated_skills_dir):
    client = TestClient(app)
    for i in range(CUSTOM_SKILL_CAP):
        (isolated_skills_dir / f"custom_fill{i}.md").write_text(CONTENT_A, encoding="utf-8")

    # 第 21 个新技能 → 400 拒绝；force 也救不了（替换才豁免）
    r_new = _upload_md(client, "brand_new.md", CONTENT_B, force=True)
    assert r_new.status_code == 400
    assert str(CUSTOM_SKILL_CAP) in r_new.json()["detail"]

    # 替换已有技能不受上限约束
    r_replace = _upload_md(client, "fill0.md", CONTENT_B, force=True)
    assert r_replace.status_code == 200, r_replace.text


def test_zip_package_force_replaces_dir_form(isolated_skills_dir):
    """目录包形态：zip 首传 → 重传 409 → force 覆盖成功且旧目录被替换、无 bak 残留"""
    landed_id = f"custom_{get_safe_skill_id('目录包技能')}"
    client = TestClient(app)
    buf = io.BytesIO()
    with _zipfile.ZipFile(buf, "w") as z:
        z.writestr("SKILL.md", CONTENT_A)
        z.writestr("references/extra.md", "附属资料")
    buf.seek(0)

    r1 = client.post(
        "/api/resume-editor/skills/upload",
        files={"file": ("pkg.zip", buf, "application/zip")},
        data={"name": "目录包技能", "mode": "clean"},
    )
    assert r1.status_code == 200, r1.text
    assert (isolated_skills_dir / landed_id / "SKILL.md").exists()

    buf.seek(0)
    r2 = client.post(
        "/api/resume-editor/skills/upload",
        files={"file": ("pkg.zip", buf, "application/zip")},
        data={"name": "目录包技能", "mode": "clean"},
    )
    assert r2.status_code == 409

    buf.seek(0)
    r3 = client.post(
        "/api/resume-editor/skills/upload",
        files={"file": ("pkg.zip", buf, "application/zip")},
        data={"name": "目录包技能", "mode": "clean", "force": "true"},
    )
    assert r3.status_code == 200, r3.text
    assert list(isolated_skills_dir.glob("**/.bak-*")) == []
