# 两种断言如何给出用例结论

Type: grilling
Label: wayfinder:grilling
Status: resolved
Assignee: rowla
Blocked by: 01

## Question

谁选择 DOM、独立视觉判断或组合检查？验证时机、证据不足、模型不可用和两种证据冲突时，各应得到什么结果？

## Answer

执行 Agent 可以请求验收。视觉验证由独立 VLM 读取用例原始 `expected_result` 和验收时的截图。使用 DOM 检查的用例由程序提供定位器和预期条件。用例可采用纯视觉、纯 DOM 或组合验收。

所有必选断言通过时，结果为 `passed`。必选检查明确发现实际行为与预期不符时，记为 `failed`。其余必选检查已通过、但一项因模型服务超时等执行故障无法作出判断时，记为 `error`。报告保留每项断言的结果与依据。
