# 执行记录：Recorder

Recorder 保存一次 Session 的可回查材料，包括执行 Agent 历史、全部截图、动作事实、提交、独立验收和最终结果。调用方提交事实；文件布局、图片引用和序列化集中在 Recorder 内，不散落到工具实现。

## Interface 与会话记录

Session 调用 `begin(session_id, output_dir) -> SessionRecord`。SessionRecord 表示本次运行独立的记录，执行路径使用 `append(event, screenshot?)` 增量保存，最终使用 `finish(result, history) -> artifact_paths` 收敛结果与完整历史。验收输入输出以验收事件交给同一记录对象，由 Recorder 写入单独文件。

Recorder 独占创建 output_dir/session_id，目录已经存在就报错，不覆盖、不清空。每次运行由 Session 生成唯一标识，同一用例的多次运行各保留一个目录。

```text
output_dir/
  session_id/
    events.jsonl
    history.json
    verification.json
    screenshots/
    result.json
```

## 内容及关联

| 文件 | 保存内容 |
|---|---|
| events.jsonl | 会话开始、观察、TODO 替换、工具开始与结束、校验反馈、提交、验收、错误及终止；每行一个 JSON 对象 |
| history.json | 执行 Agent 完整框架消息的持久化表达，包括文本、调用、结果和图片编号关联 |
| verification.json | 验收实际收到的断言、最终图片引用、模型返回及格式纠正过程，与执行历史分开 |
| screenshots/ | 全部实际取得的 PNG，按 screenshot_id 关联，不因模型请求过滤而删除旧图 |
| result.json | SessionResult，包括 Submission、逐项 Verdict、终止原因、错误列表与可用产物路径 |

验收图片引用 screenshots 中的现有 PNG，不额外复制。history 使用框架消息类型进行序列化，不建立另一套运行时消息协议。

事件带 session_id、类型和实际日期时间。工具事件以 call_id 关联请求和结果；浏览器动作另有 action_index、输入和输出截图编号。并发工具按实际开始与完成记录，不假定模型提出顺序等于完成顺序。

先保存图片，再写引用它的事件。点击记录图片坐标和实际 CSS 坐标；fill_value 只记录引用名，不保存实际值。TODO 的每次整表替换均记录，不能只留最后一份。

完整消息和图片关联在产生时增量保存，Context 为模型过滤旧图前必须保留原始记录。会话末尾只读取已过滤框架历史不能代替完整记录。模型请求视图只含最新图片，不影响本地全部图片和历史保存。

## 写入失败与终态

本地记录属于运行必要产物。任一次本地写入失败都向 Session 返回明确记录错误和已知可用路径，立即停止后续 Agent 操作。操作已经派发就保留动作计数；不重放，不继续生成无法完整追溯的新动作。

Session 始终尝试清理浏览器，再保存包含清理错误的最终结果。最终结果在同目录写入临时文件后更名，避免读取半份 result.json。最终保存失败时，调用方仍可取得内存中的 SessionResult；不得声称文件已保存。已经取得的 Submission 和 Verdict 保持原值，Session.status 因记录故障为 error。

执行超时或外部取消后，已有材料保存和资源清理受独立短收尾时限约束，不因此继续请求模型或操作页面。外部取消保留取消记录后仍向调用方传播。

本地产物用于复盘，不用于恢复中断执行。Recorder 不重建页面、焦点或 Agent 循环。

## 遥测

Langfuse 是在线调用追踪平台；span 表示一段有起止时间的操作。会话使用根 span，模型请求、工具和验收使用子 span。在线导出只包含标识、摘要、耗时和状态，不包含原始消息、图片、实际引用值或密钥。使用 OTLP 时遵守相同约束。

在线导出失败不改变测试结论，不阻止本地记录。实际 PNG 可能显示页面输入或个人信息，不能把“不在事件中记录实际引用值”误写为图片已自动脱敏。

M1 的错误标识、诊断布局与首批错误码见 [错误处理契约](error-handling.md#m1-已采用的本地诊断契约2026-11-14)。诊断保存于 diagnostics/<error_id>.json，由 Recorder 写入。

故障处置中的二次写入失败由 SessionRecord.writing 暂存为摘要与诊断，保留正在传播的原始异常。验收最终历史保存失败延迟交给 Session 合并，使已经获得的 Verdict 保持。Session 完成必要收尾；应用客户端关闭失败后通过同一记录对象更新结果，更新失败时不再将旧 result.json 列为当前结果。
