export type UserRole = "admin" | "user";

export interface User {
  id: number;
  username: string;
  role: UserRole;
}

export interface AuthenticatedUser extends User {
  is_owner: boolean;
}

export interface AdminUser extends User {
  is_active: boolean;
  store_ids: number[];
}

export interface AccessibleStore {
  id: number;
  name: string;
  timezone: string;
  is_active?: boolean;
}

export interface AdminStore extends AccessibleStore {
  address: string;
  latitude: string;
  longitude: string;
  is_active: boolean;
}

export interface StoreLocation {
  label: string;
  latitude: number;
  longitude: number;
  timezone: string;
}

export interface IncomeCategory {
  id: number;
  store_id: number;
  name: string;
  include_in_total: boolean;
  is_active: boolean;
  sort_order: number;
}

export interface IncomeConfigResponse {
  store_id: number;
  enabled: boolean;
  formula: string;
  items: IncomeConfigItem[];
}

export interface IncomeConfigItem {
  id: number;
  store_id: number;
  name: string;
  include_in_total: boolean;
  is_active: boolean;
  sort_order: number;
  archived_at: string | null;
}

export interface StoreMembers {
  store_id: number;
  user_ids: number[];
}

export interface SystemAlert {
  id: number;
  store_id: number | null;
  alert_type: string;
  level: string;
  message: string;
  is_resolved: boolean;
  created_at: string | null;
  resolved_at: string | null;
  timestamp_status: "utc" | "legacy_unknown";
}

export interface ScheduledTaskLog {
  id: number;
  store_id: number | null;
  task_type: string;
  status: string;
  message: string | null;
  retry_count: number;
  started_at: string | null;
  finished_at: string | null;
  created_at: string | null;
  timestamp_status: "utc" | "legacy_unknown";
}

export type LedgerStatus = "营业" | "休息" | "天气停业";
export type IncomeMode = "legacy_total" | "composed";
export interface CategoryDescriptor { id: number; name: string; include_in_total: boolean; is_active: boolean; sort_order: number }
export interface IncomeItemBody { category_id: number; amount: number }
export interface LedgerBody {
  is_open: LedgerStatus;
  daily_revenue: number | null;
  wash_count: number | null;
  weather: string | null;
  weather_edited: boolean;
  activity: string | null;
  items: IncomeItemBody[];
}
export interface LedgerSaveResponse { id: number; date: string; daily_revenue: number }
export interface RecordItem extends IncomeItemBody { id: number; category_name: string; include_in_total: boolean; sort_order: number; created_at: string; updated_at: string }
export interface RecordSnapshot {
  id: number; store_id: number; date: string; daily_revenue: number; wash_count: number | null; is_open: LedgerStatus;
  income_mode: IncomeMode;
  weather: string | null; weather_auto: string | null; weather_code: number | null; temperature_max: string | null;
  temperature_min: string | null; precipitation: string | null; activity: string | null; weather_edited: boolean; scanned: boolean;
  created_by: number; updated_by: number; created_at: string; updated_at: string; items: RecordItem[];
  created_by_name?: string; updated_by_name?: string;
}
export interface DatabaseResponse { items: RecordSnapshot[]; categories: CategoryDescriptor[]; sum_daily_revenue: number; total: number; page: number; page_size: number }
export interface BriefingCard {
  card_type: "yesterday" | "today" | "tomorrow";
  state: "missing" | "recorded" | "rest" | "weather_closed" | "forecast" | "unavailable";
  revenue: number | null;
  weather: string | null;
  weekday: string | null;
  temperature_max: string | null;
  temperature_min: string | null;
  precipitation: string | null;
  hint: string | null;
  generated_at: string | null;
  timestamp_status: "utc" | "legacy_unknown";
}
export interface WeatherResponse { weather: string | null; weather_code: number | null; temperature_max: number | null; temperature_min: number | null; precipitation: number | null }
export type ChartBucket = "day" | "month";
export interface CategoryComposition { category_id: number; category_name: string; amount: number }
export interface ChartComparisonKpis { start: string; end: string; total_revenue: number; open_days: number; average_revenue: number }
export interface ChartsResponse {
  kpis: { total_revenue: number; record_days: number; open_days: number; average_revenue: number; primary_categories: CategoryComposition[]; total_wash_count: number | null; average_ticket: number | null };
  range: { start: string; end: string; bucket: ChartBucket };
  comparison_kpis: ChartComparisonKpis | null;
  classified_included_total: number;
  daily: { date: string; revenue: number }[];
  categories: CategoryComposition[];
  excluded_categories: CategoryComposition[];
  monthly: { month: string; revenue: number }[];
  weather: { weather: string; average_revenue: number }[];
  weekday: { weekday: number; average_revenue: number }[];
}
