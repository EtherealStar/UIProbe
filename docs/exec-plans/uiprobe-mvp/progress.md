# Progress

## Current State

- Status：in progress（M1、M2 已完成）；计划包已编写，10 份 ticket 已发布到本地 issues。
- Current milestone：M3 浏览器动作闭环（尚未开始）。
- Last updated：2026-11-13，Asia/Shanghai。
- Tracker：用户已确认本地；已发布为 ready-for-agent。

## Milestones And Batches

- [x] M1：输入失败可追查（01）
  - [x] 严格输入与 Session 错误路径。
  - [x] 错误记录与独占产物目录。
- [x] M2：零动作提交与独立验收（02、03，可并行）
  - [x] 初始观察到框架最终文本。
  - [x] 隔离断言与 PNG 到 Verdict。
- [ ] M3：浏览器动作闭环（04、05、06）
  - [ ] 计划后点击及派发计数接口。
  - [ ] 引用值登录。
  - [ ] 页面滚动与有界等待。
- [ ] M4：有界执行与完整证据（07、08、09）
  - [ ] 工具禁用及框架预算。
  - [ ] 完整历史及唯一最新图。
  - [ ] 跨阶段失败、超时与取消。
- [ ] M5：命令行 MVP 验收（10）
  - [ ] 应用装配、标准格式样例和 README。
  - [ ] 离线回归及真实模型演示证据。

## Surprises And Discoveries

- 计划建立时已有实现仅为 `src/uiprobe/model_service.py` 和对应测试，其余正式设计不代表实现已存在。
- `login-demo/test-cases.json` 和 `.scratch/single-case-agent/` 使用旧设计，不能直接用来验收新输入契约。
- `GLOSSARY.md` 中“执行目标由 Agent 提取”的旧表述与正式 TestCase.execution 定义不同；本计划以正式设计和共享契约为准。如实施需要更新术语文档，单独按术语规范处理，不把旧表述引入新代码。
- 三处待验证接口接合：预检到动作计数、过滤前原生历史捕获、验收运行依赖；启动配置校验顺序也需补到正式设计。
- M1 开始时工作区干净；本次仅实现输入失败路径及其文档。

## Validation Evidence

- 已阅读 `docs/design/system-architecture.md`、`docs/design/contracts.md` 和全部模块设计；检查现有代码、测试及演示页面。
- 基线命令：`.venv/bin/python -m unittest discover -s tests -v`。执行结果将在基线完成后记录；尚未运行 MVP 功能测试。
- 计划链接、DAG 和 ticket 对应关系的静态校验结果将在编写收尾时记录。

## Artifacts And Notes

- [计划入口](plan.md)
- [实施批次与验证命令](execution.md)
- [执行选择与未决接合](decisions.md)
- [已发布 tickets](../../../.scratch/uiprobe-mvp/issues/)

发布后，实际工作前沿是所有阻塞票据已完成的未完成 ticket。计划的初始前沿为 01；ready-for-agent 只表示规格完整，不代表可越过阻塞边执行。

## Outcomes And Retrospective

M1、M2 均已完成；合法输入经过真实浏览器初图、框架提交和独立验收形成结果。M2 已完成；M3–M5 及真实模型验收尚未执行。

## M1 验证证据（2026-11-13）

- 新增 case_input.py、session.py、recording.py 和 tests/test_session_input.py。
- 单文件：.venv/bin/python -m unittest discover -s tests -p test_session_input.py -v，13 tests，OK。
- 全量：.venv/bin/python -m unittest discover -s tests -v，22 tests，OK。沙箱内在既有 SDK 测试停滞，获准沙箱外执行后通过；不调用真实模型。
- git diff --check 通过。仓库及环境无静态类型检查器，未运行静态类型检查。
- 双轴 code-review 完成；修复未知字段含点号的路径泄漏、极大超时溢出和保存失败后目录读取异常，均有回归测试。
- 测试使用临时目录；独占目录、不覆盖、事件时间关联、原子结果替换及故障后已知路径均有验证。
- 测试编写顺序偏离完整 TDD：初始实现后补测；审查修复使用先失败后通过的回归循环。

## M2 验证证据（2026-11-13）

- 实现固定视口 Browser 初图、原生框架 ExecutionAgent、运行独立 Context、独立 Verification，以及 Session 正常零动作路径。
- 真实 Chromium 加 SDK MockTransport 测试连续两次运行，验证有效 PNG、零动作、初图验收、数据值隔离和借用客户端可复用。
- 验收测试覆盖三种状态合成、全部断言映射、空白理由与非法状态、框架纠正及额度耗尽、缺图、截止时间、拒答、连接异常和记录故障。
- code-review 双轴审查发现并修复重复开始事件、超时归因、传输与记录错误混淆、取消漏存结果；增加回归测试。
- 静态检查：uv run ruff check .、ruff format --check .、pyright 全通过。
- 单文件初图测试：1 test，OK；最终全量：uv --cache-dir /tmp/uiprobe-uv-cache run python -m unittest discover -s tests -v，29 tests，OK。沙箱内框架循环停滞，获准在沙箱外运行；浏览器测试未跳过，无真实模型调用。
- 原生请求与响应分别通过 ProcessHistory 与 Hooks.after_model_request 保存；此版本无 history_processors 或 instrument 构造参数。默认在线观测关闭。
- 测试顺序：验收首条测试先失败后实现；真实页面与错误分支在实现后补测。未声称完整 TDD。
- 后续工作：计划与浏览器动作、动作预算、三次观察过滤、综合故障矩阵和 CLI／真实模型演示仍未实现。
