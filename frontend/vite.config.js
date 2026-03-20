import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

const BUILD_TS = Date.now()

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  return {
    plugins: [react()],
    define: {
      __BUILD_TS__: BUILD_TS,
    },
    server: {
      host: '0.0.0.0',
      port: 5173,
      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
        },
        '/ws': {
          target: 'ws://localhost:8000',
          ws: true,
          changeOrigin: true,
        },
        '/media': {
          target: 'http://localhost:8000',
          changeOrigin: true,
        },
      }
    },
    build: {
      outDir: 'dist',
      rollupOptions: {
        output: {
          // Use a short build timestamp suffix to bust CDN cache on every deploy
          entryFileNames: `assets/[name]-[hash]-${BUILD_TS.toString(36)}.js`,
          chunkFileNames: `assets/[name]-[hash]-${BUILD_TS.toString(36)}.js`,
          assetFileNames: `assets/[name]-[hash].[ext]`,
          manualChunks: {
            vendor: ['react', 'react-dom', 'react-router-dom'],
            charts: ['recharts'],
          }
        }
      }
    }
  }
})
