"""Employee account editing grants do not grant business or delegation access."""

from fastapi import HTTPException
from sqlalchemy import delete, exists, select, true

from app.models.identity import EmployeeEditor, Store, User
from app.services.access import store_scope_clause
from app.services.owner import is_administrator, is_owner


def can_manage_editors(actor: User, employee: User) -> bool:
    return is_owner(actor) or employee.creator_id == actor.id


def employee_management_clause(actor: User):
    if is_owner(actor):
        return true()
    return (
        (User.manager_id == actor.id)
        | (User.creator_id == actor.id)
        | exists()
        .where(EmployeeEditor.employee_id == User.id, EmployeeEditor.admin_id == actor.id)
        .correlate(User)
    )


async def require_manage_target(session, actor: User, target: User):
    if is_owner(target):
        raise HTTPException(403, "主管理员账号受保护")
    if is_owner(actor):
        return
    if (
        target.role == "admin"
        or await session.scalar(
            select(User.id).where(User.id == target.id, employee_management_clause(actor))
        )
        is None
    ):
        raise HTTPException(403, "无权管理该账号")


async def replace_editors(session, actor: User, employee: User, editor_ids: list[int]):
    if not can_manage_editors(actor, employee):
        raise HTTPException(403, "只有主管理员和员工创建者可以设置编辑授权")
    if is_administrator(employee):
        if editor_ids:
            raise HTTPException(422, "管理员不能设置员工编辑授权")
    else:
        editors = (await session.scalars(select(User).where(User.id.in_(set(editor_ids))))).all()
        if {editor.id for editor in editors} != set(editor_ids) or any(
            not is_administrator(editor) or is_owner(editor) for editor in editors
        ):
            raise HTTPException(422, "编辑授权只能授予从管理员；主管理员始终可管理全部员工")
    await session.execute(delete(EmployeeEditor).where(EmployeeEditor.employee_id == employee.id))
    session.add_all(
        EmployeeEditor(employee_id=employee.id, admin_id=ident) for ident in sorted(set(editor_ids))
    )


async def managed_user_payload(session, actor: User, user: User, store_ids: list[int]) -> dict:
    if not is_owner(actor):
        store_ids = list(
            await session.scalars(
                select(Store.id)
                .where(Store.id.in_(store_ids), await store_scope_clause(session, actor))
                .order_by(Store.id)
            )
        )
    editor_ids = list(
        await session.scalars(
            select(EmployeeEditor.admin_id)
            .where(EmployeeEditor.employee_id == user.id)
            .order_by(EmployeeEditor.admin_id)
        )
    )
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "is_active": user.is_active,
        "manager_id": user.manager_id,
        "creator_id": user.creator_id,
        "editor_ids": editor_ids,
        "can_manage_editors": can_manage_editors(actor, user),
        "store_ids": store_ids,
    }
