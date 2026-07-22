import { useMutation, useQuery } from "@tanstack/react-query";
import { eachDayOfInterval, format, parseISO } from "date-fns";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { api, friendlyApiError } from "@/api/client";
import type { DatabaseResponse, RecordSnapshot } from "@/api/types";
import { useAuth } from "@/auth/AuthProvider";
import { BusinessAnalysisCard } from "@/components/BusinessAnalysisCard";
import { DeleteRecordDialog } from "@/components/DeleteRecordDialog";
import { MobileRecordList } from "@/components/MobileRecordList";
import { MobileRecordSheet } from "@/components/MobileRecordSheet";
import { RecordDetailPanel, type RecordDetail } from "@/components/RecordDetailPanel";
import { RecordFilters } from "@/components/RecordFilters";
import { RecordPagination } from "@/components/RecordPagination";
import { RecordTable, type RecordTableRow } from "@/components/RecordTable";
import type { DateRange, RecordRangeMode } from "@/lib/business-record-ranges";
import { recordRange } from "@/lib/business-record-ranges";
import { downloadBusinessRecords } from "@/lib/business-record-export";
import { databaseKey, storeLocalToday } from "@/lib/user-api";
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
  const restored = useRef(restoredBusinessRecordsState(location.state, selected?.id)).current;
  const hasRestoreEnvelope = Boolean(location.state && typeof location.state === "object" && "restoreBusinessRecords" in location.state);
  const [recordMode, setRecordMode] = useState<RecordRangeMode>(restored?.recordMode ?? "current-month");
  const [range, setRange] = useState<DateRange>(() => restored?.range ?? recordRange("current-month", today));
  const [page, setPage] = useState(restored?.page ?? 1);
  const [selectedDate, setSelectedDate] = useState<string | null>(restored?.selectedDate ?? null);
  const [mobileRecord, setMobileRecord] = useState<RecordDetail | null>(null);
  const [returnFocusTo, setReturnFocusTo] = useState<HTMLButtonElement | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [recordStoreId, setRecordStoreId] = useState<number | null>(selected?.id ?? null);
  const selectedRecordRef = useRef<RecordSnapshot | null>(null);
  const previousScope = useRef({ storeId: selected?.id ?? null, today });
  const pendingMobileRestoreDate = useRef(restored?.mobileRecordDate ?? null);
  const restoreConsumed = useRef(false);
  const scrollRestored = useRef(false);

  useEffect(() => {
    const previous = previousScope.current;
    if (previous.storeId === (selected?.id ?? null) && previous.today === today) return;
    previousScope.current = { storeId: selected?.id ?? null, today };
    if (!selected) {
      setRecordStoreId(null);
      setSelectedDate(null);
      setMobileRecord(null);
      setReturnFocusTo(null);
      setDeleteOpen(false);
      return;
    }
    setRecordStoreId(selected.id);
    setRecordMode("current-month");
    setRange(recordRange("current-month", storeLocalToday(selected)));
    setPage(1);
    setSelectedDate(null);
    setMobileRecord(null);
    setReturnFocusTo(null);
    setDeleteOpen(false);
    pendingMobileRestoreDate.current = null;
  }, [selected?.id, today]);

  useEffect(() => {
    if (!selected || !hasRestoreEnvelope || restoreConsumed.current) return;
    restoreConsumed.current = true;
    navigate(location.pathname, { replace: true, state: null });
  }, [hasRestoreEnvelope, location.pathname, navigate, selected]);

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
    queryFn: () => api<DatabaseResponse>(`/database/${selected!.id}/records?${recordQueryString}`),
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
    const mobileDate = pendingMobileRestoreDate.current;
    if (mobileDate) {
      pendingMobileRestoreDate.current = null;
      setMobileRecord(items.find((item) => item.date === mobileDate) ?? { id: null, date: mobileDate });
    }
  }, [records.data, records.isSuccess, selected?.id]);

  useEffect(() => {
    if (!restored || !records.isSuccess || scrollRestored.current) return;
    scrollRestored.current = true;
    const frame = requestAnimationFrame(() => window.scrollTo({ top: restored.scrollY }));
    return () => cancelAnimationFrame(frame);
  }, [records.isSuccess, restored]);

  const selectedRecordFromResponse = records.data?.items.find((item) => (
    item.date === selectedDate && item.store_id === selected?.id
  )) ?? null;
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
  const visibleRecords = records.data?.items.filter((item) => item.store_id === selected?.id) ?? [];
  const tableRows = useMemo<RecordTableRow[]>(() => {
    const byDate = new Map(visibleRecords.map((record) => [record.date, record]));
    const tableEnd = range.end > today ? today : range.end;
    return eachDayOfInterval({ start: parseISO(range.start), end: parseISO(tableEnd) })
      .map((day) => byDate.get(format(day, "yyyy-MM-dd")) ?? { id: null, date: format(day, "yyyy-MM-dd") })
      .reverse();
  }, [range.end, range.start, today, visibleRecords]);
  const selectedTableRow = tableRows.find((record) => record.date === selectedDate) ?? null;
  const pagedTableRows = tableRows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const exportMutation = useMutation({
    mutationFn: ({ storeId, requestedRange }: { storeId: number; requestedRange: DateRange }) => (
      downloadBusinessRecords(storeId, requestedRange)
    ),
  });
  const exportError = exportMutation.isError
    ? friendlyApiError(exportMutation.error, "导出失败，请重试")
    : "";

  const handleRecordRangeChange = (nextMode: RecordRangeMode, nextRange: DateRange) => {
    setRecordMode(nextMode);
    setRange(nextRange);
    setPage(1);
    setSelectedDate(null);
    setMobileRecord(null);
  };
  const handlePageChange = (nextPage: number) => {
    setPage(nextPage);
    setSelectedDate(null);
    setMobileRecord(null);
  };
  const editRecord = (targetDate: string) => {
    const returnToBusinessRecords: BusinessRecordsViewState = {
      storeId: selected!.id,
      recordMode,
      range,
      page,
      selectedDate,
      mobileRecordDate: mobileRecord?.date ?? null,
      scrollY: window.scrollY,
    };
    navigate(`/ledger?date=${targetDate}`, { state: { returnToBusinessRecords } });
  };

  if (!selected) {
    return <section className="grid w-full gap-4"><h1 className="text-2xl font-semibold">营业记录</h1><p role="status">请先选择门店。</p></section>;
  }

  return (
    <section className="grid w-full gap-4">
      <header><h1 className="text-2xl font-semibold">营业记录</h1></header>
      <RecordFilters
        mode={recordMode}
        range={range}
        today={today}
        exporting={exportMutation.isPending}
        exportError={exportError}
        onChange={handleRecordRangeChange}
        onExport={() => exportMutation.mutate({ storeId: selected.id, requestedRange: range })}
      />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(30rem,32rem)] lg:items-start">
        <div className="min-w-0 overflow-x-hidden">
          <div className="hidden lg:block">
            <RecordTable
              records={pagedTableRows}
              selectedDate={selectedDate}
              loading={records.isLoading}
              error={records.error}
              onSelect={(nextRecord) => setSelectedDate(nextRecord.date)}
              onRetry={() => void records.refetch()}
            />
          </div>
          <div className="lg:hidden">
            <MobileRecordList
              records={pagedTableRows}
              selectedDate={selectedDate}
              onSelect={(nextRecord, trigger) => {
                setSelectedDate(nextRecord.date);
                setMobileRecord(nextRecord);
                setReturnFocusTo(trigger);
              }}
            />
            {records.isSuccess && visibleRecords.length === 0 && (
              <div className="grid gap-2 rounded-md border border-dashed p-4">
                <p>暂无可查看记录</p>
                <Link className="w-fit text-primary underline-offset-4 hover:underline" to={`/ledger?date=${today}`} onClick={(event) => { event.preventDefault(); editRecord(today); }}>补记记录</Link>
              </div>
            )}
          </div>
          <RecordPagination
            page={page}
            total={tableRows.length}
            pageSize={PAGE_SIZE}
            onPageChange={handlePageChange}
          />
        </div>
        <aside className="grid gap-4 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
          <div className="hidden lg:block">
            {selectedTableRow ? (
              <RecordDetailPanel
                record={selectedTableRow}
                canEdit
                canDelete={isAdmin && selectedTableRow.id !== null}
                onEdit={editRecord}
                onDelete={() => {
                  if (selectedTableRow.id === null) return;
                  setDeleteOpen(true);
                }}
              />
            ) : (
              <div className="grid gap-2 rounded-md border border-dashed p-4">
                <p>暂无可查看记录</p>
                {!records.isLoading && !records.error && (
                  <Link className="w-fit text-primary underline-offset-4 hover:underline" to={`/ledger?date=${today}`} onClick={(event) => { event.preventDefault(); editRecord(today); }}>补记记录</Link>
                )}
              </div>
            )}
          </div>
          {recordStateReady && <BusinessAnalysisCard key={selected.id} storeId={selected.id} range={range} />}
        </aside>
      </div>
      {mobileRecord && (mobileRecord.id === null || mobileRecord.store_id === selected.id) && (
        <MobileRecordSheet
          open
          record={mobileRecord}
          canEdit
          canDelete={isAdmin && mobileRecord.id !== null}
          onEdit={editRecord}
          returnFocusTo={returnFocusTo}
          onOpenChange={(open) => {
            if (!open) setMobileRecord(null);
          }}
          onDelete={() => {
            if (mobileRecord.id === null) return;
            setDeleteOpen(true);
          }}
        />
      )}
      <DeleteRecordDialog
        key={selected.id}
        storeId={selected.id}
        record={selectedRecord}
        open={recordStateReady && deleteOpen}
        onOpenChange={setDeleteOpen}
        onCompleted={() => setMobileRecord(null)}
      />
    </section>
  );
}
