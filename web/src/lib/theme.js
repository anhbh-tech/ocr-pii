/* Bảng chọn chủ đề.
 *
 * ÁP CHỦ ĐỀ TRƯỚC KHI TRANG VẼ
 * ────────────────────────────
 * `apDungSom()` được gọi bằng một thẻ <script> nội tuyến trong <head>,
 * trước cả khi CSS chính tải xong. Nếu để tới lúc JS ứng dụng chạy mới áp
 * thì người dùng thấy một nháy chủ đề mặc định rồi mới đổi sang chủ đề đã
 * chọn — hiện tượng quen gọi là FOUC. Nháy đó rất khó chịu với chủ đề sáng.
 */

export const CHU_DE = [
  { id: 'slate',   ten: 'Slate',   mo_ta: 'xám xanh trung tính · mặc định', sang: false },
  { id: 'nord',    ten: 'Nord',    mo_ta: 'lạnh, bão hoà thấp · dịu mắt',   sang: false },
  { id: 'gruvbox', ten: 'Gruvbox', mo_ta: 'ấm, ngả nâu · làm việc đêm',     sang: false },
  { id: 'paper',   ten: 'Paper',   mo_ta: 'sáng · cùng tông với giấy scan', sang: true  },
];

const KHOA = 'ocrlab.theme';
const MAC_DINH = 'slate';

export function chuDeHienTai() {
  try {
    const id = localStorage.getItem(KHOA);
    return CHU_DE.some((c) => c.id === id) ? id : MAC_DINH;
  } catch {
    return MAC_DINH;
  }
}

export function datChuDe(id) {
  if (!CHU_DE.some((c) => c.id === id)) id = MAC_DINH;
  document.documentElement.setAttribute('data-theme', id);
  try { localStorage.setItem(KHOA, id); } catch { /* chế độ riêng tư */ }
  // Cho phần còn lại của ứng dụng biết — canvas overlay phải vẽ lại vì
  // nét vẽ lấy màu từ biến CSS tại thời điểm vẽ, không tự cập nhật.
  window.dispatchEvent(new CustomEvent('doi-chu-de', { detail: { id } }));
}

/** Gọi sớm trong <head>. Không phụ thuộc DOM đã dựng xong. */
export function apDungSom() {
  document.documentElement.setAttribute('data-theme', chuDeHienTai());
}

/**
 * Dựng bảng chọn chủ đề dạng thả xuống.
 * @param {HTMLElement} nut  nút bấm để mở bảng
 */
export function ganBangChonChuDe(nut) {
  const bang = document.createElement('div');
  bang.className = 'themePanel';
  bang.hidden = true;
  bang.innerHTML = `
    <div class="themeHead">Giao diện</div>
    <div class="themeList">
      ${CHU_DE.map((c) => `
        <button class="themeItem" data-id="${c.id}">
          <span class="themeSwatch" data-sw="${c.id}">
            <i class="sw-bg"></i><i class="sw-panel"></i><i class="sw-accent"></i>
          </span>
          <span class="themeText">
            <b>${c.ten}</b>
            <small>${c.mo_ta}</small>
          </span>
          <span class="themeTick">✓</span>
        </button>`).join('')}
    </div>`;
  document.body.appendChild(bang);

  const danhDauDangChon = () => {
    const nay = chuDeHienTai();
    bang.querySelectorAll('.themeItem').forEach((b) => {
      b.classList.toggle('on', b.dataset.id === nay);
    });
  };

  const mo = () => {
    // Đặt bảng ngay dưới nút. Tính theo toạ độ thật của nút thay vì đặt
    // cứng, vì nút nằm trong thanh công cụ co giãn theo độ rộng cửa sổ.
    const r = nut.getBoundingClientRect();
    bang.style.top = `${r.bottom + 6}px`;
    // Neo theo cạnh PHẢI: bảng rộng hơn nút, neo trái sẽ tràn ra ngoài
    // màn hình khi nút nằm sát mép phải.
    bang.style.right = `${Math.max(8, window.innerWidth - r.right)}px`;
    danhDauDangChon();
    bang.hidden = false;
    nut.classList.add('on');
  };

  const dong = () => { bang.hidden = true; nut.classList.remove('on'); };

  nut.addEventListener('click', (e) => {
    e.stopPropagation();
    bang.hidden ? mo() : dong();
  });

  bang.addEventListener('click', (e) => {
    const item = e.target.closest('.themeItem');
    if (!item) return;
    datChuDe(item.dataset.id);
    danhDauDangChon();
  });

  // Bấm ra ngoài thì đóng. Dùng `click` ở tầm document — `blur` không chạy
  // vì bảng chứa các nút, bấm vào chúng sẽ khiến nút mở mất focus.
  document.addEventListener('click', (e) => {
    if (!bang.hidden && !bang.contains(e.target) && e.target !== nut) dong();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !bang.hidden) dong();
  });

  return { mo, dong };
}
