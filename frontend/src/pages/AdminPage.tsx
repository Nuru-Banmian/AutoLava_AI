import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { AdminLayout, isAdminTab, type AdminTab } from "@/admin/AdminLayout";
import { IncomeItemsPanel } from "@/admin/IncomeItemsPanel";
import { StoreSettingsPanel } from "@/admin/StoreSettingsPanel";
import { SystemStatusPanel } from "@/admin/SystemStatusPanel";
import { UsersPanel } from "@/admin/UsersPanel";

export function AdminPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedStoreId, setSelectedStoreId] = useState<number | null>(null);
  const requestedTab = searchParams.get("tab");
  const tab: AdminTab = isAdminTab(requestedTab) ? requestedTab : "income";

  function selectTab(next: AdminTab) {
    const nextParams = new URLSearchParams(searchParams);
    if (next === "income") nextParams.delete("tab"); else nextParams.set("tab", next);
    setSearchParams(nextParams, { replace: true });
  }

  return <AdminLayout tab={tab} onTabChange={selectTab} panels={{
    income: <IncomeItemsPanel selectedStoreId={selectedStoreId} onSelectedStoreChange={setSelectedStoreId} />,
    users: <UsersPanel />,
    stores: <StoreSettingsPanel />,
    status: <SystemStatusPanel />,
  }} />;
}
