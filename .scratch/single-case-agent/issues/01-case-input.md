# 用例如何表达业务预期

Type: grilling
Label: wayfinder:grilling
Status: resolved
Assignee: rowla

## Question

现有或拟定的 JSON 中哪些字段表达起始条件、测试意图和预期结果？Agent 如何据此形成执行目标，哪些验收要求必须保留原意？

## Answer

用户提供的登录样例为 JSON 数组，单条记录包含 `title`、`priority`、`case_type`、`is_smoke`、`precondition`、`steps` 和 `expected_result`。此次仅讨论一条记录的执行。

Agent 依据标题、前置条件、业务步骤和原始预期生成目标，并根据每次行动的反馈规划具体操作。优先级、用例类型和冒烟标记是用例元数据。原始预期“登录成功，跳转到首页”保留为验收依据。入口地址和实际账号数据的来源另行决定。
