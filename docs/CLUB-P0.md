# Kiri Club P0：配置与验证

范围：新增共享目录/会员方案/资格/公告 outbox，手机友好的日文管理后台，主页动态读取公开目录。旧付款、商店、历史月度表保留，不自动迁移和不作为新方案会员凭据。

## 运行方式

- Python 3.9+、SQLite、discord.py；无新增生产依赖。
- 管理服务：python club_admin.py
- 新 P0 Bot：python club_bot.py（Docker 默认入口已改为此入口）。
- 旧完整付款流程仍可通过 python main.py 启动。只有确实需要把新 worker 运行在旧进程中时才设置 CLUB_ENABLED=1；不要同时运行 club_bot.py 和该兼容 worker。
- 一台主机上两个 Python 进程共用 CLUB_DB_PATH；SQLite 文件不要放到不支持可靠锁的网络共享，不要在多个主机复制数据库分别写入。主页通过 HTTP API 访问，不需要挂载数据库。

## 本地运行

在仓库目录建立专用测试数据库，切勿拿已跟踪的旧 bot.db 做测试：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
mkdir -p .local-data
export CLUB_DB_PATH="$PWD/.local-data/club.db"
export CLUB_MEDIA_DIR="$PWD/.local-data/media"
export CLUB_ADMIN_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
export CLUB_ADMIN_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
# 在本机保存你生成的密码，用于登录；不要提交它。
export CLUB_COOKIE_SECURE=0
export CLUB_ADMIN_ORIGIN=http://127.0.0.1:8080
.venv/bin/python club_admin.py
```

浏览器打开 http://127.0.0.1:8080/admin/login，用 CLUB_ADMIN_PASSWORD 登录。仅本机 HTTP 调试设置 COOKIE_SECURE=0。线上必须 HTTPS + COOKIE_SECURE=1，正确设置 CLUB_ADMIN_ORIGIN；反向代理到管理服务，防止公网直接访问内部 HTTP 端口。

公开上传需设置 CLUB_PUBLIC_URL 为管理服务的真实 HTTPS 域名；上传目录只放可公开展示的 JPEG/PNG/WebP (每张≤4MB)。上传后自动填封面或追加预览 URL。先本地准备内容也可直接填现有 HTTPS 托管链接。

CLUB_SITE_URL 是主页正式地址，用于公告详情链接。主页设置 CLUB_API_URL 指向该管理 API 的可达地址；具体见主页 CLUB-P0.md。

在另一个具有相同 CLUB_DB_PATH 的进程环境配置 DISCORD_TOKEN，启动 club_bot.py。需要开启 Discord Server Members Intent，Bot 需要 View Channel、Send Messages、Embed Links、Manage Roles，且角色层级高于要管理的角色。不需要付款验证或 Message Content Intent。

可选 CLUB_WELCOME_CHANNEL_ID 开启单条入群指引；已有欢迎服务时不配置，避免重复欢迎。

## 使用顺序

1. 后台创建会员方案：名称、价格说明、权益、Discord 角色 ID（每行一个）。免费方案可不配置角色。
2. 录入系列、作品或活动。时间表单按日本时间，必须有活动开始与结束，截止时间单独填写。草稿不会进入公开 API。
3. 选择 PUBLISHED，可勾选同时通知并输入频道 ID。保存事务将公开数据与唯一公告任务一起提交。
4. 主页重新请求后立即读取新内容，已打开页面最多30秒刷新；不需要重新构建主页。
5. 会员管理输入服务器/用户 ID、方案、起止时间，选择手动或赠送；支持搜索、延长、方案变更和取消。
6. Bot 每30秒合并各用户当前有效的所有资格并同步角色。重启后先重新计算，已到期资格不会继续授权。免费成员身份及非管理角色不会被移除。
7. 通知页查看 PENDING / SENDING / SENT / FAILED / UNCERTAIN、Discord message ID 与失败原因。操作履历查看会员变更与角色操作。

角色映射只能使用专门由本服务管理的会员角色；不要映射管理员/机器人角色，也不要与旧月度付费系统共用一个角色。方案下架不会取消既有资格；要取消权益请显式取消资格。赠送资格只授权本 Discord，完全不验证或改变 Fantia 资格。

## 公告防重复的边界

同一手动 source_key 只建立一个任务；内容通知以 kind/id/revision 为键，重复保存旧 revision 被拒绝，编辑并再次勾选通知会视为新的更正公告。worker 以事务领取任务，成功记录 message ID。

网络中断可能发生在 Discord 已接收但本地尚未记账之间，不能凭空保证外部 exactly-once。发送结果不明确或发送中崩溃的任务进入 UNCERTAIN，不自动重发；应先到 Discord 核实。P0 不提供盲目重试按钮；自动重试、原消息编辑和更正关联属于 P1。

## 验证

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile club_store.py club_admin.py club_worker.py club_bot.py main.py
```

测试覆盖：结束/报名截止/满员/取消及历史保留、日本时间边界、延长/变更/赠送重叠与到期撤权、保留非管理角色、映射更新、发布与通知原子性、重启去重、发送结果不确定、公开字段白名单、会话/CSRF/后台未授权访问。

真实 Discord 需另行验收：开通后能看到目标频道、取消一条赠送仍保留其他有效资格、全部到期后只撤对应会员角色、重启不重复公告。自动测试使用 Discord mock，不代表已向真实服务器发消息。

## 未完成与待确定

- P1：活动提醒/自动更正、到期提醒、原公告编辑、失败重试、提醒角色、原生 Discord 投票整合、Fantia 获取方式调查与自动通知。
- P2：支付/自动会员验证、站内订单/交付、限定下载、内容备份、个人中心。没有新增限定文件访问端点；未授权请求返回404，不伪造已完成服务端限定下载鉴权。
- 生产域名、实际社交/购买链接、计划价格/权益与角色 ID、管理员密码、Bot Token、图片存储与磁盘备份必须由实际运营配置。没有部署或修改线上服务器。
- 后台为单管理员口令，未来多管理员身份/OAuth 可增量添加；会话8小时、HttpOnly/SameSite/CSRF，密码轮换时同时轮换 secret 撤销旧会话。

## 本机用户级 systemd

服务模板位于 deploy/：kiri-club-admin.service、kiri-club-bot.service。分别引用 ~/.config/kiri-club/admin.env 和 bot.env；真实凭据与数据库不放入仓库。主页另有 kiri-homepage.service，端口13000，管理端口18080。

仅局域网 HTTP 部署可明确设置 CLUB_ALLOW_LOCAL_HTTP=1，并将 CLUB_PUBLIC_URL 设为本机管理 origin。此时只额外允许该 origin 的 HTTP 图片链接，主页需配置相同 CLUB_MEDIA_ORIGIN；对其他 HTTP 来源继续拒绝。正式外网部署仍使用 HTTPS、Secure Cookie。

后续在 bot.env 填入 DISCORD_TOKEN 后，执行 systemctl --user enable --now kiri-club-bot.service，随后用 systemctl --user status kiri-club-bot.service 查看状态。Bot 未运行时，后台通知任务保持待处理，主页与活动过期判断仍正常工作。
