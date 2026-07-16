import type { ReactNode } from "react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export type AdminTab = "income" | "users" | "stores" | "status";

export const orderedAdminTabs: { value: AdminTab; label: string }[] = [
  { value: "income", label: "收入项目" },
  { value: "users", label: "用户与权限" },
  { value: "stores", label: "门店设置" },
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
    <section className="space-y-4">
      <div><h1 className="text-2xl font-semibold">系统管理</h1><p className="text-sm text-muted-foreground">配置用户、门店与业务基础数据。</p></div>
      <Tabs value={tab} onValueChange={(value) => onTabChange(value as AdminTab)}>
        <TabsList className="h-auto w-full flex-wrap justify-start">
          {orderedAdminTabs.map((item) => <TabsTrigger key={item.value} value={item.value}>{item.label}</TabsTrigger>)}
        </TabsList>
        {orderedAdminTabs.map((item) => <TabsContent className="space-y-4" key={item.value} value={item.value}>{panels[item.value]}</TabsContent>)}
      </Tabs>
    </section>
  );
}
