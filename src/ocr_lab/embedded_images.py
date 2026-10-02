"""Lập danh mục ẢNH NHÚNG CÓ CHỮ trong PDF digital — đơn vị làm việc thật.

VÌ SAO ĐÂY LÀ MỘT BÀI TOÁN RIÊNG
────────────────────────────────
Mọi phép đo trước đây lấy đơn vị là TRANG hợp đồng scan: một trang A4 đầy
chữ, engine nào cũng đọc được phần lớn, và chênh lệch giữa chúng bị pha
loãng trong hàng nghìn ký tự giống nhau. Con số ra rất chung chung.

Bài toán thật nhỏ và khác hẳn: PDF digital đã có lớp text HOÀN HẢO (không
phải OCR, mà là chữ gốc do phần mềm sinh). Thứ duy nhất thiếu là chữ nằm
BÊN TRONG vài tấm ảnh chèn vào — ảnh chụp một ô bảng, một biên lai, một
màn hình. Thường chỉ vài chục tới vài trăm ký tự mỗi ảnh, nhưng đó lại là
mã số thuế, số đơn, ngày tháng.

Nên đơn vị đo phải là TẤM ẢNH, không phải trang. Và vì lớp text quanh nó
là chuẩn, ta có sẵn một mốc đối chiếu miễn phí ngay trong tệp.

DÒ KHÁC ĐỌC — VÀ PHẢI TÁCH RA
─────────────────────────────
Bản trước dùng Apple Vision để dò: chạy nhận dạng đầy đủ rồi xem có ra chữ
không. Hai cái sai:

  * Vision chỉ chạy trên macOS, mà việc DÒ thì phải chạy ở mọi nơi;
  * nhận dạng kém trên một ảnh sẽ bị hiểu nhầm là "ảnh không có chữ".

Ở đây dùng riêng phần DÒ của RapidOCR (DB-mobilenet, ONNX, 4,7 MB). Nó trả
về vùng có chữ mà KHÔNG đọc, nên kết quả không phụ thuộc vào việc model có
biết tiếng Việt hay không. Một bộ dò tốt cho câu trả lời đúng kể cả khi mọi
bộ đọc đều thất bại.

BA NHÓM ẢNH, CHỈ MỘT NHÓM ĐÁNG ĐỌC
──────────────────────────────────
  trống      không có vùng chữ nào        → bỏ qua
  khung      chữ lặp lại khắp kho         → logo, chân trang, watermark
  nội dung   chữ riêng của tấm ảnh này    → ĐÁNG ĐỌC

Phân biệt "khung" với "nội dung" bằng độ LẶP trên toàn kho, không phải
trong một tệp: chân trang công ty xuất hiện ở mọi tài liệu công ty đó phát
hành, nên mỗi tệp chỉ đóng góp một hai lần và phép đếm trong phạm vi một
tệp không bao giờ nhận ra.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

#: Ảnh nhỏ hơn mức này (pixel) gần như luôn là biểu tượng hoặc đường kẻ.
MIN_CANH = 64

#: Ảnh phải chiếm ít nhất ngần này phần trang thì mới đáng xét. Ảnh tí hon
#: đặt rải rác thường là bullet hoặc khung viền.
MIN_TI_LE_TRANG = 0.005

#: Số vùng chữ tối thiểu để coi là "có chữ". Một vùng đơn lẻ thường là nhiễu
#: từ hoa văn hoặc chữ ký.
MIN_VUNG_CHU = 2

#: Ảnh giống hệt nhau xuất hiện ở quá ngần này tấm trong TOÀN KHO thì là
#: khung trang. Đặt theo số tuyệt đối chứ không theo tỉ lệ: một logo xuất
#: hiện 40 lần là logo, bất kể kho có 100 hay 10.000 ảnh.
NGUONG_LAP_KHO = 4


@dataclass
class AnhNhung:
    """Một tấm ảnh nhúng, kèm bằng chứng vì sao nó được xếp nhóm ấy."""

    tep: str                  # đường dẫn tương đối của PDF
    trang: int                # số trang (1-based)
    xref: int                 # id ảnh trong PDF — định danh trong tệp đó
    rong: int
    cao: int
    ti_le_trang: float        # phần diện tích trang mà ảnh chiếm
    n_vung_chu: int = 0       # số vùng chữ bộ dò tìm được
    ti_le_dien_tich_chu: float = 0.0
    van_ban_lop_text: int = 0  # số ký tự lớp text của trang chứa nó
    bam_anh: str = ""         # băm nội dung — để nhận ra ảnh lặp toàn kho
    nhom: str = "trong"       # trong | khung | noi_dung
    ly_do: str = ""
    duong_dan_crop: str = ""  # nơi lưu ảnh cắt ra, để chạy engine sau

    @property
    def khoa(self) -> str:
        return f"{self.tep}#p{self.trang}#x{self.xref}"


def bam_noi_dung(data: bytes) -> str:
    """Băm nội dung ảnh — hai tấm giống hệt cho cùng một chuỗi.

    Dùng băm chứ không so từng byte: một logo có thể nhúng hàng trăm lần
    trong kho, và so cặp đôi là phép so bình phương.
    """
    return hashlib.sha256(data).hexdigest()[:16]


def phan_nhom(anh: AnhNhung, dem_bam: dict[str, int]) -> AnhNhung:
    """Xếp một tấm ảnh vào ba nhóm, kèm lý do đọc được.

    Thứ tự kiểm quan trọng: kiểm LẶP trước kiểm có-chữ, vì một logo có chữ
    vẫn là logo. Đảo lại thì mọi chân trang đều rơi vào nhóm "nội dung".
    """
    if dem_bam.get(anh.bam_anh, 0) >= NGUONG_LAP_KHO:
        anh.nhom = "khung"
        anh.ly_do = (f"ảnh giống hệt xuất hiện {dem_bam[anh.bam_anh]} lần "
                     f"trong kho — logo / chân trang / watermark")
        return anh

    if anh.n_vung_chu < MIN_VUNG_CHU:
        anh.nhom = "trong"
        anh.ly_do = (f"chỉ {anh.n_vung_chu} vùng chữ — ảnh minh hoạ, "
                     f"không phải tài liệu")
        return anh

    anh.nhom = "noi_dung"
    anh.ly_do = (f"{anh.n_vung_chu} vùng chữ, chiếm "
                 f"{anh.ti_le_dien_tich_chu:.0%} diện tích ảnh — "
                 f"chữ nằm trong ảnh, lớp text KHÔNG chứa")
    return anh


@dataclass
class DanhMuc:
    """Kết quả quét một kho."""

    anh: list[AnhNhung] = field(default_factory=list)

    def theo_nhom(self, nhom: str) -> list[AnhNhung]:
        return [a for a in self.anh if a.nhom == nhom]

    def duy_nhat(self, nhom: str) -> list[AnhNhung]:
        """Mỗi ẢNH một lần, dù nó xuất hiện trong bao nhiêu tệp.

        Kho này có bản sao của cùng một tài liệu ở nhiều thư mục (một tệp
        nằm trong cả 'Filing' lẫn 'Accounting'), nên cùng một tấm ảnh được
        đếm nhiều lần. Chạy engine trên bản sao là trả tiền hai lần cho
        cùng một câu trả lời — và làm mọi thống kê phồng lên.

        Đo trên kho thật: 59 lượt xuất hiện nhưng chỉ 38 ảnh khác nhau.
        """
        thay: dict[str, AnhNhung] = {}
        for a in self.anh:
            if a.nhom == nhom and a.bam_anh not in thay:
                thay[a.bam_anh] = a
        return list(thay.values())

    def tom_tat(self) -> dict:
        return {
            "tong_anh": len(self.anh),
            "trong": len(self.theo_nhom("trong")),
            "khung": len(self.theo_nhom("khung")),
            "noi_dung": len(self.theo_nhom("noi_dung")),
            "noi_dung_duy_nhat": len(self.duy_nhat("noi_dung")),
            "so_tep_co_noi_dung": len({a.tep for a in self.theo_nhom("noi_dung")}),
        }


__all__ = ["AnhNhung", "DanhMuc", "bam_noi_dung", "phan_nhom",
           "MIN_CANH", "MIN_TI_LE_TRANG", "MIN_VUNG_CHU", "NGUONG_LAP_KHO"]
