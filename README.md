# 门店管理系统

用于记录日常经营、管理公司结算和查看经营表现的 Web 应用，支持多个门店及按门店分配用户权限。

系统目前以洗车门店为实际业务场景，提供通用的记账、收入分类、记录查询和结算功能，也保留洗车数量、记录天气等场景功能。可根据门店配置选择记账方式和启用的业务。

## 功能介绍

### 记账与营业记录

为选定日期创建或修改每日台账，支持历史补记。

- **总额记账**：直接记录当日总营业额。
- **分类记账**：按收入分类分别记录金额，可设置分类是否计入总营业额。
- **营业状态**：区分营业、休息和提前休息。
- **补充信息**：按门店设置记录洗车数量，并可填写记录天气和事件。
- **历史查询**：查看营业记录及记录详情，导出 Excel 工作簿。

### 公司结算

按门店管理结算公司，登记开票记录，跟踪待到账应收款，支持到账确认和撤销到账确认。管理员可为门店开启或关闭公司结算。

已确认金额归属于开票月份，不改变单日台账营业额。尚未到账的开票记录不计入收入。

### 经营分析

通过收入构成、趋势、日历、星期和天气分组查看经营表现。分析随当前门店及查询范围切换；具体指标口径见 [领域文档](CONTEXT.md)。

管理员也可在 AI 对话中按需查询台账、历史分类明细、月度收入和收入构成，一次取得多个分组或同期比较结果。后端计算均值、排名、占比、差额和变化率，并说明范围、分母、覆盖及不可用原因。日/周台账不摊公司结算；月度总收入按开票月份计入整笔已确认金额，关闭公司结算后仍保留历史收入。

### 管理与备份

管理员可管理门店、收入分类、用户及门店访问权限。用户可修改自己的密码。系统自动生成数据库备份，最终管理员可下载完整数据库备份。

## 技术栈

| 部分 | 使用技术 |
| --- | --- |
| 后端 | Python、FastAPI、SQLAlchemy、Alembic |
| 数据库 | SQLite |
| 前端 | React、TypeScript、Vite、Tailwind CSS |
| 测试 | pytest、Vitest、Playwright |
| 部署 | Docker Compose、Nginx、外部 HTTPS 反向代理 |

## 本地运行

### 环境准备

Windows 本地开发需要：

- Python 3.12 或以上版本。
- `uv`。
- Node.js 22 和 npm。

### 启动项目

在仓库根目录打开 PowerShell，执行：

```powershell
.\scripts\start-local.ps1
```

首次运行会安装依赖、生成本地 JWT 密钥，并提示设置管理员账号和密码。随后自动执行 `alembic upgrade head` 完成数据库迁移、初始化管理员，启动后端和前端，打开浏览器。

| 入口 | 地址 |
| --- | --- |
| 网页 | http://127.0.0.1:5173 |
| 后端 | http://127.0.0.1:8000 |
| API 文档 | http://127.0.0.1:8000/docs |
| 健康检查 | http://127.0.0.1:8000/health |

如需手动打开网页：

```powershell
.\scripts\start-local.ps1 -NoBrowser
```

按 `Ctrl+C` 结束运行，脚本会停止前后端子进程。启动前请确保 8000 和 5173 端口空闲。

### 本地配置与数据

- `.env`：保存本地 JWT 密钥及管理员初始化配置，不应提交。
- `.autolava-local/autolava.sqlite3`：本地数据库，重启后继续使用。
- `.autolava-local/`：同时保存依赖状态标记；依赖清单变化时启动脚本会重新安装依赖。

启动脚本不会自动导入其他环境的数据。管理员初始化只创建不存在的账号，不覆盖同名账号的密码或权限。

项目展示名称为“门店管理系统”，现有 `AUTOLAVA_*` 配置项、数据库路径和容器标识继续沿用。

## 项目结构

```text
backend/          后端服务、数据模型、数据库迁移及测试
frontend/         前端页面、组件、API 类型及测试
scripts/          本地启动、发布构建及验收脚本
deploy/           部署配置
docs/             工程约定与验证记录
CONTEXT.md        领域术语与业务口径
compose.yaml      容器编排
.env.example      部署环境变量示例
```

## 开发检查

下面的后端与前端命令分别从仓库根目录的新终端开始执行。

### 后端

安装锁定依赖，并将数据库路径指向临时目录：

```powershell
cd backend
uv sync --locked --extra dev
$env:AUTOLAVA_DATABASE_PATH = Join-Path $env:TEMP "autolava-test.sqlite3"
uv run --frozen ruff check .
uv run --frozen pytest --cov=app --cov-report=term-missing
uv run --frozen python scripts/export_openapi.py --check
```

### 前端

```powershell
cd frontend
npm ci
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

`npm run build` 包含 TypeScript 检查和生产构建。浏览器测试会自动在 4173 端口启动测试 Web 服务；普通套件主要使用模拟接口，独立真实服务用例按相应验收文档运行。

### API 契约

后端 API 变更后，在后端目录导出快照，再在前端目录生成类型：

```powershell
cd backend
uv run --frozen python scripts/export_openapi.py
cd ..\frontend
npm run generate:api-types
```

[常规 CI](.github/workflows/ci.yml) 检查 API 契约、后端质量与覆盖率、前端单元测试、构建及浏览器测试。

## 部署

应用由 `autolava-api` 和 `autolava-web` 两个容器服务组成。API 使用一个 Uvicorn worker，Web 使用 Nginx 提供网页并代理 API，HTTPS 由同机外部反向代理处理。

### 1. 构建镜像

使用干净、已提交的代码，运行 GitHub Actions 的 [Build release images](.github/workflows/release-images.yml)，或在具备 Docker 与 Node.js 22 的 Linux 构建机上执行：

```sh
bash scripts/build-release-images.sh
```

构建过程使用后端锁文件安装生产依赖，生成前端产物后再构建 Web 镜像，并检查 API 健康状态、迁移版本和实际安装的依赖。工作流保存两个镜像及检查材料。

面向 2 核 / 2 GB 的服务器部署时，在 CI 或其他构建机完成构建，将镜像传到服务器后加载：

```sh
docker load -i autolava-api.tar
docker load -i autolava-web.tar
```

### 2. 配置环境

将 `.env.example` 复制为 `.env`，替换所有 `change-me` 值，设置随机 JWT 密钥和管理员初始化凭据。指定实际加载的镜像标签：

```dotenv
AUTOLAVA_API_IMAGE=autolava-api:<commit>
AUTOLAVA_WEB_IMAGE=autolava-web:<commit>
AUTOLAVA_COOKIE_SECURE=true
```

`<commit>` 应替换为构建对应的提交 SHA。生产 HTTPS 环境保持 `AUTOLAVA_COOKIE_SECURE=true`；本地 HTTP 验证才使用 `AUTOLAVA_COOKIE_SECURE=false`。

### 3. 启动与初始化

```sh
docker compose up -d --no-build
docker compose exec autolava-api python -m app.scripts.create_admin
```

API 容器会在启动前执行数据库迁移。管理员初始化不会覆盖已有同名账号。确认登录后，可按部署环境的密钥轮换流程移除管理员初始化密码。

Compose 默认将 Web 绑定到 `127.0.0.1:80`。配置同机 HTTPS 反向代理转发到此地址，并用真实客户端地址覆盖不可信的 `X-Forwarded-For`。Web Nginx 仅信任回环地址及 Compose 网络网关 `172.30.0.1` 的真实 IP 转发。

### 4. 验证发布

手动运行 [发布流程检查](.github/workflows/release-flow.yml)，通过实际 API/Web 镜像、Nginx 和隔离 HTTPS 测试代理验证登录与退出、浏览器记账、重启回读、分析接口、工作簿导出和旧数据库迁移。

保存对应提交、镜像 ID、迁移版本、依赖清单、浏览器 trace 和失败日志。常规 CI 与镜像构建通过不代表已完成发布流程验证；真实天气供应商、生产部署、负载和异机恢复需分别验证。详细范围见 [发布验收说明](docs/validation/issue-203-release-flow.md)。

部署后，可在服务空闲及完成一次正常业务操作后分别记录 `docker stats --no-stream`，用于观察实际资源占用。

## 数据备份与恢复

命名卷 `autolava_data` 保存：

- 数据库：`/data/autolava.sqlite3`。
- 自动备份：`/data/backups`，保留最近三天的有效备份。

应用没有恢复入口。仓库提供运维用的 [备份复制工具](backend/app/services/backup_copy.py) 和 [隔离恢复工具](backend/app/services/backup_restore.py)，用于复制已验证备份及在独立目录检查恢复结果。

需要手动恢复生产数据库时，先停止 API，再用验证过的备份替换主数据库，移除旧的 `autolava.sqlite3-wal` 和 `autolava.sqlite3-shm` 文件，最后启动 API。不能直接替换正在使用的 SQLite 文件。

## 文档与问题跟踪

- [领域文档](CONTEXT.md)：业务术语及指标口径。
- [GitHub Issues](https://github.com/Nuru-Banmian/AutoLava_AI/issues)：问题与需求跟踪。
- [验证记录](docs/validation/)：各项验收的范围、结果与限制。

AI 对话提供受控数据目录、针对性台账/历史收入分类明细查询、分组指标与比较：可复用有效目录，按问题筛选、稳定排序或选择前N项，完整事件不截断；无范围默认本月至今，全部历史不限366天。大结果使用本轮不可变快照分页，默认50行、最多200行；累计容量不足保留成功结果并说明已读/未读和部分完成。图表由后续工单接入。能力与限制见 `backend/app/agents/README.md`。
