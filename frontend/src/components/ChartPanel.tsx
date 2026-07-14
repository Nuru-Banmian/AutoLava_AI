import type { ReactNode } from "react";
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
const colors = ["#2563eb", "#16a34a", "#ca8a04", "#9333ea", "#dc2626", "#0891b2"];
export type ChartKind = "bar" | "pie" | "line";
export function ChartPanel({ title, data, kind, xKey, valueKey, children }: { title: string; data?: Record<string, unknown>[]; kind?: ChartKind; xKey?: string; valueKey?: string; children?: ReactNode }) {
  const rows = data ?? [];
  return <Card><CardHeader><CardTitle>{title}</CardTitle></CardHeader><CardContent>{children ?? (!rows.length ? <p className="flex h-64 items-center justify-center text-muted-foreground">暂无数据</p> : <div className="h-72 min-h-72 w-full"> <ResponsiveContainer width="100%" height="100%">{kind === "pie" ? <PieChart><Pie data={rows} dataKey={valueKey!} nameKey={xKey!} outerRadius={90}>{rows.map((_, index) => <Cell key={index} fill={colors[index % colors.length]} />)}</Pie><Tooltip /></PieChart> : kind === "line" ? <LineChart data={rows}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey={xKey} /><YAxis /><Tooltip /><Line type="monotone" dataKey={valueKey!} stroke="#2563eb" /></LineChart> : <BarChart data={rows}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey={xKey} /><YAxis /><Tooltip /><Bar dataKey={valueKey!} fill="#2563eb" /></BarChart>}</ResponsiveContainer></div>)}</CardContent></Card>;
}
