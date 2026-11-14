# 运行追踪实现

本文件补充 Observability 模块的已实现配置与持久化契约。

## 正常运行追踪实现（2026-11-14）

应用使用独立 OTel TracerProvider，不修改全局 provider。根作用域早于文件读取，覆盖 Session 和模型客户端关闭；Session 单独调用时建立自己的根。原生 Agent.instrument 使用锁定版本 InstrumentationSettings，完整文本开启、include_binary_content=False；StreamingModel 聚合后的响应由原生能力记录，不再套一层模型 instrumentation。

Recorder 保存 trace.json（trace_id、原生及项目 spans、可知在线告警）、execution-requests.jsonl 和 verification-requests.jsonl（每次实际发送视图，图片替换为 screenshot 引用）。原有历史、PNG、验收及结果布局保留。事件关联 trace_id；工具保留 call_id、参数、实际结果，派发事件保留 action_index 和剩余时间，浏览器记录导航 HTTP 状态、最终 URL 与截图尺寸。HTTP 4xx/5xx 不独立导致失败。

在线采用 Langfuse OTLP HTTP 接口（LANGFUSE_BASE_URL、LANGFUSE_PUBLIC_KEY、LANGFUSE_SECRET_KEY），无公钥时仅本地记录。BatchSpanProcessor 批量投递，HTTP timeout=2 秒，退出在独立 daemon 线程 flush + shutdown，主线程 join 最多等待 2500ms（锁定 SDK 忽略原生 timeout 参数）；不逐条确认远端。初始化及 exporter 异常隔离为观测告警。更完整的故障／取消组合与状态表达仍由后续批次完成。
