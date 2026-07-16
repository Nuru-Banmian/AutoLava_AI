import type { ReactNode } from "react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatMoney } from "@/lib/user-api";
export const chartSeriesColors = ["var(--primary)", "var(--chart-series-2)", "var(--chart-series-3)"];
export type ChartKind = "bar" | "horizontal-bar" | "line";
export function chartTooltipValue(row: Record<string, unknown>, valueKey: string) { return formatMoney(String(row[`${valueKey}_raw`] ?? row[valueKey] ?? "0")); }
export function ChartPanel({ title, data, kind, xKey, valueKey, children }: { title: string; data?: Record<string, unknown>[]; kind?: ChartKind; xKey?: string; valueKey?: string; children?: ReactNode }) {
  const rows = data ?? [];
  const tooltip = <Tooltip formatter={(_value, _name, item) => chartTooltipValue(item.payload as Record<string, unknown>, valueKey!)} />;
  return <Card><CardHeader><CardTitle>{title}</CardTitle></CardHeader><CardContent>{children ?? (!rows.length ? <p className="flex h-64 items-center justify-center text-muted-foreground">暂无数据</p> : <div className="h-72 min-h-72 w-full"><ResponsiveContainer width="100%" height="100%">{kind === "line" ? <LineChart data={rows}><CartesianGrid stroke="var(--border)" strokeDasharray="3 3" /><XAxis dataKey={xKey} /><YAxis />{tooltip}<Line type="monotone" dataKey={valueKey!} stroke={chartSeriesColors[0]} strokeWidth={3} dot={false} /></LineChart> : kind === "horizontal-bar" ? <BarChart data={rows} layout="vertical"><CartesianGrid stroke="var(--border)" strokeDasharray="3 3" /><XAxis type="number" /><YAxis type="category" dataKey={xKey} width={80} />{tooltip}<Bar dataKey={valueKey!} fill={chartSeriesColors[1]} radius={[0, 6, 6, 0]} /></BarChart> : <BarChart data={rows}><CartesianGrid stroke="var(--border)" strokeDasharray="3 3" /><XAxis dataKey={xKey} /><YAxis />{tooltip}<Bar dataKey={valueKey!} fill={chartSeriesColors[0]} /></BarChart>}</ResponsiveContainer></div>)}</CardContent></Card>;
}
