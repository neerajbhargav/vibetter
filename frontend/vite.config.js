import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// The built UI ships inside the Python package as package data.
export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: '../src/vibetter/ui',
    emptyOutDir: true,
  },
})
