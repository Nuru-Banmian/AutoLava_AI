import { format, parseISO } from "date-fns";

const chineseWeekdays = ["星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"] as const;

export function formatBusinessRecordDate(value: string): string {
  const recordDate = parseISO(value);
  return `${format(recordDate, "yyyy年M月d日")} ${chineseWeekdays[recordDate.getDay()]}`;
}
