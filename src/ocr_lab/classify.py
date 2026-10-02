"""Phân loại nguồn tài liệu theo TỪNG TRANG.

Vì sao theo trang chứ không theo tệp: một `.pdf` có thể là văn bản số, ảnh
quét, hoặc lai cả hai. Đuôi tệp không nói lên điều gì. Phân loại sai ở bước
này làm hỏng mọi bước sau — trang quét bị xếp "văn bản số" thì không ai OCR
nó, và nội dung mất đi im lặng: không lỗi, không cảnh báo, chỉ là một tài liệu
trống trong kho.

NGƯỠNG ĐO TỪ DỮ LIỆU THẬT, KHÔNG PHẢI ĐOÁN
──────────────────────────────────────────
Đo trên 1 163 trang của 300 PDF thật trong kho (11/09/2026):

    0 ký tự      372 trang (32,0%)   ← chắc chắn là ảnh quét
    1–9            8 trang ( 0,7%)
    10–49          7 trang ( 0,6%)
    50–99         34 trang ( 2,9%)
    100–299       21 trang ( 1,8%)
    ≥300         721 trang (62,0%)   ← chắc chắn là văn bản số

Phân bố **lưỡng cực**: 94% số trang nằm gọn ở một trong hai cực, chỉ ~4% ở
giữa. Nên ngưỡng đặt ở đâu trong khoảng 50–300 cũng không ảnh hưởng mấy — điều
thực sự quan trọng là xử lý đúng vùng giữa.

VÙNG XÁM MỚI LÀ CHỖ NGUY HIỂM
─────────────────────────────
35 trang có 1–299 ký tự VÀ ảnh phủ >50% trang. Đây là trang QUÉT đã bị dán
thêm một lớp text mỏng. Ví dụ thật:

    NQ9001 sap nhap dia gioi hanh chinh.pdf, trang 1
        148 ký tự · ảnh phủ 100%
        text: "Người ký: CỔNG THÔNG TIN ĐIỆN TỬ CHÍNH PHỦ
               Email: thongtinchinhphu@chinhphu.vn ..."

Toàn bộ 148 ký tự chỉ là CHỮ KÝ SỐ. Nội dung nghị quyết nằm trong ảnh. Nếu
dùng ngưỡng "≥100 ký tự ⇒ văn bản số" thì trang này không bao giờ được OCR.

    TV9011...huong dan chuan bi website, trang 5–8
        6 ký tự ("Hình 2") · ảnh phủ ~55%

Bài học: **số ký tự một mình không đủ.** Tín hiệu quyết định là tỉ lệ ảnh phủ
trang kết hợp mật độ chữ.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)
import pymupdf

__all__ = ["PageKind", "SourceKind", "PageResult", "SourceResult",
           "classify_page", "classify_pdf", "decide_page", "source_kind_of"]


# ── ngưỡng (xem giải thích ở đầu tệp) ───────────────────────────────────────

#: Từ mức này trở lên, chữ đủ dày để coi là nội dung thật — trừ khi ảnh phủ
#: gần hết trang (xem `_IMAGE_DOMINANT_COVER`).
_BORN_DIGITAL_CHARS = 300

#: Dưới mức này, chữ quá thưa để là nội dung: số trang, chú thích, chữ ký số.
_SPARSE_CHARS = 50

#: Ảnh phủ từ mức này trở lên ⇒ nội dung nằm trong ảnh, không nằm ở text layer.
#: Đặt 0,50 vì ca thật thấp nhất đo được là 55% (trang "Hình 2").
_IMAGE_DOMINANT_COVER = 0.50

#: Ngay cả khi ảnh phủ kín trang, chữ đủ dày vẫn là văn bản số thật.
#:
#: Ngưỡng này nằm GIỮA HAI CA THẬT kéo ngược chiều nhau, đo trên 300 PDF:
#:
#:   148 ký tự + ảnh 100%  → phải SCANNED
#:       `NQ9001…pdf` tr1 — toàn bộ chữ chỉ là chữ ký số, nội dung trong ảnh
#:
#:   456 ký tự + ảnh  67%  → phải BORN_DIGITAL
#:       `Ty gia VCB_*.pdf` tr1 (6 tệp) — trang web in ra PDF, ảnh là banner,
#:       chữ là nội dung thật. OCR lại sẽ cho kết quả TỆ HƠN text sẵn có.
#:
#: Đặt 300: cao hơn ca chữ ký số gấp đôi, thấp hơn ca tỷ giá 1,5 lần. Bản đầu
#: đặt 600 (đoán) nên xếp nhầm cả 6 trang tỷ giá thành cần OCR.
_TEXT_WINS_OVER_IMAGE_CHARS = 300

#: Trang KHÔNG một ký tự nào: từ mức phủ này trở lên thì ảnh là nội dung thật,
#: dưới mức này là vệt trang trí (đường kẻ ngang, logo góc).
#:
#: Đặt 0,01 sau khi XEM TẬN MẮT các ca sát ranh giới trong kho thật
#: (`NH9002.US. Non-Final Office Action`, 234 PDF):
#:
#:   ảnh 1717×4   → phủ 0,14%  → trang trắng, chỉ một đường kẻ mờ   → SPARSE
#:   ảnh 1717×70  → phủ 2,45%  → dòng bản quyền + logo thanh toán   → SCANNED
#:   ảnh 1717×433 → phủ 15,2%  → ảnh chụp trang web, có giá, tên SP → SCANNED
#:
#: Ranh giới thật nằm giữa 0,14% và 2,45%. Chọn 1% — cao hơn vệt kẻ 7 lần,
#: thấp hơn ca chữ thật nhỏ nhất 2,5 lần. Đây KHÔNG phải ngưỡng đoán: mỗi mốc
#: trên đã được kết xuất ra ảnh và đọc bằng mắt.
_MIN_REAL_IMAGE_COVER = 0.01

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp",
                   ".heic", ".heif", ".gif"}


class PageKind(Enum):
    """Loại của MỘT trang."""

    BORN_DIGITAL = "born_digital"   #: có lớp text thật → đọc thẳng, không OCR
    SCANNED = "scanned"             #: nội dung nằm trong ảnh → phải OCR
    SPARSE = "sparse"               #: gần trống → OCR cũng không thu được gì


class SourceKind(Enum):
    """Loại của CẢ tệp."""

    BORN_DIGITAL_PDF = "born_digital_pdf"
    SCANNED_PDF = "scanned_pdf"
    HYBRID_PDF = "hybrid_pdf"       #: lai — phải định tuyến từng trang
    IMAGE = "image"                 #: ảnh rời (ảnh chụp, ảnh quét, ảnh màn hình)
    UNREADABLE = "unreadable"

    # Các loại dưới đây chỉ `classify_api` sinh ra — `classify_pdf` không đụng
    # tới docx hay tệp văn bản.
    DOCX_TEXT = "docx_text"                 #: docx có chữ thật, không ảnh đáng kể
    DOCX_IMAGE_ONLY = "docx_image_only"     #: docx chỉ là ảnh dán vào (ảnh chụp)
    DOCX_HYBRID = "docx_hybrid"             #: docx có chữ VÀ ảnh đáng kể
    TEXT = "text"                           #: tệp văn bản thuần (txt, md, csv…)
    UNSUPPORTED = "unsupported"             #: mở được nhưng chưa phân loại (xlsx…)


@dataclass(frozen=True)
class PageResult:
    """Kết quả cho một trang, kèm LÝ DO để người đọc kiểm chứng được."""

    index: int
    kind: PageKind
    chars: int
    image_cover: float
    reason: str

    @property
    def needs_ocr(self) -> bool:
        return self.kind is PageKind.SCANNED


@dataclass(frozen=True)
class SourceResult:
    kind: SourceKind
    path: Path
    pages: list[PageResult] = field(default_factory=list)
    error: str = ""

    @property
    def pages_needing_ocr(self) -> list[int]:
        """Chỉ số các trang cần OCR — thứ bước định tuyến thực sự dùng."""
        return [p.index for p in self.pages if p.needs_ocr]


def _image_cover(page: "pymupdf.Page") -> float:
    """Tỉ lệ diện tích trang bị ảnh che phủ.

    Cộng dồn diện tích các hình chữ nhật chứa ảnh. Ảnh chồng nhau có thể làm
    tổng vượt 1,0 — chấp nhận được vì ta chỉ so với một ngưỡng, và vượt ngưỡng
    theo hướng "có nhiều ảnh" là kết luận đúng.
    """
    area = page.rect.width * page.rect.height
    if area <= 0:
        return 0.0
    covered = 0.0
    for img in page.get_images(full=True):
        try:
            for r in page.get_image_rects(img[0]) or []:
                covered += r.width * r.height
        except Exception:
            # Ảnh lỗi tham chiếu: bỏ qua ảnh đó, không bỏ cả trang.
            continue
    return covered / area


def classify_page(page: "pymupdf.Page") -> PageResult:
    """Phân loại một trang PDF: đo hai tín hiệu rồi giao cho `decide_page`."""
    text = (page.get_text("text") or "").strip()
    chars = len(text)
    cover = _image_cover(page)
    kind, reason = decide_page(chars, cover)
    return PageResult(page.number, kind, chars, cover, reason)


def decide_page(chars: int, cover: float) -> tuple[PageKind, str]:
    """Quyết định loại trang CHỈ từ hai tín hiệu đo được.

    Tách khỏi `classify_page` để bên ngoài hỏi được "nếu tín hiệu lệch đi một
    chút thì quyết định có đổi không" mà không cần dựng trang PDF — đó là cách
    `classify_api` tính độ tin cậy.

    Thứ tự kiểm có chủ ý: kiểm "ảnh lấn át" TRƯỚC khi kiểm số ký tự, vì đó
    chính là ca mà ngưỡng theo số ký tự đơn thuần bị sai (trang quét kèm chữ
    ký số).
    """
    # Ảnh phủ gần hết trang: nội dung nằm trong ảnh, kể cả khi có ít chữ.
    if cover >= _IMAGE_DOMINANT_COVER and chars < _TEXT_WINS_OVER_IMAGE_CHARS:
        return (
            PageKind.SCANNED,
            f"ảnh phủ {cover:.0%} trang, chỉ {chars} ký tự — nội dung nằm "
            f"trong ảnh (chữ ký số / chú thích không phải nội dung)")

    # KHÔNG MỘT KÝ TỰ NÀO + có ảnh thật ⇒ quét, bất kể ảnh phủ bao nhiêu.
    #
    # Ngưỡng `_IMAGE_DOMINANT_COVER` ở trên được hiệu chỉnh cho trang quét khổ
    # A4 (ảnh phủ ≥50%). Ảnh chụp màn hình điện thoại dán vào A4 thì tỉ lệ dọc
    # khác hẳn, ảnh chỉ phủ 40–47% — lọt qua, rồi bị nhánh `chars < _SPARSE`
    # bên dưới gọi là "gần trống" dù trang có hẳn một tấm ảnh.
    #
    # CA THẬT: `NH9001.US_Anh chup man hinh nhan hieu_011025.pdf` (0 ký tự,
    # ảnh 46%) và `…Tin nhan ket qua tra cuu_190925.pdf` (0 ký tự, ảnh 44%).
    # Quét lại 234 PDF trong kho: 69 trang cùng dạng bị bỏ sót, tức không bao
    # giờ được ADE Pro đọc.
    #
    # Điều kiện là `chars == 0`, KHÔNG phải `chars < _SPARSE_CHARS`: trang có
    # dù chỉ một dòng chữ thật thì lớp text đang hoạt động, còn 0 ký tự nghĩa
    # là lớp text rỗng hoàn toàn — mọi nội dung chỉ có thể nằm trong ảnh.
    # `_MIN_REAL_IMAGE_COVER` loại các vệt ảnh trang trí (đường kẻ, logo góc).
    if chars == 0 and cover >= _MIN_REAL_IMAGE_COVER:
        return (
            PageKind.SCANNED,
            f"không có lớp text, ảnh phủ {cover:.0%} — toàn bộ nội dung nằm "
            f"trong ảnh (ảnh chụp màn hình / ảnh dán vào trang)")

    if chars >= _BORN_DIGITAL_CHARS:
        return PageKind.BORN_DIGITAL, f"{chars} ký tự trong lớp text"

    # Ít chữ, ít ảnh: trang gần trống. OCR cũng không thu được gì, và gọi nó là
    # SCANNED sẽ sinh "OCR thất bại" giả trong thống kê chất lượng.
    if chars < _SPARSE_CHARS:
        return (
            PageKind.SPARSE,
            f"chỉ {chars} ký tự, ảnh phủ {cover:.0%} — trang gần trống")

    # Vùng giữa (50–299 ký tự, ít ảnh): chữ thưa nhưng có thật.
    return (
        PageKind.BORN_DIGITAL,
        f"{chars} ký tự, ảnh phủ {cover:.0%} — chữ thưa nhưng đọc được")


def classify_pdf(path: str | Path) -> SourceResult:
    """Phân loại một tệp: PDF (theo từng trang) hoặc ảnh rời.

    Tệp hỏng trả về `UNREADABLE` kèm thông báo, KHÔNG ném ngoại lệ — một tệp
    hỏng giữa mẻ 566 tệp không được phép giết cả mẻ.
    """
    path = Path(path)

    if path.suffix.lower() in _IMAGE_SUFFIXES:
        return SourceResult(
            SourceKind.IMAGE, path,
            [PageResult(0, PageKind.SCANNED, 0, 1.0, "ảnh rời — luôn cần OCR")])

    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        return SourceResult(SourceKind.UNREADABLE, path, error=str(exc))

    try:
        pages = [classify_page(pg) for pg in doc]
    except Exception as exc:
        return SourceResult(SourceKind.UNREADABLE, path, error=str(exc))
    finally:
        doc.close()

    if not pages:
        return SourceResult(SourceKind.UNREADABLE, path,
                            error="PDF không có trang nào")

    return SourceResult(source_kind_of(pages), path, pages)


def source_kind_of(pages: list[PageResult]) -> SourceKind:
    """Gộp loại từng trang thành loại cả tệp PDF (danh sách trang không rỗng)."""
    kinds = {p.kind for p in pages}
    has_scan = PageKind.SCANNED in kinds
    has_text = PageKind.BORN_DIGITAL in kinds

    if has_scan and has_text:
        return SourceKind.HYBRID_PDF
    if has_scan:
        return SourceKind.SCANNED_PDF
    # Chỉ có text và/hoặc trang trống.
    return SourceKind.BORN_DIGITAL_PDF
