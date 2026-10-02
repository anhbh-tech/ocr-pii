# `POST /api/classify` — tài liệu này đi đường nào

Hợp đồng `ocr-lab.classify/1`. Bên gọi: jev ai (Vercel AI router), trong bước
kiểm từng node của màn hình bpmn_editor theo hồ sơ:

```
quét tệp hồ sơ → /api/classify → (ocr-lab nếu route = "ocr") → agent đọc context → so với yêu cầu của node
```

Mã: `src/ocr_lab/classify_api.py` (logic), `scripts/serve_classify.py`
(server). JSON Schema: [`classify-api.schema.json`](classify-api.schema.json),
cũng phục vụ tại `GET /api/classify/schema`. Test:
`tests/test_classify_api.py`.

## Chạy

```bash
make classify-api          # = uv run python scripts/serve_classify.py → 127.0.0.1:8812
```

Server **chỉ nghe `127.0.0.1`**, ghi cứng, không có cờ đổi host. Endpoint nhận
đường dẫn tuyệt đối bất kỳ trên máy nên không được lộ ra mạng; jev ai phải
chạy cùng máy (hoặc tự dựng đường hầm riêng, có xác thực).

## Gửi tài liệu

Hai cách, chọn theo `Content-Type`:

| Cách | Request | Ghi chú |
|---|---|---|
| Tải nội dung lên | thân = byte của tệp (`Content-Type: application/octet-stream`); tên tệp (tuỳ chọn) ở `?filename=` | Tệp **không** bị ghi ra đĩa — phân loại hoàn toàn trong bộ nhớ. **Không** nhận `multipart/form-data` (`FormData`) → 415: gửi thẳng byte của tệp, ví dụ `fetch(url, {method: "POST", body: file})` |
| Trỏ tệp cục bộ | `Content-Type: application/json`, thân `{"path": "/đường/dẫn/tuyệt/đối"}` | Đọc trên máy chạy server |

```bash
curl --data-binary @hop_dong.pdf -H 'Content-Type: application/octet-stream' \
     'http://127.0.0.1:8812/api/classify?filename=hop_dong.pdf'

curl -H 'Content-Type: application/json' -d '{"path": "/abs/hop_dong.pdf"}' \
     http://127.0.0.1:8812/api/classify
```

Loại tài liệu được nhận ra **từ byte của tệp**, không từ đuôi tên: một PDF đặt
tên `.docx` vẫn là PDF. `filename` chỉ để trả lại trong `source.name`.

### Mã HTTP

| Mã | Khi nào |
|---|---|
| 200 | Mọi tệp đã nhận được — **kể cả tệp rỗng, hỏng, có mật khẩu, định dạng lạ**. Những ca đó trả kết quả xác định với `confidence: 0` (xem dưới). |
| 400 | `path` không tuyệt đối, hoặc không phải tệp (thư mục…); `Host` không phải `127.0.0.1`/`localhost` |
| 404 | `path` không tồn tại |
| 413 | Tệp vượt 200 MB |
| 415 | `Content-Type: multipart/form-data` — gửi thẳng byte của tệp kèm `?filename=` |
| 422 | Thân JSON sai khuôn (thiếu `path`, thừa khoá, không phải JSON) |

Nói cách khác: lỗi 4xx là lỗi **của request**; tài liệu tệ đến đâu cũng ra 200
với một kết quả đúng khuôn.

## Khuôn trả về

```ts
/** ocr-lab.classify/1 — khớp docs/classify-api.schema.json */
type Route = "read_direct" | "ocr" | "agent_context";

type Kind =
  | "born_digital_pdf"  // PDF có lớp text thật ở mọi trang có nội dung; mọi trang gần trống → agent_context
  | "scanned_pdf"       // PDF mà nội dung nằm trong ảnh, không trang nào có text dùng được
  | "hybrid_pdf"        // PDF lẫn cả hai — xem pages_needing_ocr
  | "docx_text"         // docx gõ chữ, không có ảnh đáng kể (gần trống → agent_context)
  | "docx_image_only"   // docx chỉ là ảnh dán vào (ảnh chụp đoạn chat, bản scan)
  | "docx_hybrid"       // docx có chữ VÀ ảnh lớn (CCCD, biên lai dán kèm)
  | "image"             // ảnh rời: ảnh chụp, ảnh quét, ảnh màn hình
  | "text"              // tệp văn bản thuần UTF-8 (gần trống → agent_context)
  | "unsupported"       // định dạng chưa phân loại: xlsx, pptx, .doc/.xls cũ, zip, nhị phân lạ
  | "unreadable";       // rỗng, hỏng, có mật khẩu, PDF 0 trang

type PageKind =
  | "text_layer"  // có lớp text đọc được
  | "image"       // nội dung nằm trong ảnh
  | "mixed"       // cả hai (chỉ gặp ở docx_hybrid)
  | "blank";      // gần như không có gì (< 50 ký tự, không ảnh đáng kể);
                  // route read_direct nếu tệp còn trang chữ, agent_context nếu cả tệp đều blank

interface Page {
  index: number;               // 0-based — trang đầu là 0
  kind: PageKind;
  route: Route;
  confidence: number;          // [0, 1], xem "Độ tin cậy"
  reason: string;              // tiếng Việt, cho người đọc
  chars: number;               // số ký tự lớp text (0 với ảnh rời)
  image_cover: number;         // phần diện tích trang bị ảnh phủ; docx nhiều trang ảnh có thể > 1
  images: number | null;       // số ảnh trong thân docx; null với PDF/ảnh
  text_regions: number | null; // số vùng chữ bộ dò thấy; chỉ ảnh rời, null nếu không dò được
}

interface ClassifyResult {
  contract: "ocr-lab.classify/1";
  kind: Kind;
  route: Route;                // quyết định cho CẢ tệp
  confidence: number;          // [0, 1] = min(pages[].confidence); 0 với unreadable/unsupported
  reason: string;
  source: { name: string; format: string; bytes: number };  // name đã chuẩn hoá NFC
  pages: Page[];               // PDF: mỗi trang một phần tử; docx/ảnh/text: đúng một; lỗi: rỗng
  pages_needing_ocr: number[]; // index các trang có route "ocr"
  signals: {
    page_count: number;
    text_layer_pages: number;
    image_pages: number;
    mixed_pages: number;
    blank_pages: number;
    chars_total: number;
    text_layer_coverage: number; // text_layer_pages / page_count
    route_agreement: number;     // phần trang có route trùng route cả tệp
    images: number | null;
    text_regions: number | null;
  };
  error: string | null;        // chỉ khác null khi kind = "unreadable"
}
```

`source.format` là định dạng nhận từ byte: `pdf`, `docx`, `xlsx`, `pptx`,
`zip`, `ole`, `png`, `jpeg`, `heic`, …, `text`, `empty`, `unknown`. Đây là
chuỗi để ghi log, **không** phải enum để rẽ nhánh — rẽ nhánh theo `kind` và
`route`.

Phiên bản: thêm trường mới không đổi `contract`; đổi tên, bỏ trường hay đổi
nghĩa một giá trị thì tăng lên `ocr-lab.classify/2`. Bên gọi nên bỏ qua trường
lạ và kiểm `contract`.

### Ví dụ — PDF lai 2 trang (dựng tổng hợp)

```json
{
  "contract": "ocr-lab.classify/1",
  "kind": "hybrid_pdf",
  "route": "ocr",
  "confidence": 1.0,
  "reason": "PDF lai 2 trang: 1 trang có lớp text đọc thẳng được, 1 trang nội dung nằm trong ảnh — chỉ OCR các trang trong pages_needing_ocr",
  "source": {"name": "ho_so_vay.pdf", "format": "pdf", "bytes": 676235},
  "pages": [
    {"index": 0, "kind": "text_layer", "route": "read_direct", "confidence": 1.0,
     "reason": "579 ký tự trong lớp text", "chars": 579, "image_cover": 0.0,
     "images": null, "text_regions": null},
    {"index": 1, "kind": "image", "route": "ocr", "confidence": 1.0,
     "reason": "ảnh phủ 86% trang, chỉ 0 ký tự — nội dung nằm trong ảnh (chữ ký số / chú thích không phải nội dung)",
     "chars": 0, "image_cover": 0.8608, "images": null, "text_regions": null}
  ],
  "pages_needing_ocr": [1],
  "signals": {"page_count": 2, "text_layer_pages": 1, "image_pages": 1,
              "mixed_pages": 0, "blank_pages": 0, "chars_total": 579,
              "text_layer_coverage": 0.5, "route_agreement": 0.5,
              "images": null, "text_regions": null},
  "error": null
}
```

## Đường đi

| `kind` | `route` | Vì sao |
|---|---|---|
| `born_digital_pdf` | `read_direct` | Lớp text là bản gốc — chính xác hơn mọi OCR. Trang `blank` lẫn giữa các trang chữ cũng `read_direct` |
| `born_digital_pdf`, mọi trang `blank` | `agent_context` | Không có lớp text lẫn ảnh đáng kể (vd. chữ vẽ thành đường cong) — đọc thẳng chỉ ra rỗng, để agent xem |
| `scanned_pdf` | `ocr` | Nội dung chỉ nằm trong ảnh |
| `hybrid_pdf` | `ocr` | Chỉ OCR `pages_needing_ocr`; các trang còn lại đọc thẳng (`pages[].route`) |
| `docx_text` | `read_direct` | |
| `docx_text`, < 50 ký tự (`blank`) | `agent_context` | Docx gần trống, không ảnh đáng kể — không có gì để đọc thẳng |
| `docx_image_only` | `ocr` | |
| `docx_hybrid` | `ocr` | Phần chữ đọc thẳng được, nhưng chữ trong ảnh (CCCD, biên lai) chỉ OCR mới lấy được. Thà OCR thừa còn hơn mất nội dung im lặng |
| `image`, ≥ 2 vùng chữ | `ocr` | Ảnh giấy tờ / ảnh quét / ảnh màn hình |
| `image`, 0–1 vùng chữ | `agent_context` | Ảnh chụp cảnh vật/sản phẩm: OCR không thu được gì, agent phải tự nhìn. Một vùng lẻ thường là nhiễu hoa văn (`MIN_VUNG_CHU` trong `embedded_images.py`) |
| `image`, không dò được | `ocr`, confidence 0,5 | Thiếu RapidOCR, hoặc định dạng Pillow không giải mã (HEIC). Mặc định OCR vì chạy tại máy, rẻ |
| `text` | `read_direct` | |
| `text`, < 50 ký tự (`blank`) | `agent_context` | |
| `unsupported` | `agent_context`, confidence 0 | Chưa có tín hiệu để định tuyến |
| `unreadable` | `agent_context`, confidence 0 | `error` nói lý do |

Rẽ nhánh ở cấp **trang** khi `kind = hybrid_pdf`: đọc thẳng các trang
`read_direct`, chỉ gửi ocr-lab các trang trong `pages_needing_ocr`.

Quy tắc phân loại trang PDF là `decide_page` trong `src/ocr_lab/classify.py`
— các ngưỡng (300 / 50 ký tự, ảnh phủ 50% / 1%) và lý do chọn chúng được
ghi ngay trong mô-đun đó. Docx dùng cùng ngưỡng ảnh phủ 1%; ngưỡng 200 ký tự
"chỉ là ảnh" lấy từ `scripts/so_ban_sach.py` (12 docx ảnh chụp trong kho đều
có đúng 0 ký tự).

## Độ tin cậy

`confidence` đo **quyết định đường đi bền đến đâu** trước sai số đo tín hiệu,
không phải xác suất đã hiệu chỉnh trên dữ liệu gán nhãn.

Mọi quyết định là so một tín hiệu đo được với một ngưỡng: số ký tự lớp text,
phần trang bị ảnh phủ, số vùng chữ. Nên:

```
d          = lượng thay đổi nhỏ nhất của các tín hiệu, tính bằng SỐ LẦN NHÂN ĐÔI
             (|log2(tín hiệu / ranh giới)|), đủ để ĐỔI ĐƯỜNG ĐI; trần 1
confidence = 0,5 + 0,5 × d          (làm tròn 3 chữ số)
```

- Nằm đúng trên ranh giới → **0,5**: đổi một chút là đổi đường.
- Cách mọi ranh giới liên quan từ gấp đôi trở lên → **1,0**.
- Tín hiệu bằng 0 là một cực: nhân đôi bao nhiêu lần vẫn là 0, nên tính là
  cách xa hẳn (d = 1).
- Tín hiệu đếm nguyên (ký tự, vùng chữ) có ranh giới ở nửa số: "≥ 300" là
  ranh giới 299,5.
- Hai tín hiệu cùng phải dịch thì tốn bằng tín hiệu phải dịch xa hơn.
- **Chỉ tính ranh giới làm đổi đường đi.** Trong PDF còn trang chữ, trang gần
  trống và trang văn bản số cùng `read_direct`, nên ranh giới 50 ký tự giữa
  chúng không hạ độ tin cậy. Khi cả tài liệu đều `blank` (PDF mọi trang trống,
  docx hay tệp văn bản < 50 ký tự) thì tài liệu đi `agent_context`, nên ranh
  giới 50 ký tự và các ranh giới ảnh phủ **có** được tính. Trang không trống
  duy nhất của một PDF (mọi trang khác `blank`) cũng tính ranh giới 50 ký tự:
  nó rơi xuống dưới 50 là cả tệp đổi sang `agent_context`. Docx "chỉ ảnh" và
  "lai" cùng `ocr`, nên ranh giới 200 ký tự không hạ độ tin cậy.
- Cả tệp = **min** các trang: tệp chỉ chắc bằng trang kém chắc nhất, và
  trang đó có thể chính là trang chữ ký mà node cần.

Vì sao thang nhân đôi: các ngưỡng trong `classify.py` được đặt theo tỉ lệ
("cao hơn ca chữ ký số gấp đôi, thấp hơn ca tỷ giá 1,5 lần"), và 94% trong
1 163 trang thật nằm ở 0 ký tự hoặc ≥ 300 ký tự — rất xa ngưỡng. Thang log
cho các trang đó 1,0 và chỉ hạ vùng xám.

| Tín hiệu | Đường | confidence |
|---|---|---|
| trang 0 ký tự, ảnh phủ 90% | `ocr` | 1,000 |
| trang 2 000 ký tự, không ảnh | `read_direct` | 1,000 |
| trang 6 ký tự, ảnh phủ 55% | `ocr` | 0,569 — ảnh chỉ nhỉnh hơn ngưỡng 50% |
| trang 310 ký tự, ảnh phủ 45% | `read_direct` | 0,576 — sát cả ngưỡng 300 ký tự lẫn 50% |
| trang 299 ký tự, ảnh phủ 60% | `ocr` | 0,501 — thêm một ký tự là đổi đường |
| PDF mọi trang 0 ký tự, không ảnh | `agent_context` | 1,000 |
| PDF 1 trang 60 ký tự, không ảnh | `read_direct` | 0,639 — sát ngưỡng 50 ký tự |
| docx 30 ký tự, không ảnh | `agent_context` | 0,861 — sát ngưỡng 50 ký tự |
| ảnh rời, 0 / 1 / 2 / ≥ 3 vùng chữ | `agent_context` / `agent_context` / `ocr` / `ocr` | 1,000 / 0,792 / 0,708 / 1,000 |
| ảnh rời, không dò được | `ocr` | 0,500 |
| unreadable / unsupported | `agent_context` | 0 |

`signals.route_agreement` và `signals.text_layer_coverage` được trả để bên gọi
tự dùng; chúng **không** vào công thức (PDF lai có `route_agreement` thấp là
bình thường, không phải dấu hiệu không chắc).

Gợi ý cho bên gọi: `confidence < 0,6` là vùng xám thật — nếu node cần chắc,
chạy cả hai đường (đọc thẳng và OCR) rồi để agent so.

## Giới hạn đã biết

- **Bản scan đã OCR sẵn** (ảnh + lớp text ẩn) có lớp text ≥ 300 ký tự nên ra
  `born_digital_pdf` / `read_direct`. Lớp text đó là OCR cũ, chất lượng không
  bảo đảm. Quy tắc có sẵn của `classify.py`, chưa đổi.
- **Độ nhạy của bộ dò vùng chữ trên ảnh thật của kho chưa được đo.** Ngưỡng 2
  vùng lấy từ `embedded_images.py` (ảnh nhúng trong PDF), chưa kiểm riêng
  trên ảnh chụp điện thoại.
- **docx được xét như một khối** (`pages` có đúng một phần tử, `index` 0):
  docx không có trang cố định trước khi dàn trang. Ảnh ở header/footer (logo)
  bị bỏ qua có chủ ý.
- **Chưa phân loại** xlsx, pptx, .doc/.xls đời cũ → `unsupported`. Lưu ý thêm
  với xlsx của kho: ô ngày có thể bị đảo ngày/tháng (AGENTS.md).
- `confidence` đo khoảng cách tới ngưỡng, **không** đo độ đúng của chính
  ngưỡng. Một trang ở xa ngưỡng vẫn có thể bị phân loại sai nếu ngưỡng sai
  cho loại tài liệu đó.
