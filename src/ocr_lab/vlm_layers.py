"""Tách đầu ra VLM thành HAI LỚP, thay vì vứt một lớp đi.

SAI LẦM ĐÃ MẮC
──────────────
Khi thấy ground truth của ADE Pro làm mọi bộ OCR ăn điểm 0, tôi lọc bỏ
`<description>` rồi chấm trên phần còn lại. Cách đó sửa được phép đo nhưng
vứt đi thứ đắt giá nhất: mô tả ấy mang gần như toàn bộ NGỮ CẢNH của bức
ảnh, và về bản chất nó vượt xa bất cứ thứ gì một pipeline OCR làm được.

Một bộ OCR nhìn ảnh chụp màn hình trang bán mũ và trả về các nét chữ. Pro
nhìn cùng bức ảnh và biết đó là một trang thương mại điện tử, có nút giỏ
hàng, giá 39,95 đô, đánh giá 4,8 sao. Thông tin thứ hai không suy ra được
từ thông tin thứ nhất.

HAI LỚP, HAI VIỆC
─────────────────
    lớp CHỮ       các nét chữ đọc được trên ảnh
                  → OCR làm được; đây là nơi so engine rẻ với engine đắt

    lớp NGỮ CẢNH  bức ảnh này LÀ GÌ, có những thành phần nào
                  → chỉ VLM làm được; không có gì để so, chỉ có hoặc không

Tách ra rồi thì cả hai câu hỏi đều trả lời được, và không câu nào làm hỏng
câu kia:

  * "engine rẻ thay được Pro ở việc đọc chữ không?"  → so trên lớp CHỮ
  * "mất gì khi bỏ Pro?"                              → đúng bằng lớp NGỮ CẢNH

ĐỀ XUẤT ĐỊNH TUYẾN RÚT RA TỪ ĐÓ
───────────────────────────────
Không phải chọn một engine cho mọi thứ, mà hỏi từng tài liệu cần lớp nào:

    ảnh nhiều chữ, ít ngữ cảnh   (hoá đơn, giấy tờ)  → engine rẻ là đủ
    ảnh ít chữ, nhiều ngữ cảnh   (ảnh sản phẩm)      → chỉ VLM có nghĩa
    ảnh nhiều cả hai             (chụp màn hình)     → VLM, không thay được

Tỉ lệ chữ/ngữ cảnh đo được từ chính đầu ra của Pro, nên việc phân loại này
không cần thêm một lần gọi nào.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Khối mô tả: VLM nói VỀ bức ảnh.
_MO_TA = re.compile(r"<description>(.*?)</description>", re.S)
#: Thẻ figure kèm loại: PHOTOGRAPH, ILLUSTRATION, CHART…
_FIGURE = re.compile(r'<figure(?:\s+type="([A-Z_]+)")?[^>]*>', re.I)
#: Nhãn tượng trưng cho thành phần giao diện: [SEARCH_ICON], [CART_ICON]…
_NHAN = re.compile(r"\[([A-Z_]{2,})\]")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_THE = re.compile(r"</?figure[^>]*>")


@dataclass
class HaiLop:
    """Đầu ra VLM tách đôi."""

    chu: str                    # nét chữ đọc được — so được với OCR
    ngu_canh: str               # mô tả bức ảnh — chỉ VLM có
    loai_hinh: list[str]        # PHOTOGRAPH / ILLUSTRATION / CHART…
    nhan_giao_dien: list[str]   # SEARCH_ICON, CART_ICON, SIGNED…

    @property
    def ty_le_ngu_canh(self) -> float:
        """Phần thông tin chỉ VLM mới có.

        Gần 1 nghĩa là bức ảnh hầu như không có chữ — một bộ OCR sẽ trả về
        gần như không gì, và thay Pro bằng nó là mất trọn tài liệu.
        Gần 0 nghĩa là ảnh toàn chữ — engine rẻ thay được.
        """
        tong = len(self.chu) + len(self.ngu_canh)
        return len(self.ngu_canh) / tong if tong else 0.0

    @property
    def khuyen_nghi(self) -> str:
        # Cả hai lớp rỗng ⇒ Pro không thấy gì. Không được kết luận "engine
        # rẻ là đủ": tỉ lệ 0/0 = 0 chỉ là mặc định của phép chia, không phải
        # một phát hiện. Ảnh này nằm ngoài bài toán.
        if not self.chu and not self.ngu_canh:
            return "không kết luận được — Pro cũng không đọc ra gì"
        r = self.ty_le_ngu_canh
        if r >= 0.7:
            return "chỉ VLM — ảnh hầu như không có chữ, OCR trả về gần như rỗng"
        if r <= 0.25:
            return "engine rẻ là đủ — gần như toàn bộ giá trị nằm ở nét chữ"
        return "VLM đáng tiền — chữ và ngữ cảnh đều đáng kể"


def tach(markdown: str) -> HaiLop:
    """Tách markdown của VLM thành lớp chữ và lớp ngữ cảnh."""
    md = _COMMENT.sub("", markdown)

    mo_ta = [m.strip() for m in _MO_TA.findall(md) if m.strip()]
    loai = [m for m in _FIGURE.findall(md) if m]
    nhan = _NHAN.findall(md)

    chu = _MO_TA.sub("", md)
    chu = _THE.sub("", chu)
    chu = _NHAN.sub(" ", chu)
    # Gộp khoảng trắng thừa do việc bóc thẻ để lại, nhưng GIỮ ngắt dòng —
    # bố cục dòng là thông tin thật trên ảnh biểu mẫu.
    chu = re.sub(r"[ \t]+", " ", chu)
    chu = re.sub(r"\n{3,}", "\n\n", chu).strip()

    return HaiLop(chu=chu, ngu_canh="\n".join(mo_ta),
                  loai_hinh=loai, nhan_giao_dien=nhan)


def dinh_tuyen(markdown: str) -> dict:
    """Nói cho tài liệu này: engine rẻ thay được Pro không, và mất gì."""
    h = tach(markdown)
    return {
        "ky_tu_chu": len(h.chu),
        "ky_tu_ngu_canh": len(h.ngu_canh),
        "ty_le_ngu_canh": round(h.ty_le_ngu_canh, 3),
        "loai_hinh": h.loai_hinh,
        "n_nhan_giao_dien": len(h.nhan_giao_dien),
        "khuyen_nghi": h.khuyen_nghi,
    }


__all__ = ["HaiLop", "tach", "dinh_tuyen"]
