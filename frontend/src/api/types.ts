export type UserRole = "admin" | "user";

export interface User {
  id: number;
  username: string;
  role: UserRole;
}

export interface AdminUser extends User {
  is_active: boolean;
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
