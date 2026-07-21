import { useState } from "react";

import type { CategoryComposition } from "@/api/types";
import { Button } from "@/components/ui/button";
import { formatWholeEuro } from "@/lib/user-api";

const INITIAL_VISIBLE_ROWS = 5;

export function compositionPercentage(amount: number, total: number): string {
  if (total <= 0) return "0.0%";
  return `${(Math.round((amount * 1000) / total) / 10).toFixed(1)}%`;
}

interface IncomeCompositionProps {
  included: CategoryComposition[];
  excluded: CategoryComposition[];
  classifiedIncludedTotal: number;
  totalRevenue: number;
}

interface CompositionGroupProps {
  title: string;
  rows: CategoryComposition[];
  expanded: boolean;
  onExpandedChange: () => void;
  showProportions: boolean;
  total: number;
  toggleLabel: string;
}

function CompositionGroup({ title, rows, expanded, onExpandedChange, showProportions, total, toggleLabel }: CompositionGroupProps) {
  const visibleRows = expanded ? rows : rows.slice(0, INITIAL_VISIBLE_ROWS);
  const hiddenCount = rows.length - INITIAL_VISIBLE_ROWS;

  return <section aria-label={title} className="grid gap-3">
    <div className="flex items-baseline justify-between gap-3">
      <h4 className="font-medium">{title}</h4>
      <span className="text-sm text-muted-foreground">{rows.length} 项</span>
    </div>
    {rows.length === 0 ? <p className="text-sm text-muted-foreground">暂无分类金额</p> : <div className="grid gap-2">
      {visibleRows.map((row) => <div key={row.category_id ?? row.category_name} className="grid gap-1">
        <div className="flex items-center justify-between gap-3 text-sm">
          <span className="min-w-0 break-words">{row.category_name}</span>
          <span className="shrink-0 tabular-nums">{formatWholeEuro(row.amount)}</span>
        </div>
        {showProportions && <div data-testid="composition-proportion" className="h-1.5 overflow-hidden rounded-full bg-muted" aria-label={`${row.category_name} 占比 ${compositionPercentage(row.amount, total)}`}>
          <div className="h-full rounded-full bg-primary" style={{ width: compositionPercentage(row.amount, total) }} />
        </div>}
        {showProportions && <span className="text-xs text-muted-foreground">{compositionPercentage(row.amount, total)}</span>}
      </div>)}
    </div>}
    {hiddenCount > 0 && <Button type="button" variant="ghost" size="sm" className="justify-self-start" onClick={onExpandedChange}>{expanded ? `收起${title}` : `${toggleLabel}（还有 ${hiddenCount} 项）`}</Button>}
  </section>;
}

export function IncomeComposition({ included, excluded, classifiedIncludedTotal, totalRevenue }: IncomeCompositionProps) {
  const [includedExpanded, setIncludedExpanded] = useState(false);
  const [excludedExpanded, setExcludedExpanded] = useState(false);
  const showProportions = included.length >= 2 && classifiedIncludedTotal > 0;

  return <section className="grid gap-4" aria-label="收入构成">
    <CompositionGroup
      title="收入分类"
      rows={included}
      expanded={includedExpanded}
      onExpandedChange={() => setIncludedExpanded((value) => !value)}
      showProportions={showProportions}
      total={classifiedIncludedTotal}
      toggleLabel="展开收入分类"
    />
    <hr className="border-border" />
    <CompositionGroup
      title="未计入总额"
      rows={excluded}
      expanded={excludedExpanded}
      onExpandedChange={() => setExcludedExpanded((value) => !value)}
      showProportions={false}
      total={0}
      toggleLabel="展开未计入总额"
    />
    <p className="text-xs text-muted-foreground">未计入总额的金额不会计入总营业额、增幅或平均值。</p>
    {classifiedIncludedTotal < totalRevenue && <p className="text-xs text-muted-foreground">部分历史总额记录未分配到收入分类，因此分类金额低于总营业额。</p>}
  </section>;
}
