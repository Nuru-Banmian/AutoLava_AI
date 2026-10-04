import type { ReactNode } from "react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export type AdminTab = "stores" | "users" | "status";

export const orderedAdminTabs: { value: AdminTab; label: string }[] = [
  { value: "stores", label: "门店与收入" },
  { value: "users", label: "用户与权限" },
  { value: "status", label: "系统状态" },
];

export function isAdminTab(value: string | null): value is AdminTab {
  return orderedAdminTabs.some((tab) => tab.value === value);
}

export function AdminLayout({ tab, onTabChange, panels }: {
  tab: AdminTab;
  onTabChange: (tab: AdminTab) => void;
  panels: Record<AdminTab, ReactNode>;
}) {
  return (
    <section className="min-w-0 space-y-6">
      <div className="space-y-2"><h1 className="text-2xl font-semibold tracking-tight">系统管理</h1><p className="text-sm leading-6 text-muted-foreground">配置用户、门店与业务基础数据。</p></div>
      <Tabs value={tab} onValueChange={(value) => onTabChange(value as AdminTab)}>
        <TabsList className="h-auto w-full flex-wrap justify-start gap-1 rounded-xl border border-border bg-card p-1.5 shadow-sm">
          {orderedAdminTabs.map((item) => <TabsTrigger className="min-h-11 min-w-0 flex-1 whitespace-normal px-3 sm:flex-none" key={item.value} value={item.value}>{item.label}</TabsTrigger>)}
        </TabsList>
        {orderedAdminTabs.map((item) => <TabsContent className="mt-4 min-w-0 space-y-4" key={item.value} value={item.value}>{panels[item.value]}</TabsContent>)}
      </Tabs>
    </section>
  );
}
