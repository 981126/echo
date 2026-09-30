import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath } from 'node:url'

export default defineConfig(() => ({
  // R-208：老前端已下线，生产直接挂根路径 /（FastAPI 静态托管）
  base: '/',
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) }
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          'vendor-motion': ['framer-motion'],
          'vendor-query': ['@tanstack/react-query'],
          'vendor-tiptap': [
            '@tiptap/react',
            '@tiptap/starter-kit',
            '@tiptap/markdown',
            '@tiptap/extension-image',
            '@tiptap/extension-placeholder',
            '@tiptap/extension-table',
            '@tiptap/extension-list'
          ],
          'vendor-radix': [
            '@radix-ui/react-dialog',
            '@radix-ui/react-dropdown-menu',
            '@radix-ui/react-popover',
            '@radix-ui/react-tooltip',
            '@radix-ui/react-scroll-area',
            '@radix-ui/react-tabs',
            '@radix-ui/react-avatar',
            '@radix-ui/react-switch',
            '@radix-ui/react-progress',
            '@radix-ui/react-separator',
            '@radix-ui/react-slot',
            '@radix-ui/react-label'
          ]
        }
      }
    }
  },
  server: {
    port: 3000,
    proxy: {
      '/api': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/covers': 'http://localhost:8000',
      '/uploads': 'http://localhost:8000',
      '/media': 'http://localhost:8000'
    }
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    css: false
  }
}))
