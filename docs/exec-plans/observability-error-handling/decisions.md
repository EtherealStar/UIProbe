# Decisions

## 2026-11-14：正式设计是范围依据

Decision：以 Observability、Error Handling 与共享契约为实现约束；讨论中的未采纳字段和建议不自动实施。

Context：设计已确认采集、图片、重试归属和错误处置，但尚未定义完整诊断文件名、导出字段或新异常继承体系。

Rationale：让计划安排交付与验证，而不是新增另一套架构来源。

Consequences：首个实际使用批次落实必要细节并同步 owning design；不把 disabled／complete 等讨论枚举、retryable 字段或逐分片日志直接作为交付要求。设计来源见 [Observability](../../design/modules/observability.md)与 [Error Handling](../../design/modules/error-handling.md)。

## 2026-11-14：沿用本地 tracker，先审阅逐票草案

Decision：使用独立 feature 的本地文件 tracker，每票一个文件；草案位于 `.scratch/observability-error-handling/drafts/`，确认后发布至 `issues/` 并使用 ready-for-agent。

Context：此前用户已确认本地 tracker 与状态词汇，记录在 [MVP tracker 决定](../uiprobe-mvp/decisions.md#2026-11-13已确认本地-tracker拆分已确认并发布)。本次请求未更改 tracker。

Rationale：复用已授权的本地流程，不另建外部 issue，也不要求重新初始化 tracker。

Consequences：to-tickets 的拆分审阅要求仍适用；本次完成计划与可审阅草案，等待粒度、阻塞关系、合并／拆分确认后发布。草案状态不代表可以开始实施，不修改旧 MVP 父票据或完成状态。

## 2026-11-14：以失败和正常会话为纵向切片

Decision：01 用初始化失败打通共享错误表达与本地诊断，02 用零动作会话接通在线追踪，之后按可复现的用户场景扩展。

Context：当前 SessionError 构造分散于入口、Session 与测试，且框架追踪尚未启用；单独的类型／exporter／span 工具票据无法说明用户能看到什么。

Rationale：每票交付一个完整可演示行为，首票包含它所需的最小调用点整理；现有调用数量不构成必须采用宽重构 expand–contract 的条件。

Consequences：各票保持现有 suite 通过，不新增“只写基础设施”的前置票。没有真正阻塞的功能不串联：03、05、06 均在 02 后可开始，07 负责组合生命周期，08 负责真实验收。

## 2026-11-14：第一次导出就排除图片

Decision：图片排除和在线异常不影响测试的最低契约随 02 一起实现；06 再完整验证观测不完整的表达和失败收尾。

Context：模型实际请求和框架消息含图，额外 HTTP 正文采集也可能绕过二进制排除。不能让“稍后完善图片控制”的中间批次违反已确认要求。

Rationale：使每个启用线上导出的中间交付都遵守用户流量要求；避免将不完整但已出网的行为留到最后审查。

Consequences：使用原生 Instrumentation 并检查真实待导出内容；不重复包装模型生成记录，不用关闭内容采集代替排除图片。[设计出处](../../design/modules/observability.md#图片投影与流式内容)。

## 2026-11-14：区分自动回归、真实接入与确认范围

Decision：离线使用受控模型、真实本地浏览器和可控观测出口；最终真实演示使用用户已配置的模型与个人 Langfuse。运行时不新增远端逐条确认。

Context：现有 53 tests 通过只证明离线行为，旧 MVP 的真实模型验收仍未完成；SDK flush 结果也不能证明远端全部条目可查。

Rationale：避免把模拟结果和 SDK 入队当成实际接入成功，同时保持已确认的网络开销范围。

Consequences：08 记录真实 session／trace 证据，缺配置时明确保持未完成；在线页面人工检查属于交付验收，不变成每次运行的额外网络协议。

## 待首次使用时落实的实施选择

| 选择 | 负责票据 | 必须满足的约束 |
|---|---|---|
| 首批稳定错误类别、完整诊断本地承载与 error_id 复用 | 01 | 摘要和诊断可对应；无原始异常对象落盘；本地失败保留内存摘要 |
| 原生 Instrumentation 与 StreamingModel 接合 | 02 | 锁定版本可运行，执行／验收仍隔离，没有重复模型记录 |
| 本地 trace／实际发送视图的文件布局及关联 | 02 | Recorder 拥有写入，现有产物保留；不创建另一套运行时消息协议 |
| 应用级观测配置与基本有界退出 | 02 | 不扩展严格 SessionConfig，不上传图片，在线故障不影响结论 |
| 部分流内容的实际可见范围 | 05 | 只用 SDK／框架已暴露材料；不另写流协议、不承诺恢复不可见数据 |
| 观测不完整字段、SDK 状态表达与故障下退出等待 | 06 | 可知与未知分开，不远端逐条查询、不无限等待 |
| 应用客户端关闭故障与已有 SessionResult 的接合 | 07 | 根 trace 覆盖关闭，已有结果不丢失，持久化路径及快照真实性准确 |

这些项目是实施细化，不是已完成决定。实施者必须在对应票据中先记录选择并更新拥有该契约的设计文档；若触及已确认行为则停止依赖该变化的工作，明确提出冲突，不能自行替换范围。

## M1 实施选择

2026-11-14：用户明确要求执行 M1，按票据 01 范围实施。诊断采用每 error_id 一个 JSON 文件，保留标准 traceback 的完整异常链；业务校验错误不伪造异常。采用操作边界包装保留同一故障标识，不按 OSError 推测文件故障。在线追踪仍属后续 M2。

## 正常运行追踪实现（2026-11-14）

应用使用独立 OTel TracerProvider，不修改全局 provider。根作用域早于文件读取，覆盖 Session 和模型客户端关闭；Session 单独调用时建立自己的根。原生 Agent.instrument 使用锁定版本 InstrumentationSettings，完整文本开启、include_binary_content=False；StreamingModel 聚合后的响应由原生能力记录，不再套一层模型 instrumentation。

Recorder 保存 trace.json（trace_id、原生及项目 spans、可知在线告警）、execution-requests.jsonl 和 verification-requests.jsonl（每次实际发送视图，图片替换为 screenshot 引用）。原有历史、PNG、验收及结果布局保留。事件关联 trace_id；工具保留 call_id、参数、实际结果，派发事件保留 action_index 和剩余时间，浏览器记录导航 HTTP 状态、最终 URL 与截图尺寸。HTTP 4xx/5xx 不独立导致失败。

在线采用 Langfuse OTLP HTTP 接口（LANGFUSE_BASE_URL、LANGFUSE_PUBLIC_KEY、LANGFUSE_SECRET_KEY），无公钥时仅本地记录。BatchSpanProcessor 批量投递，HTTP timeout=2 秒，退出在独立 daemon 线程 flush + shutdown，主线程 join 最多等待 2500ms（锁定 SDK 忽略原生 timeout 参数）；不逐条确认远端。初始化及 exporter 异常隔离为观测告警。更完整的故障／取消组合与状态表达仍由后续批次完成。

## 2026-11-14：故障分类与原生可见性

用户明确授权执行 M3 并提交；本次不以 tracker 草案尚未发布为阻塞。04—06 完成，草案不批量发布；范围与原计划一致。

执行通过异常附带纯数据诊断，保留 UsageLimitExceeded 等原生类型，Session.describe 复用摘要与 error_id；动作 LocatedFailure 沿原路径传播。锁定 Pydantic AI 实际将工具纠正表示为 ToolReturnPart(outcome=retried, retry=RetryInfo)，不能只检查旧 RetryPromptPart；生产采集兼容两者，不复制框架校验。

StreamingModel 使用原生 request_stream/stream.get 聚合；中断只给异常附带已暴露的部分响应，所属执行／验收边界形成阶段诊断。部分内容不进入提交或工具派发，不另写 SSE 协议；正常完整响应仍由原生 instrumentation 计量一次。传输最终连接失败仍由 SDK max_retries=2 处理。

SDK exporter 返回值和 force_flush 完成表达不同事实；分别保存批次计数、flush 与 remote_delivery=unknown。通过锁定 SDK 的实际队列日志记录丢弃，不读取私有队列推断成功。导出故障诊断保存在 trace.json 的 observability_diagnostics，避免污染 Session.errors；终端使用同一 error_id。退出线程只返回本地等待结果，超时的主线程快照不被迟到的成功改写。跨阶段取消与多故障保留不扩展到本阶段，仍由 07 验收。

## 2026-11-14：跨阶段收尾与结果快照

用户授权执行跨阶段收尾与真实演示验收并提交。记录故障处置中的再次写入失败暂存在记录对象，Session 合并到结果，不覆盖主故障。应用客户端关闭独立限五秒，关闭失败后通过绑定 Recorder 更新诊断与结果，更新等待同样限五秒；更新失败或最终 trace 保存失败移除返回路径中的 result.json，磁盘旧文件仅代表较早快照。已有结论和主停止原因保留，取消继续传播。真实模型配置可用，个人 Langfuse 配置尚缺，真实在线验收按实际证据保留缺口。

用户随后明确“先不配置，完成其他的部分”。因此本轮不配置个人 Langfuse，完成离线实现、回归和真实模型本地演示；在线验收继续待执行，计划不关闭、不归档。
