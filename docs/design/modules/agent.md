# 测试 Agent 与循环

测试 Agent 阅读完整测试用例，通过工具维护计划和操作页面，最后以最终文本提交。Pydantic AI 负责模型—工具循环、工具输入校验、结果反馈及纠正重试；项目在其执行路径上加入会话规则，不另写一套循环。

## Interface 与装配

Session 调用异步 `execute(context, dependencies) -> Submission`。Agent 在应用入口装配时取得模型和工具集；模型不从每次运行配置中重新选择。dependencies 提供本次运行的 Browser、记录对象和 RunBudget，context 保存用例、数据引用名、TODO、最新观察和框架消息历史。

Submission 只包含正常最终输出文本，表示执行结束，不表示断言通过。模型请求、工具调用、浏览器动作是不同计数：一次 execute 可包含多次请求，一次响应可含多个工具调用；只有点击、填写、滚动和等待占浏览器动作额度。

## 执行与计划

初始输入包含完整 TestCase、数据引用名和初始截图。实际引用值留在 Browser，不作为模型填写的参数。

首次浏览器操作前必须调用 replace_todo，创建至少一项、描述非空白的计划；状态为 pending / in_progress / completed，最多一项 in_progress。公共工具执行层检查 plan_created，未创建就返回可纠正错误，不派发操作。

之后 Agent 可以整体替换或清空 TODO，不冻结完成项，也不要求提交前全部 completed。计划状态是执行进度，不是提交门槛。Agent 可以不做任何浏览器动作就提交，此时也不强制创建 TODO；Session 使用初始截图验收。

浏览器工具为 click、fill_value、scroll、wait，串行执行并在操作后刷新观察。fill_value 覆盖当前焦点输入框，不追加。replace_todo 不刷新截图，允许按框架非串行策略并发，仍遵守浏览器工具屏障。

## 模型输入与工具反馈

每次请求通过 Context 生成消息视图：保留完整文本及调用配对，移除历史图片，在请求末尾附加唯一最新截图，并紧邻说明 screenshot_id、图片尺寸和视口尺寸。完整框架消息与所有截图关联在过滤前保留，不能用发送视图覆盖完整历史。

参数结构由框架校验；工具与 Browser 报告各自业务错误，如旧截图、越界坐标、未知引用、不适合填写的焦点或无效 TODO。公共层报告计划门槛、额度和时间限制。LLM 根据报错自行修改参数或后续操作，项目不替它纠正或自动重放。

所有工具共用 Agent 的工具纠正重试配置，不设每工具独立次数或项目重试计数器。纠正消耗正常框架请求额度并受 deadline_at 约束。操作派发后的故障、截图失败、本地记录失败、新窗口等不能转为参数重试。

## 动作额度耗尽与提交

最后一次允许的浏览器操作及截图完成后，禁用全部工具，包括 TODO。下一次模型请求提示额度已耗尽，要求根据已有观察总结并提交；不额外设计总结阶段或固定一次的专用模型请求。

不再向模型开放工具，执行入口也拒绝仍被提出的调用，包括同一响应里尚未执行的调用。拒绝反馈交回原有循环，由模型返回最终文本；若持续尝试调用，框架请求与工具预算、纠正限制和共享截止时间会终止执行。

正常最终文本直接形成 Submission，不要求额外 submit 工具。TODO 未完成不影响提交。执行 Agent 不注册 verify，Session 在收到 Submission 后启动一次独立验收；验收结果不送回执行 Agent。

额度或时间耗尽而没有正常最终输出时，不构造虚假 Submission。连接、页面操作后故障和记录错误向 Session 传播。外部取消经过 Session 收尾后继续传播。Context 只支持当前运行，不从本地产物恢复中断的 Agent。

## 当前运行依赖

execute 的关键字依赖为 browser、budget、record、deadline_at、request_limit、retry_limit 和 tool_call_limit；Context 保存 todo 与 plan_created。五个原生工具由 FunctionToolset 注册、ActionToolset 包装。浏览器工具 sequential 屏障覆盖包装层中的派发、截图、保存与观察更新；TODO 使用非串行声明并遵守框架屏障。
