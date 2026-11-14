# Execution

执行部分以逐票 ticket 为工作单位；本文件只保留票据映射、接合位置和验证入口，不重复每票的验收清单。当前票据在 `.scratch/observability-error-handling/drafts/`，待用户确认粒度与阻塞关系后发布至同一 feature 的 `issues/`，届时更新以下链接并将状态设为 ready-for-agent。

## 票据与阻塞关系

| Ticket | Milestone | Blocked by | 当前草案 |
|---|---|---|---|
| 01 初始化失败可取得具体摘要与完整本地诊断 | M1 | 无 | [01](../../../.scratch/observability-error-handling/drafts/01-initialization-diagnostics.md) |
| 02 零动作会话贯通本地与 Langfuse 追踪 | M2 | 01 | [02](../../../.scratch/observability-error-handling/drafts/02-zero-action-tracing.md) |
| 03 正常计划与浏览器动作全程可查 | M2 | 02 | [03](../../../.scratch/observability-error-handling/drafts/03-browser-action-tracing.md) |
| 04 工具拒绝与派发后故障可区分 | M3 | 03 | [04](../../../.scratch/observability-error-handling/drafts/04-tool-failure-diagnostics.md) |
| 05 模型与验收失败保留完整诊断及可见部分输出 | M3 | 02 | [05](../../../.scratch/observability-error-handling/drafts/05-verification-stream-errors.md) |
| 06 Langfuse 故障可见且不改变测试结果 | M3 | 02 | [06](../../../.scratch/observability-error-handling/drafts/06-export-failure-isolation.md) |
| 07 跨阶段故障、超时和取消保留原始结论 | M4 | 04、05、06 | [07](../../../.scratch/observability-error-handling/drafts/07-lifecycle-failure-preservation.md) |
| 08 完整离线回归与真实 Langfuse 演示 | M4 | 07 | [08](../../../.scratch/observability-error-handling/drafts/08-end-to-end-acceptance.md) |

这些边只列直接前置，不重复传递依赖。01 发布后是初始可执行前沿；02 完成后，03、05、06 的前置均满足。这里描述依赖可用性，不要求同时修改共享文件。

## M1：初始化失败可完整定位

### Batch 01：初始化诊断贯通（已完成，2026-11-14）

接合 `src/uiprobe/session.py`、`src/uiprobe/recording.py`、`src/uiprobe/__main__.py` 和 Browser 初始化。引入 Error Handling 的首次生产调用，规范化摘要与完整诊断，沿调用位置归因，迁移现有摘要构造使旧 suite 保持通过。不能只新增孤立错误类而没有实际失败路径使用它。

首票开始时在 owning design／共享契约中落实错误类别目录的首批条目和诊断本地承载方式。以真实浏览器访问一个已确认未监听的本地地址复现导航失败，并以配置可用的输入错误、无可用目录、结构化异常链验证诊断保存与内存退路。受控未监听地址只用于本地测试，不请求真实模型。

完成条件：调用方取得 operation 和 error_id，通过 error_id 找到完整异常链；无目录时不宣称保存成功，浏览器释放；既有输入及阶段故障回归通过。

验证入口：现有 `test_session_input.py`、`test_session_lifecycle.py` 及新增错误诊断测试。新增测试名由实施批次确定并记录到 progress，不能用尚不存在的测试命令声称验证通过。

## M2：正常测试的本地与 Langfuse 全链路可查

### Batch 02：零动作追踪贯通（已完成，2026-11-14）

接合应用入口、Session、Agent、Verification 和 Recorder。首次使用锁定 Pydantic AI 原生 Instrumentation 与 Langfuse／OTel 接合，在本地 exporter 和受控在线出口观察同一次零动作会话。先验证当前 StreamingModel 对框架模型观测的影响，不照搬不同版本构造参数。

本批次必须同时满足在线排除图片、基础在线异常隔离和有界退出，不能先把完整图片导出再等后票修复。将本地追踪／实际发送视图的布局、应用级观测配置、运行关联和初版退出等待选择更新到 owning design；观测配置不混入严格 SessionConfig。06 在此基础上完整覆盖失败状态及 SDK 的确认范围。

完成条件：首图直接提交后，本地与受控出口可查启动、执行模型、独立验收、资源关闭及相同 trace 关联；图片只在本地和模型请求中出现；action_count=0、Verdict 与原行为一致。

验证入口：`test_session_zero_action.py`、`test_mvp_e2e.py`，以及新增原生追踪与待导出载荷检查。受控 exporter 与网络出口都不得依赖真实凭据。

### Batch 03：正常浏览器动作追踪（已完成，2026-11-14）

沿 `src/uiprobe/actions.py`、`src/uiprobe/browser.py`、Context 发送视图和 Recorder 接入正常 TODO／点击／引用填写路径，使用现有 before_dispatch 接合记录事实，不为观测新增派发循环。

用真实本地登录页和受控模型响应完成登录与独立验收；比较原始工具参数、实际结果、CSS 坐标、前后截图编号、动作计数、完整历史和实际发送视图。单独验证 HTTP 4xx／5xx 页面可导航并取得首图时继续执行，状态码只用于记录。

完成条件：一条调用可从模型 tool call 定位到派发、capture、本地 PNG 与返回结果；在线载荷没有图片，没有重复模型调用记录或重复用量。

验证入口：`test_agent_click.py`、`test_agent_login.py`、`test_context_recording.py`、`test_mvp_e2e.py` 和新增导航状态观测场景。

## M3：故障链可解释且不改变执行策略

### Batch 04：工具拒绝与派发后故障（已完成，2026-11-14）

通过已接通的动作链覆盖框架校验、BrowserRejected、派发异常、取图异常及新窗口。框架在 ActionToolset 前拒绝的未知工具／类型／参数问题也要有调用及拒绝材料，不通过复制框架校验实现。

完成条件：预检拒绝能被模型纠正且 action_count 不增；派发后故障计数保留、运行停止、无动作重放和无后续验收；截图失败仍保留最后成功观察。每种情况的错误或拒绝原因可从本地与受控线上事实定位。

验证入口：`test_agent_click.py`、`test_agent_login.py`、`test_agent_observation.py`、`test_session_lifecycle.py` 和 `test_failure_observability.py`。

### Batch 05：模型、验收与流中断诊断（已完成，2026-11-14）

沿真实模型适配、原生框架和 `src/uiprobe/verification.py` 接入失败材料。使用受控响应复现非标准成功响应、流中断、验收格式纠正耗尽和原生预算耗尽，不调用真实服务故意制造失败。

中断内容只保留 SDK／框架已暴露且可取得的部分，逐 chunk 不重复记录；若当前聚合适配掩盖该内容，优先使用框架原生能力接合并记录可见性，不另写流协议。合法 failed／证据不足 error 不追加请求；异常导致的验收 error 有具体诊断而不是伪造模型判断。

完成条件：错误摘要和完整诊断可关联；没有半份工具执行或伪造 Submission；SDK 原生重试保持原归属，执行与验收输入仍隔离。

验证入口：`test_model_service.py`、`test_verification.py`、`test_agent_budget.py` 及 `test_failure_observability.py`。

### Batch 06：在线故障隔离与退出状态（已完成，2026-11-14）

覆盖应用级观测配置、初始化、SDK 导出、可见的队列丢弃／提交失败与 flush。只测试 SDK 实际可见的结果，不能要求库报告不存在的成功确认。落实观测不完整的结果表达及独立等待时限，并同步 owning design；原有本地写入失败语义不变。

完成条件：真实本地页面的零动作／正常结果在在线故障下仍保持原值，本地诊断和可见告警可查；入队、flush 完成和远端状态不可知被准确区分；不远端逐条查询、不无限等待、不递归追踪导出请求。

验证入口：`test_export_failures.py`、`test_failure_observability.py` 的可控 exporter 失败／阻塞／flush 测试，复用 `test_session_zero_action.py` 与 `test_mvp_e2e.py` 的应用入口。

## M4：跨阶段收尾与真实演示验收

### Batch 07：组合故障与生命周期（已完成，2026-11-14）

组合执行／验收主故障、记录再次失败、浏览器清理失败、应用持有模型客户端关闭失败、最终结果写入失败和在线故障。补齐启动早于目录创建、总时限耗尽及外部取消的根追踪和错误传播。

重点验证两处现有风险：ActionToolset 异常处理写入失败和 Agent finally 再次保存失败可能遮住主因；应用模型客户端关闭在 Session 返回后发生，不能使已有结果被丢弃或把已保存快照谎称为最新结果。

完成条件：主故障与后续故障分别可查，已知结论／动作数／截图及主 stop_reason 保持；本地不可写时返回内存摘要与真实可用路径，取消收尾后继续传播；外层根追踪覆盖应用资源关闭且收尾有界。

验证入口：`test_session_lifecycle.py`、`test_session_input.py`、`test_session_zero_action.py`、`test_mvp_e2e.py` 和 `test_combined_failures.py`。

### Batch 08：端到端验收与交付记录（离线与真实模型本地演示完成；在线验收待执行）

先运行完整离线检查，再通过 README 中的真实本地页面启动方式运行登录用例和初图用例。仅真实演示连接个人 Langfuse 与已配置模型；记录 session_id、trace_id、在线 trace 定位、本地目录、终态和观察到的导出情况。

真实演示时在 Langfuse 页面检查根运行、模型调用、完整工具参数／结果、验收和清理；确认没有图片附件。此为验收时检查，不引入运行时远端逐条确认。证明图片不出网以离线待导出载荷和媒体请求断言为准，不能只凭网页没显示图片推断。

完成条件：全部离线检查通过，真实登录与零动作演示各有本地和在线证据；README 写清配置、诊断定位与观测失败语义；无法完成真实演示时保留具体缺口，不能关闭计划。

## 验证命令

开发时按上文选择已存在的目标测试文件，例如：

```bash
uv run python -m unittest discover -s tests -p 'test_session_lifecycle.py' -v
uv run python -m unittest discover -s tests -p 'test_session_zero_action.py' -v
uv run python -m unittest discover -s tests -p 'test_mvp_e2e.py' -v
```

所有 Python 批次完成前执行；跨 module、生命周期和持久化变更执行全 suite：

```bash
uv run ruff check --select I --fix .
uv run ruff format .
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run python -m unittest discover -s tests -v
git diff --check
```

预期：目标测试确实被发现且全部通过；新场景必须有行为断言，不能通过跳过浏览器、削弱原断言或只检查文件存在来通过。记录测试数量与命令结果。离线回归不访问真实模型或 Langfuse。

真实演示在一个终端启动页面，另一个终端依次运行：

```bash
uv run python -m http.server 8765 --bind 127.0.0.1 --directory login-demo
```

```bash
uv run python -m uiprobe --case login-demo/mvp-case.json --config login-demo/mvp-config.json
uv run python -m uiprobe --case login-demo/mvp-initial-case.json --config login-demo/mvp-config.json
```

运行前按 02／06 落地后的 README 配置 Langfuse；本计划不写入个人凭据，不提前承诺当前尚不存在的观测 CLI 参数。

## Idempotence And Recovery

票据未开始时先检查 blocker 的实际完成证据，不凭 ready-for-agent 推断已完成。每票停止时更新 progress、实际测试入口和决定；设计发生变化先更新拥有该契约的设计文档。

测试和演示每次使用新运行目录，不覆盖旧产物。失败后保留诊断，再以新会话重做人工演示；应用不会自动恢复中断执行。发布草案时逐票迁移到 issues，保留编号与依赖，不修改旧 MVP 票据；重复发布先核对目标，不能覆写已存在票据的执行状态。

## 本轮交付边界（2026-11-14）

用户明确暂不配置 Langfuse，要求完成其余部分。真实模型登录和初图用例已在本地页面通过；个人 Langfuse 的真实导出、在线 trace 定位及页面检查保持待执行。此缺口不妨碍提交已验证的生命周期实现，但计划仍保持未完成，不归档。运行标识与验证证据见 progress。
