# 全流程观测：Observability

Observability 负责将 UIProbe 一次截图驱动的浏览器测试关联为可回查的完整过程，覆盖本地记录和 Langfuse 在线追踪。本文中的 module 指对外提供 interface 并隐藏内部实现（implementation）的职责划分；interface 包含调用、顺序、数据归属和错误语义，不表示已经存在同名 Python 类型。

本文定义目标设计；当前正常链路和故障接合见文末实现约定，跨阶段收尾与真实演示按执行计划验收。设计依据是[讨论已确认的十项约定](../../discussions/errors-and-observability.md#已确认)，以及现有 [Recorder](recording.md)、[Agent](agent.md)、[Session](runner.md) 的职责。观测不决定测试是否通过，也不接管模型或浏览器执行。

## 基本概念与状态归属

| 概念 | 定义与归属 |
|---|---|
| Session／session_id | 一次测试会话及其标识；Session 组织输入准备、执行、验收和收尾 |
| trace／trace_id | 一次运行的完整追踪及其标识，由 Observability 关联；覆盖 Session 前的启动和应用持有资源的关闭 |
| span／span_id | trace 中一段有起止时间的操作及其标识；父子关系表达操作归属，不替代实际发生顺序 |
| Langfuse | 接收并展示在线 trace 的平台；本项目使用个人账号 |
| Pydantic AI／OpenTelemetry | 前者是已有 Agent 执行框架；后者简称 OTel，是框架向观测后端传递追踪数据的标准机制 |
| Recorder | 持有运行目录、序列化和写入本地产物的 module；Observability 不另建一套本地写入实现 |
| Submission／Verdict | 前者是执行 Agent 的正常最终提交；后者是独立视觉验收的断言判断，均由原有 module 产生 |

Agent 是由模型和工具循环驱动、负责规划与操作页面的执行过程。独立验收只根据断言和最终截图判断结果，不共享执行 Agent 的历史。

每次运行的追踪关联与导出情况属于 Observability；页面、完整模型历史和测试终态仍分别属于 Browser、Context 和 Session。Browser 管浏览器操作，Context 管当前观察与原生消息历史。完整诊断的内容由 [Error Handling](error-handling.md) 形成，Observability 只关联并投递。

依据与理由：现有 Session 已将运行状态保持在 run 局部，Recorder 已负责文件布局。沿用这些归属可避免增加另一份会话状态，代价是必须显式关联各 module 的事实，不能仅依赖模型调用追踪。[出处：Session 状态归属](runner.md#状态归属)、[Recorder 内容及关联](recording.md#内容及关联)。

## Interface 与依赖装配

应用入口装配 Observability，注入本地记录依赖和 Langfuse／OTel 依赖。调用方使用同一个运行作用域；作用域指本次运行追踪的有效期间及其关联信息。Session、Browser、工具路径和验收只提交各自拥有的事实，不取得 Langfuse 客户端或文件句柄。

| 逻辑 interface | 调用方必须知道的契约 |
|---|---|
| 建立运行作用域 → 追踪关联 | 应用入口在文件读取和模型装配前建立根 trace；Session 创建 session_id 后关联到该 trace，启动失败也保留已有追踪 |
| 进入操作作用域 → 操作关联 | 项目拥有的初始化、导航、派发、截图、记录与清理表达为相应操作；成功、失败、超时、取消均应结束或明确中断，不虚构完成 |
| 记录事实／诊断 | 接收原生框架材料或现有业务结果及关联信息，保留完整文本；本地与在线投递规则由 module 内部处理 |
| 结束运行并 flush → 可知的导出情况 | flush 指请求观测软件开发库（SDK）提交待导出数据；应用入口在业务收尾后调用，报告 SDK 可知的失败和最终 flush 情况 |

以上是 interface 的语义范围，不要求新增四种包装类。框架已有的 Agent、模型和工具作用域直接复用，不让各调用点手工复制。会话标识尚未创建或本地目录不可用时，只关联已取得的信息，不宣称存在本地产物。

该 interface 的 seam，即可替换行为而不修改业务调用处的位置，位于“提交事实／诊断”处。本地必要写入和在线导出有不同故障语义，不能以同一个成功返回值掩盖其中任一失败。序列化、图片投影和导出关联集中在该 seam 后，调用方无需学习 Langfuse 数据格式。

依据与取舍：这是对 Recorder、框架追踪和项目生命周期的接合，不是新建 Agent 协议。保留小 interface，使图片排除或关联规则修改集中在 Observability；同时保留本地写入故障向外传播的能力。[出处：讨论确认 1、4、5](../../discussions/errors-and-observability.md#已确认)、[模型连接装配](model.md#配置与装配)。

## 核心数据流与追踪粒度

1. 应用入口建立根 trace，记录启动、文件读取与装配；Session 创建后关联 session_id。一份用例的不同运行使用不同 trace，session_id 与 trace_id 明确映射。
2. 初始化记录浏览器启动、入口导航与首图。导航事实包含可取得的主文档响应状态、最终网址和截图关联；HTTP 4xx／5xx 页面在导航与首图成功时继续测试。
3. 执行 Agent 记录完整指令、模型实际发送文本、工具定义、响应和可取得的 token 用量；token 用量是模型返回的输入／输出计量，不推算不可见数据。工具记录原始参数、实际结果与纠正反馈，包括框架在项目工具包装层之前拒绝的调用。
4. 浏览器动作关联工具 call_id（框架调用标识）、action_index（已派发动作的会话内计数），以及操作前后的 screenshot_id（本地截图标识）。预检、实际派发和后续截图必须可区分。
5. 正常 Submission 后进入独立验收，记录验收实际输入、格式纠正与 Verdict。执行与验收位于同一 trace 下各自的作用域。每次验收的子 span 固定关联 session_id、submission_id 和可用的 screenshot_id。
6. 收尾记录浏览器释放、本地最终保存及应用持有客户端的关闭。根追踪覆盖这些业务收尾后，再处理观测自身的导出；不把 Langfuse 导出请求递归记作新的业务运行。

Pydantic AI 原生追踪负责 Agent、模型请求、工具和框架纠正；项目补充框架之外的 Browser、Recorder 与生命周期操作。同一模型调用只有一份权威记录和用量归属，不额外创建重复的模型调用记录。SDK 内部连接重试只记录其原生机制实际暴露的事实，不为补观测重写重试循环。

依据与取舍：两次实际报错分别只能看到 initialization_error 与 execution_error，无法定位导航和模型响应校验；只接入模型追踪不能解释这些步骤。按已有 module 的实际操作划分 span，可定位派发后故障而不逐行埋点。[出处：已发生案例](../../discussions/errors-and-observability.md#两个已发生案例应如何呈现)、[工具调用路径](actions.md#浏览器动作路径)、[Browser 操作与截图](browser.md#操作与截图的关系)。

## 内容与关联契约

| 材料 | 本地 | Langfuse |
|---|---|---|
| 用例、模型指令、输入输出文本、工具定义 | 完整保留；完整历史与模型实际发送视图分别可查 | 完整记录，明确是执行还是验收输入 |
| TODO、工具参数与实际结果、纠正反馈 | 完整保留；TODO 是 Agent 使用工具维护的操作计划 | 完整记录；不为日志改变工具返回值 |
| 截图 | 保存所有实际取得的 PNG 格式图片 | 只记录截图编号、图片／视口尺寸、本地路径和动作关联 |
| 异常与终态 | 错误摘要、完整诊断、Submission、Verdict 和收尾结果 | 对应诊断与结果，以 error_id 关联；error_id 是同一次故障的诊断标识 |
| 时间与额度 | 操作起止、耗时和当时可取得的剩余额度 | 使用同一事实，不另行改变预算 |

沿用原生框架消息和 Recorder 的图片引用表达，不建立另一套运行时消息协议。trace_id／span_id 与业务标识关联，但不替代业务标识。调用并发时按实际开始与完成记录，不以模型提出顺序推断完成顺序。

依据与取舍：完整文本和工具结果用于个人开发排错，不引入脱敏工作流；图片只留本地是用户为减少网络流量确认的例外。在线路径只是本地文件的定位信息，不承诺可从 Langfuse 网页直接打开。[出处：讨论确认 1—3、8](../../discussions/errors-and-observability.md#已确认)、[Context 完整历史与发送视图](context.md#完整历史与发送视图)。

## 图片投影与流式内容

图片排除只影响在线观测视图，不影响模型实际看图或本地 PNG。在线不能出现图片字节、base64（图片的文本编码）、图片 data URI（包含图片内容的网址形式）或图片附件；框架消息、工具结果、自定义属性和异常附带载荷均遵守此规则。

框架采集文本而排除二进制内容；不能假定这一配置覆盖任意自定义对象或额外 HTTP 正文采集。HTTP 是模型服务使用的网络请求协议，其正文可能包含图片，不能无区别完整导出。该限制解决流量问题，不改变完整文本采集约定。[依据：讨论确认 3](../../discussions/errors-and-observability.md#已确认)、[框架二进制排除说明](https://pydantic.dev/docs/ai/integrations/logfire/#excluding-binary-content)；接入能力已对照项目锁定版本核查，依赖版本仍归 [uv.lock](../../../uv.lock) 管理。

流式请求在多段内容到达后聚合为完整响应，观测保存该完整输出，不逐 chunk（传输分片）重复记录。中断时保留 SDK／框架已暴露且可取得的部分输出，标记 incomplete（未完成），不将其作为提交、完整工具参数或有效验收结论。未暴露的数据不承诺恢复。

依据与取舍：聚合输出足以复盘完整调用，中断材料帮助解释失败；不重复上传每个分片可避免同一内容多次记录，也无需自建流协议。[出处：讨论确认 9](../../discussions/errors-and-observability.md#已确认)、[模型默认流式传输](model.md#默认流式传输)。

## 故障与收尾

本地必要材料写入失败向 Session 传播，停止后续执行，并尝试清理与保存可用结果。Langfuse 初始化、导出或 flush 失败则继续测试，单独记录观测不完整及原因，不改变 Submission、Verdict 或测试运行状态，也不覆盖原有故障。本地同时不可写时，保留内存摘要并通过标准错误输出报告，不声称诊断已保存。

首版只报告 SDK 可知的导出失败和最终 flush 情况，不远端逐条查询。入队或 flush 调用完成不等于远端每条记录已可查询；不可知状态不推断为成功。退出导出不得无界等待或延长 Agent 执行时限；具体等待时限和导出状态字段在执行计划中落实，不在此新增状态枚举。

依据与取舍：必要本地证据是现有运行契约，在线平台故障不能影响浏览器测试结论。接受远端完整性未逐条确认，换取个人开发项目较小的接入与网络开销。[出处：讨论确认 4、10](../../discussions/errors-and-observability.md#已确认)、[Recorder 写入失败与终态](recording.md#写入失败与终态)。

本地 trace 与完整诊断的文件布局、具体导出字段尚待实施前细化；当前不新增模型重试、后台补传、断点恢复或额外验收流程。框架接入能力可参考 [Pydantic AI 观测说明](https://pydantic.dev/docs/ai/integrations/logfire/)与 [Langfuse 集成说明](https://langfuse.com/integrations/frameworks/pydantic-ai)，最终以项目锁定版本为准。

## 正常运行追踪实现（2026-11-14）

应用使用独立 OTel TracerProvider，不修改全局 provider。根作用域早于文件读取，覆盖 Session 和模型客户端关闭；Session 单独调用时建立自己的根。原生 Agent.instrument 使用锁定版本 InstrumentationSettings，完整文本开启、include_binary_content=False；StreamingModel 聚合后的响应由原生能力记录，不再套一层模型 instrumentation。

Recorder 保存 trace.json（trace_id、原生及项目 spans、可知在线告警）。执行模型的实际请求保存于 execution-requests.jsonl，验收模型的实际请求保存于 `submissions/<submission_id>/requests.jsonl`。两处请求均使用截图编号引用已有 PNG。事件关联 trace_id；工具保留 call_id、参数、实际结果，派发事件保留 action_index 和剩余时间，浏览器记录导航 HTTP 状态、最终 URL 与截图尺寸。HTTP 4xx/5xx 不独立导致失败。

在线采用 Langfuse OTLP HTTP 接口（LANGFUSE_BASE_URL、LANGFUSE_PUBLIC_KEY、LANGFUSE_SECRET_KEY），未提供任一 Langfuse 配置时仅本地记录；部分配置视为观测配置故障。BatchSpanProcessor 批量投递，HTTP timeout=2 秒，退出在独立 daemon 线程 flush + shutdown，主线程 join 最多等待 2500ms（锁定 SDK 忽略原生 timeout 参数）；不逐条确认远端。初始化及 exporter 异常隔离为观测告警。跨阶段故障／取消组合仍由后续批次完成。

## 故障与退出状态

trace.json 的 export 区分 enabled、flush（not_requested/pending/completed/failed/timed_out）、remote_delivery（始终 unknown）以及 SDK exporter 返回成功／失败的批次计数。flush 完成只说明本地提交调用结束，不能覆盖已知导出失败。配置、导出、SDK 队列丢弃和 flush 故障单独保存 observability_diagnostics（error_id、操作、异常链），设置 observability_incomplete 并向 stderr 提示，不加入 Session.errors。队列丢弃仅采用锁定 SDK 实际产生的日志，不推测远端状态。超时后保存的状态保持 timed_out，后台结束不能把这份退出快照改称成功。

流中断仅将原生 stream.get() 已暴露的聚合响应保存到 code=model_stream_incomplete 的完整诊断及关联 diagnostic 事件，附 incomplete=true；没有完整响应就不交给工具或提交路径。框架尚未暴露的片段不补造。工具前置拒绝从原生 ToolReturnPart(outcome=retried) 或兼容的 RetryPromptPart 记录，原始调用仍在完整历史与框架模型 span 中。
