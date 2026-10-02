/* Thanh điều khiển tài liệu ở cột giữa: đường dẫn, phóng to, chuyển trang.
 *
 * VÌ SAO LÀ MỘT THANH CHUNG, KHÔNG PHẢI HAI
 * ─────────────────────────────────────────
 * Cột giữa dựng nội dung bằng HAI cơ chế khác nhau:
 *
 *   ảnh trang  #imgWrap + canvas overlay   (tài liệu đã chạy OCR — app.js)
 *   trình xem  lớp TrinhXem                (pdf/docx/xlsx đọc thẳng — viewer.js)
 *
 * Người dùng không quan tâm điều đó: với họ chỉ có "tài liệu đang xem". Nếu
 * mỗi cơ chế mọc một thanh nút riêng thì cùng một cột có lúc hiện thanh này,
 * lúc hiện thanh kia, ở hai vị trí khác nhau — và nút phóng to biến mất đúng
 * lúc cần nhất (khi đang soi ảnh scan).
 *
 * Nên thanh nằm CỐ ĐỊNH trong HTML, còn hai cơ chế kia đăng ký mình làm
 * "nguồn" đang hoạt động. Thanh chỉ biết gọi `nguon.phongTo()`; nó không
 * biết bên dưới là canvas hay là thẻ <img>.
 *
 * 100% LÀ KÍCH THƯỚC THẬT, KHÔNG PHẢI "VỪA KHUNG"
 * ───────────────────────────────────────────────
 * Mọi trình xem tài liệu đều hiểu 100% là một điểm ảnh tài liệu ăn một điểm
 * ảnh màn hình. Mở tài liệu ra thì tự thu cho vừa bề ngang (ảnh scan 1275px
 * rộng hơn cột), nên con số ban đầu thường là 52% hay 68% — đúng sự thật,
 * thay vì ghi 100% cho một thứ đã bị thu nhỏ.
 *
 * Chỉ THU, không bao giờ PHÓNG khi mở: một trang docx hẹp bị kéo giãn cho
 * đầy cột sẽ ra chữ to quá khổ, không ai muốn.
 */

export const MUC_ZOOM = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4];

/* Đường dẫn từ đĩa đi thẳng vào `innerHTML`, và tên tệp là do người dùng
   đặt. Một thư mục tên `<img onerror=…>` không phải chuyện viển vông khi
   công cụ này đọc cả kho hồ sơ khách hàng. */
const esc = (s) => String(s).replace(/[&<>"]/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/** Nấc zoom kế tiếp theo hướng (+1 phóng, -1 thu). */
export function mucKe(zoom, huong) {
  if (huong > 0) return MUC_ZOOM.find((m) => m > zoom + 1e-6) ?? MUC_ZOOM.at(-1);
  return [...MUC_ZOOM].reverse().find((m) => m < zoom - 1e-6) ?? MUC_ZOOM[0];
}

export class ThanhTaiLieu {
  constructor() {
    this.nguon = null;
    this.duongDan = null;   // { goc, rel }  — xem `datDuongDan`

    this.oPath  = document.getElementById('docPath');
    this.oZoom  = document.getElementById('zoomGrp');
    this.oNhan  = document.getElementById('zoomLabel');
    this.oPager = document.getElementById('pager');
    this.oTrang = document.getElementById('pageLabel');

    const bam = (id, fn) =>
      document.getElementById(id)?.addEventListener('click', () => {
        if (this.nguon) fn(this.nguon);
      });

    bam('zoomIn',   (n) => n.phongTo());
    bam('zoomOut',  (n) => n.thuNho());
    bam('zoomLabel', (n) => n.zoomThat());
    bam('zoomFit',  (n) => n.vuaBeNgang());
    bam('prevPage', (n) => n.doiTrang(n.trangThai().trang - 1));
    bam('nextPage', (n) => n.doiTrang(n.trangThai().trang + 1));

    /* Bấm đường dẫn = chép đường dẫn TUYỆT ĐỐI.
       Người soát thường cần mở chính tệp đó bằng công cụ khác (Preview, Word)
       để đối chiếu; không có bước này họ phải tự gõ lại một đường dẫn dài. */
    this.oPath?.addEventListener('click', () => {
      if (!this.duongDan) return;
      const day = (this.goc ? this.goc + '/' : '') + this.duongDan;
      this.chep(day);
    });

    /* Phím tắt quen tay từ mọi trình xem. `metaKey` cho macOS — người dùng
       Mac bấm Cmd, và quên nó là tính năng coi như không tồn tại với họ. */
    document.addEventListener('keydown', (e) => {
      if (!this.nguon || !(e.ctrlKey || e.metaKey)) return;
      /* Bỏ qua khi đang gõ trong ô sửa chunk: Cmd+- ở đó không phải lệnh
         phóng to, và cướp phím của ô nhập là kiểu lỗi làm người dùng mất chữ. */
      if (e.target.closest('textarea, input')) return;
      const f = { '=': 'phongTo', '+': 'phongTo', '-': 'thuNho',
                  '_': 'thuNho', '0': 'zoomThat' }[e.key];
      if (!f) return;
      e.preventDefault();
      this.nguon[f]();
    });
  }

  /** Đặt nguồn đang hoạt động. `null` = không có tài liệu nào. */
  datNguon(nguon) {
    this.nguon = nguon;
    this.ve();
  }

  /**
   * Chép một chuỗi vào bảng nhớ tạm, kèm đường lùi cho ngữ cảnh không an toàn.
   *
   * VÌ SAO KHÔNG DÙNG THẲNG `navigator.clipboard`: trình duyệt chỉ cấp API đó
   * trong "secure context" — HTTPS, hoặc localhost. Trang này phục vụ qua
   * `http://100.101.172.22:8811` (tailnet, không TLS) nên `navigator.clipboard`
   * là `undefined`, và `?.` khiến lệnh chép im lặng không làm gì: nút bấm
   * không phản hồi, không báo lỗi, không có gì trong console.
   *
   * Lỗi này KHÔNG lộ ra khi thử ở `127.0.0.1` — localhost được coi là secure
   * context. Chỉ người dùng thật, qua tailnet, mới gặp.
   *
   * Đường lùi `execCommand('copy')` đã bị khai tử trong tài liệu chuẩn nhưng
   * vẫn chạy ở mọi trình duyệt hiện tại và KHÔNG đòi secure context.
   */
  chep(chuoi) {
    const xong = (ok) => {
      this.oPath?.classList.add(ok ? 'daChep' : 'chepLoi');
      setTimeout(() => this.oPath?.classList.remove('daChep', 'chepLoi'), 1100);
    };

    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(chuoi).then(() => xong(true),
                                                () => xong(this.chepCu(chuoi)));
      return;
    }
    xong(this.chepCu(chuoi));
  }

  /** Đường lùi: ô nhập ẩn + `execCommand`. Trả về true nếu chép được. */
  chepCu(chuoi) {
    const o = document.createElement('textarea');
    o.value = chuoi;
    /* Phải nằm trong luồng hiển thị thì `select()` mới ăn, nên đẩy ra ngoài
       khung nhìn thay vì `display:none`. `readOnly` chặn bàn phím ảo hiện lên
       trên thiết bị cảm ứng. */
    o.setAttribute('readonly', '');
    o.style.cssText = 'position:fixed;top:-9999px;left:-9999px;opacity:0';
    document.body.appendChild(o);
    try {
      o.select();
      o.setSelectionRange(0, chuoi.length);
      return document.execCommand('copy');
    } catch {
      return false;
    } finally {
      o.remove();
    }
  }

  /**
   * Đặt đường dẫn hiện trên thanh.
   *
   * Hiện ĐỦ đường dẫn chứ không chỉ tên tệp: kho này có hàng chục tệp tên
   * `0.pdf`, `1.pdf`, `CCCD.pdf` nằm ở các hồ sơ khác nhau, nên mỗi tên
   * tệp một mình không trả lời được câu hỏi "đang xem tài liệu nào".
   *
   * Thư mục làm nhạt, tên tệp làm đậm — mắt bắt được tên trước, còn đường
   * dẫn vẫn đọc được khi cần. Bấm vào là chép cả đường dẫn tuyệt đối.
   */
  datDuongDan(rel, may) {
    this.duongDan = rel || null;
    const o = this.oPath;
    if (!o) return;
    o.innerHTML = '';
    if (!rel) {
      o.title = 'Chưa chọn tài liệu';
      o.classList.remove('coPath');
      o.innerHTML = '<span class="muted">chưa chọn tài liệu</span>';
      return;
    }

    const phan = rel.split('/');
    const ten = phan.pop();
    o.classList.add('coPath');
    o.title = `${this.goc ? this.goc + '/' : ''}${rel}\n\nBấm để chép đường dẫn`;

    /* Thư mục đi trong MỘT ô co được, tên tệp đứng riêng và không bao giờ co.
       Chia như vậy vì khi cột hẹp lại thì thứ phải mất đi là phần đầu đường
       dẫn, không phải tên tệp — cắt đuôi là mất đúng thông tin người dùng
       nhìn vào thanh này để tìm. `<bdi>` chặn `direction: rtl` (dùng để đẩy
       dấu … về đầu) làm đảo thứ tự các đoạn đường dẫn. */
    if (phan.length) {
      const d = document.createElement('span');
      d.className = 'pthDirs';
      d.innerHTML = `<bdi>${esc(phan.join('/'))}/</bdi>`;
      o.appendChild(d);
    }
    const t = document.createElement('span');
    t.className = 'pthFile';
    t.textContent = ten;
    o.appendChild(t);

    if (may) {
      const m = document.createElement('span');
      m.className = 'pthMay';
      m.textContent = may;
      o.appendChild(m);
    }
  }

  /** Thư mục gốc trên đĩa, để chép ra đường dẫn dùng được ở nơi khác. */
  datGoc(goc) { this.goc = goc; }

  /** Vẽ lại nhãn zoom và bộ chuyển trang theo trạng thái nguồn. */
  ve(tt) {
    const t = tt || this.nguon?.trangThai();
    if (!t) {
      if (this.oZoom) this.oZoom.hidden = true;
      if (this.oPager) this.oPager.hidden = true;
      return;
    }
    if (this.oZoom) this.oZoom.hidden = false;
    if (this.oNhan) this.oNhan.textContent = `${Math.round(t.zoom * 100)}%`;

    const nhieuTrang = t.soTrang > 1;
    if (this.oPager) this.oPager.hidden = !nhieuTrang;
    if (nhieuTrang && this.oTrang) {
      this.oTrang.textContent = `${t.trang} / ${t.soTrang}`;
      const p = document.getElementById('prevPage');
      const n = document.getElementById('nextPage');
      if (p) p.disabled = t.trang <= 1;
      if (n) n.disabled = t.trang >= t.soTrang;
    }
  }
}

/* Một thanh duy nhất cho cả trang.
 *
 * Dùng biến module + hàm gắn thay vì `globalThis`: app.js và main.js đều
 * `import` từ đây, và ràng buộc module là ràng buộc SỐNG — app.js nạp sau
 * vẫn thấy đúng đối tượng main.js vừa tạo, mà không phải bày thêm một biến
 * toàn cục nữa.
 */
export let thanhTaiLieu = null;

export function ganThanhTaiLieu() {
  thanhTaiLieu = new ThanhTaiLieu();
  return thanhTaiLieu;
}
