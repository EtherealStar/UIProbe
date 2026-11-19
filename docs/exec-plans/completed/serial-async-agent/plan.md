# 串行批次与异步检查点 Agent 演进计划

## Purpose

调用方使用同一命令提交一个 Case 或有序批次；Case 之间串行，每条 Case 内执行 Agent 在同一原生循环中逐段读取检查点、提交冻结截图，并继续后续操作。独立验收与执行重叠，结果用于最终报告。调用方最终取得包含非法项、未运行项和所有检查点事实的 SuiteResult，以及可关联的本地证据和一份批次追踪。

本计划落实当前模块设计，不修改架构。计划已编写不表示功能已实现；实施状态与验证证据见 [progress](progress.md)。

## Scope

覆盖输入准备、SuiteRunner、Session、Agent／Context、工具调用、Browser 生命周期、Verification、Recorder、模型资源所有权、Observability 和 Error Handling 的迁移。保留现有浏览器预检、原生模型循环、默认流式传输、SDK 连接重试、引用值隔离及在线图片排除。

交付包括新检查点输入和默认配置／Case 覆盖、整批预检、顺序调度、逐段公开、显式提交、冻结证据、有界异步验收、按层预算、结果合成、主动记录故障通知、取消快照交接及批次资源收尾。单 Case 同样进入 SuiteRunner；CLI 保持 --case、--config、--headed，标准输出迁移为 SuiteResult，退出码保持 0／1／2。

不增加 Case 并发、批次共享验收池、旧输入兼容、验收驱动返工、断点恢复、动作重放、来源插件框架、第二套消息协议、独立总结循环或角色配置产品功能。个人 Langfuse 的真实在线验收沿用旧计划的待办，本计划用受控真实 OTLP 出口验证新归属及图片排除，不把该待办作为本次演进的前置条件。

## Design References

- [系统架构](../../../design/system-architecture.md)：串行批次、异步检查点和状态所有权。
- [共享契约](../../../design/contracts.md)：输入、提交、阶段、预算、状态及结果合成的唯一字段来源。
- [模块索引](../../../design/modules/README.md)、[输入准备](../../../design/modules/case-input.md)、[SuiteRunner](../../../../src/uiprobe/suite_runner.py)：整批准备、条目顺序、配置覆盖和批次生命周期。
- [Session](../../../design/modules/runner.md)：提交成立、验收协调、执行退出后的页面释放及取消交接。
- [Agent](../../../design/modules/agent.md)、[Context](../../../design/modules/context.md)、[工具调用](../../../design/modules/actions.md)、[具体工具](../../../design/modules/tools.md)：一次循环、逐段公开、响应屏障和工具可用性。
- [Browser](../../../design/modules/browser.md)、[Verification](../../../design/modules/verification.md)：已有动作接合、冻结截图及独立输出校验。
- [Recorder](../../../design/modules/recording.md)、[Observability](../../../design/modules/observability.md)、[运行追踪接合](../../../design/modules/observability-runtime.md)：提交专属材料、固定追踪关联和一批一份 trace。
- [Error Handling](../../../design/modules/error-handling.md)、[模型连接](../../../design/modules/model.md)：故障所属层级、取消控制流和共享连接关闭。
- [MVP 进度](../../uiprobe-mvp/progress.md)、[观测与错误处理进度](../../observability-error-handling/progress.md)：现有实现与历史证据。旧计划的验收状态不由本计划补记。

## Context And Orientation

2026-11-15 的工作区已具备单 Case 的真实 Chromium 动作、终态独立验收、完整历史、发送视图、诊断和在线导出隔离。基线实际运行 76 项 unittest 全部通过。模块设计已经升级，代码尚未迁移：

| 位置 | 当前实现与迁移接合 |
|---|---|
| `src/uiprobe/case_input.py` | TestCase 仍为顶层 execution／assertions，prepare 返回 PreparedSession；需支持完整输入准备和 PreparedCase |
| `src/uiprobe/session.py` | run 接收原始 JSON／配置，等待最终文本后单次验收；需只接收合法 PreparedCase 并拥有检查点账本与任务 |
| `src/uiprobe/observation.py`、`src/uiprobe/error_handling.py` | Submission.text、单 Verdict、SessionError；按首次用途迁移为目标契约，不保留第二套长期类型 |
| `src/uiprobe/agent.py` | Context 持有完整 TestCase，初始 prompt 全量发送；需只持有已公开阶段并返回 ExecutionOutcome |
| `src/uiprobe/actions.py` | 已有原生串行包装与动作派发计数；需提交能力、响应屏障和按能力禁用工具 |
| `src/uiprobe/verification.py`、`src/uiprobe/recording.py` | 验收接收完整 Case，材料存于固定单槽；需冻结输入和提交专属句柄 |
| `src/uiprobe/observability.py` | 当前根 scope 绑定单个 record，最后绑定可覆盖归属；需固定子作用域和批次唯一 trace |
| `src/uiprobe/__main__.py` | 应用关闭客户端后改写 SessionResult；需注入创建能力，让 SuiteRunner 完成资源与结果收尾 |
| `tests/`、`login-demo/`、`README.md` | 回归及样例仍基于旧输入／单终态；随所属切片迁移，保留已有行为断言 |

SuiteRunner 尚无生产实现，计划新增 `src/uiprobe/suite_runner.py`；不要求按设计页数量创建源文件。术语以正式契约为准，旧 GLOSSARY 中“Agent 提取执行目标”的表述不约束本次实现。已有未提交设计、模型、CLI 和测试改动均作为工作区起点保留。

## Plan Of Work

采用十个可独立验证的实施批次，映射见 [execution](execution.md)。只有 01 是为迁移准备的局部重构；共享类型随首条生产路径引入，避免单独建立全库改名或类型铺设票据。所有切片自行负责新增路径的基本异常传播和资源释放，后续故障票据负责异步与跨 Case 的新增策略。

### M1：隔离现有验收材料与追踪归属（01）

先把验收所需事实固定为不可变输入，为一次验收绑定专属记录和追踪归属。现有单次运行的业务判断、模型循环与退出语义保持可回归。通过两份独立验收交错完成，证明输入、历史和诊断不会互相覆盖。此处尚不改变批次调度。

### M2：新格式单检查点与串行批次可运行（02、03）

02 首先贯通一条新格式单检查点：整份准备、合法 Session、显式提交、独立验收、正常最终文本及 SuiteResult；同时切换最小 CLI 样例。03 扩展为完整有序批次，贯通混合非法／合法条目、公共错误与配置覆盖，证明上一 Session 全部收敛后才启动下一条。

### M3：同一执行循环逐段提交并异步验收（04、05、06）

04 在 02 基础上支持多个检查点、有界队列及可配置验收并发；下一阶段经回执公开，执行不等待验收槽位或结论。05 完成动作后提交和跨阶段预算边界；06 完成提前结束、执行故障和单项验收故障下的独立收敛。正常路径已经在 02 开始于执行退出后释放 Browser，06 验证失败分支同样成立。

### M4：异步故障与批次收尾可信（07、08、09）

07 贯通后台必要记录故障到 Session 停止及 Suite 停调；08 贯通同一硬截止时间和携带快照的取消传播；09 验证共享资源、批次追踪与最终保存故障归属，保留已结束 Case 的事实。这些切片分别验证不同触发条件，不把“errors 非空”用作统一取消开关。

### M5：命令行交付与真实模型证据齐备（10）

更新完整样例和使用说明，以真实本地页面、受控模型及 OTLP 出口完成组合回归，再经同一生产 CLI 运行真实模型的多 Case、多检查点演示。实际异步重叠必须由受控同步点证明；真实模型演示单独证明工具与视觉判断接合。

## Validation And Acceptance

1. 单对象与批次 JSON 经过同一准备和执行语义；整份预检早于 Browser／模型请求。重复 ID 全部冲突项非法，公共错误阻止启动，条目错误不阻止其他合法项，覆盖合并不污染默认值。
2. Case 串行且各自拥有页面、预算、Context 与记录；普通 failed／error 后继续，必要记录失败后后续合法项为 not_run。共享客户端跨 Case 复用，仅在 Suite 收尾关闭。
3. 单 Case 只调用一次 execute；未来内容在公开前不出现在 prompt、工具定义、拒绝反馈或历史中。动作与提交串行；同响应提交后的动作／再次提交拒绝，最后检查点后所有工具禁用。
4. 提交引用最新已保存图且不重拍；保存提交事实并登记验收后才推进。重复拒绝不建任务，回执交付失败不撤销已成立提交。验收只收到本组断言和冻结图，后续页面变化、浏览器关闭及任务乱序完成都不改变其证据归属。
5. verification_concurrency 限制逻辑验收并发而非 Case 并发；排队不延长 deadline。执行与验收确有重叠，执行退出即关闭页面，下一 Case 等全部收敛。
6. 请求／工具／动作预算按 Case 累计，验收请求／纠正按检查点累计。动作耗尽后仍可提交当前证据；框架额度耗尽不能伪造最终文本或保证额外总结请求。
7. 单项模型故障局部化；执行故障不取消已有验收；后台记录失败主动停止所有业务；超时／取消后无新业务请求或遗留验收任务。Session 通过 CancelledError 子类交付快照，Suite 保存事实再继续传播。
8. SessionResult 覆盖全部声明检查点且不遗留 queued／running，ExecutionOutcome、Verdict、RunError、stop_reason 分别表达。SuiteResult 保留全部可定位条目；批次错误不回写最后 Case。
9. 图片仅保存一次，提交材料互不覆盖，结果只存引用；批次和 Session 目录并列且不覆盖。完整 trace 仅保存于 Suite，后台追踪固定关联，无在线图片载荷。必要保存失败只声明实际可用路径，返回快照不被后台修改。
10. 全量离线回归与静态检查通过；同一 CLI 的真实模型演示保存批次／会话标识、模型名、日期和产物位置，不保存密钥。未取得真实证据时 M5 保持未完成。

具体命令和预期观察归 [execution](execution.md)，实际测试数量、失败与限制归 [progress](progress.md)。

## Recovery

每个批次独立落地并保持适用回归通过；按阻塞关系工作，不跳过未完成前置。迁移旧断言时更换目标契约和关联，保留其生产行为覆盖，不通过删除失败测试使检查变绿。中间版本的迁移安排见 [decisions](decisions.md)，不对外承诺未完成的完整功能。

测试失败先定位本批次接合；若锁定框架无法满足响应屏障或故障通知，先记录证据并修订所属正式设计，再调整计划。失败运行不恢复、不重放，每次重跑创建新的 suite_id／session_id 和目录。完成全部验收后才把整个计划包归档到 completed，并重新校验链接。

## Related Documents

- [Execution](execution.md)
- [Decisions](decisions.md)
- [Progress](progress.md)
