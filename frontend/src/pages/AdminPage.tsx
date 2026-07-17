import { useSearchParams } from "react-router-dom";

import { AdminLayout, isAdminTab, type AdminTab } from "@/admin/AdminLayout";
import { StoreWorkspace } from "@/admin/StoreWorkspace";
import { SystemStatusPanel } from "@/admin/SystemStatusPanel";
import { UsersPanel } from "@/admin/UsersPanel";
import { useUnsavedChanges } from "@/navigation/UnsavedChanges";

export function AdminPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { requestTransition } = useUnsavedChanges();
  const requestedTab = searchParams.get("tab");
  const tab: AdminTab = isAdminTab(requestedTab) ? requestedTab : "stores";

  function selectTab(next: AdminTab) {
    if (next === tab) return;
    requestTransition(() => {
      const nextParams = new URLSearchParams(searchParams);
      if (next === "stores") nextParams.delete("tab"); else nextParams.set("tab", next);
      setSearchParams(nextParams, { replace: true });
    });
  }

  return <AdminLayout tab={tab} onTabChange={selectTab} panels={{
    stores: <StoreWorkspace />,
    users: <UsersPanel />,
    status: <SystemStatusPanel />,
  }} />;
}
