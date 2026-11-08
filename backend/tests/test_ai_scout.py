import pytest
import asyncio
from unittest.mock import patch, MagicMock

# The module to test
from job_processor.step1_rule_filter import AIScoutEngine

@pytest.mark.asyncio
async def test_ai_scout_engine_must_condition():
    strategy = {
        "ai_scout_rules": [
            {
                "keyword": "双休",
                "condition": "must",
                "desc": "1周休息2天为双休"
            }
        ]
    }
    engine = AIScoutEngine(strategy)
    
    # Mocking the AsyncOpenAI client response
    class MockMessage:
        def __init__(self, content):
            self.content = content
            
    class MockChoice:
        def __init__(self, content):
            self.message = MockMessage(content)
            
    class MockResponse:
        def __init__(self, content):
            self.choices = [MockChoice(content)]

    # Test 1: LLM says it matches (true) -> should PASS because it's "must"
    mock_client1 = MagicMock()
    async def mock_coro1(*args, **kwargs):
        return MockResponse('{"双休": true}')
    mock_client1.chat.completions.create = mock_coro1

    with patch('job_processor.step1_rule_filter.get_cleaner_client', return_value=mock_client1):
        result = await engine.evaluate_job("开发", "提供双休")
        assert result["status"] == "PASS"

    # Test 2: LLM says it DOES NOT match (false) -> should REJECT because it's "must"
    mock_client2 = MagicMock()
    async def mock_coro2(*args, **kwargs):
        return MockResponse('{"双休": false}')
    mock_client2.chat.completions.create = mock_coro2

    with patch('job_processor.step1_rule_filter.get_cleaner_client', return_value=mock_client2):
        result = await engine.evaluate_job("开发", "单休")
        assert result["status"] == "REJECT"
        assert "不满足必须条件 [双休]" in result["reject_reason"]

@pytest.mark.asyncio
async def test_ai_scout_engine_never_condition():
    strategy = {
        "ai_scout_rules": [
            {
                "keyword": "外包",
                "condition": "never",
                "desc": "绝不包含外包"
            }
        ]
    }
    engine = AIScoutEngine(strategy)
    
    class MockMessage:
        def __init__(self, content):
            self.content = content
            
    class MockChoice:
        def __init__(self, content):
            self.message = MockMessage(content)
            
    class MockResponse:
        def __init__(self, content):
            self.choices = [MockChoice(content)]

    # Test 1: LLM says it matches (true) -> should REJECT because it's "never"
    mock_client3 = MagicMock()
    async def mock_coro3(*args, **kwargs):
        return MockResponse('{"外包": true}')
    mock_client3.chat.completions.create = mock_coro3

    with patch('job_processor.step1_rule_filter.get_cleaner_client', return_value=mock_client3):
        result = await engine.evaluate_job("开发", "外包岗")
        assert result["status"] == "REJECT"
        assert "触发绝不条件 [外包]" in result["reject_reason"]

    # Test 2: LLM says it DOES NOT match (false) -> should PASS because it's "never"
    mock_client4 = MagicMock()
    async def mock_coro4(*args, **kwargs):
        return MockResponse('{"外包": false}')
    mock_client4.chat.completions.create = mock_coro4

    with patch('job_processor.step1_rule_filter.get_cleaner_client', return_value=mock_client4):
        result = await engine.evaluate_job("开发", "正式编制")
        assert result["status"] == "PASS"

@pytest.mark.asyncio
async def test_ai_scout_never_condition_appends_jd_quote():
    """死因溯源：never 命中时死因必须带上「触发依据」摘录的 JD 原句。"""
    strategy = {
        "ai_scout_rules": [
            {"keyword": "外包", "condition": "never", "desc": "劳务派遣/外派驻场"}
        ]
    }
    engine = AIScoutEngine(strategy)
    jd_text = "岗位职责：\n1. 负责产品动画制作\n2. 该岗位为劳务派遣用工，需驻场办公\n3. 双休"

    class MockResponse:
        def __init__(self, content):
            self.choices = [MagicMock(message=MagicMock(content=content))]

    # 1. 原句逐字命中 JD -> 标注「JD 原句」
    verbatim_json = (
        '{"外包": true, "触发依据": {"外包": "该岗位为劳务派遣用工，需驻场办公"}}'
    )
    mock_client = MagicMock()
    async def mock_create(*args, **kwargs):
        return MockResponse(verbatim_json)
    mock_client.chat.completions.create = mock_create
    with patch('job_processor.step1_rule_filter.get_cleaner_client', return_value=mock_client):
        result = await engine.evaluate_job("动画师", jd_text)
    assert result["status"] == "REJECT"
    assert "触发绝不条件 [外包]" in result["reject_reason"]
    assert "JD 原句: “该岗位为劳务派遣用工，需驻场办公”" in result["reject_reason"]

    # 2. 摘录与原文不一致 -> 标注「模型转述」（提示人工回 JD 核对）
    paraphrased_json = '{"外包": true, "触发依据": {"外包": "岗位属于派遣性质"}}'
    mock_client2 = MagicMock()
    async def mock_create2(*args, **kwargs):
        return MockResponse(paraphrased_json)
    mock_client2.chat.completions.create = mock_create2
    with patch('job_processor.step1_rule_filter.get_cleaner_client', return_value=mock_client2):
        result2 = await engine.evaluate_job("动画师", jd_text)
    assert result2["status"] == "REJECT"
    assert "JD 依据(模型转述): “岗位属于派遣性质”" in result2["reject_reason"]

    # 3. 模型未返回触发依据（旧格式）-> 死因保持原样，不附加原句
    mock_client3 = MagicMock()
    async def mock_create3(*args, **kwargs):
        return MockResponse('{"外包": true}')
    mock_client3.chat.completions.create = mock_create3
    with patch('job_processor.step1_rule_filter.get_cleaner_client', return_value=mock_client3):
        result3 = await engine.evaluate_job("动画师", jd_text)
    assert result3["status"] == "REJECT"
    assert result3["reject_reason"] == "触发 AI 侦察兵排雷: 触发绝不条件 [外包]"


@pytest.mark.asyncio
async def test_ai_scout_evidence_key_does_not_affect_judgement():
    """「触发依据」只是溯源附件：不得影响布尔判定，也不得把 must 条件误判。"""
    strategy = {
        "ai_scout_rules": [
            {"keyword": "外包", "condition": "never", "desc": "外包"},
            {"keyword": "双休", "condition": "must", "desc": "每周休息两天"},
        ]
    }
    engine = AIScoutEngine(strategy)

    class MockResponse:
        def __init__(self, content):
            self.choices = [MagicMock(message=MagicMock(content=content))]

    # 全部 false + 空触发依据 -> PASS
    mock_client = MagicMock()
    async def mock_create(*args, **kwargs):
        return MockResponse('{"外包": false, "双休": true, "触发依据": {}}')
    mock_client.chat.completions.create = mock_create
    with patch('job_processor.step1_rule_filter.get_cleaner_client', return_value=mock_client):
        result = await engine.evaluate_job("开发", "双休，正式编制")
    assert result["status"] == "PASS"

    # must 未满足：即使模型多给了触发依据对象，死因也保持原句，不附加原句
    mock_client2 = MagicMock()
    async def mock_create2(*args, **kwargs):
        return MockResponse('{"外包": false, "双休": false, "触发依据": {"双休": "无"}}')
    mock_client2.chat.completions.create = mock_create2
    with patch('job_processor.step1_rule_filter.get_cleaner_client', return_value=mock_client2):
        result2 = await engine.evaluate_job("开发", "单休")
    assert result2["status"] == "REJECT"
    assert result2["reject_reason"] == "触发 AI 侦察兵排雷: 不满足必须条件 [双休]"


@pytest.mark.asyncio
async def test_cleaner_model_resolution_and_probe():
    import job_processor.step1_rule_filter as s1
    
    # 1. 默认状态能获取有效清洗模型
    model = s1.get_cleaner_model()
    assert isinstance(model, str) and len(model) > 0
    
    # 2. 外部覆写兼容测试
    s1.LLM_MODEL = "test-custom-model"
    try:
        assert s1.get_cleaner_model() == "test-custom-model"
    finally:
        s1.LLM_MODEL = None

    # 3. 验证 evaluate_job 正确将 model 传递给 chat.completions.create 且探针打印不报错
    strategy = {
        "ai_scout_rules": [{"keyword": "测试", "condition": "must", "desc": "测试"}]
    }
    engine = s1.AIScoutEngine(strategy)
    called_kwargs = {}

    class MockResponse:
        def __init__(self, content):
            self.choices = [MagicMock(message=MagicMock(content=content))]

    mock_client = MagicMock()
    async def mock_create(*args, **kwargs):
        called_kwargs.update(kwargs)
        return MockResponse('{"测试": true}')
    mock_client.chat.completions.create = mock_create

    with patch('job_processor.step1_rule_filter.get_cleaner_client', return_value=mock_client):
        res = await engine.evaluate_job("测试岗位", "测试JD", "测试公司")
        assert res["status"] == "PASS"
        assert called_kwargs.get("model") == model


