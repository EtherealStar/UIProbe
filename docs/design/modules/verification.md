# 独立验收：Verification

Verification 在执行 Agent 正常提交之后，根据断言和最终截图判断终态。它不操作浏览器、不共享执行 Agent 的历史，也不把执行总结作为证据。Session 一次运行只启动一次 evaluate；验收失败不引起 Agent 返工。

## Interface 与输入隔离

应用入口向 Verification 注入验收模型和固定验收指令，模型配置不来自每次运行的 SessionConfig。Session 调用异步 `evaluate(test_case, evidence_screenshot, deadline_at) -> Verdict`，并提供验收阶段的请求及输出纠正额度。

Verification 从完整 TestCase 提取 assertions，只把全部断言和同一张最终截图作为业务输入交给视觉模型。execution、TODO、执行历史和 Submission 都不发送。固定指令说明逐项状态、证据要求和输出结构。

Screenshot 包含实际 PNG 和截图编号；Session 在提交时选择最新成功观察。零动作提交使用初始截图。缺少截图或共享时间已耗尽时不发起模型请求，为断言返回无法完成验收的错误。

## 模型输出与程序职责

模型只生成每项 assertion_id、status、reason。例如：

```json
[
  {"assertion_id": "home_visible", "status": "passed", "reason": "截图显示首页标题"},
  {"assertion_id": "identity_visible", "status": "error", "reason": "用户菜单未展开，无法确认昵称"}
]
```

| 每项状态 | 含义 |
|---|---|
| passed | 图中存在支持预期的可见证据 |
| failed | 图中存在明确否定预期的反例 |
| error | 证据不足或判断无法完成，不能推测通过 |

程序检查每个输入断言恰好对应一个结果，无遗漏、重复或未知 ID；状态必须合法，reason 不能空白。模型不用生成 screenshot_id 或总状态：Verification 为每项补上输入截图编号，并计算 Verdict.status。

合成规则是：任一项 failed 则 failed；全部 passed 则 passed；其余为 error。合法结果可以同时包含三种逐项状态。程序只检查结构及非空依据，不用关键词判断理由是否支持结论，也不增加第二个模型复核理由。真实视觉判断由验收模型承担。

## 输出纠正和错误结果

一次 evaluate 可以包含受限的格式纠正请求，不等于只允许一次网络请求。使用框架结构化输出机制反馈字段缺失、重复或遗漏 ID、无效状态、空白依据等问题。纠正仍只使用断言、同一张截图和验收自身的纠正反馈，不引入执行历史。

格式合法的 failed 或证据不足 error 是有效判断，不触发重新判断，也不为了获得 passed 而重试。纠正请求消耗验收请求额度并受同一 deadline_at 约束。

若最终仍得不到完整合法输出，包括拒答、不可解析或断言映射错误，整份输出不被接受，不从中拼接部分结论。Verification 为全部输入断言生成 error，说明输出校验失败；原始模型输出和纠正过程保存在验收记录中。传输故障或超时同样形成明确错误结果，不伪造视觉判断。

最终 Verdict 包含总状态和全部 AssertionResult；每项有 assertion_id、status、reason 和可用时的 screenshot_id。Session 保留 Verdict，即使随后清理或保存失败，不能覆盖已有验收结论。

## 预算与记录

验收不消耗浏览器动作额度，模型请求不得超出执行阶段共用的截止时间。一次 evaluate 完成后不拆分断言另行调用，也不恢复执行 Agent。

通过本次运行的 Recorder 保存实际断言输入、最终截图引用、模型输出和格式纠正记录到 verification.json，图片引用已有 PNG，不复制图片。记录与执行 Agent 的 history.json 分离；本地记录失败向 Session 报告，不能把产物写入失败当作视觉判断。

## 已采用的运行依赖接合

Python 实现将本次运行的依赖作为 evaluate 的关键字参数传入：record、request_limit、retry_limit。
构造函数只保存已装配模型；每次 evaluate 独立创建框架 Agent，结构化输出与 ID 验证器使用框架纠正机制。
ProcessHistory 在每次请求前保存原生消息，Hooks.after_model_request 在验证输出前保存模型响应，
包括最终非法响应。未安装 Instrumentation capability，默认不启用在线消息导出。
