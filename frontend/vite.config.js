import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// During `npm run dev`, /api and /socket.io are proxied to the FastAPI backend
// at localhost:8000 so the React app and the backend share an origin.
// In production, Nginx handles the same routing — see ../nginx/sikok.conf.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: '0.0.0.0',
    proxy: {
      '/api': 'http://localhost:8000',
      '/socket.io': { target: 'http://localhost:8000', ws: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
