import type { InputHTMLAttributes } from "react";

type NativeDateInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "className" | "type">;

export function NativeDateInput(props: NativeDateInputProps) {
  return <input {...props} type="date" className="min-h-11 w-full rounded-md border border-input bg-background px-2 pr-11 text-base [color-scheme:light] [&::-webkit-calendar-picker-indicator]:h-11 [&::-webkit-calendar-picker-indicator]:w-11 [&::-webkit-calendar-picker-indicator]:cursor-pointer" />;
}
