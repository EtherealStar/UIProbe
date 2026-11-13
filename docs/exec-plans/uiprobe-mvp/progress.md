# Progress

## Current State

- Status：not started（实施）；计划包已编写，10 份 ticket 已发布到本地 issues。
- Current milestone：M1 输入失败可追查。
- Last updated：2026-11-13，Asia/Shanghai。
- Tracker：用户已确认本地；已发布为 ready-for-agent。

## Milestones And Batches

- [ ] M1：输入失败可追查（01）
  - [ ] 严格输入与 Session 错误路径。
  - [ ] 错误记录与独占产物目录。
- [ ] M2：零动作提交与独立验收（02、03，可并行）
  - [ ] 初始观察到框架最终文本。
  - [ ] 隔离断言与 PNG 到 Verdict。
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

- 已有实现仅为 `src/uiprobe/model_service.py` 和对应测试，其余正式设计不代表实现已存在。
- `login-demo/test-cases.json` 和 `.scratch/single-case-agent/` 使用旧设计，不能直接用来验收新输入契约。
- `GLOSSARY.md` 中“执行目标由 Agent 提取”的旧表述与正式 TestCase.execution 定义不同；本计划以正式设计和共享契约为准。如实施需要更新术语文档，单独按术语规范处理，不把旧表述引入新代码。
- 三处待验证接口接合：预检到动作计数、过滤前原生历史捕获、验收运行依赖；启动配置校验顺序也需补到正式设计。
- 仓库当前存在大量未跟踪的用户文件；本次仅新增计划包和 10 份本地 ticket，不修改这些已有内容。

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

当前只完成计划编写和票据草拟，未实现 MVP，也未完成真实模型验收。批准拆分并发布后，从 01 开始；每个批次完成时在本文件记录命令、实际测试数、产物及未解决问题。全部验收完成后整体归档计划包。
