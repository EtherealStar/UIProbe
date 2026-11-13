# 规划器每一步能看到什么

Type: grilling
Label: wayfinder:grilling
Status: resolved
Assignee: rowla

## Question

用户已确定执行 Agent 看截图定位。程序每次行动后截图，追加到消息历史，Agent 输出截图中的坐标，外围程序换算并驱动 Playwright 点击。剩余问题是模型坐标采用哪种单位、相对于哪张截图，以及如何检查动作是否对应最新截图。

## Answer

程序把初始截图和每次行动后的截图依次交给执行 Agent。点击针对最新截图，以其左上角为原点，横纵坐标使用发给模型的图片像素。程序校验截图标识和坐标范围，负责从图像坐标换算到 Playwright 视口坐标并执行点击。
