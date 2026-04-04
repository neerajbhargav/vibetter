<script setup>
import { ref, onMounted } from 'vue'
import { VueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'

import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'

const nodes = ref([])
const edges = ref([])
const loading = ref(true)
const noData = ref(false)

onMounted(() => {
    const data = window.__VIBETTER_BLUEPRINT__

    if (data && Array.isArray(data.nodes) && data.nodes.length > 0) {
        // Apply dark theme styling to nodes that don't already have classes
        nodes.value = data.nodes.map((n, i) => ({
            ...n,
            class: n.class || getNodeClass(i),
        }))
        edges.value = (data.edges || []).map(e => ({
            ...e,
            animated: e.animated ?? true,
            style: e.style || { stroke: '#3b82f6', strokeWidth: 2 },
        }))
        loading.value = false
    } else {
        loading.value = false
        noData.value = true
    }
})

const palette = [
    'bg-blue-900 border-blue-500 text-white shadow-xl shadow-blue-500/20',
    'bg-emerald-900 border-emerald-500 text-white shadow-xl shadow-emerald-500/20',
    'bg-purple-900 border-purple-500 text-white shadow-xl shadow-purple-500/20',
    'bg-amber-900 border-amber-500 text-white shadow-xl shadow-amber-500/20',
    'bg-rose-900 border-rose-500 text-white shadow-xl shadow-rose-500/20',
    'bg-cyan-900 border-cyan-500 text-white shadow-xl shadow-cyan-500/20',
]

function getNodeClass(index) {
    return palette[index % palette.length]
}
</script>

<template>
  <div class="h-full w-full">
    <!-- Loading spinner -->
    <div v-if="loading" class="absolute inset-0 flex items-center justify-center bg-gray-900/90 z-50 backdrop-blur-sm">
        <div class="flex flex-col items-center gap-6">
            <div class="relative w-16 h-16">
                <div class="absolute inset-0 border-4 border-emerald-500 border-t-transparent rounded-full animate-spin"></div>
                <div class="absolute inset-2 border-4 border-blue-500 border-b-transparent rounded-full animate-spin direction-reverse"></div>
            </div>
            <p class="text-emerald-400 font-mono tracking-widest text-sm bg-gray-800 px-4 py-2 rounded-lg border border-gray-700 shadow-lg">INGESTING MASTER CONTEXT...</p>
        </div>
    </div>

    <!-- No data state -->
    <div v-else-if="noData" class="absolute inset-0 flex items-center justify-center bg-gray-900 z-50">
        <div class="flex flex-col items-center gap-4 text-center max-w-md px-6">
            <div class="text-5xl">🗺️</div>
            <h2 class="text-xl font-bold text-white">Blueprint not generated yet</h2>
            <p class="text-gray-400 text-sm leading-relaxed">
                Call the <code class="bg-gray-800 px-2 py-0.5 rounded text-emerald-400 font-mono">generate_blueprint</code> tool first,
                then reopen this resource to see your codebase map.
            </p>
            <div class="mt-2 bg-gray-800 rounded-lg px-4 py-3 border border-gray-700 text-left w-full">
                <p class="text-xs text-gray-500 font-mono mb-1">In your IDE chat:</p>
                <p class="text-sm text-emerald-400 font-mono">generate_blueprint()</p>
            </div>
        </div>
    </div>

    <!-- Vue Flow graph -->
    <VueFlow
        v-else
        v-model:nodes="nodes"
        v-model:edges="edges"
        class="bg-gray-900 text-white vue-flow-dark"
        fit-view-on-init
    >
        <Background pattern-color="#374151" gap="24" size="1.2" />
        <Controls class="bg-gray-800 border-gray-700 fill-gray-300" />
        <MiniMap
            class="bg-gray-800 border-gray-700 rounded-lg shadow-xl"
            node-color="#10b981"
            mask-color="rgba(17, 24, 39, 0.7)"
        />
    </VueFlow>
  </div>
</template>

<style>
.vue-flow-dark .vue-flow__node {
  border-radius: 8px;
  padding: 12px 20px;
  font-family: inherit;
  font-size: 14px;
  border-width: 2px;
  font-weight: 500;
  transition: all 0.2s ease;
}
.vue-flow-dark .vue-flow__node:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
}
.vue-flow-dark .vue-flow__edge-path {
    stroke-width: 2.5;
}
.direction-reverse {
    animation-direction: reverse;
}
</style>
