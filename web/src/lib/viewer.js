/* Trình xem tệp đa định dạng, có phóng to / thu nhỏ.
 *
 * MỘT TRÌNH XEM CHO MỌI THỨ
 * ─────────────────────────
 * Trước đây web chỉ dựng được ảnh trang đã render sẵn trong kho — nghĩa là
 * chỉ xem được tệp ĐÃ chạy OCR. Người dùng muốn duyệt cả docx, xlsx, và cả
 * PDF chưa chạy. Module này nhận một đường dẫn và tự quyết cách dựng:
 *
 *   pdf            → pdf.js, dựng ra canvas theo từng trang
 *   ảnh            → thẻ <img>
 *   docx/xlsx/…    → HTML do server dựng (/api/preview)
 *   txt/md         → <pre>
 *
 * PHÓNG TO DÙNG CSS TRANSFORM, KHÔNG DỰNG LẠI
 * ───────────────────────────────────────────
 * Với pdf.js có hai cách phóng: dựng lại canvas ở `scale` mới (nét hơn,
 * nhưng mỗi nấc zoom mất 100-400ms và giật), hoặc `transform: scale()` lên
 * phần tử đã dựng (tức thì, hơi mờ khi phóng rất to).
 *
 * Chọn transform, vì thao tác zoom ở đây là để soi nhanh một vùng rồi thu
 * lại. Riêng khi dừng ở một mức zoom quá 1,5 lần thì dựng lại canvas ở độ
 * phân giải đúng — người dùng đã dừng lại nghĩa là họ đang thực sự đọc.
 */

import { mucKe } from './docbar.js';


export class TrinhXem {
  /**
   * @param {HTMLElement} khung  phần tử chứa
   * @param {object}  tuyChon
   * @param {boolean} tuyChon.hienThanh  dựng thanh công cụ riêng hay không.
   *   Bản NHÚNG ở cột giữa đặt `false`: cột đó đã có thanh tài liệu chung
   *   (đường dẫn + zoom + số trang) và hai thanh chồng nhau thì người dùng
   *   không biết nút nào ăn cái gì.
   * @param {(tt: object) => void} tuyChon.khiDoi  gọi mỗi khi zoom hoặc trang
   *   đổi, để thanh bên ngoài bám theo — kể cả khi zoom bằng Ctrl + lăn chuột.
   */
  constructor(khung, { hienThanh = true, khiDoi = null } = {}) {
    this.khung = khung;
    this.hienThanh = hienThanh;
    this.khiDoi = khiDoi;
    this.zoom = 1;
    this.duongDan = '';
    this.loai = '';
    this.trang = 1;
    this.soTrang = 1;
    this.pdf = null;          // tài liệu pdf.js đang mở
    this._dungLaiTimer = null;
    this._dungKhung();
  }

  /** Trạng thái để thanh điều khiển bên ngoài vẽ lại. */
  trangThai() {
    return { zoom: this.zoom, trang: this.trang, soTrang: this.soTrang };
  }

  _bao() { this.khiDoi?.(this.trangThai()); }

  _dungKhung() {
    this.khung.innerHTML = (this.hienThanh ? `
      <div class="vwBar">
        <button class="vwBtn" data-act="out" title="Thu nhỏ (Ctrl -)">−</button>
        <button class="vwZoom" data-act="reset" title="Trả về 100%">100%</button>
        <button class="vwBtn" data-act="in" title="Phóng to (Ctrl +)">+</button>
        <button class="vwBtn" data-act="fit" title="Vừa bề ngang">⤢</button>
        <span class="vwSep"></span>
        <button class="vwBtn" data-act="prev" title="Trang trước">‹</button>
        <span class="vwPage">1 / 1</span>
        <button class="vwBtn" data-act="next" title="Trang sau">›</button>
        <span class="vwSpacer"></span>
        <span class="vwNote"></span>
      </div>` : '')
      + `<div class="vwScroll"><div class="vwStage"></div></div>`;

    this.bar    = this.khung.querySelector('.vwBar');
    this.scroll = this.khung.querySelector('.vwScroll');
    this.stage  = this.khung.querySelector('.vwStage');
    this.nhanZoom = this.khung.querySelector('.vwZoom');
    this.nhanTrang = this.khung.querySelector('.vwPage');
    this.ghiChu = this.khung.querySelector('.vwNote');

    this.bar?.addEventListener('click', (e) => {
      const act = e.target.closest('[data-act]')?.dataset.act;
      if (!act) return;
      ({
        in:    () => this.datZoom(this._mucKe(+1)),
        out:   () => this.datZoom(this._mucKe(-1)),
        reset: () => this.datZoom(1),
        fit:   () => this.vuaBeNgang(),
        prev:  () => this.doiTrang(this.trang - 1),
        next:  () => this.doiTrang(this.trang + 1),
      })[act]?.();
    });

    // Ctrl/Cmd + lăn chuột = phóng to, đúng thói quen từ mọi trình xem.
    //
    // BA ĐIỀU BẮT BUỘC, thiếu một là hỏng:
    //  * `passive: false` — nếu không, `preventDefault` bị bỏ qua và trình
    //    duyệt phóng to CẢ TRANG thay vì chỉ tài liệu.
    //  * gắn trên cả KHUNG (`this.khung`) chứ không riêng vùng cuộn: khi nội
    //    dung ngắn hơn khung, con trỏ nằm ngoài `.vwScroll` và sự kiện không
    //    bao giờ tới.
    //  * `metaKey` cho macOS — người dùng Mac bấm Cmd chứ không phải Ctrl.
    this.khung.addEventListener('wheel', (e) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      this.datZoom(this._mucKe(e.deltaY < 0 ? +1 : -1));
    }, { passive: false });

  }

  _mucKe(huong) {
    return mucKe(this.zoom, huong);
  }

  /* API chung của một "nguồn" cho `ThanhTaiLieu` — xem docbar.js. */
  phongTo()  { this.datZoom(this._mucKe(+1)); }
  thuNho()   { this.datZoom(this._mucKe(-1)); }
  zoomThat() { this.datZoom(1); }

  datZoom(z) {
    this.zoom = z;
    this.stage.style.transform = `scale(${z})`;
    // `top left` chứ không phải `center`: phóng từ giữa làm nội dung nhảy
    // ra ngoài vùng cuộn và người dùng mất dấu chỗ đang đọc.
    this.stage.style.transformOrigin = 'top left';
    if (this.nhanZoom) this.nhanZoom.textContent = `${Math.round(z * 100)}%`;
    this._bao();

    // Dựng lại ở độ phân giải thật khi người dùng DỪNG ở mức phóng lớn.
    clearTimeout(this._dungLaiTimer);
    if (this.pdf && z > 1.5) {
      this._dungLaiTimer = setTimeout(() => this._veTrangPdf(this.trang, z), 400);
    }
  }

  /**
   * Thu/phóng cho vừa bề ngang vùng cuộn.
   * @param {boolean} chiThu  chỉ THU, không phóng. Dùng khi mở tài liệu: một
   *   trang hẹp bị kéo giãn cho đầy cột sẽ ra chữ to quá khổ.
   */
  vuaBeNgang(chiThu = false) {
    const con = this.stage.firstElementChild;
    if (!con) return;
    const rongCo = this.scroll.clientWidth - 32;
    const rongThat = con.getBoundingClientRect().width / this.zoom;
    if (rongThat <= 0) return;
    const z = Math.min(4, rongCo / rongThat);
    this.datZoom(chiThu ? Math.min(1, z) : z);
  }

  async doiTrang(n) {
    if (!this.pdf) return;
    n = Math.min(this.soTrang, Math.max(1, n));
    if (n === this.trang) return;
    this.trang = n;
    await this._veTrangPdf(n, this.zoom > 1.5 ? this.zoom : 1);
    this._capNhatNhanTrang();
  }

  _capNhatNhanTrang() {
    this._bao();
    if (!this.bar) return;
    this.nhanTrang.textContent = `${this.trang} / ${this.soTrang}`;
    this.bar.querySelectorAll('[data-act="prev"],[data-act="next"],.vwPage')
      .forEach((el) => { el.hidden = this.soTrang <= 1; });
  }

  /** Mở một tệp. `path` là đường dẫn tương đối trong kho hồ sơ. */
  async mo(path, tenHienThi = '') {
    this.duongDan = path;
    this.zoom = 1;
    this.trang = 1;
    this.pdf = null;
    this.stage.style.transform = '';
    this.stage.innerHTML = '<div class="vwLoad">đang mở…</div>';
    if (this.ghiChu) this.ghiChu.textContent = tenHienThi;

    const suf = path.slice(path.lastIndexOf('.')).toLowerCase();
    try {
      if (suf === '.pdf') await this._moPdf(path);
      else if (['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tif', '.tiff']
        .includes(suf)) await this._moAnh(path);
      else await this._moQuaServer(path);
    } catch (e) {
      this.stage.innerHTML =
        `<div class="vwErr">Không mở được:<br><code>${e.message}</code></div>`;
    }
    this._capNhatNhanTrang();
    if (this.nhanZoom) this.nhanZoom.textContent = '100%';
    /* Thu cho vừa cột. Ảnh scan rộng 1275px còn cột giữa chỉ ~700px, nên mở
       ra ở 100% là người dùng thấy một góc trang và phải cuộn ngang mới biết
       mình đang xem gì. `_moAnh` đã chờ ảnh tải xong nên đo được kích thước
       thật ở đây. */
    this.vuaBeNgang(true);
    this._bao();
  }

  _moAnh(path) {
    this.soTrang = 1;
    /* CHỜ ảnh tải xong.
     *
     * `vuaBeNgang` đo `getBoundingClientRect()`; với ảnh chưa tải thì con số
     * đó là 0 và phép thu im lặng không làm gì — đúng kiểu lỗi chỉ hiện ra
     * trên máy chậm hoặc tệp lớn. */
    return new Promise((ok) => {
      const img = new Image();
      img.className = 'vwImg';
      img.onload = img.onerror = () => ok();
      img.src = `/api/raw?path=${encodeURIComponent(path)}`;
      this.stage.innerHTML = '';
      this.stage.appendChild(img);
    });
  }

  async _moPdf(path) {
    // Nạp pdf.js theo yêu cầu (dynamic import): nó nặng ~350KB và phần lớn
    // lượt dùng web này là xem ảnh trang trong kho, không đụng tới PDF.
    const pdfjs = await import('pdfjs-dist');
    pdfjs.GlobalWorkerOptions.workerSrc =
      (await import('pdfjs-dist/build/pdf.worker.min.mjs?url')).default;

    // pdf.js v5 không còn nhận chuỗi URL trần — phải truyền object có
    // khoá `url`. Truyền chuỗi thì nó ném "expected either `data`, `range`,
    // or `url` parameter", và lỗi đó rơi vào catch nên trang chỉ hiện một
    // khung báo lỗi mà không có gì trong console.
    const tai = pdfjs.getDocument({
      url: `/api/raw?path=${encodeURIComponent(path)}`,
    });
    this.pdf = await tai.promise;
    this.soTrang = this.pdf.numPages;
    await this._veTrangPdf(1, 1);
  }

  async _veTrangPdf(n, scale) {
    const page = await this.pdf.getPage(n);
    // Nhân với `devicePixelRatio` để trên màn Retina chữ không bị mờ —
    // canvas 1x phóng lên 2x là đúng kiểu lỗi "nhìn mới thấy".
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const vp = page.getViewport({ scale: scale * dpr });
    const cv = document.createElement('canvas');
    cv.className = 'vwCanvas';
    cv.width = vp.width;
    cv.height = vp.height;
    cv.style.width = `${vp.width / dpr}px`;
    cv.style.height = `${vp.height / dpr}px`;
    await page.render({ canvasContext: cv.getContext('2d'), viewport: vp }).promise;
    this.stage.innerHTML = '';
    this.stage.appendChild(cv);
    // Đã dựng ở độ phân giải mới thì transform phải trả về 1, nếu không
    // hai phép phóng nhân vào nhau.
    if (scale !== 1) {
      this.stage.style.transform = '';
      this.zoom = scale;
      if (this.nhanZoom) this.nhanZoom.textContent = `${Math.round(scale * 100)}%`;
      this._bao();
    }
  }

  async _moQuaServer(path) {
    const r = await fetch(`/api/preview?path=${encodeURIComponent(path)}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    this.soTrang = 1;
    if (d.note && this.ghiChu) this.ghiChu.textContent += `  ·  ${d.note}`;

    if (d.kind === 'html') {
      const box = document.createElement('div');
      box.className = 'vwDoc';
      box.innerHTML = d.html;
      this.stage.innerHTML = '';
      this.stage.appendChild(box);
    } else {
      const pre = document.createElement('pre');
      pre.className = d.kind === 'loi' ? 'vwErr' : 'vwText';
      pre.textContent = d.text || '';
      this.stage.innerHTML = '';
      this.stage.appendChild(pre);
    }
  }
}
