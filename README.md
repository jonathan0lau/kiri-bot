# kiri-bot

[中文](#中文说明) | [日本語](#日本語説明)

一个使用 Python、discord.py 和 SQLite 编写的 Discord 社群管理机器人。项目提供两种运行模式：

- `main.py`：完整模式，负责 PayPay 付费申请、人工审核、会员权限、新人资料和到期提醒。
- `bot.py`：简易模式，只提供 `/grant` 和 `/revoke` 两个角色管理命令。

> 注意：当前 `Dockerfile` 默认运行 `bot.py`。如需部署完整模式，请将其中的启动命令改为 `CMD ["python", "main.py"]`。

---

## 中文说明

### 这个机器人有什么用？

完整模式适合运营带有付费会员区的 Discord 社群，可以把以下工作串成一个流程：

1. 新成员加入服务器后，通过按钮填写昵称、自我介绍、联系方式、Twitter 和生日。
2. 管理员发布付费面板，成员取得 PayPay 链接并提交付款名。
3. 机器人把申请发送到审核频道，管理员点击按钮通过或拒绝。
4. 审核通过后，机器人自动授予付费会员角色，并记录会员期限。
5. 机器人定期扫描即将到期的会员，并在指定频道提醒。
6. 启动时自动建立当年的 12 个付费频道和对应的月度角色。

数据保存在 SQLite 数据库中，默认文件为 `bot.db`。

### 功能一览

- PayPay 收款链接的设置与展示
- 付款申请及管理员按钮审核
- 自动授予付费会员角色
- 会员开始时间、到期时间及状态记录
- 即将到期提醒
- 新成员欢迎消息和个人资料收集
- SQLite 配置中心 `Kvs_M`
- 自动创建 `Paid Content` 分类、`Paid_年_月` 角色和月度频道
- 简易的 Slash Command 角色授予/撤销模式

### 环境要求

- Python 3.9 或更高版本（Docker 使用 Python 3.12）
- 一个 Discord Bot
- Bot 已加入目标 Discord 服务器

安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 创建及设置 Discord Bot

1. 在 [Discord Developer Portal](https://discord.com/developers/applications) 创建 Application 和 Bot。
2. 在 Bot 设置页启用以下 Privileged Gateway Intents：
   - Server Members Intent
   - Message Content Intent（完整模式的 `!` 命令需要）
3. 邀请 Bot 进入服务器，并授予以下权限：
   - View Channels
   - Send Messages
   - Read Message History
   - Manage Roles
   - Manage Channels（完整模式自动创建频道和角色时需要）
4. 在服务器角色列表中，把 Bot 的角色放到它需要管理的角色上方。
5. 打开 Discord 的“开发者模式”，右键频道或角色即可复制 ID。

### 完整模式：付费会员管理

#### 1. 设置环境变量

PowerShell 示例：

```powershell
$env:DISCORD_TOKEN = "你的 Discord Bot Token"
$env:KVS_ADMIN_KEY = "用于管理配置的强密码"
$env:DB_PATH = "bot.db"
python main.py
```

环境变量：

| 变量 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `DISCORD_TOKEN` | 是 | `PUT_YOUR_TOKEN_HERE` | Discord Bot Token |
| `KVS_ADMIN_KEY` | 是 | 空 | 通过 DM 修改机器人配置时使用的密码 |
| `DB_PATH` | 否 | `bot.db` | SQLite 数据库路径 |

#### 2. 初始化运行配置

首次启动时，机器人会自动创建数据库和默认配置。请私信 Bot，用以下格式配置各项 ID：

```text
!kvs <密码> <key1> <key2> <key3> <值> [备注]
```

推荐依次执行：

```text
!kvs 你的密码 discord channel review_id 审核频道ID
!kvs 你的密码 discord channel remind_id 到期提醒频道ID
!kvs 你的密码 discord channel welcome_id 欢迎频道ID
!kvs 你的密码 discord role paid_id 付费会员角色ID
!kvs 你的密码 auth role admin_role_ids 管理员角色ID
!kvs 你的密码 billing global month_price_label 1000円
!kvs 你的密码 reminder global expiry_days 5
!kvs 你的密码 reminder global scan_hours 12
```

多个管理员角色 ID 使用英文逗号分隔，例如：

```text
!kvs 你的密码 auth role admin_role_ids 123456789,987654321
```

查询单项配置：

```text
!kvsget discord channel review_id
```

`!kvs` 和 `!kvsget` 只能在与 Bot 的私信中使用。配置写入后，业务命令会重新读取配置，无需手动重启。

#### 3. 管理员发布付费入口

在服务器频道中执行：

```text
!setpaypay https://你的-paypay-链接
!paypanel
```

也可以给链接附加有效期文本：

```text
!setpaypay https://你的-paypay-链接 2026-12-31 23:59 JST
```

查看当前链接：

```text
!getpaypay
```

其中 `!setpaypay` 和 `!paypanel` 仅允许配置的管理员角色使用；`!getpaypay` 当前对服务器成员开放。

#### 4. 成员付款和审核流程

1. 成员点击“支付 1 个月”，Bot 仅向该成员显示 PayPay 链接。
2. 付款后点击“已付款”，填写 PayPay 账户名和备注。
3. 审核频道收到申请，管理员点击“确认通过”或“拒绝”。
4. 通过后，Bot 授予 `paid_id` 对应的角色，并私信成员。
5. 当前会员期限规则为：从审核通过时开始，到下一个月的最后一天 `23:59:59`（JST）结束。

#### 5. 新人资料

新成员加入服务器时，Bot 会在 `welcome_id` 对应频道发送欢迎消息和资料填写按钮。如果没有设置该 ID，则尝试使用服务器的系统频道。

#### 6. 自动创建付费区

完整模式每次启动时会为当前年份检查并创建：

- 分类：`Paid Content`
- 角色：`Paid_2026_01` 至 `Paid_2026_12`
- 频道：`2026-01` 至 `2026-12`

月度频道默认对 `@everyone` 隐藏，并对对应月度角色及配置的管理员角色开放。这个月度角色体系与审核时授予的 `paid_id` 是两套独立设置，需要根据你的运营方式自行分配月度角色。

### 简易模式：角色管理

简易模式提供两个 Slash Command：

```text
/grant member:@成员
/revoke member:@成员
```

只有具有 Administrator 或 Manage Roles 权限的成员可以执行。配置并启动：

```powershell
$env:DISCORD_TOKEN = "你的 Discord Bot Token"
$env:DISCORD_GUILD_ID = "服务器 ID"
$env:TARGET_ROLE_NAME = "Member"
python bot.py
```

`DISCORD_GUILD_ID` 可省略，但设置后命令会同步到指定服务器，通常能更快显示。

### Docker / Fly.io 部署

当前 Docker 配置运行简易模式：

```powershell
docker build -t kiri-bot .
docker run --rm -e DISCORD_TOKEN="你的Token" -e DISCORD_GUILD_ID="服务器ID" -e TARGET_ROLE_NAME="Member" kiri-bot
```

部署到 Fly.io：

```powershell
flyctl secrets set DISCORD_TOKEN="你的Token" DISCORD_GUILD_ID="服务器ID" TARGET_ROLE_NAME="Member" -a kiri-bot
flyctl deploy --remote-only -a kiri-bot
flyctl logs -a kiri-bot
```

若要部署完整模式：

1. 将 `Dockerfile` 最后一行改成 `CMD ["python", "main.py"]`。
2. 设置 `DISCORD_TOKEN` 和 `KVS_ADMIN_KEY`。
3. 为 SQLite 配置持久化磁盘，并把 `DB_PATH` 指向挂载目录；否则重新部署或更换机器时数据可能丢失。

### 安全注意事项

- 不要把 Discord Token、管理密码或真实 PayPay 链接提交到 Git。
- 如果 Token 曾经写进文件或提交到仓库，请立即在 Discord Developer Portal 重置并替换它；仅从文件中删除并不能使旧 Token 失效。
- 生产环境请使用环境变量或 Fly.io Secrets。
- `bot.db` 可能包含成员资料和付款记录，请限制访问并做好备份。

---

## 日本語説明

### このBotは何に使えますか？

このプロジェクトは、Discordコミュニティの有料会員管理を補助するBotです。完全版では、次の運用を一つの流れにまとめられます。

1. 新規メンバーがボタンからニックネーム、自己紹介、連絡先、Twitter、誕生日を登録する。
2. 管理者が支払いパネルを設置し、メンバーがPayPayリンクを取得して支払名を送信する。
3. Botが申請を審査チャンネルへ送り、管理者がボタンで承認または却下する。
4. 承認時に有料会員ロールを自動付与し、会員期限を記録する。
5. 期限が近い会員を定期的に確認し、指定チャンネルへ通知する。
6. 起動時に当年12か月分の有料チャンネルと月別ロールを作成する。

データはSQLiteに保存され、既定のデータベースファイルは `bot.db` です。

### 主な機能

- PayPay支払いリンクの登録・表示
- 支払い申請と管理者によるボタン審査
- 有料会員ロールの自動付与
- 会員期間・ステータスの記録
- 有効期限前のリマインド
- 新規メンバー向けウェルカムメッセージとプロフィール登録
- SQLiteテーブル `Kvs_M` による動的設定
- `Paid Content` カテゴリー、月別ロール、月別チャンネルの自動作成
- Slash Commandによる簡易ロール付与・解除モード

### 動作環境

- Python 3.9以上（DockerではPython 3.12）
- Discord Bot
- Botを導入するDiscordサーバー

依存パッケージをインストールします。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### Discord Botの準備

1. [Discord Developer Portal](https://discord.com/developers/applications) でApplicationとBotを作成します。
2. Bot設定で次のPrivileged Gateway Intentsを有効にします。
   - Server Members Intent
   - Message Content Intent（完全版の `!` コマンドで必要）
3. Botをサーバーに招待し、次の権限を付与します。
   - View Channels
   - Send Messages
   - Read Message History
   - Manage Roles
   - Manage Channels（完全版の自動作成機能で必要）
4. Discordのロール設定で、Botのロールを管理対象ロールより上に配置します。
5. Discordの「開発者モード」を有効にすると、チャンネルやロールを右クリックしてIDをコピーできます。

### 完全版：有料会員管理

#### 1. 環境変数を設定する

PowerShellの例：

```powershell
$env:DISCORD_TOKEN = "Discord Bot Token"
$env:KVS_ADMIN_KEY = "設定管理用の強力なパスワード"
$env:DB_PATH = "bot.db"
python main.py
```

| 変数 | 必須 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `DISCORD_TOKEN` | はい | `PUT_YOUR_TOKEN_HERE` | Discord Bot Token |
| `KVS_ADMIN_KEY` | はい | 空 | DMから設定を変更するときのパスワード |
| `DB_PATH` | いいえ | `bot.db` | SQLiteデータベースのパス |

#### 2. 実行時設定を登録する

初回起動時にデータベースと既定設定が自動作成されます。BotへのDMで次の形式のコマンドを送ります。

```text
!kvs <パスワード> <key1> <key2> <key3> <値> [メモ]
```

設定例：

```text
!kvs パスワード discord channel review_id 審査チャンネルID
!kvs パスワード discord channel remind_id 期限通知チャンネルID
!kvs パスワード discord channel welcome_id ウェルカムチャンネルID
!kvs パスワード discord role paid_id 有料会員ロールID
!kvs パスワード auth role admin_role_ids 管理者ロールID
!kvs パスワード billing global month_price_label 1000円
!kvs パスワード reminder global expiry_days 5
!kvs パスワード reminder global scan_hours 12
```

管理者ロールが複数ある場合は、IDを半角カンマで区切ります。

```text
!kvs パスワード auth role admin_role_ids 123456789,987654321
```

設定値の確認：

```text
!kvsget discord channel review_id
```

`!kvs` と `!kvsget` はBotへのDMでのみ利用できます。業務コマンド実行時に設定が再読み込みされるため、通常は再起動不要です。

#### 3. 支払いパネルを設置する

サーバー内で管理者が次を実行します。

```text
!setpaypay https://PayPayリンク
!paypanel
```

リンクに有効期限の表示を追加する例：

```text
!setpaypay https://PayPayリンク 2026-12-31 23:59 JST
```

現在のリンクを確認するコマンド：

```text
!getpaypay
```

`!setpaypay` と `!paypanel` は設定済みの管理者ロールのみ実行できます。現在、`!getpaypay` はサーバーメンバーも実行できます。

#### 4. 支払い申請と審査

1. メンバーが「支付 1 个月」ボタンを押すと、本人だけにPayPayリンクが表示されます。
2. 支払い後に「已付款」を押し、PayPay表示名とメモを入力します。
3. 審査チャンネルで管理者が「确认通过」または「拒绝」を押します。
4. 承認されると `paid_id` のロールが付与され、メンバーへDMが送信されます。
5. 現在の会員期限は、承認時から翌月末の `23:59:59`（JST）までです。

> Bot内のボタンやメッセージは現在中国語で表示されます。

#### 5. 新規メンバーのプロフィール

新しいメンバーが参加すると、`welcome_id` のチャンネルにウェルカムメッセージと入力ボタンを送信します。未設定の場合はサーバーのシステムチャンネルを使用します。

#### 6. 有料エリアの自動作成

完全版は起動時に当年分の次の項目を確認し、存在しなければ作成します。

- カテゴリー：`Paid Content`
- ロール：`Paid_2026_01` ～ `Paid_2026_12`
- チャンネル：`2026-01` ～ `2026-12`

月別チャンネルは `@everyone` から非表示になり、対応する月別ロールと管理者ロールから閲覧できます。月別ロールと、審査時に付与する `paid_id` は別の仕組みです。運用方針に合わせて月別ロールを割り当ててください。

### 簡易版：ロール管理

簡易版には次のSlash Commandがあります。

```text
/grant member:@メンバー
/revoke member:@メンバー
```

AdministratorまたはManage Roles権限を持つメンバーだけが実行できます。

```powershell
$env:DISCORD_TOKEN = "Discord Bot Token"
$env:DISCORD_GUILD_ID = "サーバーID"
$env:TARGET_ROLE_NAME = "Member"
python bot.py
```

`DISCORD_GUILD_ID` は省略できますが、指定すると対象サーバーへコマンドが同期され、通常は早く表示されます。

### Docker / Fly.ioへのデプロイ

現在のDocker設定は簡易版を起動します。

```powershell
docker build -t kiri-bot .
docker run --rm -e DISCORD_TOKEN="Token" -e DISCORD_GUILD_ID="サーバーID" -e TARGET_ROLE_NAME="Member" kiri-bot
```

Fly.ioへのデプロイ例：

```powershell
flyctl secrets set DISCORD_TOKEN="Token" DISCORD_GUILD_ID="サーバーID" TARGET_ROLE_NAME="Member" -a kiri-bot
flyctl deploy --remote-only -a kiri-bot
flyctl logs -a kiri-bot
```

完全版をデプロイする場合：

1. `Dockerfile` の最終行を `CMD ["python", "main.py"]` に変更します。
2. `DISCORD_TOKEN` と `KVS_ADMIN_KEY` を設定します。
3. SQLite用の永続ボリュームを用意し、`DB_PATH` をマウント先に設定します。設定しない場合、再デプロイやMachine交換時にデータが失われる可能性があります。

### セキュリティ上の注意

- Discord Token、管理用パスワード、実際のPayPayリンクをGitへコミットしないでください。
- TokenをファイルやGit履歴へ一度でも記録した場合は、Discord Developer Portalですぐに再生成してください。ファイルから削除するだけでは古いTokenは無効になりません。
- 本番環境では環境変数またはFly.io Secretsを利用してください。
- `bot.db` にはプロフィールや支払い記録が含まれる可能性があります。アクセスを制限し、バックアップを作成してください。

---

## 文件结构 / ファイル構成

| 文件 / ファイル | 说明 / 説明 |
| --- | --- |
| `main.py` | 完整会员管理入口 / 完全版の起動ファイル |
| `bot_views.py` | 按钮、表单和审核 UI / ボタン、フォーム、審査UI |
| `storage_sqlite.py` | SQLite 表、配置及数据操作 / SQLiteのテーブル・設定・データ操作 |
| `config.py` | 完整模式环境变量 / 完全版の環境変数 |
| `bot.py` | 简易角色管理入口 / 簡易ロール管理の起動ファイル |
| `Dockerfile` | Docker 镜像配置（当前启动 `bot.py`）/ Docker設定（現在は `bot.py` を起動） |
| `fly.toml` | Fly.io 部署配置 / Fly.ioデプロイ設定 |
| `requirements.txt` | Python 依赖 / Python依存パッケージ |

## License

本项目目前未提供 License 文件。公开发布或允许第三方使用前，建议补充适当的开源许可证。

現在、このプロジェクトにはLicenseファイルがありません。公開・再配布する場合は、適切なライセンスを追加してください。
