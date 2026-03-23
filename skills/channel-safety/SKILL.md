---
name: channel-safety
description: Enforce confirmation for risky actions. Invoke when requests involve shell, deletion, execution, or other high-risk operations.
triggers: shell, execute, command, delete, remove, 风险, 删除, 执行
always: true
metadata: {"openclaw":{"requires":{"bins":[],"env":[]}}}
---
For high-risk operations, require explicit user confirmation.
If user denies, stop action and reply with cancellation.
Keep risk explanation short and specific.
