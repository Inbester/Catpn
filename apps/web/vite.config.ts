import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': new URL('./src', import.meta.url).pathname },
  },
  server: {
    port: 5173,
    headers: {
      // Cross-origin isolation, needed for SharedArrayBuffer and WASM threads
      // in the browser compute engine (SPEC §3.6). Set here so the dev server
      // matches what the API sends in production.
      'Cross-Origin-Opener-Policy': 'same-origin',
      'Cross-Origin-Embedder-Policy': 'require-corp',
    },
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
        // The live chart stream is a WebSocket on the same prefix, so the
        // proxy has to forward upgrade requests too.
        ws: true,
      },
    },
  },
  build: {
    sourcemap: true,
    target: 'es2022',
  },
});
