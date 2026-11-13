# 具体工具实现

工具是测试 Agent 可以调用的有类型函数，使用 Pydantic AI 注册和依赖注入。每个工具的参数、说明及业务报错放在自身实现中；公共执行层处理预算、计划门槛、记录与操作后截图。LLM 根据具体报错自行决定如何修改参数或后续操作，项目不代替它生成纠正方案，也不自动重放操作。

## 工具 interface

下表省略框架依赖参数。整数使用严格输入类型，拒绝字符串和布尔值冒充；拒绝未知输入字段。

| 工具 | 模型填写的参数 | 单次语义 |
|---|---|---|
| click | screenshot_id: str, x: int, y: int | 按当前图片上的非负整数坐标点击一次 |
| fill_value | ref: str | 将当前焦点输入框内容替换为引用对应的完整值 |
| scroll | delta_y: int | 按 CSS 像素垂直滚动页面，正数向下、负数向上 |
| wait | duration_ms: int | 按正整数毫秒执行一次有界等待 |
| replace_todo | items: list[TodoItem] | 校验并整体替换计划列表 |

click、fill_value、scroll、wait 均声明 sequential=true 和 metadata.refresh_browser_state=true，保证操作及后续截图在同一串行区域完成，并占用一次动作额度。replace_todo 两者均为 false，不刷新截图，不占浏览器动作额度，但仍受框架工具调用预算约束。

## 浏览器工具

click 调用 Browser.click(screenshot_id, x, y, deadline_at)。当前图编号、坐标范围和图片到 CSS 坐标换算由 Browser 统一处理，工具不传 PNG，也不重复换算。一次调用只点击一次。

fill_value 的工具说明必须表达覆盖语义：将当前获得焦点的输入框内容替换为 ref 对应的完整值，调用前先点击目标。工具不接受实际文本；Browser 从本次运行的数据引用表读取值。焦点不适合填写时不自动搜索或切换目标，返回具体错误。工具结果只包含引用名，不包含实际值。

scroll 使用页面级垂直滚动，不增加容器选择或自动寻找目标。wait 受单次等待上限与共享截止时间约束。操作返回后不额外添加固定延迟，Agent 可根据新截图显式等待。即使画面不变，成功取图也生成新编号。

浏览器工具只负责操作，统一执行层负责后续 capture、保存截图、更新 Context 和构造反馈。成功摘要包含工具名、输入和输出截图编号；点击的实际 CSS 坐标和耗时进入 Recorder。图片由 Context 的模型发送视图统一附加，避免重复发送。

## TODO 工具

TodoItem 包含非空白 description 和 pending / in_progress / completed 状态，最多一项 in_progress。首次创建必须至少一项；只有这次有效替换完成后才允许浏览器操作。之后可以清空列表，plan_created 不因此重置。

replace_todo 在全部校验通过后一次赋值替换列表，返回保存后的完整列表。允许并发，当前计划采用最近完成的有效替换；各次完整输入与结果均保留。并发仍遵守浏览器工具的串行屏障。

不提供逐项补丁、状态迁移表或完成项冻结。TODO 未全部完成不阻止提交；Agent 可以零浏览器动作直接提交，此时也不强制先建 TODO。动作额度耗尽后 TODO 与所有其他工具一起禁用。

## 错误职责

工具参数格式由框架校验；每个工具报告自己的业务错误，Browser 提供点击、引用值和焦点等操作错误。公共层只报告未建计划、额度耗尽、超时等共同限制。

派发前能确认的问题通过框架纠正反馈交给 LLM，不占动作额度。所有工具使用统一的 Agent 工具纠正重试配置，不增加每工具独立次数或项目级重试计数器。操作已派发后的故障、新窗口和截图失败结束执行，不反馈成可自动重试的参数错误。错误不得回显实际密码或任意原始输入值。

## 文件组织

```text
agent/
  tools/
    click.py
    fill_value.py
    scroll.py
    wait.py
    todo.py
  tool_calling.py
  context.py
  loop.py
```

这是 implementation 的组织方式，不要求每个工具建立一套 module 框架。执行 Agent 不注册 verify 工具，独立验收由 Session 在提交后启动。
