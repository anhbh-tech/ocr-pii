"""Chấm OCR khi ground truth đến từ một VLM — hai bên KHÔNG cùng loại.

VÌ SAO KHÔNG THỂ CHẤM NGANG HÀNG
────────────────────────────────
ADE Pro không phải một bộ OCR. Nó là mô hình thị giác-ngôn ngữ: nó NHÌN bức
ảnh rồi thuật lại. Một bộ OCR thì chép lại các nét chữ nó thấy. Hai việc
khác nhau, và đầu ra khác nhau ở những chỗ không thể quy về nhau:

    Pro trả về                          OCR trả về
    ─────────────────────────           ──────────────────
    ⭐⭐⭐⭐⭐ 4.8                      "4.8"  hoặc  "*****"
    [SEARCH_ICON] [CART_ICON]           (không có gì)
    🚚 Get it between Sunday            "Get it between Sunday"
    <description>A stylized logo…</>    (không có gì)
    搜索  (chữ trên thanh taskbar)       "搜索" nếu dò thấy

Đo trên kho: **80% markdown thô của Pro là `<description>`** — văn xuôi
tiếng Anh mô tả bức ảnh. Chấm CER trên đó là phạt mọi bộ OCR vì tội không
bịa ra một đoạn văn miêu tả.

Ngay cả sau khi lọc hết mô tả, phần còn lại vẫn đầy emoji và nhãn tượng
trưng mà không bộ OCR nào có thể sinh ra — và cũng KHÔNG NÊN sinh ra.

CÁCH CHẤM ĐÚNG: HỎI CÂU MÀ CẢ HAI ĐỀU TRẢ LỜI ĐƯỢC
──────────────────────────────────────────────────
Bỏ CER. Thay bằng ba câu hỏi mà cả VLM lẫn OCR đều có đáp án so được:

  1. THU HỒI (recall) trên từ có nghĩa
     Bao nhiêu phần trăm từ Pro đọc được, engine cũng đọc được? Chỉ tính
     từ CÓ NGHĨA — bỏ emoji, nhãn `[...]`, ký tự đơn lẻ. Đây là câu hỏi
     "engine có bỏ sót thông tin không", và nó không phạt engine vì thiếu
     những thứ vốn không phải chữ.

  2. GIỮ MÃ SỐ
     Số hợp đồng, mã đơn, ngày, số tiền — thứ SAI LÀ NGUY HIỂM. Cổng quyết
     định của toàn dự án.

  3. ĐỘ SẠCH (precision)
     Trong những gì engine trả về, bao nhiêu phần trăm thật sự có trong
     ground truth? Bắt được engine bịa chữ — hỏng kiểu nguy hiểm vì bản
     chép trông vẫn trôi chảy.

Thu hồi và độ sạch tách rời nhau có chủ đích: một engine đọc thiếu và một
engine bịa thêm là hai lỗi khác hẳn nhau về mức nghiêm trọng, mà CER gộp
chúng thành một con số.
"""

from __future__ import annotations

import re
import unicodedata

#: Nhãn tượng trưng VLM chèn vào: [SEARCH_ICON], [SIGNED], [FOLDER_ICON]…
_NHAN = re.compile(r"\[[A-Z_]{2,}\]")

#: Khối mô tả và thẻ figure — VLM nói VỀ bức ảnh, không chép chữ trên ảnh.
_MO_TA = re.compile(r"<description>.*?</description>", re.S)
_FIGURE = re.compile(r"</?figure[^>]*>")
_COMMENT = re.compile(r"<!--.*?-->", re.S)

#: Mã số: số hợp đồng, CCCD, ngày, mã đơn, số tiền. Thứ SAI LÀ NGUY HIỂM.
MA_SO = re.compile(r"[A-Z]{0,3}\d{4,}(?:[/.\-]\d+)*(?:/[A-Z\-]+)?")


def bo_phan_vlm(md: str) -> str:
    """Bỏ mọi thứ chỉ VLM mới sinh ra được."""
    md = _COMMENT.sub("", md)
    md = _MO_TA.sub("", md)
    md = _FIGURE.sub("", md)
    md = _NHAN.sub(" ", md)
    return md.strip()


def _la_tu_co_nghia(w: str) -> bool:
    """Từ mà một bộ OCR có thể và NÊN đọc được.

    Loại ba nhóm, mỗi nhóm vì một lý do khác nhau:
      * emoji / ký hiệu — không phải chữ, OCR không sinh ra được;
      * ký tự đơn lẻ    — gần như luôn là nhiễu hoặc mảnh giao diện;
      * chuỗi không có chữ cái lẫn chữ số — dấu câu trôi nổi.
    """
    if len(w) < 2:
        return False
    if not any(c.isalnum() for c in w):
        return False
    # Emoji và ký hiệu nằm ở nhóm Unicode S* (Symbol) và Co (Private Use).
    if all(unicodedata.category(c)[0] in {"S", "C"} or not c.isalnum()
           for c in w):
        return False
    return True


def tu_co_nghia(s: str) -> set[str]:
    """Tập từ có nghĩa, chuẩn hoá NFC + thường.

    NFC trước khi tách: macOS trả NFD, và `ký` dạng NFD khác `ký` dạng NFC
    theo từng byte — không chuẩn hoá thì mọi từ có dấu đều bị coi là khác.
    """
    s = unicodedata.normalize("NFC", s.lower())
    return {w for w in re.split(r"[\s|/\\]+", s)
            if _la_tu_co_nghia(w.strip(".,;:()[]{}\"'"))}


def cham(chuan_raw: str, doc: str) -> dict:
    """Chấm một cặp (ground truth VLM, đầu ra OCR).

    Trả về dict thay vì một điểm số duy nhất: gộp lại thành một con số là
    đúng cái làm hỏng phép đo trước.
    """
    chuan = bo_phan_vlm(chuan_raw)
    tc, td = tu_co_nghia(chuan), tu_co_nghia(doc)

    chung = tc & td
    thu_hoi = len(chung) / len(tc) if tc else None
    do_sach = len(chung) / len(td) if td else None

    mc = set(MA_SO.findall(chuan))
    md_ = set(MA_SO.findall(doc))

    return {
        "tu_chuan": len(tc),
        "tu_doc": len(td),
        "tu_trung": len(chung),
        "thu_hoi": round(thu_hoi, 3) if thu_hoi is not None else None,
        "do_sach": round(do_sach, 3) if do_sach is not None else None,
        "ma_so_chuan": len(mc),
        "ma_so_giu": len(mc & md_),
        "thieu": sorted(tc - td)[:12],
        "bia_them": sorted(td - tc)[:12],
    }


def gop(ket: list[dict]) -> dict:
    """Gộp nhiều ảnh.

    Cộng TỬ SỐ và MẪU SỐ rồi mới chia, không lấy trung bình của các tỉ lệ:
    một ảnh có 3 từ và một ảnh có 300 từ không được đóng góp ngang nhau.
    """
    tc = sum(k["tu_chuan"] for k in ket)
    td = sum(k["tu_doc"] for k in ket)
    tr = sum(k["tu_trung"] for k in ket)
    mc = sum(k["ma_so_chuan"] for k in ket)
    mg = sum(k["ma_so_giu"] for k in ket)
    return {
        "so_anh": len(ket),
        "thu_hoi": round(tr / tc, 3) if tc else None,
        "do_sach": round(tr / td, 3) if td else None,
        "ma_so": f"{mg}/{mc}",
        "ma_so_pct": round(mg / mc * 100, 1) if mc else None,
        "tu_chuan": tc,
        "tu_doc": td,
    }


__all__ = ["bo_phan_vlm", "tu_co_nghia", "cham", "gop", "MA_SO"]
