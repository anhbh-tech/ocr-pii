# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- Add durable project-specific notes here as they are discovered through real work.

## Kho hồ sơ: tên tệp không nhận diện được ảnh chụp

Đo trên toàn kho `~/.private/refiny_data` (588 tệp, 421 có parse ADE): 7 tên tệp
có chữ "tin nhan", chỉ 4 trong số đó thật sự là ảnh chụp màn hình; 197 ảnh chụp
khác thì tên không hề nói. Nhận diện ảnh chụp phải dựa vào CẤU TRÚC — docx chỉ
có `word/media/*` mà không có run `<w:t>`, pdf không có lớp text — rồi xác nhận
cặp bằng độ trùng nội dung giữa hai bản parse. Chi tiết và ngưỡng đo được:
`scripts/so_ban_sach.py`.

Hệ quả: một tài liệu thường có hai bản nằm cạnh nhau (bản gõ sạch và ảnh chụp
đoạn chat), và không bản nào thay được bản kia — ảnh chụp mới chứa câu hỏi của
khách. Sổ nối chúng lại: `~/.private/so/ban_sach_vs_anh.json` (ngoài cây git,
cùng vùng tin cậy với `~/.private/ade_out`).

ADE Pro OCR ảnh chụp thành khối text, KHÔNG để lại khối figure — "là ảnh chụp"
phải lấy từ cấu trúc tệp gốc, không từ parse. `section` trong `meta_pro.json`
có thể đã cũ (ghi `pdf_digital` cho pdf mà `classify_pdf` giờ nói là scan).
ADE còn đổi icon giao diện (app ngân hàng, web, email) thành emoji, nên "có
emoji" một mình bắt nhầm gần một nửa; dấu hiệu khung chat mạnh hơn. Số đo:
`scripts/so_hinh_thuc.py`.

## Ảnh chụp chat nhận bằng khung ứng dụng, không bằng từ khoá

Ảnh chụp nhóm chat in dòng tiêu đề `<đối tác> x REFINY[ - đuôi]` và dòng
`N thành viên`/`N members` trong CÙNG một bản parse. Đòi cả hai thì không có
dương tính giả trên toàn kho; chỉ dòng "thành viên" thì giấy ĐKDN nào cũng có.
Kênh là thực thể riêng, n–n với hồ sơ: `scripts/so_kenh.py` →
`~/.private/so/kenh/hoi_thoai/`. Khoá kênh không mang tên người (băm tiêu đề,
`kenh_id` trong `src/ocr_lab/danh_tinh.py`, dùng chung cho cả hai sổ), vì
khoá đi vào tên tệp và nhật ký.

Trong ảnh chat, `hh.mm`/`hh:mm` là đồng hồ giao diện, không phải ngày; ngày
thiếu năm phải suy năm. Mọi ngày mang `nguon` (ten_tep | dong_ho_chat |
trong_loi | mtime) và giờ đi danh sách riêng: `thoi_gian_hoi_thoai()` trong
`scripts/so_ngay.py`, đọc sổ kênh. `so_kenh` nhập `so_ngay` ở đầu tệp, nên
`so_ngay` chỉ được nhập `so_kenh` muộn (`_so_kenh()`), không ở đầu tệp.

## Số hiệu: chủ sở hữu theo trường Mark, không theo thư mục

Số đơn USPTO của một hồ sơ có khi chỉ nằm trong nhánh khiếu nại, và bản in
TSDR tra cứu chứa toàn số của nhãn đối chứng. Chủ của một số là trường "Mark"
cùng bản ghi TSDR (URL `caseNumber=` cuối trang), không phải thư mục chứa tệp.
`TV<số>` trên tên tệp là mã phiếu tra cứu/tư vấn, không phải mã hồ sơ. Sổ và
phép chứng minh tên tệp không mang số cấm: `scripts/so_so_hieu.py` →
`~/.private/so/so_hieu.json`. Tên tệp mang số cấm mà chủ kho đã quyết giữ
nguyên nằm trong `~/.private/so/ten_tep_chap_nhan.json`: đừng đổi tên chúng.

## Ảnh chat: nối bằng số trước, chữ sau

Bản `parse.json` (chuẩn) của ảnh chụp chat hỏng dấu ("sän phấm", "dăng ký")
trong khi bản pro/pro2 của CÙNG tệp còn dấu; chữ số sống qua cả hai, chỉ
thỉnh thoảng lệch một chữ số. Nối tệp hội thoại về hồ sơ bằng số 7–8 chữ số
và nhóm Nice so với sổ số hiệu trước, và khi buộc phải so chữ thì bỏ dấu CẢ
HAI phía: `scripts/so_neo_so.py` → `~/.private/so/neo_so.json` (có phép
chứng minh chuỗi có dấu trượt mà số vẫn nối).

## Agent hình thức chỉ chạy ở chỗ quyết định cổng

`scripts/agent_hinh_thuc.py` (lõi `src/ocr_lab/agent_hinh_thuc.py`) →
`~/.private/so/agent_hinh_thuc.json`. Tên tệp vào lời nhắc SAU nội dung, như
phỏng đoán không số dòng; khẳng định nào không đọc lại được nguyên văn ở dòng
đã chỉ thì bị bỏ. Mặc định chỉ ước lượng, `--goi` mới tốn tiền (đo: $0.05–0.17
mỗi tài liệu, token ra chiếm ~2/3). Đổi luật kiểm thì `--kiem-lai` trên câu
trả lời đã lưu, 0 đồng; đổi `HE_THONG` thì phải gọi lại. Parse ADE mang thực
thể HTML (`&#x27;`) — so chuỗi với trích của model thì giải trước.

## Đường dẫn trên macOS phải chuẩn hoá NFC trước khi so

`Path.rglob` trả tên NFD; `doc_id_for` trong `src/ocr_lab/ade_store.py` băm bản
NFC. So chuỗi đường dẫn mà quên `unicodedata.normalize("NFC", …)` thì mọi hồ sơ
có dấu đều trượt im lặng.

## "Tệp này thuộc hồ sơ nào" có MỘT chỗ trả lời

`src/ocr_lab/danh_tinh.py` (sổ: `scripts/so_danh_tinh.py` ⟶
`~/.private/so/danh_tinh.json`). Sổ mới đừng tự suy từ thư mục hay tên tệp:
`thuoc_ho_so` là MẢNG (chứng từ dùng chung là n–n), khoá bỏ số 0 đệm, và khi
tên tệp / thư mục / số in trong văn bản lệch nhau thì KHÔNG chọn — ca đó nằm
trong `~/.private/so/hang_cho_xung_dot.jsonl` chờ người, và lần dựng lại giữ
nguyên quyết định đã ghi ở đó.

## Mã lạc trong tên tệp không phải lỗi OCR

Mã hồ sơ đầu tên tệp đọc từ hệ tệp, không qua OCR. Mã lệch mã đa số của thư
mục có ba nguồn: lỗi gõ (lệch 1–2 chữ số, một tệp), số tra cứu song song
(khác tiền tố — không phải lỗi), tệp để nhầm hồ sơ (mã khác + tên nhãn khác).
Luật phân và sổ: `scripts/so_ma_lac.py` → `~/.private/so/ma_lac_dan.json`.
Số 0 đầu mang nghĩa khi dò lỗi gõ; `chuan_ma()` (`src/ocr_lab/danh_tinh.py`) bỏ
số 0 đầu nên không dùng được cho việc đó.

## Không định danh thật nào trong cây git

Mã hồ sơ, số hợp đồng/đơn, tên nhãn/khách, tên tệp gốc, ngày sinh trên căn
cước: chỉ dùng giá trị bịa (`901. ZORBLAX`, `NH9001`, `V2025-901`…) trong mã,
test, tài liệu, commit. Cấu hình cần dữ liệu thật (phán xét từng tệp, ca tự
kiểm, gold set) nằm ở `~/.private/so/*.json` và nạp lúc chạy; thiếu tệp thì
bỏ qua. `tests/test_khong_du_lieu_that.py` lấy token từ sổ thật và đỏ khi
token lọt vào tệp git — nó chỉ thấy cái sổ có, nên tên đối tác trong tên tệp
và dữ liệu căn cước vẫn phải tự soát.

## Che PII: pii-core quyết, box ADE Pro định vị

`src/ocr_lab/che.py` (`make che`) tô đen lên `pages/p{n}.jpg` rồi dựng PDF
chỉ-ảnh. Cái gì che và ở đâu trong chữ KHÔNG định nghĩa ở đây: cả
`lam_sach(markdown)` đi qua pii-core (`nap_pii_core`: `PII_CORE_URL` →
`/v1/document`; không thì thư viện `PII_CORE_SRC`, vắng thì `pii-core/src`
trong repo, + `PII_CORE_KEY` → `redact_case`, có ngữ cảnh hồ sơ với
`che_ho_so`; không khoá thì `pii-core serve` :8813), field ≠
KEEP đổi về markdown bằng bản đồ của `lam_sach` rồi về box. Đừng thêm bảng
quyết định, bộ dò hay ghi đè vào ocr-lab (pii-lab và `web/src/lib/pii.js` là
bảng cũ): sửa ở pii-core. Ô đen in `replacement` của pii-core (token) — cùng
khoá pii-core với lần che văn bản vào kho thì mới cùng mã. `chung_minh` hỏng
khi field ≠ KEEP nào không có vùng (`khong_dinh_vi`). Hình không phải chữ:
dòng `[...]` ADE mô tả ảnh người/chữ ký/QR/vân tay (`_HINH`), `scan_code`, và
mọi phần tử `figure`/`logo` (MARK_IMAGE, cả phần tử — kể cả ảnh chụp cả
trang) che cả box, hành động theo bảng pii-core (vắng thì REMOVE).
`grounding.page` của ADE Pro đếm từ 1, như ảnh trang. Box ADE Pro theo DÒNG;
vị trí trong dòng đo theo mực (`_hop_muc`, khít ±1 px), không đo được mới
nội suy (`dinh_vi` trong che.json); docx không có ảnh trang nên chưa che
được. ADE Pro có khi gán chữ lệch một box cả khối (CCCD); `_dat_lai` lấy box
từ `parse.json` cùng tệp khi mực nói box pro sai. Box ô bảng / đoạn nhiều dòng
tách theo dải hàng mực (`_tach_hang`); gạch chân và kẻ ô bỏ khỏi mặt nạ mực
(`_cum_dong`). `<a@b.com>` trong thư là chữ, không phải thẻ (`_MARKUP`).
Xem trước trên web: nút "⬛ che" (`/api/doc/{id}/che`, 503 khi không có pii-core);
soát mọi field kể cả KEEP theo hành động: nút "🏷 trường" (`/api/doc/{id}/truong`,
`?lop=truong` bật sẵn). Phần tử `attestation` (con dấu/chữ ký) che cả box như
figure (`chung_thuc`; pii-core không có STAMP nên REMOVE). `tim_vung` trả vùng
KHÔNG chồng nhau (`_giai_chong`: hành động nghiêm hơn giữ phần chung, `nhan`
chỉ ở mảnh lớn nhất) — bên vẽ đừng tự gộp. Trang scan lệch: `Khung` xoay thẳng
ảnh, mọi đo/cắt làm trong khung thẳng, vùng về trang gốc mang `tu_giac` (tứ
giác); `_mat_muc` bỏ khung khi góc sai làm rơi mực. Nắn box dòng từ hộp bao
hụt chân chữ khi đầu phải dòng không có chân chữ: dòng đó lui về hộp bao.

## pii-core/ là project riêng nằm trong repo

Bản chép tip pii-core (2f92340), KHÔNG kèm lịch sử: lịch sử gốc mang giá
trị thật. Lấy thêm từ repo pii-core riêng là chép tệp rồi soát định danh
thật trước khi commit — đừng `git subtree add/pull` lịch sử của nó.
Trong `pii-core/`, `pii-core/AGENTS.md` là luật (chỉ thư viện chuẩn, dữ liệu
bịa, khoá/roster ngoài cây). Test chạy trong thư mục của nó (`make
test-pii-core`); `testpaths` của ocr-lab chỉ là `tests/`, nên `uv run pytest`
ở gốc không gom `pii-core/tests`. `data/` trong `.gitignore` khớp mọi tầng:
`pii-core/src/pii_core/data/` được mở lại bằng một dòng `!`.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.

## Sharp edges found in real work

**8 ca `tests/test_project_setup.py` hỏng trong mọi worktree.** Chúng đòi
`data/`, `reports/` — thư mục cục bộ bị gitignore, chỉ có ở bản checkout
chính. Không phải hồi quy; đừng tạo thư mục giả để làm chúng xanh.

**Mỗi worktree cài `node_modules` riêng.** `node_modules` bị gitignore (cả
thư mục lẫn symlink); cần build web trong worktree thì chạy `npm ci` ngay
trong worktree đó. `serve_review.py` chưa có `web/dist` thì trang KHÔNG chạy
(`src/main.js` nhập CSS, chỉ Vite hiểu): `npm run build` trước khi xem.

**Ô ngày trong .xlsx của kho bị đảo ngày/tháng.** Đường đọc xlsx hiện tại
trả `2025-08-10` cho ô mà bản PDF của CÙNG chứng từ in rõ `8/10/2025`.
Đừng tin ngày lấy từ ô xlsx nếu chưa đối chiếu bản PDF hoặc một mốc khác
trong cùng hồ sơ. Phán xét từng tệp: `~/.private/so/giai_thich_lech.json`,
nạp bằng `giai_thich_lech()` trong `scripts/so_ngay.py`.

**`unicodedata.normalize("NFD", "đ")` không tách `đ` ra.** `đ`/`Đ` là chữ
cái riêng của bảng chữ cái, không phải `d` có dấu. Mọi hàm bỏ dấu tiếng
Việt phải `.replace("Đ","D").replace("đ","d")` TRƯỚC khi chuẩn hoá NFD,
nếu không "Hợp đồng" thành "hop đong" và mọi cụm chứa `đ` trượt lặng lẽ.
Xem `_bo_dau()` trong `scripts/so_ngay.py`.

**`classify.py` nay có bên gọi ngoài.** jev ai gọi `POST /api/classify`
(`scripts/serve_classify.py`, hợp đồng `ocr-lab.classify/1`). Thêm/đổi
`SourceKind`, `PageKind` hay ngưỡng trong `decide_page` là đổi hợp đồng:
sửa cùng lúc `docs/classify-api.schema.json` + `docs/classify-api.md`, và
tăng `CONTRACT` trong `src/ocr_lab/classify_api.py` nếu đổi nghĩa giá trị.
`tests/test_classify_api.py` kiểm mọi kết quả theo schema nên enum lệch sẽ đỏ.
