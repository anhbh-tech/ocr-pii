"""Xem trước tệp KHÔNG phải ảnh: docx, xlsx, txt, md, html.

VÌ SAO KHÔNG DÙNG LIBREOFFICE
─────────────────────────────
Cách phổ biến là gọi `soffice --convert-to pdf`. Đã cân nhắc và bỏ:

  * Máy này không có LibreOffice, và máy đích (Xeon E-2224G) cũng không
    chắc có. Thêm một phụ thuộc 400MB chỉ để xem trước là quá đắt.
  * `soffice` chạy nền một tiến trình dùng chung; gọi song song nhiều tệp
    thì nó xếp hàng hoặc chết. Web này mở tệp theo thao tác người dùng,
    nghĩa là nhiều yêu cầu chồng nhau.
  * Thời gian khởi động lần đầu 3-8 giây — quá lâu cho một lượt xem trước.

Thay vào đó đọc thẳng cấu trúc tệp bằng thư viện Python thuần:

  docx  → mammoth  (chuyển sang HTML ngữ nghĩa, GIỮ được ảnh nhúng)
  xlsx  → openpyxl (đọc giá trị ô, dựng bảng HTML)
  txt   → đọc thẳng
  md    → đọc thẳng, để phía web dựng

ĐÁNH ĐỔI ĐÃ BIẾT
────────────────
Cách này KHÔNG giữ bố cục in ấn: lề, ngắt trang, vị trí tuyệt đối của hộp
văn bản đều mất. Chấp nhận được, vì mục đích ở đây là ĐỌC NỘI DUNG để đối
chiếu OCR, không phải in lại tài liệu.

Điều quan trọng hơn: mammoth giữ ảnh nhúng dưới dạng data URI. Đó chính là
thứ ta cần — 148 tệp docx trong kho chứa ảnh mà PyMuPDF không nhìn thấy.
"""

from __future__ import annotations

import base64
import html
import io
from pathlib import Path


#: Trần số ô đọc từ một sheet. Bảng lớn hơn mức này thì cắt và báo rõ.
#: Không có trần thì một tệp xlsx 50 nghìn dòng sẽ dựng chuỗi HTML hàng
#: chục MB và làm treo trình duyệt — hỏng ở phía người dùng, khó truy.
MAX_O = 5000

#: Trần ký tự cho tệp văn bản thuần.
MAX_KY_TU = 400_000


def xem_truoc(path: Path) -> dict:
    """Trả về ``{"kind": ..., "html"|"text": ..., "note": ...}``.

    ``kind`` cho phía web biết dựng thế nào. Luôn trả về một dict hợp lệ,
    kể cả khi đọc hỏng — phía web không phải đoán giữa "tệp rỗng" và "lỗi".
    """
    suf = path.suffix.lower()
    try:
        if suf == ".docx":
            return _docx(path)
        if suf == ".xlsx":
            return _xlsx(path)
        if suf in {".txt", ".md", ".csv", ".json", ".xml", ".log"}:
            return _van_ban(path, suf)
        if suf in {".html", ".htm"}:
            return {"kind": "html",
                    "html": path.read_text("utf-8", errors="replace")[:MAX_KY_TU],
                    "note": ""}
    except Exception as e:  # noqa: BLE001 — muốn BẤT KỲ lỗi nào cũng thành thông báo
        return {"kind": "loi", "text": f"Không đọc được: {type(e).__name__}: {e}",
                "note": ""}

    return {"kind": "khong_ho_tro",
            "text": f"Chưa xem trước được đuôi {suf or '(không có)'}.",
            "note": ""}


def _docx(path: Path) -> dict:
    """docx → HTML, giữ ảnh nhúng dưới dạng data URI."""
    import mammoth

    anh_dem = {"n": 0}

    def nhung_anh(image):
        # Ảnh nhúng chính là thứ đáng giá nhất trong tệp docx ở kho này:
        # một khảo sát trước đây thấy 147 tệp docx báo "0 ảnh" qua PyMuPDF
        # nhưng thực chứa 262 ảnh, 106 trong số đó có chữ (gồm ảnh CCCD).
        anh_dem["n"] += 1
        with image.open() as f:
            data = base64.b64encode(f.read()).decode("ascii")
        return {"src": f"data:{image.content_type};base64,{data}"}

    with path.open("rb") as f:
        kq = mammoth.convert_to_html(
            f, convert_image=mammoth.images.img_element(nhung_anh))

    note = f"{anh_dem['n']} ảnh nhúng" if anh_dem["n"] else ""
    return {"kind": "html", "html": kq.value, "note": note}


def _xlsx(path: Path) -> dict:
    """xlsx → một bảng HTML cho mỗi sheet."""
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter

    # `data_only=True`: lấy GIÁ TRỊ đã tính, không lấy công thức. Người soát
    # cần thấy con số như khi mở bằng Excel, không cần thấy "=SUM(A1:A9)".
    # KHÔNG dùng `read_only=True`: chế độ đó không nạp `merged_cells`, nên
    # mọi ô gộp vỡ thành một ô có chữ cộng nhiều ô trống nằm rải rác — bảng
    # trông rời rạc, tiêu đề tách khỏi giá trị của nó. Bảng tính hồ sơ ở đây
    # vài trăm hàng, không phải vài triệu, nên nạp đầy đủ là đáng.
    wb = load_workbook(path, data_only=True)
    phan = []
    tong_o = 0
    cat = False

    for ws in wb.worksheets:
        # Ô gộp: ô TRÊN-TRÁI giữ giá trị, các ô còn lại trong vùng bị nuốt.
        # Dựng sẵn hai bảng tra để mỗi ô chỉ phải hỏi một lần.
        nhip: dict[tuple[int, int], tuple[int, int]] = {}
        bi_nuot: set[tuple[int, int]] = set()
        for vung in getattr(ws, "merged_cells", []).ranges if hasattr(
                ws, "merged_cells") else []:
            r1, c1 = vung.min_row, vung.min_col
            nhip[(r1, c1)] = (vung.max_row - r1 + 1, vung.max_col - c1 + 1)
            for r in range(r1, vung.max_row + 1):
                for c in range(c1, vung.max_col + 1):
                    if (r, c) != (r1, c1):
                        bi_nuot.add((r, c))

        # Hàng cuối CÓ chữ. Chỉ cắt phần đuôi trống, không cắt hàng trống nằm
        # giữa vùng dữ liệu — xem giải thích ở vòng lặp bên dưới.
        hang_cuoi = 0
        for h in ws.iter_rows():
            if any(o.value is not None and str(o.value).strip() for o in h):
                hang_cuoi = h[0].row

        # Lưới cột cố định, lấy đúng độ rộng người soạn đặt trong Excel.
        #
        # Không có lưới này thì HTML tự co mỗi cột theo nội dung DÀI NHẤT của
        # riêng nó, nên ranh giới cột ở mỗi hàng một khác: "Số: V2025-904"
        # trôi khỏi cột của nó, bảng phí lệch hẳn một cột so với tiêu đề.
        # Đơn vị của Excel là số ký tự; ~7px mỗi ký tự cộng 5px đệm.
        #
        # Số cột phải khớp `max_column`, KHÔNG phải số mục trong
        # `column_dimensions`: Excel lưu độ rộng cho cả những cột trống nằm
        # ngoài vùng dữ liệu (ở đây 18 mục cho một sheet 8 cột), và phát dư
        # <col> làm lưới rộng hơn số ô thật.
        so_cot = ws.max_column
        cot = []
        for c in range(1, so_cot + 1):
            chieu = ws.column_dimensions[get_column_letter(c)].width \
                if get_column_letter(c) in ws.column_dimensions else None
            px = (chieu or 8.43) * 7 + 5
            cot.append(f'<col style="width:{px:.0f}px">')
        cot_html = "".join(cot)

        hang_html = []
        for hang in ws.iter_rows(min_row=1, max_row=hang_cuoi):
            if tong_o >= MAX_O:
                cat = True
                break

            # GIỮ hàng trống nằm trong vùng dữ liệu. Bản trước bỏ chúng, và
            # đó là nguyên nhân thật của việc bảng lệch: ô gộp `A4:E5` phát
            # ra `rowspan="2"`, nhưng hàng 5 vừa bị xoá, nên ô đó thò xuống
            # chiếm chỗ của hàng KẾ TIẾP và đẩy mọi ô của hàng ấy sang phải.
            # Hàng trống còn là giãn cách người soạn cố ý đặt.
            rong = all(o.value is None or str(o.value).strip() == ""
                       for o in hang)

            phan_o = []
            for o in hang:
                if (o.row, o.column) in bi_nuot:
                    continue        # đã nằm trong colspan/rowspan của ô gốc
                nh = nhip.get((o.row, o.column))
                thuoc = ""
                if nh:
                    if nh[0] > 1:
                        thuoc += f' rowspan="{nh[0]}"'
                    if nh[1] > 1:
                        thuoc += f' colspan="{nh[1]}"'
                txt = "" if o.value is None else str(o.value)
                phan_o.append(f"<td{thuoc}>{html.escape(txt)}</td>")

            lop = ' class="rTrong"' if rong else ""
            hang_html.append(f"<tr{lop}>{''.join(phan_o)}</tr>")
            tong_o += len(hang)

        if hang_html:
            phan.append(
                f'<h3 class="sheetName">{html.escape(ws.title)}</h3>'
                f'<table class="xlsxTable"><colgroup>{cot_html}</colgroup>'
                f'{"".join(hang_html)}</table>')
        if cat:
            break

    wb.close()
    note = f"{len(wb.worksheets)} sheet"
    if cat:
        note += f" · cắt ở {MAX_O} ô"
    if not phan:
        return {"kind": "html", "html": '<p class="muted">Bảng tính rỗng.</p>',
                "note": note}
    return {"kind": "html", "html": "".join(phan), "note": note}


def _van_ban(path: Path, suf: str) -> dict:
    t = path.read_text("utf-8", errors="replace")
    cat = len(t) > MAX_KY_TU
    return {
        "kind": "markdown" if suf == ".md" else "text",
        "text": t[:MAX_KY_TU],
        "note": f"cắt ở {MAX_KY_TU:,} ký tự".replace(",", ".") if cat else "",
    }


__all__ = ["xem_truoc", "MAX_O", "MAX_KY_TU"]
