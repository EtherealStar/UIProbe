"""兼容 OpenAI 接口的底层模型连接。

SDK 响应和异常原样向上传递。Agent 上下文、动作校验和浏览器派发由上层负责。
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from os import environ
from pathlib import Path
from types import TracebackType

from dotenv import dotenv_values
from openai import AsyncOpenAI, omit
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessageParam,
    ChatCompletionToolUnionParam,
)


@dataclass(frozen=True)
class ModelServiceConfig:
    base_url: str
    api_key: str = field(repr=False)
    model: str
    timeout: float = 60.0

    @classmethod
    def from_env(cls, path: str | Path = ".env") -> "ModelServiceConfig":
        """读取 dotenv 文件，已有环境变量优先于文件中的配置。"""
        values = {**dotenv_values(path, interpolate=False), **environ}

        def required(name: str) -> str:
            value = values.get(name)
            if value is None or not value.strip():
                raise ValueError(f"{name} is required")
            return value.strip()

        return cls(
            base_url=required("OPENAI_BASE_URL"),
            api_key=required("OPENAI_API_KEY"),
            model=required("OPENAI_MODEL"),
            timeout=float(values.get("OPENAI_TIMEOUT", "60")),
        )


class ModelService:
    """持有一个 SDK 客户端，每次 complete() 发起一次非流式请求。"""

    def __init__(self, config: ModelServiceConfig) -> None:
        self.config = config
        # 公开客户端，供后续 Pydantic AI 接入时复用连接。
        self.client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
            timeout=config.timeout,
            max_retries=0,
        )

    async def complete(
        self,
        messages: Iterable[ChatCompletionMessageParam],
        *,
        tools: Iterable[ChatCompletionToolUnionParam] | None = None,
        timeout: float | None = None,
    ) -> ChatCompletion:
        """返回完整 SDK 响应，保留所有工具调用的原始参数。

        单次调用的超时参数覆盖配置中的请求超时。SDK 异常直接向上传递，
        本层不执行响应中的工具调用。
        """
        return await self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            tools=tools if tools is not None else omit,
            timeout=self.config.timeout if timeout is None else timeout,
            stream=False,
        )

    async def close(self) -> None:
        await self.client.close()

    async def __aenter__(self) -> "ModelService":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()
