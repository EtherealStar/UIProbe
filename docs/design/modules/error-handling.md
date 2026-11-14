# 错误处理与报错：Error Handling

Error Handling 负责将一次故障形成可定位的错误摘要和完整诊断，使终端、本地产物和 Langfuse 在线追踪能对应同一个原因。UIProbe 是截图驱动的浏览器测试程序；Session 是一次测试会话，Submission 是执行 Agent 的正常最终提交，Verdict 是独立视觉验收的断言判断。错误处理不生成提交，也不替代验收。

Agent 是由模型和工具循环驱动的规划与页面操作过程；Browser 管理页面操作与截图，Verification 负责只看断言与最终截图的独立验收。Langfuse 是在线追踪平台，Observability 是关联并导出运行事实的观测 module。

本文中的 module 指隐藏内部实现（implementation）、向调用方提供 interface 的职责划分；interface 包含输入、输出、调用顺序和错误语义。以下是目标设计，尚未完成代码改造。依据是[已确认讨论](../../discussions/errors-and-observability.md#已确认)、[共享契约](../contracts.md#提交验收和终态)及现有 Session、工具、Browser 和 Verification 的职责。

## 错误类别与职责归属

| 类别 | 定义 | 谁决定后续行为 |
|---|---|---|
| 可纠正拒绝 | 参数或当前状态不允许操作，浏览器动作尚未派发，如旧截图、越界坐标、未知引用 | 工具／Browser 给出原因，Pydantic AI 执行框架将反馈交给模型纠正 |
| 运行故障 | 当前流程无法按契约继续，如导航失败、动作派发后异常、截图或必要写入失败 | 发生故障的 module 保留上下文，Session 停止后续执行并收尾 |
| 有效验收结果 | 格式合法的 passed、failed 或证据不足 error；分别表示通过、存在反例或无法判断 | Verification 保留判断并合成 Verdict，不重试到通过 |
| 在线观测故障 | Langfuse 初始化、导出或最终提交观测数据失败 | Observability 标记观测不完整，继续测试，不改变测试结论 |

Pydantic AI 负责模型与工具循环、参数验证及纠正额度；模型 SDK（软件开发库）负责连接类重试。Error Handling 负责具体原因、摘要和诊断关联，不另加重试循环。Session 保持运行终态、错误列表和收尾顺序的所有权；[Observability](observability.md)负责诊断的追踪关联与投递，[Recorder](recording.md)负责本地序列化和保存。

依据与取舍：当前多个异常被统一写成 Session phase failed，验收也将多类异常写成无法验收。分开故障、拒绝和合法判断，可以保留具体原因，又避免一次被纠正的参数错误导致整次测试失败。[出处：讨论中的实现核查](../../discussions/errors-and-observability.md#当前实现核查)、[Agent 工具反馈](agent.md#模型输入与工具反馈)、[验收错误结果](verification.md#输出纠正和错误结果)。

## Interface 与依赖装配

Error Handling 的逻辑 interface 为“描述故障：异常或明确的业务失败 + 发生位置 → SessionError 摘要与完整诊断”。发生位置由调用方提供，至少包括 phase（流程阶段）和 operation（具体操作）。只传本次故障所需的调用、动作、截图等已知上下文，不传整个 Session 或页面句柄。

该 interface 不执行浏览器操作、不请求模型，也不直接写文件或发送 Langfuse 数据。异常转为结构化诊断在此完成，保存和导出通过现有 Recorder／Observability 接合。对同一已描述故障继续传播时复用诊断标识 error_id，不因经过多个调用层而重复创建不同原因。

发生故障的 module 根据自身已知的语义提供类别与操作；Error Handling 集中形成一致表达，不能仅凭 OSError 等异常基类断定故障来自文件记录，也不通过匹配英文异常消息猜测业务类别。

这里的 seam，即可以替换错误表达而不修改执行行为的位置，位于“描述故障”处。将原始异常解析和摘要关联放在该 seam 后，可统一修复报错信息；是否继续执行仍留在拥有相应规则的 module，避免错误处理变成第二个生命周期控制器。

依据与取舍：Session 当前根据 OSError 推断 recording 阶段，但异常基类不包含足够的业务位置。明确输入发生位置比增加全局捕获和自动恢复更可靠；代价是调用方必须提供它实际知道的操作信息。[出处：当前 Session 异常捕获](../../../src/uiprobe/session.py)、[讨论实现核查](../../discussions/errors-and-observability.md#当前实现核查)。

## 摘要与完整诊断契约

SessionError 是终端与 SessionResult 使用的简洁错误摘要；SessionResult 是一次测试的返回结果。其目标字段由[共享契约](../contracts.md#提交验收和终态)定义：

| 字段 | 含义与约束 |
|---|---|
| phase | 故障发生的流程阶段，如初始化、执行、验收、清理或记录 |
| operation | 阶段内的具体操作，如导航、实际派发、截图或结果保存；不能只重复阶段名称 |
| code | 可稳定区分的错误类别；不使用原始异常文本作为标识 |
| message | 面向终端的简明原因，能够说明失败了什么；不嵌入整份堆栈 |
| error_id | 同一次故障的诊断标识；摘要、本地诊断与 Langfuse 使用同一值 |

完整诊断保留异常类型、原始消息、异常链和堆栈。异常链是原始异常与后续包装原因的关系，堆栈是异常发生时的调用路径。诊断与摘要通过 error_id 对应；原始异常对象不进入返回结果或持久化数据。

阶段与具体操作来自相同的故障上下文，不应由导出后端再推断。工具 call_id 是框架调用标识，action_index 是已派发动作计数，screenshot_id 是截图标识；已有这些信息时用于关联诊断，不为补齐字段伪造动作、截图或故障。

依据与取舍：用户确认终端保留摘要、完整异常链和堆栈放在本地与 Langfuse。这样终端可以快速定位，复杂细节仍可追查；代价是查看完整堆栈需要通过 error_id 关联。operation 与 error_id 尚未在当前 SessionError implementation 中实现。[出处：讨论确认 8](../../discussions/errors-and-observability.md#已确认)、[现有 SessionError](../../../src/uiprobe/session.py)。

## 核心错误数据流

1. 输入解析、Browser、工具、框架或验收产生明确拒绝／故障，拥有该操作的 module 保留发生位置和原始原因。输入解析的字段问题继续按现有规则聚合，不改成模型修复。
2. 可纠正拒绝通过框架原生反馈返回模型；未派发则不占浏览器动作额度。观测保留原始调用及拒绝原因，包含项目工具包装层执行前被框架拒绝的调用。
3. 无法继续的故障经描述 interface 形成摘要和诊断，按所属执行路径传播。Session 保存主故障，停止后续执行，未取得正常 Submission 时不启动验收。
4. Observability 关联本地与在线诊断。在线失败只标记观测不完整；必要本地写入失败作为独立运行故障交给 Session。错误处理不能以“报错已生成”声称诊断保存成功。
5. Session 在独立短收尾时限内尝试释放资源和保存结果。已有 Submission、Verdict、动作计数和最后成功截图保持事实含义，后续故障不能覆盖它们或主故障。

依据与取舍：传播使用已有框架纠正机制与 Session 生命周期，不建立第三套工具结果或异常控制协议。原始原因保留到形成诊断时，解决跨层通用化丢失信息的问题。[出处：Session 主流程与取消](runner.md#主流程)、[公共工具路径](actions.md#浏览器动作路径)、[Recorder 写入失败](recording.md#写入失败与终态)。

## 各路径的处置契约

HTTP 是网页请求协议，4xx／5xx 状态码分别表示请求错误或服务端错误；flush 指要求观测 SDK 提交待导出的数据。这些事实用于定位，不单独决定测试是否通过。

| 路径 | 必须保留的原因 | 处置 |
|---|---|---|
| 启动与输入 | 文件读取／解析、缺失配置、字段校验的具体位置 | 按现有输入错误返回，不启动模型与浏览器；无目录时不宣称有本地产物 |
| 浏览器初始化 | 启动、导航、首图和保存各自的原因 | 连接失败、导航超时或无首图则终止；HTTP 4xx／5xx 且导航与首图成功则记录状态并继续 |
| 工具预检 | 参数、计划门槛、截图时效、坐标、引用、焦点、等待参数等拒绝原因 | 通过框架交模型纠正，不占未派发动作额度，不自动修正目标或参数 |
| 浏览器动作派发后 | 哪个动作已派发，随后是操作、截图还是写盘失败 | 立即停止后续执行，不自动重放；已派发仍计数，不声称页面没有改变 |
| 模型调用 | SDK／框架最终暴露的连接、协议、拒答或输出不完整原因 | 连接重试归 SDK／框架；项目记录原因，不更换模型或重跑 Agent |
| 预算耗尽 | 哪种额度或共享总时限耗尽 | 按已有框架与会话规则结束；动作额度耗尽可在原循环总结，未正常提交不伪造 Submission |
| 验收 | 无证据、时限耗尽、输出纠正耗尽或模型故障 | 保留具体原因；不能把运行故障写成模型对画面作出的“证据不足”判断；无合法完整输出时全部断言 error |
| 本地保存 | 失败文件操作与已知可用路径 | 停止后续动作，尝试收尾；最终保存失败仍返回内存结果，不假称文件已保存 |
| 清理与外部取消 | 资源关闭故障、取消发生阶段 | 保留已有结论；取消在尝试记录与清理后继续传播，不改成普通成功返回 |
| 在线观测 | SDK 可知的导出失败及最终 flush 情况 | 单独标记观测不完整，测试继续，不覆盖原有错误或 Verdict |

这些处置来自现有 module 的错误语义及讨论确认 4—7、9—10；分类在此汇总，具体参数约束仍由 [Browser](browser.md)、[工具](tools.md)、[Verification](verification.md) 和 [模型连接](model.md)维护。完整情形清单保留在[讨论记录](../../discussions/errors-and-observability.md#错误与应对清单)，不将其中尚未采纳的字段或类别名称自动变成稳定错误码。

## 派发、部分结果与主故障保留

派发指 Browser 完成无副作用预检、占用动作额度后向页面发送操作。派发前拒绝可以安全交回模型纠正；派发后异常不能证明页面未改变，因此不能仅用一个“可重试”标志自动决定重放。操作完成但截图失败时保留最后成功截图，不能把旧图片标为操作后的新证据。

流中断时的部分输出只作为诊断，明确表示未完成，不作为完整提交、工具参数或验收结论。合法验收 failed 或证据不足 error 不触发重试。上述规则分别适配动作副作用和验收结果，不通过统一“出错即重试”处理。[依据：讨论确认 5、6、9](../../discussions/errors-and-observability.md#已确认)、[Browser 派发与故障](browser.md#派发与故障)、[验收输出纠正](verification.md#输出纠正和错误结果)。

原始故障发生后，记录、清理或最终保存可能再次失败。后续故障形成自己的摘要和诊断，不替换主故障的 error_id、原因或主流程 stop_reason；stop_reason 是主流程停止原因。若记录也失败，至少尝试保留内存摘要并向标准错误输出报告，不递归依赖同一个已失败的记录操作。

依据与取舍：当前工具异常处理和 Agent finally 中都可能再次保存材料，后一次异常存在遮住原始异常的风险。分别保留故障会增加诊断条目，但能够解释“执行为何失败”和“证据为何不完整”，也符合 Session 已有多错误契约。[出处：工具错误路径](../../../src/uiprobe/actions.py)、[Agent 收尾](../../../src/uiprobe/agent.py)、[Session 结果与错误](runner.md#结果与错误)。

具体错误码目录、诊断文件布局和异常承载方式在实施前细化；本文不指定新的异常继承体系、重试计数器或自动恢复机制。程序被强制终止且未执行收尾时，只能解释已经记录的事实，不能补造完成事件。

## M1 已采用的本地诊断契约（2026-11-14）

SessionError 的 operation 与 error_id 已实现。Error Handling 的 describe 返回摘要和纯数据诊断；locate 在操作边界保留发生位置及原始异常链，跨层描述同一 LocatedFailure 时复用摘要和 error_id。SessionError 从 session 模块继续可导入，旧构造调用自动补全操作与标识。

Recorder 将每条诊断保存到 diagnostics/<error_id>.json，包含摘要字段、exception_type、exception_message 和 traceback。traceback 包含 Python 原始 cause/context 异常链；字段校验等明确业务失败没有异常对象，相应异常字段为 null，不伪造堆栈。诊断目录列入 artifact_paths。无可用目录只返回内存摘要；诊断保存失败追加独立 recording 错误，不声称诊断保存成功。

首批错误码：invalid_input（validate_input）、startup_failed（read_config/read_case/configure_model）、begin_failed（create_record）、navigation_failed（navigate）、capture_failed（capture_initial）、screenshot_save_failed（save_initial_screenshot）、diagnostic_save_failed（save_diagnostic）。保留已有 run_failed、cancelled、close_failed、append_failed、finish_failed、timeout、finalization_timeout，供后续票据逐路径细化。初始化底层 OSError 不再被推断为 recording；初图与事件写入通过实际写入边界归因。
