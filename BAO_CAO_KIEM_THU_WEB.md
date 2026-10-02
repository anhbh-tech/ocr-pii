# Báo cáo kiểm thử giao diện web đối chiếu (ocr-lab)

Ngày 16/09/2026 · Chromium thật qua Playwright · kho `~/.private/ade_out`
(618 tệp parse, 10 hồ sơ)

---

## Tóm tắt cho người quyết định

Anh chỉ ra một triệu chứng: chunk `5 - table_cell` hiện `d>Nhãn hi` thay vì
`Nhãn hiệu`. Truy đến cùng thì đó **không phải lỗi hiển thị** mà là lỗi cắt
dữ liệu, và nó **không chỉ ở một chunk**:

| | Số đo |
|---|---|
| Chunk bị cắt lệch trên toàn kho | **1.363 / 2.526 (54%)** |
| Tệp dính lỗi | 42 / 618 |
| Mức lệch | 1–6 ký tự, **cộng dồn** theo tài liệu |

Mức nghiêm trọng: đây là lỗi **sai âm thầm**. Chữ cắt ra vẫn trông như chữ
thật (`d>Nhãn hi` đọc thoáng vẫn ra "Nhãn hi"), nên người soát bấm 👍 cho
một bản ghi **không khớp tài liệu gốc**. Công cụ này tồn tại để sinh ground
truth cho hồ sơ khách hàng — dữ liệu sai ở đây đi thẳng vào mọi thứ dùng nó
về sau.

Đã sửa cả hai lỗi, có test khoá lại. Chi tiết bên dưới.

---

## Lỗi 1 — Offset đếm sai đơn vị (NGHIÊM TRỌNG, đã sửa)

### Triệu chứng
Tài liệu `158a05938328657c` (`TV9012_Ket qua tra cuu 4 nhan_080825.docx`):

| Chunk | Web hiện | Đúng phải là |
|---|---|---|
| 5 - table_cell | `d>Nhãn hi` | `Nhãn hiệu` |
| 6 - table_cell | `d>Đối chứ` | `Đối chứng` |
| 7 - table_cell | `d>Khả năng bảo ` | `Khả năng bảo hộ` |
| 8 - table_cell | `">GLIMW` | `GLIMWICK` |
| 10 - table_cell | `">5` | `55%` |

### Nguyên nhân gốc
Engine sinh `grounding.range` bằng Python, nơi `len("👤")` = **1** (code
point). Web cắt bằng `String.prototype.slice`, nơi `"👤".length` = **2**
(UTF-16 code unit).

Tài liệu này có **19 emoji** (`👤 🏷 😀 🖼 📎 🪪 …`) trong phần đầu — nó là
ảnh chụp chat Messenger. Mỗi emoji đẩy mọi chunk phía sau lệch thêm 1 đơn vị.

Đo trực tiếp:
```
Python len (code point) : 4878
JS .length (UTF-16 unit): 4897     ← lệch 19, đúng bằng số emoji
```

Chunk ở offset 473 lẽ ra là `Nhãn hiệu`, nhưng JS cắt tại vị trí đó ra
`md[471:480]` = `d>Nhãn hi` — **trượt vào giữa thẻ `<td>`**.

Điểm đáng chú ý: **dữ liệu trên đĩa hoàn toàn đúng**. Tôi đã quét cả 618 tệp
parse, không tệp nào có offset sai. Lỗi sinh ra 100% ở lớp hiển thị.

### Vì sao nó sống sót lâu
`.slice()` đọc rất tự nhiên và cho kết quả **đúng trên 92% tài liệu** —
những tệp không có emoji. Chỉ tài liệu chứa ảnh chụp chat, biểu tượng cảm
xúc, hay ký tự ngoài BMP mới lộ ra. Thử tay vài tệp bất kỳ gần như chắc chắn
không gặp.

### Cách sửa
`web/app.js`:
- Thay `sliceMd` bằng `catMd`, cắt trên **mảng code point** đã dựng sẵn.
- `state.markdown` đổi thành accessor (`Object.defineProperty`): mỗi lần gán
  markdown thì mảng code point tự dựng lại. Có **4 chỗ** gán `state.markdown`
  (mở tài liệu / đổi engine / đọc tệp cục bộ / chạy xong OCR); để lập trình
  viên tự nhớ dựng cache là mời lỗi quay lại ở chỗ thứ 5.
- Cache dựng **một lần mỗi tài liệu**, không phải mỗi chunk: tài liệu
  `0ce8080050f84778` có 1.036 chunk, gọi `[...md]` trong hàm cắt sẽ quét lại
  43.592 ký tự một nghìn lần.

### Kiểm chứng sau khi sửa
Trên đúng tài liệu trong ảnh chụp:
```
5 - table_cell || Nhãn hiệu      ✓
6 - table_cell || Đối chứng      ✓
7 - table_cell || Khả năng bảo hộ ✓
8 - table_cell || GLIMWICK        ✓
10 - table_cell || 55%           ✓
```
Quét 6 tài liệu / **1.766 chunk**: 0 chunk còn mảnh thẻ HTML, 0 lỗi JS.

---

## Lỗi 2 — Span nuốt khoảng trắng (đã sửa)

Phát hiện trong lúc điều tra lỗi 1, không nằm trong báo cáo ban đầu.

### Triệu chứng
Tài liệu `c733b144942f3996`, chunk 3: web hiện **`Nhãnhiêu`** — dính liền,
trong khi dữ liệu gốc là `Nhãn hiêu`.

### Nguyên nhân gốc
`atomic_grounding` neo **từng từ**, nên ký tự phân cách nằm **ngoài** mọi
range:
```
'Nhãn'  [250, 254)
        ← dấu cách ở offset 254 không thuộc span nào
'hiêu'  [255, 259)
```
`renderSegments` nối các `<span>` liền nhau → mất dấu cách.

### Vì sao nó nguy hiểm hơn vẻ ngoài
Người soát nhìn thấy `Nhãnhiêu` sẽ bấm 👎 và sửa lại — trong khi **engine đã
đọc đúng**. Tức là lỗi hiển thị này tạo ra dữ liệu huấn luyện sai từ một
bản đọc đúng, và ghi đè lên chính thứ công cụ này sinh ra.

### Cách sửa
Phát hiện khoảng hở giữa các span và giữa span với biên chunk, chèn lại
phần chữ bị bỏ rơi dưới dạng text node (không phải `<span>` — nó không thuộc
từ nào nên không có toạ độ để tô sáng khi rê chuột).

---

## Lỗi 3 — docx hiện ô hình vỡ (đã sửa ở lượt trước)

`meta.pages` ghi `[{page:1}]` cho cả docx để báo cáo đếm được, nhưng
`/api/doc/{id}/page/1` trả 404 vì docx không có ảnh trang. Dải "Files" dựng
`<img>` trỏ vào endpoint đó → một ô vỡ ngay dưới tài liệu đang mở bình
thường, trông như tệp hỏng.

Sửa: ẩn dải Files khi tài liệu không có ảnh trang.

---

## Kết quả kiểm thử toàn bộ nút

Chromium thật, tài liệu `158a05938328657c`, bắt mọi `console.error`,
`pageerror`, request 4xx/5xx:

| Nhóm | Kết quả |
|---|---|
| Engine: ADE Verity / ADE Pro | ✓ đổi đúng, 35 chunk, markdown đổi theo engine |
| Engine: Apple Vision / Đọc tệp | ✓ làm mờ đúng (tài liệu chưa chạy) |
| Zoom: − + 100% ⤢ | ✓ 75% → 50% → 100% → 57% |
| Chuyển trang ‹ › | ✓ giữ nguyên mức phóng |
| Tab Markdown / JSON | ✓ |
| Lớp phủ ▭ chunk / ▬ span | ✓ |
| Nút ✎ đã sửa | ✓ |
| Nút trên thẻ: 👍 👎 # Raw | ✓ 3 nút, Raw mở đúng nội dung |
| Đổi giao diện ◐ | ✓ |
| Dải Files | ✓ |
| **Lỗi console / JS / mạng** | **0** |

---

## Bài học cho lần sau

**1. Đừng tin `.slice()` trên chuỗi có thể chứa emoji.**
Mọi offset đi qua ranh giới Python ↔ JavaScript đều phải thống nhất đơn vị.
Python đếm code point, JS đếm UTF-16 code unit — hai thứ khác nhau và chỉ
khác nhau trên đúng những dữ liệu hiếm gặp lúc thử tay.

**2. Ràng buộc dữ liệu dẫn xuất vào chỗ gán, không vào ý thức người viết.**
Cache code point được móc vào setter chứ không để lập trình viên tự dựng.
Bốn chỗ gán markdown thì xác suất quên là bốn lần.

**3. Dấu hiệu khách quan thay cho ground truth.**
Không có bản chuẩn để so từng chunk, nhưng có bất biến: *một ô bảng không
bao giờ bắt đầu bằng `d>` hay `">`*. Bất biến đó đủ để quét cả kho tự động
và đủ để viết test.

**4. Lỗi "sai âm thầm" phải được ưu tiên hơn lỗi làm sập.**
Trang trắng thì ai cũng thấy. `d>Nhãn hi` thì trông như dữ liệu thật, và nó
đi thẳng vào hồ sơ khách hàng. Loại lỗi này xứng đáng có test riêng.

---

## Test đã thêm

`tests/test_range_codepoint.py` (10 test):
- Chạy hàm cắt **thật** trong Node, không chép lại logic (chép lại thì test
  vẫn xanh sau khi ai đó sửa hỏng `app.js`).
- Chặn `state.markdown.slice(` quay lại `app.js`.
- Quét tài liệu **thật có emoji** trong kho, kiểm bất biến "không chunk nào
  bắt đầu bằng mảnh thẻ".
- Mỗi test có bước tự chứng minh mẫu thử đúng là mẫu dính lỗi — nếu không,
  test xanh mà vô nghĩa.

`tests/test_docbar_ui.py` + `tests/test_docbar_office_ui.py` (12 test, lượt
trước): lái Chromium thật, đo bề rộng ảnh và cỡ chữ sau khi bấm.

**Tổng: 357 test pass.**

---

## Còn tồn đọng

- Server tailnet chạy foreground trong phiên Hermes, sẽ tắt khi phiên kết
  thúc hoặc máy khởi động lại. Chưa dựng launchd agent (đang chờ anh quyết,
  vì kho chứa hồ sơ khách hàng nên mở cổng vĩnh viễn là đánh đổi bảo mật).

---

## Xác minh cuối trên bản đã deploy

Bản tailnet đã dựng lại (vân tay `e930498a534c` → `46ff9c90cfb7`) và kiểm
trên chính trình duyệt sống, không phải chỉ qua test:

| Tài liệu | Chunk | Mảnh thẻ còn lại |
|---|---|---|
| `158a05938328657c` | 35 | 0 |
| `c733b144942f3996` | 23 | 0 |
| `0248508db31909e1` | 19 | 0 |
| `0ce8080050f84778` | 1.036 | 0 |
| `21ef36eaffaa5d32` | 96 | 0 |
| `3639afd86c70ef2b` | 557 | 0 |
| **Tổng** | **1.766** | **0** |

- Chunk từng hỏng dấu cách: `Nhãn hiêu` ✓ (không còn `Nhãnhiêu`)
- 416 span vẫn rê chuột được — fix không phá mất mức neo thứ hai
- 0 lỗi JS / console / request hỏng

Đối chiếu trực tiếp với ảnh chụp ban đầu:

| Trước | Sau |
|---|---|
| `d>Nhãn hi` | `Nhãn hiệu` |
| `d>Đối chứ` | `Đối chứng` |
| `d>Khả năng bào` | `Khả năng bảo hộ` |
| `">GLIMW` | `GLIMWICK` |
| `">5` | `55%` |

