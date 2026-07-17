interface RecordPaginationProps {
  page: number;
  total: number;
  pageSize: 15;
  onPageChange(page: number): void;
}

export function RecordPagination({ page, total, pageSize, onPageChange }: RecordPaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const previousDisabled = page <= 1;
  const nextDisabled = page >= totalPages;

  return (
    <nav aria-label="记录分页" className="flex items-center justify-between gap-3">
      <button type="button" disabled={previousDisabled} onClick={() => onPageChange(page - 1)} className="rounded-md border border-border px-3 py-2 disabled:cursor-not-allowed disabled:opacity-50">上一页</button>
      <span aria-live="polite">第 {page} / {totalPages} 页</span>
      <button type="button" disabled={nextDisabled} onClick={() => onPageChange(page + 1)} className="rounded-md border border-border px-3 py-2 disabled:cursor-not-allowed disabled:opacity-50">下一页</button>
    </nav>
  );
}
