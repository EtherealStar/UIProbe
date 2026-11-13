# UIProbe 模块设计

UIProbe 接收测试 JSON 和运行配置，执行一次浏览器测试会话。完整流程是：校验输入 → 初始化页面与上下文 → Agent 规划和操作或直接提交 → 独立验收 → 释放资源与保存结果。提交只表示执行结束，不表示断言通过。

这些文档描述目标设计及 module 的 interface、内部状态、依赖和错误语义，不表示所有代码已经实现。每份文档给出理解自身所需的上下文，不要求读者先阅读讨论记录。

## 模块及 interface

| Module | Interface 与调用方 | 内部职责 |
|---|---|---|
| [Session](runner.md) | 调用方使用 run(test_json, config) -> SessionResult | 对象保存装配依赖，每次运行创建预算、组织生命周期、汇总故障并收尾 |
| [输入解析](case-input.md) | Session 使用 prepare(test_json, config) | 严格校验用例与配置，聚合字段错误，不改写任务 |
| [Agent](agent.md) | Session 使用 execute(context, dependencies) -> Submission | 框架循环、工具纠正、工具禁用与正常提交 |
| [Context](context.md) | Agent 使用状态及 messages_for_model | 完整用例、计划、唯一当前观察、完整消息及最新图视图 |
| [工具调用](actions.md) | Agent 使用框架工具集 | 公共计划门槛、预算、串行操作与截图、记录和工具禁用 |
| [具体工具](tools.md) | 框架调用独立函数 | click、fill_value、scroll、wait、replace_todo 的参数及业务报错 |
| [Browser](browser.md) | Session 和工具调用页面 interface | 单页面资源、数据引用、原始视口截图及坐标换算 |
| [Verification](verification.md) | Session 使用 evaluate(test_case, screenshot, deadline_at) -> Verdict | 隔离输入、验收输出校验、格式纠正及确定性合成 |
| [Recorder](recording.md) | Session 创建记录，执行路径追加，最终 finish | 独立目录、完整历史与截图、独立验收材料及最终结果 |
| [模型连接](model.md) | 应用入口装配并注入模型 | 配置与客户端生命周期，不接管循环或会话状态 |

Agent、Context、工具调用和具体工具构成执行 Agent 的内部划分。Browser、Verification、Recorder 独立提供各自 interface。具体工具按文件组织，不为每个工具再建立完整框架。

## 装配与运行状态

模型在应用入口装配 Agent 和 Verification 时确定，运行配置只包含入口、数据引用值、预算、时限和输出位置。客户端由入口关闭，Session 借用；Browser 与记录对象则按运行独立创建。

Session 的阶段结果使用 run 局部状态，预算通过小 interface 供工具路径使用；Context 不持有页面句柄或整个 Session。共享截止时间覆盖初始化、执行和验收，保存与清理另有短收尾时限。

首次页面操作前需要非空 TODO；零动作可直接提交，未完成计划不阻止提交。浏览器动作额度耗尽后禁用所有工具，包括 TODO，并提示模型总结；仍尝试调用就拒绝，继续受原有请求与时间预算约束，不另建总结阶段。

## 观察、验收与错误

浏览器操作串行完成，随后统一取图。Context 保留完整框架历史，请求末尾只附加最新图片及编号、尺寸。Recorder 保存全部观察，模型视图不破坏本地记录。

一次独立验收只使用断言与最终截图，可以有限纠正输出格式，不因合法失败重试。程序关联截图并合成总状态，不接受最终无效输出中的部分判断。

SessionError 保存阶段、类别和原因；SessionResult 分别保留停止原因、错误列表、Submission 与 Verdict。本地记录或清理故障使会话为 error，但不覆盖既有验收结论。取消经过收尾继续传播，产物不用于中断恢复。

[系统架构](../system-architecture.md) 描述整体调用关系，[共享契约](../contracts.md) 定义跨 module 的数据结构和状态语义。
