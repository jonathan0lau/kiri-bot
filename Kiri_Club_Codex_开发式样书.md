# Kiri Club Discord Bot / HP 开发式样书

- 版本：1.0
- 日期：2026-07-30
- 主要用途：作为 Codex 的实现依据
- 默认实现语言：Python
- 现有 Bot 技术栈：`discord.py`、SQLite、`Kvs_M`
- 适用仓库：优先应用于现有 `kiri-bot` 仓库；HP 相关工作应用于 `kiri-homepage` 仓库

---

## 0. Codex 执行指令

将本文件视为需求的唯一基准。开始修改代码前，必须先完成以下动作：

1. 阅读仓库的 `README`、依赖文件、入口文件、数据库初始化代码和现有付款流程。
2. 搜索并确认以下现有实现：
   - PayPay 支付按钮；
   - “已付款”Modal；
   - 管理员审核按钮；
   - Paid 身分组赋予；
   - 到期提醒；
   - `Kvs_M` 的读取与 `!kvs` 更新命令；
   - 现有用户表、付款表或申请表。
3. 不得重写或删除已经正常工作的付款审核功能。优先以扩展方式实现。
4. 如果现有数据库表的名称与本文不同，优先复用现有表，不得创建含义重复的第二套主表。
5. 在开始编码前，输出一份简短实施计划，列出：
   - 将修改的文件；
   - 数据库迁移方式；
   - 需要新增的环境变量和 KVS；
   - 测试方式。
6. 默认只实施 **P0：可销售 MVP**。P1/P2/P3 不得在同一次改动中擅自实现。
7. 每项数据库迁移必须可重复执行，不得因重复启动而报错。
8. 所有 Discord 交互必须处理权限、超时、重复点击和异常，并向用户返回可理解的消息。
9. 完成后必须输出：
   - 变更文件列表；
   - 数据库变更；
   - 环境变量与 KVS 配置清单；
   - 启动与测试命令；
   - 尚未实现的内容。

---

## 1. 项目目标

### 1.1 产品定位

Kiri Club 不是 Fantia 的完整替代品，也不在 Discord 内保存完整写真。

系统由三部分组成：

```text
Kiri HP
- 对外展示
- 商品目录
- 少量预览
- 引导用户进入 Discord

Discord Bot / Server
- 商品商店
- PayPay 付款申请
- 管理员审核
- 自动交付
- 我的写真集
- 订单与用户资料
- 通知和社区互动

云盘 + NAS
- 云盘保存当前销售的加密写真包或视频
- 飞牛 NAS 保存原始资料、成品和长期备份
```

### 1.2 P0 目标

用户应能够完成以下完整流程：

```text
浏览商品
→ 选择商品
→ 获取 PayPay 支付信息
→ 提交已付款申请和邮箱
→ 管理员审核通过
→ 自动发送下载链接和密码
→ 用户可在 Discord 的“我的写真集”重新取得交付信息
```

### 1.3 非目标

P0 不实现：

- Discord 内完整写真上传或媒体归档；
- 月份频道和月份身分组；
- 自动识别 PayPay 入账；
- 每位购买者独立云盘链接；
- 在线多图浏览会员网站；
- 多创作者、多店铺、多币种；
- 复杂订阅档位；
- X 自动同步；
- 积分、签到和粉丝等级。

---

## 2. 现有系统兼容要求

### 2.1 已知现有功能

以下功能应继续正常工作：

- 支付面板；
- “支付 1 个月”或现有支付按钮；
- PayPay 链接的私密回复；
- “已付款”Modal；
- 管理员审核频道；
- 批准、拒绝按钮；
- Paid Discord Role；
- 到期提醒；
- SQLite；
- `Kvs_M(key1, key2, key3, value, note)`；
- `!kvs` 和 `!kvsget`；
- Discord Token、KVS 管理密码通过环境变量保存。

### 2.2 兼容策略

- 原有会员制支付流程不得删除。
- 新增“商品购买模式”。商品购买与会员购买必须通过 `purchase_type` 或等价字段区分。
- 如果现有付款申请表已经能够表示一笔付款申请，应扩展该表，而不是复制为新的 `order_T`。
- 如果现有表结构不适合扩展，可建立迁移后的标准表，但必须提供旧数据迁移和兼容读取。
- Codex 必须在 `docs/db-mapping.md` 记录实际表名与本文逻辑表名之间的映射。

---

## 3. 推荐目录结构

根据现有仓库调整，不要求机械照搬。目标结构：

```text
kiri-bot/
├─ bot.py / main.py
├─ cogs/
│  ├─ shop.py
│  ├─ profile.py
│  ├─ admin_orders.py
│  └─ existing_*.py
├─ services/
│  ├─ product_service.py
│  ├─ order_service.py
│  ├─ delivery_service.py
│  ├─ mail_service.py
│  └─ permission_service.py
├─ repositories/
│  ├─ product_repository.py
│  ├─ order_repository.py
│  └─ user_repository.py
├─ views/
│  ├─ shop_views.py
│  ├─ order_views.py
│  └─ profile_views.py
├─ db/
│  ├─ migrations.py
│  └─ schema.sql
├─ templates/
│  └─ delivery_mail.txt
├─ tests/
├─ docs/
│  ├─ db-mapping.md
│  └─ operations.md
└─ .env.example
```

要求：

- Discord UI、业务逻辑、数据库访问、邮件发送不得全部堆在一个文件内。
- 数据库写入必须统一经过 repository/service。
- 邮件发送必须封装为独立 provider，测试时不得真的发送邮件。

---

## 4. 数据模型

### 4.1 数据库通用规则

- 数据库：SQLite。
- 时间字段：统一保存 UTC ISO-8601，例如 `2026-07-30T08:00:00Z`。
- Discord ID：SQLite 中推荐使用 `TEXT` 保存，避免语言或驱动的整数边界问题。
- 状态字段：使用固定大写枚举字符串。
- 所有迁移必须幂等。
- 关键表必须创建索引。
- 密码和下载链接禁止写入普通业务日志。

### 4.2 逻辑表：`product_T`

用于保存一套可销售写真或数字商品。

```sql
CREATE TABLE IF NOT EXISTS product_T (
    product_id             TEXT PRIMARY KEY,
    product_name           TEXT NOT NULL,
    product_type           TEXT NOT NULL DEFAULT 'PHOTO_SET',
    description            TEXT,
    price_amount           INTEGER NOT NULL CHECK (price_amount >= 0),
    price_currency         TEXT NOT NULL DEFAULT 'JPY',
    cover_url              TEXT,
    preview_url            TEXT,
    download_url           TEXT NOT NULL,
    download_password      TEXT,
    file_size_label        TEXT,
    content_count_label    TEXT,
    storage_provider       TEXT NOT NULL DEFAULT 'GOOGLE_DRIVE',
    status                 TEXT NOT NULL DEFAULT 'DRAFT',
    sort_order             INTEGER NOT NULL DEFAULT 0,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_product_status_sort
ON product_T(status, sort_order, created_at);
```

允许值：

- `product_type`：`PHOTO_SET`、`VIDEO_SET`、`BUNDLE`
- `status`：`DRAFT`、`SALE`、`STOP`、`ARCHIVED`

规则：

- 只有 `SALE` 商品显示在用户商店。
- `download_url` 和 `download_password` 仅对已购用户、管理员和交付服务可见。
- 商品停止销售后，已购用户仍然可以从“我的写真集”取得交付信息。

### 4.3 逻辑表：`order_T`

一条记录代表一次购买申请。

```sql
CREATE TABLE IF NOT EXISTS order_T (
    order_id               TEXT PRIMARY KEY,
    purchase_type          TEXT NOT NULL DEFAULT 'PRODUCT',
    product_id             TEXT,
    discord_user_id        TEXT NOT NULL,
    discord_guild_id       TEXT NOT NULL,
    email                  TEXT NOT NULL,
    paypay_name            TEXT NOT NULL,
    payment_note           TEXT,
    amount_expected        INTEGER,
    currency               TEXT NOT NULL DEFAULT 'JPY',
    status                 TEXT NOT NULL DEFAULT 'PENDING',
    requested_at           TEXT NOT NULL,
    approved_by            TEXT,
    approved_at            TEXT,
    rejected_by            TEXT,
    rejected_at            TEXT,
    reject_reason          TEXT,
    delivery_completed_at  TEXT,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    FOREIGN KEY(product_id) REFERENCES product_T(product_id)
);

CREATE INDEX IF NOT EXISTS idx_order_user_status
ON order_T(discord_user_id, status, requested_at);

CREATE INDEX IF NOT EXISTS idx_order_product_status
ON order_T(product_id, status, requested_at);
```

允许值：

- `purchase_type`：`PRODUCT`、`MEMBERSHIP`
- `status`：
  - `PENDING`
  - `APPROVED`
  - `REJECTED`
  - `DELIVERY_PENDING`
  - `SENT`
  - `DELIVERY_FAILED`
  - `CANCELLED`

状态迁移：

```text
PENDING
├─ approve → APPROVED → DELIVERY_PENDING → SENT
│                                  └──────→ DELIVERY_FAILED
├─ reject  → REJECTED
└─ cancel  → CANCELLED

DELIVERY_FAILED
└─ resend  → DELIVERY_PENDING → SENT / DELIVERY_FAILED
```

约束：

- 重复点击批准不得重复创建订单或重复赋予权益。
- 同一 `order_id` 的批准必须幂等。
- 用户可以再次购买同一商品，但不能在已有 `PENDING` 订单时重复提交相同商品；应提示现有订单编号。

### 4.4 逻辑表：`delivery_T`

用于记录每次交付尝试。

```sql
CREATE TABLE IF NOT EXISTS delivery_T (
    delivery_id            TEXT PRIMARY KEY,
    order_id               TEXT NOT NULL,
    channel                TEXT NOT NULL,
    destination_masked     TEXT,
    status                 TEXT NOT NULL,
    attempt_count          INTEGER NOT NULL DEFAULT 1,
    error_code             TEXT,
    error_message          TEXT,
    attempted_at           TEXT NOT NULL,
    completed_at           TEXT,
    created_at             TEXT NOT NULL,
    FOREIGN KEY(order_id) REFERENCES order_T(order_id)
);

CREATE INDEX IF NOT EXISTS idx_delivery_order
ON delivery_T(order_id, attempted_at);
```

允许值：

- `channel`：`EMAIL`、`DISCORD`
- `status`：`PENDING`、`SENT`、`FAILED`

注意：

- `destination_masked` 只保存脱敏值，例如 `ab***@example.com`。
- `error_message` 不得包含下载密码、完整链接、SMTP 密码。

### 4.5 逻辑表：`user_T`

如果仓库已有用户表，扩展现有表。

```sql
CREATE TABLE IF NOT EXISTS user_T (
    discord_user_id        TEXT PRIMARY KEY,
    nickname               TEXT,
    birthday_mmdd          TEXT,
    twitter_handle         TEXT,
    twitter_name           TEXT,
    email                  TEXT,
    language               TEXT NOT NULL DEFAULT 'ja',
    consent_delivery       INTEGER NOT NULL DEFAULT 0,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL
);
```

校验：

- `birthday_mmdd`：允许空；非空时格式必须为 `MM-DD`。
- `twitter_handle`：保存时去除开头 `@`。
- 邮箱必须进行基本格式校验和前后空格清理。

---

## 5. 配置

### 5.1 环境变量

敏感信息必须放环境变量，不得放 KVS 或代码。

```dotenv
DISCORD_TOKEN=
KVS_ADMIN_KEY=

MAIL_MODE=log
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_USE_TLS=true
MAIL_FROM_ADDRESS=
MAIL_FROM_NAME=Kiri Club

APP_ENV=development
LOG_LEVEL=INFO
```

`MAIL_MODE`：

- `log`：不发送邮件，仅将脱敏后的发送结果记录到日志；开发和测试默认值。
- `smtp`：通过 SMTP 发送。

`.env.example` 不得包含真实 Token、密码、邮箱或链接。

### 5.2 KVS 新增键

沿用 `Kvs_M(key1, key2, key3, value, note)`：

```text
discord / channel / shop_id
discord / channel / profile_id
discord / channel / review_id
discord / channel / purchase_support_id
discord / channel / bot_log_id

discord / role / paid_id
discord / role / buyer_id

auth / role / admin_role_ids

billing / global / paypay_url
billing / global / currency
billing / global / review_timeout_hours

shop / global / max_products_per_page
shop / global / allow_duplicate_purchase

delivery / global / self_service_cooldown_minutes
delivery / global / max_retry_count
```

规则：

- `admin_role_ids` 是 Discord Role ID 列表，不是用户 ID。
- `buyer_id` 不存在时，可以临时复用现有 `paid_id`，但必须记录日志。
- 频道或 Role 不存在、Bot 无权限时，启动检查必须输出明确错误。

---

## 6. 权限模型

### 6.1 普通用户

可执行：

- 浏览 `SALE` 商品；
- 打开商品详情；
- 发起购买；
- 提交付款信息；
- 查看自己的订单；
- 查看自己已购的写真；
- 在冷却时间后自助重新取得交付信息。

不可执行：

- 查看其他用户订单；
- 查看未购买商品的下载链接或密码；
- 修改商品；
- 审核订单；
- 强制重发邮件。

### 6.2 管理员

满足以下任一条件视为管理员：

- 拥有 `auth/role/admin_role_ids` 中的 Role；
- 现有项目已定义并验证的管理员机制。

管理员可：

- 创建、编辑、发布、停止商品；
- 查看待审核订单；
- 批准或拒绝订单；
- 重发交付邮件；
- 查询订单和交付历史；
- 重新生成商店和 Profile 固定面板。

### 6.3 Bot 权限

最低权限：

- View Channels
- Send Messages
- Embed Links
- Read Message History
- Manage Roles（仅在需要赋予 Buyer/Paid Role 时）
- Use Application Commands

Bot Role 必须高于 `buyer_id` / `paid_id`。

---

## 7. 用户界面与交互

### 7.1 `#shop` 固定面板

标题：

```text
Kiri 写真商店
```

正文：

```text
选择商品查看内容、价格和购买方式。
付款完成后由管理员确认，确认后会自动发送下载信息。
```

组件：

- 商品选择菜单，最多每页 25 项；商品更多时分页。
- `刷新商品列表` 按钮可选，仅管理员可见或可执行。

商品选项显示：

```text
{product_name}｜{price_amount}円
```

只显示 `status = SALE` 的商品。

### 7.2 商品详情

使用 Embed 或 Components v2，必须包含：

- 商品名称；
- 商品类型；
- 价格；
- 简介；
- 照片/视频数量说明；
- 文件大小；
- 封面或预览 URL（存在时）；
- “购买”按钮；
- “返回商店”按钮。

禁止显示：

- `download_url`
- `download_password`

### 7.3 购买按钮

点击后：

1. 再次从数据库读取商品，确认仍为 `SALE`。
2. 检查同用户、同商品是否已有 `PENDING` 订单。
3. 私密回复 PayPay 链接、应付金额和“已付款”按钮。
4. PayPay URL 从 KVS 获取，不从代码硬编码。

示例：

```text
商品：KIRI 2026年8月写真集
金额：2,000円

请通过以下 PayPay 链接付款。付款后点击“已付款”，填写付款名和接收邮箱。
```

### 7.4 “已付款”Modal

字段：

1. `PayPay 显示名`：必填，1～100 字符。
2. `接收邮箱`：必填，基本格式校验。
3. `付款备注`：选填，最多 300 字符。

系统自动关联：

- Discord user ID；
- guild ID；
- product ID；
- 商品当时的价格；
- 申请时间。

提交后：

- 创建 `PENDING` 订单；
- 私密回复订单编号；
- 在审核频道发送审核卡片。

### 7.5 管理员审核卡片

必须显示：

- 订单编号；
- 商品名称 / ID；
- 应付金额；
- Discord 用户 Mention 与 ID；
- PayPay 显示名；
- 脱敏邮箱；
- 付款备注；
- 申请时间；
- 当前状态。

按钮：

- `批准`
- `拒绝`
- `查看交付记录`（订单处理后可用）

批准要求：

1. 使用事务或等价机制更新状态，防止重复处理。
2. 校验商品仍存在；停止销售不影响已提交订单的批准。
3. 将订单更新为 `APPROVED`，记录审核人和时间。
4. 确保用户获得 Buyer Role；Role 不存在或赋予失败时记录错误，但不得丢失订单。
5. 将订单更新为 `DELIVERY_PENDING`。
6. 执行邮件交付。
7. 邮件成功则状态为 `SENT`；失败则 `DELIVERY_FAILED`。
8. 更新审核卡片，禁用批准/拒绝按钮。
9. 私信或在用户可见位置通知处理结果；DM 失败不得使订单回滚。

拒绝要求：

- 点击后打开 Modal 输入拒绝理由；
- 状态更新为 `REJECTED`；
- 保存管理员和时间；
- 通知用户；
- 不发送下载信息，不赋予 Buyer Role。

### 7.6 `#profile` 固定面板

按钮：

- `查看我的资料`
- `编辑我的资料`
- `我的写真集`
- `我的订单`
- `联系客服`

所有回复默认 ephemeral。

#### 我的写真集

只查询当前用户、状态为 `SENT` 的商品订单。

列表去重规则：

- 同一用户重复购买同一商品时，列表只显示一项；
- 详情中可以显示首次购买日期和订单数量。

选择商品后显示：

- 商品名称；
- 下载链接；
- 解压密码；
- 文件大小；
- 最近更新时间；
- `重新发送到邮箱` 按钮。

安全要求：

- 必须确认点击者 ID 与查询用户 ID 一致。
- 回复必须 ephemeral。
- 禁止将下载信息写入公开频道。

#### 我的订单

显示最近 20 条：

```text
订单号 / 商品 / 状态 / 申请时间 / 审核时间
```

用户可选择一条查看详情，但看不到管理员内部备注和错误堆栈。

### 7.7 自助重发

- 只有 `SENT` 或 `DELIVERY_FAILED` 的本人订单可重发。
- 使用 KVS `self_service_cooldown_minutes` 限制频率。
- 达到 `max_retry_count` 后提示联系客服。
- 每次重发写入 `delivery_T`。
- 重发成功不创建新订单。

---

## 8. 邮件交付

### 8.1 邮件主题

```text
【Kiri Club】写真集下载信息：{product_name}
```

### 8.2 邮件正文（日文默认）

```text
{display_name} 様

「{product_name}」をご購入いただき、ありがとうございます。

ダウンロードURL：
{download_url}

解凍パスワード：
{download_password_or_none}

ファイルサイズ：{file_size_label}
注文番号：{order_id}

本URL、パスワードおよびコンテンツを第三者へ共有・転載しないでください。
リンクが利用できない場合は、Discord の「私の写真集」から最新情報をご確認ください。

Kiri Club
```

### 8.3 邮件发送要求

- SMTP 超时必须配置，建议 15 秒以内。
- 失败时捕获异常，记录脱敏错误，不得导致 Bot 进程退出。
- 不得在日志中打印完整邮件正文、下载链接或密码。
- `MAIL_MODE=log` 时视为模拟成功或返回明确的 simulated 状态；测试必须覆盖这一模式。
- 实际发送成功后才将订单置为 `SENT`。

---

## 9. 商品管理（管理员）

P0 采用 Discord 管理命令，不建设 Web 管理后台。

推荐使用 slash command group：

```text
/product create
/product edit <product_id>
/product publish <product_id>
/product stop <product_id>
/product list
/product show <product_id>
/panel shop
/panel profile
/order search
/order resend <order_id>
```

如果现有 Bot 尚未使用 slash command，可使用当前命令体系实现，但必须：

- 仅管理员可执行；
- 敏感输入和结果使用 DM 或 ephemeral；
- 命令不能把下载密码发送到公开频道。

### 9.1 创建/编辑商品字段

至少支持：

- `product_id`
- `product_name`
- `product_type`
- `description`
- `price_amount`
- `cover_url`
- `preview_url`
- `download_url`
- `download_password`
- `file_size_label`
- `content_count_label`
- `sort_order`

创建后默认 `DRAFT`，必须执行 publish 才进入 `SALE`。

### 9.2 校验

- `product_id`：`A-Z`、`0-9`、`-`、`_`，长度 3～50；保存时转大写。
- 价格：0～10,000,000 日元整数。
- URL：仅允许 `https://`。
- 商品名：1～100 字符。
- 简介：最多 1,500 字符。
- 密码：允许空；存在时最多 200 字符。

---

## 10. 日志、异常和审计

### 10.1 日志事件

至少记录：

- Bot 启动和配置检查；
- 商品创建、更新、发布、停止；
- 订单创建；
- 订单批准、拒绝；
- Role 赋予成功/失败；
- 邮件交付成功/失败；
- 用户自助重发；
- 数据库迁移结果；
- 未捕获异常。

### 10.2 敏感信息处理

日志中禁止出现：

- Discord Token；
- SMTP 密码；
- KVS 管理密码；
- 完整下载 URL；
- 解压密码；
- 完整邮箱。

提供工具函数：

```python
mask_email("abc@example.com") -> "a***@example.com"
mask_url("https://...") -> "https://***"
```

### 10.3 Bot 日志频道

如果配置 `discord/channel/bot_log_id`：

- 仅发送运营级摘要；
- 不发送堆栈、密码或链接；
- 失败时仍保留本地日志。

---

## 11. 启动自检

Bot 启动后检查：

- 必要环境变量；
- 必要 KVS；
- 数据库迁移是否成功；
- guild、频道和 Role 是否存在；
- Bot 是否具有发送消息和管理 Role 权限；
- 邮件配置是否完整。

行为：

- 缺少非关键配置：明确 warning，对应模块禁用。
- 缺少 `DISCORD_TOKEN` 或数据库无法初始化：终止启动。
- 邮件未配置：自动切换 `MAIL_MODE=log` 仅限开发环境；生产环境必须报错或禁用批准交付。

---

## 12. 测试要求

使用现有测试框架；没有时使用 `pytest`。

### 12.1 单元测试

至少覆盖：

- 商品状态过滤；
- 商品字段校验；
- 邮箱校验与脱敏；
- 订单状态迁移；
- 重复批准的幂等性；
- 重复待审核订单拦截；
- 已购商品去重；
- 自助重发冷却时间；
- 邮件模拟发送；
- 下载信息不会进入普通日志。

### 12.2 Repository 测试

使用临时 SQLite 数据库，覆盖：

- migration 重复执行；
- 商品 CRUD；
- 创建订单；
- 并发或连续批准只成功一次；
- 查询用户已购商品；
- delivery 历史。

### 12.3 交互测试

可以使用 mock，不要求连接真实 Discord：

- 非管理员不能批准；
- 他人不能点击目标用户的 Profile 交互；
- 未购买用户不能获得下载信息；
- 商品停止销售后不能新建购买，但已有订单可审核；
- 邮件失败时订单为 `DELIVERY_FAILED`，并可重发。

### 12.4 手工验收流程

使用“1 管理员号 + 2 测试号”：

1. 管理员创建并发布测试商品。
2. 测试号 A 打开商店并提交付款申请。
3. 测试号 A 再次提交同商品，应被拦截。
4. 测试号 B 不能查看 A 的订单和写真。
5. 管理员批准 A 的订单。
6. `MAIL_MODE=log` 下检查模拟交付记录。
7. A 在“我的写真集”看到商品和下载信息。
8. A 点击重发，首次成功；冷却时间内再次点击应被拒绝。
9. 管理员停止商品；A 仍可查看，B 无法新购买。
10. 重启 Bot，商店面板和订单数据仍然有效，不重复交付。

---

## 13. P0 验收标准

以下全部满足才算完成：

- [ ] 管理员可以创建、编辑、发布和停止商品。
- [ ] `#shop` 只显示在售商品。
- [ ] 用户可以选择商品并提交 PayPay 付款申请。
- [ ] 付款申请绑定商品、价格、用户和邮箱。
- [ ] 审核频道可以批准或拒绝。
- [ ] 重复点击批准不会重复处理。
- [ ] 批准后尝试赋予 Buyer/Paid Role。
- [ ] 批准后自动执行邮件交付。
- [ ] 邮件失败时订单保留为可重试状态。
- [ ] 用户可以通过“我的写真集”查看已购商品。
- [ ] 未购买者和其他用户无法取得下载信息。
- [ ] 用户可以在冷却限制下重新发送交付邮件。
- [ ] 所有数据库迁移可重复执行。
- [ ] 日志不泄露邮箱、链接、密码和 Token。
- [ ] 现有会员付款与提醒功能不回归。
- [ ] README、`.env.example` 和运营文档已更新。
- [ ] 自动测试通过。

---

## 14. P1 后续范围（本次不得实现）

仅记录设计方向：

### 14.1 X / HP 动态聚合

- `#x-updates` 或 `#kiri-feed`；
- 只同步 Kiri 原创投稿；
- 保存 `post_id` 防止重复；
- 正文、少量预览、原文链接；
- 模块必须可关闭；
- X API 成本或不可用时支持管理员手动统一格式发布。

### 14.2 投票与企划

- 服装、鞋袜、妆容、场景、封面、标题；
- 普通投票与 Buyer 专属投票；
- 保存结果和结束时间；
- 管理员可发布结果。

### 14.3 提问箱和许愿池

- Discord Forum 为主要承载；
- Bot 提供表单、标签和匿名代投；
- 记录是否已回答、是否被选中。

### 14.4 活动

- Scheduled Event / Stage；
- 报名、提醒、参加记录；
- Buyer 限定活动。

---

## 15. P2/P3 长期方向（本次不得实现）

- 支持者等级和实际权益；
- 粉丝投稿与月度精选；
- HP 通过只读 JSON/API 展示商品；
- Discord OAuth 登录；
- Cloudflare R2 私有对象存储；
- 在线写真浏览；
- Discord Activity “Kiri Room”。

---

## 16. HP 最小联动式样（独立任务）

P0 Bot 完成后，另行在 `kiri-homepage` 实施。

### 16.1 页面

```text
/
/about
/universe
/products
/products/{product_id}
/faq
/community
```

### 16.2 商品页显示

- 封面；
- 商品名称；
- 简介；
- 价格；
- 照片/视频数量；
- 文件大小；
- 5～10 张压缩预览；
- “进入 Discord 购买”按钮。

不得：

- 在公开前端代码中保存下载链接或密码；
- 直接从 Bot SQLite 暴露敏感字段；
- 在 HP 上实现付款审核。

### 16.3 数据方式

第一阶段优先采用人工维护的公开商品 JSON：

```json
{
  "product_id": "KIRI-2026-08",
  "product_name": "KIRI 2026年8月写真集",
  "description": "...",
  "price_amount": 2000,
  "price_currency": "JPY",
  "cover_url": "/images/products/kiri-2026-08/cover.webp",
  "preview_images": ["..."],
  "content_count_label": "写真120张 / 视频2段",
  "file_size_label": "1.8GB",
  "discord_url": "...",
  "status": "SALE"
}
```

公开 JSON 不允许包含：

- `download_url`
- `download_password`
- 用户、订单或付款信息

---

## 17. Codex 最终输出格式

完成本次 P0 后，以以下格式报告：

```markdown
## 实现摘要

## 修改文件
- path: 说明

## 数据库迁移
- 表/字段/索引

## 新增配置
### 环境变量
### KVS

## 测试
- 命令
- 结果

## 手工验证步骤

## 兼容性说明

## 未实现 / 后续任务
```

不得只回复“已完成”。必须提供可复现的启动和验证方法。
