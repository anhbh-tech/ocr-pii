"""Trích xuất nội dung có NEO VỊ TRÍ từ tệp, không cần OCR và không tốn tiền.

VÌ SAO TỆP NÀY TỒN TẠI
──────────────────────
Web đối chiếu đang có ba engine, cả ba đều trả về cùng một khuôn: cây
`structure` gồm các phần tử, mỗi phần tử mang `grounding` để biết nó nằm ở
đâu trên trang. Nhờ khuôn chung đó, một bộ dựng giao diện phục vụ được cả ba.

Nhưng phần lớn tệp trong kho KHÔNG cần OCR: PDF có sẵn lớp text, docx/xlsx
vốn là văn bản. Chạy engine lên chúng là trả tiền (hoặc trả thời gian) để
đọc lại thứ đã đọc được.

Module này đọc thẳng và trả về ĐÚNG KHUÔN ẤY. Hệ quả: markdown, JSON, danh
sách chunk, khung neo — mọi thứ trong web chạy y như với ADE, không phải
viết thêm một đường hiển thị thứ hai.

NEO VỊ TRÍ DÙNG CHUNG CHO MỌI ĐỊNH DẠNG
───────────────────────────────────────
Đây là phần khó. PDF có toạ độ thật; docx và xlsx thì KHÔNG CÓ hình học nào
cho tới khi được dàn trang bởi Word/Excel — và ta không có chúng.

Cách giải: `grounding` mang thêm trường `kind`, và có đúng hai loại neo.

    kind="box"   PDF, ảnh — toạ độ phân số [0,1] như ADE.
                 grounding = {kind, page, box:{xmin,ymin,xmax,ymax}, range}

    kind="path"  docx, xlsx — đường dẫn CẤU TRÚC tới phần tử.
                 grounding = {kind, path:"p:12" | "Sheet1!B7", range}

Cả hai đều neo vào bản dựng mà người dùng đang nhìn: một cái bằng pixel
(vẽ khung lên canvas), một cái bằng nút DOM (tô sáng đoạn văn / ô bảng).

Vì sao KHÔNG bịa toạ độ cho docx: có thể dựng hình học giả bằng cách ước
lượng chiều cao dòng. Khung sẽ vẽ ra, trông như thật, và lệch — đúng kiểu
sai mà người soát không phát hiện được. Một neo cấu trúc đúng có ích hơn
một toạ độ sai trông có vẻ đúng.

`range` giữ nguyên ý nghĩa ở cả hai loại: khoảng offset ký tự trong
`markdown`, để tô đúng đoạn chữ tương ứng ở khung bên phải.
"""

from __future__ import annotations

import html as _html
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


#: Đuôi tệp module này đọc được.
PDF_SUFFIXES = {".pdf"}
DOCX_SUFFIXES = {".docx"}
XLSX_SUFFIXES = {".xlsx"}
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".json", ".xml", ".log"}

#: Trần số ô đọc từ một bảng tính. Xem ghi chú ở `preview.py` — bảng lớn
#: dựng ra chuỗi hàng chục MB và làm treo trình duyệt.
MAX_O = 5000


@dataclass
class _Builder:
    """Gom dần markdown và cây structure, giữ hai thứ luôn khớp offset.

    Phải đi cùng nhau: `range` là offset ký tự trong `markdown`, nên mọi
    chỗ nối chuỗi đều phải cập nhật con trỏ. Tách ra hai vòng lặp là cách
    chắc chắn nhất để chúng lệch nhau.
    """

    md: list[str] = field(default_factory=list)
    n: int = 0                       # số ký tự đã ghi vào markdown
    pages: list[dict] = field(default_factory=list)

    def them(self, text: str, grounding: dict, loai: str) -> None:
        """Ghi một phần tử, tự tính `range` trong markdown."""
        text = text.rstrip()
        if not text:
            return
        dau = self.n
        self.md.append(text)
        self.n += len(text) + 2      # +2 cho "\n\n" nối giữa các phần tử
        grounding = dict(grounding)
        grounding["range"] = {"start": dau, "end": dau + len(text)}
        self.pages[-1]["children"].append({
            "id": f"el{sum(len(p['children']) for p in self.pages)}",
            "type": loai,
            "grounding": grounding,
            "children": [],
        })

    def trang_moi(self, so: int) -> None:
        self.pages.append({
            "type": "page",
            "page": so,
            "grounding": {"kind": "page", "page": so},
            "children": [],
        })

    def ket_qua(self) -> dict:
        return {
            "markdown": "\n\n".join(self.md),
            "structure": {"type": "document", "children": self.pages},
        }


def trich_xuat(path: Path) -> dict:
    """Trả về ``{"markdown", "structure", "meta"}`` — cùng khuôn ADE trả về.

    Ném `ValueError` khi đuôi tệp không đọc được, thay vì trả về cây rỗng:
    một tài liệu rỗng và một tài liệu không đọc được là hai chuyện khác
    nhau, và gộp lại thì phía web không phân biệt nổi.
    """
    suf = path.suffix.lower()
    if suf in PDF_SUFFIXES:
        return _pdf(path)
    if suf in DOCX_SUFFIXES:
        return _docx(path)
    if suf in XLSX_SUFFIXES:
        return _xlsx(path)
    if suf in TEXT_SUFFIXES:
        return _text(path)
    raise ValueError(f"chưa trích xuất được đuôi {suf or '(không có)'}")


def _pdf(path: Path) -> dict:
    """PDF có lớp text → toạ độ THẬT, chuẩn hoá [0,1] đúng như ADE."""
    import pymupdf

    b = _Builder()
    doc = pymupdf.open(path)
    tong_ky_tu = 0
    try:
        for i, page in enumerate(doc, start=1):
            b.trang_moi(i)
            W, H = page.rect.width, page.rect.height
            if not (W and H):
                continue
            # `sort=True`: trả block theo thứ tự đọc thay vì thứ tự vẽ trong
            # tệp. Không có nó, văn bản hai cột trả về đan xen nhau.
            for blk in page.get_text("blocks", sort=True):
                x0, y0, x1, y1, text, *_ = blk
                text = text.strip()
                if not text:
                    continue
                tong_ky_tu += len(text)
                b.them(text, {
                    "kind": "box",
                    "page": i,
                    # Chuẩn hoá về phân số: đúng quy ước ADE, nên cùng một
                    # phép `box_to_pixels` dùng được cho cả hai nguồn.
                    "box": {"xmin": x0 / W, "ymin": y0 / H,
                            "xmax": x1 / W, "ymax": y1 / H},
                }, "text")
    finally:
        doc.close()

    kq = b.ket_qua()
    kq["meta"] = {
        "engine": "local-pdf",
        "so_trang": len(b.pages),
        "ky_tu": tong_ky_tu,
        # Cảnh báo thẳng khi PDF hầu như không có chữ: đây là PDF scan, và
        # người dùng cần biết để chạy OCR thay vì tưởng tệp rỗng.
        "can_ocr": tong_ky_tu < 100 * max(1, len(b.pages)),
    }
    return kq


def _docx(path: Path) -> dict:
    """docx → neo theo CHỈ SỐ ĐOẠN VĂN, vì tệp không mang hình học nào."""
    import mammoth

    with path.open("rb") as f:
        # Bỏ ảnh khỏi HTML ở đây: bản xem trước (preview.py) mới cần ảnh.
        # Chỗ này lấy văn bản để neo, ảnh chỉ làm phình chuỗi.
        kq_html = mammoth.convert_to_html(
            f, convert_image=lambda image: {})

    b = _Builder()
    b.trang_moi(1)          # docx không có khái niệm trang trước khi dàn

    # Tách theo thẻ khối. Không dùng trình phân tích HTML đầy đủ vì đầu ra
    # của mammoth là tập thẻ nhỏ và đã biết trước.
    import re
    khoi = re.findall(
        r"<(p|h[1-6]|li|td|th)[^>]*>(.*?)</\1>", kq_html.value, re.S)
    for idx, (the, noi_dung) in enumerate(khoi):
        text = _html.unescape(re.sub(r"<[^>]+>", "", noi_dung)).strip()
        if not text:
            continue
        b.them(text, {
            "kind": "path",
            # `p:N` — N là chỉ số khối tính cả khối rỗng, nên nó ổn định
            # giữa các lần chạy và khớp được với DOM phía web.
            "path": f"p:{idx}",
        }, "heading" if the.startswith("h") else "text")

    kq = b.ket_qua()
    kq["meta"] = {"engine": "local-docx", "so_trang": 1,
                  "ky_tu": len(kq["markdown"]), "can_ocr": False}
    return kq


def _xlsx(path: Path) -> dict:
    """xlsx → neo theo ĐỊA CHỈ Ô (`Sheet1!B7`), thứ định danh tự nhiên nhất."""
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter

    wb = load_workbook(path, data_only=True, read_only=True)
    b = _Builder()
    tong_o = 0
    try:
        for si, ws in enumerate(wb.worksheets, start=1):
            b.trang_moi(si)
            for ri, hang in enumerate(ws.iter_rows(values_only=True), start=1):
                if tong_o >= MAX_O:
                    break
                o_co_chu = [(ci, o) for ci, o in enumerate(hang, start=1)
                            if o is not None and str(o).strip()]
                tong_o += len(hang)
                if not o_co_chu:
                    continue
                # Ghi CẢ HÀNG làm một phần tử: một ô lẻ mất ngữ cảnh, và
                # người soát đọc theo hàng chứ không theo ô.
                text = " | ".join(str(o) for _, o in o_co_chu)
                dia_chi = f"{ws.title}!{get_column_letter(o_co_chu[0][0])}{ri}"
                b.them(text, {"kind": "path", "path": dia_chi}, "table_row")
    finally:
        wb.close()

    kq = b.ket_qua()
    kq["meta"] = {"engine": "local-xlsx", "so_trang": len(b.pages),
                  "ky_tu": len(kq["markdown"]), "can_ocr": False}
    return kq


def _text(path: Path) -> dict:
    """Văn bản thuần → neo theo SỐ DÒNG."""
    t = path.read_text("utf-8", errors="replace")
    b = _Builder()
    b.trang_moi(1)
    # Gộp theo đoạn (ngăn bằng dòng trống) chứ không theo dòng: một dòng
    # đơn lẻ quá nhỏ để làm đơn vị soát.
    dong = 1
    for doan in t.split("\n\n"):
        so_dong = doan.count("\n") + 1
        if doan.strip():
            b.them(doan.strip(), {"kind": "path", "path": f"L{dong}"}, "text")
        dong += so_dong + 1

    kq = b.ket_qua()
    kq["meta"] = {"engine": "local-text", "so_trang": 1,
                  "ky_tu": len(t), "can_ocr": False}
    return kq


def chuan_hoa_nfc(s: str) -> str:
    """macOS trả tên tệp dạng NFD; kho lưu NFC. Xem `ade_store.doc_id_for`."""
    return unicodedata.normalize("NFC", s)


__all__ = ["trich_xuat", "PDF_SUFFIXES", "DOCX_SUFFIXES", "XLSX_SUFFIXES",
           "TEXT_SUFFIXES", "MAX_O", "chuan_hoa_nfc"]
