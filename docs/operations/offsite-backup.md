# 异机备份与隔离恢复

生产环境继续在每天 03:00 按门店维护时区执行 SQLite 在线备份、完整性检查、原子落盘和本地三日保留。复制只读取已完成且再次验证通过的快照。复制失败会记录为独立任务结果，不中断记账。

## 配置

仅在已经确认独立主机或独立存储故障范围、具备传输授权后，通过受保护的部署环境配置 `AUTOLAVA_BACKUP_SSH_HOST`、`AUTOLAVA_BACKUP_SSH_USER`、`AUTOLAVA_BACKUP_SSH_DIRECTORY`、`AUTOLAVA_BACKUP_SSH_KEY_FILE` 和 `AUTOLAVA_BACKUP_SSH_KNOWN_HOSTS_FILE`。远端目录须预先建立并限制访问。SSH 使用批处理模式、固定的 known_hosts 和密钥文件；应用不记录凭证、目标路径或 SSH 错误输出。同主机的另一目录或数据卷不能作为异机验收。未配置时管理员诊断返回 `offsite_copy: not_configured`。

远端先收到带随机后缀的临时文件，计算 SHA-256 与本地快照比较成功后才改名为正式快照。传输失败会尝试清理临时文件；远端也应定期清理遗留的 `.upload-*` 文件，并独立设置保留策略。管理员诊断的 `local_snapshot`、`offsite_copy`、`isolated_restore` 是不同结果；复制成功不代表恢复通过。

## 隔离恢复演练

从获授权的目的地取回一个快照，放入可丢弃的隔离环境。不要指向当前业务库目录。可在该环境运行：

```powershell
cd backend
.\.venv\Scripts\python.exe -c "from pathlib import Path; from app.services.backup_restore import verify_isolated_restore; print(verify_isolated_restore(Path('SNAPSHOT.sqlite3'), Path('EMPTY-DIRECTORY')))"
```

结果包含迁移版本和账号、门店、每日台账、历史分类快照、公司结算的样本行存在情况。缺少任一代表性记录则演练失败。目标目录必须为空，程序只在该目录建立恢复副本，不覆盖在线主库。`restore-result.json` 保存本地隔离演练结果、时间及快照摘要；失败时保存错误类型。维护者可将该报告放在受保护的位置，并通过 `AUTOLAVA_BACKUP_RESTORE_REPORT_FILE` 指向它，管理员诊断会显示 `local_drill_success` 或 `failed`。这不表示真实异机恢复已通过。保留快照来源及失败记录；不得在证据中写入凭证或真实业务数据。

当前自动化验收只覆盖传输替身与本地隔离恢复。真实异机目的地的启用、数据传输及恢复演练尚未执行，需单独配置与明确授权。
