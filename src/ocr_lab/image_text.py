"""Nhận ra trang "digital" nhưng có nội dung thật nằm trong ảnh.

BÀI TOÁN
────────
`classify_page` chỉ hỏi "trang có lớp text không". Trang ≥300 ký tự là
BORN_DIGITAL và không bao giờ được OCR. Nhưng tài liệu xuất từ Word/Excel rất
hay chèn ảnh chụp vào giữa văn bản thật: một ô bảng chụp màn hình, một biên
lai dán vào. Chữ trong đó biến mất khỏi bản chép mà không có dấu hiệu gì.

Đo bằng Vision trên 312 trang digital của kho thật: **32 trang (10%) có chữ
trong ảnh mà lớp text không có**, tổng 811 từ.

NHƯNG KHÔNG PHẢI CẢ 32 TRANG ĐỀU ĐÁNG OCR
─────────────────────────────────────────
Số liệu tách ra hai nhóm rõ rệt:

    Filing Receipt tr5   175 ký tự text · 73 từ trong ảnh   ← nội dung THẬT
    TV9011 tr1-9         969 ký tự text · 30 từ trong ảnh   ← chân trang

Nhóm hai là logo + địa chỉ công ty lặp lại y hệt trên mọi trang. OCR nó tốn
tiền để lấy về đúng một dòng địa chỉ đã biết.

Phân biệt bằng TỈ LỆ, không bằng số tuyệt đối: chữ trong ảnh so với chữ trong
lớp text. Chân trang thì tỉ lệ nhỏ (30/969 ≈ 3%); trang nội dung-trong-ảnh
thì lớn (73/175 ≈ 42%).

Thêm một dấu hiệu nữa: chân trang LẶP LẠI trên nhiều trang của cùng tệp. Một
cụm từ xuất hiện ở quá nửa số trang thì nó là khung trang, không phải nội
dung.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

__all__ = ["ImageTextFinding", "danh_gia_trang", "loc_chan_trang",
           "tim_khung_trang_toan_kho", "danh_gia_lai", "NGUONG_LAP_KHO",
           "TI_LE_DANG_OCR", "MIN_TU_MOI"]

#: Tỉ lệ (từ trong ảnh / từ trong lớp text) đủ lớn để coi là nội dung thật.
#:
#: Đặt ở 0,15 theo phân bố đo được: chân trang của kho này nằm ở 0,03–0,04,
#: còn trang nội dung-trong-ảnh ở 0,42–0,67. Khoảng trống giữa hai cụm rất
#: rộng, nên ngưỡng ở đâu trong đó cũng được — chọn gần nhóm dưới để thà OCR
#: thừa một trang còn hơn bỏ sót nội dung.
TI_LE_DANG_OCR = 0.15

#: Dưới mức này thì thường là nhiễu nhận dạng từ logo/chữ ký: Vision hay đọc
#: ra vài ký tự vô nghĩa từ hoa văn.
MIN_TU_MOI = 4

#: Một cụm từ xuất hiện ở quá tỉ lệ này số trang của cùng tệp thì là khung
#: trang (chân trang, đầu trang, watermark), không phải nội dung.
NGUONG_LAP = 0.5


@dataclass(frozen=True)
class ImageTextFinding:
    """Kết luận cho MỘT trang, kèm lý do kiểm chứng được."""

    page: int
    n_tu_moi: int
    n_tu_text: int
    tu_moi: list[str]
    dang_ocr: bool
    ly_do: str

    @property
    def ti_le(self) -> float:
        return self.n_tu_moi / max(self.n_tu_text, 1)


def chuan_hoa(s: str) -> set[str]:
    """Tập từ chuẩn hoá để so hai nguồn văn bản.

    NFC trước khi tách: macOS trả chuỗi NFD, và `ký` dạng NFD khác `ký` dạng
    NFC theo từng byte — so hai tập mà không chuẩn hoá thì mọi từ có dấu đều
    bị coi là "mới".
    """
    s = unicodedata.normalize("NFC", s.lower())
    return {w for w in re.split(r"[^\w]+", s) if len(w) >= 2}


def danh_gia_trang(text_layer: str, text_trong_anh: str,
                   page: int = 0) -> ImageTextFinding:
    """Trang này có nội dung thật nằm trong ảnh không."""
    tu_text = chuan_hoa(text_layer)
    tu_anh = chuan_hoa(text_trong_anh)
    moi = sorted(tu_anh - tu_text)
    n_moi, n_text = len(moi), len(tu_text)
    ti_le = n_moi / max(n_text, 1)

    if n_moi < MIN_TU_MOI:
        return ImageTextFinding(
            page, n_moi, n_text, moi, False,
            f"chỉ {n_moi} từ mới — nhiễu từ logo hoặc chữ ký")

    if ti_le < TI_LE_DANG_OCR:
        return ImageTextFinding(
            page, n_moi, n_text, moi, False,
            f"{n_moi} từ mới trên {n_text} từ sẵn có ({ti_le:.0%}) — "
            f"tỉ lệ của chân trang / logo, không phải nội dung")

    return ImageTextFinding(
        page, n_moi, n_text, moi, True,
        f"{n_moi} từ mới trên {n_text} từ sẵn có ({ti_le:.0%}) — "
        f"nội dung thật nằm trong ảnh, ĐÁNG OCR")


def loc_chan_trang(findings: list[ImageTextFinding]) -> list[ImageTextFinding]:
    """Bỏ những từ lặp lại trên quá nửa số trang của cùng một tệp.

    Chân trang công ty (địa chỉ, số điện thoại, tên miền) xuất hiện y hệt ở
    mọi trang. Xét từng trang riêng lẻ thì không thấy, phải nhìn cả tệp mới
    nhận ra — đó là lý do hàm này nhận cả danh sách chứ không nhận một trang.

    Đánh giá lại sau khi lọc: một trang có thể từ "đáng OCR" thành "không"
    khi phần lớn từ mới của nó hoá ra là chân trang.
    """
    if len(findings) < 3:
        # Hai trang giống nhau KHÔNG đủ để kết luận là khung trang. Một biên
        # lai hai trang nội dung giống nhau sẽ bị loại oan — đã xảy ra thật
        # với `Filing Receipt` tr5-6: 73 từ nội dung bị coi là chân trang.
        #
        # Khung trang chỉ nhận ra được khi có đủ trang để thấy nó LẶP, nên
        # dưới 3 trang thì không kết luận.
        return findings

    dem: dict[str, int] = {}
    for f in findings:
        for w in set(f.tu_moi):
            dem[w] = dem.get(w, 0) + 1

    # Phải xuất hiện ở quá nửa số trang VÀ ít nhất 3 trang.
    nguong = max(3, int(len(findings) * NGUONG_LAP) + 1)
    khung = {w for w, n in dem.items() if n >= nguong}
    if not khung:
        return findings

    ra = []
    for f in findings:
        con_lai = [w for w in f.tu_moi if w not in khung]
        n_moi = len(con_lai)
        ti_le = n_moi / max(f.n_tu_text, 1)
        if n_moi < MIN_TU_MOI or ti_le < TI_LE_DANG_OCR:
            ra.append(ImageTextFinding(
                f.page, n_moi, f.n_tu_text, con_lai, False,
                f"sau khi bỏ {len(f.tu_moi) - n_moi} từ khung trang "
                f"(lặp trên ≥{nguong}/{len(findings)} trang) chỉ còn "
                f"{n_moi} từ — không đáng OCR"))
        else:
            ra.append(ImageTextFinding(
                f.page, n_moi, f.n_tu_text, con_lai, True,
                f"{n_moi} từ mới sau khi bỏ khung trang ({ti_le:.0%}) — "
                f"nội dung thật nằm trong ảnh"))
    return ra


#: Một từ xuất hiện ở quá tỉ lệ này số trang nghi ngờ TRÊN TOÀN KHO thì là
#: khung trang dùng chung (letterhead, con dấu, watermark), không phải nội
#: dung của riêng tài liệu nào.
#:
#: Đặt 0,25 theo phân bố đo được trên kho thật: letterhead của công ty luật
#: ("9th floor · Prime Centre · 53 Trung Hoa · Ha Noi") xuất hiện ở 16-19
#: trên 32 trang nghi ngờ (50-59%), trong khi từ nội dung thật cao nhất chỉ
#: 2-3 trang. Khoảng trống rộng, ngưỡng ở đâu trong đó cũng được.
NGUONG_LAP_KHO = 0.25


def tim_khung_trang_toan_kho(tat_ca: list[list[str]]) -> set[str]:
    """Từ dùng chung trên TOÀN KHO, từ danh sách `tu_moi` của mọi trang.

    VÌ SAO KHÔNG ĐỦ KHI CHỈ LỌC TRONG TỪNG TỆP
    ──────────────────────────────────────────
    `loc_chan_trang` nhìn trong một tệp, nên nó chỉ bắt được chân trang của
    tài liệu nhiều trang. Nhưng letterhead của công ty nằm trên MỌI tài liệu
    công ty phát hành — mỗi tệp chỉ đóng góp 1-2 trang nghi ngờ, dưới ngưỡng
    "lặp lại", nên nó lọt hết.

    Đo thật: 32 trang nghi ngờ thuộc 21 tệp; địa chỉ công ty xuất hiện ở 17
    trang nhưng không tệp nào có đủ 3 trang để bộ lọc theo tệp nhận ra.

    Hệ quả nếu bỏ sót: trả tiền OCR cho 20 trang chỉ để lấy về đúng một dòng
    địa chỉ đã biết sẵn.
    """
    if len(tat_ca) < 4:
        return set()
    dem: dict[str, int] = {}
    for tu in tat_ca:
        for w in set(tu):
            dem[w] = dem.get(w, 0) + 1
    nguong = max(3, int(len(tat_ca) * NGUONG_LAP_KHO))
    return {w for w, n in dem.items() if n >= nguong}


def danh_gia_lai(f: ImageTextFinding, khung: set[str]) -> ImageTextFinding:
    """Chấm lại một trang sau khi đã biết tập từ khung trang toàn kho."""
    con = [w for w in f.tu_moi if w not in khung]
    n = len(con)
    ti_le = n / max(f.n_tu_text, 1)
    bo = len(f.tu_moi) - n
    if n < MIN_TU_MOI or ti_le < TI_LE_DANG_OCR:
        return ImageTextFinding(
            f.page, n, f.n_tu_text, con, False,
            f"bỏ {bo} từ khung trang dùng chung toàn kho, còn {n} từ "
            f"({ti_le:.0%}) — không đáng OCR")
    return ImageTextFinding(
        f.page, n, f.n_tu_text, con, True,
        f"{n} từ riêng của tài liệu này ({ti_le:.0%}) sau khi bỏ {bo} từ "
        f"khung trang — nội dung thật nằm trong ảnh")
