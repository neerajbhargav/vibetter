import { CURRENCY } from './format'

export async function fetchCart(id) {
  const response = await fetch(`/api/carts/${id}?currency=${CURRENCY}`)
  if (!response.ok) {
    throw new Error(`cart ${id} failed: ${response.status}`)
  }
  return response.json()
}
