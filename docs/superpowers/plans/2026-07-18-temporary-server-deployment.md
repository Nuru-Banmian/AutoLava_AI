# 临时服务器部署 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 AutoLava AI 部署到 `116.62.112.245:8080`，使用私有 MySQL 容器和每日完整备份。

**Architecture:** 保持 `compose.yaml` 的安全默认值；新增临时 Compose 覆盖文件，发布 8080 端口并运行私有 MySQL。服务器密钥只保存在 `/opt/autolava/.env`，备份脚本从 MySQL 容器导出 SQL 到宿主机目录。

**Tech Stack:** Docker Engine、Docker Compose plugin、MySQL 8.4、FastAPI、React/Nginx、PowerShell、OpenSSH。

## Global Constraints

- 临时入口固定为 `http://116.62.112.245:8080`，设置 `AUTOLAVA_COOKIE_SECURE=false`。
- MySQL 和 API 不得发布宿主机端口。
- 不修改或重启 Nginx、Halo、PostgreSQL 或 `sag-app`。
- 生产密钥不进入 Git，服务器密钥文件权限为 `0600`。
- MySQL 数据使用 `autolava_mysql_data` 命名卷；每天一次完整 SQL 备份，保留最近 7 天。

---

### Task 1: 新增临时 Compose 覆盖配置

**Files:**
- Create: `compose.temporary.yaml`
- Modify: `backend/tests/test_deployment_config.py`

**Interfaces:**
- Consumes: 根目录 `.env` 中的 `AUTOLAVA_DB_PASSWORD` 和 `AUTOLAVA_DB_ROOT_PASSWORD`。
- Produces: `docker compose -f compose.yaml -f compose.temporary.yaml up -d --build` 启动 Web、API、MySQL。

- [ ] **Step 1: 写入失败测试**

在 `backend/tests/test_deployment_config.py` 加入测试，断言临时文件包含 `autolava-api`、`autolava-web`、`autolava-db`；Web 发布 `0.0.0.0:8080:80`；数据库没有 `ports`；API 等待数据库健康；数据库使用 `autolava_mysql_data:/var/lib/mysql`。

- [ ] **Step 2: 运行失败测试**

运行：`cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_deployment_config.py -q`

预期：因缺少 `compose.temporary.yaml` 而失败。

- [ ] **Step 3: 创建最小覆盖文件**

```yaml
services:
  autolava-api:
    environment:
      AUTOLAVA_DATABASE_URL: mysql+asyncmy://autolava:${AUTOLAVA_DB_PASSWORD}@autolava-db:3306/autolava
    depends_on:
      autolava-db:
        condition: service_healthy
  autolava-web:
    ports:
      - "0.0.0.0:8080:80"
  autolava-db:
    image: mysql:8.4
    restart: unless-stopped
    environment:
      MYSQL_DATABASE: autolava
      MYSQL_USER: autolava
      MYSQL_PASSWORD: ${AUTOLAVA_DB_PASSWORD:?set a database password}
      MYSQL_ROOT_PASSWORD: ${AUTOLAVA_DB_ROOT_PASSWORD:?set a database root password}
    command: ["--character-set-server=utf8mb4", "--collation-server=utf8mb4_unicode_ci"]
    volumes:
      - autolava_mysql_data:/var/lib/mysql
    healthcheck:
      test: ["CMD-SHELL", "mysqladmin ping -h localhost -uroot -p$$MYSQL_ROOT_PASSWORD --silent"]
      interval: 5s
      timeout: 5s
      retries: 20
      start_period: 20s
volumes:
  autolava_mysql_data:
```

- [ ] **Step 4: 运行针对性测试并提交**

运行：`cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_deployment_config.py -q`

预期：部署配置测试通过。

```powershell
git add compose.temporary.yaml backend/tests/test_deployment_config.py
git commit -m "feat: add temporary docker deployment stack"
```

### Task 2: 添加生产数据库完整备份脚本

**Files:**
- Create: `scripts/backup-production-db.sh`
- Modify: `README.md`

**Interfaces:**
- Consumes: `/opt/autolava/.env` 和运行中的 `autolava-db`。
- Produces: `/opt/autolava/backups/autolava-YYYYMMDD-HHMMSS.sql.gz`，并清除 7 天前的完整备份。

- [ ] **Step 1: 创建脚本**

```sh
#!/usr/bin/env sh
set -eu
APP_DIR=${AUTOLAVA_APP_DIR:-/opt/autolava}
BACKUP_DIR="$APP_DIR/backups"
TIMESTAMP=$(date -u +%Y%m%d-%H%M%S)
mkdir -p "$BACKUP_DIR"
umask 077
cd "$APP_DIR"
docker compose -f compose.yaml -f compose.temporary.yaml exec -T autolava-db \
  sh -c 'exec mysqldump -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' \
  | gzip -c > "$BACKUP_DIR/autolava-$TIMESTAMP.sql.gz"
find "$BACKUP_DIR" -type f -name 'autolava-*.sql.gz' -mtime +6 -delete
```

- [ ] **Step 2: 在 README 说明备份和恢复**

记录手动执行 `/opt/autolava/scripts/backup-production-db.sh`、每天一次完整备份、保留 7 天；给出 `gunzip -c` 管道至 MySQL 容器的恢复命令。

- [ ] **Step 3: 检查并提交**

运行：`bash -n scripts/backup-production-db.sh`

预期：退出码为 `0`。

```powershell
git add scripts/backup-production-db.sh README.md
git commit -m "feat: add production database backup script"
```

### Task 3: 本地运行验证

**Files:**
- Modify: 无

**Interfaces:**
- Consumes: 本机 `.autolava-db.env`、`.env` 和 MySQL。
- Produces: `http://127.0.0.1:8000/health` 与 `http://127.0.0.1:5173/health` 返回 `200`。

- [ ] **Step 1: 启动本地服务**

运行：`powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -NoBrowser`

预期：输出 `AutoLava AI 已就绪：http://127.0.0.1:5173`。

- [ ] **Step 2: 在另一窗口检查健康状态**

```powershell
(Invoke-WebRequest http://127.0.0.1:8000/health -UseBasicParsing).StatusCode
(Invoke-WebRequest http://127.0.0.1:5173/health -UseBasicParsing).StatusCode
```

预期：两行均为 `200`。

- [ ] **Step 3: 在启动器窗口按 Ctrl+C**

预期：输出关闭信息，8000 与 5173 端口释放。

### Task 4: 服务器部署、备份与健康检查

**Files:**
- Create on server: `/opt/autolava/.env`
- Create on server: `/etc/cron.d/autolava-backup`
- Create on server: `/root/autolava-initial-credentials.txt`

**Interfaces:**
- Consumes: 当前 Git 提交、SSH `root@116.62.112.245`、Docker Engine。
- Produces: IP 加端口可访问的临时实例、私有 MySQL、每日备份任务。

- [ ] **Step 1: 安装 Compose 插件**

运行：`ssh root@116.62.112.245 'apt-get update && apt-get install -y docker-compose-plugin && docker compose version'`

预期：输出 Compose 版本，不停止现有容器。

- [ ] **Step 2: 传输当前 Git 提交**

运行：`git archive --format=tar HEAD | ssh root@116.62.112.245 'rm -rf /opt/autolava.new && mkdir -p /opt/autolava.new && tar -x -C /opt/autolava.new && mv /opt/autolava.new /opt/autolava'`

预期：服务器不接收本机 `.env`、`.autolava-db.env` 或 `.git`。

- [ ] **Step 3: 生成权限为 0600 的服务器密钥、构建并启动**

在服务器生成高熵数据库密码、JWT 密钥与管理员密码，写入 `.env` 和 `/root/autolava-initial-credentials.txt`；运行：

```sh
cd /opt/autolava
docker compose -f compose.yaml -f compose.temporary.yaml up -d --build
docker compose -f compose.yaml -f compose.temporary.yaml ps
```

预期：只有 Web 显示 `0.0.0.0:8080->80/tcp`。

- [ ] **Step 4: 配置并验证每日备份**

```sh
chmod 700 /opt/autolava/scripts/backup-production-db.sh
printf '17 3 * * * root /opt/autolava/scripts/backup-production-db.sh\n' > /etc/cron.d/autolava-backup
chmod 644 /etc/cron.d/autolava-backup
/opt/autolava/scripts/backup-production-db.sh
ls -l /opt/autolava/backups
```

预期：生成一个压缩 SQL 文件；cron 每天 UTC 03:17 运行。

- [ ] **Step 5: 验证健康检查和日志**

运行：

```sh
curl --fail --silent --show-error http://127.0.0.1:8080/health
docker compose -f /opt/autolava/compose.yaml -f /opt/autolava/compose.temporary.yaml logs --tail=100 autolava-api autolava-web autolava-db
```

运行：`curl --fail --silent --show-error http://116.62.112.245:8080/health`

预期：两次健康检查均成功，日志没有数据库连接或迁移错误。
