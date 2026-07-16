import L from "leaflet";

import type { MapAdapter } from "@/maps/types";

export const mapProviderConfig = {
  tiles: import.meta.env.VITE_MAP_TILE_URL || "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  attribution: import.meta.env.VITE_MAP_ATTRIBUTION || "© OpenStreetMap contributors",
};

const markerIcon = L.divIcon({
  className: "autolava-map-marker",
  html: '<span aria-hidden="true"></span>',
  iconAnchor: [12, 24],
  iconSize: [24, 24],
});

export const leafletMapAdapter: MapAdapter = {
  mount(container, value, onChange) {
    const initial = value ? L.latLng(value.latitude, value.longitude) : L.latLng(34, 105);
    const map = L.map(container).setView(initial, value ? 14 : 3);
    L.tileLayer(mapProviderConfig.tiles, { attribution: mapProviderConfig.attribution, maxZoom: 19 }).addTo(map);
    const marker = L.marker(initial, { draggable: true, icon: markerIcon });
    if (value) marker.addTo(map);

    const select = (latitude: number, longitude: number) => {
      marker.setLatLng([latitude, longitude]);
      if (!map.hasLayer(marker)) marker.addTo(map);
      onChange({ latitude, longitude });
    };
    const onClick = (event: L.LeafletMouseEvent) => select(event.latlng.lat, event.latlng.lng);
    const onDrag = () => { const point = marker.getLatLng(); onChange({ latitude: point.lat, longitude: point.lng }); };
    map.on("click", onClick);
    marker.on("dragend", onDrag);
    requestAnimationFrame(() => map.invalidateSize());
    return () => {
      marker.off("dragend", onDrag);
      map.off("click", onClick);
      map.remove();
    };
  },
};
