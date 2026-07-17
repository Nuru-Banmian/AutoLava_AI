# Management Center Selection Follow-ups Design

**Date:** 2026-07-17

## Goal

Remove the empty initial state from the management center when data exists, make mobile selectors consistent with the separate create buttons, and apply the approved card and action ordering changes.

## Store and Income Page

- After the store query first succeeds, automatically select the first store when the list is non-empty.
- Desktop and mobile views use the same real selection state; the default is not a render-only fallback.
- Remove the mobile selector's `请选择门店` option.
- Remove the content area's `请选择门店` prompt.
- Keep the selector visually empty while the create-store editor is active. This empty value is an internal hidden option and must not appear as a selectable item.
- After a store is created successfully, select the created store.
- In edit mode, render the income-items card above the store-details card.
- Preserve the existing create, switch, delete, unsaved-change guard, stale-callback, and dirty-state behavior.
- When no stores exist, do not invent a selection and do not show the removed prompt.

## Users and Permissions Page

- After the user query first succeeds, automatically select the first user when the list is non-empty.
- The mobile selector contains existing users only. Remove the selectable `新建用户` and `请选择用户` entries.
- Place the mobile selector and the separate `新建用户` button on one horizontally aligned row.
- Keep the selector visually empty while the create-user editor is active. This empty value is an internal hidden option and must not appear as a selectable item.
- After a user is created successfully, select the created user.
- In edit mode, swap the bottom actions so `永久删除` is on the left and `保存用户` is on the right.
- In create mode, continue to show only the `添加用户` action; no delete action is present.
- Preserve the existing switching, authorization, save, delete-confirmation, request-lifecycle, and unsaved-change behavior.
- When no users exist, do not invent a selection and do not show the removed prompt.

## Selection Lifecycle

Automatic first-item selection runs only when the relevant list first becomes successfully available and the current selection is still `null`. It must not override:

- an explicit existing-item selection;
- the `new` create state;
- a selection made while a refetch is in flight;
- the post-create selection of the newly created item; or
- existing post-delete selection handling.

Both selectors use a hidden empty option solely to represent create mode or a genuinely empty list. Users cannot choose that empty value from the opened selector.

## Responsive Layout

- Store and user desktop sidebars remain unchanged.
- Mobile selectors remain hidden at the existing desktop breakpoint.
- On mobile, each selector takes the available row width while its create button remains visible at the right.

## Verification

Automated component tests must cover:

- first store and first user selection after successful initial loading;
- no synthetic selection for empty lists;
- absence of the removed selectable options and empty-state prompts;
- blank selector display during store and user create modes;
- selection of the newly created item after a successful create;
- income-items card appearing before store-details card;
- user selector and create button sharing the mobile control row;
- destructive user action on the left and save action on the right;
- unchanged unsaved-change protection and existing create, switch, save, and delete behavior.

The existing frontend test suite and production build must pass before completion. No backend or API changes are required.
