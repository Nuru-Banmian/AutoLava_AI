import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, friendlyApiError } from "@/api/client";
import type { DatabaseResponse, RecordSnapshot } from "@/api/types";
import { useAuth } from "@/auth/AuthProvider";
import { BusinessAnalysisCard } from "@/components/BusinessAnalysisCard";
import { MobileRecordList } from "@/components/MobileRecordList";
import { MobileRecordSheet } from "@/components/MobileRecordSheet";
import { RecordDetailPanel } from "@/components/RecordDetailPanel";
import { RecordFilters } from "@/components/RecordFilters";
import { RecordManagementDialogs } from "@/components/RecordManagementDialogs";
import { RecordPagination } from "@/components/RecordPagination";
import { RecordTable } from "@/components/RecordTable";
import type { DateRange, RecordRangeMode } from "@/lib/business-record-ranges";
import { recordRange } from "@/lib/business-record-ranges";
import { downloadBusinessRecords } from "@/lib/business-record-export";
import { databaseKey, storeLocalToday } from "@/lib/user-api";
import { useStore } from "@/stores/StoreProvider";

const PAGE_SIZE = 15 as const;

export function BusinessRecordsPage() {
  const { selected } = useStore();
  const { user } = useAuth();
  const today = selected ? storeLocalToday(selected) : "1970-01-01";
  const isAdmin = user?.role === "admin";
  const [recordMode, setRecordMode] = useState<RecordRangeMode>("current-month");
  const [range, setRange] = useState<DateRange>(() => recordRange("current-month", today));
  const [page, setPage] = useState(1);
  const [selectedRecordId, setSelectedRecordId] = useState<number | null>(null);
  const [mobileRecord, setMobileRecord] = useState<RecordSnapshot | null>(null);
  const [returnFocusTo, setReturnFocusTo] = useState<HTMLButtonElement | null>(null);
  const [managementOpen, setManagementOpen] = useState(false);
  const [managementDate, setManagementDate] = useState<string | null>(null);
  const [recordStoreId, setRecordStoreId] = useState<number | null>(selected?.id ?? null);
  const selectedRecordRef = useRef<RecordSnapshot | null>(null);

  useEffect(() => {
    if (!selected) {
      setRecordStoreId(null);
      setSelectedRecordId(null);
      setMobileRecord(null);
      setReturnFocusTo(null);
      setManagementOpen(false);
      setManagementDate(null);
      return;
    }
    setRecordStoreId(selected.id);
    setRecordMode("current-month");
    setRange(recordRange("current-month", storeLocalToday(selected)));
    setPage(1);
    setSelectedRecordId(null);
    setMobileRecord(null);
    setReturnFocusTo(null);
    setManagementOpen(false);
    setManagementDate(null);
  }, [selected?.id, today]);

  const recordQueryString = useMemo(() => new URLSearchParams({
    start: range.start,
    end: range.end,
    page: String(page),
    page_size: String(PAGE_SIZE),
  }).toString(), [page, range.end, range.start]);
  const recordStateReady = selected !== null && recordStoreId === selected.id;
  const records = useQuery({
    queryKey: recordStateReady ? databaseKey(selected.id, recordQueryString) : ["database", "records", "pending", selected?.id ?? null],
    enabled: recordStateReady,
    queryFn: () => api<DatabaseResponse>(`/database/${selected!.id}/records?${recordQueryString}`),
  });

  useEffect(() => {
    if (!records.isSuccess) return;
    const items = records.data.items.filter((item) => item.store_id === selected?.id);
    setSelectedRecordId((current) => items.some((item) => item.id === current) ? current : (items[0]?.id ?? null));
    setMobileRecord((current) => {
      if (!current) return null;
      return items.find((item) => item.id === current.id) ?? null;
    });
  }, [records.data, records.isSuccess, selected?.id]);

  const selectedRecordFromResponse = records.data?.items.find((item) => (
    item.id === selectedRecordId && item.store_id === selected?.id
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
    setSelectedRecordId(null);
    setMobileRecord(null);
  };
  const handlePageChange = (nextPage: number) => {
    setPage(nextPage);
    setSelectedRecordId(null);
    setMobileRecord(null);
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
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(22rem,24rem)] lg:items-start">
        <div className="min-w-0 overflow-x-hidden">
          <div className="hidden lg:block">
            <RecordTable
              records={visibleRecords}
              selectedId={selectedRecordId}
              loading={records.isLoading}
              error={records.error}
              onSelect={(nextRecord) => setSelectedRecordId(nextRecord.id)}
              onRetry={() => void records.refetch()}
            />
          </div>
          <div className="lg:hidden">
            <MobileRecordList
              records={visibleRecords}
              selectedId={selectedRecordId}
              onSelect={(nextRecord, trigger) => {
                setSelectedRecordId(nextRecord.id);
                setMobileRecord(nextRecord);
                setReturnFocusTo(trigger);
              }}
            />
            {records.isSuccess && visibleRecords.length === 0 && (
              <div className="grid gap-2 rounded-md border border-dashed p-4">
                <p>暂无可查看记录</p>
                <Link className="w-fit text-primary underline-offset-4 hover:underline" to={`/ledger?date=${today}`}>补记记录</Link>
              </div>
            )}
          </div>
          <RecordPagination
            page={page}
            total={records.data?.total ?? 0}
            pageSize={PAGE_SIZE}
            onPageChange={handlePageChange}
          />
        </div>
        <aside className="grid gap-4 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
          <div className="hidden lg:block">
            {selectedRecord ? (
              <RecordDetailPanel
                record={selectedRecord}
                canEdit
                canManage={isAdmin}
                onManage={() => {
                  setManagementDate(selectedRecord.date);
                  setManagementOpen(true);
                }}
              />
            ) : (
              <div className="grid gap-2 rounded-md border border-dashed p-4">
                <p>暂无可查看记录</p>
                {!records.isLoading && !records.error && (
                  <Link className="w-fit text-primary underline-offset-4 hover:underline" to={`/ledger?date=${today}`}>补记记录</Link>
                )}
              </div>
            )}
          </div>
          <BusinessAnalysisCard key={selected.id} storeId={selected.id} today={today} />
        </aside>
      </div>
      {mobileRecord && mobileRecord.store_id === selected.id && (
        <MobileRecordSheet
          open
          record={mobileRecord}
          canEdit
          canManage={isAdmin}
          returnFocusTo={returnFocusTo}
          onOpenChange={(open) => {
            if (!open) setMobileRecord(null);
          }}
          onManage={() => {
            setManagementDate(mobileRecord.date);
            setManagementOpen(true);
          }}
        />
      )}
      <RecordManagementDialogs
        key={selected.id}
        storeId={selected.id}
        record={selectedRecord}
        targetDate={recordStateReady ? managementDate : null}
        open={recordStateReady && managementOpen}
        onOpenChange={setManagementOpen}
        onCompleted={() => setMobileRecord(null)}
      />
    </section>
  );
}
