# Execution

本文件只定义实施批次与验证方式；当前实现状态以 [progress.md](progress.md) 为准。票据描述业务行为，具体落点和命令以本计划包及正式设计为准。测试文件名和命令行入口中标为“计划新增”的内容目前不存在，必须随对应批次交付，不能把零测试执行或 import 失败记为通过。

## M1：输入失败可追查（01，已完成）

### Batch 1：严格输入贯通 Session 错误结果（已完成）

在 `src/uiprobe/` 下定义独立值类型、输入解析和最小 Session.run；输入模块不导入 Session 实现。结合 [输入设计](../../design/modules/case-input.md#错误表达)聚合字段问题，拒绝未知字段、重复断言 ID 和布尔值冒充整数。合法配置下，非法用例不创建 Browser，也不请求模型。

启动配置先完成建立截止时间和记录目录所必需的安全校验，再进入完整输入准备；总时间从 run 入口开始计量。配置不合法时返回安全内存结果，可用目录存在时才尝试落盘。先将这一接口接合决定同步到正式 Session／输入设计，避免两份规则。

完成标准：新增 `tests/test_session_input.py`，验证有效及无效 JSON、配置问题、错误聚合和零外部调用。

### Batch 2：错误记录与不覆盖产物（已完成）

实现 Recorder.begin、append、finish 的最小持久化路径；结果先同目录临时写再更名。以独占目录冲突、不可写目录及最终保存失败验证 Session 返回内存结果和已知路径，错误不回显原始输入。session_id、结果、事件的值契约先只补足本路径，后续票据按需扩展。

完成标准：同一输入在独立运行中创建不同目录；已有目录不覆盖；`tests/test_session_input.py` 覆盖保存成功与失败。

## M2：零动作提交与独立验收（已完成）（02、03）

### Batch 1：初始观察到框架最终文本（02）

实现 Browser.open／capture／close、Context 初始状态、框架模型 adapter 和 Agent.execute 的零动作路径；复用现有 ModelService.client。加入首图记录、正常最终文本形成 Submission、资源释放和客户端借用生命周期。Session 测试注入可控验收实现，生产实现不设置假验收默认值。

用锁定环境验证框架原生消息保留和请求处理接点；在 `tests/test_session_zero_action.py` 使用真实本地页面、可控模型响应跑完整会话。此时开始增量保存完整原生消息，后续 08 扩展多轮过滤和重建验证。

完成标准：不调用 TODO 和浏览器动作也能提交，action_count=0，保存初始 PNG，Session 清理 Browser 但不关闭借用模型客户端。多次 run 不串用页面、TODO 或历史。

### Batch 2：断言与 PNG 到 Verdict（03）

实现独立 Verification adapter、结构化输出及记录，按[验收设计](../../design/modules/verification.md#输出纠正和错误结果)处理纠正额度、传输错误及无完整合法输出。验收需要的每次运行额度与记录对象显式传入，不存入复用实例。将具体传递方式补到正式设计。

新增 `tests/test_verification.py`，使用可控模型响应捕获实际请求：断言、图片及自身纠正信息可见，执行信息不可见。覆盖 passed、failed、error 的合成、ID 缺失／重复／未知、空依据、合法失败不重试、非法输出不拼接部分判断、共享截止时间。

完成标准：同一截图完成整组断言判断，独立验收记录引用已有 PNG；记录失败向 Session 报告，不转成模型判断。

## M3：浏览器动作闭环（04、05、06，已完成）

### Batch 1：计划后点击（04）

实现 TODO 整表替换、click 工具和统一执行路径，贯通 RunBudget、Browser 预检及派发、capture、Recorder、Context。先用锁定框架验证浏览器工具串行区域覆盖包装层、TODO 遵守屏障，以及同响应多调用的实际行为，再扩展工具。

派发前计数的建议接法是小型回调：Browser 完成无副作用预检后，实际操作前调用外围注入的计数动作。选择必须先写入正式设计；Browser 不接收整个 Session，也不重复预检规则。若框架或 Browser 更适合显式预检／派发，记录原因并保持相同语义。可纠正错误与致命错误采用明确类型区分，不建立项目重试计数器。

新增 `tests/test_agent_click.py`。模型响应驱动 replace_todo → click → 正常提交；测试断言事件开始／结束配对、截图编号和 action_index。用非 1:1 图片与视口比例证明 CSS 换算，不只在默认比例下测试。

完成标准：首个浏览器动作前有非空有效计划；后续可清空；过期图、越界、无效 TODO 不增加动作数；已派发失败保留计数，不重放；成功动作只 capture 一次。

### Batch 2：引用值登录（05）

加入 fill_value，并从执行说明、模型参数、工具反馈、普通事件和错误中检查实际引用值的流向。只对当前焦点覆盖填写，不自动寻找目标。使用真实页面加可控模型响应完成点击账号、填写、点击密码、填写、点击提交；测试可从 DOM 检查浏览器行为，但 DOM 不作为生产验收通道。

完成标准：`tests/test_agent_login.py` 证明登录后首页可见、覆盖而非追加、未知引用及不适合填写的焦点在派发前拒绝；模型工具 schema 不提供实际文本参数。真实截图按设计不承诺脱敏。

### Batch 3：滚动与有界等待（06）

加入 scroll 和 wait，全部复用统一路径；用测试自带的可滚动本地页面检验页面级 CSS 滚动和正负方向，用可控时钟／短等待检验单次上限及剩余截止时间。参数严格拒绝布尔值、字符串和非法时长。

完成标准：`tests/test_agent_observation.py` 证明两种动作各计一次、各有一个新图编号，画面不变也生成新编号；不存在自动固定延迟。

## M4：有界执行与完整证据（07、08、09）

### Batch 1：额度禁用与有界纠正（07）

补全最后一次动作成功取图后的工具禁用：不向后续请求开放任何工具，执行路径也拒绝同一响应剩余调用和模型继续提出的调用，含 TODO。总结留在原有循环中，受框架请求／工具／纠正额度和 deadline_at 约束。

完成标准：`tests/test_agent_budget.py` 覆盖先执行最后动作再拒绝同响应 TODO／click、正常总结、持续调用而无 Submission、请求额度耗尽。零剩余时间不会发起新请求；没有专用额外总结请求或隐式 SDK 重试。

### Batch 2：完整历史与唯一最新图（08）

扩展 02 已有的原生历史增量捕获，接入 Context.messages_for_model 的过滤视图；捕获点必须在过滤前且不覆盖完整历史。工具只反馈摘要及截图关联，模型请求末尾统一附加一次最新 PNG、编号及两组尺寸。Recorder 集中序列化框架消息，验收文件独立。

完成标准：`tests/test_context_recording.py` 用至少三次观察逐次检查请求仅有最新图、文本及调用配对保留；本地可回查全部原生消息和 PNG，所有引用存在且图片先于引用事件保存。覆盖并发 TODO 的整表有效替换及记录；普通输出不含实际引用值。

### Batch 3：跨阶段失败、超时与取消（09）

集中验证初始化、执行、验收和收尾的组合失败，资源清理始终尝试，独立短收尾时限不延长执行。新窗口、派发后错误、截图失败和本地 append 失败立即停止后续执行；在线遥测失败不影响结果。缺少 Submission 不启动验收。

完成标准：`tests/test_session_lifecycle.py` 证明外部取消最终继续传播，截止时间耗尽后无页面／模型新调用；验收已 passed 后清理或 finish 失败时 Session 为 error，但 Verdict 保持 passed，stop_reason 不被后续错误覆盖，内存结果与可用路径准确。预算耗尽、工具失败及验收失败都能释放资源。

## M5：命令行 MVP 验收（10）

### Batch 1：装配入口与新格式样例

计划新增 `src/uiprobe/__main__.py`、`login-demo/mvp-case.json`、`login-demo/mvp-config.json`、`login-demo/mvp-initial-case.json`，更新 `README.md`。入口读取模型配置并装配 Session，运行参数中不重复选择模型。用例只包含 execution／assertions；登录 config 只使用演示数据引用，示例 entry_url 为 `http://127.0.0.1:8765/login.html`，输出目录为 `.scratch/uiprobe-mvp/runs`。

CLI 接受 `--case` 与 `--config`，向标准输出输出可解析的 SessionResult JSON；passed／failed／error 分别返回 0／1／2。外部取消保留传播语义，不吞掉成普通成功输出。零动作演示用例只要求确认初始登录页面，验证无需先建 TODO 的真实模型路径。

完成标准：帮助信息和 README 能让新执行者安装依赖与浏览器、启动演示页面、提供模型配置后运行；缺少模型配置给出安全错误，不启动浏览器。

### Batch 2：离线回归与真实模型证据

计划新增 `tests/test_mvp_e2e.py`，以真实本地 Browser、真实框架和可控模型响应测试命令行／同一应用装配入口。覆盖登录通过、明确断言反例及不可判断；不要只模拟 Session.run。随后手工运行真实模型命令，保存 session_id、结果和证据路径到 progress。

完成标准：离线测试全通过；至少一次真实登录验收通过，一次真实初始观察零动作验收完成；产物链路可回查。如真实服务未配置，保留 M5 未完成并记录原因，不能把模拟演示当真实验收。

## Validation Commands

以下从仓库根目录执行。开发环境准备命令需要网络；已经安装时无需重复下载。

```bash
uv sync --locked
uv run --locked python -m playwright install chromium
uv run --locked python -m unittest discover -s tests -v
```

预期：依赖按锁文件安装，Chromium 可启动；现有及新增 unittest 全通过。对已有 `.venv`，可用 `.venv/bin/python -m unittest discover -s tests -v` 验证当前环境。

各批次单独验证，使用新增文件对应的 discovery pattern，例如：

```bash
uv run --locked python -m unittest discover -s tests -p 'test_agent_click.py' -v
uv run --locked python -m unittest discover -s tests -p 'test_session_lifecycle.py' -v
uv run --locked python -m unittest discover -s tests -p 'test_mvp_e2e.py' -v
```

预期：运行数量非零，所有测试通过，模型均使用可控响应，浏览器场景使用真实本地页面；缺少浏览器不得静默跳过并宣称 MVP 已通过。

M5 交付上述入口及样例后，在一个终端启动演示页，在另一个终端运行真实模型：

```bash
uv run --locked python -m http.server 8765 --bind 127.0.0.1 --directory login-demo
```

```bash
uv run --locked python -m uiprobe --help
uv run --locked python -m uiprobe --case login-demo/mvp-case.json --config login-demo/mvp-config.json
uv run --locked python -m uiprobe --case login-demo/mvp-initial-case.json --config login-demo/mvp-config.json
```

预期：`--help` 说明参数；登录用例最终首页可见且独立 Verdict=passed、Session.status=passed、返回码 0；初始观察用例 action_count=0 并产生独立验收。实际模型可能多次操作，不固定工具调用次数；两次运行使用不同目录。标准输出中的 artifact_paths 必须指向真实产物，逐项结果关联最终截图。真实模型不稳定造成的失败保留证据再人工判断，不自动重跑到通过。

## Idempotence And Recovery

测试使用临时目录、独立页面和可控响应，结束时释放资源。未完成批次从对应测试和 progress 记录继续，不重复安装无关依赖。运行失败只重启新 Session，不重放已派发动作，不覆盖现有目录。外部模型异常保存当前证据并停止，测试可重复使用同一输入但必须生成新运行标识。

若 02／04 的框架接合验证失败，在继续相应路径前更新 [decisions.md](decisions.md) 并修订对应正式设计；不要用第二套循环或重复的消息协议规避问题。依赖文件或配置变更时，只对受影响批次重新验证，再运行最终回归。
