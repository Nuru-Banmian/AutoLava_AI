export function formatCompactEuro(value: number): string {
  const scales = [[1_000_000_000, "b"], [1_000_000, "m"], [1_000, "k"]] as const;
  for (const [divisor, unit] of scales) {
    if (Math.abs(value) >= divisor) return `€${Number((value / divisor).toFixed(1))}${unit}`;
  }
  return `€${value}`;
}
