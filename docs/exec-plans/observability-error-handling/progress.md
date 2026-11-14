# Progress

## Current State

- Status：M1 implemented；M2—M4 尚未实施。
- Current milestone：M1 完成；下一批为 M2 / 02。用户本轮直接授权执行 M1。
- Last updated：2026-11-14，Asia/Shanghai。
- Tracker：沿用已确认的本地文件 tracker；本 feature 草案尚未发布。

## Milestones And Batches

- [x] M1：初始化失败可完整定位。
  - [x] 01 初始化失败可取得具体摘要与完整本地诊断。
- [ ] M2：正常测试的本地与 Langfuse 全链路可查。
  - [ ] 02 零动作会话贯通本地与 Langfuse 追踪。
  - [ ] 03 正常计划与浏览器动作全程可查。
- [ ] M3：故障链可解释且不改变执行策略。
  - [ ] 04 工具拒绝与派发后故障可区分。
  - [ ] 05 模型与验收失败保留完整诊断及可见部分输出。
  - [ ] 06 Langfuse 故障可见且不改变测试结果。
- [ ] M4：跨阶段收尾与真实演示验收。
  - [ ] 07 跨阶段故障、超时和取消保留原始结论。
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

M1 已按用户授权实施并通过离线验证；M2—M4 继续按票据依赖推进，真实在线验收保持待执行。

## M1 实施证据（2026-11-14）

完成错误摘要 operation/error_id、纯数据异常链诊断、Recorder diagnostics/<error_id>.json、CLI 文件及模型配置启动失败保存、真实导航拒绝与资源释放。输入业务校验诊断没有伪造异常。无目录时返回内存摘要与空产物路径。初始化 OSError 按发生位置归因。

新增 test_initialization_diagnostics.py：真实 Chromium 连接拒绝、异常 cause 链、CLI 有／无可用目录、初始化超时操作归因。原有输入测试适配新增目录并继续检查其中 JSON 内容。code-review 双轴审查指出的超时归因与启动保存时限问题已修复。静态 Ruff check / format --check 和 Pyright 通过。全量 unittest：57 tests，OK（24.694 秒）。测试不使用真实模型或 Langfuse。

M2—M4、在线导出、真实演示及组合故障仍未完成。草案文件保留，M1 执行不等同批量发布其余票据。
