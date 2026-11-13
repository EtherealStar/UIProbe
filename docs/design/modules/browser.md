# 浏览器控制：Browser

Browser 隐藏 Playwright 页面操作、观察尺寸和实际输入值。Session 每次运行创建一个 Browser 实例，并在结束时释放它；页面句柄不暴露给 Agent。Agent 只看到 BrowserState，即截图和同次观察的视口信息。

## Interface 与内部状态

| Interface | 调用方及语义 |
|---|---|
| open(entry_url, data_values, deadline_at) -> BrowserState | Session 创建本次运行的页面、导航并取得初始观察 |
| click(screenshot_id, x, y, deadline_at) | click 工具使用图片坐标点击一次，返回图片与实际 CSS 坐标摘要 |
| fill_value(ref, deadline_at) | 将当前焦点输入框的内容替换为引用值 |
| scroll(delta_y, deadline_at) | 按 CSS 像素垂直滚动页面，正数向下、负数向上 |
| wait(duration_ms, deadline_at) | 在单次上限与剩余时间内等待 |
| capture(deadline_at) -> BrowserState | 工具调用层获取新的页面观察 |
| close() | Session 释放本次运行的页面及浏览器上下文 |

实例内部保存本次运行的浏览器上下文与单个页面、数据引用表、最近成功观察的截图标识及图片和视口尺寸、截图编号计数器。视口在创建时确定，运行中不主动调整。模型客户端与会话历史不属于 Browser。

首版只管理单页面。操作触发新窗口或新页面时，报告不支持的执行错误并结束运行，不自动选择或切换页面；清理仍释放本次运行创建的资源。

## 操作与截图的关系

open 组合初始化导航和首图；后续 click、fill_value、scroll、wait 只完成自身操作。工具调用层在同一串行区域调用 capture，保存图片并更新 Context。具体工具不再单独截图，避免一次操作生成两次观察。

点击或填写返回后直接截图，不增加固定延迟，也不额外等待页面稳定。底层操作自身所需的等待仍保留。截图可能显示加载中的页面；Agent 根据观察决定是否调用 wait。截图表示观察时点的画面，不保证页面此后不变。

## 截图与坐标

Screenshot 包含 screenshot_id、PNG 字节、image_width、image_height。BrowserState 还包含 viewport_width、viewport_height，后两者使用 CSS 像素，即页面布局坐标单位。

首版截图覆盖整个当前视口，使用原始图片尺寸，不缩放、不裁剪，不拍超出视口的完整长页面。图片尺寸与 CSS 视口尺寸分别保留，Browser 根据同次观察的比例换算：

```text
css_x = x * viewport_width / image_width
css_y = y * viewport_height / image_height
```

Browser 保存最近成功观察的尺寸，因此 click 不需要传入 PNG 或整个 Screenshot。Browser 在派发前检查 screenshot_id 是否为最近成功观察、x/y 是否位于图片内，再完成换算。调用方不重复实现这些规则。

每次 capture 成功产生会话内唯一截图编号，即使画面没有变化。只有成功取得观察才替换内部观察信息。截图失败保留旧观察，不把旧图片标记成新的。

## 填写、滚动与等待

fill_value 的 ref 是数据引用名，例如 login_password。实际值由 Session 在 open 时注入 Browser，不发给模型。操作覆盖当前焦点输入框的原有内容，不追加；调用前由 Agent 点击目标输入框。

Browser 不自动寻找其他输入框或重新点击。未知引用、填写前能确认的非可填写焦点，属于派发前的可纠正错误。工具结果和事件只返回引用名，不回传实际值。对实际图片不作“绝不会显示输入值”的保证，截图仍是页面真实观察。

scroll 只作用于页面，不提供滚动容器选择参数。wait 使用正整数毫秒，并检查单次等待上限和会话剩余时间。两者完成后同样由外围层取图，并消耗一次浏览器动作额度。

## 派发与故障

导航、操作与截图使用 deadline_at 的剩余时间。Browser 在实际派发前完成自身无副作用校验，工具执行路径在这些校验通过后才占用动作额度。校验与派发、后续截图均位于同一串行执行区域。

错误必须区分派发前拒绝、操作已派发后的故障、后续截图故障。派发前拒绝可反馈给 LLM 决定纠正；派发后的故障结束执行，不能自动重放。实现需要把实际派发时点与预算占用接在一起，不能先计数再把本可预检的错误当成已执行。

执行超时或失败后 close 仍会被调用，使用 Session 的短收尾时限；这不允许继续页面操作。

## 派发接合实现

动作方法额外接收 before_dispatch 无参数回调。Browser 完成无副作用预检后，在同一串行区域、实际页面操作之前调用它；外围传入 RunBudget.claim_browser_action。回调拒绝时不派发，派发异常不退还额度。wait 单次上限为 10000 毫秒，等待不得占满剩余时限。测试可配置 device_scale_factor 验证原始图片与 CSS 视口比例。
