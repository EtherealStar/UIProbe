# 会话控制：Session

Session 运行一次完整浏览器测试：校验输入、初始化页面、执行测试 Agent、接收提交、独立验收、释放资源并保存结果。测试用例是输入数据；Session 是一次运行。模型与工具之间的循环由 Pydantic AI 驱动，Session 不逐轮调用模型。

本文中的 interface 表达目标设计，不表示对应代码已经实现。

## Interface 与依赖装配

应用入口创建 Session 对象，在构造时注入输入解析、Agent、browser_factory、Verification 和 Recorder。调用方使用异步 `run(test_json, config) -> SessionResult`。

Session 对象只保存依赖，不保存当前用例、动作数或截图。每次 run 在内部创建本次运行的数据。browser_factory 用于创建本次运行独享的 Browser；Recorder.begin 为本次运行创建独立记录。

执行模型和验收模型在应用入口装配 Agent、Verification 时注入。运行配置包含入口 URL、实际数据引用值、预算、时限和输出目录，不包含模型连接或模型角色配置。切换模型需要重新装配 Session。注入的模型客户端由应用入口关闭，Session 不关闭借用的客户端。

## 状态归属

| 状态 | 所有者及用途 |
|---|---|
| session_id、已解析输入、Submission、Verdict、stop_reason、errors | run 内的局部状态，用于组织阶段结果和终态 |
| deadline_at、浏览器动作计数 | 本次运行的 RunBudget，由 Session 与工具执行路径共享 |
| 完整用例、TODO、最新 BrowserState、框架消息历史 | Context，供 Agent 和工具使用 |
| 页面句柄、观察尺寸、实际数据引用值 | Browser，不进入模型输入 |

不创建包含所有字段的通用 SessionState，也不把整个 Session 暴露给工具。

RunBudget 的小 interface 是 `remaining_seconds()`、`claim_browser_action() -> action_index` 和只读 `action_count`。deadline_at 在 run 开始时由总时限换算为单调时钟的绝对截止时间，覆盖输入准备、初始化、Agent 执行和验收。实际日期时间另由 Recorder 记录。

工具执行路径先完成无副作用校验，再在派发操作前占用额度。校验拒绝不计数；已经派发的操作即使失败也计数，不退回额度。动作计数包括点击、填写、滚动和等待，不包括初始化、TODO 和验收。

## 主流程

1. 创建 session_id、共享截止时间和预算，调用 Recorder.begin 创建记录；校验输入和运行配置。
2. 创建 Browser，打开入口页面，取得并保存初始 BrowserState。
3. 创建 Context，装入完整用例、数据引用名、初始观察、空 TODO 和消息历史。
4. 调用 Agent.execute(context, dependencies)。Agent 可直接提交；首次浏览器操作前必须先创建非空 TODO。
5. 接收正常最终文本形成的 Submission，以最新截图调用一次 Verification.evaluate。零动作提交使用初始截图验收。TODO 未完成不阻止提交。
6. 无论主流程成功还是失败，都尝试释放浏览器资源，再保存含清理故障的最终结果。事件、历史和截图在执行期间增量保存，不依赖最后一次写入。

Session 只调用一次 execute。动作额度耗尽后，Agent 提示模型总结并禁用全部工具，包括 TODO；仍沿原有循环返回最终文本，不增加独立总结入口或固定一次的额外请求。模型仍尝试工具调用时拒绝执行并反馈。剩余请求额度与共享截止时间限制循环；用尽时按执行错误结束，不伪造 Submission。

模型请求和通用工具调用预算复用框架机制。执行阶段和验收阶段分别配置框架额度，共享同一 deadline_at。正常提交后不恢复执行 Agent，也不把验收反馈给它返工。

## 结果与错误

SessionResult 保存 session_id、可用测试用例、status、stop_reason、Submission、action_count、last_screenshot_id、Verdict、artifact_paths 和 errors。尚未取得的阶段结果允许为空。

`SessionError` 包含 `phase`、`code`、`message`：分别表示故障阶段、错误类别和安全可读的原因，不保存原始异常对象。stop_reason 表示主流程为何停止；errors 保留执行、清理和保存中可能同时发生的故障，后发生的错误不能覆盖原先的原因。

Verdict 表示断言判断，SessionResult.status 表示整次运行的结果。没有执行、清理或记录故障时，Session 使用 Verdict 的 passed / failed / error；存在这些故障时 Session 为 error，但已有 Submission、Verdict 和证据保持不变。例如验收通过后保存失败，Verdict 仍为 passed，Session 为 error。

Agent 未提交即失败时不启动验收。页面操作后取图失败时保留最近成功观察，不重放动作。本地记录失败立即停止后续页面操作；在线遥测失败不改变运行结论。最终保存失败仍向调用方返回内存中的 SessionResult 和已知可用路径，不能声称结果文件已成功保存。

## 取消与收尾

外部取消先触发已有材料保存和浏览器清理，再向调用方继续传播取消信号，不将取消吞掉并正常返回。取消记录中说明运行被取消；收尾不调用模型、不继续操作页面。

共享截止时间耗尽后，保存和资源释放使用单独的短收尾时限，避免因剩余执行时间为零而跳过清理，也避免无限等待。收尾时限不延长 Agent 或验收的执行预算。清理失败仍尝试最终保存；保存失败不能阻止资源清理。

## M1 已落实的启动契约

run 入口首先记录单调时钟起点。仅在 timeout_seconds 为有限正数且非布尔值时建立截止时间；
仅在 output_dir 为非空白、不含 NUL 的字符串时尝试独占记录目录。
随后 prepare 聚合完整用例及配置错误；目录配置无效时返回内存结果，可用目录则尝试保存。
所有校验完成前不创建 Browser、不请求模型。M1 合法输入由 prepare 返回 PreparedSession；
Session 的合法执行路径在 M2 接入，当前明确返回 execution_unavailable。

配置字段及严格类型约束见 [输入解析](case-input.md#m1-已落实的启动契约)。

### 收尾记录等待

最终事件和结果写入使用独立线程处理 SessionResult 快照，Session 等待上限为五秒。等待超时返回 recording/finalization_timeout；不声明结果文件已经保存，仅返回已成功创建的会话目录。线程不执行浏览器或模型操作，也不能修改返回结果。操作系统中已经开始的文件写入可能稍后完成；此时限约束 Session 等待，不承诺中断内核文件 I/O。
