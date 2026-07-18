# 临时服务器部署设计

## 目标

在用户注册域名期间，将当前 AutoLava AI 版本部署至阿里云服务器，暂时通过公网 IP 加端口访问。

## 架构

发布版本在独立的 Compose 网络中运行三个 Docker 容器：

- `autolava-web`：提供 React 前端，并转发 API 请求。
- `autolava-api`：执行 Alembic 数据库迁移并运行 FastAPI 服务。
- `autolava-db`：运行专用 MySQL 数据库，数据持久化到命名卷。

仅 `autolava-web` 对宿主机发布 `8080` 端口。API 与数据库均不发布端口。现有宿主机 Nginx、Halo 容器及已停止的 `sag-app` 容器均不作修改。

## 配置与密钥

部署目录为 `/opt/autolava`。目录中的 `.env` 仅 root 可读，保存数据库连接地址、随机生成的 JWT 密钥和初始管理员凭据。管理员凭据也仅保留在服务器 root 可读的文件中，部署输出不会打印任何密钥或密码。

临时版本通过 `http://116.62.112.245:8080` 访问，因此设置 `AUTOLAVA_COOKIE_SECURE=false`。这是明确的过渡性配置：HTTP 无法保护登录密码、Cookie 和经营数据在传输过程中的安全。

## 数据与恢复

MySQL 使用 `autolava_mysql_data` Docker 命名卷持久化数据。数据库只允许 Compose 内部网络访问。部署会创建 `/opt/autolava/backups`，并通过服务器的每日定时任务使用 `docker compose exec` 和 `mysqldump` 导出完整标准 SQL 文件。备份在容器外保存，保留最近 7 天；任何破坏性数据库操作前也先执行一次备份。

## 部署流程

1. 在本机验证项目能够启动，并确认健康检查接口正常响应。
2. 若服务器缺少 Docker Compose 插件，则安装该插件。
3. 通过 SSH 将已提交的发布源代码传输至 `/opt/autolava`，不传输本机密钥文件。
4. 在服务器生成仅服务器可读的密钥并启动 Compose 服务。
5. 创建每日 SQL 备份任务并执行一次备份验证。
6. 检查各容器健康状态、数据库迁移、初始管理员创建情况，并确认 `http://116.62.112.245:8080/health` 返回成功。

## 后续 HTTPS 迁移

域名解析到服务器后，使用现有 Nginx 配置 TLS 反向代理并申请自动续期证书，停止将应用端口直接暴露到公网，并将 `AUTOLAVA_COOKIE_SECURE` 改回 `true`。数据库卷与应用数据无需迁移。

## 错误处理

本机验证、镜像构建、数据库迁移或健康检查任一失败时，部署立即停止。不会重启、删除或修改已有服务；除非用户明确要求，`sag-app` 保持停止状态。
