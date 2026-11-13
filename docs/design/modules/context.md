# 上下文管理：Context

Context 保存单次运行中供执行 Agent 与工具共享的数据，并构造模型请求视图。Session 管生命周期、截止时间和预算；Browser 管页面及实际输入值；Context 管用例、计划、观察和消息历史，不成为所有运行状态的容器。

## 内部状态与 interface

| 字段 | 含义 |
|---|---|
| test_case | 已通过校验的完整用例，含 execution 和 assertions，执行 Agent 可以读取全部内容 |
| ref_names | 允许使用的数据引用名，不包含实际值 |
| todo | 最近完成的有效整表替换 |
| plan_created | 是否曾成功创建非空初始计划 |
| browser_state | 唯一当前 BrowserState，含截图和同次观察的视口尺寸 |
| history | 框架原生消息历史，保留文本、工具调用、结果及图片观察 |

interface 按职责表达为 replace_todo(items)、update_browser_state(state)、messages_for_model(history)。这些操作不要求各自建立 adapter 类。框架 RunContext.deps 只是获取本次运行依赖的载体，不是另一个会话或 Context 副本。

## 观察的单一更新入口

Session 用 Browser.open 返回的初始观察创建 Context。之后只有工具调用层在成功 capture 后调用 update_browser_state；具体工具只执行操作，不能自行替换观察。

操作、截图和观察更新位于同一串行区域。成功观察带新的 screenshot_id，即使画面没有变化。派发前校验拒绝保持当前观察；派发后截图失败也保留最近成功观察，但运行终止，不把旧图重新编号或假装成操作后的新证据。

Browser 保存最近观察的尺寸以校验点击与转换坐标，Context 持有供 Agent 和最终验收使用的 BrowserState；两者都只接受实际成功取得的观察。

## 完整历史与发送视图

history 使用 Pydantic AI 原生消息类型，不自定义 Message、ToolCall 或 ToolResult 协议。Recorder 负责将这些消息序列化到本地并把图片关联到独立 PNG 文件。

每次请求前，messages_for_model 构造副本或等价视图：

1. 保留完整文本、工具调用及结果配对，不摘要、不自动截断。
2. 从历史消息中移除图片内容，历史截图编号与动作文本仍可保留。
3. 在本次请求末尾统一附加当前最新截图一次，旁边说明 screenshot_id、图片像素尺寸与 CSS 视口尺寸。

例如历史有三次观察，模型请求只带第三张图片；本地仍保存三次观察及其关联。旧截图编号只是历史事实，不能用作新的点击依据。图片使用框架支持的多模态内容表示，不改变调用和结果的合法配对。

通过框架消息处理机制挂接视图构造。完整消息必须在过滤之前保存；若框架保存的是处理后的消息，不能在会话末尾把该副本当成完整历史。具体工具反馈以摘要和截图关联为主，最新图片由视图统一附加，防止重复发送。模型上下文容量不足作为运行错误，不悄悄压缩文本。

## TODO 整表替换

TodoItem 包含非空白 description 和 pending / in_progress / completed 状态，最多一项 in_progress。首次创建必须非空；全部校验通过后一次赋值替换 todo，并设置 plan_created。之后允许空列表，plan_created 不回退。

replace_todo 允许并发，不设置串行标记，仍遵守浏览器工具屏障。当前列表对应最近完成的有效替换，每次输入和结果都进入历史。不增加版本锁、补丁协议、状态迁移表或完成项冻结。

TODO 不修改 BrowserState、不占浏览器动作数。未全部完成不阻止提交；零动作提交无需创建计划。动作额度耗尽后全部工具被禁用，TODO 也不能继续更新。

## 生命周期和验收隔离

Context 是当前运行的内存状态，不支持进程中断后从记录恢复执行。本地产物用于复盘，不承担页面、焦点和动作恢复。

Session 在正常提交后取最新 Screenshot 交给 Verification。Verification 不读取 Context 历史、TODO 或 Submission，只把断言和该截图交给视觉模型。执行与验收的记录分别保存。

## 初始观察路径的框架接点

零动作路径使用 ProcessHistory 保存请求前原生消息，以 Hooks.after_model_request 捕获响应，
在输出被接受或拒绝之前保存。Context.history 持有原生消息，Recorder 将 BinaryContent 替换为已保存 PNG 的截图引用。
后续多观察过滤仍按上文规则扩展；初始观察路径尚不提供工具或计划替换。
