"""Hợp đồng phân loại cho bên gọi ngoài: tài liệu này đi ĐƯỜNG NÀO.

Bên gọi (jev ai, qua `POST /api/classify` của `scripts/serve_classify.py`)
không cần biết trang nào có bao nhiêu ký tự. Nó cần một quyết định:

    read_direct     đọc thẳng lớp text bằng thư viện — không OCR
    ocr             nội dung nằm trong ảnh → gửi ocr-lab
    agent_context   không có chữ để trích (ảnh không chữ, tài liệu mà mọi
                    trang đều gần trống), hoặc không phân loại được → để
                    agent tự xem tài liệu

kèm độ tin cậy và lý do. Mô-đun này dựng đúng khuôn JSON đó; tài liệu cho bên
gọi (kèm kiểu TypeScript) ở `docs/classify-api.md`, JSON Schema ở
`docs/classify-api.schema.json`.

LOẠI THEO NỘI DUNG, KHÔNG THEO ĐUÔI TỆP
────────────────────────────────────────
Định dạng nhận ra từ byte đầu tệp (`%PDF-`, `PK…word/document.xml`, ảnh mà
Pillow giải mã được…). Tên tệp chỉ để hiển thị lại. Kho thật cho thấy tên
tệp không đáng tin: xem AGENTS.md, mục "tên tệp không nhận diện được ảnh
chụp".

ĐỘ TIN CẬY = ĐỘ BỀN CỦA ĐƯỜNG ĐI
─────────────────────────────────
Mọi quyết định ở đây là so một tín hiệu đo được với một ngưỡng (số ký tự lớp
text, tỉ lệ ảnh phủ trang, số vùng chữ dò được). Tín hiệu càng sát ngưỡng thì
quyết định càng mong manh. Nên:

    d = lượng thay đổi NHỎ NHẤT của tín hiệu, tính bằng SỐ LẦN NHÂN ĐÔI
        (|log2(tín hiệu / ranh giới)|), đủ để ĐỔI ĐƯỜNG ĐI; trần 1
    confidence = 0,5 + 0,5 × d

Nằm đúng trên ranh giới → 0,5 (tung đồng xu, theo định nghĩa). Cách mọi ranh
giới có liên quan từ gấp đôi trở lên → 1,0. Tín hiệu bằng 0 là một cực: nhân
đôi bao nhiêu lần vẫn là 0.

Vì sao đo bằng lần nhân đôi: chính các ngưỡng trong `classify.py` được đặt
theo TỈ LỆ ("cao hơn ca chữ ký số gấp đôi, thấp hơn ca tỷ giá 1,5 lần"), và
phân bố đo trên 1 163 trang thật là lưỡng cực — 94% trang ở 0 ký tự hoặc
≥300 ký tự, tức cách ngưỡng rất xa. Thang log cho đúng bức tranh đó: trang ở
cực được 1,0, chỉ vùng xám mới bị hạ.

Chỉ tính các ranh giới làm ĐỔI ĐƯỜNG ĐI. Trong một PDF có trang chữ, trang
"gần trống" và trang "văn bản số" cùng đi `read_direct`, nên ranh giới 50 ký
tự giữa chúng không hạ độ tin cậy của ai. Nhưng khi MỌI trang (hay phần duy
nhất của docx/tệp văn bản) đều gần trống, cả tài liệu đi `agent_context` —
đọc thẳng chỉ ra rỗng — và lúc đó ranh giới 50 ký tự có đổi đường, nên được
tính. Trang chữ DUY NHẤT giữa các trang trống cũng vậy: nó rơi xuống dưới 50
ký tự là cả tệp đổi sang `agent_context`.

Cả tệp lấy độ tin cậy THẤP NHẤT trong các trang: một tệp chỉ chắc bằng trang
kém chắc nhất của nó — trang đó có thể chính là trang chữ ký mà yêu cầu của
node cần.
"""

from __future__ import annotations

import io
import math
import re
import threading
import unicodedata
import zipfile
from collections.abc import Callable
from pathlib import Path
from xml.etree import ElementTree as ET

from ocr_lab.classify import (
    _BORN_DIGITAL_CHARS,
    _IMAGE_DOMINANT_COVER,
    _MIN_REAL_IMAGE_COVER,
    _SPARSE_CHARS,
    _TEXT_WINS_OVER_IMAGE_CHARS,
    PageKind,
    SourceKind,
    classify_page,
    decide_page,
    source_kind_of,
)
from ocr_lab.embedded_images import MIN_VUNG_CHU

__all__ = ["CONTRACT", "ROUTES", "classify_bytes", "classify_path"]

#: Tên + phiên bản hợp đồng. Đổi tên trường hay đổi nghĩa một giá trị thì
#: tăng số này; thêm trường mới (bên gọi bỏ qua được) thì không cần.
CONTRACT = "ocr-lab.classify/1"

READ_DIRECT = "read_direct"
OCR = "ocr"
AGENT = "agent_context"
ROUTES = (READ_DIRECT, OCR, AGENT)

#: docx dưới ngần này ký tự text mà có ảnh đáng kể → ảnh chụp thuần.
#: Cùng số với `TOI_DA_KY_TU_ANH_CHUP` trong `scripts/so_ban_sach.py`, đo trên
#: kho thật: 12 docx ảnh chụp đều có ĐÚNG 0 ký tự; 200 là mép an toàn cho
#: tệp lỡ dính một dòng chú thích. Ranh giới này KHÔNG đổi đường đi (ảnh chụp
#: thuần và lai đều đi `ocr`), chỉ đổi nhãn.
_DOCX_IMAGE_ONLY_MAX_CHARS = 200

#: Khổ trang mặc định khi docx không khai `w:pgSz`: A4, đơn vị twip (1/1440 in).
_A4_TWIPS = (11906, 16838)
_EMU_PER_TWIP = 635

#: Cạnh dài tối đa khi đưa ảnh cho bộ dò chữ. Ảnh điện thoại 4000×3000 dò ở
#: kích thước gốc chậm gấp nhiều lần mà không thêm vùng chữ nào đáng kể.
_DETECT_MAX_SIDE = 2048

#: Không giải nén phần XML nào lớn hơn mức này — chặn zip bomb.
_MAX_XML_BYTES = 200 * 1024 * 1024

#: Nhãn thương hiệu ISO-BMFF của HEIC/HEIF (byte 8–12, sau `ftyp`).
_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis",
                b"mif1", b"msf1"}

#: Tiền tố tệp OLE2 — .doc/.xls/.ppt đời cũ.
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_V = "{urn:schemas-microsoft-com:vml}"
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"

#: Đơn vị trong thuộc tính `style` của ảnh VML → EMU.
_EMU_PER_UNIT = {"pt": 12700, "in": 914400, "cm": 360000, "mm": 36000,
                 "px": 9525}

_PAGE_ROUTE = {PageKind.BORN_DIGITAL: READ_DIRECT,
               PageKind.SCANNED: OCR,
               PageKind.SPARSE: READ_DIRECT}

#: Đường đi của trang khi MỌI trang của tệp đều gần trống: không còn trang chữ
#: nào để đọc thẳng, nên trang trống đi `agent_context`.
_PAGE_ROUTE_TOAN_TRONG = {**_PAGE_ROUTE, PageKind.SPARSE: AGENT}

#: Loại trang trong hợp đồng — chữ thường, không phụ thuộc tên enum nội bộ.
_PAGE_LABEL = {PageKind.BORN_DIGITAL: "text_layer",
               PageKind.SCANNED: "image",
               PageKind.SPARSE: "blank"}

_EPS = 1e-9


# ── độ tin cậy ──────────────────────────────────────────────────────────────

#: (ranh giới, (giá trị ngay dưới, giá trị ngay trên)). Với tín hiệu đếm
#: nguyên, ranh giới nằm GIỮA hai số nguyên kề ngưỡng (299,5 cho "≥300"), để
#: khoảng cách của hai bên được đo công bằng.
_Ranh = tuple[float, tuple[float, float]]


def _doublings(x: float, bien: float) -> float:
    """Khoảng cách từ tín hiệu `x` tới ranh giới, tính bằng lần nhân đôi, trần 1."""
    if x <= 0:
        return 1.0          # 0 là cực: nhân đôi bao nhiêu lần vẫn là 0
    return min(1.0, abs(math.log2(x / bien)))


def _do_ben(route_of: Callable[[float, float], str], a: float, b: float,
            ranh_a: list[_Ranh], ranh_b: list[_Ranh]) -> float:
    """d ∈ [0, 1]: lượng nhân đôi nhỏ nhất của (a, b) làm `route_of` đổi kết quả.

    Quyết định là tổ hợp các phép so ngưỡng theo trục, nên đường đi chỉ có thể
    đổi khi một tín hiệu vượt qua một ranh giới. Thử mọi tổ hợp "giữ nguyên /
    đặt ngay hai bên mỗi ranh giới" của hai tín hiệu là ĐỦ và CHÍNH XÁC — không
    cần dò lưới. Đẩy cả hai tín hiệu cùng lúc thì tốn bằng tín hiệu phải đẩy xa
    hơn (max), vì cả hai cùng nhúc nhích một lúc.
    """
    goc = route_of(a, b)
    ung_a = [(a, 0.0)] + [(v, _doublings(a, bien))
                          for bien, vs in ranh_a for v in vs]
    ung_b = [(b, 0.0)] + [(v, _doublings(b, bien))
                          for bien, vs in ranh_b for v in vs]
    d = 1.0
    for va, da in ung_a:
        for vb, db in ung_b:
            if route_of(va, vb) != goc:
                d = min(d, max(da, db))
    return d


def _tin_cay(d: float) -> float:
    return round(0.5 + 0.5 * d, 3)


#: Mọi ranh giới mà `decide_page` so tới, lấy thẳng từ hằng số của nó để hai
#: nơi không bao giờ lệch nhau.
_PDF_RANH_CHARS: list[_Ranh] = [
    (_TEXT_WINS_OVER_IMAGE_CHARS - 0.5,
     (_TEXT_WINS_OVER_IMAGE_CHARS - 1, _TEXT_WINS_OVER_IMAGE_CHARS)),
    (_BORN_DIGITAL_CHARS - 0.5, (_BORN_DIGITAL_CHARS - 1, _BORN_DIGITAL_CHARS)),
    (_SPARSE_CHARS - 0.5, (_SPARSE_CHARS - 1, _SPARSE_CHARS)),
    (0.5, (0, 1)),                              # "chars == 0"
]
_PDF_RANH_COVER: list[_Ranh] = [
    (_IMAGE_DOMINANT_COVER, (_IMAGE_DOMINANT_COVER - _EPS, _IMAGE_DOMINANT_COVER)),
    (_MIN_REAL_IMAGE_COVER, (_MIN_REAL_IMAGE_COVER - _EPS, _MIN_REAL_IMAGE_COVER)),
]


def _pdf_route(chars: float, cover: float) -> str:
    return _PAGE_ROUTE[decide_page(int(chars), cover)[0]]


def _pdf_route_toan_trong(chars: float, cover: float) -> str:
    return _PAGE_ROUTE_TOAN_TRONG[decide_page(int(chars), cover)[0]]


# ── khung kết quả ───────────────────────────────────────────────────────────

def _page(index: int, kind: str, route: str, confidence: float, reason: str,
          chars: int, image_cover: float, *, images: int | None = None,
          text_regions: int | None = None) -> dict:
    return {"index": index, "kind": kind, "route": route,
            "confidence": confidence, "reason": reason, "chars": chars,
            "image_cover": round(image_cover, 4), "images": images,
            "text_regions": text_regions}


def _result(kind: SourceKind, route: str, confidence: float, reason: str,
            source: dict, pages: list[dict], *, error: str | None = None,
            images: int | None = None, text_regions: int | None = None) -> dict:
    """Khung chung cho MỌI kết quả — bên gọi luôn nhận đủ trường, kể cả khi lỗi."""
    n = len(pages)
    dem = {k: sum(1 for p in pages if p["kind"] == k)
           for k in ("text_layer", "image", "mixed", "blank")}
    cung_duong = sum(1 for p in pages if p["route"] == route)
    return {
        "contract": CONTRACT,
        "kind": kind.value,
        "route": route,
        "confidence": confidence,
        "reason": reason,
        "source": source,
        "pages": pages,
        "pages_needing_ocr": [p["index"] for p in pages if p["route"] == OCR],
        "signals": {
            "page_count": n,
            "text_layer_pages": dem["text_layer"],
            "image_pages": dem["image"],
            "mixed_pages": dem["mixed"],
            "blank_pages": dem["blank"],
            "chars_total": sum(p["chars"] for p in pages),
            "text_layer_coverage": round(dem["text_layer"] / n, 4) if n else 0.0,
            "route_agreement": round(cung_duong / n, 4) if n else 0.0,
            "images": images,
            "text_regions": text_regions,
        },
        "error": error,
    }


def _khong_doc_duoc(source: dict, loi: str) -> dict:
    """Kết quả cố định cho đầu vào hỏng: độ tin cậy 0, để agent tự xem."""
    return _result(SourceKind.UNREADABLE, AGENT, 0.0,
                   f"không đọc được tệp: {loi} — không có tín hiệu nào để "
                   f"định tuyến, để agent hoặc người xem trực tiếp",
                   source, [], error=loi)


# ── PDF ─────────────────────────────────────────────────────────────────────

# PyMuPDF không an toàn đa luồng, mà server chạy mỗi request trong threadpool:
# mọi việc với MuPDF (mở → đọc từng trang → đóng) đi qua một khoá.
_pymupdf_lock = threading.Lock()


def _pdf_trang(data: bytes) -> list | str:
    """Phân loại từng trang, hoặc trả chuỗi lỗi nếu không đọc được."""
    import pymupdf          # `classify` đã tắt DeprecationWarning của nó

    with _pymupdf_lock:
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:             # noqa: BLE001 — tệp hỏng
            return f"PDF không mở được: {exc}"
        try:
            if doc.needs_pass:
                return "PDF có mật khẩu"
            try:
                return [classify_page(pg) for pg in doc]
            except Exception as exc:         # noqa: BLE001
                return f"PDF hỏng giữa chừng: {exc}"
        finally:
            doc.close()


def _pdf(data: bytes, source: dict) -> dict:
    ket_qua = _pdf_trang(data)
    if isinstance(ket_qua, str):
        return _khong_doc_duoc(source, ket_qua)
    if not ket_qua:
        return _khong_doc_duoc(source, "PDF không có trang nào")

    toan_trong = all(r.kind is PageKind.SPARSE for r in ket_qua)
    bang = _PAGE_ROUTE_TOAN_TRONG if toan_trong else _PAGE_ROUTE
    pages = []
    for r in ket_qua:
        con_lai_trong = all(o.kind is PageKind.SPARSE
                            for o in ket_qua if o is not r)
        route_of = _pdf_route_toan_trong if con_lai_trong else _pdf_route
        d = _do_ben(route_of, r.chars, r.image_cover,
                    _PDF_RANH_CHARS, _PDF_RANH_COVER)
        pages.append(_page(r.index, _PAGE_LABEL[r.kind], bang[r.kind],
                           _tin_cay(d), r.reason, r.chars, r.image_cover))

    kind = source_kind_of(ket_qua)
    n = len(pages)
    so_text = sum(1 for p in pages if p["kind"] == "text_layer")
    so_anh = sum(1 for p in pages if p["kind"] == "image")
    so_trong = n - so_text - so_anh
    if kind is SourceKind.HYBRID_PDF:
        route = OCR
        reason = (f"PDF lai {n} trang: {so_text} trang có lớp text đọc thẳng "
                  f"được, {so_anh} trang nội dung nằm trong ảnh — chỉ OCR các "
                  f"trang trong pages_needing_ocr")
    elif kind is SourceKind.SCANNED_PDF:
        route = OCR
        reason = (f"PDF {n} trang, nội dung nằm trong ảnh ở {so_anh} trang, "
                  f"không trang nào có lớp text dùng được — OCR qua ocr-lab")
    elif so_text:
        route = READ_DIRECT
        reason = (f"PDF {n} trang có lớp text thật ({so_text} trang chữ, "
                  f"{so_trong} trang gần trống) — đọc thẳng bằng thư viện, "
                  f"không cần OCR")
    else:
        route = AGENT
        reason = (f"PDF {n} trang, trang nào cũng gần trống: không có lớp text "
                  f"lẫn ảnh đáng kể — đọc thẳng chỉ ra rỗng (có thể chữ vẽ "
                  f"thành đường cong), để agent xem tài liệu")
    return _result(kind, route, min(p["confidence"] for p in pages), reason,
                   source, pages)


# ── DOCX ────────────────────────────────────────────────────────────────────

def _emu_tu_style(style: str, thuoc_tinh: str) -> float:
    m = re.search(rf"(?:^|;)\s*{thuoc_tinh}\s*:\s*([\d.]+)\s*([a-z]*)", style)
    if not m:
        return 0.0
    try:
        so = float(m.group(1))
    except ValueError:
        return 0.0
    return so * _EMU_PER_UNIT.get(m.group(2) or "px", 0)


def _cua_rieng(el: ET.Element, tag: str):
    """Hậu duệ `tag` của `el`, không đi vào `w:drawing` lồng bên trong."""
    for con in el:
        if con.tag == tag:
            yield con
        if con.tag != f"{_W}drawing":
            yield from _cua_rieng(con, tag)


def _do_docx(z: zipfile.ZipFile) -> tuple[int, int, float]:
    """(số ký tự text, số ảnh trong thân, tỉ lệ ảnh phủ) của thân một docx.

    Chỉ đọc `word/document.xml` — THÂN văn bản. Ảnh ở đầu/chân trang (logo
    tiêu đề thư) nằm trong `header*.xml`/`footer*.xml`, lặp trên mọi trang
    và không phải nội dung, nên tự nhiên bị loại.

    Word lưu hộp chữ/khối hình HAI lần trong `mc:AlternateContent`: bản
    `mc:Choice` (DrawingML) và bản `mc:Fallback` (VML) cùng nội dung. Chỉ đếm
    bản Choice — bỏ mọi nhánh Fallback trước khi đếm chữ lẫn ảnh.

    Ảnh phủ = tổng diện tích HIỂN THỊ của ảnh (kích thước khai trong
    `wp:extent`, không phải số pixel) chia cho diện tích MỘT trang. Cùng nghĩa
    với `image_cover` của trang PDF, nên dùng lại được ngưỡng 1% "vệt trang trí
    vs ảnh thật" đã đo bằng mắt trong `classify.py`. Docx nhiều trang dán nhiều
    ảnh chụp thì tỉ lệ vượt 1,0 — hiểu là "ngần ấy trang ảnh".
    """
    info = z.getinfo("word/document.xml")
    if info.file_size > _MAX_XML_BYTES:
        raise ValueError(f"word/document.xml quá lớn ({info.file_size} byte)")
    root = ET.fromstring(z.read(info))
    for cha, con in [(cha, con) for cha in root.iter() for con in cha
                     if con.tag == f"{_MC}Fallback"]:
        cha.remove(con)

    chars = len("".join(t.text or "" for t in root.iter(f"{_W}t")).strip())

    w, h = _A4_TWIPS
    pg = next(root.iter(f"{_W}pgSz"), None)
    if pg is not None:
        try:
            w = int(pg.get(f"{_W}w") or w)
            h = int(pg.get(f"{_W}h") or h)
        except ValueError:
            pass
    dien_tich_trang = float(w * _EMU_PER_TWIP) * float(h * _EMU_PER_TWIP)

    so_anh, phu = 0, 0.0
    # DrawingML: `w:drawing` chứa `a:blip` là ẢNH; không có blip là biểu đồ
    # hay khối hình vẽ — chữ trong đó (nếu có) đã nằm ở `w:t`. Blip và khổ
    # chỉ tính của CHÍNH drawing đó: hộp chữ bọc một ảnh là một `w:drawing`
    # chứa `w:drawing` khác, ảnh bên trong đã được đếm ở drawing của nó.
    for dr in root.iter(f"{_W}drawing"):
        if next(_cua_rieng(dr, f"{_A}blip"), None) is None:
            continue
        so_anh += 1
        ext = next(_cua_rieng(dr, f"{_WP}extent"), None)
        if ext is not None:
            try:
                phu += float(ext.get("cx", 0)) * float(ext.get("cy", 0))
            except ValueError:
                pass
    # VML: docx đời cũ và ảnh xem trước của đối tượng OLE nhúng.
    for shape in root.iter(f"{_V}shape"):
        if next(shape.iter(f"{_V}imagedata"), None) is None:
            continue
        so_anh += 1
        style = shape.get("style", "")
        phu += _emu_tu_style(style, "width") * _emu_tu_style(style, "height")

    return chars, so_anh, (phu / dien_tich_trang if dien_tich_trang > 0 else 0.0)


def _docx_kind(chars: float, cover: float) -> SourceKind:
    if cover < _MIN_REAL_IMAGE_COVER:
        return SourceKind.DOCX_TEXT
    if chars < _DOCX_IMAGE_ONLY_MAX_CHARS:
        return SourceKind.DOCX_IMAGE_ONLY
    return SourceKind.DOCX_HYBRID


_DOCX_ROUTE = {SourceKind.DOCX_TEXT: READ_DIRECT,
               SourceKind.DOCX_IMAGE_ONLY: OCR,
               SourceKind.DOCX_HYBRID: OCR}


def _docx_route(chars: float, cover: float) -> str:
    kind = _docx_kind(chars, cover)
    if kind is SourceKind.DOCX_TEXT and chars < _SPARSE_CHARS:
        return AGENT
    return _DOCX_ROUTE[kind]


def _docx(z: zipfile.ZipFile, source: dict) -> dict:
    try:
        chars, so_anh, cover = _do_docx(z)
    except Exception as exc:                 # noqa: BLE001 — XML hỏng
        return _khong_doc_duoc(source, f"docx không đọc được: {exc}")

    kind = _docx_kind(chars, cover)
    route = _docx_route(chars, cover)
    d = _do_ben(_docx_route, chars, cover,
                [(_DOCX_IMAGE_ONLY_MAX_CHARS - 0.5,
                  (_DOCX_IMAGE_ONLY_MAX_CHARS - 1, _DOCX_IMAGE_ONLY_MAX_CHARS)),
                 (_SPARSE_CHARS - 0.5, (_SPARSE_CHARS - 1, _SPARSE_CHARS))],
                [(_MIN_REAL_IMAGE_COVER,
                  (_MIN_REAL_IMAGE_COVER - _EPS, _MIN_REAL_IMAGE_COVER))])
    conf = _tin_cay(d)

    if kind is SourceKind.DOCX_IMAGE_ONLY:
        nhan = "image"
        reason = (f"docx chỉ là ảnh dán vào: {so_anh} ảnh phủ {cover:.0%} một "
                  f"trang, chỉ {chars} ký tự text — nội dung nằm trong ảnh, "
                  f"OCR qua ocr-lab")
    elif kind is SourceKind.DOCX_HYBRID:
        nhan = "mixed"
        reason = (f"docx có {chars} ký tự text VÀ {so_anh} ảnh phủ {cover:.0%} "
                  f"một trang — phần text đọc thẳng được, nhưng chữ trong ảnh "
                  f"(ảnh chụp, CCCD, biên lai) chỉ OCR mới lấy được")
    else:
        nhan = "text_layer" if route == READ_DIRECT else "blank"
        anh = (f", {so_anh} ảnh nhỏ phủ {cover:.1%} một trang (vệt trang trí)"
               if so_anh else "")
        if route == READ_DIRECT:
            reason = f"docx có {chars} ký tự text{anh} — đọc thẳng, không cần OCR"
        else:
            reason = (f"docx gần trống: {chars} ký tự text{anh}, không ảnh đáng "
                      f"kể — đọc thẳng chỉ ra rỗng, để agent xem tài liệu")

    pages = [_page(0, nhan, route, conf, reason, chars, cover, images=so_anh)]
    return _result(kind, route, conf, reason, source, pages, images=so_anh)


# ── ẢNH RỜI ─────────────────────────────────────────────────────────────────

_do_chu_lock = threading.Lock()
_do_chu: object | None = None
_do_chu_hong = False


def _bo_do_chu():
    """Bộ DÒ chữ của RapidOCR, nạp một lần; None nếu không có.

    Chỉ dò VÙNG chữ, không đọc — đúng cách `embedded_images.py` dùng nó: kết
    quả không phụ thuộc model có biết tiếng Việt hay không. Đây không phải
    OCR; OCR vẫn là việc của ocr-lab ở bước sau.
    """
    global _do_chu, _do_chu_hong
    with _do_chu_lock:
        if _do_chu is None and not _do_chu_hong:
            try:
                from rapidocr_onnxruntime import RapidOCR
                _do_chu = RapidOCR()
            except Exception:                # noqa: BLE001 — thiếu gói/model
                _do_chu_hong = True
        return _do_chu


def _dem_vung_chu(im) -> int | None:
    """Số vùng chữ bộ dò thấy trong ảnh; None nếu không dò được."""
    do = _bo_do_chu()
    if do is None:
        return None
    import numpy as np

    im = im.convert("RGB")
    im.thumbnail((_DETECT_MAX_SIDE, _DETECT_MAX_SIDE))
    try:
        with _do_chu_lock:          # một phiên ONNX dùng chung cho mọi request
            hop, _ = do(np.asarray(im), use_det=True, use_cls=False,
                        use_rec=False)
    except Exception:                        # noqa: BLE001
        return None
    return len(hop or [])


def _image_route(n: float, _b: float) -> str:
    return OCR if n >= MIN_VUNG_CHU else AGENT


def _image(im, source: dict) -> dict:
    """Ảnh rời: không có lớp text, nên chỉ còn câu hỏi "trong ảnh có chữ không".

    Có chữ (≥ `MIN_VUNG_CHU` vùng — một vùng lẻ thường là nhiễu hoa văn) →
    `ocr`: ảnh chụp giấy tờ, ảnh quét, ảnh màn hình. Không có chữ → ảnh chụp
    cảnh vật/sản phẩm: OCR không thu được gì, agent phải tự nhìn.
    """
    n = _dem_vung_chu(im) if im is not None else None
    if n is None:
        # Không dò được (thiếu rapidocr, hoặc định dạng như HEIC mà Pillow
        # không giải mã): mặc định OCR — chạy tại máy, và thà OCR thừa một ảnh
        # còn hơn bỏ sót nội dung. Không có bằng chứng nào → đúng 0,5.
        route, conf = OCR, 0.5
        reason = ("ảnh rời, không dò được vùng chữ — mặc định OCR qua ocr-lab; "
                  "nếu OCR không ra chữ thì để agent xem ảnh")
    else:
        route = _image_route(n, 0)
        conf = _tin_cay(_do_ben(_image_route, n, 0,
                                [(MIN_VUNG_CHU - 0.5,
                                  (MIN_VUNG_CHU - 1, MIN_VUNG_CHU))], []))
        if route == OCR:
            reason = (f"ảnh rời, dò thấy {n} vùng chữ — ảnh giấy tờ / ảnh quét "
                      f"/ ảnh màn hình, OCR qua ocr-lab")
        else:
            reason = (f"ảnh rời, dò thấy {n} vùng chữ — ảnh chụp không mang "
                      f"chữ, OCR không thu được gì; để agent xem ảnh")
    pages = [_page(0, "image", route, conf, reason, 0, 1.0, text_regions=n)]
    return _result(SourceKind.IMAGE, route, conf, reason, source, pages,
                   text_regions=n)


# ── nhận dạng định dạng + điểm vào ─────────────────────────────────────────

def _khong_ho_tro(source: dict, mo_ta: str) -> dict:
    return _result(SourceKind.UNSUPPORTED, AGENT, 0.0,
                   f"{mo_ta}: định dạng này chưa được phân loại — không có tín "
                   f"hiệu nào để định tuyến, để agent xem trực tiếp",
                   source, [])


def _text_route(chars: float, _b: float) -> str:
    return READ_DIRECT if chars >= _SPARSE_CHARS else AGENT


def _van_ban(text: str, source: dict) -> dict:
    chars = len(text.strip())
    route = _text_route(chars, 0)
    conf = _tin_cay(_do_ben(_text_route, chars, 0,
                            [(_SPARSE_CHARS - 0.5,
                              (_SPARSE_CHARS - 1, _SPARSE_CHARS))], []))
    if route == READ_DIRECT:
        nhan, reason = "text_layer", f"tệp văn bản thuần, {chars} ký tự — đọc thẳng"
    else:
        nhan = "blank"
        reason = (f"tệp văn bản thuần gần trống, {chars} ký tự — không có gì "
                  f"để đọc thẳng, để agent xem tài liệu")
    pages = [_page(0, nhan, route, conf, reason, chars, 0.0)]
    return _result(SourceKind.TEXT, route, conf, reason, source, pages)


def _mo_anh(data: bytes):
    """Ảnh Pillow đã nạp, hoặc None nếu không phải ảnh Pillow đọc được."""
    from PIL import Image

    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:                        # noqa: BLE001 — không phải ảnh
        return None
    return im


def classify_bytes(data: bytes, name: str = "") -> dict:
    """Phân loại nội dung một tệp. KHÔNG BAO GIỜ ném ngoại lệ.

    Làm việc hoàn toàn trong bộ nhớ: tệp tải lên (có thể là CCCD, hợp đồng của
    khách) không bị ghi ra đĩa ở bất kỳ bước nào.
    """
    name = unicodedata.normalize("NFC", name or "")
    source = {"name": name, "format": "unknown", "bytes": len(data)}
    try:
        return _classify(data, source)
    except Exception as exc:                 # noqa: BLE001 — lưới cuối cùng
        return _khong_doc_duoc(source, f"lỗi không lường trước: {exc}")


def _classify(data: bytes, source: dict) -> dict:
    if not data:
        source["format"] = "empty"
        return _khong_doc_duoc(source, "tệp rỗng (0 byte)")

    if b"%PDF-" in data[:1024]:
        source["format"] = "pdf"
        return _pdf(data, source)

    if data[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
            names = set(z.namelist())
        except Exception as exc:             # noqa: BLE001
            source["format"] = "zip"
            return _khong_doc_duoc(source, f"zip hỏng: {exc}")
        with z:
            if "word/document.xml" in names:
                source["format"] = "docx"
                return _docx(z, source)
        for member, fmt in (("xl/workbook.xml", "xlsx"),
                            ("ppt/presentation.xml", "pptx")):
            if member in names:
                source["format"] = fmt
                return _khong_ho_tro(source, fmt)
        source["format"] = "zip"
        return _khong_ho_tro(source, "kho zip")

    if data[:8] == _OLE_MAGIC:
        source["format"] = "ole"
        return _khong_ho_tro(source, "tệp Office đời cũ (.doc/.xls/.ppt)")

    im = _mo_anh(data)
    if im is not None:
        source["format"] = (im.format or "image").lower()
        return _image(im, source)
    if data[4:8] == b"ftyp" and data[8:12] in _HEIF_BRANDS:
        source["format"] = "heic"
        return _image(None, source)

    if b"\x00" not in data[:8192]:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            source["format"] = "text"
            return _van_ban(text, source)

    return _khong_ho_tro(source, "định dạng không nhận ra")


def classify_path(path: str | Path) -> dict:
    """Như `classify_bytes`, đọc từ một tệp cục bộ. Tệp không mở được → UNREADABLE."""
    p = Path(path)
    try:
        data = p.read_bytes()
    except OSError as exc:
        name = unicodedata.normalize("NFC", p.name)
        return _khong_doc_duoc({"name": name, "format": "unknown", "bytes": 0},
                               f"không mở được tệp: {exc.strerror or exc}")
    return classify_bytes(data, p.name)
