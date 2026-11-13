# Decisions

## 2026-11-13：以正式设计定义 MVP

Decision：采用 `docs/design/` 的严格输入、框架循环、独立视觉验收和本地证据契约；`.scratch/single-case-agent/` 是历史讨论，不作为实施规范。

Context：旧讨论使用旧用例字段、逐轮一步、Agent 请求验收和可选 DOM 断言，与当前正式设计不同。

Rationale：避免在同一 MVP 中实现两套行为。

Consequences：新增标准格式演示用例，保留旧样例；首版不自动转换旧输入。视觉断言只使用可见证据。

## 2026-11-13：通过纵向交付推进模块实现

Decision：按输入错误、零动作、独立验收、单动作和登录等可验收路径拆 ticket；不为每个文件或基础模块单独建立 ticket。

Context：模块依赖图用于控制代码方向，实施 DAG 用于确定可以开始的交付物，两者不同。

Consequences：共享类型按首次需要引入；02 与 03 可以并行，后续扩展在 04 后分支。框架接合验证放在首次使用它的批次，不增加与全部任务串联的独立研究票据。每票均需测试，跨阶段组合在 09 集中验证。

## 2026-11-13：最小应用入口与范围

Decision：建议 MVP 使用 Python 模块命令行入口、同一客户端装配两个模型角色、固定 Chromium 视口与本地演示页面。执行／验收消息隔离，应用入口负责关闭客户端。在线遥测导出延后，本地记录不可延后。

Context：没有现成 CLI 或 Web 应用；已有模型配置只定义一个连接和模型名称。

Consequences：M5 提供命令与样例；角色独立配置不作为 MVP 门槛。CLI 的 0／1／2 返回码是本计划建议，批准计划后采用；该入口不改变 Session.run 的取消传播契约。

## 2026-11-13：已确认本地 tracker，拆分已确认并发布

Decision：用户明确要求发布到本地；最终发布位置为 `.scratch/uiprobe-mvp/issues/`，每票一个文件，阻塞关系采用编号和标题，状态采用技能的 ready-for-agent。

Context：仓库已有本地 `.scratch` 票据，但没有 `docs/agents/issue-tracker.md` 或 triage 配置。用户本轮已明确发布目标，因此无需再选择 tracker。

Consequences：先在 `.scratch/uiprobe-mvp/drafts/` 保存逐票可审阅草案；确认后迁移为最终 issues 文件，未修改旧票据；不额外运行 tracker 初始化或新增 AGENTS.md。

## 待执行阶段落实：Browser 预检与计数

状态：待 04 的接口接合验证，尚未采用具体实现。

约束来源：[Browser 派发与故障](../../design/modules/browser.md#派发与故障)、[公共执行路径](../../design/modules/actions.md#浏览器动作路径)。

建议：预检通过后、派发前调用外围提供的计数回调；不把整个 RunBudget 或 Session 注入 Browser。替代是显式预检／派发接合，但必须保证同一串行区域内完成，且不重复领域校验。

验证：旧图／越界拒绝计数不变；已派发异常计数保留；额度不足时实际操作次数为零。结论先更新正式设计，计划中只保留执行选择与证据。

## 待执行阶段落实：原生历史捕获点

状态：02 确定可用接点，08 完成多轮过滤验证；未声称当前框架已经满足。

约束来源：[Context 完整历史与发送视图](../../design/modules/context.md#完整历史与发送视图)。

必须在过滤前增量捕获，模型视图不能覆盖完整历史；浏览器工具串行区域必须覆盖截图和更新，TODO 遵守同一屏障。锁定版本无法支持时先修订正式设计，不创建替代模型协议。

## 待执行阶段落实：启动配置及验收运行依赖

状态：分别在 01、03 落实，均不阻塞当前计划编写。

启动配置：run 入口开始计时；先安全校验用于时限和目录的字段，再初始化可用记录；不能因完整用例非法而启动浏览器。目录／超时本身非法时返回内存错误，不声称保存成功。

验收：本次运行的记录对象、框架请求和纠正额度显式作为调用依赖提供，模型仍在构造时装配。不要把本次运行数据存入共享 Verification 实例。

两项都是正式文档尚未明确的接口接合细节；实施时先补充对应正式设计，并记录实际选择，避免产生另一套长期契约。

## 2026-11-13：输入失败路径落地

Decision：使用 Pydantic strict 值类型校验、固定错误码及可信字段路径；Session 仅先校验时限与目录所需字段，再聚合完整输入问题。
Recorder 独占创建目录，以同目录临时文件更名保存结果。配置字段命名与启动顺序已补充正式输入及 Session 设计。

Consequences：错误不回显未知字段名、引用映射键值或底层异常正文。M1 仅实现输入失败路径；
合法输入由 prepare 返回 PreparedSession，Session 正常执行留待 M2。当前没有已配置的静态类型检查器。

## 2026-11-13：初始观察与独立验收接合

Decision：复用应用持有的 AsyncOpenAI 客户端，通过 OpenAIChatModel／OpenAIProvider 接入框架；Session 不关闭借用客户端。
验收的 record、request_limit、retry_limit 每次调用显式传入，实例只保存模型。

Evidence：锁定 Pydantic AI 2.68.0 使用 ProcessHistory capability 和 Hooks.after_model_request；
真实 Chromium 与受控 SDK 响应已贯通连续运行。验收输出使用结构化工具输出和框架 ModelRetry，不手写循环。

Consequences：首图先保存 PNG 后写事件，完整消息将图片转为引用，验收记录独立。
多轮图片过滤保留给 08；工具、动作预算与登录保留给后续批次。无真实模型验收声明。

## 2026-11-13：浏览器动作派发接合

采用 before_dispatch 小型回调，Browser 自身预检通过后调用 RunBudget.claim_browser_action，再实际派发；不注入整个 Session。WrapperToolset.call_tool 包含操作、单次截图、记录及 Context 更新。真实框架同响应 TODO／click／旧图 click 测试证明串行屏障覆盖包装层。wait 单次上限选择 10000 毫秒，剩余时间不足时预检拒绝。

## 2026-11-13：有界执行与原生证据保存

采用 WrapperToolset.get_tools 禁止后续请求使用工具，call_tool 再拒绝同响应剩余调用。
Context 在 ProcessHistory 过滤前保存原生消息，保留观察文本，仅发送最新 PNG。
使用框架 agent.iter 自动推进原有循环，并在退出时读取 all_messages 的未记录尾部，避免请求额度检查早于 ProcessHistory 时丢失工具结果；不创建第二套模型循环。

收尾保留已有结论和主 stop_reason。最终事件和结果保存改为在线程中处理结果快照，Session 使用独立五秒等待上限。超时返回内存错误及已创建会话目录；后台写入不能修改返回对象。内核 I/O 不可由 asyncio 取消，可能稍后完成；约束的是 Session 等待时间。此行为已写入正式 Session 设计，并以阻塞保存回归验证。
