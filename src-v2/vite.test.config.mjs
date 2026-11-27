import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Временный конфиг для браузерных проверок на тестовой БД:
// фронтенд тот же, но /api проксируется на отдельный API (8002), чтобы
// не менять данные рабочей karier_db.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5175,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8002',
        changeOrigin: false,
      },
    },
  },
})
