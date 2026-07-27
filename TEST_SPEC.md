# kiri-bot 测试式样书

## 1. 测试目的

确认 `kiri-bot` 在 Discord 测试服务器中可以正确完成以下功能：

- KVS 配置读写
- 新人入场欢迎与资料填写
- `#profile` 面板查看/编辑个人资料
- PayPay 支付申请提交
- 管理员审核通过/拒绝
- 审核通过后的按月授权
- 每年/月 Role 和 Channel 的自动创建与权限修复
- `!sync_roles` 对账补角色
- 定时任务基础行为

## 2. 测试环境

### 2.1 本机环境

- OS: Windows
- Python: 3.9+
- 依赖: `discord.py>=2.4.0`
- 数据库: SQLite `bot.db`
- 时区基准: JST

启动命令：

```powershell
cd C:\WorkSpace\kiri-bot\kiri-bot
pip install -r requirements.txt
$env:DISCORD_TOKEN = "你的 Bot Token"
$env:KVS_ADMIN_KEY = "测试用管理密码"
python main.py
```

### 2.2 Discord 测试服务器准备

测试服务器需要：

- 一个 Bot
- 一个管理员角色，例如 `BotAdmin`
- 一个普通测试用户 A
- 一个新用户 B，建议用小号测试 `on_member_join`
- 频道：
  - `#welcome`
  - `#profile`
  - `#review`
  - `#remind`
  - `#pay`

Bot 权限需要：

- Manage Roles
- Manage Channels
- View Channels
- Send Messages
- Read Message History
- Use Application Commands / Interactions

注意：Bot 的最高角色必须高于它要添加的 `Paid_YYYY_MM` 角色。

### 2.3 Discord ID 获取方法

第一次测试前先打开 Discord 开发者模式：

1. 打开 Discord。
2. 点击左下角用户设置。
3. 进入 `Advanced`。
4. 打开 `Developer Mode`。
5. 回到服务器。
6. 右键频道、角色、用户或服务器。
7. 点击 `Copy ID`。

本式样书中所有 `<频道ID>`、`<角色ID>`、`<用户ID>` 都用这个方法取得。

### 2.4 测试账号分工

| 名称 | 用途 | 需要权限 |
|---|---|---|
| 管理员账号 | 执行 `!kvs`, `!paypanel`, `!profilepanel`, `!sync_roles`, 审核付款 | 拥有 `BotAdmin` 角色 |
| 普通用户 A | 测试没有权限、点击别人 welcome 按钮 | 无管理员权限 |
| 新用户 B | 测试新入场、填写资料、付款申请 | 普通成员 |

### 2.5 测试前检查清单

执行正式测试前，逐项确认：

- Bot 已邀请进测试服务器。
- Bot 在线。
- Bot 角色位置高于 `Paid_YYYY_MM` 角色。
- Bot 有 `Manage Roles`。
- Bot 有 `Manage Channels`。
- Bot 可以在 `#welcome`, `#profile`, `#review`, `#remind`, `#pay` 发消息。
- Discord Developer Portal 已开启 `SERVER MEMBERS INTENT`。
- Discord Developer Portal 已开启 `MESSAGE CONTENT INTENT`。
- 管理员账号拥有 `BotAdmin` 角色。
- 普通用户 A 没有 `BotAdmin` 角色。
- 新用户 B 可以退出并重新加入测试服务器，或准备一个还没加入的小号。

## 3. 初始配置

以下命令通过 DM 私信 Bot 执行。

详细步骤：

1. 打开 Discord。
2. 找到 Bot。
3. 右键 Bot，选择 `Message`。
4. 在私信窗口输入下面命令。
5. 每输入一条后确认 Bot 回复成功。
6. 如果 Bot 没回复，先确认 Bot 在线、`MESSAGE CONTENT INTENT` 已开启、`KVS_ADMIN_KEY` 是否正确。

```text
!kvs <password> auth role admin_role_ids <BotAdmin角色ID>
!kvs <password> discord channel welcome_id <welcome频道ID>
!kvs <password> discord channel profile_id <profile频道ID>
!kvs <password> discord channel review_id <review频道ID>
!kvs <password> discord channel remind_id <remind频道ID>
!kvs <password> billing global month_price_label 1000円
!kvs <password> reminder global expiry_days 5
!kvs <password> reminder global scan_hours 12
!kvs <password> reminder global sync_enabled 1
```

确认命令：

```text
!kvsget discord channel welcome_id
!kvsget discord channel profile_id
!kvsget auth role admin_role_ids
```

通过标准：

- 每个 `!kvsget` 都返回刚设置的值。
- Bot 控制台重启后打印的 `KCFG` 中能看到对应配置。

失败时确认：

- `<password>` 是否等于本机 `$env:KVS_ADMIN_KEY`。
- 命令是否在 DM 私信 Bot 中执行。
- 频道 ID 和角色 ID 是否复制正确。

## 4. 测试数据

### 4.1 用户资料测试数据

| 项目 | 值 |
|---|---|
| nickname | TestNick |
| birthday_mmdd | 07-21 |
| twitter_handle | test_handle |
| twitter_name | Test Name |
| note | profile test |

### 4.2 异常生日测试数据

| 输入 | 预期 |
|---|---|
| 02-29 | 成功 |
| 02-30 | 失败 |
| 13-01 | 失败 |
| 7-21 | 失败 |
| 07/21 | 失败 |

## 5. 测试用例

### 5.0 推荐执行顺序

建议按以下顺序跑，避免后面的测试缺少前置数据：

1. TC-001 Bot 启动与 DB 初始化
2. TC-002 KVS 配置写入与读取
3. TC-003 年度按月结构自动创建
4. TC-004 年度结构幂等性
5. TC-005 权限覆盖自动修复
6. TC-011 profile 面板发送与 Pin
7. TC-006 新人入场欢迎消息
8. TC-007 welcome 按钮本人可用
9. TC-008 welcome 按钮非本人不可用
10. TC-009 新人资料保存成功
11. TC-010 birthday_mmdd 格式校验
12. TC-012 profile 面板查看我的资料
13. TC-013 profile 面板编辑我的资料
14. TC-014 PayPay 链接设置
15. TC-015 支付面板发送
16. TC-016 用户获取 PayPay 链接
17. TC-017 用户提交付款信息
18. TC-018 非管理员不能审核
19. TC-019 管理员审核通过：按月授权
20. TC-021 sync_roles 手动对账补角色
21. TC-020 管理员审核拒绝
22. TC-023 sync_roles 定时任务开关
23. TC-024 到期提醒任务

### TC-001 Bot 启动与 DB 初始化

前提：

- `DISCORD_TOKEN` 和 `KVS_ADMIN_KEY` 已设置
- PowerShell 当前目录为项目根目录

步骤：

1. 打开 PowerShell。
2. 执行：

```powershell
cd C:\WorkSpace\kiri-bot\kiri-bot
```

3. 执行：

```powershell
$env:DISCORD_TOKEN = "你的 Bot Token"
$env:KVS_ADMIN_KEY = "测试用管理密码"
python main.py
```

4. 等待 5 到 30 秒。
5. 观察控制台是否输出 `READY`。
6. 观察控制台是否输出 `GUILDS`。
7. 观察控制台是否输出 `KCFG`。
8. 在另一个 PowerShell 窗口执行确认 SQL。

预期结果：

- 控制台输出 `READY`
- 输出当前 guild 列表
- `bot.db` 存在
- 表 `Kvs_M`, `user_T`, `requests`, `paypay_links`, `entitlement_T` 存在

确认 SQL：

```powershell
python -c "import sqlite3; c=sqlite3.connect('bot.db'); print(c.execute(\"select name from sqlite_master where type='table'\").fetchall()); c.close()"
```

### TC-002 KVS 配置写入与读取

步骤：

1. 用管理员账号打开 Bot 私信。
2. 输入：

```text
!kvs <password> discord channel welcome_id <welcome频道ID>
```

3. 确认 Bot 回复 `upsert 完成`。
4. 输入：

```text
!kvsget discord channel welcome_id
```

5. 确认返回值等于 `<welcome频道ID>`。
6. 用同样方法设置 `profile_id`, `review_id`, `remind_id`, `admin_role_ids`。
7. 重启 Bot。
8. 查看控制台 `KCFG`，确认配置已加载。

预期结果：

- Bot 回复 upsert 成功
- `!kvsget` 返回刚才写入的频道 ID

### TC-003 年度按月结构自动创建

步骤：

1. 启动 Bot。
2. 等待控制台输出 `[year-structure]` 日志。
3. 在 Discord 左侧频道列表查找 `Paid Content` Category。
4. 展开 `Paid Content`。
5. 确认频道从 `2026-01` 到 `2026-12` 都存在。
6. 打开服务器设置。
7. 进入 `Roles`。
8. 搜索 `Paid_2026_01`。
9. 确认 `Paid_2026_01` 到 `Paid_2026_12` 都存在。
10. 右键 `#2026-01`，进入 `Edit Channel`。
11. 进入 `Permissions`。
12. 确认 `@everyone` 不能 View Channel。
13. 确认 `Paid_2026_01` 可以 View Channel 和 Read Message History。
14. 确认 `BotAdmin` 可以 View Channel 和 Read Message History。

预期结果：

- 存在 Category: `Paid Content`
- 存在 12 个频道：
  - `#2026-01` 到 `#2026-12`
- 存在 12 个角色：
  - `Paid_2026_01` 到 `Paid_2026_12`
- 控制台输出 created / skip / fixed 日志

权限预期：

- `@everyone`: View Channel = false
- 对应 `Paid_YYYY_MM`: View Channel = true, Read Message History = true
- Admin 角色: View Channel = true, Read Message History = true

### TC-004 年度结构幂等性

步骤：

1. 停止 Bot：在 PowerShell 按 `Ctrl+C`。
2. 再执行 `python main.py`。
3. 等待 `[year-structure]` 日志完成。
4. 在 Discord 服务器设置的 Roles 中搜索 `Paid_2026_01`。
5. 确认只有一个 `Paid_2026_01`。
6. 在频道列表确认只有一个 `#2026-01`。
7. 对 `Paid_2026_02` / `#2026-02` 随机抽查一次。

预期结果：

- 不创建重复 Role
- 不创建重复 Channel
- 控制台输出 skip exists 或 skip overwrite ok

### TC-005 权限覆盖自动修复

步骤：

1. 在 Discord 中右键 `#2026-01`。
2. 点击 `Edit Channel`。
3. 点击 `Permissions`。
4. 选择 `@everyone`。
5. 将 `View Channel` 改成允许。
6. 保存。
7. 回到 PowerShell，停止 Bot。
8. 重新执行 `python main.py`。
9. 等待 `[month-structure] fixed overwrite` 日志。
10. 回到 `#2026-01` 权限页面。
11. 查看 `@everyone` 的 `View Channel`。

预期结果：

- Bot 将 `@everyone` View Channel 修复为 false
- 控制台输出 fixed overwrite

### TC-006 新人入场欢迎消息

前提：

- `discord/channel/welcome_id` 已配置
- 新用户 B 未加入服务器

步骤：

1. 确认 Bot 正在运行。
2. 确认 `welcome_id` 指向 `#welcome`。
3. 使用邀请链接让新用户 B 加入服务器。
4. 等待 1 到 10 秒。
5. 用管理员账号查看 `#welcome`。
6. 找到 Bot 发出的欢迎消息。
7. 确认消息里 mention 了新用户 B。
8. 确认消息下方有 `填写资料` 按钮。

预期结果：

- Bot 在 `#welcome` 发消息
- 消息 mention 新用户 B
- 消息包含按钮 `填写资料`

### TC-007 welcome 按钮本人可用

步骤：

1. 切换到新用户 B。
2. 打开 `#welcome`。
3. 找到 mention 新用户 B 的欢迎消息。
4. 点击 `填写资料`。
5. 确认 Discord 弹出 Modal。
6. 检查 Modal 标题为 `填写/编辑资料`。
7. 检查字段名称。

预期结果：

- 弹出 Modal
- Modal 字段包含：
  - `nickname`
  - `birthday_mmdd (MM-DD)`
  - `twitter_handle`
  - `twitter_name`
  - `note`

### TC-008 welcome 按钮非本人不可用

步骤：

1. 切换到管理员账号或普通用户 A。
2. 打开 `#welcome`。
3. 找到 mention 新用户 B 的欢迎消息。
4. 点击这条消息下方的 `填写资料`。
5. 观察是否弹出 Modal。
6. 观察是否出现只有自己可见的 ephemeral 提示。

预期结果：

- 不弹 Modal
- 返回 ephemeral 提示：
  - `这不是给你的。请去 #profile 管理自己的资料。`
  - 如果配置了 profile 频道，应提示 `<#profile频道ID>`

### TC-009 新人资料保存成功

步骤：

1. 切换到新用户 B。
2. 在 `#welcome` 点击自己的 `填写资料`。
3. 在 `nickname` 输入 `TestNick`。
4. 在 `birthday_mmdd (MM-DD)` 输入 `07-21`。
5. 在 `twitter_handle` 输入 `test_handle`。
6. 在 `twitter_name` 输入 `Test Name`。
7. 在 `note` 输入 `profile test`。
8. 点击提交。
9. 查看 Bot 的 ephemeral 回复。
10. 在本机 PowerShell 执行确认 SQL。

预期结果：

- Bot ephemeral 回复 `资料已保存。`
- 显示资料 Embed
- `user_T` 中有该用户记录

确认 SQL：

```powershell
python -c "import sqlite3; c=sqlite3.connect('bot.db'); print(c.execute('select user_id,nickname,birthday_mmdd,twitter_handle,twitter_name,note from user_T').fetchall()); c.close()"
```

### TC-010 birthday_mmdd 格式校验

步骤：

1. 切换到新用户 B。
2. 打开资料 Modal。
3. `nickname` 输入任意非空值，例如 `TestNick`。
4. `birthday_mmdd (MM-DD)` 输入 `02-30`。
5. 其他字段可留空。
6. 点击提交。
7. 观察 Bot 回复。
8. 再打开资料查看，确认旧生日没有被错误覆盖。
9. 依次测试 `13-01`, `7-21`, `07/21`。

预期结果：

- Bot ephemeral 回复生日格式错误
- DB 不应保存这次错误值

### TC-011 profile 面板发送与 Pin

前提：

- `discord/channel/profile_id` 已配置
- 执行者拥有 Admin 角色

步骤：

1. 切换到管理员账号。
2. 打开 `#profile`。
3. 在消息框输入：

```text
!profilepanel
```

4. 按 Enter 发送。
5. 等待 Bot 回复。
6. 查看频道顶部 Pin 列表。

预期结果：

- Bot 发送 profile 面板消息
- 包含按钮：
  - `查看我的资料`
  - `编辑我的资料`
- Bot 尝试 Pin 该消息

### TC-012 profile 面板查看我的资料

步骤：

1. 切换到用户 B。
2. 打开 `#profile`。
3. 找到 profile 面板消息。
4. 点击 `查看我的资料`。
5. 观察 Discord 是否出现 ephemeral 回复。
6. 切换到用户 A，确认用户 A 看不到用户 B 的回复。

预期结果：

- Bot ephemeral 显示当前 `user_T` 内容
- 其他用户看不到该回复

### TC-013 profile 面板编辑我的资料

步骤：

1. 切换到用户 B。
2. 打开 `#profile`。
3. 点击 `编辑我的资料`。
4. 确认 Modal 中默认显示之前保存的 `TestNick`, `07-21`, `test_handle`, `Test Name`, `profile test`。
5. 将 `nickname` 改为 `EditedNick`。
6. 保持其他字段不变。
7. 点击提交。
8. 再点击 `查看我的资料`。
9. 用 SQL 查询 `user_T`。

预期结果：

- Modal 默认值显示已有资料
- 提交后 upsert 覆盖更新
- 查看结果中 nickname 为 `EditedNick`

### TC-014 PayPay 链接设置

步骤：

1. 切换到管理员账号。
2. 打开 `#pay` 或任意 Bot 可发消息的服务器频道。
3. 输入：

```text
!setpaypay https://example.com/paypay-test 2026-12-31
```

4. 确认 Bot 回复已更新。
5. 输入：

```text
!getpaypay
```

6. 确认 Bot 回复当前 active 链接。

预期结果：

- Bot 回复当前 PayPay 链接
- 链接为刚才设置的 URL

### TC-015 支付面板发送

步骤：

1. 切换到管理员账号。
2. 打开 `#pay`。
3. 输入：

```text
!paypanel
```

4. 按 Enter 发送。
5. 等待 Bot 发送面板。

预期结果：

- Bot 发送付费面板
- 包含按钮：
  - `支付 1 个月`
  - `已付款`

### TC-016 用户获取 PayPay 链接

步骤：

1. 切换到用户 B。
2. 打开 `#pay`。
3. 找到付费面板消息。
4. 点击 `支付 1 个月`。
5. 观察是否出现 ephemeral 回复。
6. 确认其他用户看不到该回复。

预期结果：

- Bot ephemeral 回复 PayPay 链接
- 回复包含价格 `month_price_label`

### TC-017 用户提交付款信息

步骤：

1. 切换到用户 B。
2. 打开 `#pay`。
3. 点击付费面板的 `已付款`。
4. 在 Modal 的 PayPay 名字段输入 `Pay Test B`。
5. 备注输入 `test payment`。
6. 点击提交。
7. 打开 `#review`。
8. 找到 Bot 发出的审核 Embed。
9. 记录 Embed 中的 Request ID。

预期结果：

- Bot ephemeral 回复已提交审核
- `#review` 出现付款审核 Embed
- Embed 包含用户、PayPay 名、Request ID
- 有审核按钮 `确认通过` / `拒绝`

### TC-018 非管理员不能审核

步骤：

1. 切换到普通用户 A。
2. 打开 `#review`。
3. 找到用户 B 的付款审核消息。
4. 点击 `确认通过`。
5. 观察用户 A 收到的 ephemeral 回复。
6. 查看用户 B 的角色列表。
7. 用 SQL 查询 `entitlement_T`。

预期结果：

- Bot ephemeral 回复没有审核权限
- 不写入 entitlement
- 不加角色

### TC-019 管理员审核通过：按月授权

步骤：

1. 切换到管理员账号。
2. 打开 `#review`。
3. 找到用户 B 的付款审核消息。
4. 点击 `确认通过`。
5. 等待 Bot 处理完成。
6. 观察管理员收到的 ephemeral 成功提示。
7. 打开服务器成员列表或用户 B 的 Profile。
8. 查看用户 B 是否获得 `Paid_YYYY_MM` 角色。
9. 查看 `Paid Content` 下对应月份频道是否存在。
10. 用 SQL 查询 `entitlement_T`。
11. 回到审核消息，确认按钮已 disabled。

预期结果：

- 先写入 `entitlement_T`
- 对 start_at ~ end_at 覆盖的自然月写入 `YYYYMM`
- 用户 B 获得对应 `Paid_YYYY_MM` 角色
- 审核消息按钮被 disabled
- 管理员收到 ephemeral 成功提示

确认 SQL：

```powershell
python -c "import sqlite3; c=sqlite3.connect('bot.db'); print(c.execute('select user_id,yyyymm,request_id,granted_at from entitlement_T').fetchall()); c.close()"
```

### TC-020 管理员审核拒绝

步骤：

1. 切换到用户 B。
2. 再次在 `#pay` 点击 `已付款`。
3. 输入 PayPay 名，例如 `Reject Test B`。
4. 提交。
5. 切换到管理员账号。
6. 打开 `#review`。
7. 找到新的审核消息。
8. 点击 `拒绝`。
9. 用 SQL 查询该 request 的 status。

预期结果：

- requests 状态为 `REJECTED`
- 审核按钮 disabled
- 用户不会获得新角色

### TC-021 sync_roles 手动对账补角色

前提：

- `entitlement_T` 中已有用户 B 的 `yyyymm`
- 手动从用户 B 移除对应 `Paid_YYYY_MM` 角色

步骤：

1. 打开用户 B 的成员管理界面。
2. 手动移除一个已授权月份角色，例如 `Paid_2026_07`。
3. 确认用户 B 失去该角色。
4. 切换到管理员账号。
5. 在服务器频道输入：

```text
!sync_roles
```

6. 等待 Bot 输出报告。
7. 再次查看用户 B 的角色列表。

预期结果：

- Bot 读取 `entitlement_T`
- 检测用户 B 缺少对应 role
- 自动 add_roles
- 输出报告，列出补齐用户和月份

### TC-022 sync_roles 成员不存在

步骤：

1. 准备一个不存在或已退群的 Discord user_id。
2. 停止 Bot 或保持 Bot 运行均可。
3. 在 PowerShell 插入测试数据：

```powershell
python -c "import sqlite3, datetime; c=sqlite3.connect('bot.db'); c.execute('insert or ignore into entitlement_T(user_id,yyyymm,request_id,granted_at) values(?,?,?,?)', ('999999999999999999','202607','manual-test',datetime.datetime.now().isoformat())); c.commit(); c.close()"
```

4. 在 Discord 中用管理员账号执行：

```text
!sync_roles
```

5. 查看 Bot 输出报告。

预期结果：

- 报告记录 member 不存在
- 命令继续处理其他记录
- Bot 不崩溃

### TC-023 sync_roles 定时任务开关

步骤：

1. 打开 Bot 私信。
2. 输入：

```text
!kvs <password> reminder global sync_enabled 0
```

3. 确认 Bot 回复成功。
4. 重启 Bot。
5. 等待 JST 03:00 后观察 PowerShell 日志。
6. 确认没有 `[sync-roles] scheduled start`。

预期结果：

- 定时 sync 不执行

恢复：

```text
!kvs <password> reminder global sync_enabled 1
```

### TC-024 到期提醒任务

前提：

- 有 APPROVED request
- `end_at` 在未来 `expiry_days` 天内
- `discord/channel/remind_id` 已配置

步骤：

1. 准备一条 APPROVED request，`end_at` 设置在未来 `expiry_days` 天内。
2. 确认 `remind_id` 指向 `#remind`。
3. 启动 Bot。
4. 等待 reminder tick。
5. 查看 PowerShell 是否有提醒任务日志。
6. 查看 `#remind`。

预期结果：

- Bot 在提醒频道发送即将到期提醒

## 6. 回归测试清单

每次改代码后至少确认：

- Bot 可以启动并输出 `READY`
- `!kvsget` 可用
- `!profilepanel` 可用
- welcome 按钮本人可打开，非本人不可打开
- profile 查看/编辑可用
- `!paypanel` 可用
- 审核通过会写 `entitlement_T`
- 审核通过会添加 `Paid_YYYY_MM`
- `!sync_roles` 能补齐缺失角色
- 重启 Bot 不重复创建 Role/Channel

## 7. 常见失败与确认点

### Bot 无法加角色

确认：

- Bot 有 Manage Roles
- Bot 的最高角色高于 `Paid_YYYY_MM`
- 目标用户仍在服务器

### Bot 无法创建频道或设置权限

确认：

- Bot 有 Manage Channels
- Bot 可以管理 `Paid Content` Category

### welcome 不发送

确认：

- `discord/channel/welcome_id` 已配置
- Bot 可以在该频道发消息
- Developer Portal 已开启 Server Members Intent

### Modal 不出现

确认：

- 点击者是否为目标用户
- Bot 是否在线
- Discord 客户端是否正常显示交互

### `!profilepanel` 无权限

确认：

- 执行者是否拥有 `admin_role_ids` 配置中的角色
- `auth/role/admin_role_ids` 是否正确

## 8. 测试完成判定

满足以下条件可判定测试通过：

- 所有 P0/P1 测试用例通过
- 没有 Python 语法错误
- 没有 Discord 权限导致的未处理异常
- 数据库 `user_T` 和 `entitlement_T` 数据符合预期
- 重启 Bot 后幂等逻辑正常，不重复创建 Discord 对象
