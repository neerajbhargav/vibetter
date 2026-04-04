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

onMounted(async () => {
    loading.value = true;
    try {
        // Mock payload simulating the Master Context generate_blueprint() FastMCP response.
        // In reality, this UI runs within Claude Desktop/Cursor using SEP-1865,
        // and the host client directly feeds the schema via protocol context.
        setTimeout(() => {
            const mockData = {
                nodes: [
                    { id: '1', type: 'input', position: { x: 300, y: 50 }, data: { label: 'src/server.py' }, class: 'bg-blue-900 border-blue-500 text-white shadow-xl shadow-blue-500/20' },
                    { id: '2', position: { x: 150, y: 200 }, data: { label: 'brain/scholar.py' }, class: 'bg-emerald-900 border-emerald-500 text-white shadow-xl shadow-emerald-500/20' },
                    { id: '3', position: { x: 450, y: 200 }, data: { label: 'config.py (Env Layer)' }, class: 'bg-gray-800 border-gray-600 text-gray-200 shadow-xl' },
                    { id: '4', position: { x: 300, y: 350 }, data: { label: 'Master Context Engine' }, class: 'bg-purple-900 border-purple-500 text-white shadow-xl shadow-purple-500/20 rounded-full' }
                ],
                edges: [
                    { id: 'e1-2', source: '1', target: '2', animated: true, style: { stroke: '#3b82f6', strokeWidth: 2 } },
                    { id: 'e1-3', source: '1', target: '3', animated: true, style: { stroke: '#3b82f6', strokeWidth: 2 } },
                    { id: 'e2-4', source: '2', target: '4', animated: true, style: { stroke: '#10b981', strokeWidth: 2 } }
                ]
            }
            
            nodes.value = mockData.nodes
            edges.value = mockData.edges
            loading.value = false;
        }, 1200);
    } catch (e) {
        console.error(e)
        loading.value = false;
    }
})
</script>

<template>
  <div class="h-full w-full">
    <div v-if="loading" class="absolute inset-0 flex items-center justify-center bg-gray-900/90 z-50 backdrop-blur-sm transition-opacity duration-300">
        <div class="flex flex-col items-center gap-6">
            <div class="relative w-16 h-16">
                <div class="absolute inset-0 border-4 border-emerald-500 border-t-transparent rounded-full animate-spin"></div>
                <div class="absolute inset-2 border-4 border-blue-500 border-b-transparent rounded-full animate-spin direction-reverse"></div>
            </div>
            <p class="text-emerald-400 font-mono tracking-widest text-sm bg-gray-800 px-4 py-2 rounded-lg border border-gray-700 shadow-lg">INGESTING MASTER CONTEXT...</p>
        </div>
    </div>
    
    <VueFlow v-model:nodes="nodes" v-model:edges="edges" class="bg-gray-900 text-white vue-flow-dark" fit-view-on-init>
        <Background pattern-color="#374151" gap="24" size="1.2" />
        <Controls class="bg-gray-800 border-gray-700 fill-gray-300" />
        <MiniMap class="bg-gray-800 border-gray-700 rounded-lg shadow-xl" node-color="#10b981" mask-color="rgba(17, 24, 39, 0.7)" />
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
</style>
