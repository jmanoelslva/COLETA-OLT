import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import pacote from './package.json'

// Em dev a API roda em http://127.0.0.1:8090 (python -m coletor).
declare const process: { env: Record<string, string | undefined> }

// COLETOR_BASE=/olt/ no build = publicado dentro do app técnico (tecnico.hotnet.net.br/olt/).
export default defineConfig({
  base: process.env.COLETOR_BASE || '/',
  plugins: [react()],
  define: { __VERSAO__: JSON.stringify(pacote.version) },
  server: {
    port: 5174,
    proxy: { '/api': 'http://127.0.0.1:8090' },
  },
})
