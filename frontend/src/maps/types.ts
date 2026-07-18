export interface MapLocation {
  label: string;
  latitude: number;
  longitude: number;
  timezone: string;
}

export interface MapAdapter {
  mount(
    container: HTMLElement,
    value: MapLocation | null,
    onChange: (value: Pick<MapLocation, "latitude" | "longitude">) => void,
  ): () => void;
}
