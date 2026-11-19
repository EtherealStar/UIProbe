# Progress

## Current State

- Status：in progress，M1—M2／01—03 已完成。
- Current milestone：M3，票据 04 可执行。批次资源收尾票据 09 的直接前置也已完成。
- Last updated：2026-11-20，Asia/Shanghai。
- Tracker：本地文件。01—03 为 completed，04—10 为 ready-for-agent，执行顺序见 [依赖表](execution.md#票据与阻塞关系)。

## Milestones And Batches

- [x] M1：隔离现有验收材料与追踪归属。
  - [x] 01：现有验收路径使用专属记录和固定追踪关联。
- [x] M2：新格式单检查点与串行批次可运行。
  - [x] 02：显式提交的首条完整路径与 SuiteResult。
  - [x] 03：完整预检、覆盖配置和 Case 串行。
- [ ] M3：同一执行循环逐段提交并异步验收。
  - [ ] 04：逐段公开、响应屏障、有界并发与冻结证据。
  - [ ] 05：动作后提交与跨阶段预算。
  - [ ] 06：提前结束、执行及单项验收故障独立收敛。
- [ ] M4：异步故障与批次收尾可信。
  - [ ] 07：后台必要记录故障主动停机和批次停调。
  - [ ] 08：硬截止时间、取消快照交接及有界保存。
  - [ ] 09：共享资源、追踪和最终保存故障归属。
- [ ] M5：命令行交付与真实模型证据齐备。
  - [ ] 10：完整样例、组合回归与真实模型演示。

## Surprises And Discoveries

- M1 的单终态路径已使用冻结提交、独立记录和固定追踪关联。PreparedSession、Submission.text 和单次终态验收由 M2 开始迁移。
- 锁定框架在原生工具返回中保存本次格式纠正及反馈。交错测试确认该材料保存在对应验收的历史和第二次实际请求中。
- 旧 MVP progress 仍缺其真实模型验收状态；后续观测计划已有两次真实模型本地演示，并明确没有个人 Langfuse 在线证据。本计划不修改旧计划的状态。
- 计划发布时的工作区已有目标设计及模型、入口和测试改动。M1 以该工作区为基线，沿用已有行为和测试覆盖。

## Validation Evidence

- 已阅读系统架构、完整共享契约、全部模块设计、README、MVP 计划包及观测计划状态；检查输入、Session、Agent／Context、动作、验收、记录、追踪和应用装配的生产代码与既有测试。
- 计划编写时运行 `uv run python -m unittest discover -s tests -v`，实际发现并运行 76 项，全部通过（58.543 秒）。使用真实本地 Chromium、受控模型和本地追踪出口。迁移后的回归结果见下方 M1 实施证据。
- 计划编写时检查了四份计划文档、十张草案和 40 个本地链接及锚点。草案字段、编号顺序、直接阻塞边、有向无环性及最终票据可达性均通过。发布时验证记录见下方。

## Artifacts And Notes

- [计划入口](plan.md)
- [批次、依赖与验证命令](execution.md)
- [执行决定与待验证接合](decisions.md)
- [十张已发布工单](../../../.scratch/serial-async-agent/issues/)
- [已完成的票据 01](../../../.scratch/serial-async-agent/issues/01-isolated-verification-records.md)
- [已完成的显式检查点提交](../../../.scratch/serial-async-agent/issues/02-explicit-single-checkpoint.md)与[批次预检和串行调度](../../../.scratch/serial-async-agent/issues/03-serial-suite-input.md)
- [接续的逐段公开与有界验收](../../../.scratch/serial-async-agent/issues/04-async-checkpoint-pipeline.md)

## Outcomes And Retrospective

单 Case 和有序批次使用同一入口。批次先预检，随后串行运行合法 Case。执行模型可显式提交单检查点，退出后开始释放 Browser 并验收已冻结证据。逐段公开、有界异步验收及真实模型演示按后续里程碑验收。

## 2026-11-15：工单发布

用户确认拆分后，将十张草案按原编号迁移至本地 issues，每张状态更新为 ready-for-agent，交付范围、验收标准及阻塞关系保持不变。同步 execution、decisions 和本页的发布状态；所有实施里程碑仍未完成。

验证：`uv run python` 发布校验实际检查 14 份文档和 41 个本地链接及锚点，全部通过；十份发布文件的 SHA-256 与仅替换状态后的获批草案完全一致。逐票必需字段、直接阻塞编号及标题、依赖有向无环性、无冗余边、最终票据可达性、空白和换行全部通过，drafts 中无残留工单。初始可执行前沿为 01。`git diff --check` 通过。本次仅发布工单和更新文档，未修改 Python，未重复运行测试；上方 76 项结果为计划编写时的基线。

## 2026-11-20 M1 实施证据

- 由现有 Session 固定断言和最近已保存的截图。用 `verdict.submission_id` 定位专属 `input.json`、`history.json` 和 `requests.jsonl`。这些文件引用原图。验收诊断与子 span 使用对应提交标识。单终态路径没有声明检查点或批次，关联仅记录实际存在的标识。
- 新增 `test_submission_records.py`（1 项）。在同一 Session 记录下通过同步点使第二次验收先结束。第一次验收随后纠正无效输出并遇到传输故障。三次实际模型请求均携带各自验收的断言和截图。历史、发送视图、诊断和追踪归属分离，受控 OTLP 载荷排除了图片数据。
- 定向测试用 `uv run python -m unittest discover -s tests -p '<文件名>' -v` 运行。验收 5 项、零动作 2 项、观测 3 项、组合故障 6 项和交错验收 1 项均通过。组合故障回归确认原模型错误和 error_id 在记录二次失败后可查，已取得的 passed Verdict 在最终历史保存失败后保留。
- 全量 `uv run python -m unittest discover -s tests -v` 实际发现并运行 77 项，55.348 秒，全部通过。包含真实本地 Chromium 的零动作、登录和故障回归，模型与追踪出口受控。
- `uv run ruff check .`、`uv run ruff format --check .`（68 个文件）、`uv run pyright`（0 errors）和 `git diff --check` 均通过。真实模型演示由 M5 验收。

## 2026-11-20 新格式单检查点与串行批次实施证据

- CLI 使用同一入口处理单 Case 与有序批次。整份装配校验在创建模型和 Browser 之前完成。条目保留来源位置，重复 ID 的冲突项均非法，已匹配的配置覆盖只影响所属 Case。
- 执行模型通过 `submit_checkpoint` 提交最新已保存的截图。回执前保存断言、截图引用和提交事件。正常最终文本与独立视觉结论分别记录，提前结束时保留未提交状态。
- `test_checkpoint_session.py` 的 3 项定向测试验证未知检查点拒绝、初图复用、回执前持久化、最后提交后关闭工具、提前结束，以及提交写入失败后的停止语义。
- `test_suite_input.py` 的 3 项定向测试验证有序输入、全部重复项拒绝、断言 ID 作用域、覆盖的合并与失败范围。
- `test_suite_runner.py` 的 3 项定向测试使用真实本地 Chromium 和受控流式响应验证串行顺序、入口与填写值隔离、普通失败后继续、批次共享客户端及唯一追踪。另覆盖公共配置错误和必要执行记录写入失败后的停调。
- `test_mvp_e2e.py` 经 CLI 装配运行登录与零动作路径，两条路径均以受控原生流式响应取得 passed、failed、error。真实页面验证动作计数与截图数量，受控出口验证追踪排除图片载荷。
- 规范和规格双轨审查发现的必要写入分类、追踪归属、提交后预算提示、URL 与编码校验、故障标识及零动作覆盖问题均已修正。
- 本阶段的验收由本地 Chromium 和受控模型建立。多检查点逐段公开、受并发限制的验收，以及真实模型演示保留给后续批次。
- 全量 `uv run python -m unittest discover -s tests -v` 发现并运行 87 项，63.718 秒，全部通过。初始化诊断的 4 项定向测试也通过。
- `uv run ruff check .`、`uv run ruff format --check .`（73 个文件）、`uv run pyright`（0 errors）、`git diff --check` 和 CLI `--help` 均通过。计划和工单的 14 份文档中，49 个本地链接的目标路径在当前工作区可用。
