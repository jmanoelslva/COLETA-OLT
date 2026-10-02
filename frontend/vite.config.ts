import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import pacote from './package.json'

// Em dev a API roda em http://127.0.0.1:8090 (python -m coletor).
export default defineConfig({
  plugins: [react()],
  define: { __VERSAO__: JSON.stringify(pacote.version) },
  server: {
    port: 5174,
    proxy: { '/api': 'http://127.0.0.1:8090' },
  },
})
