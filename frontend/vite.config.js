import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import frappeui from 'frappe-ui/vite'
import path from 'path'

// Paths are explicit (relative to this folder) so the build works whatever the
// repository folder is called, e.g. when `bench get-app` clones "timetable-generator".
export default defineConfig({
  plugins: [
    frappeui({
      frontendRoute: '/timetable',
      buildConfig: {
        outDir: path.resolve(__dirname, '../timetable_app/public/frontend'),
        indexHtmlPath: path.resolve(__dirname, '../timetable_app/www/timetable.html'),
        baseUrl: '/assets/timetable_app/frontend/',
      },
    }),
    vue(),
  ],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
})
