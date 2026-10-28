"""
测试共享 Fake LLM Client Helper (backend/tests/helpers/fake_llm_gateway.py)

用于模拟 429 限流、鉴权错误、部分重试成功等边界，避免在单测文件中反复堆砌 Mock 代码。
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock
import httpx
import openai


class FakeChoiceMessage:
    def __init__(self, content: str):
        self.content = content


class FakeChoice:
    def __init__(self, content: str, finish_reason: str = "stop"):
        self.message = FakeChoiceMessage(content)
        self.finish_reason = finish_reason


class FakeUsage:
    def __init__(self, prompt_tokens: int = 100, completion_tokens: int = 50, total_tokens: int = 150):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens


class FakeCompletionResponse:
    def __init__(self, content: str, finish_reason: str = "stop"):
        self.choices = [FakeChoice(content, finish_reason)]
        self.usage = FakeUsage()


class FakeChatCompletions:
    def __init__(
        self,
        mode: str = "success",
        fail_count: int = 0,
        retry_after: float | None = None,
        success_content: str | None = None,
    ):
        self.mode = mode
        self.fail_count = fail_count
        self.retry_after = retry_after
        self.success_content = success_content or json.dumps({
            "personal_advantage": "5 年 Python 后端架构与 AI 研发经验",
            "work_experience": [
                {
                    "company": "科技公司",
                    "position": "架构师",
                    "start_date": "2020-01",
                    "end_date": "至今",
                    "description": "负责核心微服务",
                }
            ],
        })
        self.calls: list[dict[str, Any]] = []

    def _make_rate_limit_error(self) -> openai.RateLimitError:
        headers = {}
        if self.retry_after is not None:
            headers["Retry-After"] = str(self.retry_after)
        req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        resp = httpx.Response(429, headers=headers, request=req, text="Rate limit exceeded")
        return openai.RateLimitError("您的账户已达到速率限制 (code 1302)", response=resp, body=None)

    def _make_auth_error(self) -> openai.AuthenticationError:
        req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        resp = httpx.Response(401, request=req, text="Invalid API key")
        return openai.AuthenticationError("API Key 无效或已过期", response=resp, body=None)

    def create(self, *args, **kwargs) -> FakeCompletionResponse:
        call_idx = len(self.calls)
        self.calls.append({"args": args, "kwargs": kwargs})

        if self.mode == "rate_limit":
            raise self._make_rate_limit_error()
        elif self.mode == "auth_error":
            raise self._make_auth_error()
        elif self.mode == "rate_limit_then_success":
            if call_idx < self.fail_count:
                raise self._make_rate_limit_error()
            return FakeCompletionResponse(self.success_content)
        elif self.mode == "invalid_json":
            return FakeCompletionResponse("Not a valid json response")
        else:
            return FakeCompletionResponse(self.success_content)


class FakeLLMClient:
    """可替代 OpenAI client 的轻量级测试类。"""

    def __init__(
        self,
        mode: str = "success",
        fail_count: int = 0,
        retry_after: float | None = None,
        success_content: str | None = None,
    ):
        self.chat = MagicMock()
        self.completions = FakeChatCompletions(
            mode=mode,
            fail_count=fail_count,
            retry_after=retry_after,
            success_content=success_content,
        )
        self.chat.completions = self.completions

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.completions.calls
