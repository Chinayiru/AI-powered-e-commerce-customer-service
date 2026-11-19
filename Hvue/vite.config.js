import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// JAVA_PROXY_TARGET 仅在开发服务器读取，不向浏览器注入实际部署地址。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = process.env.JAVA_PROXY_TARGET || env.JAVA_PROXY_TARGET
  if (target) {
    try {
      const url = new URL(target)
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password ||
          url.search || url.hash || url.hostname.endsWith('.invalid')) throw new Error()
    } catch {
      throw new Error('JAVA_PROXY_TARGET must be an HTTP(S) URL without credentials, query or fragment')
    }
  }
  return {
    plugins: [vue()],
    server: {
      host: '127.0.0.1',
      port: 5173,
      proxy: target ? {
        '/api': {
          target,
          changeOrigin: true
        }
      } : undefined
    }
  }
})
