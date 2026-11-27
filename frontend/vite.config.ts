import { defaultAllowedOrigins, defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The board diagram frame is sandboxed without allow-same-origin, so it loads its scripts as origin "null".
const cors = { origin: [defaultAllowedOrigins, 'null'] }

// https://vite.dev/config/
export default defineConfig({
  // VITE_API_BASE=. is the one-port build: the API serves it (ARP_FRONTEND_DIST) and every URL is
  // relative, so it also works under a path prefix such as Jupyter's /user/<id>/proxy/8000/.
  base: process.env.VITE_API_BASE === '.' ? './' : '/',
  plugins: [react()],
  // board-diagram.html is the Agent board's sandboxed diagram frame (spec agent-board, Amendment 1d).
  build: { rollupOptions: { input: { main: 'index.html', 'board-diagram': 'board-diagram.html' } } },
  server: { cors },
  preview: { cors },
})
