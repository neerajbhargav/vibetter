<script setup>
import { ref, onMounted } from 'vue'
import { formatPrice } from '../lib/format'
import { fetchCart } from '../lib/api.js'

const total = ref(0)

onMounted(async () => {
  const cart = await fetchCart('current')
  total.value = cart.totalCents
})
</script>

<template>
  <p>Total: {{ formatPrice(total) }}</p>
</template>
