# Progress

## Current State

- Status：in progress（M1、M2、M3、M4 已完成）；计划包已编写，10 份 ticket 已发布到本地 issues。
- Current milestone：M5 命令行 MVP 验收（尚未开始）。
- Last updated：2026-11-13，Asia/Shanghai。
- Tracker：用户已确认本地；已发布为 ready-for-agent。

## Milestones And Batches

- [x] M1：输入失败可追查（01）
  - [x] 严格输入与 Session 错误路径。
  - [x] 错误记录与独占产物目录。
- [x] M2：零动作提交与独立验收（02、03，可并行）
  - [x] 初始观察到框架最终文本。
  - [x] 隔离断言与 PNG 到 Verdict。
- [x] M3：浏览器动作闭环（04、05、06）
  - [x] 计划后点击及派发计数接口。
  - [x] 引用值登录。
  - [x] 页面滚动与有界等待。
- [x] M4：有界执行与完整证据（07、08、09）
  - [x] 工具禁用及框架预算。
  - [x] 完整历史及唯一最新图。
  - [x] 跨阶段失败、超时与取消，以及独立有界的收尾保存等待。
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

M1、M2 均已完成；合法输入经过真实浏览器初图、框架提交和独立验收形成结果。M2 已完成；M4–M5 及真实模型验收尚未执行。

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

## M3 验证证据（2026-11-13）

- 实现 TODO、click、fill_value、scroll、wait，原生 FunctionToolset／WrapperToolset 统一计数、取图、保存和观察更新；Session 汇总动作数与最终截图。
- 新增三个 agent 测试文件，共 7 项：真实 Chromium 非 1:1 点击、计划门槛和同响应屏障、旧图／参数拒绝、派发失败保留计数、引用值覆盖登录、页面正负滚动与有界等待。
- 首条比例点击测试先失败后实现；其余覆盖在接口接合后补测，未声称完整 TDD。
- 全量 unittest 36 tests，OK；真实浏览器无跳过、受控模型无真实服务调用。沙箱限制浏览器启动，经批准在沙箱外运行。
- Ruff check、format --check、pyright 和 diff --check 通过。
- code-review 双轴审查：修复截图按图片内容误关联、模型工具说明缺失、输入／输出截图及耗时字段缺失。保留未过滤原生历史；唯一最新图片过滤与三次观察重建由 M4 完成，不提前宣称通过。
- 后续动作额度禁用、综合失败矩阵、CLI 和真实模型验收仍未完成。

## M4 验证证据（2026-11-13）

- 实现动作额度后的全部工具禁用，包括同响应 TODO／click；总结留在框架循环，持续调用受请求额度限制。
- Context 保存过滤前完整原生历史，发送视图仅保留最新 PNG；框架 iter 的最终状态补存请求耗尽时的工具结果。
- 新增 test_agent_budget.py（4 项）、test_context_recording.py（2 项）、test_session_lifecycle.py（5 项），覆盖三次观察、历史尾部、真实浏览器截图／新窗口／派发／记录故障、独立验收通过后清理失败、超时和取消传播。
- 全量：uv --cache-dir /tmp/uiprobe-uv-cache run python -m unittest discover -s tests -v，47 tests，OK。真实 Chromium 在批准的沙箱外环境执行；无真实模型调用。
- 双轴 code-review 修复总结提示遗漏、额度耗尽时历史尾部遗漏及过期截止时间仍启动截图的问题。
- 测试顺序：额度测试与历史尾部回归先失败后修复；其余场景在接合后补测，未声明完整 TDD。
- 收尾事件与结果保存在线程中处理独立结果快照，Session 最多等待五秒；阻塞保存回归验证有界返回且后台完成不能修改返回对象。内核文件 I/O 可能稍后完成，超时结果不声明 result.json 已保存。M4 已完成，M5 未开始。
- Ruff check、format --check、Pyright 与 git diff --check 均通过。
- 最终保存等待期间的取消先尝试完成已有写入，再保存取消结果并传播；回归验证 Verdict 保持 passed，而保存结果为 cancelled/error。

## M5 入口与离线验证（2026-11-13）

- 提供 python -m uiprobe 的 --case／--config 参数、SessionResult JSON 和 0／1／2 退出码；应用持有并关闭模型连接，Session 借用客户端。缺少模型配置不启动浏览器，取消保持传播。
- 新增登录、初图零动作标准用例及演示运行配置，README 补齐 Chromium 安装、页面启动、模型配置与运行命令。
- test_mvp_e2e.py 经同一应用装配入口、真实 Chromium 与 SDK 受控响应验证登录和 passed／failed／error；测试在关闭前观察 Home 文本，检查六张 PNG、保存结果及独立验收记录。CLI 检查 JSON 和三种退出码。
- Ruff check、format --check 和 Pyright 通过。首次定向测试因沙箱禁止 HTTP socket 失败，获准沙箱外运行后 2 tests 通过；新增退出码测试后以最终全量结果为准。
- 双轴审查发现登录页面状态缺少断言及 CLI 成功／失败退出码未覆盖，均已补齐。
- 测试顺序：装配实现后补集成测试，未遵循完整 red-green；用户确认采用计划规定的应用入口测试边界。
- 真实模型命令已尝试，返回 configuration_error、退出码 2，action_count=0、artifact_paths=[]。当前环境未提供完整模型配置，不保存或输出密钥。未运行真实登录及真实初图验收，无对应 session 产物证据，M5 保持未完成；计划目录不迁移到 completed。
- 最终全量：uv --cache-dir /tmp/uiprobe-uv-cache run python -m unittest discover -s tests -v，50 tests，OK；真实 Chromium 无跳过，受控模型不访问真实服务。完整回归获准在沙箱外执行。help 与 git diff --check 通过。
