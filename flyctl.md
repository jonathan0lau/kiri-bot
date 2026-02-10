
# flyctl 使用手册（后台程序 / Discord Bot 版）

面向场景：**Fly.io 上跑后台进程**（例如 Python 心跳程序、Discord Bot），**不对外提供 HTTP 服务**。  
示例 App：`kiri-bot`（用你自己的 app 名替换）。

---

## 目录
- [1. 安装与验证](#1-安装与验证)
- [2. 账号与认证](#2-账号与认证)
- [3. App 与项目初始化](#3-app-与项目初始化)
- [4. fly.toml 推荐写法（后台进程）](#4-flytoml-推荐写法后台进程)
- [5. 部署（Deploy）](#5-部署deploy)
- [6. 日志与排错](#6-日志与排错)
- [7. Secrets（环境变量）](#7-secrets环境变量)
- [8. 运行控制（停机/开机/重启/规格）](#8-运行控制停机开机重启规格)
- [9. Machines（机器管理）](#9-machines机器管理)
- [10. SSH（进容器排查）](#10-ssh进容器排查)
- [11. 常用工作流（复制就能用）](#11-常用工作流复制就能用)
- [12. 最常用命令速记](#12-最常用命令速记)

---

## 1. 安装与验证

### Windows（winget）
```powershell
winget install -e --id Fly-io.flyctl
````

### 验证

```powershell
flyctl version
```

> 说明：有的教程用 `fly` 命令，你这边用 `flyctl` 即可（同一工具的不同调用方式/别名）。

---

## 2. 账号与认证

### 注册 / 登录

```powershell
flyctl auth signup
flyctl auth login
```

### 确认当前登录用户

```powershell
flyctl auth whoami
```

### 登出

```powershell
flyctl auth logout
```

---

## 3. App 与项目初始化

### 列出你的 Apps

```powershell
flyctl apps list
```

### 查看指定 App 状态

```powershell
flyctl status -a kiri-bot
```

### 初始化项目（在项目目录生成 fly.toml）

```powershell
flyctl launch --no-deploy
```

或显式指定 app 名与 region：

```powershell
flyctl launch --no-deploy --name kiri-bot --region nrt
```

---

## 4. fly.toml 推荐写法（后台进程）

后台程序 **不要配置** `[http_service]` 或 `[[services]]`（那是 Web 服务用的）。
推荐最小模板（直接覆盖你本地 `fly.toml`）：

```toml
app = "kiri-bot"
primary_region = "nrt"

[build]
  dockerfile = "Dockerfile"

[[vm]]
  cpu_kind = "shared"
  cpus = 1
  memory_mb = 256
```

---

## 5. 部署（Deploy）

### 推荐：远端构建（Windows 省事）

```powershell
flyctl deploy --remote-only -a kiri-bot
```

### 部署后确认

```powershell
flyctl status -a kiri-bot
flyctl logs -a kiri-bot
```

---

## 6. 日志与排错

### 实时查看日志

```powershell
flyctl logs -a kiri-bot
```

### 常见现象与含义

* `Image = -`
  说明：**从未成功部署过镜像** → 运行 `flyctl deploy --remote-only`
* 程序启动后立刻退出/反复重启
  常见原因：入口命令错误、依赖缺失、环境变量未设置、内存不足（256→512）

---

## 7. Secrets（环境变量）

所有敏感信息（Discord Token、API Key、DB 密码）一律放 secrets，不写进代码/仓库。

### 设置

```powershell
flyctl secrets set KIRI_ENV="dev" -a kiri-bot
flyctl secrets set DISCORD_TOKEN="xxx" DISCORD_GUILD_ID="yyy" -a kiri-bot
```

### 查看（不显示值，只显示 key 与更新时间）

```powershell
flyctl secrets list -a kiri-bot
```

### 删除某个 key

```powershell
flyctl secrets unset DISCORD_TOKEN -a kiri-bot
```

> 经验：修改 secrets 后，为了确保进程读取新值，通常重启一下最稳（见下一节）。

---

## 8. 运行控制（停机/开机/重启/规格）

### 重启 App

```powershell
flyctl apps restart kiri-bot
```

### 停机省钱（不删 App：机器数缩到 0）

```powershell
flyctl scale count 0 -a kiri-bot
```

### 开机（机器数缩回 1）

```powershell
flyctl scale count 1 -a kiri-bot
```

### 调整内存（如果 256 不够）

```powershell
flyctl scale memory 512 -a kiri-bot
```

> 更推荐通过 `fly.toml` 的 `memory_mb` 固定规格，避免漂移。

---

## 9. Machines（机器管理）

### 查看机器列表

```powershell
flyctl machines list -a kiri-bot
```

### 查看某台机器详情

```powershell
flyctl machines status <machine_id> -a kiri-bot
```

### 重启某台机器

```powershell
flyctl machines restart <machine_id> -a kiri-bot
```

### 删除某台机器（谨慎）

```powershell
flyctl machines destroy <machine_id> -a kiri-bot
```

---

## 10. SSH（进容器排查）

### 进入机器终端

```powershell
flyctl ssh console -a kiri-bot
```

进去后常用：

* `env`：看环境变量是否注入
* `ps aux`：看进程是否在跑
* `ls -la`：确认文件是否存在
* `python --version`

---

## 11. 常用工作流（复制就能用）

### A) 改代码 → 部署 → 看日志

```powershell
flyctl deploy --remote-only -a kiri-bot
flyctl logs -a kiri-bot
```

### B) 设置/更新 secrets → 重启 → 验证

```powershell
flyctl secrets set KIRI_ENV="prod" -a kiri-bot
flyctl apps restart kiri-bot
flyctl logs -a kiri-bot
```

### C) 今天收工先停机省钱 → 需要时再开

```powershell
flyctl scale count 0 -a kiri-bot
# ...
flyctl scale count 1 -a kiri-bot
```

---

## 12. 最常用命令速记（你以后基本就靠这几条）

```powershell
flyctl auth login
flyctl apps list
flyctl status -a kiri-bot
flyctl deploy --remote-only -a kiri-bot
flyctl logs -a kiri-bot
flyctl secrets set KEY="VALUE" -a kiri-bot
flyctl apps restart kiri-bot
flyctl scale count 0|1 -a kiri-bot
```

```
::contentReference[oaicite:0]{index=0}
```
