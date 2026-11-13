# 测试输入解析

输入解析在浏览器和 Agent 启动前检查测试 JSON 与运行配置，返回合法的会话输入。测试用例包含给定的执行说明和验收断言；Agent 后续生成的 TODO 是执行计划，不属于输入解析的产物。解析不调用模型改写、修复或补充任务。

## Interface 与输入结构

Session 使用 `prepare(test_json, config) -> PreparedSession | InputError`。PreparedSession 包含合法 TestCase 和运行配置；配置中的 data_values 保存引用名到实际值的映射。Session 只将引用名交给 Agent，将实际值注入本次运行的 Browser。

```json
{
  "execution": {
    "goal": "使用测试账号完成登录",
    "instructions": ["填写账号和密码", "提交登录表单"]
  },
  "assertions": [
    {"id": "home_visible", "expected": "显示登录后的首页"},
    {"id": "identity_visible", "expected": "用户菜单显示昵称 Alice"}
  ]
}
```

execution.goal 是非空白目标；instructions 是有序执行说明列表；assertions 是非空断言列表，每项 id 在用例内唯一，expected 是非空白预期。完整对象交给执行 Agent；Verification 只将 assertions 提取后发给视觉模型。

## 严格校验与内部流程

解析先检查 JSON 结构，再校验字段类型和业务约束，最后构造 PreparedSession。每层结构均拒绝未知字段，不能把 expected 误写为 expect 后静默忽略。字段不依赖模型猜测，不将字符串或布尔值冒充整数预算。

首版只接受本文结构，不实现没有实际输入依据的旧格式兼容。未来如需兼容，新增明确格式转换，不自动猜测字段含义。

运行配置包含 entry_url、data_values、max_actions、执行及验收请求额度、通用工具调用及纠正限制、timeout_seconds 和 output_dir 等运行参数。检查 URL、必要字段、类型和正数预算。模型连接和模型角色配置在应用入口装配时确定，不属于每次运行配置，不能有两套模型选择来源。

## 错误表达

InputError 保存能够检查出的字段错误列表，每项包含字段路径与原因；尽量一次返回多个问题，而不是每次只暴露第一项。例如：

```text
execution.goal：不能是空白文本
assertions[1].id：与 assertions[0].id 重复
config.max_actions：必须是正整数
```

JSON 无法解析时只报告可确定的解析错误，不假装已检查其内部字段。错误不得回显原始输入值、实际数据引用值或密钥。自然语言目标是否合理、断言能否从图片判断，分别由执行和验收处理，解析器不推断其含义。

输入与配置全部通过后才允许创建浏览器资源。输入失败仍由 Session 保存可用的错误结果；尚未取得的 TestCase、截图、Submission 或 Verdict 留空。

## M1 已落实的启动契约

run 入口首先记录单调时钟起点。仅在 timeout_seconds 为有限正数且非布尔值时建立截止时间；
仅在 output_dir 为非空白、不含 NUL 的字符串时尝试独占记录目录。
随后 prepare 聚合完整用例及配置错误；目录配置无效时返回内存结果，可用目录则尝试保存。
所有校验完成前不创建 Browser、不请求模型。M1 合法输入由 prepare 返回 PreparedSession；
Session 的合法执行路径在 M2 接入，当前明确返回 execution_unavailable。

SessionConfig 严格接受以下必填字段：entry_url（HTTP/HTTPS URL）、data_values（字符串映射）、
max_actions、execution_request_limit、verification_request_limit、tool_call_limit、
tool_retry_limit、verification_retry_limit、timeout_seconds、output_dir。
六项整数额度必须为正整数，不接受布尔值或字符串；timeout_seconds 为有限正数。
未知字段拒绝；错误仅包含可信字段路径和固定错误码，不包含未知字段名或引用映射键值。
