# Progress

## Current State

- Status：M1—M3 与跨阶段收尾已实现；真实模型本地演示通过，个人 Langfuse 在线验收待执行。
- Current milestone：M4 / 07 完成，08 的离线与真实模型本地部分完成。用户明确暂不配置 Langfuse，完成其余部分并提交。
- Last updated：2026-11-14，Asia/Shanghai。
- Tracker：沿用已确认的本地文件 tracker；本 feature 草案尚未发布。

## Milestones And Batches

- [x] M1：初始化失败可完整定位。
  - [x] 01 初始化失败可取得具体摘要与完整本地诊断。
- [x] M2：正常测试的本地与 Langfuse 全链路可查。
  - [x] 02 零动作会话贯通本地与 Langfuse 追踪。
  - [x] 03 正常计划与浏览器动作全程可查。
- [x] M3：故障链可解释且不改变执行策略。
  - [x] 04 工具拒绝与派发后故障可区分。
  - [x] 05 模型与验收失败保留完整诊断及可见部分输出。
  - [x] 06 Langfuse 故障可见且不改变测试结果。
- [ ] M4：跨阶段收尾与真实演示验收。
  - [x] 07 跨阶段故障、超时和取消保留原始结论。
  - [ ] 08 完整离线回归与真实 Langfuse 演示。

## Surprises And Discoveries

- Observability／Error Handling 已有正式设计；实现中仍是通用 SessionError 和未启用的全流程追踪。已有 Langfuse／OTel 依赖不表示完成接入。
- 旧 MVP ticket 的状态与 progress 可能不完全一致；本计划以代码及实际测试为起点，不把旧票据修改或关闭作为当前任务。
- 输入、执行、验收与记录已有 53 项回归，流式与有窗口相关变更尚未提交。计划编写不修改这些实现。
- 当前原生流聚合适配、框架前置参数拒绝、应用客户端关闭在 Session 返回后发生，是需要通过首次生产场景验证的接合点。

## Validation Evidence

- 已阅读系统架构、共享契约、两个新 module 设计及相关现有 module 设计，并检查入口、Session、Agent、Browser、Recorder、Verification 与现有测试入口。
- Baseline：`uv run python -m unittest discover -s tests -v`，53 tests，OK，约 24 秒。使用真实本地浏览器与受控模型，无真实模型／Langfuse 调用。
- 计划／草案检查：四份计划文档、8 张逐票草案、35 个本地链接及锚点全部通过；编号、draft 状态、必需字段、依赖有向无环性及无冗余传递边检查通过。所有实施票据均可沿依赖到达最终验收票据，票据正文无具体源码路径或实现代码。
- `git diff --check` 通过；新计划与草案的空白和结构检查通过。文档编写没有修改生产代码。
- 计划编写时未实施功能；本轮 M1 的实现与验证见下方记录。未运行真实 Langfuse 演示。

## Artifacts And Notes

- [计划入口](plan.md)
- [执行与逐票草案](execution.md)
- [决定与待细化事项](decisions.md)
- 草案目录：`.scratch/observability-error-handling/drafts/`，一票一个文件，当前状态 draft。
- 发布目标：`.scratch/observability-error-handling/issues/`；确认后迁移并标 ready-for-agent，不能用草案代替已发布状态。

## Outcomes And Retrospective

跨阶段收尾与真实模型本地演示已完成；用户要求暂不配置个人 Langfuse，08 在线验收保持待执行，计划不归档。

## M1 实施证据（2026-11-14）

完成错误摘要 operation/error_id、纯数据异常链诊断、Recorder diagnostics/<error_id>.json、CLI 文件及模型配置启动失败保存、真实导航拒绝与资源释放。输入业务校验诊断没有伪造异常。无目录时返回内存摘要与空产物路径。初始化 OSError 按发生位置归因。

新增 test_initialization_diagnostics.py：真实 Chromium 连接拒绝、异常 cause 链、CLI 有／无可用目录、初始化超时操作归因。原有输入测试适配新增目录并继续检查其中 JSON 内容。code-review 双轴审查指出的超时归因与启动保存时限问题已修复。静态 Ruff check / format --check 和 Pyright 通过。全量 unittest：57 tests，OK（24.694 秒）。测试不使用真实模型或 Langfuse。

M2—M4、在线导出、真实演示及组合故障仍未完成。草案文件保留，M1 执行不等同批量发布其余票据。

## M2 实施证据（2026-11-14）

正常零动作与登录沿原生框架追踪，应用根覆盖启动、Session、浏览器和模型客户端关闭；本地 trace、原生完整历史、实际发送视图和 PNG 可对应。工具记录原始参数、实际结果、派发计数、输入输出截图、CSS 坐标和时间预算。导航 404 保留状态并继续取得合法 failed Verdict。

零动作两次运行、登录 passed/failed/error 三种结果均保持既有行为。受控 exporter 检查实际 OTLP protobuf：完整文本存在，没有 PNG、图片 base64 或 data URI；原生 chat span 数等于实际模型请求数。真实 OTLP HTTP exporter 连接本地服务并成功提交 protobuf。BrokenExporter 不改变测试结论；阻塞 exporter 的退出等待独立限制为 2.5 秒。

双轴 code-review 发现锁定 SDK 忽略 force_flush timeout 参数，已改为 daemon 线程 flush + shutdown，主线程 join 2.5 秒；修复资源关闭和 ContextVar finally 重置。最终本地追踪写入失败保留内存结果并标记 recording 错误，已保存结果快照可能早于应用收尾，完整组合语义继续由 07 验证。

Ruff check、format --check、Pyright 通过；全量 unittest 60 tests OK（29.616 秒，后续最终复跑见提交时报告）。本地真实 Chromium、受控模型和受控 OTLP 出口，无真实模型或个人 Langfuse 调用。新增 test_observability.py 覆盖 404、在线异常、阻塞退出、真实 OTLP HTTP；扩充既有零动作和应用登录回归。完整失败状态字段、流中断和跨阶段组合故障仍属 M3/M4。

## M3 实施证据（2026-11-14）

完成票据 04、05、06。沿已有未提交接合点补齐框架前置拒绝、动作故障、模型与验收诊断和导出故障状态；保留其余有窗口模式、底层 ModelService 和旧 MVP 文档改动。

- 工具拒绝采用框架原生反馈，包含未知工具、缺失／非法参数和未知字段；既有计划、旧截图、越界、引用、焦点与等待回归继续通过。拒绝可纠正且不扣动作。真实 Chromium 注入派发异常、截图异常、新页面和页面关闭，均保留一个已派发动作及 screen-1，无提交、无后续模型请求和验收；error_id、call_id、动作与截图在诊断及受控 OTLP 出口一致。
- 执行保留原生预算异常类型并附带同一诊断，Session 复用标识。验收缺图、截止时间与无效输出分类；系统错误的全部断言为 error 且附 error_id，合法 failed/error 的请求数不变。模型使用原生流聚合；受控 OpenAI SSE 中断保存一次可见文本和未完成参数，incomplete=true，不执行半份工具。非标准 200 响应停止；连接最终失败观察到 SDK 原生 3 次传输尝试，无项目重试。
- trace.json 单独保存在线故障诊断、观测不完整标志、批次成功／失败数、flush 和远端 unknown；exporter 返回 FAILURE、抛出异常和配置缺失时，真实本地页面的 passed/failed/error 均保持原值。真实 SDK 队列溢出告警、flush false／异常、shutdown 异常和阻塞退出均可定位。flush completed 不覆盖已知失败；2.5 秒超时快照在后台释放后仍为 timed_out。

验证：`uv run ruff check .`、`uv run ruff format --check .`（60 files）、`uv run pyright`（0 errors）和 `git diff --check` 通过。`uv run python -m unittest discover -s tests -v` 发现并运行 70 tests，OK（49.745 秒）。新增 `test_failure_observability.py` 7 项、`test_export_failures.py` 3 项，分别跨生产 Session／原生模型和真实 SDK 导出路径；正常流式测试沿用受控 SSE fixture。另将暂存内容导出到独立目录，排除工作区原有的 CLI 有窗口入口和底层 ModelService 变更后，Ruff check／format（58 files）、Pyright（0 errors）及全量 unittest 67 tests 均通过（40.334 秒）；提交内容可独立运行。无真实模型或个人 Langfuse 调用。

可见性限制：只保留原生 stream.get() 已暴露的部分；若请求流尚未建立，没有可补造的部分输出。SDK 队列日志只能证明其实际报告的丢弃；成功批次或 flush 不能证明远端逐条完整。跨阶段组合故障、取消与应用客户端关闭保留仍由 07 覆盖，真实在线演示由 08 覆盖，M4 保持未完成。

## 跨阶段收尾与演示证据（2026-11-14，Asia/Shanghai）

完成票据 07；票据 08 仅缺个人 Langfuse 真实在线验收。用户要求暂不配置 Langfuse，完成其余部分。

- 派发故障后同时注入错误事件、执行历史、浏览器关闭和最终结果保存失败，最初 click 故障及 error_id 保持；action_count=1、最后截图 screen-1、无 Submission、无后续验收和动作重放。后续故障分别有摘要与可取得诊断。
- 验收传输故障后诊断及历史写入再次失败，原始验收摘要保留；合法 passed Verdict 取得后最终历史保存失败，Verdict 仍 passed、Session 为 error，主 stop_reason 保持 verification_completed。
- 实际应用入口覆盖客户端关闭抛错、五秒关闭超时、关闭后更新结果失败；已取得 Submission、Verdict、动作数和截图保持。更新成功时磁盘与内存摘要一致；更新失败时移除返回路径中的旧 result.json。根追踪覆盖客户端关闭，并关联关闭诊断。
- 真实本地 Chromium 覆盖共享截止时间和外部取消；不形成 Submission、不进入验收，浏览器释放。应用取消与客户端关闭失败组合仍传播 CancelledError，并保留取消快照及根追踪。
- 既有本地不可用目录、独立五秒保存时限、保存中取消、在线故障隔离与真实待导出载荷的图片排除回归继续作为验收依据。

真实模型演示使用 README 的本地 HTTP 页面启动方式与实际 run_files 入口，执行／验收沿生产流式 adapter，共用真实配置。两次均 stop_reason=verification_completed、errors=[]；本地 trace 中 enabled=false、flush=not_requested、remote_delivery=unknown，没有个人 Langfuse 在线证据。

| 用例 | session_id | trace_id | 终态 / 动作数 | 本地材料 |
|---|---|---|---|---|
| 初图零动作 | 01279694ab1443c2aa258e690a43d78d | 0ea0d5bb03fba88f1451765b24cddf38 | passed / 0 | `.scratch/uiprobe-mvp/runs/01279694ab1443c2aa258e690a43d78d/` |
| 引用值登录 | 56acd79e7b444cf990af51aaddbc4e52 | cca711b67dcf96934ca70c0c34d223b3 | passed / 5 | `.scratch/uiprobe-mvp/runs/56acd79e7b444cf990af51aaddbc4e52/` |

本地目录保留 result、全部 PNG、完整历史、实际发送视图、独立验收和 trace；运行产物不提交 Git。真实演示不补记旧 MVP 票据完成。个人 Langfuse 配置、真实导出、在线页面的完整文本／工具／验收／清理及无图片附件检查仍待执行；受控 OTLP 出口与 flush 不能替代这些证据。

最终验证：`uv run ruff check .`、`uv run ruff format --check .`（61 files）、`uv run pyright`（0 errors）及 `git diff --check` 全部通过。新增 `test_combined_failures.py` 6 项，目标测试全部通过（12.957 秒）；全量 unittest 实际发现并运行 76 tests，OK（59.158 秒）。离线测试使用真实本地 Chromium、受控模型和受控导出，不依赖真实凭据；上述两次真实模型演示单独记录。本轮保留原有未提交的流式、有窗口模式、旧 MVP 文档和设计改动，只提交本次实现与记录。
