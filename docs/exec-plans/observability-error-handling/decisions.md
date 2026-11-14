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
