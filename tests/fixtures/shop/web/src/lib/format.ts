export const CURRENCY = 'USD'

export function formatPrice(cents: number): string {
  const dollars = (cents / 100).toFixed(2)
  return `${CURRENCY} ${dollars}`
}

export interface PriceTag {
  label: string
  cents: number
}
