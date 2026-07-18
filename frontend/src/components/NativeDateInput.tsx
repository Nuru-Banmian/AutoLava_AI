import { CalendarDays } from "lucide-react";
import { useRef, type InputHTMLAttributes } from "react";

type NativeDateInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "className" | "type">;

export function NativeDateInput(props: NativeDateInputProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const ariaLabel = props["aria-label"] ?? "日期";
  const openPicker = () => {
    const input = inputRef.current;
    if (!input) return;
    if (typeof input.showPicker === "function") input.showPicker();
    else input.focus();
  };

  return <div className="relative w-full">
    <input ref={inputRef} {...props} type="date" className="min-h-11 w-full rounded-md border border-input bg-background px-2 pr-11 text-base [color-scheme:light] [&::-webkit-calendar-picker-indicator]:pointer-events-none [&::-webkit-calendar-picker-indicator]:opacity-0" />
    <button aria-label={`打开${ariaLabel}日历`} className="absolute inset-y-0 right-0 grid size-11 place-items-center rounded-r-md" onClick={openPicker} type="button"><CalendarDays aria-hidden="true" size={20} /></button>
  </div>;
}
