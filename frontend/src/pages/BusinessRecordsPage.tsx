import { useMutation, useQuery } from "@tanstack/react-query";
import { eachDayOfInterval, format, parseISO } from "date-fns";
import { ChartNoAxesCombined, List } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { friendlyApiError } from "@/api/client";
import type { RecordSnapshot } from "@/api/types";
import { useAuth } from "@/auth/AuthProvider";
import { BusinessAnalysisCard } from "@/components/BusinessAnalysisCard";
import { DeleteRecordDialog } from "@/components/DeleteRecordDialog";
import { MobileRecordList } from "@/components/MobileRecordList";
import { RecordDetailPanel, type RecordDetail } from "@/components/RecordDetailPanel";
import { RecordFilters } from "@/components/RecordFilters";
import { RecordPagination } from "@/components/RecordPagination";
import { RecordTable, type RecordTableRow } from "@/components/RecordTable";
import { Button } from "@/components/ui/button";
import type { DateRange, RecordRangeMode } from "@/lib/business-record-ranges";
import { monthRange } from "@/lib/business-record-ranges";
import { downloadBusinessRecords } from "@/lib/business-record-export";
import { databaseKey, loadBusinessRecords, storeLocalToday } from "@/lib/user-api";
import { useStore } from "@/stores/StoreProvider";
import { restoredBusinessRecordsState, type BusinessRecordsViewState } from "@/navigation/business-records-return";

const PAGE_SIZE = 15 as const;
const FETCH_SIZE = 200 as const;

export function BusinessRecordsPage() {
  const { selected } = useStore();
  const { user } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const today = selected ? storeLocalToday(selected) : "1970-01-01";
  const isAdmin = user?.role === "admin";
  const canWrite = selected?.is_active !== false;
  const restored = useRef(restoredBusinessRecordsState(location.state, selected?.id)).current;
  const hasNavigationEnvelope = Boolean(
    location.state
    && typeof location.state === "object"
    && "restoreBusinessRecords" in location.state
  );
  const [recordMode, setRecordMode] = useState<RecordRangeMode>(restored?.recordMode ?? "month");
  const [range, setRange] = useState<DateRange>(() => restored?.range ?? monthRange(today.slice(0, 7)));
  const [page, setPage] = useState(restored?.page ?? 1);
  const [view, setView] = useState<"records" | "analysis">("records");
  const [selectedDate, setSelectedDate] = useState<string | null>(restored?.selectedDate ?? null);
  const [mobileRecord, setMobileRecord] = useState<RecordDetail | null>(null);
  const [returnDeleteFocusTo, setReturnDeleteFocusTo] = useState<HTMLButtonElement | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteFocusDate, setDeleteFocusDate] = useState<string | null>(null);
  const [recordStoreId, setRecordStoreId] = useState<number | null>(selected?.id ?? null);
  const selectedRecordRef = useRef<RecordSnapshot | null>(null);
  const previousScope = useRef({ storeId: selected?.id ?? null, today });
  const pendingMobileRestoreDate = useRef(restored?.mobileRecordDate ?? null);
  const restoreConsumed = useRef(false);
  const scrollRestored = useRef(false);
  const listContainer = useRef<HTMLDivElement>(null);
  const detailContainer = useRef<HTMLDivElement>(null);
  const listPosition = useRef({ scrollY: restored?.scrollY ?? 0, scrollTop: 0 });
  const viewPositions = useRef({ records: restored?.scrollY ?? 0, analysis: 0 });
  const openedFromList = useRef(false);
  const focusAfterReturn = useRef<string | null>(null);
  const linkedDate = new URLSearchParams(location.search).get("date");
  const currentWorkspace = useRef({ storeId: selected?.id, range, selectedDate });
  currentWorkspace.current = { storeId: selected?.id, range, selectedDate };

  useEffect(() => {
    const previous = previousScope.current;
    if (previous.storeId === (selected?.id ?? null) && previous.today === today) return;
    previousScope.current = { storeId: selected?.id ?? null, today };
    scrollRestored.current = true;
    if (!selected) {
      setRecordStoreId(null);
      setSelectedDate(null);
      setMobileRecord(null);
      setReturnDeleteFocusTo(null);
      setDeleteOpen(false);
      setDeleteFocusDate(null);
      return;
    }
    setRecordStoreId(selected.id);
    setRecordMode("month");
    setRange(monthRange(storeLocalToday(selected).slice(0, 7)));
    setPage(1);
    setSelectedDate(null);
    setMobileRecord(null);
    setReturnDeleteFocusTo(null);
    setDeleteOpen(false);
    setDeleteFocusDate(null);
    pendingMobileRestoreDate.current = null;
    openedFromList.current = false;
    focusAfterReturn.current = null;
    if (linkedDate) navigate(location.pathname, { replace: true, state: null });
  }, [selected?.id, today]);

  useEffect(() => {
    if (!selected || !hasNavigationEnvelope || restoreConsumed.current) return;
    restoreConsumed.current = true;
    navigate({ pathname: location.pathname, search: location.search }, { replace: true, state: null });
  }, [hasNavigationEnvelope, location.pathname, navigate, selected]);

  const recordQueryString = useMemo(() => new URLSearchParams({
    start: range.start,
    end: range.end,
    page: "1",
    page_size: String(FETCH_SIZE),
  }).toString(), [range.end, range.start]);
  const recordStateReady = selected !== null && recordStoreId === selected.id;
  const records = useQuery({
    queryKey: recordStateReady ? databaseKey(selected.id, recordQueryString) : ["database", "records", "pending", selected?.id ?? null],
    enabled: recordStateReady,
    queryFn: ({ signal }) => loadBusinessRecords(
      selected!.id,
      range.start,
      range.end,
      signal,
    ),
  });

  useEffect(() => {
    if (!records.isSuccess) return;
    const items = records.data.items.filter((item) => item.store_id === selected?.id);
    setSelectedDate((current) => current ?? items[0]?.date ?? null);
    setMobileRecord((current) => {
      if (!current) return null;
      if (current.id === null) return current;
      return items.find((item) => item.id === current.id) ?? null;
    });
  }, [records.data, records.isSuccess, selected?.id]);

  useEffect(() => {
    if (!restored || !records.isSuccess || records.isFetching || scrollRestored.current) return;
    if (range.start !== restored.range.start || range.end !== restored.range.end || page !== restored.page) return;
    const frame = requestAnimationFrame(() => {
      const restoringMobileDetail = mobileRecord && !window.matchMedia?.("(min-width: 1024px)").matches;
      window.scrollTo({ top: restoringMobileDetail ? 0 : restored.scrollY });
      scrollRestored.current = true;
    });
    return () => cancelAnimationFrame(frame);
  }, [records.isSuccess, records.isFetching, restored, range.start, range.end, page, mobileRecord?.date]);

  const selectedRecordFromResponse = recordStateReady ? records.data?.items.find((item) => (
    item.date === selectedDate && item.store_id === selected?.id
  )) ?? null : null;
  if (!selectedRecordFromResponse) {
    selectedRecordRef.current = null;
  } else if (
    selectedRecordRef.current?.id === selectedRecordFromResponse.id
    && selectedRecordRef.current.store_id === selectedRecordFromResponse.store_id
  ) {
    Object.assign(selectedRecordRef.current, selectedRecordFromResponse);
  } else {
    selectedRecordRef.current = selectedRecordFromResponse;
  }
  const selectedRecord = selectedRecordRef.current;
  const hasWindowData = recordStateReady && records.data !== undefined;
  const visibleRecords = hasWindowData ? records.data.items.filter((item) => item.store_id === selected?.id) : [];
  const tableRows = useMemo<RecordTableRow[]>(() => {
    if (!hasWindowData) return [];
    const byDate = new Map(visibleRecords.map((record) => [record.date, record]));
    const tableEnd = range.end > today ? today : range.end;
    if (tableEnd < range.start) return [];
    return eachDayOfInterval({ start: parseISO(range.start), end: parseISO(tableEnd) })
      .map((day) => byDate.get(format(day, "yyyy-MM-dd")) ?? { id: null, date: format(day, "yyyy-MM-dd") })
      .reverse();
  }, [hasWindowData, range.end, range.start, today, visibleRecords]);
  const selectedTableRow = tableRows.find((record) => record.date === selectedDate) ?? null;
  const pagedTableRows = tableRows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const restoreListFocus = (date: string) => {
    const desktop = window.matchMedia?.("(min-width: 1024px)").matches;
    listContainer.current?.querySelector<HTMLElement>(`${desktop ? "tr" : "button"}[data-record-date='${date}']`)?.focus({ preventScroll: true });
    if (listContainer.current) listContainer.current.scrollTop = listPosition.current.scrollTop;
    window.scrollTo({ top: listPosition.current.scrollY });
  };
  // The date URL also supports calendar links, once the current window has loaded successfully.
  useEffect(() => {
    if (!hasWindowData) return;
    const requestedDate = linkedDate ?? pendingMobileRestoreDate.current;
    if (!requestedDate) {
      if (mobileRecord) {
        focusAfterReturn.current = mobileRecord.date;
        setMobileRecord(null);
      }
      return;
    }
    const index = tableRows.findIndex((row) => row.date === requestedDate);
    if (index < 0) return;
    pendingMobileRestoreDate.current = null;
    if (mobileRecord?.date !== requestedDate) setView("records");
    setPage(Math.floor(index / PAGE_SIZE) + 1);
    setSelectedDate(requestedDate);
    setMobileRecord(tableRows[index]);
    if (!linkedDate) navigate({ pathname: location.pathname, search: `?date=${requestedDate}` }, { replace: true });
  }, [hasWindowData, linkedDate, location.pathname, navigate, records.data, range.start, range.end]);

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      if (mobileRecord) {
        if (window.matchMedia?.("(min-width: 1024px)").matches) return;
        window.scrollTo({ top: 0 });
        detailContainer.current?.querySelector<HTMLElement>("[tabindex='-1']")?.focus({ preventScroll: true });
      } else if (focusAfterReturn.current) {
        const date = focusAfterReturn.current;
        focusAfterReturn.current = null;
        restoreListFocus(date);
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [mobileRecord?.date]);
  useEffect(() => {
    if (!deleteFocusDate || records.isFetching || !recordStateReady) return;
    // Wait for the refreshed missing-date row to be committed before focusing it.
    if (tableRows.find((row) => row.date === deleteFocusDate)?.id !== null) return;
    const frame = requestAnimationFrame(() => {
      restoreListFocus(deleteFocusDate);
      setDeleteFocusDate(null);
    });
    return () => cancelAnimationFrame(frame);
  }, [deleteFocusDate, records.data, records.isFetching, recordStateReady]);
  useEffect(() => {
    if (restored && !scrollRestored.current) return;
    if (mobileRecord && !window.matchMedia?.("(min-width: 1024px)").matches) return;
    const frame = requestAnimationFrame(() => window.scrollTo({ top: viewPositions.current[view] }));
    return () => cancelAnimationFrame(frame);
  }, [view]);
  const exportMutation = useMutation({
    mutationFn: ({ storeId, requestedRange }: {
      storeId: number;
      requestedRange: DateRange;
    }) => downloadBusinessRecords(storeId, requestedRange),
  });
  const exportError = exportMutation.isError
    ? friendlyApiError(exportMutation.error, "导出失败，请重试")
    : "";

  const handleRecordRangeChange = (nextMode: RecordRangeMode, nextRange: DateRange) => {
    scrollRestored.current = true;
    if (linkedDate) navigate(location.pathname, { replace: true, state: null });
    pendingMobileRestoreDate.current = null;
    openedFromList.current = false;
    setRecordMode(nextMode);
    setRange(nextRange);
    setPage(1);
    setSelectedDate(null);
    setMobileRecord(null);
  };
  const handlePageChange = (nextPage: number) => {
    scrollRestored.current = true;
    if (linkedDate) navigate(location.pathname, { replace: true, state: null });
    pendingMobileRestoreDate.current = null;
    openedFromList.current = false;
    setPage(nextPage);
    setSelectedDate(null);
    setMobileRecord(null);
  };
  const openDate = (nextRecord: RecordTableRow) => {
    listPosition.current = { scrollY: window.scrollY, scrollTop: listContainer.current?.scrollTop ?? 0 };
    setSelectedDate(nextRecord.date);
    openedFromList.current = true;
    navigate({ pathname: location.pathname, search: `?date=${nextRecord.date}` });
  };
  const returnToRecords = () => {
    if (openedFromList.current) {
      openedFromList.current = false;
      navigate(-1);
    } else navigate(location.pathname, { replace: true });
  };
  const switchView = (nextView: "records" | "analysis") => {
    viewPositions.current[view] = window.scrollY;
    setView(nextView);
  };
  const editRecord = (targetDate: string) => {
    const editingMobileDetail = mobileRecord && !window.matchMedia?.("(min-width: 1024px)").matches;
    const returnToBusinessRecords: BusinessRecordsViewState = {
      storeId: selected!.id,
      recordMode,
      range,
      page,
      selectedDate,
      mobileRecordDate: mobileRecord?.date ?? null,
      scrollY: editingMobileDetail ? listPosition.current.scrollY : window.scrollY,
    };
    navigate(`/ledger?date=${targetDate}`, { state: { returnToBusinessRecords } });
  };

  if (!selected) {
    return <section className="grid w-full gap-4"><h1 className="text-2xl font-semibold">营业记录</h1><p role="status">请先选择门店。</p></section>;
  }

  return (
    <section className="grid w-full min-w-0 content-start gap-4">
      <header><h1 className="text-2xl font-semibold">营业记录</h1></header>
      <div className={mobileRecord && view === "records" ? "hidden gap-3 lg:grid" : "grid gap-3"}>
        <div role="group" aria-label="营业记录视图" className="grid w-full max-w-md grid-cols-2 gap-1 rounded-xl border border-border bg-white p-1">
          <Button type="button" className="h-11 gap-2" variant={view === "records" ? "default" : "outline"} aria-pressed={view === "records"} onClick={() => switchView("records")}><List aria-hidden="true" className="size-4" />记录</Button>
          <Button type="button" className="h-11 gap-2" variant={view === "analysis" ? "default" : "outline"} aria-pressed={view === "analysis"} onClick={() => switchView("analysis")}><ChartNoAxesCombined aria-hidden="true" className="size-4" />经营分析</Button>
        </div>
        <RecordFilters
          mode={recordMode}
          range={range}
          today={today}
          exporting={exportMutation.isPending}
          exportError={exportError}
          onChange={handleRecordRangeChange}
          onExport={() => exportMutation.mutate({
            storeId: selected.id,
            requestedRange: range,
          })}
        />
      </div>
      <div hidden={view !== "records" || !(records.isError || !hasWindowData || records.isFetching)} className="grid gap-2">
        {view === "records" && records.isError && (
          <div role="alert" className="grid gap-2 rounded-md border border-destructive p-4">
            <p>{hasWindowData ? "刷新记录失败，当前显示上次取得的数据。" : "加载记录失败，请重试。"}</p>
            <button type="button" onClick={() => void records.refetch()} className="w-fit rounded-md border border-border px-3 py-2">重试</button>
          </div>
        )}
        {view === "records" && !hasWindowData && !records.isError && (
          <div role="status" className="animate-pulse rounded-md bg-muted p-4">正在加载记录…</div>
        )}
        {view === "records" && hasWindowData && records.isFetching && !records.isError && (
          <div role="status" className="rounded-md border border-border p-3">正在刷新记录…</div>
        )}
      </div>
      <div hidden={view !== "records"} className={mobileRecord ? "hidden lg:block" : ""}>
      <div className="grid gap-4 lg:min-h-0 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div ref={listContainer} className={mobileRecord ? "hidden min-w-0 overflow-x-hidden lg:flex lg:min-h-0 lg:flex-col" : "min-w-0 overflow-x-hidden lg:flex lg:min-h-0 lg:flex-col"}>
          {hasWindowData && <div className="hidden lg:min-h-0 lg:flex-1 lg:overflow-y-auto lg:block">
            <RecordTable
              records={pagedTableRows}
              selectedDate={selectedDate}
              loading={false}
              error={null}
              onSelect={(nextRecord) => {
                listPosition.current = { scrollY: window.scrollY, scrollTop: listContainer.current?.scrollTop ?? 0 };
                setSelectedDate(nextRecord.date);
                if (linkedDate) navigate({ pathname: location.pathname, search: `?date=${nextRecord.date}` }, { replace: true });
              }}
              onRetry={() => void records.refetch()}
            />
          </div>}
          <div className="lg:hidden">
            <MobileRecordList
              records={pagedTableRows}
              selectedDate={selectedDate}
              onSelect={openDate}
            />
            {hasWindowData && visibleRecords.length === 0 && (
              <div className="grid gap-2 rounded-md border border-dashed p-4">
                <p>暂无可查看记录</p>
                {canWrite && <Link className="w-fit text-primary underline-offset-4 hover:underline" to={`/ledger?date=${today}`} onClick={(event) => { event.preventDefault(); editRecord(today); }}>补记记录</Link>}
              </div>
            )}
          </div>
          {hasWindowData && <RecordPagination
            page={page}
            total={tableRows.length}
            pageSize={PAGE_SIZE}
            onPageChange={handlePageChange}
          />}
        </div>
        <aside className="grid gap-4 lg:min-h-0 lg:overflow-y-auto">
          {hasWindowData && <div className="hidden lg:block">
            {selectedTableRow ? (
              <RecordDetailPanel
                record={selectedTableRow}
                canEdit={canWrite}
                canDelete={canWrite && isAdmin && selectedTableRow.id !== null}
                washCountEnabled={selected.wash_count_enabled ?? true}
                timeZone={selected.timezone}
                onEdit={editRecord}
                onDelete={(trigger) => {
                  if (selectedTableRow.id === null) return;
                  setReturnDeleteFocusTo(trigger);
                  setDeleteOpen(true);
                }}
              />
            ) : (
              <div className="grid gap-2 rounded-md border border-dashed p-4">
                <p>暂无可查看记录</p>
                {hasWindowData && canWrite && (
                  <Link className="w-fit text-primary underline-offset-4 hover:underline" to={`/ledger?date=${today}`} onClick={(event) => { event.preventDefault(); editRecord(today); }}>补记记录</Link>
                )}
              </div>
            )}
          </div>}
        </aside>
      </div>
      </div>
      <div hidden={view !== "analysis"} className="min-w-0">
        {recordStateReady && <BusinessAnalysisCard key={selected.id} storeId={selected.id} range={range} />}
      </div>
      {view === "records" && hasWindowData && mobileRecord && (mobileRecord.id === null || mobileRecord.store_id === selected.id) && (
        <div ref={detailContainer} role="region" aria-label={`${mobileRecord.date} 营业记录详情`} className="lg:hidden">
        <RecordDetailPanel
          mobile
          record={mobileRecord}
          canEdit={canWrite}
          canDelete={canWrite && isAdmin && mobileRecord.id !== null}
          washCountEnabled={selected.wash_count_enabled ?? true}
          timeZone={selected.timezone}
          onEdit={editRecord}
          onBack={returnToRecords}
          onDelete={(trigger) => {
            if (mobileRecord.id === null) return;
            setReturnDeleteFocusTo(trigger);
            setDeleteOpen(true);
          }}
        />
        </div>
      )}
      <DeleteRecordDialog
        key={selected.id}
        storeId={selected.id}
        record={selectedRecord}
        open={recordStateReady && deleteOpen}
        returnFocusTo={returnDeleteFocusTo}
        onOpenChange={setDeleteOpen}
        onCompleted={() => {
          const current = currentWorkspace.current;
          if (current.storeId !== selected.id || current.selectedDate !== selectedDate
            || current.range.start !== range.start || current.range.end !== range.end) return;
          if (mobileRecord) returnToRecords();
          else if (selectedDate) setDeleteFocusDate(selectedDate);
        }}
      />
    </section>
  );
}
