# Global Store Selector Layout Design

## Goal

Make the active store easy to see and switch from every authenticated page without duplicating the selector in the mobile More page.

## Approved layout

- Desktop (`md` and above): render the existing global store selector directly below the `AutoLava AI` brand in the fixed left sidebar.
- Mobile (below `md`): render the same selector in the header row, aligned to the far right of `AutoLava AI`; the brand remains left-aligned.
- Remove the selector from the mobile More page.

## Behavior and accessibility

- Keep the existing StoreProvider state, loading behavior, store-load error, and retry behavior unchanged.
- Both responsive presentations operate on the same selected-store state; no independent mobile state is introduced.
- Only one selector is visible at any viewport width.
- The mobile selector remains labelled `门店`, stays keyboard accessible, and truncates long selected store names rather than causing horizontal overflow or pushing the brand off-screen.
- The desktop selector uses the existing accessible label and keeps the sidebar-width presentation.

## Scope

- Primary implementation owner: `frontend/src/layouts/AppShell.tsx`.
- Remove the redundant More-page selector markup and update relevant shell/More tests.
- No API, routing, store-selection data flow, or business-page behavior changes.

## Verification

- Component tests verify desktop placement, mobile header placement, a single visible selector per breakpoint, and no selector in More.
- Add a long-name mobile regression to ensure the header does not overflow.
- Run the related frontend tests during development; run full frontend checks before the next PR update.
