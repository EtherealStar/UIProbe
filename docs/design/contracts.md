# 会话与 Agent 数据契约

本文定义 UIProbe module 之间共享的数据语义。Session 是从输入准备、浏览器操作、Agent 提交、独立验收到结果保存与清理的一次运行。TestCase 是输入，TODO 是 Agent 的计划，Submission 是执行结束信号，Verdict 才是独立断言判断。以下字段表达目标设计，不表示对应类型已经实现。

## 类型与所有权

| 类型 | 所有者 | 职责 |
|---|---|---|
| TestCase | 输入解析 | 给定执行目标、说明和断言 |
| SessionConfig | Session | 每次运行的入口、数据引用值、预算、时限和输出目录 |
| PreparedSession | 输入解析 | 合法的 TestCase 与 SessionConfig |
| InputError | 输入解析 | 字段路径和安全错误原因列表 |
| TodoItem | Context | 非空白描述与计划状态 |
| Screenshot / BrowserState | Browser 产生，Context 持有最新观察 | 实际图片与同次观察尺寸 |
| Submission | Agent | 正常最终输出，不表达权威验收结论 |
| CheckpointSubmission | Session | 固定的验收断言、截图及提交关联 |
| AssertionResult / Verdict | Verification | 逐项断言判断和程序合成的总状态 |
| SessionError / SessionResult | Session | 阶段故障及整次运行结果 |
| SessionEvent | Recorder | 带运行与调用关联的落盘事实 |

共享数据不导入页面句柄、模型客户端或执行实现。Agent 内部直接使用框架消息、调用、重试类型，不建立 ToolSpec、ModelResponse 或另一套消息协议。

## 输入与运行配置

```json
{
  "execution": {
    "goal": "使用测试账号完成登录",
    "instructions": ["填写账号和密码", "提交登录表单"]
  },
  "assertions": [
    {"id": "home_visible", "expected": "显示登录后的首页"}
  ]
}
```

TestCase 每层结构拒绝未知字段。goal 非空白，instructions 是有序执行说明，assertions 非空，每项 id 唯一、expected 非空白。首版仅接受此格式，不猜测旧字段，不调用模型修复输入。InputError 尽量一次收集可确定的问题，不包含原始秘密值。

SessionConfig 包含 entry_url、data_values、max_actions、执行和验收的框架请求额度、工具调用及纠正限制、timeout_seconds、output_dir 等运行参数。模型连接与角色配置在应用入口装配 Agent、Verification 时确定，不属于 SessionConfig。实际 data_values 只注入 Browser，执行模型只收到引用名。

timeout_seconds 在运行开始时换算为单调时钟绝对截止时间 deadline_at，初始化、执行和验收共享，重试不重置。RunBudget 对执行路径提供 remaining_seconds、claim_browser_action 和 action_count。派发前校验拒绝不计数，校验通过后在实际派发前占用，派发后失败不退还。

## 计划

```text
TodoItem:
    description: str
    status: pending | in_progress | completed
```

description 不为空白，最多一项 in_progress。replace_todo 接收完整列表，全部校验通过后一次替换。首次创建非空列表后 plan_created 为真；之后可清空列表，不重置 plan_created。当前计划是最近完成的有效替换，所有替换均保留记录。

首次浏览器操作前必须有计划；零动作提交无需先创建计划，TODO 未全部完成也不阻止提交。不提供逐项补丁、状态迁移、版本锁或完成项冻结。

## 页面观察与工具

```text
Screenshot:
    screenshot_id: str
    png: bytes
    image_width: int
    image_height: int

BrowserState:
    screenshot: Screenshot
    viewport_width: int
    viewport_height: int
```

图片尺寸是 PNG 实际像素，视口尺寸是同次观察的 CSS 像素，尺寸均为正。首版每次运行固定视口，截图覆盖当前视口，不缩放、不裁剪，不拍视口外长页面。Browser 保存最新成功观察的编号及两组尺寸，以比例将图片坐标转换为 CSS 坐标。

每次 capture 成功生成会话内唯一编号，即使画面不变。Session 装入初始观察，之后仅工具调用层成功取图后更新 Context。取图失败保留最近成功观察但终止执行，不把旧图标记为新图。

| 工具 | 输入 | 语义与校验 |
|---|---|---|
| click | screenshot_id、非负整数 x/y | Browser 检查当前图和范围，换算后点击一次 |
| fill_value | 非空 ref | 引用存在、焦点可填写；覆盖当前输入框原内容，不回传实际值 |
| scroll | 整数 delta_y | 页面级垂直滚动，CSS 像素，正向下、负向上 |
| wait | 正整数 duration_ms | 单次上限与剩余时间内等待 |
| replace_todo | 完整 TodoItem 列表 | 计划整表替换，不改变页面 |

整数参数不接受字符串和布尔值冒充，工具拒绝未知输入字段。浏览器工具声明 sequential=true、metadata.refresh_browser_state=true，保证操作、截图及更新处于同一串行区域；TODO 两者为 false，可并发但遵守屏障。

具体工具只执行操作；公共层执行计划与预算检查、记录和后续截图。Browser 完成自己的预检后才允许占用额度与实际派发。每个工具报告自己的具体错误，由 LLM 决定修改；共用 Agent 工具纠正配置，不另建重试计数器。派发后故障不自动重放。页面操作后不加固定延迟，Agent 可显式 wait；新窗口不自动切换，按执行错误结束。

动作额度耗尽后禁用全部工具，包括 TODO，并在下一次请求提示总结。仍尝试调用则拒绝并反馈，原有循环受框架额度、纠正限制及 deadline_at 约束，不增加独立总结阶段。未正常输出即耗尽请求或时间时不能构造 Submission。

## 完整历史与模型视图

history 是框架原生完整消息历史。messages_for_model 保留完整文本与调用配对，移除历史图片，在请求末尾附加唯一最新图片及 screenshot_id、图片与视口尺寸。发送视图不覆盖完整历史；Recorder 在过滤前保存完整消息与所有图片关联。文本不自动摘要或截断，容量不足是运行错误。

Context 仅是当前运行的内存状态，产物用于复盘，不支持中断恢复执行。

## 提交、验收和终态

```text
Submission:
    text: str

CheckpointSubmission:
    submission_id: str
    session_id: str
    checkpoint_id: str | None
    assertions: immutable sequence[Assertion]
    screenshot: Screenshot | None

AssertionResult:
    assertion_id: str
    status: passed | failed | error
    reason: str
    screenshot_id: str | None

Verdict:
    submission_id: str
    status: passed | failed | error
    assertions: list[AssertionResult]

SessionError:
    phase: str
    code: str
    message: str

SessionResult:
    session_id: str
    test_case: TestCase | None
    status: passed | failed | error
    stop_reason: str
    submission: Submission | None
    action_count: int
    last_screenshot_id: str | None
    verdict: Verdict | None
    artifact_paths: list[str]
    errors: list[SessionError]
```

正常最终文本形成 Submission。Session 为本次验收生成 submission_id，固定断言和最后一张已保存的截图，再调用一次 evaluate。当前终态输入的 checkpoint_id 为空。验收模型只收到冻结的断言和截图，不收到 execution、TODO、执行历史或提交说明。

验收模型只输出 assertion_id、status、reason。程序检查 ID 一一对应、状态合法、依据非空，补截图标识并计算总状态。passed 是可见支持，failed 是明确反例，error 是无法判断。任一 failed 则总判定 failed，全部 passed 才 passed，其余 error。

一次 evaluate 可在验收请求额度和共享截止时间内纠正格式；合法 failed 或 error 不重试。最终输出仍无效时不接受部分判断，为全部断言返回 error。程序不增加模型复核理由。验收结束不恢复执行 Agent。

stop_reason 保留主流程停止原因；errors 记录阶段、类别和安全原因，不保存原始异常对象。执行、清理或本地记录故障使 Session.status 为 error，但已取得的 Submission 和 Verdict 不变。没有这些故障时 Session 使用 Verdict 状态，尚未取得的阶段数据留空。

本地记录失败停止后续操作；最终保存失败仍返回内存结果和已知可用路径。外部取消在尝试记录和清理后继续传播，不正常返回并吞掉取消。截止时间后的保存和释放资源使用独立短收尾时限，不能继续模型或页面执行。

## 记录事实

每次运行独占 output_dir/session_id，目录存在时报错，不覆盖。SessionEvent 使用实际日期时间、session_id 和事件类型；工具事件以 call_id 配对，页面动作另带 action_index 和截图关联。并发按实际开始与完成记录。

先保存 PNG 再写引用事件。history.json 保存执行历史。验收输入、原生历史和实际请求保存在 `submissions/<submission_id>/`。验收诊断和追踪使用同一 submission_id，图片引用 screenshots 内已有 PNG。result.json 保存最终结果。本地不恢复执行。摘要与错误不回显实际输入值，在线遥测不含正文或图片；实际页面截图不承诺自动脱敏。

M1 的错误标识、诊断布局与首批错误码见 [错误处理契约](modules/error-handling.md#m1-已采用的本地诊断契约2026-11-14)。诊断保存于 diagnostics/<error_id>.json，由 Recorder 写入。
