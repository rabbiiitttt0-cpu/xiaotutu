import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      // dxf-viewer 以 default 方式导入 opentype.js，其 ESM 版（opentype.mjs）无 default 导出，
      // rollup 构建报 "not exported" —— 强制走 UMD/CJS 版做默认导出兼容
      'opentype.js': 'opentype.js/dist/opentype.js',
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:7780',
        changeOrigin: true,
      },
      '/output': {
        target: 'http://localhost:7780',
        changeOrigin: true,
      },
    },
  },
})
