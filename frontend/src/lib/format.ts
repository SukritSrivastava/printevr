const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' })
const plain = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 })

/** "169920.00" -> "₹1,69,920.00". The API sends money as strings; formatting is display-only. */
export function money(value: string | number): string {
  return inr.format(typeof value === 'string' ? Number(value) : value)
}

/** Whole money without paise when there are none: "55.00" -> "₹55", "5.50" -> "₹5.50". */
export function shortMoney(value: string | number): string {
  const n = typeof value === 'string' ? Number(value) : value
  return Number.isInteger(n) ? inr.format(n).replace(/\.00$/, '') : inr.format(n)
}

export function count(value: number): string {
  return plain.format(value)
}

export function plural(n: number, unit: string): string {
  if (n === 1 || unit.endsWith('s') || unit.includes(' ')) return unit
  if (/(x|ch|sh)$/.test(unit)) return `${unit}es`
  return `${unit}s`
}

/** "1,200 boxes", "240 sq ft", "3 rolls". */
export function qtyWithUnit(n: number, unit: string): string {
  return `${count(n)} ${plural(n, unit)}`
}
