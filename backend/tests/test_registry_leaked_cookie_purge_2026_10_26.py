"""历史安装包误带入的构建机猎聘 cookie 端侧清理回归（2026-10-26，agy double-check 第 1 轮 P1）。

事故：0.3.2~0.3.5 安装包携带构建机 liepin_cookies.json，get_liepin_cookie_file() 的 legacy
迁移把它复制进了用户数据目录并被 liepin_session/liepin_crawler 作为会话凭证加载。

回归口径：
  1. 打包态：用户数据目录中与泄漏哈希一致的文件 → 删除；用户自己的 cookie（哈希不同）→ 保留；
  2. 打包态：程序目录 anchor 命中泄漏哈希 → 拒绝迁移，不创建 target；
  3. 开发态（target == anchor，开发者本人文件）→ 即便哈希命中也绝不删除。
"""

import hashlib
import os

import app.session.registry as registry

LEAKED_CONTENT = b'[{"name": "leaked", "value": "x"}]'
USER_CONTENT = b'[{"name": "mine", "value": "y"}]'


def _hash(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _packaged(monkeypatch, tmp_path):
    """模拟打包态：anchor 在 tmp 的假 backend 根，JOBHUNTER_DATA_DIR 指向独立用户数据目录。"""
    backend_root = tmp_path / "resources" / "backend"
    (backend_root / "liepin_scraper").mkdir(parents=True)
    data_dir = tmp_path / "userData"
    monkeypatch.setattr(registry, "_BACKEND_ROOT", str(backend_root))
    monkeypatch.setenv("JOBHUNTER_DATA_DIR", str(data_dir))
    monkeypatch.setattr(registry, "_LEAKED_LIEPIN_COOKIE_SHA256", frozenset({_hash(LEAKED_CONTENT)}))
    return backend_root / "liepin_scraper" / "liepin_cookies.json", data_dir / "liepin_cookies.json"


def test_packaged_purges_leaked_copy_in_user_data(monkeypatch, tmp_path):
    _anchor, target = _packaged(monkeypatch, tmp_path)
    target.parent.mkdir(parents=True)
    target.write_bytes(LEAKED_CONTENT)

    assert registry.get_liepin_cookie_file() == str(target)
    assert not target.exists()


def test_packaged_keeps_users_own_cookie(monkeypatch, tmp_path):
    _anchor, target = _packaged(monkeypatch, tmp_path)
    target.parent.mkdir(parents=True)
    target.write_bytes(USER_CONTENT)

    registry.get_liepin_cookie_file()
    assert target.read_bytes() == USER_CONTENT


def test_packaged_refuses_to_migrate_leaked_anchor(monkeypatch, tmp_path):
    anchor, target = _packaged(monkeypatch, tmp_path)
    anchor.write_bytes(LEAKED_CONTENT)

    registry.get_liepin_cookie_file()
    assert not target.exists()


def test_packaged_still_migrates_genuine_legacy_cookie(monkeypatch, tmp_path):
    anchor, target = _packaged(monkeypatch, tmp_path)
    anchor.write_bytes(USER_CONTENT)

    registry.get_liepin_cookie_file()
    assert target.read_bytes() == USER_CONTENT


def test_dev_mode_never_deletes_developers_own_file(monkeypatch, tmp_path):
    backend_root = tmp_path / "backend"
    anchor = backend_root / "liepin_scraper" / "liepin_cookies.json"
    anchor.parent.mkdir(parents=True)
    anchor.write_bytes(LEAKED_CONTENT)
    monkeypatch.setattr(registry, "_BACKEND_ROOT", str(backend_root))
    monkeypatch.delenv("JOBHUNTER_DATA_DIR", raising=False)
    monkeypatch.setattr(registry, "_LEAKED_LIEPIN_COOKIE_SHA256", frozenset({_hash(LEAKED_CONTENT)}))

    assert registry.get_liepin_cookie_file() == str(anchor)
    assert anchor.read_bytes() == LEAKED_CONTENT


def test_real_leaked_hash_matches_bundled_file_if_present():
    """构建机上若存在历史 bundled 文件，其哈希必须在清单内（防止清单与实际泄漏文件脱节）。"""
    bundled = os.path.join(registry._BACKEND_ROOT, "liepin_scraper", "liepin_cookies.json")
    if not os.path.exists(bundled):
        return
    with open(bundled, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    # 本机文件可能已被开发者重新登录刷新；只在它仍是历史泄漏内容时断言
    if digest == "17bc181bfbc2adf63e16c722430e41d0cd60cb13d650b3f26d1ca8b3dce16f89":
        assert digest in registry._LEAKED_LIEPIN_COOKIE_SHA256
