/* Điểm vào ứng dụng.
 *
 * VÌ SAO GIỮ LẠI app.js CŨ
 * ────────────────────────
 * app.js chứa 955 dòng logic đã qua nhiều vòng sửa lỗi thật: vẽ overlay
 * đúng tỉ lệ, tô diff từng từ, ba engine chạy độc lập, NFC/NFD, chặn tính
 * tiền hai lần. Viết lại toàn bộ theo kiểu module nghe gọn gàng nhưng sẽ
 * làm mất từng đó bài học — mỗi lỗi đã sửa là một dòng ai đó phải tìm lại.
 *
 * Nên tệp này chỉ làm ba việc: dựng thanh kéo cột, gắn bảng chọn chủ đề,
 * gắn trình xem đa định dạng. Rồi nạp app.js như cũ.
 *
 * THỨ TỰ QUAN TRỌNG
 * ─────────────────
 * app.js gán sự kiện cho các phần tử ngay khi nạp, và nó trông chờ DOM đã
 * có sẵn (đó là lý do thẻ script của nó nằm cuối <body>). Các module ở đây
 * CHÈN THÊM phần tử vào DOM, nên phải chạy TRƯỚC app.js — nếu không app.js
 * sẽ không thấy chúng.
 */

// Thứ tự QUAN TRỌNG: theme.css định nghĩa biến, style.css dùng chúng.
// Đảo lại thì các luật đọc biến chưa khai báo và nhận giá trị rỗng.
import './styles/theme.css';
import '../style.css';
import { ganThanhKeo } from './lib/splitter.js';
import { ganBangChonChuDe, apDungSom } from './lib/theme.js';
import { TrinhXem } from './lib/viewer.js';
import { ganThanhTaiLieu } from './lib/docbar.js';

apDungSom();

const layout = document.querySelector('.layout');
const tree   = document.getElementById('tree');
const panel  = document.querySelector('.panel');

// ── Thanh kéo chia cột ───────────────────────────────────────────────────
// Chèn vào giữa các cột. Lưới có 5 rãnh: tree | kéo | viewer | kéo | panel.
if (layout && tree && panel) {
  const { thanhTree, thanhPanel } = ganThanhKeo(layout);
  tree.after(thanhTree);
  panel.before(thanhPanel);
}

// ── Bảng chọn chủ đề ─────────────────────────────────────────────────────
const nutTheme = document.getElementById('btnTheme');
if (nutTheme) ganBangChonChuDe(nutTheme);

// ── Thanh tài liệu (đường dẫn + phóng to) ────────────────────────────────
// Gắn TRƯỚC app.js chạy: app.js gọi `thanhTaiLieu?.datNguon(...)` ngay khi
// mở tài liệu đầu tiên, và nếu thanh chưa tồn tại lúc đó thì lần mở đầu
// không có nút phóng to — đúng kiểu lỗi chỉ hiện ở lần dùng đầu tiên.
const thanhTaiLieu = ganThanhTaiLieu();

// Overlay lấy màu từ biến CSS tại LÚC VẼ, không tự cập nhật khi biến đổi.
// Đổi chủ đề xong phải vẽ lại, nếu không khung chunk giữ màu chủ đề cũ.
window.addEventListener('doi-chu-de', () => {
  window.veLaiOverlay?.();
});

// ── Trình xem đa định dạng ───────────────────────────────────────────────
// Dựng sẵn một khung ẩn. File manager gọi `window.moTrinhXem(path, ten)`
// khi người dùng bấm vào tệp không chạy OCR được (docx, xlsx, …) hoặc bấm
// nút xem trước trên tệp PDF chưa chạy.
const khungXem = document.createElement('div');
khungXem.className = 'vwOverlay';
khungXem.hidden = true;
khungXem.innerHTML = `
  <div class="vwPanel">
    <div class="vwTitle">
      <span class="vwName"></span>
      <button class="vwClose" title="Đóng (Esc)">✕</button>
    </div>
    <div class="vwBody"></div>
  </div>`;
document.body.appendChild(khungXem);

const trinhXem = new TrinhXem(khungXem.querySelector('.vwBody'));
const tenXem = khungXem.querySelector('.vwName');

const dongTrinhXem = () => { khungXem.hidden = true; };

khungXem.querySelector('.vwClose').addEventListener('click', dongTrinhXem);
// Bấm ra ngoài panel thì đóng — nhưng CHỈ khi bấm đúng vào lớp phủ, không
// phải khi bấm bên trong rồi thả chuột ra ngoài lúc kéo thanh cuộn.
khungXem.addEventListener('mousedown', (e) => {
  if (e.target === khungXem) dongTrinhXem();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !khungXem.hidden) dongTrinhXem();
});

window.moTrinhXem = (path, ten) => {
  tenXem.textContent = ten || path.split('/').pop();
  khungXem.hidden = false;
  trinhXem.mo(path, '');
};

// ── Trình xem NHÚNG ở cột giữa ───────────────────────────────────────────
// Cùng lớp `TrinhXem`, chỉ khác chỗ đặt. Dựng lười (lần gọi đầu mới tạo) để
// không tốn gì cho phiên chỉ xem tài liệu đã OCR.
let xemNhung = null;
window.moTrinhXemInline = (path, ten) => {
  const khung = document.getElementById('inlineViewer');
  if (!khung) return;
  /* `hienThanh: false` — thanh phóng to nằm trên `.docBar` dùng chung, và
     trình xem chỉ báo trạng thái lên. Bản nhúng tự dựng thanh riêng thì cột
     giữa có HAI ô phần trăm cạnh nhau, chúng lệch nhau khi dùng phím tắt, và
     người dùng không biết tin ô nào. */
  if (!xemNhung) xemNhung = new TrinhXem(khung, { hienThanh: false });
  khung.hidden = false;
  thanhTaiLieu.datNguon(xemNhung);
  xemNhung.mo(path, ten);
};
window.anTrinhXemInline = () => {
  const khung = document.getElementById('inlineViewer');
  if (khung) khung.hidden = true;
};

// ── Tự nhận bản mới ──────────────────────────────────────────────────────
// `no-store` chỉ áp cho lần TẢI SAU. Một tab mở từ trước giữ nguyên HTML và
// JS trong bộ nhớ, nên người dùng báo "tính năng không có" trong khi nó đã
// chạy trên đĩa — đã xảy ra thật hai lần và mất cả hai lượt để chẩn đoán.
//
// Hỏi dấu vân tay mỗi 30 giây; lệch thì báo và tự tải lại.
(() => {
  let vanTayGoc = null;
  const kiem = async () => {
    try {
      const r = await fetch('/api/version', { cache: 'no-store' });
      if (!r.ok) return;
      const d = await r.json();
      /* Gốc kho hồ sơ: chỉ server biết, mà thanh tài liệu cần để hiện đường
         dẫn TUYỆT ĐỐI. Lấy ở đây thay vì thêm một endpoint nữa — lần hỏi đầu
         tiên đã chạy sẵn lúc trang mở. */
      if (d.goc) thanhTaiLieu.datGoc(d.goc);

      if (vanTayGoc === null) { vanTayGoc = d.van_tay; return; }
      if (d.van_tay !== vanTayGoc) {
        console.info('[ocr-lab] có bản mới — đang tải lại');
        location.reload();
      }
    } catch { /* server tắt giữa chừng: im lặng, lần sau hỏi lại */ }
  };
  kiem();
  setInterval(kiem, 30000);
})();

// ── Nạp logic ứng dụng ───────────────────────────────────────────────────
// Sau cùng, vì app.js gán sự kiện ngay khi nạp và cần thấy mọi phần tử
// mà các module trên vừa chèn vào.
import('/app.js').then(async () => {
  const { kiemTraCauNoi } = await import('./lib/bridge.js');
  kiemTraCauNoi();
});
