# Progress

## Current State

- Status：completed，全部里程碑已验收，计划已归档。
- Final milestone：命令行交付、组合回归和真实模型演示已完成。
- Last updated：2026-11-20，Asia/Shanghai。
- Tracker：本地文件。全部票据为 completed，执行顺序见 [依赖表](execution.md#票据与阻塞关系)。

## Milestones And Batches

- [x] M1：隔离现有验收材料与追踪归属。
  - [x] 01：现有验收路径使用专属记录和固定追踪关联。
- [x] M2：新格式单检查点与串行批次可运行。
  - [x] 02：显式提交的首条完整路径与 SuiteResult。
  - [x] 03：完整预检、覆盖配置和 Case 串行。
- [x] M3：同一执行循环逐段提交并异步验收。
  - [x] 04：逐段公开、响应屏障、有界并发与冻结证据。
  - [x] 05：动作后提交与跨阶段预算。
  - [x] 06：提前结束、执行及单项验收故障独立收敛。
- [x] M4：异步故障与批次收尾可信。
  - [x] 07：后台必要记录故障主动停机和批次停调。
  - [x] 08：硬截止时间、取消快照交接及有界保存。
  - [x] 09：共享资源、追踪和最终保存故障归属。
- [x] M5：命令行交付与真实模型证据齐备。
  - [x] 10：完整样例、组合回归与真实模型演示。

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
- [十张已发布工单](../../../../.scratch/serial-async-agent/issues/)
- [已完成的票据 01](../../../../.scratch/serial-async-agent/issues/01-isolated-verification-records.md)
- [已完成的显式检查点提交](../../../../.scratch/serial-async-agent/issues/02-explicit-single-checkpoint.md)与[批次预检和串行调度](../../../../.scratch/serial-async-agent/issues/03-serial-suite-input.md)
- [已完成的逐段公开与有界验收](../../../../.scratch/serial-async-agent/issues/04-async-checkpoint-pipeline.md)

## Outcomes And Retrospective

单 Case 和有序批次使用同一入口。批次先预检，随后串行运行合法 Case。执行模型在同一循环逐段提交，检查点验收可以与后续页面操作重叠。执行退出后开始释放 Browser，会话在验收和清理全部结束后返回。后台必要记录失败会停止当前 Session 和后续调度。到期和取消会收敛未完成的检查点，Suite 收尾后继续传播取消。共享资源和批次保存故障记录在 Suite。真实模型演示由下一里程碑验收。

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

## 2026-11-20 逐段提交与异步验收实施证据

- 一个执行循环保留 TODO、动作额度、模型请求与工具历史。成功提交后通过原生工具回执公开下一检查点。同一响应内剩余页面动作和提交被拒绝，最后一次提交后禁用所有工具。
- Session 在回执前保存冻结断言和截图引用，并登记验收。验收并发默认 1，可配置为 2 或更高，排队和执行共用 Case 截止时间。真实本地 Chromium 和受控模型的同步点证明验收槽位占满时仍可执行和收到回执。落盘事件证明验收可以乱序完成，最终结果仍按声明顺序，后台验收 span 始终归属 Session。
- 请求与工具额度跨阶段累积。动作耗尽后仍可用最后一次保存的截图提交。每份验收分别使用其请求和纠正额度。超过执行额度时保留原生工具响应及截图引用，Case 无最终执行文本。
- 提前结束时保留已提交、当前未提交及未来未公开的检查点。执行模型故障和关闭浏览器故障不取消已有验收。单项无效输出产生关联的系统 error，合法 failed 和证据不足 error 则保存在各自 Verdict，均不回传执行模型。
- 规范与规格双轨审查复现了回执保存失败后的阶段公开与错误归属问题，以及后台验收 span 的父作用域错误。已修正并补充回归。预算场景改用显式测试参数，实际完成顺序以持久化事件为准。
- 检查点定向测试 `uv run python -m unittest discover -s tests -p 'test_checkpoint_*.py' -v` 发现并运行 9 项，全部通过。
- 全量 `uv run python -m unittest discover -s tests -v` 在当前工作区发现并运行 93 项，69.296 秒，全部通过。从暂存区导出的独立代码快照运行 91 项，62.310 秒，全部通过。工作区额外两项测试来自既有模型服务改动。
- `uv run ruff check .`、`uv run ruff format --check .`（77 个文件）、`uv run pyright`（0 errors）和 `git diff --check` 均通过。14 份执行计划与工单文档中的 49 个本地链接目标均可访问。


## 2026-11-20 后台记录故障、取消交接与批次收尾

- 用受控模型阻塞执行请求，在后台验收写入失败时观察执行被取消、后续 Case 保留为 not_run。两个已取得的 passed 结论保留，排队提交以同一故障标识结束为 error。并发取消仍交付快照，保留实际停止原因。
- 同一单调截止时间传递给页面初始化、执行和验收。请求材料保存跨过截止时间时，执行模型和验收模型均不会发起请求。排队取消及超时回归确认全部验收退出，真实 Chromium 取消回归确认浏览器已释放。
- Suite 保留 Session 内存快照，再关闭共享客户端、导出和保存批次追踪及结果。故障注入覆盖共享客户端创建、关闭异常和超时、追踪与结果写入、重复取消和 CLI 有界退出。真实 HTTP OTLP 接收端观察到一份批次 trace、18 个原生模型请求、各自的 Session 及用量、验收归属和诊断标识，载荷保留文本并排除图片。在线导出失败只标记观测不完整。
- 规范和规格审查复现了 CLI 等待超时线程、取消事件与快照不一致、模型请求跨过截止时间、资源关闭等待失去上限，以及取消与记录故障竞态。上述场景已补回归。
- `uv run python -m unittest discover -s tests -v` 在工作区发现并运行 104 项，通过。最终暂存快照独立运行 102 项，65.053 秒，全部通过。工作区额外两项测试来自已有模型服务改动。最终暂存快照包含追踪中保存超时诊断的回归。
- `uv run ruff check .`、`uv run ruff format --check .`（81 个文件）、`uv run pyright`（0 errors）、`git diff --check`、`git diff --cached --check` 和 CLI `--help` 均通过。14 份计划与工单文档的 49 个本地链接目标均可访问。

## 2026-11-20 命令行组合回归与真实模型演示

- 新样例使用同一生产 CLI 串行运行初图用例和多检查点登录用例。登录用例覆盖入口和密码引用，继承默认账号引用。
- `test_serial_async_cli.py` 的三项组合回归经生产 CLI 及应用入口运行真实本地 Chromium、受控流式模型和受控 OTLP 出口。同步点证明槽位占满时执行仍可收到回执并结束，浏览器关闭后排队验收继续，验收完成顺序可不同于声明顺序。下一条用例打开页面前，首条用例已关闭浏览器、收敛验收并写完结果。
- 单对象失败在真实 CLI 路径返回批次 JSON 和退出码 1，混合批次的 error 返回退出码 2。混合批次覆盖非法条目、普通 failed 和 error 后继续、记录故障中断执行及后续 not_run。动作后提交绑定新截图，同一响应中提交后的动作被拒绝，达到动作上限仍可提交。取消回归确认正在请求的执行和验收退出、排队验收形成终态、批次保存后取消继续传播。组合回归核对并列目录、唯一批次 trace、PNG 引用和 OTLP 载荷。

- 规范审查后改用实际页面打开顺序验证串行，并在验收事件保存后发出完成信号。规格审查后补充了单对象失败的生产 CLI 回归。

- 定向 `uv run --locked python -m unittest discover -s tests -p 'test_serial_async_cli.py' -v` 发现并运行 3 项，全部通过。全量 `uv run --locked python -m unittest discover -s tests -v` 在工作区运行 107 项（75.086 秒），暂存快照独立运行 105 项（68.807 秒），全部通过。工作区额外两项来自既有模型服务改动。
- Ruff 检查、Ruff 格式检查、Pyright、CLI `--help` 和 Git 空白检查均通过。工作区和暂存快照各校验 15 份文档中的 52 个本地链接及锚点。

### 真实模型运行

2026-11-20 01:47（Asia/Shanghai）使用模型 `cline-pass/deepseek-v4.1-flash-1017`，按 README 启动本地页面后运行：

~~~bash
uv run --locked python -m uiprobe --case login-demo/serial-async-suite.json --config login-demo/serial-async-config.json --headed
~~~

CLI 退出码为 0，批次状态为 passed，退出原因为 suite_completed，无运行错误。产物根目录为 `.scratch/serial-async-agent/runs/`，其下保存命令标准输出 `demo-stdout.json` 及以下三个目录：

| 产物 | 目录标识 | 结果 |
|---|---|---|
| 批次 | `2d3c20bbb26d4d489816c54176149525` | `result.json`、`events.jsonl`、唯一的 `trace.json`，trace_id 为 `4788802c5a5cd3bf9bb53cdfe9ba1d9b` |
| 初图用例 | `e1e425374ad245b2bfbde1a2f72afdc3` | `login-page` 引用 `screen-1` 并通过，0 个动作、1 张截图 |
| 登录用例 | `71091ef9cff4491dbc4d0f443a1c5d21` | `before-login` 引用 `screen-1`、`home` 引用 `screen-6`，均通过，5 个动作、6 张截图 |

两条用例均以 execution_completed 结束。检查了真实执行首个请求的阶段可见性、每个提交的验收历史和请求、图片引用及批次追踪。真实运行使用本地追踪。个人 Langfuse 在线验收仍归观测计划。
