export type UserRole = "admin" | "user";

export interface User {
  id: number;
  username: string;
  role: UserRole;
}

export interface AdminUser extends User {
  is_active: boolean;
  store_ids: number[];
}

export interface AccessibleStore {
  id: number;
  name: string;
  timezone: string;
}

export interface AdminStore extends AccessibleStore {
  address: string;
  latitude: string;
  longitude: string;
  is_active: boolean;
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
  version_id: number | null;
  version: number;
  enabled: boolean;
  formula: string;
  created_at: string | null;
  items: IncomeConfigItem[];
}

export interface IncomeConfigItem {
  id: number;
  category_id: number | null;
  name: string;
  include_in_total: boolean;
  is_active: boolean;
  sort_order: number;
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
  created_at: string;
  resolved_at: string | null;
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
  created_at: string;
}

export type LedgerStatus = "营业" | "休息" | "天气停业";
export type IncomeMode = "legacy_total" | "composed";
export interface CategoryDescriptor { id: number; name: string; include_in_total: boolean; is_active: boolean; sort_order: number }
export interface IncomeItemBody { category_id: number; amount: string }
export interface LedgerBody {
  is_open: LedgerStatus;
  daily_revenue: string | null;
  config_version_id: number | null;
  expected_version: number | null;
  wash_count: number | null;
  weather: string | null;
  weather_edited: boolean;
  activity: string | null;
  items: IncomeItemBody[];
}
export interface LedgerSaveResponse { id: number; date: string; daily_revenue: string; row_version: number }
export interface RecordItem extends IncomeItemBody { id: number; category_name: string; include_in_total: boolean; sort_order: number; created_at: string; updated_at: string }
export interface RecordSnapshot {
  id: number; store_id: number; date: string; daily_revenue: string; wash_count: number | null; is_open: LedgerStatus;
  income_mode: IncomeMode; income_config_version_id: number | null; row_version: number;
  weather: string | null; weather_auto: string | null; weather_code: number | null; temperature_max: string | null;
  temperature_min: string | null; precipitation: string | null; activity: string | null; weather_edited: boolean; scanned: boolean;
  created_by: number; updated_by: number; created_at: string; updated_at: string; items: RecordItem[];
  created_by_name?: string; updated_by_name?: string;
}
export interface DatabaseResponse { items: RecordSnapshot[]; categories: CategoryDescriptor[]; sum_daily_revenue: string; total: number; page: number; page_size: number }
export interface AuditEntry { id: number; record_id: number | null; record_date: string | null; operation_type: string; operation_source: string; operator_user_id: number; operator_username: string; before: RecordSnapshot | null; after: RecordSnapshot | null; description: string; requires_approval: boolean; approved: boolean; rollbackable: boolean; created_at: string }
export interface BriefingCard {
  card_type: "yesterday" | "today" | "tomorrow";
  state: "missing" | "recorded" | "rest" | "weather_closed" | "forecast" | "unavailable";
  revenue: string | null;
  weather: string | null;
  weekday: string | null;
  temperature_max: string | null;
  temperature_min: string | null;
  precipitation: string | null;
  hint: string | null;
  generated_at: string;
}
export interface WeatherResponse { weather: string | null; weather_code: number | null; temperature_max: number | null; temperature_min: number | null; precipitation: number | null }
export interface ChartsResponse {
  kpis: { total_revenue: string; record_days: number; open_days: number; average_revenue: string; primary_categories: { category_id: number; category_name: string; amount: string }[]; total_wash_count: number | null; average_ticket: string | null };
  daily: { date: string; revenue: string }[]; categories: { category_id: number; category_name: string; amount: string }[];
  monthly: { month: string; revenue: string }[]; weather: { weather: string; average_revenue: string }[]; weekday: { weekday: number; average_revenue: string }[];
}
