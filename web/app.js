/* Đối chiếu ADE — vẽ overlay và đồng bộ chọn giữa ảnh và bản chép.
 *
 * HAI MỨC NEO, ĐỪNG TRỘN
 * ──────────────────────
 *   chunk  element.grounding.box        cả một phần tử (mặt thẻ, đoạn văn)
 *   span   element.atomic_grounding[]   từng dòng (từng từ trên vài model)
 *
 * TOẠ ĐỘ LÀ PHÂN SỐ [0,1], KHÔNG PHẢI PIXEL
 * ─────────────────────────────────────────
 * Nhân với kích thước canvas ĐANG hiển thị. Các trường width/height/dpi trên
 * node trang đã bị API bỏ, nên kích thước thật lấy từ meta.pages do pipeline
 * ghi lúc render.
 *
 * CÂY `grounding` CẤP CAO NHẤT LÀ BẢN CŨ VÀ DÙNG ĐƠN VỊ PIXEL — không đọc.
 */

'use strict';

import { mucKe, thanhTaiLieu } from './src/lib/docbar.js';
import { SENSITIVITY, xuLy, timPII, NHAN } from './src/lib/pii.js';

/* Lấy phần tử theo id.
 *
 * Báo ra console khi không tìm thấy thay vì trả `null` lặng lẽ: gán
 * `.onclick` lên `null` ném TypeError, và một TypeError ở tầm module giết
 * TOÀN BỘ phần script sau nó — trang hiện ra khung trắng không rõ vì sao.
 *
 * Đã xảy ra thật: thẻ `<script>` nằm phía trên lớp phủ file manager trong
 * HTML, nên `$('btnBrowse')` chạy lúc phần tử chưa được phân tích.
 */
const $ = (id) => {
  const el = document.getElementById(id);
  if (!el) console.error(`[ocr-lab] không có phần tử #${id}`);
  return el;
};

/* Gán sự kiện an toàn: thiếu một phần tử thì mất đúng chức năng đó, không
   kéo sập phần còn lại của trang. */
const on = (id, ev, fn) => {
  const el = $(id);
  if (el) el.addEventListener(ev, fn);
};

const state = {
  docId: null,
  meta: null,
  parse: null,
  _markdown: '',
  mdCP: [],            // mảng CODE POINT của _markdown — xem `catMd`
  chunks: [],          // phẳng hoá từ structure, theo thứ tự đọc
  page: 1,
  preview: null,       // docx/xlsx: HTML dựng từ tệp gốc (không có ảnh trang)
  sel: null,           // index chunk đang chọn
  selSpan: null,       // {chunk, seg} span đang trỏ
  view: 'md',          // 'md' | 'json'
  layers: { chunk: true, span: true },
  /* Bật thì mọi vùng nhạy cảm được tô theo cách xử lý (bút danh/ẩn danh).
     Mặc định TẮT: soát chính tả là việc thường ngày, còn soát PII là việc
     có chủ đích — bật sẵn thì màu che mất lỗi OCR cần tìm. */
  piiOn: false,
  /* Lớp CHE (pii-core quyết, box ADE Pro định vị — `src/ocr_lab/che.py`).
     Khác lớp "nhạy cảm" ở trên: đó tô CHỮ theo bảng cũ `pii.js`, còn đây vẽ
     lên ẢNH TRANG đúng những ô đen mà PDF che sẽ có. */
  cheOn: false,
  cheXuyen: false,     // nhìn xuyên ô đen để soát nó có che trúng chữ không
  che: null,           // {vung, dem, pii_core, truong, khong_dinh_vi, co_pdf, ly_do} của docId đang mở
  /* Lớp TRƯỜNG: mọi field pii-core thấy (kể cả KEEP), tô màu theo hành động
     — để soát cái gì bị bí danh hoá / ẩn danh hoá / giữ. `?lop=truong` bật sẵn. */
  truongOn: new URLSearchParams(location.search).get('lop') === 'truong',
  truong: null,        // {vung, dem, theo_hang_muc, truong, khong_dinh_vi, ly_do}
  verdicts: {},
  /* Bản sửa chính tả theo chunk_id: { original, corrected, changed }.
     Rỗng khi chưa chạy `make correct-write`. */
  corrected: {},
  /* Engine đang xem: 'ade' | 'vision'. Đổi engine dựng lại state.chunks từ
     nguồn khác — cùng ảnh trang, cùng toạ độ, chỉ khác cách đọc. */
  engine: 'ade',          // 'ade' | 'vision' | 'pro'
  visionRaw: null,
  proRaw: null,
  /* Hiện bản sửa hay bản thô. Mặc định HIỆN BẢN SỬA, vì đó là thứ sẽ dùng
     về sau; nút "# Raw" luôn cho xem lại bản ADE trả về nguyên văn. */
};

/* `state.markdown` là accessor, không phải ô dữ liệu thường.
 *
 * Có BỐN chỗ gán `state.markdown` (mở tài liệu, đổi engine, đọc tệp cục bộ,
 * chạy xong OCR). Nếu mảng code point phải dựng bằng tay thì chỉ cần một
 * chỗ quên là toàn bộ chunk của đường đi đó cắt bằng cache CŨ — sai âm thầm,
 * đúng loại lỗi vừa mất một buổi để truy. Buộc hai thứ đi cùng nhau ở đây
 * thì không có chỗ nào quên được nữa.
 */
Object.defineProperty(state, 'markdown', {
  get() { return this._markdown; },
  set(v) {
    this._markdown = v || '';
    this.mdCP = [...this._markdown];
  },
});

/* Màu theo `type`. `type` là chuỗi MỞ, không phải enum: dữ liệu thật trả về
 * card / text / attestation, còn SDK chỉ ghi cứng mỗi `table`. Type lạ PHẢI
 * rơi vào màu mặc định chứ không được thành `undefined`. */
const TYPE_COLOR = {
  card:        '#e8590c',
  text:        '#4c6ef5',
  attestation: '#0ca678',
  table:       '#9c36b5',
  table_cell:  '#ae3ec9',
  figure:      '#f08c00',
};
const DEFAULT_COLOR = '#868e96';
const colorFor = (t) => TYPE_COLOR[t] || DEFAULT_COLOR;

const PLACEHOLDER_RE = /\[[A-Z_]+\]|\[[a-z ]+image\]/g;

/* ── nạp cây hồ sơ ─────────────────────────────────────────────────────
 *
 * Chia theo LOẠI TÀI LIỆU trước, hồ sơ sau. Trước đây cây chỉ có một cấp
 * hồ sơ, nên 439 tài liệu nằm lẫn lộn: muốn soát riêng tệp scan — nhóm sai
 * nhiều nhất vì phải OCR — thì phải mở từng hồ sơ một mà dò.
 *
 * Mỗi section gấp/mở được và nhớ trạng thái: mở hết 6 section cùng lúc là
 * một danh sách dài 439 dòng, cuộn mỏi tay hơn là hữu ích.
 */
const SECTION_MO = 'ocrlab.sectionMo';

function _sectionDangMo() {
  try { return new Set(JSON.parse(localStorage.getItem(SECTION_MO) || '[]')); }
  catch { return new Set(); }
}

async function loadTree() {
  const data = await (await fetch('/api/tree')).json();
  const box = $('treeBody');

  const secs = data.sections || [];
  if (!secs.length) {
    box.innerHTML = '<div class="pad muted">Kho trống.<br>Chạy '
      + '<code>batch_toan_kho.py</code> trước.</div>';
    return;
  }

  // Mặc định mở section đầu (PDF scan) — nhóm đáng soát nhất. Mở hết thì
  // dài quá, đóng hết thì người dùng phải bấm mới thấy gì.
  const mo = localStorage.getItem(SECTION_MO) === null
    ? new Set([secs[0].key]) : _sectionDangMo();

  box.classList.remove('muted');
  box.innerHTML = '';

  for (const s of secs) {
    const dangMo = mo.has(s.key);

    const head = document.createElement('button');
    head.className = 'secHead' + (dangMo ? ' open' : '');
    head.dataset.sec = s.key;
    head.innerHTML = `<span class="secCaret">${dangMo ? '▾' : '▸'}</span>`
      + `<span class="secName">${s.label}</span>`
      + `<span class="secCount">${s.n_docs}</span>`;
    box.appendChild(head);

    const than = document.createElement('div');
    than.className = 'secBody';
    than.dataset.sec = s.key;
    if (!dangMo) than.hidden = true;
    box.appendChild(than);

    for (const m of s.matters) {
      const h = document.createElement('div');
      h.className = 'matter';
      h.textContent = m.name;
      than.appendChild(h);

      for (const d of m.docs) {
        const b = document.createElement('button');
        b.className = 'docItem';
        b.textContent = d.name;
        b.title = d.source;
        b.dataset.docId = d.doc_id;
        b.onclick = () => loadDoc(d.doc_id);
        than.appendChild(b);
      }
    }

    head.onclick = () => {
      const dang = !than.hidden;
      than.hidden = dang;
      head.classList.toggle('open', !dang);
      head.querySelector('.secCaret').textContent = dang ? '▸' : '▾';
      const t = _sectionDangMo();
      // Lần đầu chưa có gì trong localStorage: phải gieo bằng trạng thái
      // ĐANG hiện, nếu không mọi section khác bị coi như đóng và nhảy hết.
      if (localStorage.getItem(SECTION_MO) === null) {
        for (const x of secs) if (x.key === secs[0].key) t.add(x.key);
      }
      if (dang) t.delete(s.key); else t.add(s.key);
      localStorage.setItem(SECTION_MO, JSON.stringify([...t]));
    };
  }
}


/* ── mở một tệp BẤT KỲ trên màn hình chính, không cần OCR ──────────────
 *
 * Trước đây tệp không chạy OCR được chỉ xem được trong một lớp phủ riêng:
 * có chữ nhưng không có tab Markdown/JSON, không có danh sách chunk, không
 * neo được vị trí. Tức là hai trình đọc cho hai loại tệp, và loại thứ hai
 * kém hẳn.
 *
 * Nay chỉ còn MỘT. Server trả về đúng khuôn ADE (`markdown` + `structure` +
 * `grounding`) nên mọi thứ dưới đây là đường đi sẵn có, không phải nhánh
 * riêng: `chunksFor` phẳng hoá, `renderChunks` dựng, `selectChunk` tô sáng.
 */
async function openLocalFile(path, ten) {
  const r = await fetch(`/api/extract?path=${encodeURIComponent(path)}`);
  if (!r.ok) {
    const msg = r.status === 415 ? 'chưa đọc được định dạng này'
                                 : `lỗi HTTP ${r.status}`;
    $('chunks').innerHTML = `<div class="muted pad">${msg}</div>`;
    return;
  }
  const d = await r.json();

  /* Xoá sạch trạng thái của tài liệu TRƯỚC. Thiếu bước này thì nút engine
   * cũ vẫn sáng và bấm vào sẽ dựng chunk từ dữ liệu của tệp khác — sai âm
   * thầm, kiểu tệ nhất. */
  state.docId = null;
  state.parseRaw = null;
  state.visionRaw = null;
  state.proRaw = null;
  state.corrected = {};
  state.verdicts = {};

  state.localRaw = d;
  state.meta = d.meta;
  state.markdown = d.markdown || '';
  setEngineButtons('local');
  state.chunks = chunksFor('local');
  markEngineAvailability();
  state.page = 1;
  state.sel = null;
  state.selSpan = null;

  document.querySelectorAll('.docItem').forEach((e) => e.classList.remove('on'));
  thanhTaiLieu?.datDuongDan(path, d.meta.engine || '');

  /* PDF scan không có lớp text: nói thẳng và mời chạy OCR, thay vì hiện một
   * danh sách rỗng trông như công cụ hỏng. */
  if (d.meta.can_ocr) {
    $('chunks').innerHTML =
      `<div class="muted pad">Tệp này không có lớp chữ (${d.meta.so_trang} trang, `
      + `${d.meta.ky_tu} ký tự) — là bản scan.<br>`
      + `Mở <b>📁 Duyệt tệp</b> rồi bấm một chấm engine để chạy OCR.</div>`;
  } else {
    renderChunks();
  }

  /* Dựng bản xem trước ở cột giữa bằng CHÍNH trình xem đa định dạng — có
   * phóng to thu nhỏ, và không phải một bản dựng thứ hai. */
  showLocalPreview(path, ten || d.meta.name);

  if (!d.meta.can_ocr && state.chunks.length) selectChunk(0, false);
}

/* Đặt trình xem vào cột giữa (thay vì lớp phủ), để đọc tệp và soi nội dung
 * trích ra là MỘT thao tác chứ không phải hai cửa sổ chồng nhau. */
function showLocalPreview(path, ten) {
  $('placeholder').hidden = true;
  $('imgWrap').hidden = true;
  window.moTrinhXemInline?.(path, ten);
}

/* ── nạp một tài liệu ────────────────────────────────────────────────── */
async function loadDoc(docId) {
  const data = await (await fetch(`/api/doc/${docId}`)).json();

  state.docId = docId;
  state.meta = data.meta;
  state.parse = data.parse;
  // Có mặt với docx/xlsx: HTML dựng từ tệp gốc, thay cho ảnh trang.
  state.preview = data.preview || null;
  state.markdown = data.parse.markdown || '';
  state.verdicts = data.verdicts || {};
  /* Đánh chỉ mục theo chunk_id để tra O(1) khi dựng từng thẻ. */
  state.corrected = {};
  for (const c of (data.corrected?.chunks || [])) {
    if (c.original !== c.corrected) state.corrected[c.chunk_id] = c;
  }
  state.parseRaw = data.parse;
  state.visionRaw = data.vision || null;
  state.proRaw = data.parse_pro || null;
  /* Tự chuyển sang engine CÓ dữ liệu cho tài liệu này.
   *
   * Tài liệu chạy bằng Vision mà đang đứng ở tab ADE Verity thì mở ra trống
   * trơn, và người dùng vừa chạy xong nên tin là mình làm sai. Chuyển tab
   * thay vì bắt họ đoán. */
  const co = { ade: !!data.parse?.structure, pro: !!data.parse_pro,
               vision: !!data.vision };
  if (!co[state.engine]) {
    const sang = ['ade', 'pro', 'vision'].find((k) => co[k]);
    if (sang) setEngineButtons(sang);
  }
  state.chunks = chunksFor(state.engine);
  markEngineAvailability();
  state.page = 1;
  state.sel = null;
  state.selSpan = null;

  document.querySelectorAll('.docItem').forEach(
    (e) => e.classList.toggle('on', e.dataset.docId === docId));

  /* Ẩn trình xem nhúng: nó còn mở từ lượt xem tệp trước và sẽ che ảnh trang. */
  window.anTrinhXemInline?.();
  state.localRaw = null;

  renderCrumb();
  renderFiles();
  renderChunks();
  showPage(1);
  /* Dữ liệu che là của TÀI LIỆU CŨ: giữ lại thì ô đen của tệp trước nằm
     lên trang tệp mới, đúng kiểu lệch mà người soát không nhận ra. */
  state.che = null;
  if (state.cheOn) taiChe(); else document.getElementById('chePanel')?.remove();
  state.truong = null;
  if (state.truongOn) taiTruong(); else document.getElementById('truongPanel')?.remove();

  /* Chọn sẵn chunk đầu. Không có bước này thì lần mở tài liệu nào cũng ra một
   * trang ảnh trơn không khung nào — người dùng phải đoán rằng mình cần bấm
   * vào đâu đó trước. Overlay là lý do công cụ này tồn tại, nên nó phải hiện
   * ngay. */
  if (state.chunks.length) selectChunk(0, false);
}

/* Phẳng hoá `structure` thành danh sách chunk theo thứ tự đọc.
 * Mỗi chunk giữ nguyên node gốc để cột JSON hiện được đúng dữ liệu thật. */
/* Dựng danh sách phần tử từ `vision.json`.
 *
 * Vision và ADE chia phần tử theo hai cách KHÁC HẲN nhau, và đó chính là thứ
 * cần so:
 *
 *   ADE    → phần tử ngữ nghĩa (card, text, attestation), mỗi cái gom nhiều
 *            dòng, kèm `atomic_grounding` cho từng dòng bên trong.
 *   Vision → từng DÒNG rời, mỗi dòng một khung bao, không có khái niệm phần
 *            tử ngữ nghĩa.
 *
 * Không ép Vision về khuôn của ADE (gom dòng thành "đoạn" theo khoảng cách):
 * gom là đã áp một cách diễn giải, và người soát sẽ nhìn kết quả của phép gom
 * đó mà tưởng là năng lực Vision. Hiện đúng cái engine trả về.
 *
 * Toạ độ: Vision trả `bbox_topleft` = [x, y, w, h] tính bằng ĐIỂM ẢNH, còn
 * ADE trả phân số [0,1] dạng {xmin,ymin,xmax,ymax}. Quy về khuôn của ADE ở
 * đây để lớp vẽ overlay dùng chung một phép biến đổi — chỗ này mà sai thì
 * khung vẽ lệch, và nó lệch ÂM THẦM.
 */
/* Nguồn chunk theo engine đang chọn.
 *
 * Mỗi engine có `markdown` riêng, nên `state.markdown` cũng phải đổi theo —
 * `catMd` cắt theo offset, và cắt bản Verity bằng offset của bản Pro sẽ ra
 * chữ lệch mà KHÔNG báo lỗi. Đây là chỗ dễ sai nhất khi có nhiều engine.
 */
function chunksFor(name) {
  if (name === 'vision') {
    return state.visionRaw ? collectVisionChunks(state.visionRaw) : [];
  }
  /* Engine 'local' đọc thẳng từ tệp (không OCR, không tốn tiền) và trả về
   * ĐÚNG khuôn ADE, nên đi qua chính `collectChunks` — không có nhánh dựng
   * riêng nào cho nó. Đó là lý do khuôn chung đáng giá. */
  const raw = name === 'local' ? state.localRaw
            : name === 'pro' ? state.proRaw : state.parseRaw;
  if (!raw) return [];
  state.markdown = raw.markdown || '';
  return collectChunks(raw.structure);
}

/* Làm mờ nút của engine chưa có dữ liệu cho tài liệu này.
 *
 * Không ẩn hẳn: ẩn thì người dùng tưởng engine đó không tồn tại, còn làm mờ
 * nói đúng sự thật — "có engine này, tài liệu này chưa chạy". */
function markEngineAvailability() {
  const có = { local: !!state.localRaw, ade: !!state.parseRaw,
               vision: !!state.visionRaw, pro: !!state.proRaw };
  for (const [k, id] of [['local','engLocal'], ['ade','engAde'],
                         ['vision','engVision'], ['pro','engPro']]) {
    const b = document.getElementById(id);
    if (b) { b.classList.toggle('missing', !có[k]); b.disabled = !có[k]; }
  }
}

function collectVisionChunks(vis) {
  const out = [];
  for (const pg of vis.pages || []) {
    for (const ln of pg.lines || []) {
      const [x, y, w, h] = ln.bbox_topleft;
      out.push({
        i: out.length,
        id: `vis-${out.length}`,
        type: 'line',
        page: pg.page,
        box: {
          xmin: x / pg.width,  ymin: y / pg.height,
          xmax: (x + w) / pg.width, ymax: (y + h) / pg.height,
        },
        range: null,
        atomic: [],
        text: ln.text,
        conf: ln.confidence,
        node: ln,
      });
    }
  }
  return out;
}

function collectChunks(structure) {
  const out = [];
  if (!structure) return out;

  const walk = (node, page) => {
    const g = node.grounding || {};
    const pg = g.page || page || 1;
    /* Nhận CẢ HAI kiểu neo:
     *   box   — toạ độ [0,1], vẽ khung lên ảnh trang (ADE, Vision, PDF)
     *   path  — đường dẫn cấu trúc "p:12" / "Sheet1!B7" (docx, xlsx, text)
     * Trước đây chỉ nhận `box`, nên tệp docx trích ra 1.737 ký tự markdown
     * mà danh sách chunk rỗng — nhìn y hệt một tệp không đọc được. */
    if (g.box || g.path) {
      out.push({
        i: out.length,
        id: node.id || `el${out.length}`,
        type: node.type || 'unknown',
        page: pg,
        box: g.box || null,
        path: g.path || null,
        kind: g.kind || (g.box ? 'box' : 'path'),
        range: g.range || null,
        atomic: node.atomic_grounding || [],
        node,
      });
    }
    for (const c of node.children || []) walk(c, pg);
  };

  for (const page of structure.children || []) {
    const pg = (page.grounding || {}).page || page.page || 1;
    for (const el of page.children || []) walk(el, pg);
  }
  return out;
}

function renderCrumb() {
  /* Đường dẫn TƯƠNG ĐỐI so với kho hồ sơ — thanh tài liệu tự ghép gốc vào.
     `meta.source` đã là dạng đó, dùng nguyên chứ không cắt lấy tên tệp: cắt
     đi thì hai tệp trùng tên ở hai hồ sơ khác nhau nhìn y hệt nhau. */
  thanhTaiLieu?.datDuongDan(state.meta.source || '', state.meta.engine || '');

  $('modelTag').textContent = state.meta.model || '';
  const c = state.meta.credits;
  $('creditInfo').textContent =
    c == null ? '' : `Lần chạy · ${c} credits ≈ $${(c * 0.01).toFixed(3)}`;
}

/* ── tài liệu KHÔNG phân trang (docx, xlsx) ──────────────────────────── */
/**
 * Dựng docx/xlsx bằng HTML server trả về, thay cho ảnh trang.
 *
 * Không có toạ độ để vẽ khung, nên cũng không có overlay — neo của chúng là
 * `grounding.kind = "path"` (`đoạn 12`, `Sheet1!B7`). Vẽ khung ước lượng lên
 * HTML sẽ ra những ô trông như thật mà lệch, đúng kiểu sai người soát không
 * phát hiện được.
 */
function showPreviewDoc(pv) {
  $('placeholder').hidden = true;
  $('imgWrap').hidden = true;

  const box = $('docHtml');
  box.hidden = false;
  box.innerHTML = '';

  if (pv.html) {
    box.innerHTML = pv.html;
  } else if (pv.text) {
    const pre = document.createElement('pre');
    pre.className = 'docText';
    pre.textContent = pv.text;
    box.appendChild(pre);
  } else {
    box.innerHTML = `<div class="pad muted">Không đọc được nội dung.`
      + `${pv.note ? '<br>' + pv.note : ''}</div>`;
  }
  thanhTaiLieu?.datNguon(nguonHtml);
  nguonHtml.datZoom(1);
}

/* Nguồn phóng to cho docx/xlsx dựng bằng HTML.
 *
 * Ở đây phóng to là đổi CỠ CHỮ GỐC chứ không phải `scale()`: nội dung HTML
 * tự xuống dòng, nên tăng cỡ chữ thì đoạn văn giãn ra vừa bề ngang cột và
 * không sinh thanh cuộn ngang. `scale()` thì ngược lại — chữ to ra nhưng
 * dòng vẫn dài đúng bằng cũ, và người dùng phải kéo ngang từng dòng một.
 */
const nguonHtml = {
  zoom: 1,
  trangThai() { return { zoom: this.zoom, trang: 1, soTrang: 1 }; },
  datZoom(z) {
    this.zoom = Math.min(4, Math.max(0.25, z));
    // 15px là cỡ chữ gốc của `.docHtml` trong style.css.
    $('docHtml').style.fontSize = `${(15 * this.zoom).toFixed(2)}px`;
    thanhTaiLieu?.ve(this.trangThai());
  },
  phongTo()  { this.datZoom(mucKe(this.zoom, +1)); },
  thuNho()   { this.datZoom(mucKe(this.zoom, -1)); },
  zoomThat() { this.datZoom(1); },
  vuaBeNgang() { this.datZoom(1); },   // HTML đã tự vừa bề ngang sẵn
  doiTrang() {},
};

/* ── ảnh trang + overlay ─────────────────────────────────────────────── */

/* Nguồn phóng to cho ẢNH TRANG đã render (tài liệu đã chạy OCR).
 *
 * Đây là nửa còn lại của thanh tài liệu: lớp `TrinhXem` lo pdf/docx đọc
 * thẳng, còn lớp này lo ảnh trang + canvas overlay. Cả hai cùng một API
 * (`phongTo`, `thuNho`, `zoomThat`, `vuaBeNgang`, `doiTrang`, `trangThai`)
 * nên thanh điều khiển không cần biết đang xem loại nào.
 *
 * PHÓNG BẰNG CHIỀU RỘNG, KHÔNG PHẢI `transform: scale()`
 * ──────────────────────────────────────────────────────
 * `transform` không làm đổi kích thước bố cục, nên phóng to xong phần tràn
 * ra ngoài KHÔNG cuộn tới được — ảnh bị cắt mất một mảng và người dùng
 * tưởng trang lỗi. Đặt chiều rộng thật thì vùng cuộn tự dài ra.
 *
 * Canvas overlay `inset: 0; width/height: 100%` nên nó bám theo miễn phí;
 * chỉ cần vẽ lại để nét khung dày đúng ở tỉ lệ mới.
 */
const nguonAnhTrang = {
  zoom: 1,

  _anh() { return document.getElementById('pageImg'); },

  trangThai() {
    return {
      zoom: this.zoom,
      trang: state.page,
      soTrang: (state.meta?.pages || []).length || 1,
    };
  },

  datZoom(z) {
    const img = this._anh();
    const wrap = document.getElementById('imgWrap');
    if (!img || !img.naturalWidth || !wrap) return;
    this.zoom = Math.min(4, Math.max(0.25, z));
    wrap.style.width = `${Math.round(img.naturalWidth * this.zoom)}px`;
    /* Nét khung tính từ bề rộng ĐANG hiển thị, nên đổi cỡ là phải vẽ lại —
       không thì khung mảnh dần cho tới lúc gần như vô hình. */
    drawOverlay();
    thanhTaiLieu?.ve(this.trangThai());
  },

  phongTo()  { this.datZoom(mucKe(this.zoom, +1)); },
  thuNho()   { this.datZoom(mucKe(this.zoom, -1)); },
  zoomThat() { this.datZoom(1); },

  /** @param {boolean} chiThu chỉ thu nhỏ, không phóng — dùng khi mở trang. */
  vuaBeNgang(chiThu = false) {
    const img = this._anh();
    const stage = document.getElementById('stage');
    if (!img || !img.naturalWidth || !stage) return;
    const co = stage.clientWidth - 40;          // 20px padding mỗi bên
    const z = co / img.naturalWidth;
    this.datZoom(chiThu ? Math.min(1, z) : z);
  },

  doiTrang(n) { showPage(n); },
};

function showPage(n) {
  // docx/xlsx: server gửi kèm `preview` vì chúng KHÔNG có ảnh trang nào.
  // Không dùng `pages.length === 0` làm dấu hiệu — lô chạy vẫn ghi
  // `meta.pages = [{page: 1}]` cho docx để báo cáo đếm được, nên điều kiện
  // đó không bao giờ đúng trong khi ảnh trang vẫn không tồn tại.
  if (state.preview) { showPreviewDoc(state.preview); return; }

  const pages = state.meta.pages || [];
  if (!pages.length) return;
  $('docHtml').hidden = true;
  state.page = Math.min(Math.max(1, n), pages.length);

  $('placeholder').hidden = true;
  $('imgWrap').hidden = false;

  const img = $('pageImg');
  const doiTep = img.src.indexOf(`/doc/${state.docId}/`) < 0;
  img.onload = () => {
    drawOverlay();
    /* Chỉ tự thu khi ĐỔI tài liệu. Lật trang trong cùng tài liệu mà cũng
       thu lại là xoá mất mức phóng người dùng vừa chọn để đọc chữ nhỏ. */
    if (doiTep) nguonAnhTrang.vuaBeNgang(true);
    else nguonAnhTrang.datZoom(nguonAnhTrang.zoom);
  };
  img.src = `/api/doc/${state.docId}/page/${state.page}`;

  thanhTaiLieu?.datNguon(nguonAnhTrang);
  if (state.cheOn && state.che) dungBangChe();   // "trang này N" đổi theo trang
  if (state.truongOn && state.truong) dungBangTruong();
  document.querySelectorAll('.thumb').forEach(
    (e, i) => e.classList.toggle('on', i + 1 === state.page));
}

/**
 * Giữ chuột trái rồi kéo để di chuyển trang, như mọi trình xem ảnh/PDF.
 *
 * GẮN VÀO `.stage`, KHÔNG PHẢI `.vwScroll`.
 * Tài liệu ĐÃ OCR hiện qua `#imgWrap` (ảnh trang + canvas lớp phủ) và vùng
 * cuộn của nó là `.stage`. `#inlineViewer`/`.vwScroll` chỉ dùng cho tệp CHƯA
 * OCR mở từ cây thư mục. Gắn nhầm vào `.vwScroll` thì kéo không có tác dụng
 * trên đúng màn hình người dùng làm việc nhiều nhất.
 *
 * KHÔNG ĐƯỢC CƯỚP THAO TÁC CHỌN CHUNK. Bấm vào canvas lớp phủ là cách chọn
 * vùng trên trang — chức năng chính của công cụ. Nên chỉ coi là kéo khi con
 * trỏ đã đi quá ngưỡng rung tay; bấm gọn vẫn rơi xuống trình xử lý chọn.
 */
function ganKeoDiChuyen() {
  const khung = document.getElementById('stage');
  if (!khung || khung._daGanKeo) return;
  khung._daGanKeo = true;

  let dang = false, x0 = 0, y0 = 0, tr0 = 0, du0 = 0, daDiChuyen = false;

  khung.addEventListener('pointerdown', (e) => {
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.target.closest('button, input, textarea, a, select')) return;
    /* Chữ chọn được thì nhường cho thao tác bôi đen: docx/xlsx hiện chữ thật
       trong `#docHtml`, người soát cần chọn chữ để đối chiếu. */
    if (e.target.closest('#docHtml')) return;
    /* Không tràn thì không có gì để kéo. */
    if (khung.scrollHeight <= khung.clientHeight
        && khung.scrollWidth <= khung.clientWidth) return;

    dang = true; daDiChuyen = false;
    x0 = e.clientX; y0 = e.clientY;
    tr0 = khung.scrollLeft; du0 = khung.scrollTop;
  });

  khung.addEventListener('pointermove', (e) => {
    if (!dang) return;
    const dx = e.clientX - x0, dy = e.clientY - y0;
    /* Ngưỡng 4px: tay ai cũng rung một chút khi bấm, và coi cú bấm đó là kéo
       sẽ nuốt mất thao tác chọn chunk. */
    if (!daDiChuyen && Math.hypot(dx, dy) < 4) return;
    if (!daDiChuyen) {
      daDiChuyen = true;
      khung.classList.add('dangKeo');
      /* Bắt con trỏ SAU khi đã chắc là kéo. Bắt ngay từ `pointerdown` sẽ
         chuyển hướng cả sự kiện `click` của cú bấm gọn sang `.stage`, làm
         mất thao tác chọn chunk trên canvas. */
      khung.setPointerCapture(e.pointerId);
    }
    e.preventDefault();
    khung.scrollLeft = tr0 - dx;
    khung.scrollTop  = du0 - dy;
  });

  const thoi = (e) => {
    if (!dang) return;
    dang = false;
    khung.classList.remove('dangKeo');
    if (khung.hasPointerCapture?.(e.pointerId)) {
      khung.releasePointerCapture(e.pointerId);
    }
    /* Vừa kéo xong thì chặn đúng một cú `click` kế tiếp, nếu không lớp phủ
       dưới con trỏ tưởng người dùng vừa chọn vùng đó. */
    if (daDiChuyen) {
      khung.addEventListener(
        'click', (ev) => { ev.stopPropagation(); ev.preventDefault(); },
        { capture: true, once: true });
    }
  };
  khung.addEventListener('pointerup', thoi);
  khung.addEventListener('pointercancel', thoi);
}

function drawOverlay() {
  const img = $('pageImg');
  const cv = $('overlay');
  if (!img.naturalWidth) return;

  /* Canvas dùng kích thước THẬT của ảnh (naturalWidth), còn CSS co nó lại cho
   * vừa khung. Vẽ theo kích thước hiển thị sẽ mờ trên màn Retina và lệch khi
   * cửa sổ đổi cỡ. */
  cv.width = img.naturalWidth;
  cv.height = img.naturalHeight;

  /* NÉT VẼ PHẢI QUY ĐỔI THEO TỈ LỆ THU NHỎ.
   * Canvas 1275 px thường bị CSS thu về ~669 px (tỉ lệ 1,9). Nét 1,5 px vẽ
   * trên canvas hiện ra chỉ 0,8 px trên màn — mắt thường không thấy, và khung
   * trông như không được vẽ dù thực tế có. Nhân ngược lại để độ dày nhìn thấy
   * luôn đúng ý đồ bất kể ảnh to nhỏ ra sao. */
  const shown = img.getBoundingClientRect().width || cv.width;
  const k = Math.max(1, cv.width / shown);

  const ctx = cv.getContext('2d');
  ctx.clearRect(0, 0, cv.width, cv.height);

  const onPage = state.chunks.filter((c) => c.page === state.page);

  if (state.layers.chunk) {
    for (const c of onPage) {
      const sel = c.i === state.sel;
      drawBox(ctx, c.box, cv, {
        stroke: sel ? '#e8590c' : colorFor(c.type),
        width: (sel ? 3 : 1.75) * k,
        fill: sel ? 'rgba(232,89,12,.10)' : null,
        label: `${c.i + 1}.${c.type}`,
        labelOn: sel,
        k,
      });
    }
  }

  if (state.layers.span && state.sel != null) {
    const c = state.chunks[state.sel];
    if (c) {
      c.atomic.forEach((s, j) => {
        if (!s.box || (s.page && s.page !== state.page)) return;
        const isSel = state.selSpan
          && state.selSpan.chunk === c.i && state.selSpan.seg === j;
        drawBox(ctx, s.box, cv, {
          stroke: isSel ? '#0ca678' : 'rgba(12,166,120,.55)',
          width: (isSel ? 2.5 : 1) * k,
          fill: isSel ? 'rgba(12,166,120,.12)' : null,
          k,
        });
      });
    }
  }

  // Vẽ SAU CÙNG: ô đen phải nằm trên khung chunk, như trong PDF che.
  if (state.cheOn && state.che) veChe(ctx, cv, k);
  if (state.truongOn && state.truong) veTruong(ctx, cv, k);
}

function drawBox(ctx, box, cv, o) {
  /* Chunk neo theo `path` (docx/xlsx) không có hộp. Thoát im lặng thay vì
   * ném: gọi tới đây là hợp lệ — vòng vẽ duyệt mọi chunk và không phải
   * chunk nào cũng có hình học. */
  if (!box) return;
  const x = box.xmin * cv.width;
  const y = box.ymin * cv.height;
  const w = (box.xmax - box.xmin) * cv.width;
  const h = (box.ymax - box.ymin) * cv.height;
  const k = o.k || 1;

  if (o.fill) { ctx.fillStyle = o.fill; ctx.fillRect(x, y, w, h); }
  ctx.strokeStyle = o.stroke;
  ctx.lineWidth = o.width;
  ctx.strokeRect(x, y, w, h);

  if (o.label && o.labelOn) {
    /* Nhãn cũng phải quy đổi: cỡ chữ 13 px trên canvas 1275 px hiện ra chỉ
     * ~7 px trên màn, không đọc được. */
    const fs = 13 * k;
    ctx.font = `600 ${fs}px system-ui, sans-serif`;
    const tw = ctx.measureText(o.label).width;
    const pad = 5 * k;
    const bh = fs + pad;
    ctx.fillStyle = o.stroke;
    ctx.fillRect(x, Math.max(0, y - bh), tw + pad * 2, bh);
    ctx.fillStyle = '#fff';
    ctx.fillText(o.label, x + pad, Math.max(fs, y - pad * 0.8));
  }
}

/* Bấm lên ảnh → chọn chunk nhỏ nhất chứa điểm đó.
 * Nhỏ nhất, vì các chunk lồng nhau (table chứa table_cell): chọn cái to sẽ làm
 * phần tử con không bao giờ bấm được. */
on('overlay', 'click', (ev) => {
  const cv = ev.currentTarget;
  const r = cv.getBoundingClientRect();
  const fx = (ev.clientX - r.left) / r.width;
  const fy = (ev.clientY - r.top) / r.height;

  let best = null, bestArea = Infinity;
  for (const c of state.chunks) {
    if (c.page !== state.page) continue;
    const b = c.box;
    if (fx < b.xmin || fx > b.xmax || fy < b.ymin || fy > b.ymax) continue;
    const area = (b.xmax - b.xmin) * (b.ymax - b.ymin);
    if (area < bestArea) { best = c; bestArea = area; }
  }
  if (best) selectChunk(best.i, true);
});

/* ── dải Files ───────────────────────────────────────────────────────── */
function renderFiles() {
  const pages = state.meta.pages || [];
  const strip = $('filesStrip');
  strip.innerHTML = '';

  /* docx/xlsx KHÔNG có ảnh trang, dù `meta.pages` vẫn ghi `[{page:1}]` cho
     báo cáo đếm được. Dựng thẻ <img> trỏ vào endpoint trả 404 thì ra một ô
     hình vỡ — trông như tệp hỏng, trong khi tài liệu mở bình thường ngay
     bên trên. Ẩn cả dải đi: với tài liệu một trang không phân trang, nó
     không nói thêm được điều gì. */
  const coAnh = !state.preview && pages.length > 0;
  $('files').hidden = !coAnh;
  if (!coAnh) return;

  $('filesCount').textContent = `Files (${pages.length})`;

  pages.forEach((p, i) => {
    const b = document.createElement('button');
    b.className = 'thumb' + (i === 0 ? ' on' : '');
    b.onclick = () => showPage(i + 1);
    const im = document.createElement('img');
    im.src = `/api/doc/${state.docId}/page/${i + 1}`;
    im.alt = `trang ${i + 1}`;
    b.appendChild(im);
    strip.appendChild(b);
  });
}

on('filesHead', 'click', (ev) => {
  const open = ev.currentTarget.getAttribute('aria-expanded') === 'true';
  ev.currentTarget.setAttribute('aria-expanded', String(!open));
  $('filesStrip').hidden = open;
});

/* ── thẻ chunk ───────────────────────────────────────────────────────── */
function renderChunks() {
  const box = $('chunks');
  box.innerHTML = '';
  box.classList.remove('muted');

  if (!state.chunks.length) {
    box.innerHTML = '<div class="pad muted">Tài liệu không có phần tử nào.</div>';
    return;
  }

  state.chunks.forEach((c) => box.appendChild(chunkCard(c)));
}

function chunkCard(c) {
  const el = document.createElement('div');
  el.className = 'chunk' + (c.i === state.sel ? ' on' : '');
  el.id = `chunk-${c.i}`;
  el.onclick = (ev) => {
    if (ev.target.closest('.chunkActs, .fixBox')) return;
    selectChunk(c.i, false);
  };

  /* đầu thẻ */
  const head = document.createElement('div');
  head.className = 'chunkHead';

  const badge = document.createElement('span');
  badge.className = 'badge';
  badge.textContent = `${c.i + 1} - ${c.type}`;
  head.appendChild(badge);

  /* Nhãn vị trí cho tệp không có ảnh trang — xem `nhanViTri`. */
  const vt = nhanViTri(c);
  if (vt) {
    const p = document.createElement('span');
    p.className = 'badge pathBadge';
    p.textContent = vt;
    p.title = `Vị trí trong tệp gốc: ${c.path}`;
    head.appendChild(p);
  }

  /* Dấu hiệu thấy được ngay ở danh sách: chunk nào đã bị lớp sửa đụng vào.
     Không có nó thì người soát phải mở từng thẻ mới biết. */
  if (state.corrected[c.id]) {
    const fx = document.createElement('span');
    fx.className = 'badge fixBadge';
    fx.textContent = '✎ đã sửa';
    fx.title = 'protonX đã sửa chính tả — rê lên chữ tô để xem bản ADE gốc';
    head.appendChild(fx);
  }

  const acts = document.createElement('div');
  acts.className = 'chunkActs';

  const v = state.verdicts[c.id] || {};
  const good = document.createElement('button');
  good.textContent = '👍';
  good.title = 'Đọc đúng';
  if (v.verdict === 'good') good.classList.add('good');
  good.onclick = () => sendVerdict(c, 'good', '');

  const bad = document.createElement('button');
  bad.textContent = '👎';
  bad.title = 'Đọc sai — sửa lại';
  if (v.verdict === 'bad') bad.classList.add('bad');
  bad.onclick = () => toggleFix(el, c);

  const raw = document.createElement('button');
  raw.textContent = '# Raw';
  raw.title = 'Markdown ADE trả về nguyên văn cho phần tử này (chưa sửa)';
  raw.onclick = () => toggleRaw(el, c);

  acts.append(good, bad, raw);
  head.appendChild(acts);
  el.appendChild(head);

  /* thân thẻ */
  const body = document.createElement('div');
  body.className = 'chunkBody';
  if (state.view === 'json') {
    body.classList.add('mono');
    body.textContent = JSON.stringify(c.node, null, 2);
  } else {
    renderSegments(body, c);
  }
  el.appendChild(body);

  /* toạ độ thô — để soát được cả phép biến đổi, không chỉ soát nội dung */
  /* Chunk neo theo `path` không có toạ độ — hiện đường dẫn cấu trúc thay
   * cho dòng toạ độ, và không cắt ảnh (không có ảnh trang để cắt). */
  if (c.i === state.sel && !c.box) {
    const co = document.createElement('div');
    co.className = 'coords';
    co.textContent = `vị trí trong tệp · ${c.path}`;
    el.appendChild(co);
  } else if (c.i === state.sel) {
    const co = document.createElement('div');
    co.className = 'coords';
    const b = c.box;
    co.textContent =
      `trang ${c.page} · xmin ${b.xmin.toFixed(4)} · ymin ${b.ymin.toFixed(4)}`
      + ` · xmax ${b.xmax.toFixed(4)} · ymax ${b.ymax.toFixed(4)}`;
    el.appendChild(co);

    /* Hình / chữ ký / con dấu: cắt đúng vùng từ ảnh trang. */
    if (c.type === 'figure' || c.type === 'attestation') {
      const im = document.createElement('img');
      im.className = 'crop';
      im.alt = c.type;
      im.src = `/api/doc/${state.docId}/crop?page=${c.page}`
        + `&xmin=${b.xmin}&ymin=${b.ymin}&xmax=${b.xmax}&ymax=${b.ymax}`;
      el.appendChild(im);
    }
  }

  return el;
}

/* Chia thân thẻ thành các `<span>` theo `atomic_grounding`, mỗi span rê được
 * để soi vị trí trên ảnh. Đây là mức neo thứ hai. */
/* Nhãn vị trí cho chunk neo theo `path`.
 *
 * Với tài liệu có ảnh, người soát nhìn khung vẽ để biết chunk nằm đâu. Với
 * docx/xlsx không có hình học nào, nên đường dẫn cấu trúc LÀ câu trả lời:
 *   p:12          đoạn văn thứ 12 của tài liệu
 *   Sheet1!B7     ô B7 của sheet tên Sheet1
 *   L48           dòng 48 của tệp văn bản
 * Hiện nó ra thay vì giấu đi — nếu không, chunk chỉ là một mẩu chữ trôi nổi
 * không định vị được trong tệp gốc.
 */
function nhanViTri(c) {
  if (!c.path) return '';
  if (c.path.includes('!')) return c.path;                 // ô bảng tính
  const m = /^p:(\d+)$/.exec(c.path);
  if (m) return `đoạn ${Number(m[1]) + 1}`;
  const l = /^L(\d+)$/.exec(c.path);
  if (l) return `dòng ${l[1]}`;
  return c.path;
}

function renderSegments(body, c) {
  /* Chunk của Vision mang sẵn chữ (`c.text`) vì không có `markdown` chung để
     cắt theo offset — Vision trả từng dòng rời, không trả một chuỗi trang. */
  if (c.text != null) {
    body.textContent = c.text;
    return;
  }

  /* Chunk đã được sửa chính tả: vẽ DIFF theo từ thay vì cắt theo span.
   *
   * Vì sao không dùng span ở đây: mọi `atomic_grounding.range` neo vào
   * `markdown` GỐC bằng offset ký tự. Bản sửa đổi độ dài chữ (`Nới`→`Nơi`
   * cùng độ dài, nhưng `thė`→`thẻ` thì không nhất thiết), nên cắt bản sửa
   * bằng offset của bản gốc sẽ ra chữ lệch — sai mà trông vẫn hợp lý.
   *
   * Đổi lại thì mất mức neo span trên đúng những chunk này. Đó là đánh đổi
   * có ý thức: thấy rõ chữ nào bị model đổi quan trọng hơn, vì đó chính là
   * thứ người soát cần xét. Bấm "# Raw" để về bản gốc kèm span.
   */
  const fix = state.corrected[c.id];
  if (fix) {
    renderDiff(body, fix.original, fix.corrected);
    return;
  }

  const segs = c.atomic.filter((s) => s.range);
  if (!segs.length) {
    body.innerHTML = withPlaceholders(catMd(c.range));
    return;
  }

  segs.forEach((s, j) => {
    /* Chữ nằm GIỮA hai span phải được trả lại.
     *
     * `atomic_grounding` neo TỪNG TỪ, nên khoảng trắng phân cách nằm ngoài
     * mọi range: 'Nhãn' [250,254) + 'hiêu' [255,259) bỏ rơi dấu cách ở 254.
     * Nối thẳng các span ra 'Nhãnhiêu' — chữ dính liền, sai chính tả tiếng
     * Việt, và người soát có thể chấm SAI cho một chunk mà engine đọc ĐÚNG.
     *
     * Phần đệm không phải `<span>`: nó không thuộc từ nào nên không có toạ
     * độ để tô sáng khi rê chuột. */
    const truoc = j ? segs[j - 1].range.end : c.range?.start;
    if (truoc != null && s.range.start > truoc) {
      body.appendChild(document.createTextNode(
        catMd({ start: truoc, end: s.range.start })));
    }

    const sp = document.createElement('span');
    sp.className = 'seg-atom';
    sp.innerHTML = withPlaceholders(catMd(s.range));
    sp.onmouseenter = () => { state.selSpan = { chunk: c.i, seg: j }; drawOverlay(); };
    sp.onmouseleave = () => { state.selSpan = null; drawOverlay(); };
    sp.onclick = () => { selectChunk(c.i, false); };
    body.appendChild(sp);
  });

  /* Và phần đuôi sau span cuối (dấu câu, ký tự xuống dòng). */
  const cuoi = segs[segs.length - 1].range.end;
  if (c.range?.end != null && c.range.end > cuoi) {
    body.appendChild(document.createTextNode(
      catMd({ start: cuoi, end: c.range.end })));
  }
}

/* Vẽ bản sửa, tô đúng những TỪ model đã đổi.
 *
 * Hiện bản sửa mà không chỉ ra chỗ đổi thì người soát phải tự so hai bản
 * trong đầu — và họ sẽ không làm, họ sẽ tin. Tô lên thì mắt tự dừng đúng chỗ
 * cần xét. Rê chuột lên từ được tô để thấy chữ gốc.
 */
function renderDiff(body, before, after) {
  const a = before.split(/(\s+)/);
  const b = after.split(/(\s+)/);

  /* So theo từ bằng quy hoạch động (LCS). Chuỗi ở đây dài vài chục từ nên
   * O(n·m) là thoải mái, và nó cho kết quả đúng thay vì đoán bằng heuristic. */
  const n = a.length, m = b.length;
  const L = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      L[i][j] = a[i] === b[j] ? L[i + 1][j + 1] + 1
                              : Math.max(L[i + 1][j], L[i][j + 1]);

  let i = 0, j = 0;
  const frag = document.createDocumentFragment();
  const push = (text, oldText) => {
    if (!text) return;
    if (oldText == null) {
      frag.appendChild(document.createTextNode(text));
      return;
    }
    const sp = document.createElement('span');
    sp.className = 'fixed';
    sp.textContent = text;
    sp.title = `ADE đọc: ${oldText}`;
    frag.appendChild(sp);
  };

  while (i < n || j < m) {
    if (i < n && j < m && a[i] === b[j]) { push(a[i]); i++; j++; continue; }
    /* Gom cả cụm đã đổi lại thành một mảng tô, thay vì tô rời từng từ.
     *
     * Điều kiện dừng phải là "cả hai cùng hết HOẶC gặp lại từ giống nhau" —
     * viết `i < n && j < m` thì cụm đổi nằm ở CUỐI chuỗi bị bỏ sót, vì vòng
     * ngoài thoát trước khi kịp tô. Đó chính là ca `điện tứ` → `điện tử`:
     * từ đổi là từ cuối cùng, và nó hiện ra không màu. */
    const oi = i, oj = j;
    while ((i < n || j < m) && !(i < n && j < m && a[i] === b[j])) {
      if (j >= m || (i < n && L[i + 1][j] >= L[i][j + 1])) i++; else j++;
    }
    push(b.slice(oj, j).join(''), a.slice(oi, i).join('') || '(trống)');
  }

  body.appendChild(frag);
}

/* Cắt `markdown` theo `grounding.range`.
 *
 * ĐẾM THEO CODE POINT, KHÔNG PHẢI `.slice()`.
 * Engine sinh `range` bằng Python, nơi `len("👤")` là 1. JS `.slice()` đếm
 * UTF-16 code unit, nơi `"👤".length` là 2. Mỗi emoji đứng TRƯỚC một chunk
 * đẩy chunk đó lệch 1 đơn vị, và lệch CỘNG DỒN — tài liệu có 6 emoji ở đầu
 * thì mọi chunk phía sau lệch 6 ký tự.
 *
 * Triệu chứng thật: ô bảng `Nhãn hiệu` hiện ra `d>Nhãn hi` — cắt trúng mảnh
 * thẻ `<td>`. Vẫn trông như chữ thật nên người soát ký duyệt một bản ghi
 * không khớp tài liệu gốc. Đo lúc phát hiện: 1.363/2.526 chunk lệch.
 *
 * `state.mdCP` là mảng code point dựng MỘT lần mỗi lần đổi markdown. Gọi
 * `[...md]` trong chính hàm này thì mỗi chunk quét lại cả tài liệu — trang
 * 1.036 chunk sẽ đứng hình.
 */
const catMd = (r) => {
  if (!r || !state.mdCP) return '';
  return state.mdCP.slice(r.start ?? 0, r.end ?? 0).join('');
};

/* Placeholder ADE tự chèn ([VISUAL_TEXT], [QR_CODE], [chip image]…) phải nhìn
 * khác chữ thật, kẻo có người chép nhầm chúng vào ground truth. */
function withPlaceholders(text) {
  return danhDauPII(text).replace(PLACEHOLDER_RE, (m) => `<span class="ph">${m}</span>`);
}

/* Tô các vùng nhạy cảm.
 *
 * Phải tìm PII trên văn bản THÔ rồi mới escape từng mảnh, không được escape
 * trước: `&` trong 'A & B' nở thành '&amp;' làm mọi offset sau nó lệch 4 ký
 * tự, và vùng tô sẽ trượt sang chữ bên cạnh — tô nhầm chỗ còn tệ hơn không
 * tô, vì người soát tin vào màu.
 *
 * Trả về HTML đã escape an toàn trong mọi nhánh. */
function danhDauPII(text) {
  if (!state.piiOn || !text) return esc(text);
  const vung = timPII(text);
  if (!vung.length) return esc(text);

  let out = '';
  let i = 0;
  for (const v of vung) {
    out += esc(text.slice(i, v.start));
    const cach = xuLy(v.f);
    out += `<mark class="pii ${cach}" title="${esc(v.f.ten)} — ${esc(NHAN[cach].ten)}`
         + `\n${esc(v.f.vi_sao)}">${esc(text.slice(v.start, v.end))}</mark>`;
    i = v.end;
  }
  return out + esc(text.slice(i));
}

function selectChunk(i, scroll) {
  state.sel = i;
  state.selSpan = null;
  const c = state.chunks[i];
  /* Chunk neo theo `path` (docx/xlsx) không có ảnh trang: bỏ qua cả việc
   * chuyển trang lẫn việc vẽ overlay. Gọi `showPage` ở đây sẽ nạp ảnh của
   * TÀI LIỆU TRƯỚC — `state.docId` đã bị xoá nên URL ảnh trỏ vào null. */
  const coAnh = c && c.kind !== 'path';
  if (coAnh && c.page !== state.page) { showPage(c.page); }
  renderChunks();
  /* `drawOverlay` thoát sớm khi ảnh chưa tải (naturalWidth = 0), nên lần chọn
   * đầu tiên ngay sau `loadDoc` có thể vẽ hụt. `img.onload` trong `showPage`
   * sẽ gọi lại — nhưng chỉ khi ảnh CHƯA tải xong. Gọi thêm ở đây phủ nốt
   * trường hợp ảnh đã nằm sẵn trong cache và `onload` không bắn nữa. */
  if (coAnh) drawOverlay();
  if (scroll) {
    const el = $(`chunk-${i}`);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
}

/* ── Raw / sửa ───────────────────────────────────────────────────────── */
function toggleRaw(card, c) {
  const old = card.querySelector('.rawBox');
  if (old) { old.remove(); return; }
  const d = document.createElement('div');
  d.className = 'chunkBody mono rawBox';
  d.textContent = c.node.markdown || catMd(c.range) || '(không có)';
  card.appendChild(d);
}

function toggleFix(card, c) {
  const old = card.querySelector('.fixBox');
  if (old) { old.remove(); return; }

  const box = document.createElement('div');
  box.className = 'fixBox';

  const ta = document.createElement('textarea');
  ta.value = state.verdicts[c.id]?.corrected || catMd(c.range);

  const row = document.createElement('div');
  row.className = 'row';

  const save = document.createElement('button');
  save.className = 'primary';
  save.textContent = 'Lưu bản sửa';
  save.onclick = () => sendVerdict(c, 'bad', ta.value).then(() => box.remove());

  const cancel = document.createElement('button');
  cancel.textContent = 'Huỷ';
  cancel.onclick = () => box.remove();

  row.append(save, cancel);
  box.append(ta, row);
  card.appendChild(box);
  ta.focus();
}

async function sendVerdict(c, verdict, corrected) {
  const r = await fetch(`/api/doc/${state.docId}/verdict`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chunk_id: c.id, verdict, corrected }),
  });
  if (!r.ok) { alert('Không lưu được: ' + r.status); return; }
  state.verdicts[c.id] = { verdict, corrected };
  renderChunks();
}

/* ── điều khiển ──────────────────────────────────────────────────────── */
on('tabMd', 'click', () => setView('md'));
on('tabJson', 'click', () => setView('json'));
function setView(v) {
  state.view = v;
  $('tabMd').classList.toggle('on', v === 'md');
  $('tabJson').classList.toggle('on', v === 'json');
  renderChunks();
}

on('engAde', 'click', () => setEngine('ade'));
on('engVision', 'click', () => setEngine('vision'));
on('engPro', 'click', () => setEngine('pro'));
/* Đặt engine + tô nút, KHÔNG dựng lại chunk.
   Tách ra để `loadDoc` dùng được lúc đang tải, trước khi có state.chunks. */
function setEngineButtons(name) {
  state.engine = name;
  $('engLocal')?.classList.toggle('on', name === 'local');
  $('engAde')?.classList.toggle('on', name === 'ade');
  $('engVision')?.classList.toggle('on', name === 'vision');
  $('engPro')?.classList.toggle('on', name === 'pro');
}

function setEngine(name) {
  if (state.engine === name) return;
  setEngineButtons(name);

  /* Dựng lại từ dữ liệu ĐÃ TẢI, không gọi lại API: cả hai bản chép về cùng
     một lượt, nên đổi engine phải tức thì — có độ trễ thì người soát sẽ ngại
     bấm qua bấm lại, mà bấm qua lại chính là cách so sánh. */
  if (!state.parseRaw) return;
  state.chunks = chunksFor(name);
  state.sel = null;
  state.selSpan = null;
  renderChunks();
  if (state.chunks.length) selectChunk(0, false); else drawOverlay();
}

on('layChunk', 'click', (e) => toggleLayer('chunk', e.currentTarget));
on('laySpan', 'click', (e) => toggleLayer('span', e.currentTarget));

/* Bật/tắt lớp tô thông tin nhạy cảm, kèm bảng tổng kết đếm được trên chính
 * tài liệu đang mở — con số cụ thể thì cãi được, cảm giác thì không. */
on('tabPII', 'click', (e) => {
  state.piiOn = !state.piiOn;
  e.currentTarget.classList.toggle('on', state.piiOn);
  renderChunks();
  dungBangPII();
});

function dungBangPII() {
  const cu = document.getElementById('piiPanel');
  if (cu) cu.remove();
  if (!state.piiOn) return;

  const dem = new Map();
  for (const c of state.chunks) {
    for (const v of timPII(catMd(c.range))) {
      const k = v.f.id;
      if (!dem.has(k)) dem.set(k, { f: v.f, n: 0 });
      dem.get(k).n += 1;
    }
  }
  const ds = [...dem.values()].sort((a, b) => (b.f.R * b.f.L) - (a.f.R * a.f.L) || b.n - a.n);

  const el = document.createElement('div');
  el.id = 'piiPanel';
  el.className = 'piiPanel';
  if (!ds.length) {
    el.innerHTML = '<div class="pp-head">Không thấy trường nhạy cảm nào '
                 + 'trong tài liệu này.</div>';
  } else {
    const tong = ds.reduce((a, x) => a + x.n, 0);
    el.innerHTML =
      `<div class="pp-head">${tong} vùng nhạy cảm · ${ds.length} loại trường</div>`
      + '<table class="pp-tbl"><thead><tr><th>trường</th><th>số vùng</th>'
      + '<th>R×L</th><th>cách xử lý</th></tr></thead><tbody>'
      + ds.map(({ f, n }) => {
          const cach = xuLy(f);
          return `<tr><td>${esc(f.ten)}</td><td class="num">${n}</td>`
               + `<td class="num">${f.R * f.L}</td>`
               + `<td><span class="pii-tag ${cach}">${esc(NHAN[cach].ten)}</span></td></tr>`;
        }).join('')
      + '</tbody></table>'
      + '<div class="pp-legend">'
      + '<span><i class="pseudo"></i>bút danh hoá — thay bằng mã, hoàn nguyên được qua vault</span>'
      + '<span><i class="anon"></i>ẩn danh hoá — khái quát hoá, KHÔNG hoàn nguyên được</span>'
      + '</div>'
      + '<div class="pp-foot">R = sức tái định danh · L = thiệt hại nếu lộ · '
      + 'N = nhu cầu nghiệp vụ. Rủi ro = R×L; N quyết định bút danh hay ẩn danh.</div>';
  }
  const chu = document.getElementById('chunks');
  chu.parentNode.insertBefore(el, chu);
}

/* ── lớp che ─────────────────────────────────────────────────────────── */

/* Cùng phép đổi của `_pixel` trong che.py (box_to_pixels + nới 1 px), để ô
   đen trên màn trùng từng điểm ảnh với ô đen trong PDF — xem trước mà lệch
   bản thật thì xem trước để làm gì. */
function _pxChe(b, w, h) {
  const x0 = Math.round(b.xmin * w), y0 = Math.round(b.ymin * h);
  const x1 = Math.round(b.xmax * w), y1 = Math.round(b.ymax * h);
  return [Math.max(0, x0 - 1), Math.max(0, y0 - 1),
          Math.min(w, x1 + 1), Math.min(h, y1 + 1)];
}

/* Trang nghiêng: ô che là tứ giác theo dòng (`tu_giac`, bốn góc trên-trái,
   trên-phải, dưới-phải, dưới-trái). Như `_truc`/`_da_giac` của che.py: nới
   1 px ra mọi phía theo trục riêng của ô, để màn trùng PDF. */
function _truc(q) {
  const [[x0, y0], [x1, y1], , [x3, y3]] = q;
  const rong = Math.hypot(x1 - x0, y1 - y0), cao = Math.hypot(x3 - x0, y3 - y0);
  return { ux: (x1 - x0) / (rong || 1), uy: (y1 - y0) / (rong || 1),
           vx: (x3 - x0) / (cao || 1), vy: (y3 - y0) / (cao || 1), rong, cao };
}

function _oChe(v, w, h) {
  if (!v.tu_giac) {
    const r = _pxChe(v.box, w, h);
    return { r, q: null, rong: r[2] - r[0], cao: r[3] - r[1] };
  }
  const q0 = v.tu_giac.map(([x, y]) => [x * w, y * h]);
  const t = _truc(q0);
  const [x, y] = q0[0];
  const q = [[-1, -1], [t.rong + 1, -1], [t.rong + 1, t.cao + 1], [-1, t.cao + 1]]
    .map(([a, b]) => [x + t.ux * a + t.vx * b, y + t.uy * a + t.vy * b]);
  const xs = q.map((p) => p[0]), ys = q.map((p) => p[1]);
  return { r: [Math.max(0, Math.floor(Math.min(...xs))), Math.max(0, Math.floor(Math.min(...ys))),
               Math.min(w, Math.ceil(Math.max(...xs))), Math.min(h, Math.ceil(Math.max(...ys)))],
           q, rong: t.rong + 2, cao: t.cao + 2, t };
}

function _duongO(ctx, o) {
  ctx.beginPath();
  if (!o.q) { const [x0, y0, x1, y1] = o.r; ctx.rect(x0, y0, x1 - x0, y1 - y0); return; }
  o.q.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
  ctx.closePath();
}

const _giao = (a, b) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];

/* Điểm (fx, fy) — theo tỉ lệ trang — có nằm trong ô không (tứ giác thì theo
   tứ giác, không theo hộp bao: hộp bao của ô nghiêng ăn sang dòng bên). */
function _trongO(v, fx, fy) {
  if (!v.tu_giac) return fx >= v.box.xmin && fx <= v.box.xmax && fy >= v.box.ymin && fy <= v.box.ymax;
  let vao = false;
  const q = v.tu_giac;
  for (let i = 0, j = q.length - 1; i < q.length; j = i++) {
    const [xi, yi] = q[i], [xj, yj] = q[j];
    if ((yi > fy) !== (yj > fy) && fx < ((xj - xi) * (fy - yi)) / (yj - yi) + xi) vao = !vao;
  }
  return vao;
}

function _hopDai(x, cao, w, h) {
  const [x0, y0] = x.q[0];
  const q = [[0, 0], [x.rong, 0], [x.rong, cao], [0, cao]]
    .map(([a, b]) => [x0 + x.t.ux * a + x.t.vx * b, y0 + x.t.uy * a + x.t.vy * b]);
  const xs = q.map((p) => p[0]), ys = q.map((p) => p[1]);
  return [Math.max(0, Math.min(...xs)), Math.max(0, Math.min(...ys)),
          Math.min(w, Math.max(...xs)), Math.min(h, Math.max(...ys))];
}

function veChe(ctx, cv, k) {
  const tren = state.che.vung.filter((v) => v.page === state.page);
  const o = tren.map((v) => _oChe(v, cv.width, cv.height));
  ctx.save();
  // Tô HẾT rồi mới ghi nhãn — ghi xen kẽ thì chữ trắng rơi lên ô kế bên
  // (lỗi đã gặp ở `nung`, 431 vùng).
  for (const x of o) {
    _duongO(ctx, x);
    ctx.fillStyle = state.cheXuyen ? 'rgba(0,0,0,.35)' : '#000';
    ctx.fill();
    if (state.cheXuyen) {
      ctx.strokeStyle = '#e03131';
      ctx.lineWidth = 1.5 * k;
      ctx.stroke();
    }
  }
  if (!state.cheXuyen) {
    ctx.fillStyle = '#fff';
    tren.forEach((v, i) => {
      // Như `nung`: mỗi field một nhãn (mảnh lớn nhất), và dải nhãn không
      // chạm ô nào khác — chạm thì chữ trắng in lên ô bên cạnh.
      const x = o[i];
      if (v.nhan === false) return;
      const fs = Math.min(11 * k, x.cao * 0.75);
      if (fs < 7 || x.cao < 20) return;   // như `_NHAN_CAO + 6` của nung
      ctx.font = `600 ${fs}px system-ui, sans-serif`;
      const nhan = nhanChe(v);
      if (ctx.measureText(nhan).width + 6 > x.rong) return;
      const dai = x.q ? _hopDai(x, fs + 3, cv.width, cv.height)
                      : [x.r[0], x.r[1], x.r[2], x.r[1] + fs + 3];
      if (o.some((y, j) => j !== i && _giao(dai, y.r))) return;
      if (!x.q) { ctx.fillText(nhan, x.r[0] + 3, x.r[1] + fs); return; }
      ctx.save();
      ctx.translate(x.q[0][0], x.q[0][1]);
      ctx.rotate(Math.atan2(x.t.uy, x.t.ux));
      ctx.fillText(nhan, 3, fs);
      ctx.restore();
    });
  }
  ctx.restore();
}

async function taiChe() {
  const id = state.docId;
  if (!id) return;
  const res = await fetch(`/api/doc/${id}/che`);
  const d = res.ok ? await res.json()
                   : { vung: [], dem: {}, loi: (await res.json().catch(() => ({}))).detail
                                              || `server trả ${res.status}` };
  if (state.docId !== id) return;   // người dùng đã sang tệp khác giữa chừng
  state.che = d;
  dungBangChe();
  drawOverlay();
}

const LUAT_CHE = {
  pii_core: 'field pii-core', ma_quet: 'mã QR/vạch',
  hinh: 'hình ADE mô tả (ảnh người, chữ ký, QR)', hinh_ade: 'hình/logo ADE (mẫu nhãn dạng hình)',
  chung_thuc: 'con dấu / chữ ký ADE (che cả phần tử)',
};

/* Chữ in lên ô đen: token pii-core, như `_nhan` của che.py (không ASCII thì
   nhãn lớp — PDF in bằng font không dấu, xem trước phải giống PDF). */
function nhanChe(v) {
  const t = v.thay || `[${v.code}]`;
  return /^[\x00-\x7f]*$/.test(t) ? t : `[${v.code}]`;
}

function dungBangChe() {
  document.getElementById('chePanel')?.remove();
  if (!state.cheOn || !state.che) return;
  const d = state.che;
  const el = document.createElement('div');
  el.id = 'chePanel';
  el.className = 'piiPanel chePanel';

  const theoMa = new Map();
  for (const v of d.vung) {
    if (!theoMa.has(v.code)) theoMa.set(v.code, { action: v.action, trang: new Set(), luat: new Set(), n: 0 });
    const m = theoMa.get(v.code);
    m.n += 1; m.trang.add(v.page); m.luat.add(v.luat);
  }
  const ds = [...theoMa.entries()].sort((a, b) => b[1].n - a[1].n);
  const trangNay = d.vung.filter((v) => v.page === state.page).length;

  let html;
  if (d.loi) {
    html = `<div class="pp-head">Không che được: ${esc(d.loi)}</div>`;
  } else if (!d.vung.length) {
    html = `<div class="pp-head">${esc(d.ly_do || 'pii-core không thấy gì phải che trong tài liệu này.')}</div>`;
  } else {
    html = `<div class="pp-head">${d.vung.length} vùng sẽ bị che · ${ds.length} hạng mục`
      + ` · trang này ${trangNay}</div>`
      + (d.ly_do ? `<div class="pp-foot">${esc(d.ly_do)}</div>` : '')
      + (d.khong_dinh_vi ? `<div class="pp-foot">⚠ ${d.khong_dinh_vi}/${d.truong} field ≠ KEEP của pii-core `
                           + 'không đặt được vào box nào — PDF che sẽ không đạt chứng minh.</div>' : '')
      + '<table class="pp-tbl"><thead><tr><th>hạng mục</th><th class="num">vùng</th>'
      + '<th>pii-core</th><th>trang</th></tr></thead><tbody>'
      + ds.map(([code, m]) =>
          `<tr title="${esc([...m.luat].map((l) => LUAT_CHE[l] || l).join(', '))}">`
          + `<td>${esc(code)}</td><td class="num">${m.n}</td>`
          + `<td><span class="pii-tag anon">${esc(m.action)}</span></td>`
          + `<td>${[...m.trang].sort((a, b) => a - b).map((p) =>
              `<button class="cheTrang${p === state.page ? ' on' : ''}" data-p="${p}">${p}</button>`).join('')}</td></tr>`)
        .join('')
      + '</tbody></table>'
      + '<div class="pp-legend cheNut">'
      + `<label><input type="checkbox" id="cheXuyen"${state.cheXuyen ? ' checked' : ''}> nhìn xuyên</label>`
      + (d.ly_do ? '' : `<a id="chePdf" href="/api/doc/${state.docId}/che.pdf" download>`
                      + `⤓ tải PDF đã che${d.co_pdf ? '' : ' (dựng ngay)'}</a>`)
      + '</div>'
      + '<div class="pp-foot">Cái gì che, và ở đâu trong chữ, do pii-core quyết '
      + '(≠ KEEP thì che); ô đen in token của pii-core. Box theo DÒNG của ADE Pro, vị trí '
      + 'trong dòng đo theo mực — bật "nhìn xuyên" để soát ô đen có trúng chữ không. '
      + 'Hình, logo, con dấu và chữ ký che cả phần tử; ô chồng nhau thì hành động '
      + 'nghiêm hơn giữ phần chung. Trang scan nghiêng: ô nghiêng theo dòng chữ.</div>';
  }
  el.innerHTML = html;
  el.querySelectorAll('.cheTrang').forEach((b) =>
    b.addEventListener('click', () => { showPage(+b.dataset.p); }));
  /* Tải qua fetch chứ không để thẻ <a> tự đi: server từ chối (409 không có
     ảnh trang, 500 chứng minh hỏng) thì <a download> lưu luôn thông báo lỗi
     thành tệp "…-che.pdf" — và người ta sẽ gửi nó đi. */
  el.querySelector('#chePdf')?.addEventListener('click', async (e) => {
    e.preventDefault();
    const a = e.currentTarget;
    const cu = a.textContent;
    a.textContent = '… đang dựng và chứng minh';
    try {
      const res = await fetch(a.href);
      if (!res.ok) {
        const m = (await res.json().catch(() => ({}))).detail || res.status;
        a.textContent = `✕ ${m}`;
        return;
      }
      const url = URL.createObjectURL(await res.blob());
      const t = document.createElement('a');
      t.href = url; t.download = `${state.docId}-che.pdf`;
      t.click();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
      state.che.co_pdf = true;
      a.textContent = '⤓ tải PDF đã che';
    } catch { a.textContent = cu; }
  });
  el.querySelector('#cheXuyen')?.addEventListener('change', (e) => {
    state.cheXuyen = e.currentTarget.checked;
    drawOverlay();
  });
  const chu = document.getElementById('chunks');
  chu.parentNode.insertBefore(el, chu);
}

on('layChe', 'click', (e) => {
  state.cheOn = !state.cheOn;
  e.currentTarget.classList.toggle('on', state.cheOn);
  if (state.cheOn && !state.che) { taiChe(); return; }
  dungBangChe();
  drawOverlay();
});

/* ── lớp trường: soát hành động pii-core trên trang ─────────────────── */

const MAU_HD = {
  PSEUDONYMISE: { mau: '#1c7ed6', ten: 'bí danh hoá' },
  ANONYMISE: { mau: '#f08c00', ten: 'ẩn danh hoá' },
  REMOVE: { mau: '#e03131', ten: 'xoá' },
  KEEP: { mau: '#2f9e44', ten: 'giữ' },
};
const THU_TU_HD = ['PSEUDONYMISE', 'ANONYMISE', 'REMOVE', 'KEEP'];

/* Con dấu, chữ ký (phần tử `attestation` của ADE) là loại vùng riêng: che cả
   phần tử, không phải field của pii-core — cùng màu với lớp phần tử ADE. */
const MAU_CHUNG_THUC = '#0ca678';
const TEN_CHUNG_THUC = { STAMP: 'con dấu', SIGNATURE: 'chữ ký' };

function nhanTruong(v) {
  if (v.luat === 'chung_thuc') return `${v.code} · ${TEN_CHUNG_THUC[v.code] || 'dấu/chữ ký'}`;
  return v.action === 'KEEP' ? v.code : `${v.code} ${nhanChe(v)}`;
}

function veTruong(ctx, cv, k) {
  const tren = state.truong.vung.filter((v) => v.page === state.page);
  const o = tren.map((v) => _oChe(v, cv.width, cv.height));
  ctx.save();
  tren.forEach((v, i) => {
    const m = (MAU_HD[v.action] || MAU_HD.REMOVE).mau;
    _duongO(ctx, o[i]);
    ctx.fillStyle = m + '26';
    ctx.fill();
    ctx.strokeStyle = v.luat === 'chung_thuc' ? MAU_CHUNG_THUC : m;
    ctx.lineWidth = (v.luat === 'chung_thuc' ? 2.5 : 1.5) * k;
    ctx.setLineDash(v.action === 'KEEP' ? [4 * k, 3 * k] : v.luat === 'chung_thuc' ? [9 * k, 3 * k] : []);
    ctx.stroke();
  });
  ctx.setLineDash([]);
  // Nhãn ghi NGOÀI ô, trên nền màu hành động: không đè lên chữ đang soát.
  // Trên mép trước, không được thì dưới mép; ô cao (dấu, hình — che cả phần
  // tử, không có chữ để soát) thì thêm chỗ trong mép trên; không được nữa
  // thì bỏ — nhãn không đè nhãn, không đè ô khác. Mỗi field một nhãn.
  const fs = 9.5 * k;
  ctx.font = `600 ${fs}px system-ui, sans-serif`;
  const da = [];
  tren.forEach((v, i) => {
    if (v.nhan === false) return;
    const [x0, y0, , y1] = o[i].r;
    const t = nhanTruong(v);
    const w = ctx.measureText(t).width + 6 * k, h = fs + 3 * k;
    const cho = [[x0, y0 - h], [x0, y1], ...(y1 - y0 >= 3 * h ? [[x0, y0]] : [])]
      .map(([x, y]) => [x, y, x + w, y + h])
      .find((c) => c[1] >= 0 && c[3] <= cv.height
        && !da.some((d) => _giao(c, d)) && !o.some((x, j) => j !== i && _giao(c, x.r))
        && (c[1] < y0 || c[1] >= y1 || c[2] <= o[i].r[2]));
    if (!cho) return;
    da.push(cho);
    ctx.fillStyle = v.luat === 'chung_thuc' ? MAU_CHUNG_THUC : (MAU_HD[v.action] || MAU_HD.REMOVE).mau;
    ctx.fillRect(cho[0], cho[1], w, h);
    ctx.fillStyle = '#fff';
    ctx.fillText(t, cho[0] + 3 * k, cho[1] + fs);
  });
  ctx.restore();
}

async function taiTruong() {
  const id = state.docId;
  if (!id) return;
  const res = await fetch(`/api/doc/${id}/truong`);
  const d = res.ok ? await res.json()
                   : { vung: [], dem: {}, theo_hang_muc: {},
                       loi: (await res.json().catch(() => ({}))).detail || `server trả ${res.status}` };
  if (state.docId !== id) return;
  state.truong = d;
  dungBangTruong();
  drawOverlay();
}

function dungBangTruong() {
  document.getElementById('truongPanel')?.remove();
  if (!state.truongOn || !state.truong) return;
  const d = state.truong;
  const el = document.createElement('div');
  el.id = 'truongPanel';
  el.className = 'piiPanel chePanel';
  const tag = (a) => `<span class="hdTag" style="--hd:${(MAU_HD[a] || MAU_HD.REMOVE).mau}">${esc(a)}</span>`;
  const hds = THU_TU_HD.filter((a) => d.dem?.[a]).concat(
    Object.keys(d.dem || {}).filter((a) => !THU_TU_HD.includes(a)));
  let html;
  if (d.loi) {
    html = `<div class="pp-head">Không hỏi được pii-core: ${esc(d.loi)}</div>`;
  } else if (!d.vung.length) {
    html = `<div class="pp-head">${esc(d.ly_do || 'pii-core không thấy field nào trong tài liệu này.')}</div>`;
  } else {
    const tong = Object.values(d.dem).reduce((a, b) => a + b, 0);
    const trangNay = d.vung.filter((v) => v.page === state.page).length;
    const hinh = d.vung.filter((v) => !['pii_core', 'chung_thuc'].includes(v.luat)).length;
    const dau = d.vung.filter((v) => v.luat === 'chung_thuc').length;
    html = `<div class="pp-head">${tong} field${hinh ? ` + ${hinh} hình/mã quét` : ''}`
      + `${dau ? ` + ${dau} con dấu/chữ ký` : ''} · trang này ${trangNay} box · `
      + hds.map((a) => `${tag(a)} ${d.dem[a]}`).join(' ') + '</div>'
      + (d.ly_do ? `<div class="pp-foot">${esc(d.ly_do)}</div>` : '')
      + (d.khong_dinh_vi ? `<div class="pp-foot">⚠ ${d.khong_dinh_vi}/${d.truong} field ≠ KEEP `
                           + 'không đặt được vào box nào.</div>' : '')
      + '<table class="pp-tbl"><thead><tr><th>hạng mục</th>'
      + hds.map((a) => `<th class="num">${tag(a)}</th>`).join('') + '</tr></thead><tbody>'
      + Object.entries(d.theo_hang_muc).map(([code, m]) =>
          `<tr><td>${esc(code)}</td>` + hds.map((a) => `<td class="num">${m[a] || ''}</td>`).join('')
          + '</tr>').join('')
      + '</tbody></table>'
      + '<div class="pp-legend">' + THU_TU_HD.map((a) =>
          `<span><i class="hdO" style="--hd:${MAU_HD[a].mau}"></i>${MAU_HD[a].ten}</span>`).join('')
      + `<span><i class="hdO" style="--hd:${MAU_CHUNG_THUC}"></i>con dấu / chữ ký (che cả phần tử)</span>`
      + '</div>'
      + '<div class="pp-foot">Mọi field pii-core thấy trong tài liệu, kể cả KEEP (không bị che). '
      + 'Field nằm trong con dấu/chữ ký không có ô riêng; ô chồng nhau đã cắt, hành động '
      + 'nghiêm hơn giữ phần chung (ANONYMISE › PSEUDONYMISE › KEEP). '
      + 'Ô ghi hạng mục và token thay vào; đếm theo field, không theo box. Hình và logo '
      + '(che cả phần tử) xem ở lớp "⬛ che".</div>';
  }
  el.innerHTML = html;
  const chu = document.getElementById('chunks');
  chu.parentNode.insertBefore(el, chu);
}

on('layTruong', 'click', (e) => {
  state.truongOn = !state.truongOn;
  e.currentTarget.classList.toggle('on', state.truongOn);
  if (state.truongOn && !state.truong) { taiTruong(); return; }
  dungBangTruong();
  drawOverlay();
});
if (state.truongOn) document.getElementById('layTruong')?.classList.add('on');

/* Rê lên ô đen → nói vì sao nó bị che. Không có lời giải thích thì người soát
   không phân biệt được ô che đúng với ô che nhầm. */
on('overlay', 'mousemove', (ev) => {
  const cv = ev.currentTarget;
  const lop = state.truongOn && state.truong ? state.truong : state.cheOn && state.che ? state.che : null;
  if (!lop) { cv.title = ''; return; }
  const r = cv.getBoundingClientRect();
  const fx = (ev.clientX - r.left) / r.width, fy = (ev.clientY - r.top) / r.height;
  const v = lop.vung.find((x) => x.page === state.page && _trongO(x, fx, fy));
  cv.title = !v ? '' : v.action === 'KEEP' ? `${v.code} · KEEP (không che)`
    : `${nhanChe(v)} · ${v.code} · ${v.action} · ${LUAT_CHE[v.luat] || v.luat}`;
});

function toggleLayer(k, btn) {
  state.layers[k] = !state.layers[k];
  btn.classList.toggle('on', state.layers[k]);
  drawOverlay();
}

/* Chuyển trang do `ThanhTaiLieu` lo (docbar.js) — nó gọi `nguonAnhTrang
   .doiTrang`, tức cũng chính `showPage`. Gắn thêm ở đây là gọi hai lần. */

/* Cửa sổ đổi cỡ ⇒ canvas co theo CSS, nhưng nét vẽ phải vẽ lại cho sắc. */
window.addEventListener('resize', () => { if (state.docId) drawOverlay(); });

function esc(s) {
  return String(s).replace(/[&<>"]/g,
    (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[m]));
}

loadTree();

/* ── file manager ─────────────────────────────────────────────────────── */

/* Duyệt thư mục hồ sơ THẬT trên máy, chạy OCR cho tệp chưa chạy.
 *
 * Vì sao là lớp phủ chứ không phải một cột bên cạnh: duyệt tệp và soát kết
 * quả là hai việc khác nhau, ghép vào một màn hình thì cả hai đều chật. Mở
 * ra để tìm, chọn xong thì đóng lại và toàn màn hình dành cho việc soát.
 */
const fm = { path: '', dang_chay: false, es: null, chon: null };

function fmShow(on) {
  $('fmOverlay').hidden = !on;
  if (on) { fmLoad(fm.path); return; }

  /* Đóng giữa lúc đang chạy: đóng luôn EventSource và gỡ cờ.
   *
   * Không làm thì kết nối treo mãi và `fm.dang_chay` kẹt ở true — mở lại
   * thì mọi cú bấm bị `if (fm.dang_chay) return` nuốt im lặng, không có
   * thông báo nào. Đúng triệu chứng "bị khoá luôn". */
  if (fm.es) { fm.es.close(); fm.es = null; }
  fm.dang_chay = false;
  $('fmProg').hidden = true;
}

async function fmLoad(path) {
  const r = await fetch(`/api/browse?path=${encodeURIComponent(path)}`);
  if (!r.ok) return;
  const d = await r.json();
  fm.path = d.path;
  $('fmPath').textContent = '/' + (d.path || '');
  $('fmUp').disabled = d.at_root;

  const list = $('fmList');
  list.textContent = '';

  for (const dir of d.dirs) {
    list.appendChild(fmRow({
      icon: '📁', name: dir.name, meta: `${dir.n} mục`,
      onclick: () => fmLoad(dir.path),
    }));
  }
  for (const f of d.files) {
    const daChay = f.verity || f.pro || f.vision;
    const row = fmRow({
      icon: { ocr: '📄', office: '📝' }[f.kind] || '📎',
      name: f.name,
      /* Nhãn cho tệp không OCR thẳng được — nói rõ VÌ SAO không có chấm,
         thay vì để người dùng đoán là công cụ hỏng. */
      meta: f.kind === 'office' ? fmSize(f.size) + ' · xem được'
          : f.kind === 'other' ? fmSize(f.size)
          : fmSize(f.size),
      cls: f.can_ocr ? (daChay ? 'done' : 'todo')
         : f.kind === 'office' ? 'xemduoc' : 'khac',
      /* Bấm vào TÊN tệp: chạy engine đang chọn nếu nó chưa chạy, mở xem nếu
       * rồi. Bấm vào từng CHẤM: chạy đúng engine đó.
       *
       * Bản đầu coi "đã chạy" là `verity || pro || vision`, nên chạy xong
       * một engine là tệp khoá luôn — không còn cách nào chạy hai engine
       * kia. Với ba engine thì "đã chạy" phải tính THEO TỪNG ENGINE. */
      onselect: () => fmPeek(f),
      onclick: f.can_ocr
        ? () => {
            const eng = $('fmEngine').value;
            if (f[eng]) fmOpen(f); else fmRun(f, eng);
          }
        /* Tệp Office không chạy OCR thẳng được, nhưng ĐỌC được: server dựng
         * docx/xlsx thành HTML (giữ cả ảnh nhúng). Trước đây bấm vào không
         * có gì xảy ra, người dùng không phân biệt được "không đọc được"
         * với "công cụ hỏng". */
        /* Tệp không chạy OCR được vẫn mở ở MÀN HÌNH CHÍNH với đủ
         * Markdown/JSON/neo vị trí — không còn lớp phủ riêng kém chức năng. */
        : f.kind === 'office'
        ? () => { fmShow(false); openLocalFile(f.path, f.name); }
        : null,
    });
    if (f.can_ocr) {
      const dots = document.createElement('div');
      dots.className = 'fmDots';
      for (const [k, nhan] of [['verity', 'ADE Verity'], ['pro', 'ADE Pro'],
                               ['vision', 'Apple Vision']]) {
        const s = document.createElement('button');
        s.className = 'fmDot' + (f[k] ? ' on' : '');
        s.title = f[k]
          ? `${nhan}: đã chạy — bấm để xem`
          : `${nhan}: chưa chạy — bấm để chạy`;
        s.onclick = (ev) => {
          ev.stopPropagation();          // không kích hoạt onclick của cả hàng
          if (f[k]) { fmOpen(f, k); } else { fmRun(f, k); }
        };
        dots.appendChild(s);
      }
      row.insertBefore(dots, row.querySelector('.sz'));
      /* Nút xem trước: xem NỘI DUNG trước khi quyết định trả tiền cho ADE.
       * Không có nút này thì cách duy nhất để biết trong tệp có gì là chạy
       * một engine — tức là đã tiêu tiền rồi mới biết có đáng không. */
      const eye = document.createElement('button');
      eye.className = 'fmEye';
      eye.textContent = '👁';
      eye.title = 'Xem trước (không chạy OCR, không tốn tiền)';
      eye.onclick = (ev) => {
        ev.stopPropagation();
        fmShow(false);
        openLocalFile(f.path, f.name);
      };
      row.insertBefore(eye, row.querySelector('.sz'));
    }
    list.appendChild(row);
  }
}

/* Một lần bấm CHỌN, hai lần bấm MỞ.
 *
 * Trước đây một lần bấm là mở luôn, nên không có lúc nào để nhìn vào tệp
 * trước khi quyết định — và với ADE thì quyết định đó tốn tiền. Nay giống
 * mọi trình quản lý tệp: chọn để xem, mở khi đã chắc.
 *
 * Thư mục vẫn đi bằng MỘT lần bấm: duyệt cây là thao tác lặp lại liên tục,
 * bắt bấm đúp mỗi cấp thì mệt tay và chẳng bảo vệ được gì.
 */
function fmRow({ icon, name, meta, cls = '', onclick, onselect }) {
  const el = document.createElement('div');
  el.className = 'fmRow ' + cls;
  el.innerHTML = `<span class="ic">${icon}</span>`
    + `<span class="nm"></span><span class="sz"></span>`;
  el.querySelector('.nm').textContent = name;
  el.querySelector('.sz').textContent = meta;

  if (onselect) {
    el.onclick = () => {
      document.querySelectorAll('.fmRow.sel').forEach(
        (r) => r.classList.remove('sel'));
      el.classList.add('sel');
      onselect();
    };
    el.ondblclick = onclick || null;
  } else if (onclick) {
    el.onclick = onclick;
  } else {
    el.style.cursor = 'default';
  }
  return el;
}

/* Xem trước tệp đang chọn. Gọi `/api/peek` (rẻ) chứ không `/api/extract`
 * (đọc toàn bộ) — hàm này chạy mỗi lần người dùng đổi lựa chọn. */
let peekSeq = 0;
async function fmPeek(f) {
  fm.chon = f;
  const seq = ++peekSeq;
  $('fmPrevEmpty').hidden = true;
  $('fmPrevBox').hidden = false;
  $('fmPrevName').textContent = f.name;
  $('fmPrevMeta').textContent = 'đang đọc…';
  $('fmPrevThumb').innerHTML = '';
  $('fmPrevText').textContent = '';

  let d;
  try {
    const r = await fetch(`/api/peek?path=${encodeURIComponent(f.path)}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    d = await r.json();
  } catch (e) {
    $('fmPrevMeta').textContent = `không xem trước được (${e.message})`;
    return;
  }
  /* Bỏ kết quả đến muộn: người dùng bấm nhanh qua nhiều tệp thì các yêu
   * cầu về không đúng thứ tự, và khung xem trước sẽ hiện tệp CŨ đè lên tệp
   * đang chọn — sai âm thầm. */
  if (seq !== peekSeq) return;

  const phan = [fmSize(d.size)];
  if (d.so_trang > 1) phan.push(`${d.so_trang} trang`);
  if (d.can_ocr) phan.push('cần OCR (không có lớp chữ)');
  $('fmPrevMeta').textContent = phan.join(' · ');

  if (d.co_anh) {
    const im = new Image();
    im.src = `/api/peek/thumb?path=${encodeURIComponent(f.path)}`;
    im.alt = 'trang đầu';
    $('fmPrevThumb').appendChild(im);
  }
  $('fmPrevText').textContent = d.text || '';

  /* Nút "Quét OCR" chỉ có nghĩa với tệp OCR được; tệp docx/xlsx đọc thẳng
     nên chỉ cần "Mở tệp". */
  $('fmPrevScan').hidden = !f.can_ocr;
}

const fmSize = (n) =>
  n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.round(n / 1024) + ' KB';

function fmOpen(f, engine) {
  fmShow(false);
  if (engine) setEngineButtons(engine);
  /* Nạp lại cây bên trái trước: tài liệu vừa chạy chưa có trong đó, và
     `loadDoc` chỉ tô đậm mục đã tồn tại. */
  loadTree().then(() => loadDoc(f.doc_id));
}

/* Chạy OCR với tiến độ THẬT từ server (SSE).
 *
 * Không dùng hoạt hình chạy cho có: một thanh giả chạy đều rồi đứng ở 90%
 * nói dối về việc đang xảy ra, và khi engine lỗi thì nó vẫn chạy. Mỗi bước ở
 * đây là một sự kiện server thực sự gửi.
 */
function fmRun(f, engine) {
  if (fm.dang_chay) return;                 // một lượt một, kẻo bấm nhiều lần tốn tiền thật
  engine = engine || $('fmEngine').value;

  /* ADE tính tiền thật. Hỏi trước khi gửi, kèm giá — bấm nhầm một chấm là
     mất tiền, và người dùng không có cách nào lấy lại. Vision cục bộ nên
     không hỏi. */
  if (engine !== 'vision') {
    const gia = engine === 'pro' ? '0,9' : '0,3';
    const ten = engine === 'pro' ? 'ADE Pro' : 'ADE Verity';
    if (!confirm(`Chạy ${ten} cho "${f.name}"?\n\n`
                 + `Gửi tệp tới LandingAI và tính ${gia} credits mỗi trang.`)) {
      return;
    }
  }
  fm.dang_chay = true;

  $('fmProg').hidden = false;
  $('fmProgName').textContent = f.name;
  $('fmProgMsg').className = 'fmProgMsg';
  $('fmProgMsg').textContent = 'đang bắt đầu…';
  $('fmBarFill').style.width = '2%';
  $('fmProgPct').textContent = '';

  const es = new EventSource(
    `/api/run?path=${encodeURIComponent(f.path)}&engine=${engine}`);
  fm.es = es;

  es.addEventListener('step', (e) => {
    const d = JSON.parse(e.data);
    $('fmBarFill').style.width = d.pct + '%';
    $('fmProgPct').textContent = d.pct + '%';
    $('fmProgMsg').textContent = d.msg;
  });
  es.addEventListener('done', (e) => {
    const d = JSON.parse(e.data);
    $('fmBarFill').style.width = '100%';
    $('fmProgPct').textContent = '100%';
    $('fmProgMsg').textContent = `xong sau ${d.seconds}s`;
    es.close(); fm.es = null; fm.dang_chay = false;
    fmLoad(fm.path);                        // cập nhật chấm trạng thái

    /* MỞ LUÔN kết quả vừa chạy.
     *
     * Trước đây chỉ cập nhật chấm rồi dừng: người dùng bấm một lần thấy
     * thanh tiến trình chạy xong mà màn hình không đổi gì, phải bấm lần
     * hai mới mở được. Chạy OCR và xem kết quả là MỘT ý định, không phải
     * hai — tách ra chỉ khiến lần bấm đầu trông như không ăn.
     *
     * Chờ một nhịp để người dùng kịp thấy "xong sau Ns" trước khi lớp phủ
     * đóng; nhanh quá thì thanh tiến trình nháy rồi biến mất, và không ai
     * biết nó đã chạy bao lâu.
     */
    setTimeout(() => {
      $('fmProg').hidden = true;
      fmOpen({ ...f, doc_id: d.doc_id || f.doc_id }, engine);
    }, 900);
  });
  es.addEventListener('error', (e) => {
    /* Hai loại lỗi khác nhau: `e.data` có nghĩa là server báo lỗi nghiệp vụ;
       không có nghĩa là kết nối đứt. Gộp làm một thì người dùng không biết
       nên thử lại hay đi sửa cấu hình. */
    const msg = e.data ? JSON.parse(e.data).msg : 'mất kết nối tới server';
    $('fmProgMsg').className = 'fmProgMsg err';
    $('fmProgMsg').textContent = msg;
    es.close(); fm.es = null; fm.dang_chay = false;
  });
}

/* ── Chạy cả thư mục (hoặc tệp zip) ────────────────────────────────────
 *
 * Luôn đi hai bước: DỰ TOÁN rồi mới hỏi. Chạy một thư mục bằng ADE Pro là
 * con số hàng chục đô la và không có cách nào lấy lại — người dùng phải
 * thấy số tệp, số trang và số tiền TRƯỚC khi bấm đồng ý.
 *
 * Dự toán không tính tệp đã chạy engine đó, vì chúng sẽ bị bỏ qua; tính
 * vào là nói quá cả thời gian lẫn tiền.
 */
async function fmBatch() {
  if (fm.dang_chay) return;
  const engine = $('fmEngine').value;

  let d;
  try {
    const r = await fetch(`/api/batch/preview?path=${encodeURIComponent(fm.path)}`
                          + `&engine=${engine}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    d = await r.json();
  } catch (e) {
    alert(`Không dự toán được: ${e.message}`);
    return;
  }

  if (!d.so_tep) {
    alert('Mọi tệp trong thư mục này đã chạy engine đó rồi.');
    return;
  }

  const ten = { vision: 'Apple Vision', verity: 'ADE Verity', pro: 'ADE Pro' }[engine];
  const tien = d.mien_phi ? 'miễn phí (chạy cục bộ)'
                          : `TỐN $${d.chi_phi_usd} — tiền thật, không hoàn lại`;
  if (!confirm(
      `Chạy ${ten} cho ${d.so_tep} tệp (${d.so_trang} trang)?\n\n`
      + `${tien}\n\n`
      + `Ví dụ: ${d.vi_du.slice(0, 4).join(', ')}${d.so_tep > 4 ? '…' : ''}`)) {
    return;
  }

  fm.dang_chay = true;
  $('fmProg').hidden = false;
  $('fmProgMsg').className = 'fmProgMsg';
  $('fmProgName').textContent = `0 / ${d.so_tep}`;
  $('fmProgMsg').textContent = 'đang bắt đầu…';
  $('fmBarFill').style.width = '1%';

  const es = new EventSource(
    `/api/batch/run?path=${encodeURIComponent(fm.path)}&engine=${engine}`);
  fm.es = es;
  let loi = 0;

  es.addEventListener('file_start', (e) => {
    const x = JSON.parse(e.data);
    $('fmProgName').textContent = `${x.i} / ${x.n}`;
    $('fmProgPct').textContent = `${x.pct}%`;
    $('fmBarFill').style.width = `${Math.max(1, x.pct)}%`;
    $('fmProgMsg').textContent = x.name;
  });
  es.addEventListener('file_error', (e) => {
    /* Một tệp lỗi KHÔNG dừng cả lượt — báo rồi đi tiếp. Dừng hẳn nghĩa là
       một tệp hỏng chặn mất hàng trăm tệp lành. */
    loi += 1;
    const x = JSON.parse(e.data);
    console.warn('[batch]', x.name, x.msg);
  });
  es.addEventListener('batch_done', (e) => {
    const x = JSON.parse(e.data);
    $('fmBarFill').style.width = '100%';
    $('fmProgPct').textContent = '100%';
    $('fmProgMsg').className = 'fmProgMsg' + (x.loi ? ' err' : '');
    $('fmProgMsg').textContent =
      `xong ${x.xong} tệp sau ${x.seconds}s` + (x.loi ? ` · ${x.loi} lỗi` : '');
    es.close(); fm.es = null; fm.dang_chay = false;
    fmLoad(fm.path);
  });
  es.addEventListener('error', () => {
    $('fmProgMsg').className = 'fmProgMsg err';
    $('fmProgMsg').textContent = 'mất kết nối tới server';
    es.close(); fm.es = null; fm.dang_chay = false;
  });
}

on('fmPrevOpen', 'click', () => {
  const f = fm.chon;
  if (!f) return;
  if (f.can_ocr) {
    /* Tệp OCR được: mở bản engine đang chọn nếu đã chạy, không thì đọc
       thẳng — KHÔNG tự chạy OCR. Chạy là việc của nút "Quét OCR"; gộp hai
       hành động vào một nút là cách bấm nhầm mất tiền. */
    const eng = $('fmEngine').value;
    if (f[eng]) fmOpen(f, eng);
    else { fmShow(false); openLocalFile(f.path, f.name); }
  } else {
    fmShow(false);
    openLocalFile(f.path, f.name);
  }
});

on('fmPrevScan', 'click', () => {
  const f = fm.chon;
  if (!f || !f.can_ocr) return;
  const eng = $('fmEngine').value;
  if (f[eng]) fmOpen(f, eng); else fmRun(f, eng);
});

on('fmBatch', 'click', fmBatch);
on('btnBrowse', 'click', () => fmShow(true));
on('fmClose', 'click', () => fmShow(false));
on('fmUp', 'click', () => {
  const i = fm.path.lastIndexOf('/');
  fmLoad(i > 0 ? fm.path.slice(0, i) : '');
});
on('fmOverlay', 'click', (e) => {
  if (e.target === document.getElementById('fmOverlay')) fmShow(false);
});


/* ── Phơi ra window (xem web/src/lib/bridge.js) ─────────────────────────
 *
 * Vite gộp tệp này vào một module nên mọi thứ ở trên là riêng tư. Ba thứ
 * dưới đây cần gọi được từ ngoài; phơi ra có tên rõ ràng thay vì bỏ
 * `type="module"` để tất cả lại thành global.
 */
globalThis.openLocalFile = openLocalFile;
globalThis.veLaiOverlay = drawOverlay;
/* Mở một tài liệu theo doc_id mà không phải mò đúng nút trong cây.
   Cần cho test giao diện: cây là danh sách ảo, có tài liệu nằm trong nhánh
   chưa mở, nên "bấm vào tệp X" không phải một thao tác một bước. */
globalThis.moDoc = loadDoc;
Object.defineProperty(globalThis, '__state', { get: () => state });

/* Kéo-để-di-chuyển trang: gắn một lần, ngay khi mô-đun nạp xong. */
ganKeoDiChuyen();
