import { useState } from "react";

import type { IncomeCompositionItem } from "@/api/types";
import { Button } from "@/components/ui/button";
import { formatWholeEuro } from "@/lib/user-api";

const INITIAL_VISIBLE_ROWS = 5;

export function compositionPercentage(amount: number, total: number): string {
  if (total <= 0) return "0.0%";
  return `${(Math.round((amount * 1000) / total) / 10).toFixed(1)}%`;
}

interface IncomeCompositionProps {
  included: IncomeCompositionItem[];
  excluded: IncomeCompositionItem[];
  totalIncome: number | null;
}

interface CompositionGroupProps {
  title: string;
  rows: IncomeCompositionItem[];
  expanded: boolean;
  onExpandedChange: () => void;
  showProportions: boolean;
  total: number;
  toggleLabel: string;
}

function CompositionGroup({ title, rows, expanded, onExpandedChange, showProportions, total, toggleLabel }: CompositionGroupProps) {
  const categories = rows.filter((row) => row.category_id !== null);
  const specialRows = rows.filter((row) => row.category_id === null);
  const visibleRows = expanded ? rows : [...categories.slice(0, INITIAL_VISIBLE_ROWS), ...specialRows];
  const hiddenCount = categories.length - INITIAL_VISIBLE_ROWS;

  return <section aria-label={title} className="grid gap-3">
    <div className="flex items-baseline justify-between gap-3">
      <h4 className="font-medium">{title}</h4>
      <span className="text-sm text-muted-foreground">{rows.length} 项</span>
    </div>
    {rows.length === 0 ? <p className="text-sm text-muted-foreground">暂无分类金额</p> : <div className="grid gap-2">
      {visibleRows.map((row) => <div key={`${row.category_id}:${row.category_name}`} className="grid gap-1">
        <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 text-sm">
          <span className="min-w-0 break-words">{row.category_name}</span>
          <span className="text-right tabular-nums">{formatWholeEuro(row.amount)}{showProportions && <span className="ml-2 text-xs text-muted-foreground">{compositionPercentage(row.amount, total)}</span>}</span>
        </div>
        {showProportions && <div data-testid="composition-proportion" className="h-1.5 overflow-hidden rounded-full bg-muted" aria-label={`${row.category_name} 占比 ${compositionPercentage(row.amount, total)}`}>
          <div className="h-full rounded-full bg-primary" style={{ width: `${Math.max(0, Math.min(100, row.amount / total * 100))}%` }} />
        </div>}
      </div>)}
    </div>}
    {hiddenCount > 0 && <Button type="button" variant="ghost" size="sm" className="justify-self-start" onClick={onExpandedChange}>{expanded ? `收起${title}` : `${toggleLabel}（还有 ${hiddenCount} 项）`}</Button>}
  </section>;
}

export function IncomeComposition({ included, excluded, totalIncome }: IncomeCompositionProps) {
  const [includedExpanded, setIncludedExpanded] = useState(false);
  const [excludedExpanded, setExcludedExpanded] = useState(false);
  const showProportions = totalIncome !== null && totalIncome > 0;

  return <section className="flex min-w-0 flex-col gap-3 rounded-lg border bg-white p-2.5 sm:p-3 lg:row-span-3 lg:grid lg:grid-rows-subgrid" aria-label="收入构成">
    <header className="grid gap-0.5">
      <h3 className="font-semibold">收入构成</h3>
      <p className="text-xs text-muted-foreground">同范围收入金额（€）与占比</p>
    </header>
    <div className="grid content-start gap-3">
    {totalIncome === 0 && <p className="text-sm text-muted-foreground">暂无收入构成，合计为 €0</p>}
    {totalIncome === null && <p className="text-sm text-muted-foreground">暂无已统计收入构成，合计未知</p>}
    <CompositionGroup
      title="收入分类"
      rows={included}
      expanded={includedExpanded}
      onExpandedChange={() => setIncludedExpanded((value) => !value)}
      showProportions={showProportions}
      total={totalIncome ?? 0}
      toggleLabel="展开收入分类"
    />
    {excluded.length > 0 && <hr className="border-border" />}
    {excluded.length > 0 && <CompositionGroup
      title="其他数据"
      rows={excluded}
      expanded={excludedExpanded}
      onExpandedChange={() => setExcludedExpanded((value) => !value)}
      showProportions={false}
      total={0}
      toggleLabel="展开其他数据"
    />}
    </div>
    <footer className="grid gap-1 border-t pt-2 text-sm">
      <p className="flex flex-wrap justify-between gap-2"><span>收入构成合计</span><strong className="tabular-nums">{formatWholeEuro(totalIncome)}</strong></p>
      <p className="text-xs text-muted-foreground">其他数据不计收入；公司结算归属开票月份。</p>
    </footer>
  </section>;
}
