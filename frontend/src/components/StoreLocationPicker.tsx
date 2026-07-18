import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { api, friendlyApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { leafletMapAdapter } from "@/maps/provider";
import type { MapAdapter, MapLocation } from "@/maps/types";

type GeocodeCandidate = { name: string; country: string; latitude: number; longitude: number; timezone: string };

interface Props {
  value: MapLocation | null;
  onConfirm: (value: MapLocation) => void;
  adapter?: MapAdapter;
  buttonLabel?: string;
}

export function StoreLocationPicker({ value, onConfirm, adapter = leafletMapAdapter, buttonLabel }: Props) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<MapLocation | null>(value);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<GeocodeCandidate[]>([]);
  const [error, setError] = useState("");
  const [searching, setSearching] = useState(false);
  const [mapNode, setMapNode] = useState<HTMLDivElement | null>(null);
  const requestSequence = useRef(0);
  const searchSequence = useRef(0);
  const openRef = useRef(false);

  const cancelSearch = useCallback(() => {
    searchSequence.current += 1;
    setSearching(false);
  }, []);

  useEffect(() => {
    requestSequence.current += 1;
    if (!open) setDraft(value);
  }, [open, value]);

  const resolveCoordinates = useCallback(async (point: Pick<MapLocation, "latitude" | "longitude">) => {
    cancelSearch();
    const sequence = ++requestSequence.current;
    setError("");
    setDraft({ label: "地图选点", ...point, timezone: "" });
    try {
      const params = new URLSearchParams({ latitude: String(point.latitude), longitude: String(point.longitude) });
      const result = await api<{ timezone: string }>(`/admin/stores/timezone?${params}`);
      if (sequence !== requestSequence.current) return;
      setDraft({ label: "地图选点", ...point, timezone: result.timezone });
    } catch (reason) {
      if (sequence !== requestSequence.current) return;
      setError(friendlyApiError(reason, "暂时无法识别该位置的时区，请重新选择或稍后重试"));
    }
  }, [cancelSearch]);

  const useCurrentLocation = useCallback(() => {
    cancelSearch();
    const sequence = ++requestSequence.current;
    setError("");
    const isCurrent = () => openRef.current && sequence === requestSequence.current;
    if (!navigator.geolocation) {
      if (isCurrent()) setError("无法获取当前位置，你仍然可以搜索地点");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        if (!isCurrent()) return;
        void resolveCoordinates({ latitude: coords.latitude, longitude: coords.longitude });
      },
      () => {
        if (isCurrent()) setError("无法获取当前位置，你仍然可以搜索地点");
      },
      { enableHighAccuracy: true, timeout: 10000 },
    );
  }, [cancelSearch, resolveCoordinates]);

  useEffect(() => {
    if (open) useCurrentLocation();
  }, [open, useCurrentLocation]);

  useEffect(() => {
    if (!open || !mapNode) return;
    return adapter.mount(mapNode, draft, resolveCoordinates);
  }, [adapter, draft?.latitude, draft?.longitude, mapNode, open, resolveCoordinates]);

  async function search(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    requestSequence.current += 1;
    const sequence = ++searchSequence.current;
    setSearching(true);
    setError("");
    setResults([]);
    try {
      const candidates = await api<GeocodeCandidate[]>(`/admin/stores/geocode?query=${encodeURIComponent(query.trim())}`);
      if (sequence === searchSequence.current) setResults(candidates);
    } catch (reason) {
      if (sequence === searchSequence.current) setError(friendlyApiError(reason, "地点搜索失败，请稍后重试"));
    } finally {
      if (sequence === searchSequence.current) setSearching(false);
    }
  }

  function close(next: boolean) {
    openRef.current = next;
    if (!next) {
      cancelSearch();
      requestSequence.current += 1;
      setError("");
      setResults([]);
      setQuery("");
    }
    setOpen(next);
  }

  return <>
    <Button type="button" variant="outline" onClick={() => close(true)}>{buttonLabel ?? (value ? "修改地图位置" : "打开地图选择")}</Button>
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader><DialogTitle>选择门店位置</DialogTitle><DialogDescription>可搜索地点、使用当前位置，或在地图中点击和拖动标记。</DialogDescription></DialogHeader>
        <form role="search" className="flex gap-2" onSubmit={search}>
          <Input aria-label="搜索城市、区域或地点" value={query} onChange={(event) => setQuery(event.target.value)} />
          <Button disabled={searching} type="submit">{searching ? "搜索中…" : "搜索"}</Button>
        </form>
        {results.length > 0 && <ul className="space-y-1">{results.map((result) => <li key={`${result.latitude}-${result.longitude}`}>
          <Button className="h-auto w-full justify-start py-2" type="button" variant="ghost" onClick={() => {
            cancelSearch();
            requestSequence.current += 1;
            setDraft({ label: `${result.name}, ${result.country}`, latitude: result.latitude, longitude: result.longitude, timezone: result.timezone });
            setResults([]);
          }}>{result.name}, {result.country}</Button>
        </li>)}</ul>}
        <div ref={setMapNode} aria-label="门店位置地图" className="h-72 w-full overflow-hidden rounded-lg border" />
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Button type="button" variant="secondary" onClick={useCurrentLocation}>使用当前位置</Button>
          {draft && <p className="text-sm text-muted-foreground">{draft.label}{draft.timezone ? ` · ${draft.timezone}` : " · 正在识别时区…"}</p>}
        </div>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => close(false)}>取消</Button>
          <Button type="button" disabled={!draft?.timezone} onClick={() => { if (draft?.timezone) { onConfirm(draft); close(false); } }}>确认位置</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </>;
}
