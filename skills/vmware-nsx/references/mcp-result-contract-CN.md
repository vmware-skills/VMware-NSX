# 公共结果契约（未发布迁移）

依赖 Policy 1.26.0。失败的 MCP 调用在 `structuredContent.vmware_error` 中提供
字符串 `error` 和字符串或 null 的 `hint`；旧文本、结构化业务字段及成功值保留。
不改变工具名、输入默认值、授权或确认门。

支持 offset 的工具按 `next_offset` 翻页，null 时停止；不按 `truncated` 循环。
无 offset 的工具不伪造续页，cursor API 保留原有 cursor 语义。

公共分页 envelope 增加 offset 元数据，保留现有集合/子集语义。

先发布 Policy，再刷新本仓锁文件并验证打包依赖，之后才能合并/发布。源码覆盖测试不等于已发布落地。
