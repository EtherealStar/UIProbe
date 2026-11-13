# 如何从运行记录复盘一次测试

Type: grilling
Label: wayfinder:grilling
Status: resolved
Assignee: rowla
Blocked by: 03, 04

## Question

本地结果、事件、截图和 Langfuse 中的 span 各保存什么，如何关联一次运行、一次动作与一条断言？

## Answer

每次运行以本地文件为完整记录。JSONL 按轮记录动作、校验与执行结果、耗时、输入和输出截图编号，点击同时记录图像像素与 Playwright 坐标。密码输入仅记录数据引用名。浏览器动作后保存 PNG；校验拒绝的动作可引用已有截图。最终 JSON 记录原始预期、运行状态、停止原因和每项断言的证据。

Langfuse 通过 OTLP/HTTP 接收运行 trace 及模型、动作、验收的子 span。用运行 ID、步骤号及截图编号关联本地记录。PNG 保存在本地。上报失败保留本地证据及原测试结论。
