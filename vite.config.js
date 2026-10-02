import { defineConfig } from 'vite';

/* Cấu hình Vite.
 *
 * VÌ SAO CÓ VITE Ở ĐÂY
 * ────────────────────
 * Web này trước đây là ba tệp tĩnh nạp bằng thẻ <script>. Cách đó đủ dùng
 * cho tới khi cần pdf.js: thư viện đó phát hành dạng ES module kèm một tệp
 * worker riêng, không có bản dựng sẵn nào nhét vừa một thẻ script.
 *
 * Vite giải quyết đúng việc đó, và kèm theo hai thứ có giá trị thật:
 *   * nạp theo yêu cầu (`import()` động) — pdf.js 350KB chỉ tải khi mở PDF
 *   * thay nóng khi sửa mã, không phải bấm tải lại
 *
 * HAI CHẾ ĐỘ CHẠY
 * ───────────────
 *   phát triển:  `npm run dev` (cổng 5173) + server Python (cổng 8811)
 *                Vite chuyển tiếp mọi yêu cầu /api tới Python, nên phía
 *                trình duyệt vẫn chỉ thấy MỘT nguồn — không dính CORS.
 *
 *   sử dụng:     `npm run build` → web/dist/, server Python phục vụ thẳng.
 *                Người dùng chỉ cần chạy server Python như trước.
 */
export default defineConfig({
  root: 'web',
  base: '/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // Không băm tên tệp: server Python phục vụ thư mục này bằng danh sách
    // đường dẫn cố định. Băm tên thì mỗi lần dựng lại phải sửa server.
    // Cache đã bị chặn bằng header `no-store` nên băm tên cũng không giúp gì.
    rollupOptions: {
      output: {
        entryFileNames: 'assets/[name].js',
        chunkFileNames: 'assets/[name].js',
        assetFileNames: 'assets/[name][extname]',
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8811', changeOrigin: true },
    },
  },
});
