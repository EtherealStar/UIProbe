# UIProbe

按[模块设计](docs/design/modules/README.md)实现截图驱动的单条浏览器测试。
已提供浏览器测试命令行、独立视觉验收与本地产物；模型使用 Chat Completions 接口。

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

## 运行浏览器测试

安装依赖与 Chromium，复制 .env.exmaple 为 .env，填写支持图片与工具调用的模型配置：

~~~bash
uv sync --locked
uv run --locked python -m playwright install chromium
cp .env.exmaple .env
~~~

在一个终端启动演示页：

~~~bash
uv run --locked python -m http.server 8765 --bind 127.0.0.1 --directory login-demo
~~~

在另一个终端从仓库根目录执行：

~~~bash
uv run --locked python -m uiprobe --help
uv run --locked python -m uiprobe --case login-demo/mvp-case.json --config login-demo/mvp-config.json
uv run --locked python -m uiprobe --case login-demo/mvp-initial-case.json --config login-demo/mvp-config.json
~~~

登录用例使用 username／password 数据引用。初图用例直接提交，预期 action_count=0。旧 test-cases.json 不用于该入口。
运行配置包含页面、引用值、预算、时限和输出目录；执行与验收共用连接，历史独立。
标准输出为 SessionResult JSON；passed／failed／error 对应退出码 0／1／2。
缺少模型配置时返回安全错误且不启动浏览器；外部取消经清理后传播。
每次运行在 .scratch/uiprobe-mvp/runs 下创建独立目录，保存 events.jsonl、history.json、verification.json、screenshots/ 和 result.json。artifact_paths 列出可用产物，断言关联最终截图。
真实模型验收状态见 [执行进度](docs/exec-plans/uiprobe-mvp/progress.md)。离线回归不调用真实模型：

~~~bash
uv run --locked python -m unittest discover -s tests -p 'test_mvp_e2e.py' -v
~~~

运行追踪默认保存到同一产物目录的 trace.json；每次实际模型发送视图保存到 execution-requests.jsonl 和 verification-requests.jsonl。图片引用 screenshots/ 中的 PNG，在线不上传图片。配置 LANGFUSE_BASE_URL、LANGFUSE_PUBLIC_KEY、LANGFUSE_SECRET_KEY 可启用 Langfuse OTLP 导出；在线不可用不会改变验收判断。退出提交等待最多 2.5 秒，flush 完成不表示远端逐条确认。


模型或浏览器故障可通过摘要的 error_id 查找 `diagnostics/<error_id>.json`；工具纠正保存在事件和完整历史中，不直接改变测试结论。流中断的可见部分标记 incomplete，只用于诊断。
在线观测的独立诊断位于 trace.json 的 observability_diagnostics；observability_incomplete 表示已有告警。export 的批次成功／失败数与 flush 分别表达 SDK 可知情况；flush completed 仍可能伴随导出失败，remote_delivery 始终为 unknown。未提供 Langfuse 配置时只记录本地，部分配置缺失则报告观测告警。
