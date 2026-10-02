/* Thanh kéo chia cột (splitter).
 *
 * VÌ SAO TỰ VIẾT THAY VÌ DÙNG THƯ VIỆN
 * ────────────────────────────────────
 * Việc này chỉ cần ba thứ: bắt chuột kéo, ghi lại chiều rộng, nhớ lần sau.
 * Một thư viện kéo-thả đầy đủ mang theo hàng chục KB cho tình huống ta
 * không có (kéo thả tự do, chạm đa điểm, lồng nhau nhiều cấp).
 *
 * BA CÁI BẪY ĐÃ TÍNH TRƯỚC
 * ────────────────────────
 * 1. Con trỏ chạy ra ngoài thanh kéo khi kéo nhanh. Nếu nghe `mousemove`
 *    trên chính thanh kéo thì cột sẽ "rớt" giữa chừng. Nghe trên `window`.
 *
 * 2. Chữ bị bôi đen trong lúc kéo. Trình duyệt hiểu kéo chuột = chọn chữ.
 *    Đặt `user-select: none` lên <body> trong suốt thao tác.
 *
 * 3. Kéo quá tay làm cột biến mất — đúng lỗi từng gặp với media query ẩn
 *    mất cây hồ sơ. Chặn bằng `min`/`max` cứng: cột không bao giờ hẹp hơn
 *    mức còn đọc được.
 */

/** Chiều rộng cột được phép, tính bằng pixel. */
const GIOI_HAN = {
  tree:  { min: 150, max: 560, mac_dinh: 230 },
  panel: { min: 320, max: 900, mac_dinh: 460 },
};

const KHOA_LUU = 'ocrlab.cot';

/** Đọc chiều rộng đã lưu; hỏng thì trả về mặc định. */
export function docChieuRong() {
  try {
    const luu = JSON.parse(localStorage.getItem(KHOA_LUU) || '{}');
    return {
      tree:  kep('tree',  luu.tree),
      panel: kep('panel', luu.panel),
    };
  } catch {
    return { tree: GIOI_HAN.tree.mac_dinh, panel: GIOI_HAN.panel.mac_dinh };
  }
}

function kep(ten, v) {
  const g = GIOI_HAN[ten];
  if (typeof v !== 'number' || !Number.isFinite(v)) return g.mac_dinh;
  return Math.min(g.max, Math.max(g.min, v));
}

function luuChieuRong(rong) {
  try { localStorage.setItem(KHOA_LUU, JSON.stringify(rong)); } catch { /* chế độ riêng tư */ }
}

/**
 * Gắn hai thanh kéo vào bố cục.
 *
 * @param {HTMLElement} layout  phần tử có `display: grid` ba cột
 * @returns {{dat: (ten: string, px: number) => void}}
 */
export function ganThanhKeo(layout) {
  const rong = docChieuRong();

  const ap = () => {
    layout.style.setProperty('--w-tree',  `${rong.tree}px`);
    layout.style.setProperty('--w-panel', `${rong.panel}px`);
  };
  ap();

  /** @param {'tree'|'panel'} ten */
  const taoThanh = (ten) => {
    const el = document.createElement('div');
    el.className = `splitter splitter-${ten}`;
    el.setAttribute('role', 'separator');
    el.setAttribute('aria-orientation', 'vertical');
    el.title = 'Kéo để đổi độ rộng · nhấp đúp để trả mặc định';

    let dangKeo = false;
    let xDau = 0;
    let rongDau = 0;

    const batDau = (e) => {
      dangKeo = true;
      xDau = e.clientX;
      rongDau = rong[ten];
      // Chặn bôi đen chữ và giữ con trỏ dạng kéo trên TOÀN trang, vì chuột
      // sẽ đi ra ngoài thanh kéo ngay khi người dùng kéo nhanh.
      document.body.classList.add('dang-keo');
      el.classList.add('on');
      e.preventDefault();
    };

    const dangDi = (e) => {
      if (!dangKeo) return;
      // Cột trái nở khi chuột đi SANG PHẢI; cột phải thì ngược lại.
      const delta = ten === 'tree' ? e.clientX - xDau : xDau - e.clientX;
      rong[ten] = kep(ten, rongDau + delta);
      ap();
    };

    const ketThuc = () => {
      if (!dangKeo) return;
      dangKeo = false;
      document.body.classList.remove('dang-keo');
      el.classList.remove('on');
      luuChieuRong(rong);
    };

    el.addEventListener('mousedown', batDau);
    // Nghe trên `window`, KHÔNG phải trên `el`: con trỏ thường xuyên ra
    // ngoài thanh kéo rộng 6px trong lúc kéo.
    window.addEventListener('mousemove', dangDi);
    window.addEventListener('mouseup', ketThuc);
    // Chuột rời khỏi cửa sổ trình duyệt cũng phải kết thúc, nếu không cột
    // sẽ tiếp tục chạy theo khi con trỏ quay lại.
    window.addEventListener('mouseleave', ketThuc);

    el.addEventListener('dblclick', () => {
      rong[ten] = GIOI_HAN[ten].mac_dinh;
      ap();
      luuChieuRong(rong);
    });

    return el;
  };

  return {
    thanhTree:  taoThanh('tree'),
    thanhPanel: taoThanh('panel'),
    dat(ten, px) { rong[ten] = kep(ten, px); ap(); luuChieuRong(rong); },
  };
}
