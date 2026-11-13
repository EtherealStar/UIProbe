# UIProbe 单条用例执行设计

Label: wayfinder:map

## Destination

形成可交给开发者实施的单条用例设计，说明模块之间传递的数据、运行和停止条件、断言与结果记录，用一条用例走通输入到报告的过程。

交付文档见 [UIProbe 单条用例 Agent 设计](spec.md)。

## Notes

用例以 JSON 输入，Agent 提取目标并逐步规划。浏览器使用 Playwright SDK，模型框架使用 Pydantic AI，模型连接使用 OpenAI SDK。支持 DOM 断言及独立 VLM 截图断言，也支持组合使用。本地保留 JSON、JSONL 和 PNG，通过 OpenTelemetry 向 Langfuse 上报运行链路。讨论遵循 wayfinder、grilling 和 domain-modeling。

## Decisions so far

- [用例如何表达业务预期](issues/01-case-input.md) — 采用已有用例字段，Agent 将业务步骤展开为操作，并保留原始预期用于验收。
- [规划器每一步能看到什么](issues/02-page-observation.md) — 每次动作后追加截图，执行 Agent 按最新截图返回像素坐标，程序换算并点击。
- [两种断言如何给出用例结论](issues/04-verdict.md) — 独立 VLM 按原始预期验收截图，程序按需配置 DOM 检查，所有必选断言通过才判定用例通过。
- [谁控制每次动作和运行终止](issues/03-step-loop.md) — 每轮一步，执行 Agent 请求验收，程序负责校验和预算，超限仍无结论时记为执行错误。
- [入口地址和测试数据由谁提供](issues/06-case-context.md) — 运行程序提供入口和账号，模型用引用名请求输入。
- [如何从运行记录复盘一次测试](issues/05-run-record.md) — 本地保存完整证据，Langfuse 通过 OTLP/HTTP 接收可关联的调用链。

## Not yet specified

当前范围的决策均已记录。首轮实现可采用交付文档中的接口草案。

## Out of scope

本轮讨论限于单条用例；批量调度和多用例并发留待后续。
