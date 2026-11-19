# Execution

本文定义批次、接合点和验证方法。下表拆分已获用户确认，十张票据已发布至本地 [issues](../../../.scratch/serial-async-agent/issues/)。01—09 已完成。具体源码位置集中在本计划，当前实施和验证记录见 [progress](progress.md)。

## 票据与阻塞关系

| 票据 | 交付行为 | 直接阻塞 | 里程碑 |
|---|---|---|---|
| 01（已完成） | 隔离现有验收材料与追踪归属 | 无 | M1 |
| 02（已完成） | 新格式单检查点显式提交并返回批次结果 | 01 | M2 |
| 03（已完成） | 整批预检后串行运行并隔离 Case 配置 | 02 | M2 |
| 04（已完成） | 同一循环逐段提交并有界异步验收 | 02 | M3 |
| 05（已完成） | 动作后提交与跨阶段预算正确生效 | 04 | M3 |
| 06（已完成） | 执行和单项验收故障各自收敛 | 04 | M3 |
| 07（已完成） | 后台记录故障主动停止当前及后续 Case | 03、04 | M4 |
| 08（已完成） | 硬截止时间与取消快照跨批次收尾 | 03、04 | M4 |
| 09（已完成） | 批次资源及追踪收尾故障归属正确 | 03 | M4 |
| 10 | CLI 样例、组合回归与真实模型验收 | 05、06、07、08、09 | M5 |

只列直接阻塞边。03 与 04 在 02 后分别扩展批次和单 Case；两者集成在 07／08。05／06 不依赖多 Case 调度，09 不依赖多检查点。当前可执行票据为 10。

## M1：隔离现有验收材料与追踪归属（已完成）

### Batch 01：在现有生产路径中建立固定归属（已完成）

检查 `verification.py`、`recording.py`、`observability.py` 和 Session 的验收调用。先抽出验收所需的冻结输入、专属记录句柄和固定子作用域，再让现有单终态路径使用它们；新数据类型按 [共享契约](../../design/contracts.md) 的所有者放置，不建立通用协议。为后续 Suite 根作用域保留接合，当前无 suite_id 的旧路径不伪造批次事实。

每份验收材料有独立输入、历史、发送视图与诊断关联；共享 PNG 使用原图引用。保留主故障、最终历史保存故障及在线告警的分类，不以共享 failures 列表充当未来异步通知。

完成标准：现有零动作、登录及失败回归保持业务结果；通过生产 Verification 的两次受控交错调用，验证不同断言／截图／诊断不串线，已取得的 Verdict 不被后续保存错误改写。此批次是小范围 prefactor，不以批量改名横跨全库。

验证：现有 `test_verification.py`、`test_session_zero_action.py`、`test_observability.py` 和 `test_combined_failures.py`；新增计划测试 `test_submission_records.py`。所有测试仍通过公开生产调用边界，不直接断言私有容器形状。

## M2：新格式单检查点与串行批次可运行（已完成）

### Batch 02：第一条新格式完整路径（已完成）

按 [输入准备](../../design/modules/case-input.md) 在 `case_input.py` 引入目标 Case／检查点及配置契约和 prepare_suite；先贯通单 Case 单检查点的完整成功与非法输入路径。新增 `suite_runner.py`，将资源创建能力、根作用域和最终 Suite 保存接到入口。Case 来源读取移入输入准备，不在根作用域外先读完用例或创建客户端；配置文件及模型配置读取失败也交付批次启动事实。Session.run 改为只接受 PreparedCase，输入错误属于 Suite／输入条目，不创建伪 Session。

在 `observation.py` 和相关拥有者引入 ExecutionOutcome、CheckpointSubmission／Receipt／Result、RunError 和批次结果的首批用途。工具注入 accept_checkpoint 小能力，注册固定 submit_checkpoint(checkpoint_id)，初图也能提交；Agent 正常最终文本只形成 ExecutionOutcome。专属记录、事实保存和验收登记完成后才确认提交；无提交的最终文本形成 execution_incomplete。执行退出后开始 Browser 清理，验收仅依赖固定材料；最基本的取消／清理路径随本批交付。

同步 CLI 装配和最小单检查点样例，保持现有选项、流式请求及退出码；单对象也返回 SuiteResult。应用不在返回后关闭资源并改写 SessionResult。迁移受影响的既有测试，旧输入不保留公共兼容路径。

完成标准：真实本地页面与原生受控模型经入口形成零动作 passed／failed／error；初图只存一次；早停没有伪造提交；输入错误无 Browser／模型调用；单阶段全部提交后工具禁用，最后文本与 Verdict 独立保存。批次记录与会话目录并列，根 trace 保存于 Suite。

验证：迁移现有输入、零动作、MVP E2E 和相关生命周期测试；新增计划测试 `test_checkpoint_session.py`。单检查点之外的完整行为由后续批次验收，不新增永久单阶段模式。

### Batch 03：完整输入预检与 Case 串行（已完成）

扩展 prepare_suite 和 SuiteRunner，覆盖单对象与批次封装、整份聚合、作用域 ID 唯一性、SourceRef、默认配置和按 ID 覆盖。重复 Case ID 的全部冲突项非法；跨检查点可复用断言 ID。验证公共错误与条目错误的边界、未匹配覆盖 ID、未知字段、null、严格数值及默认值不变。

沿生产入口运行“合法 A—非法项—合法 B”，再运行普通 failed／error 后合法项；每个 Session 独占页面、上下文、预算、目录及历史，共享客户端只有一套。上一 Case 的验收、关闭和最终记录全部结束后才开启下一条。公共配置非法时保留可确定的条目错误，其余合法结构项为 not_run，不创建 Session；全部非法时不创建模型资源。

完成标准：输入顺序与报告顺序一致；预检在任何 Browser／模型请求前完成；Case 覆盖实际改变入口和填写值且不污染后条；普通失败后继续；客户端跨 Case 可用；一批仅一份 trace，子作用域不被后条覆盖。

验证：新增计划测试 `test_suite_input.py`、`test_suite_runner.py`，经真实本地页面验证状态隔离、顺序及覆盖，模型使用受控响应。

## M3：同一执行循环逐段提交并异步验收（已完成）

### Batch 04：逐段公开、冻结提交及有界协调（已完成）

在 `session.py` 的 run 局部状态中维护完整账本、验收登记与并发上限；Context 只持有第一阶段及后来成功回执。沿一次 Agent.execute 延续 TODO、原生历史和预算，不为每阶段重建 Agent。按 [提交成立](../../design/modules/runner.md#提交成立与阶段推进) 排列保存、登记、推进及回执；回执失败保留已成立的提交。

动作及提交共用原生串行路径，另外识别模型响应边界；不能仅依赖 sequential。测试同响应“动作→提交→动作／再次提交”，拒绝后两者且不泄露下一阶段；下一轮收到回执才能操作。工具定义不枚举未来 ID，拒绝反馈不解释未来阶段内容。多个阶段可复用同一初图或已保存图。

验收任务在原 deadline 下排队，verification_concurrency 默认为 1，也覆盖 2。用受控同步点阻塞第一验收，证明下一阶段已经操作并提交、排队提交已返回回执；再释放任务并使并发完成顺序与声明顺序不同。图片、断言和记录归属保持固定，最终报告仍按声明顺序。

完成标准：执行与验收可观察地重叠；上限不超配置；重复／未知／非当前拒绝不建新任务；无未来内容泄漏；最终无 queued／running 和后台验收写入。执行正常退出即开始关闭 Browser，不等剩余验收；Session 返回前等待双方收敛。

验证：新增计划测试 `test_checkpoint_pipeline.py`，贯通真实本地页面、原生工具响应及专属验收材料。用 asyncio 同步点与请求计数断言顺序，不凭总耗时或短 sleep 推断并发。

### Batch 05：动作后证据与整条 Case 预算（已完成）

在现有 `actions.py` 包装层中区分动作、TODO、提交三种能力；模型可见工具表和实际调用入口均执行相同限制。保留 Browser 派发计数、操作后截图保存和观察更新，提交不扣动作、不重拍；同响应动作后提交绑定该动作保存的新图。

动作耗尽后禁用动作和 TODO、保留当前提交；最后检查点提交后禁用全部工具。请求、通用工具调用及纠正按整条 Case 累计，提交计通用调用；验收请求／格式纠正按检查点隔离；不重置 TODO 门槛，也不额外保证最终总结请求。

完成标准：最后一次动作仍可提交，派发后失败不重放／不退额度；阶段切换不能刷新额度；请求耗尽保留工具结果历史且无 ExecutionOutcome；每次发送仅最新 PNG，完整历史仍保留全部原生配对和图片引用。

验证覆盖 `test_agent_budget.py`、`test_agent_click.py` 和 `test_context_recording.py` 的现有行为，以及 `test_checkpoint_budget.py` 的同响应剩余调用和两个检查点的额度边界。

### Batch 06：执行结束与局部验收故障独立（已完成）

沿生产 Session 验证并完善提前最终文本、执行模型／派发后故障、单项验收模型故障、合法 failed／证据不足 error 的不同处置。已有提交在执行故障后仍验收；当前未提交为 not_submitted、未来未公开为 not_reached，不给它们伪造 Verdict。验收失败不回传执行、不取消同级、不重试到通过。

保持合法 Verdict 的事实，系统故障为本提交全部断言形成 error 并关联 RunError；执行 stop_reason 不被随后验收／关闭故障覆盖。执行及工具退出后开始关闭 Browser，即使关闭失败，冻结证据验收继续；下一条 Case 是否启动仍由 Suite 的收敛规则控制。

完成标准：受控慢验收跨越执行失败／页面关闭仍完成；兄弟验收及后续执行继续；全部检查点状态和 Session 合成符合契约。包括已完成 failed 与系统 error 共存时 Session error 的优先级。

验证：新增计划测试 `test_checkpoint_failures.py`，复用既有真实 Browser 故障和受控模型传输／格式输出 fixture，不用测试替身直接伪造最终 SessionResult。

## M4：异步故障与批次收尾可信（已完成）

### Batch 07：后台必要写入故障主动停机（已完成）

为 Session 增加私有故障通知及其等待路径，沿提交／验收专属记录传播必要写入失败；不能等执行结束再遍历 failures。故障可发生在输入、请求视图、响应、诊断、最终历史或提交登记，后台故障必须唤醒正在等待 execute 的 Session。

取消并等待执行与验收，保留合法结论，把已接受但未完成项收敛为 error；记录同一故障的 error_id，不让二次写入遮住主因。Suite 停止后续调度，后条合法项为 not_run；在线 exporter 失败使用另一条非业务故障路径。

完成标准：在执行模型请求被阻塞时注入后台保存失败，观察其被取消，没有后续模型／浏览器请求，无残留 queued／running／验收任务；已完成 passed 保留，Case 与 Suite 为 error，后条不启动。记录与清理也失败时仍保留主故障及可用路径。

验证：`test_async_recording_failure.py` 通过 SuiteRunner 和 Session 注入故障，`test_combined_failures.py` 覆盖二次写入失败，`test_suite_finalization.py` 覆盖在线导出故障后继续运行。

### Batch 08：硬截止时间与取消快照交接（已完成）

Session 启动才建立单调 deadline，覆盖初始化、执行、排队、验收；预检耗时不占任何 Case 时间。到期停止业务，排队任务可直接 finished／error；取消并等待已启动任务，清理与保存沿用独立短时限。

实现携带最终 SessionResult 的专用 CancelledError 子类，Suite 接收后保存已运行条目与 not_run，关闭共享资源、收尾批次，再继续传播取消。不得把取消异常写入 RunError 或依赖磁盘重建。覆盖取消发生于执行、排队、验收、Browser 关闭和保存等待，以及 Session 外的输入／共享资源阶段；尚无 Session 时不伪造快照。

完成标准：提交、排队或执行退出均不延长 deadline；到期无新请求；取消不正常返回、已有证据不丢失；最终结果不留活动状态或业务任务；保存线程只处理独立快照，迟到完成不修改已交付对象。重复取消下仍不吞取消或无限等待。

验证：`test_async_lifecycle.py` 和 `test_session_lifecycle.py` 使用阻塞点及可控限时验证排队、资源关闭、保存与重复取消；`test_combined_failures.py` 保留真实 Browser 释放断言。

### Batch 09：批次资源、追踪与最终保存故障（已完成）

沿 SuiteRunner 注入的共享资源创建能力验证创建失败、关闭异常及关闭超时。批次错误保存在 Suite；已结束 Case 的结果、stop_reason、Verdict 和文件不被回写。批次 root 覆盖读取、准备、Session、共享关闭，之后导出并保存唯一 trace，最后保存 SuiteResult。

用两条 Case 和交错验收的固定 scope 检查 suite／session／checkpoint／submission／screenshot 及 error_id；输入错误没有伪造 session_id。受控 OTLP 实际载荷保持完整文本、原生请求计数及图片排除，在线失败只标不完整。必要批次 trace 或结果保存失败保留内存错误与实际可用路径，不递归导出让 trace 包含自身保存结果。

完成标准：正常 Session 在共享关闭／批次保存失败后仍保持原状态；Suite error，最后输出已经含批次故障；在线失败不改变业务结果；2.5 秒出口等待及五秒保存／资源关闭等待有界，迟到线程不改终态快照。

验证：`test_suite_runner.py` 使用真实本地 Chromium 和 HTTP OTLP 接收端验证跨 Case 关联及载荷；`test_suite_finalization.py`、`test_combined_failures.py`、`test_initialization_diagnostics.py` 和 `test_export_failures.py` 验证故障归属及收尾限制。

## M5：命令行交付与真实模型证据齐备

### Batch 10：最终组合验收

更新 `README.md` 与演示样例，清除旧默认格式、SessionResult 标准输出和“验收后才关闭窗口”的说明。保留历史样例时明确其不用于新入口；不提供兼容自动转换。计划新增 `login-demo/serial-async-suite.json`、`login-demo/serial-async-config.json`：两个合法 Case，其中一条至少两个检查点，覆盖初图零动作和引用登录，默认配置通过覆盖给不同入口／引用。

离线用同一 CLI／应用生产入口覆盖 mixed input、passed／failed／error、not_run、同响应动作后提交、并发乱序、错误优先级及不重叠 Case。检查完整产物引用、只有一份 trace、取消仍传播，--headed 参数仍进入工厂；有窗口验证按环境可用性单列。

完成标准：所有静态检查与全量测试通过且确认发现预期测试；真实模型经同一入口完成串行多 Case／多检查点运行，记录模型名、日期、suite_id、session_id、trace_id、结论与可用目录。真实失败保留材料分析，不自动反复重跑到通过。未取得真实证据时本批次保持未完成。

## 验证命令

按批次运行对应测试文件，并确认实际发现并运行了预期测试。例如：

~~~bash
uv run python -m unittest discover -s tests -p 'test_submission_records.py' -v
uv run python -m unittest discover -s tests -p 'test_suite_input.py' -v
uv run python -m unittest discover -s tests -p 'test_suite_runner.py' -v
uv run python -m unittest discover -s tests -p 'test_checkpoint_pipeline.py' -v
uv run python -m unittest discover -s tests -p 'test_checkpoint_budget.py' -v
uv run python -m unittest discover -s tests -p 'test_checkpoint_failures.py' -v
uv run python -m unittest discover -s tests -p 'test_async_recording_failure.py' -v
uv run python -m unittest discover -s tests -p 'test_async_lifecycle.py' -v
uv run python -m unittest discover -s tests -p 'test_suite_finalization.py' -v
~~~

变更 Python 时对实际修改文件运行 Ruff。每个批次均涉及共享契约、跨模块行为或持久化，提交前运行：

~~~bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run python -m unittest discover -s tests -v
git diff --check
~~~

离线回归使用受控模型和真实本地 Chromium，不要求真实模型／Langfuse 凭据。测试总数应包括迁移后的既有行为及本批新增场景；数量减少需要解释被合并覆盖的行为，不把 76 作为永远固定的数字。

真实模型验收先按 README 配置环境，再在独立终端启动页面：

~~~bash
uv run python -m http.server 8765 --bind 127.0.0.1 --directory login-demo
~~~

Batch 10 交付新样例后运行：

~~~bash
uv run python -m uiprobe --help
uv run python -m uiprobe --case login-demo/serial-async-suite.json --config login-demo/serial-async-config.json
~~~

预期：stdout 为 SuiteResult JSON，结果依输入及检查点声明顺序；正常演示退出码 0，受控失败／错误测试分别 1／2。检查批次和会话并列目录、每提交材料、PNG 引用、唯一 trace；真实请求不含未来阶段，验收请求不含执行历史。异步上限与无等待性质由受控门闩回归证明，真实模型快慢不作为唯一并发证据。

## Idempotence And Recovery

中断后从 progress 中第一项依赖已完成的批次继续，每次使用新运行标识和临时目录，不覆盖已有产物。01 可在内部短暂保留旧调用适配以维持回归，02 切换生产入口、03／04 扩展能力后及时移除已无调用的旧形式，10 确认无旧格式公共分支。任何中间适配不提供长期旧结构兼容承诺。

故障注入只在测试中控制真实调用边界，既不更改生产结论也不跳过必要保存。若发现设计矛盾，先更新拥有该契约的正式文档和 decisions，再改实现；不靠额外队列框架或自制模型循环绕过约束。真实演示不可运行时记录具体缺失条件，保留未完成状态，不关闭或改写旧计划票据。
