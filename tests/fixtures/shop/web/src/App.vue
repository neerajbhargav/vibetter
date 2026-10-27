<script setup lang="ts">
import CartView from './components/CartView.vue'
import { formatPrice } from '@/lib/format'

const banner = formatPrice(0)
</script>

<template>
  <header>{{ banner }}</header>
  <CartView />
</template>
