# P0 本地验收记录（2026-10-26）

基线核对见 P0-AUDIT.md；配置见 CLUB-P0.md。交付分支为 feature/club-p0。本机使用 systemd 用户服务运行主页与后台；Discord Bot 按用户安排等待稍后配置 Token。

- Python 21 项 unittest 通过（含原有7项回归）。新增测试涵盖活动状态和边界、会员资格与角色操作、公告持久化与结果不确定、事务原子性、公开字段、登录/CSRF、会话伪造、重复会员登记。
- Python 新服务、worker、Bot 入口和旧入口通过 py_compile。
- 主页 npm run lint 无警告；npm run build 与 TypeScript 检查通过。
- Chromium 手机390×844实际验证：未登录转登录、后台发布活动同时产生公告任务、公开活动列表和首页可见、截止活动仍在近期但不能报名、结束活动只在历史且详情正常、默认日文、无横向溢出或 JS 错误。
- 已打开的活动列表在 Bot 未运行时，随结束时间到达于30秒刷新周期内自动移除活动；原详情仍显示结束状态。
- 手机后台新建方案（排序留空）→ 公开会员方案页；管理员登记赠送资格成功。
- 公告发送与实际 Discord 角色变更仅通过 discord.py 模拟对象验证；未使用真实 Token，没有向真实频道发送公告。
- 真实环境尚需填写服务域名、管理员配置、Bot Token、角色/频道 ID、实际方案与作品链接，并进行测试服务器验收。

截图见 screenshots/admin-mobile.png、screenshots/events-mobile.png。图片中的 QA 内容和角色/频道 ID 均为测试数据，没有导入真实会员或线上数据库。
