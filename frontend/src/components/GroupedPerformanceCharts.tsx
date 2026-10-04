import type { ChartsResponse } from "@/api/types";
import { recordWeatherValues } from "@/api/weather-values";
import { formatWholeEuro } from "@/lib/user-api";

const weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
const legacyWeather = "历史未规范天气";
const missingWeather = "未记录";

interface PerformanceRow {
  label: string;
  amount: number | null;
  count: number;
  separated?: boolean;
}

function reading(row: PerformanceRow): string {
  return row.count === 0
    ? `${row.label}：无经营日样本，—，0 天`
    : `${row.label}：${formatWholeEuro(row.amount!)}，${row.count} 天经营日样本`;
}

function PerformanceCard({ title, rows }: {
  title: string;
  rows: PerformanceRow[];
}) {
  const maximum = Math.max(0, ...rows.map((row) => row.amount ?? 0));

  return <section aria-label={title} className="flex min-w-0 flex-col rounded-lg border bg-white p-2.5 sm:p-3 lg:row-span-2 lg:grid lg:grid-rows-subgrid">
    <header className="mb-2 grid gap-0.5">
      <h3 className="font-semibold">{title}</h3>
      <p className="text-xs text-muted-foreground">经营日均台账营业额（€） · 样本天数</p>
    </header>
    <div>
    <ul className="grid content-start gap-0.5" aria-label={`${title}分组`}>
      {rows.map((row) => <li key={row.label} aria-label={reading(row)} title={reading(row)} tabIndex={0}
        className={`grid min-h-7 grid-cols-[4.5rem_minmax(0,1fr)_minmax(0,4.5rem)_2.5rem] items-center gap-1.5 rounded-sm px-0.5 py-0.5 focus-visible:outline-2 focus-visible:outline-primary ${row.separated ? "mt-1 border-t border-border pt-1.5" : ""}`}>
          <span className="break-words text-sm">{row.label}</span>
          <span aria-hidden="true" className="h-2 min-w-0 overflow-hidden rounded-full bg-muted">
            <span className="block h-full rounded-full bg-primary" style={{ width: `${maximum > 0 ? (row.amount ?? 0) / maximum * 100 : 0}%` }} />
          </span>
          <strong className="min-w-0 break-all text-right text-sm tabular-nums">{row.amount === null ? "—" : formatWholeEuro(row.amount)}</strong>
          <span className="text-right text-xs tabular-nums text-muted-foreground">{row.count} 天</span>
      </li>)}
    </ul>
    {rows.length === 0 && <p className="text-sm text-muted-foreground">暂无经营日样本</p>}
    </div>
  </section>;
}

export function GroupedPerformanceCharts({ data }: { data: ChartsResponse }) {
  const weekdayRows = weekdays.map((label, weekday) => {
    const group = data.weekday.find((row) => row.weekday === weekday);
    const count = group?.operating_day_count ?? 0;
    return { label, count, amount: count > 0 ? group!.average_revenue : null };
  });
  const groups = data.weather.filter((row) => row.operating_day_count > 0);
  const canonical = recordWeatherValues.flatMap((weather) => groups.filter((row) => row.weather === weather));
  const compatible = groups.filter((row) => !recordWeatherValues.some((weather) => weather === row.weather)
    && row.weather !== legacyWeather && row.weather !== missingWeather);
  const trailing = groups.filter((row) => row.weather === legacyWeather)
    .concat(groups.filter((row) => row.weather === missingWeather));
  const weatherRows = [...canonical, ...compatible, ...trailing].map((row, index) => ({
    label: row.weather, amount: row.average_revenue, count: row.operating_day_count,
    separated: trailing.length > 0 && index === canonical.length + compatible.length && index > 0,
  }));

  return <div className="grid min-w-0 gap-2">
    <div className="grid min-w-0 items-stretch gap-x-3 gap-y-2 lg:grid-cols-2 lg:grid-rows-[auto_1fr] lg:gap-y-0">
      <PerformanceCard title="星期经营表现" rows={weekdayRows} />
      <PerformanceCard title="天气与营业额对比" rows={weatherRows} />
    </div>
  </div>;
}
