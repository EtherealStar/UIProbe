# Observability 与 Error Handling 实施计划

## Purpose

调用方完成一次 UIProbe 测试后，能在本地和个人 Langfuse 中关联查看从启动、模型请求、工具与浏览器动作、独立验收到收尾的完整过程。运行失败时，终端给出具体操作、简明原因和 error_id，完整异常链与堆栈能通过该标识查到。图片只保存在本地，在线导出失败不改变测试结论。

本计划实现已采用的 module 设计；计划存在不代表功能已经实现。执行工作拆为逐票纵向交付，票据草案及验证映射见 [execution](execution.md)。

## Scope

覆盖应用入口、Session、Error Handling、Observability、Recorder，以及 Agent、工具路径、Browser、Verification 的观测与故障接合。保留原有模型循环、严格输入、动作预算、数据引用和验收隔离。

交付范围包括：

- 简洁错误摘要与完整诊断、相同 error_id、本地必要材料写入和准确可用路径。
- 同一根 trace 关联启动、Session 和应用持有资源的关闭，复用框架原生模型／工具追踪。
- 完整文本、原始工具参数与实际结果、框架纠正、预算、时间、可取得的模型用量和错误关联。
- 在线图片排除、本地全部 PNG，以及实际发送视图与完整历史的可回查关系。
- 聚合流式输出、中断时可取得的部分内容及 incomplete 标记。
- 预检拒绝、派发后故障、合法验收结果、预算／取消、本地与在线故障的不同处置。
- 正常、失败和多故障收尾的离线回归，以及真实模型和个人 Langfuse 的演示证据。

不增加脱敏工作流、项目级连接重试、浏览器动作重放、多页面、逐 chunk 重复记录、远端逐条确认、无限补传或断点恢复。既有 MVP 计划缺少的真实模型验收不视为已完成；本计划的演示只按实际证据记录，不修改旧票据状态。

## Design References

- [系统架构与状态所有权](../../design/system-architecture.md#module-与状态所有权)：各 module 不互相接管生命周期。
- [Observability](../../design/modules/observability.md)：逻辑 interface、采集粒度、图片投影、导出与收尾。
- [Error Handling](../../design/modules/error-handling.md)：错误摘要、完整诊断、拒绝与故障传播、主故障保留。
- [共享契约](../../design/contracts.md#提交验收和终态)：SessionError 目标字段与结果语义。
- [Session](../../design/modules/runner.md#结果与错误)：主停止原因、已有结论和有界收尾。
- [Recorder](../../design/modules/recording.md#写入失败与终态)：本地必要材料、写入失败、可用路径。
- [Agent](../../design/modules/agent.md#模型输入与工具反馈)、[Context](../../design/modules/context.md#完整历史与发送视图)：框架循环、纠正和完整／发送消息视图。
- [工具调用](../../design/modules/actions.md#浏览器动作路径)、[Browser](../../design/modules/browser.md#派发与故障)：预检、派发、计数、截图与单页限制。
- [Verification](../../design/modules/verification.md#输出纠正和错误结果)：独立输入、合法失败、不接受部分输出。
- [模型连接](../../design/modules/model.md#请求预算与错误)：SDK 原生重试与共享截止时间。
- [讨论确认记录](../../discussions/errors-and-observability.md#已确认)：需求来源；未采纳提案不自动成为实现要求。

## Context And Orientation

当前已有命令行应用装配、真实 Chromium 动作闭环、独立验收、本地历史与截图。模型默认流式传输，OpenAI SDK 使用原生最多两次连接重试。53 项现有 unittest 在编写本计划时通过，无真实模型调用。

新执行者需要检查这些现有路径：

| 位置 | 当前行为与本计划接合点 |
|---|---|
| `src/uiprobe/__main__.py` | 启动错误缺少底层原因，应用管理模型客户端；根追踪须覆盖 Session 前后 |
| `src/uiprobe/session.py` | SessionError 仅有 phase／code／message，多数异常被泛化；现有取消和五秒收尾需保留 |
| `src/uiprobe/recording.py` | 保存事件、原生历史、PNG 和原子结果；新增诊断／追踪仍由此拥有本地写入 |
| `src/uiprobe/agent.py` | 保存原生完整历史并构造发送视图；未启用全流程 Instrumentation，流聚合适配可能影响部分内容可见性 |
| `src/uiprobe/actions.py`、`src/uiprobe/browser.py` | 已有派发回调与预算接合；错误事件无具体原因，框架前置拒绝可能不经过包装层 |
| `src/uiprobe/verification.py` | 有结构化输出纠正，多类异常被折叠为 unavailable；写入失败单独传播 |
| `tests/` | 已覆盖本地页面、受控模型、生命周期、记录失败与 CLI，新增测试需跨同样的生产 interface |

工作区已有未提交的流式、有窗口模式和设计变更，不清理、不覆盖、不回退它们。本地 tracker 依据此前已确认的惯例沿用逐文件票据，状态词汇为 ready-for-agent；本轮使用独立 feature 目录，发布前先审阅草案。

## Plan Of Work

### M1：初始化失败可完整定位

票据 01 让一个真实失败路径从应用返回、SessionError 到本地诊断贯通：错误摘要包含具体操作与 error_id，可用记录目录内保留原始异常链；无可用目录仍能返回准确内存摘要。共享错误表达按首次使用引入，同时保持所有现有调用可运行，不单独建立只做类型改动的横向票据。

### M2：正常测试的本地与 Langfuse 全链路可查

票据 02 在零动作提交和独立验收路径验证原生追踪及根生命周期；首次启用在线导出即排除图片。票据 03 复用该路径，扩展至计划、点击、引用填写等正常浏览器动作，补齐操作和截图关联。

### M3：故障链可解释且不改变执行策略

在正常追踪接通后，票据 04 覆盖工具拒绝与已派发故障；票据 05 覆盖模型／验收失败和流中断；票据 06 覆盖在线观测不完整及退出导出。三个切片各自拥有可独立复现的失败／恢复场景，不以“新增某个文件”为交付物。

### M4：跨阶段收尾与真实演示验收

票据 07 组合主故障、清理与写入故障，验证超时、取消以及应用持有客户端关闭不会丢失已有结果。票据 08 汇总回归，并用真实模型、真实本地页面与个人 Langfuse 展示完整运行。离线受控导出不等同在线已接入，真实演示未取得时本里程碑保持未完成。

各票实际前置关系见 [execution](execution.md#票据与阻塞关系)。M3 的 05、06 只依赖 02，不为了里程碑编号额外等待正常浏览器动作票据。

## Validation And Acceptance

整个计划完成必须同时满足：

- 初始化导航失败和模型响应无效不再仅返回通用错误；终端摘要、本地诊断和可用在线记录通过相同 error_id 对应。
- 零动作与引用登录的本地、在线追踪包含实际模型输入文本、输出、工具参数／结果、纠正与独立验收；一次调用不重复计量。
- 所有实际 PNG 留在本地；捕获真实待导出载荷证明没有图片字节、图片编码或媒体上传，模型请求仍含所需图片。
- 框架在包装层前拒绝的调用也可查；预检拒绝不计动作，派发后故障计数保留并停止，不重放动作。
- 聚合流输出完整保留，流中断仅留下明确未完成的可取得内容，不形成提交或半份工具执行。
- 合法验收 failed／证据不足 error 不触发返工；验收系统故障保留具体诊断，未有正常 Submission 不验收。
- Langfuse 故障不改变测试结论，SDK 可知的失败与最终 flush 情况单独可查；不宣称远端逐条完整。
- 本地必要写入失败停止新动作，主故障与后续故障不互相覆盖；取消继续传播，已有结论和准确路径保持。
- 现有及新增回归、全部静态检查通过，真实演示证据包含运行标识、本地材料和在线 trace 定位。

精确命令与分批验证在 [execution](execution.md)；已运行的证据只记入 [progress](progress.md)。

## Recovery

执行失败先复现当前票据的可观察场景并修复，不绕过检查、不重置预算、不自动重跑浏览器动作。每个票据应能在现有 suite 上独立保持通过；共享类型变更在首票同时接合必要调用点。

锁定框架不能提供所需追踪或中断内容时，先将实际可见性证据写入 decisions 与 progress；需要改变既定能力或依赖版本时先更新 owning design，再继续。没有 Langfuse／真实模型配置时继续完成离线部分，真实验收保持待执行，不输出凭据或把受控结果标为真实证据。

## Related Documents

- [Execution](execution.md)
- [Decisions](decisions.md)
- [Progress](progress.md)
