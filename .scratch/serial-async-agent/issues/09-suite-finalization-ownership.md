# 09: 批次资源及追踪收尾故障归属正确

**What to build:** 批次共享模型资源、追踪或最终保存出现故障时，调用方收到已经包含这些故障的 SuiteResult；已结束 Case 的视觉结论和记录保持原样，全批追踪可以准确关联每条运行。

**Blocked by:** 03 整批预检后串行运行并隔离 Case 配置.

**Status:** completed

- [x] 共享资源创建、关闭异常及关闭超时只归 Suite，不追加到最后 Case；未启动的合法项有明确 not_run 原因，已结束 Session 不被回写。
- [x] 根 trace 覆盖输入准备、共享资源创建、各 Session 及客户端关闭；业务关闭后导出并保存批次唯一完整 trace，随后保存 SuiteResult。
- [x] 固定作用域准确携带实际 suite／session 及适用的 checkpoint／submission／screenshot／error 关联；非法输入不伪造会话标识，后续 Case 不覆盖前条归属。
- [x] 受控真实 OTLP 载荷保留完整文本和原生请求／用量归属，模型调用不重复采集；PNG、图片编码、内嵌图片地址和附件不在线上传。
- [x] 在线配置／导出／队列／flush 故障仅标观测不完整，flush 完成不覆盖已知失败，remote_delivery 保持 unknown。
- [x] 批次 trace 或结果必要保存失败归 Suite，仍交付内存事实和可用路径，不声称失败文件已保存；不为追踪自身保存递归导出。
- [x] 资源与保存采用独立短时限，观测退出等待保留既有上限；迟到后台完成不修改退出快照，真实页面及故障注入的跨批次回归通过。
