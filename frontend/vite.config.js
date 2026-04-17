import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/session': 'http://localhost:8000',
      '/attachment': 'http://localhost:8000',
    },
  },
})
