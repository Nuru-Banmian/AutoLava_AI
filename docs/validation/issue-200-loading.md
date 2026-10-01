# Issue #200: page and map loading evidence

Checked on 2026-10-01 with the same local frontend dependencies and `npm run build` before and after the change. These are build artifact sizes, not measured user download time.

| Artifact | Before | After |
| --- | ---: | ---: |
| Entry JavaScript | 1,206.05 kB (gzip 361.13 kB) | 406.86 kB (gzip 129.44 kB) |
| Entry CSS | 57.97 kB (gzip 14.88 kB) | 42.90 kB (gzip 8.42 kB) |
| Map JavaScript | Included in entry | 149.67 kB (gzip 43.81 kB) |
| Map CSS | Included in entry | 15.09 kB (gzip 6.36 kB) |

The production preview at `127.0.0.1:4174` was opened in Chromium. On `/login`, the browser requested the entry, entry CSS, `LoginPage` and its small input dependency. It did not request the map provider or business page chunks. On direct `/admin` navigation, it requested `AdminPage`, but not the map provider. Clicking **打开地图选择** requested the map JavaScript and CSS, and the map appeared.

Direct navigation to `/ledger`, `/database`, `/settlements`, `/more`, and `/account/password` rendered each page's heading. A regular user entering `/admin` was redirected to `/`. Authentication and selected API responses in these browser checks were simulated. Other API requests failed because no backend was running, so these checks establish resource loading and routing rather than data flow. This is not a live backend or Web image acceptance run. Final image integration remains under #203.

Refreshing the deep link `/admin?tab=users` kept the URL and selected the **用户与权限** tab. A held login page chunk displayed **正在加载页面…**; releasing that exact request rendered the login form, without a timed delay.

Fault injection returned HTTP 503 for the login page chunk. The browser showed **页面资源加载失败** with **重新加载**; after removing the fault and clicking it, the login form returned. Returning HTTP 503 for the map provider showed **地图加载失败** with **重新加载地图**. The reload returned to the admin page after the fault was removed.

Frontend checks: `npm run build` passed; `npm test -- --run` passed with 36 files and 331 tests. No Docker image was built or run.
