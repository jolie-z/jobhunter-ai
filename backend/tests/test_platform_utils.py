import pytest
from app.core.utils import (
    GREETING_SUPPORTED_PLATFORMS,
    normalize_platform_code,
    is_greeting_supported_platform,
)


def test_normalize_platform_code_cases():
    # 51job variants
    assert normalize_platform_code("51job") == "51job"
    assert normalize_platform_code("51Job") == "51job"
    assert normalize_platform_code("前程无忧") == "51job"
    assert normalize_platform_code("  前程  ") == "51job"
    assert normalize_platform_code("JOB51") == "51job"

    # BOSS variants
    assert normalize_platform_code("boss") == "boss"
    assert normalize_platform_code("BOSS直聘") == "boss"
    assert normalize_platform_code("Boss") == "boss"

    # Zhilian variants
    assert normalize_platform_code("zhilian") == "zhilian"
    assert normalize_platform_code("智联招聘") == "zhilian"
    assert normalize_platform_code("智联") == "zhilian"

    # Liepin variants
    assert normalize_platform_code("liepin") == "liepin"
    assert normalize_platform_code("猎聘") == "liepin"
    assert normalize_platform_code("猎聘网") == "liepin"

    # Null / empty / unknown
    assert normalize_platform_code(None) == ""
    assert normalize_platform_code("") == ""
    assert normalize_platform_code("   ") == ""
    assert normalize_platform_code("unknown_platform") == "unknown_platform"


def test_is_greeting_supported_platform():
    # Supported platforms (True)
    assert is_greeting_supported_platform("boss") is True
    assert is_greeting_supported_platform("BOSS直聘") is True
    assert is_greeting_supported_platform("zhilian") is True
    assert is_greeting_supported_platform("智联招聘") is True
    assert is_greeting_supported_platform("liepin") is True
    assert is_greeting_supported_platform("猎聘") is True

    # Unsupported platforms (False)
    assert is_greeting_supported_platform("51job") is False
    assert is_greeting_supported_platform("前程无忧") is False
    assert is_greeting_supported_platform("51Job") is False
    assert is_greeting_supported_platform("unknown") is False
    assert is_greeting_supported_platform("") is False
    assert is_greeting_supported_platform(None) is False
