import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Фронт ходит на API через тот же origin (proxy), поэтому cookie с refresh-токеном
// работают без CORS и без SameSite-исключений.
// host: 0.0.0.0 — чтобы открывать сайт с телефона по локальной сети (Wi-Fi);
// прокси /api при этом остаётся на локальный бэкенд 127.0.0.1:8001.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    // Sourcemap в прод не отдаём: карты раскрывают исходники и весят больше самого бандла.
    sourcemap: false,
  },
})
