# UIProbe

按[模块设计](docs/design/modules/README.md)实现截图驱动的单条浏览器测试。
当前已实现底层 OpenAI SDK 连接，使用 Chat Completions 接口。

安装依赖，复制配置模板，再填写模型服务的地址、密钥和模型名：

```bash
uv sync
cp .env.exmaple .env
```

`.env.exmaple` 只保存占位配置，实际配置放在已被 Git 忽略的 `.env` 中。
环境变量优先于 `.env`。`OPENAI_TIMEOUT` 为 SDK 请求超时秒数，默认 60。

```python
import asyncio

from uiprobe.model_service import ModelService, ModelServiceConfig


async def main():
    config = ModelServiceConfig.from_env()
    async with ModelService(config) as service:
        response = await service.complete(
            [
                {"role": "user", "content": "请回复：连接成功"},
            ]
        )
        print(response.choices[0].message.content)


asyncio.run(main())
```

`complete()` 接收 SDK 消息（包括图片内容）和可选的 `tools`，返回完整的
`ChatCompletion`，保留文本、工具调用 ID、名称、原始参数、结束原因和用量。
每次调用只发起一轮请求，关闭 SDK 自动重试，工具由上层决定是否执行。
API、连接和超时错误直接使用 SDK 异常。`timeout` 参数可覆盖单次请求超时。
后续 Pydantic AI 接入可以复用 `service.client`。

接口用法参考 [OpenAI Python SDK 官方文档](https://developers.openai.com/api/reference/python)。

运行本地测试（使用模拟 HTTP 服务，无需真实密钥）：

```bash
uv run python -m unittest discover -s tests -v
```

## Static checks

Install the development tools with `uv sync`, then run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

Ruff checks Python code and import order; Pyright checks types in `src/` and
`tests/` using standard mode. Scratch prototypes are outside the check scope.
To format code and sort imports:

```bash
uv run ruff check --select I --fix .
uv run ruff format .
```
