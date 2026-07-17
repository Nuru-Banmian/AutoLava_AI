# 门店归档实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以可恢复的门店归档替代管理员日常使用的删除操作，并保留仅用于未使用误建门店的永久删除。

**Architecture:** 服务端继续以 `Store.is_active` 表示可用/归档状态，`PATCH /api/admin/stores/{id}` 是归档和恢复的唯一写入接口。前端将门店按状态分组，默认只显示启用门店，使用显式开关展示归档门店，并保留永久删除的关联保护。

**Tech Stack:** FastAPI、SQLAlchemy async、pytest；React、TypeScript、TanStack Query、Vitest、MSW。

## Global Constraints

- 归档与恢复必须复用 `is_active`，不新增数据库字段或迁移。
- 归档不得删除、改写经营记录、审计记录、门店设置或成员关联。
- 归档门店不可写入、不可分配普通用户，现有后端校验必须继续生效。
- 永久删除只允许未被业务、审计或受保护关联引用的门店；冲突提示使用“归档门店”。
- 所有新增和修改的行为必须先有失败测试，再写生产代码。

---

### Task 1: 归档 API 的回归契约

**Files:**
- Modify: `backend/tests/api/test_admin.py`
- Modify: `backend/app/api/routes/admin.py`

**Interfaces:**
- Consumes: `PATCH /api/admin/stores/{store_id}`，请求体 `StorePatch(is_active: bool)`。
- Produces: 归档/恢复均返回更新后的门店 JSON，并写入管理员审计；删除冲突返回 `409` 与“请归档门店”。

- [ ] **Step 1: 写失败测试**：在 `backend/tests/api/test_admin.py` 增加断言：归档 PATCH 返回 `is_active=false` 且审计的 before/after 正确；恢复返回 `is_active=true`；受保护门店 DELETE 返回 `409` 和 `该门店已有业务或历史记录，请归档门店而不是删除`。
- [ ] **Step 2: 运行失败测试**：`pytest tests/api/test_admin.py -k "store and (archive or delete)" -v`；预期因冲突提示仍使用“停用门店”而失败。
- [ ] **Step 3: 最小服务端实现**：在 `backend/app/api/routes/admin.py` 的 `_initial_store_create_audit_for_delete` 和 `delete_store` 中，将冲突详情统一改为 `该门店已有业务或历史记录，请归档门店而不是删除`。不修改 `patch_store`，它已对 `is_active` 的变更写入审计。
- [ ] **Step 4: 验证服务端测试通过**：再次运行上述 pytest 命令；预期通过。

### Task 2: 门店设置的归档与恢复界面

**Files:**
- Modify: `frontend/src/admin/StoreSettingsPanel.test.tsx`
- Modify: `frontend/src/admin/StoreSettingsPanel.tsx`

**Interfaces:**
- Consumes: `AdminStore.is_active` 和 PATCH `{ is_active: boolean }`。
- Produces: 默认隐藏归档门店；“显示已归档门店”显示并可选择它；“归档 / 恢复归档”调用 PATCH；永久删除仍调用 DELETE。

- [ ] **Step 1: 写失败测试**：在 `StoreSettingsPanel.test.tsx` 创建一个启用门店和一个 `is_active=false` 门店，断言初始下拉框隐藏归档门店；点击 `显示已归档门店` 后出现它；点击 `恢复归档门店 Closed` 向 PATCH 发送 `{ "is_active": true }`。将原有停用断言改为 `归档门店 Roma` 和 PATCH `{ "is_active": false }`。
- [ ] **Step 2: 运行失败测试**：`npm test -- StoreSettingsPanel.test.tsx`；预期因缺少开关、归档文案和归档按钮失败。
- [ ] **Step 3: 最小前端实现**：在面板中增加 `showArchived` 状态；使用 `stores.data?.filter((store) => store.is_active || showArchived)` 驱动选择器和选中门店回退；在选择器旁添加显示/隐藏归档门店开关；将当前停用/启用动作改为归档/恢复归档及相同 PATCH；永久删除保持二次确认，说明和 409 反馈改为“归档门店”。
- [ ] **Step 4: 验证前端测试通过**：`npm test -- StoreSettingsPanel.test.tsx`；预期通过。

### Task 3: 全量验证与可交付检查

**Files:**
- Verify: `backend/tests/api/test_admin.py`
- Verify: `frontend/src/admin/StoreSettingsPanel.test.tsx`
- Verify: `frontend`

- [ ] **Step 1: 运行后端相关测试**：`pytest tests/api/test_admin.py -v`；预期通过。
- [ ] **Step 2: 运行前端测试和构建**：`npm test -- StoreSettingsPanel.test.tsx && npm run build`；预期测试与 TypeScript/Vite 构建通过。
- [ ] **Step 3: 检查最终差异**：`git diff --check && git status --short`；预期无空白错误，只有本功能的源代码、测试和计划文件变更。
- [ ] **Step 4: 提交实现**：`git add backend/app/api/routes/admin.py backend/tests/api/test_admin.py frontend/src/admin/StoreSettingsPanel.tsx frontend/src/admin/StoreSettingsPanel.test.tsx docs/superpowers/plans/2026-07-18-store-archiving.md && git commit -m "feat: archive stores from admin settings"`。
