import type { components } from "@/api/generated";
import { recordWeatherValues } from "@/api/weather-values";

type Schema = components["schemas"];

export type UserRole = Schema["AuthenticatedUserResponse"]["role"];
export type User = Pick<Schema["AuthenticatedUserResponse"], "id" | "username" | "role">;
export type AuthenticatedUser = Schema["AuthenticatedUserResponse"];
export type AdminUser = Schema["AdminUserResponse"];
export type AccessibleStore = Schema["AccessibleStoreResponse"];
export type AdminStore = Schema["AdminStoreResponse"];

// Geocoding coordinates are a display and draft model, not an API transport schema.
export interface StoreLocation {
  label: string;
  latitude: number;
  longitude: number;
  timezone: string;
}

export type IncomeCategory = Schema["IncomeCategoryResponse"];
export type IncomeConfigResponse = Schema["IncomeConfigResponse"];
export type IncomeConfigItem = Schema["IncomeCategoryResponse"];
export type StoreMembers = Schema["StoreMembersResponse"];
export type SystemAlert = Schema["SystemAlertResponse"];
export type ScheduledTaskLog = Schema["ScheduledTaskLogResponse"];

export type LedgerStatus = Schema["LedgerBody"]["is_open"];
export type IncomeMode = Schema["RecordSnapshot"]["income_mode"];
export type CategoryDescriptor = Schema["CategoryDescriptor"];
export type IncomeItemBody = Schema["IncomeItemBody"];
export type LedgerBody = Schema["LedgerBody"];
type RecordWeather = NonNullable<LedgerBody["weather"]>;
type MissingWeather = Exclude<RecordWeather, (typeof recordWeatherValues)[number]>;
const allWeatherValuesPresent: MissingWeather extends never ? true : never = true;
void allWeatherValuesPresent;

export function isRecordWeather(value: string): value is RecordWeather {
  return (recordWeatherValues as readonly string[]).includes(value);
}
export type LedgerSaveResponse = Schema["LedgerSaveResponse"];
export type RecordItem = Schema["RecordItem"];
export type BookkeepingEvent = Schema["BookkeepingEvent"];
export type RecordSnapshot = Schema["RecordSnapshot"];
export type DatabaseResponse = Schema["DatabasePage"];
export type BriefingCard = Required<Schema["DashboardCardResponse"]>;
export type WeatherResponse = Schema["WeatherResponse"];

export type ChartBucket = Schema["ChartRange"]["bucket"];
export type CategoryComposition = Schema["PrimaryCategory"] | Schema["SettlementComposition"];
export type ChartComparisonKpis = Schema["ChartComparisonKpis"];
export type IncomeSummary = Schema["IncomeSummary"];
export type MonthlyRevenue = Schema["MonthlyRevenue"];
export type ChartsResponse = Schema["ChartsResponse"];
