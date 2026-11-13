# 模型连接

模型连接 module 提供兼容 OpenAI 的客户端配置和生命周期。执行 Agent 与 Verification 使用 Pydantic AI 模型 adapter 接入客户端；连接 module 不管理工具循环、上下文、截图筛选或独立验收流程。

## 配置与装配

应用入口读取端点、密钥、模型名称和请求超时，创建客户端，并分别装配执行 Agent 与 Verification。两个角色可以使用不同模型与连接，也可以复用相同连接；角色配置和消息历史始终独立。

Session 对象保存装配好的依赖。每次 run 的 SessionConfig 不再携带模型连接或角色配置；更换模型通过重新装配完成，不在运行过程中替换客户端。

| 角色 | 业务输入 | 输出 |
|---|---|---|
| 执行 Agent | 完整用例、可用工具、数据引用名、完整文本历史和最新截图 | 工具调用或正常最终文本 |
| 验收模型 | 全部断言、同一张最终截图及验收自身的格式纠正反馈 | 每项 assertion_id、status、reason |

应用入口拥有并最终关闭客户端。Session 和工具只借用，不在一次运行结束时关闭客户端，使后续运行可以复用连接。Browser 则由每次运行独立创建和清理，两种资源生命周期不同。

## 请求、预算与错误

请求超时取连接配置时限与 Session 剩余时间允许的范围，不能超过 deadline_at。执行与验收分别使用框架请求额度，共享会话截止时间；纠正请求照常计数。底层 SDK 自动传输重试保持关闭，避免隐藏请求绕过框架计数。

连接、认证、服务端和超时故障向执行 Agent 或 Verification 传播，由其按阶段形成结果，再由 Session 汇总。连接层不自动重跑 Agent，不生成提交，也不把传输故障变成工具参数纠正。

动作额度耗尽时，Agent 在原有循环中禁用所有工具并提示总结，连接层不提供单独总结函数。截止时间或请求额度耗尽后不再请求模型；短收尾时限只供保存与资源释放使用。

## 现有实现与接入方式

src/uiprobe/model_service.py 的 ModelServiceConfig 读取环境变量和 dotenv 配置，环境变量优先。密钥字段不进入 repr。ModelService 持有 AsyncOpenAI 客户端，关闭 SDK 自动重试，提供关闭及异步上下文管理。

complete() 是现有底层单次请求入口，返回 SDK 响应并传播 SDK 异常。Pydantic AI 接入复用 client，不让 Session 重复调用 complete() 来手写 Agent 决策循环。设计接入不表示 Agent 与验收已经实现。

## 记录约束

连接层不保存对话历史。Recorder 分别保存执行历史和验收材料；在线 Langfuse 或 OpenTelemetry 只导出标识、摘要、耗时和状态，不携带原始消息、图片、实际输入值或密钥。模型配置不写入会话 JSON 或普通事件日志。

## 命令行应用入口

python -m uiprobe --case <用例路径> --config <运行配置路径> 读取文件和模型连接配置，创建 ModelService 并在退出时关闭客户端。run_application 借用该服务装配执行与验收，不接管连接生命周期。
标准输出为 SessionResult JSON；passed、failed、error 分别返回 0、1、2。文件读取或模型配置启动错误返回安全内存结果，无产物路径且不启动 Browser。外部取消经 Session 收尾后继续传播。
