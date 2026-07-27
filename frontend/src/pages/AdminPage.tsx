import { useSearchParams } from "react-router-dom";

import { AdminLayout, type AdminTab, isAdminTab } from "@/admin/AdminLayout";
import { AgentSettingsPanel } from "@/admin/AgentSettingsPanel";
import { DatabaseBackupPanel } from "@/admin/DatabaseBackupPanel";
import { StoreWorkspace } from "@/admin/StoreWorkspace";
import { SystemStatusPanel } from "@/admin/SystemStatusPanel";
import { UsersPanel } from "@/admin/UsersPanel";
import { useAuth } from "@/auth/AuthProvider";
import { useUnsavedChanges } from "@/navigation/UnsavedChanges";

export function AdminPage() {
  const { user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const { requestTransition } = useUnsavedChanges();
  const requestedTab = searchParams.get("tab");
  const tab: AdminTab = isAdminTab(requestedTab) ? requestedTab : "stores";

  function selectTab(next: AdminTab) {
    if (next === tab) return;
    requestTransition(() => {
      const nextParams = new URLSearchParams(searchParams);
      if (next === "stores") nextParams.delete("tab");
      else nextParams.set("tab", next);
      setSearchParams(nextParams, { replace: true });
    });
  }

  return (
    <AdminLayout
      tab={tab}
      onTabChange={selectTab}
      panels={{
        stores: <StoreWorkspace />,
        users: <UsersPanel />,
        status: (
          <>
            <AgentSettingsPanel isOwner={Boolean(user?.is_owner)} />
            <SystemStatusPanel />
            {user?.is_owner && <DatabaseBackupPanel />}
          </>
        ),
      }}
    />
  );
}
