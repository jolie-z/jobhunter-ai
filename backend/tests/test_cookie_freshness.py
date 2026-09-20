"""inspect_profile_cookie_freshness 单测：offline 时 profile cookie 存活概况。"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.session.browser import inspect_profile_cookie_freshness  # noqa: E402
from app.session.models import PlatformConfig  # noqa: E402


def _chrome_epoch(dt: datetime) -> int:
    return int((dt - datetime(1601, 1, 1)).total_seconds() * 1_000_000)


@pytest.fixture
def fake_profile(tmp_path):
    """造一个带 Cookies 库的假 profile（Default/Cookies），返回 profile 根目录。"""
    profile_root = tmp_path / "fake_profile"
    default_dir = profile_root / "Default"
    default_dir.mkdir(parents=True)
    conn = sqlite3.connect(default_dir / "Cookies")
    conn.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, expires_utc INTEGER)")
    yield profile_root, conn
    conn.close()


def _mk_cfg(profile_dir: str) -> PlatformConfig:
    return PlatformConfig(
        name="fake",
        display_name="假平台",
        browser_type="drissionpage",
        profile_dir=profile_dir,
        port=19999,
        login_check_url="https://we.fakejob.com/",
    )


def test_valid_cookies_reported_with_soonest_expiry(fake_profile):
    profile_root, conn = fake_profile
    soon = datetime.now() + timedelta(days=3)
    late = datetime.now() + timedelta(days=200)
    conn.execute("INSERT INTO cookies VALUES ('.fakejob.com', 'a', ?)", (_chrome_epoch(soon),))
    conn.execute("INSERT INTO cookies VALUES ('.fakejob.com', 'b', ?)", (_chrome_epoch(late),))
    conn.commit()

    res = inspect_profile_cookie_freshness(_mk_cfg(str(profile_root)))
    assert res["state"] == "valid"
    assert res["valid_count"] == 2
    assert res["expires_at"] == soon.strftime("%Y-%m-%d")


def test_expired_cookies_reported_expired(fake_profile):
    profile_root, conn = fake_profile
    past = datetime.now() - timedelta(days=1)
    conn.execute("INSERT INTO cookies VALUES ('.fakejob.com', 'a', ?)", (_chrome_epoch(past),))
    conn.commit()

    res = inspect_profile_cookie_freshness(_mk_cfg(str(profile_root)))
    assert res["state"] == "expired"
    assert res["expires_at"] is None


def test_missing_profile_is_unknown(tmp_path):
    cfg = _mk_cfg(str(tmp_path / "no_such_profile"))
    res = inspect_profile_cookie_freshness(cfg)
    assert res == {"state": "unknown", "expires_at": None, "valid_count": 0}


def test_domain_filter_excludes_other_platforms(fake_profile):
    profile_root, conn = fake_profile
    late = datetime.now() + timedelta(days=100)
    # 别的平台的 cookie 不应计入
    conn.execute("INSERT INTO cookies VALUES ('.other.com', 'x', ?)", (_chrome_epoch(late),))
    conn.commit()

    res = inspect_profile_cookie_freshness(_mk_cfg(str(profile_root)))
    # 只有 other.com 的 cookie → fakejob 域无行 → unknown（有行但全过期 → expired；
    # 此处压根没有 fakejob 行）
    assert res["state"] in ("unknown", "expired")
    assert res["valid_count"] == 0
