<script setup>
import BlueprintNodeMap from './components/BlueprintNodeMap.vue'
</script>

<template>
  <div class="h-screen w-screen flex flex-col bg-gray-900 text-white">
    <header class="py-4 px-6 bg-gray-800 border-b border-gray-700 shadow-md flex justify-between items-center z-10">
      <div>
        <h1 class="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-emerald-400">VIBETTER Core</h1>
        <p class="text-sm text-gray-400 font-mono mt-1">Cognitive Codebase Blueprint</p>
      </div>
      <div class="flex items-center gap-4">
        <!-- Live status indicator -->
        <div class="flex items-center gap-2 px-3 py-1 bg-gray-900 border border-emerald-500/30 rounded-full shadow-inner">
            <span class="relative flex h-3 w-3">
              <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span class="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span>
            </span>
            <span class="text-xs font-mono tracking-widest text-emerald-400 uppercase">Live Parse Active</span>
        </div>
      </div>
    </header>
    <main class="flex-1 w-full h-full relative">
      <BlueprintNodeMap />
    </main>
  </div>
</template>

<style>
</style>
