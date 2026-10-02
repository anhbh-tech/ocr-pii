#!/usr/bin/env python3
"""Sổ ngày: tách MỘT trường ngày thành BA, và khoá phép tính hạn vào nhãn.

Hôm nay trong kho có đúng một ngày cho mỗi tài liệu — sáu chữ số cuối tên
tệp. Sáu chữ số đó là ngày ai đó bấm lưu. Biên nhận của một hồ sơ tên là `260925`
trong khi USPTO ghi `Filing date: September 24, 2025`; thư kháng của hồ sơ khác tên là
`200525` trong khi chính bức thư đề `Hanoi, May 19, 2025`. Hạn trả lời
Office Action đang đếm từ con số trong tên.

Nên sổ này ghi ba trường tách bạch:

  ngay_luu_tep   ngày đọc ra từ TÊN TỆP — chỉ để hiển thị, để sắp xếp.
  ngay_van_ban   ngày đọc ra từ NỘI DUNG, kèm nhãn `loai` bắt buộc và
                 nguyên văn dòng nó nằm trong.
  ngay_sua_dia   mtime trên đĩa — dấu vết hệ thống tệp, không phải sự kiện.

Luật cứng: chỉ ngày MANG NHÃN mới được đem tính hạn. Luật này không nằm ở
lời dặn mà ở kiểu dữ liệu — `NgayHienThi` (tên tệp, mtime) không có phép
cộng; `han_tra_loi()` chỉ nhận `NgayCoNhan`. Đưa ngày tên tệp vào đó thì
chương trình dừng, không ra một con số trông như đúng. `--kiem-tra` kiểm
chính điều đó.

Nhãn lấy trong tập đóng {ky, nop, cap, hieu_luc, het_han}. Không suy ra
được nhãn thì ngày vẫn được ghi, với `trang_thai = "cho_nhan"` — chờ người
gán. Không tài liệu nào bị bỏ lặng.

Mọi ngày còn mang `nguon` trong tập đóng {ten_tep, dong_ho_chat, trong_loi,
mtime}. Ảnh chụp chat mà sổ kênh (`scripts/so_kenh.py`) đã nhận thêm khối
`hoi_thoai`: mọi ngày trong ảnh, mỗi ngày một nhãn nguồn, và giờ của giao
diện chat tách ra danh sách riêng — xem `thoi_gian_hoi_thoai()`.

Chạy:  python3 scripts/so_ngay.py            # dựng sổ
       python3 scripts/so_ngay.py --kiem-tra  # tự kiểm luật cứng
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ocr_lab.ade_store import doc_id_for  # noqa: E402

NGUON = Path.home() / ".private" / "refiny_data"
KHO = Path.home() / ".private" / "ade_out"
SO = Path.home() / ".private" / "so" / "ngay.json"

# Ngoài khoảng này thì con số bắt được là mã, là số điện thoại, là gì đó
# khác — không phải ngày của một tài liệu trong kho này.
NAM_SOM = 1980
NAM_MUON = 2040

# Ngưỡng của báo cáo `web/bao-cao/ten-tep-vs-noi-dung.html`: lệch trong
# vòng 45 ngày là độ trễ lưu trữ bình thường, ngoài ra là chuyện cần giải
# thích từng tệp.
NGUONG_LECH = 45


# ───────────────────────── kiểu ngày ─────────────────────────
#
# Hai kiểu, khác nhau ở đúng một điểm: một kiểu cộng trừ được, một kiểu
# không. Đó là toàn bộ cơ chế thi hành luật cứng.


class NgayKhongDuocTinh(TypeError):
    """Có ai đó vừa đem một ngày không nhãn đi tính hạn."""


@dataclass(frozen=True)
class NgayHienThi:
    """Ngày KHÔNG mang nhãn: tên tệp, mtime. Hiển thị và sắp xếp, hết.

    Không có `.date` công khai, không cộng được với timedelta. Muốn lấy ra
    một `datetime.date` để tính thì phải gọi `cho_phep_tinh()` — một cái
    tên dài, cố ý, để nó không trôi qua mắt người đọc diff.
    """

    gia_tri: dt.date
    nguon: str  # "ten_tep" | "mtime"
    nguyen_van: str = ""

    def __str__(self) -> str:
        return self.gia_tri.isoformat()

    def __add__(self, other: object) -> "NgayHienThi":
        raise NgayKhongDuocTinh(
            f"{self.nguon}: ngày không mang nhãn `loai`, không được đem tính hạn"
        )

    __radd__ = __sub__ = __rsub__ = __add__

    def cho_phep_tinh(self) -> dt.date:
        raise NgayKhongDuocTinh(
            f"{self.nguon}: ngày không mang nhãn `loai`, không được đem tính hạn"
        )


LOAI_HOP_LE = ("ky", "nop", "cap", "hieu_luc", "het_han")


@dataclass(frozen=True)
class NgayCoNhan:
    """Ngày đọc từ NỘI DUNG và đã được gán nhãn. Chỉ kiểu này tính được hạn."""

    gia_tri: dt.date
    loai: str
    trich_dan: str
    dong: int
    manh_mo: str  # cụm chữ đã kích hoạt nhãn
    mo_ho_thu_tu: bool = False  # d/m hay m/d đều đọc được — đã chọn d/m

    def __post_init__(self) -> None:
        if self.loai not in LOAI_HOP_LE:
            raise ValueError(f"nhãn lạ: {self.loai!r}")

    def __str__(self) -> str:
        return self.gia_tri.isoformat()

    def cho_phep_tinh(self) -> dt.date:
        return self.gia_tri


def han_tra_loi(moc: NgayCoNhan, so_ngay: int) -> dt.date:
    """Cửa DUY NHẤT để một cái hạn ra đời trong sổ này.

    Nhận `NgayCoNhan` — nghĩa là một ngày đã biết mình là ngày gì. Đưa vào
    đây một `NgayHienThi` (ngày tên tệp, mtime) thì nó ném, không trả số.
    """
    if not isinstance(moc, NgayCoNhan):
        raise NgayKhongDuocTinh(
            "han_tra_loi() chỉ nhận ngày mang nhãn `loai`; "
            f"nhận được {type(moc).__name__}"
        )
    return moc.cho_phep_tinh() + dt.timedelta(days=so_ngay)


# ───────────────────────── đọc ngày ─────────────────────────

THANG_ANH = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"


def _ngay(nam: int, thang: int, ngay: int) -> dt.date | None:
    if not NAM_SOM <= nam <= NAM_MUON:
        return None
    try:
        return dt.date(nam, thang, ngay)
    except ValueError:
        return None


def _bo_dau(s: str) -> str:
    """Bỏ dấu để so cụm. `đ` KHÔNG phải `d` có dấu — NFD không tách nó ra,
    nên phải thay tay, nếu không `Hợp đồng` thành `hop đong` và mọi cụm
    mốc chứa chữ `đ` trượt hết."""
    s = s.replace("Đ", "D").replace("đ", "d")
    s = re.sub(r"<br\s*/?>", " ", s)
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    ).lower()


# ── ngày trong TÊN TỆP ──

_TEN_ISO = re.compile(r"(?<!\d)(20\d{2})[-._](\d{1,2})[-._](\d{1,2})(?!\d)")
_TEN_8 = re.compile(r"(?<!\d)(\d{2})(\d{2})(19|20)(\d{2})(?!\d)")
_TEN_8_NAM_TRUOC = re.compile(r"(?<!\d)(19|20)(\d{2})(\d{2})(\d{2})(?!\d)")
_TEN_6 = re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)")


def ngay_tu_ten_tep(ten: str) -> NgayHienThi | None:
    """Sáu chữ số cuối tên tệp là `ddmmyy` — quy ước lưu trữ của phòng IP.

    Cũng đọc `yyyy-mm-dd` đầu tên (hoá đơn đại diện Hoa Kỳ) và `ddmmyyyy` tám chữ số.
    Lấy cụm CUỐI cùng khi có nhiều cụm: `V2025-903_080825` thì `2025-903`
    là số đề nghị thanh toán, `080825` mới là ngày.
    """
    goc = Path(ten).stem
    m = _TEN_ISO.search(goc)
    if m:
        d = _ngay(int(m[1]), int(m[2]), int(m[3]))
        if d:
            return NgayHienThi(d, "ten_tep", m[0])
    # `..._Application_20250708_230511.pdf`: `20250708` là ngày, `230511`
    # là giờ xuất tệp. Đọc `yyyymmdd` TRƯỚC thì `230511` không còn cơ hội
    # trở thành 23/05/2011.
    for m in _TEN_8_NAM_TRUOC.finditer(goc):
        d = _ngay(int(m[1] + m[2]), int(m[3]), int(m[4]))
        if d:
            return NgayHienThi(d, "ten_tep", m[0])
    for m in _TEN_8.finditer(goc):
        nam = int(m[3] + m[4])
        a, b = int(m[1]), int(m[2])
        d = _ngay(nam, b, a) or _ngay(nam, a, b)  # ddmmyyyy trước, rồi mmddyyyy
        if d:
            return NgayHienThi(d, "ten_tep", m[0])
    cuoi = None
    for m in _TEN_6.finditer(goc):
        d = _ngay(2000 + int(m[3]), int(m[2]), int(m[1]))
        if d:
            cuoi = NgayHienThi(d, "ten_tep", m[0])
    return cuoi


# ── ngày trong NỘI DUNG ──

_ND = [
    # yyyy-mm-dd
    (re.compile(r"(?<![\d/])(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?![\d/])"),
     lambda m: (_ngay(int(m[1]), int(m[2]), int(m[3])), False)),
    # Month d, yyyy  /  Month d yyyy
    (re.compile(rf"\b({_MON})\s+(\d{{1,2}})\s*,?\s+((?:19|20)\d{{2}})\b", re.I),
     lambda m: (_ngay(int(m[3]), THANG_ANH[_bo_dau(m[1])[:3]], int(m[2])), False)),
    # d Month yyyy
    (re.compile(rf"\b(\d{{1,2}})\s+({_MON})\s*,?\s+((?:19|20)\d{{2}})\b", re.I),
     lambda m: (_ngay(int(m[3]), THANG_ANH[_bo_dau(m[2])[:3]], int(m[1])), False)),
    # ngày d tháng m năm yyyy
    (re.compile(r"ngay\s+(\d{1,2})\s+thang\s+(\d{1,2})\s+nam\s+((?:19|20)\d{2})"),
     lambda m: (_ngay(int(m[3]), int(m[2]), int(m[1])), False)),
    # d/m/yyyy, d-m-yyyy, d.m.yyyy  (và yy hai chữ số)
    # Chặn chữ cái phía trước: `L18-11-13` là số phòng trong địa chỉ trụ sở,
    # không phải 18/11/2013. Một địa chỉ đọc thành ngày là cách êm nhất để
    # một cái hạn sai lọt vào sổ.
    (re.compile(r"(?<![A-Za-z0-9/.\-])(\d{1,2})[/.-](\d{1,2})[/.-]((?:19|20)\d{2}|\d{2})(?![\d/.\-])"),
     None),  # xử lý riêng bên dưới: thứ tự d/m có thể mơ hồ
]


# `12/03/2025` trên hoá đơn đại diện Hoa Kỳ là 3 tháng 12; cùng chuỗi ấy trên đề nghị
# thanh toán của Refiny là 12 tháng 3. Không có cách nào đọc đúng cả hai
# bằng MỘT quy ước, nên thứ tự lấy theo ngôn ngữ của chính tài liệu, và
# mọi ngày mơ hồ đều mang cờ `mo_ho_thu_tu` ra sổ để người soát thấy.
_thu_tu_ngay_m_truoc = False

_VIET = re.compile(r"[àáâãèéêìíòóôõùúýăđĩũơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", re.I)


def _tai_lieu_tieng_anh(markdown: str) -> bool:
    """Ít hơn 1 chữ có dấu trên 400 ký tự thì coi là văn bản tiếng Anh."""
    return len(_VIET.findall(markdown)) * 400 < len(markdown)


def _doc_so_co_dau(m: re.Match[str]) -> tuple[dt.date | None, bool]:
    a, b, c = int(m[1]), int(m[2]), m[3]
    nam = int(c) if len(c) == 4 else 2000 + int(c)
    if a > 12 and b <= 12:  # chỉ đọc được d/m
        return _ngay(nam, b, a), False
    if b > 12 and a <= 12:  # chỉ đọc được m/d
        return _ngay(nam, a, b), False
    d = _ngay(nam, a, b) if _thu_tu_ngay_m_truoc else _ngay(nam, b, a)
    return d, d is not None


_ND[-1] = (_ND[-1][0], _doc_so_co_dau)


def _moi_ngay_trong_dong(
    dong_khong_dau: str,
) -> Iterable[tuple[int, dt.date, bool, int]]:
    """Mọi ngày trong một dòng: (vị trí đầu, ngày, cờ mơ hồ, vị trí cuối)."""
    thay: dict[int, tuple[dt.date, bool, int]] = {}
    for pat, doc in _ND:
        for m in pat.finditer(dong_khong_dau):
            d, mo_ho = doc(m)
            if d and m.start() not in thay:
                thay[m.start()] = (d, mo_ho, m.end())
    for vt in sorted(thay):
        yield vt, thay[vt][0], thay[vt][1], thay[vt][2]


# Bảng nhãn. Thứ tự QUAN TRỌNG: cụm dài, cụ thể đứng trước. "effective date
# of registration" là ngày hiệu lực, không phải ngày cấp — nên `hieu_luc`
# phải được thử trước `cap`. Mọi cụm viết không dấu vì dòng đã bỏ dấu.
BANG_NHAN: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("het_han", (
        "expiration date", "expiry date", "expires on", "expires", "date of expiry",
        "due date", "payment due on", "payment due", "due on", "deadline",
        "no later than", "must be filed by", "response due", "han chot",
        "ngay het han", "het han vao", "het han ngay", "cham nhat ngay",
        "cham nhat la ngay", "truoc ngay", "han tra loi",
    )),
    ("hieu_luc", (
        "effective date of registration", "effective date", "effective as of",
        "effective from", "in effect from", "ngay co hieu luc",
        "co hieu luc ke tu ngay", "co hieu luc tu ngay", "hieu luc ke tu ngay",
        "hieu luc tu ngay",
    )),
    ("nop", (
        "filing date", "date of filing", "date filed", "filed on", "filed:",
        "application date", "date of application", "application filed",
        "submitted on", "date submitted",
        "ngay nop don", "nop don ngay", "ngay nop ho so", "ngay nop",
    )),
    ("cap", (
        "registration decision date", "notice of allowance date",
        "date of registration", "registration date", "date of issue",
        "issue date", "issued on", "date issued", "granted on",
        "certificate date", "publication date", "date of publication",
        "date of 1st publication", "date of 1", "notice date", "status date",
        "ngay cap", "cap ngay", "ngay dang ky", "dang ky lan dau",
        "ngay cong bo", "ngay ra quyet dinh",
    )),
    ("ky", (
        "date signed", "signature date", "signed on", "date of signature",
        "executed on", "in witness whereof", "ngay ky", "ky ngay", "ky vao ngay",
        "ngay de nghi thanh toan", "ngay lap",
        "lap ngay", "duoc ky ngay",
    )),
)

# Dòng mở đầu thư/hợp đồng: "Hanoi, May 19, 2025" — nơi chốn rồi dấu phẩy
# rồi ngày. Đó là ngày lập văn bản, tính là `ky`.
_DIA_DANH = re.compile(
    r"^\s*(?:ha ?noi|hanoi|ha noi|tp\.? ?ho chi minh|ho chi minh city|hai phong|"
    r"da nang|tphcm)\s*,\s*(?:ngay\s+)?",
)

# Những dòng có ngày nhưng ngày ấy không phải ngày của tài liệu này.
_DONG_BO = (
    "ngay, thang, nam sinh", "date of birth", "ngay sinh", "sinh ngay",
    "so 36/2005/qh11", "so 50/2005/qh11", "so 91/2015/qh13",
    "approved for use through", "omb no", "cap nhat lan cuoi",
    "first use", "first date of use", "date of use in commerce",
    "su dung dau tien", "su dung trong thuong mai",
    "tru so:", "tru so chinh:", "dia chi:", "dia chi thuong tru",
    "ty gia", "vietcombank ngay",
)

# Đầu trang in từ trình duyệt: `12/3/25, 9:28 AM`. Giờ giấc đứng ngay sau
# ngày là dấu hiệu chắc chắn đây là lúc ai đó bấm In, không phải ngày của
# văn bản — và đó cũng đúng là thứ sổ này sinh ra để không đếm.
_DAU_TRANG_IN = re.compile(
    r"^\s*(?:\d{1,2}:\d{2}(:\d{2})?\s+\d{1,2}/\d{1,2}/\d{2,4}"
    r"|\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}(:\d{2})?\s*(am|pm)?)"
)

# Dòng chỉ có mỗi con số ngày — docx tách nhãn và giá trị thành hai dòng,
# nên nhãn "Ngày, tháng, năm sinh" nằm ở dòng trên.
_CHI_CO_NGAY = re.compile(r"^[\d\s/.:-]+$")


def _nhan_cho_dong(khung: str, ca_dong: str) -> tuple[str, str] | None:
    """Nhãn suy ra từ chữ ĐỨNG TRƯỚC ngày, trong dòng chứa ngày và dòng trên.

    Hai dòng, không hơn: bản PDF ngắt câu giữa chừng nên cụm "Căn cước công
    dân số ... cấp ngày" thường rơi làm đôi. Quá hai dòng thì nhãn bắt đầu
    vay từ đoạn khác, và một nhãn vay là một nhãn bịa.
    """
    for loai, cum in BANG_NHAN:
        for c in cum:
            if c in khung:
                return loai, c
    if _DIA_DANH.match(ca_dong):
        return "ky", "dia danh dau thu"
    return None


# ───────────────────────── ngày CỦA AI ─────────────────────────
#
# Một cái nhãn thôi chưa đủ. Trang đầu hợp đồng NH9001 có "cấp ngày
# 03/03/2020" — nhãn `cap` đúng, nhưng đó là ngày cấp CĂN CƯỚC của bên A,
# không phải ngày của hợp đồng. Phụ lục PL01 mở đầu bằng "ký ngày
# 20/11/2024" — nhãn `ky` đúng, nhưng là ngày ký HỢP ĐỒNG GỐC mà phụ lục
# dẫn chiếu. Đếm hạn từ một trong hai là sai y như đếm từ tên tệp.
#
# Nên mỗi ngày mang thêm `chu_the`: ngày này của ai. Chỉ
# `chinh_tai_lieu` mới được tính.

CHU_THE_BEN_KY = (
    "can cuoc cong dan so", "can cuoc cong dan", "cccd so", "cmnd so",
    "chung minh nhan dan", "ho chieu so", "passport no", "so dinh danh ca nhan",
    "giay phep hoat dong", "dang ky kinh doanh", "giay chung nhan dang ky doanh nghiep",
    "ma so thue", "quan ly hanh chinh ve trat tu", "cuc canh sat",
)

CHU_THE_DAN_CHIEU = (
    "theo hop dong", "can cu vao hop dong", "can cu hop dong",
    "theo hop dong dich vu", "cua hop dong so", "theo quyet dinh so",
    "theo giay chung nhan", "quy dinh tai dieu", "theo thong bao so",
    "cua luat so", "ban hanh ngay",
)

# Tên tệp nói tài liệu là bản chụp trang của bên khác: mọi ngày trong đó
# là ngày của bên khác.
TEN_BEN_THU_BA = (
    "anh man hinh", "screenshot", "specimen", "evidence", "tang chung",
    "doi chung", "cited mark", "tra cuu", "bao khach",
)

_DINH_NGHIA = (
    ("ky", ("ngay ky",)),
    ("hieu_luc", ("ngay co hieu luc", "ngay hieu luc", "effective date")),
    ("nop", ("ngay nop",)),
    ("het_han", ("ngay het han",)),
)


def _dinh_nghia_sau(khong_dau: str, het: int) -> str | None:
    """Hợp đồng Việt tự đặt tên cho ngày của chính nó, ngay sau con số:
    `Vào ngày 19 tháng 9 năm 2025 (“Ngày Ký”)`. Dấu ngoặc ấy là lời tài
    liệu tự khai đây là ngày CỦA TÔI — tín hiệu chắc nhất có trong kho.
    """
    duoi = khong_dau[het : het + 90]
    if "(" not in duoi and '"' not in duoi and "“" not in duoi:
        return None
    for loai, cum in _DINH_NGHIA:
        for c in cum:
            if c in duoi:
                return loai
    return None


def _chu_the(khung: str, ben_thu_ba_toan_tep: bool) -> str:
    for c in CHU_THE_BEN_KY:
        if c in khung:
            return "ben_ky"
    for c in CHU_THE_DAN_CHIEU:
        if c in khung:
            return "van_ban_dan_chieu"
    return "ben_thu_ba" if ben_thu_ba_toan_tep else "chinh_tai_lieu"


_SO_DAI = re.compile(r"(?<!\d)\d{9,}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
_DT = re.compile(r"(?<!\d)(?:\+?84|0)\d{8,10}(?!\d)")


def che(dong: str) -> str:
    """Che định danh trực tiếp trước khi trích dẫn vào sổ.

    Sổ nằm ngoài git nhưng vẫn là một bản sao: dòng `Số định danh cá nhân:
    030099000002` không có lý do gì để nhân bản thêm một lần nữa. Ngày và
    số đơn USPTO (8 chữ số) giữ nguyên — đó là thứ tra cứu công khai được.
    """
    dong = _EMAIL.sub("[email]", dong)
    dong = _DT.sub("[sdt]", dong)
    dong = _SO_DAI.sub("[so-dinh-danh]", dong)
    return dong


@dataclass
class UngVien:
    ngay: dt.date
    loai: str | None
    chu_the: str
    manh_mo: str
    dong_so: int
    trich: str
    mo_ho: bool
    tu_dinh_nghia: bool


def _uu_tien(uv: UngVien) -> tuple:
    """Thứ tự chọn. Nhỏ hơn là được chọn trước.

    1. Tài liệu tự khai ngày của nó (`(“Ngày Ký”)`).
    2. Có nhãn và là ngày của chính tài liệu.
    3. Có nhãn nhưng của bên ký / văn bản dẫn chiếu / bên thứ ba.
    4. Không nhãn.
    Cùng bậc thì lấy cái ĐỨNG TRƯỚC: đầu văn bản là chỗ tài liệu nói về
    chính nó — dòng đề thư, ô "Filing date", dòng "Ngày cấp".
    """
    if uv.tu_dinh_nghia and uv.loai:
        bac = 0
    elif uv.loai and uv.chu_the == "chinh_tai_lieu":
        bac = 1
    elif uv.loai:
        bac = 2
    else:
        bac = 3
    return (bac, uv.dong_so)


def ung_vien_ngay(markdown: str, ten_tep: str = "") -> list[UngVien]:
    """Mọi ngày đọc được trong nội dung, kèm nhãn và chủ thể."""
    global _thu_tu_ngay_m_truoc
    _thu_tu_ngay_m_truoc = _tai_lieu_tieng_anh(markdown)
    kd_ten = _bo_dau(ten_tep)
    ben_thu_ba = any(c in kd_ten for c in TEN_BEN_THU_BA)
    dong = markdown.splitlines()
    kds = [_bo_dau(d) for d in dong]
    ra: list[UngVien] = []
    for i, kd in enumerate(kds):
        tren = kds[i - 1] if i else ""
        if any(bo in kd for bo in _DONG_BO):
            continue
        if _DAU_TRANG_IN.match(kd.strip()):
            continue
        if _CHI_CO_NGAY.match(kd.strip()) and any(bo in tren for bo in _DONG_BO):
            continue
        for vt, d, mo_ho, het in _moi_ngay_trong_dong(kd):
            # +6: dạng Việt `ký ngày 28 tháng 08 năm 2025` khớp ngay từ chữ
            # `ngày`, nên cụm mốc `ky ngay` nằm vắt qua đầu chỗ khớp.
            khung = (tren + " " + kd[: vt + 6])[-266:]
            nhan = _nhan_cho_dong(khung, kd)
            tu_dn = _dinh_nghia_sau(kd, het)
            loai = nhan[0] if nhan else tu_dn
            manh = nhan[1] if nhan else (f"tu dinh nghia: {tu_dn}" if tu_dn else "")
            ct = "chinh_tai_lieu" if tu_dn else _chu_the(khung, ben_thu_ba)
            ra.append(UngVien(d, loai, ct, manh, i + 1,
                              che(dong[i].strip())[:300], mo_ho, bool(tu_dn)))
    return ra


_ISO_XLSX = re.compile(r"(?<!\d)(20\d{2})-(\d{2})-(\d{2}) 00:00:00")


def _mo_ho_o_xlsx(uv: "UngVien", duong_dan: str) -> bool:
    """Ô ngày trong xlsx ra chuỗi ISO, nhưng thứ tự ngày/tháng của nó đã
    lệch ít nhất hai lần trong kho: bản PDF của CÙNG chứng từ V2025-901 in
    `8/10/2025`, ô xlsx ra `2025-08-10`. Khi cả hai vế đều ≤ 12 thì không
    có cách nào phân biệt — nên đánh dấu mơ hồ thay vì tin.
    """
    if not duong_dan.lower().endswith(".xlsx"):
        return False
    m = _ISO_XLSX.search(uv.trich)
    return bool(m and int(m[2]) <= 12 and int(m[3]) <= 12)


def thu_tu_ngay(markdown: str) -> str:
    return "m/d" if _tai_lieu_tieng_anh(markdown) else "d/m"


def doc_ngay_van_ban(markdown: str, ten_tep: str = "") -> tuple[UngVien | None, int]:
    """Ngày của CHÍNH tài liệu, nếu đọc ra được; kèm tổng số ngày thấy.

    Không bao giờ trả None khi nội dung có ngày: một ngày không nhãn vẫn
    được ghi vào sổ ở trạng thái chờ, vì bỏ lặng một tài liệu nguy hiểm
    hơn là ghi nó kèm lời thú nhận chưa biết ngày ấy là ngày gì.
    """
    uv = ung_vien_ngay(markdown, ten_tep)
    if not uv:
        return None, 0
    return min(uv, key=_uu_tien), len(uv)


def thanh_ngay_co_nhan(uv: UngVien) -> NgayCoNhan | None:
    """Nâng ứng viên thành ngày TÍNH ĐƯỢC — chỉ khi đủ cả nhãn lẫn chủ thể."""
    if not uv.loai or uv.chu_the != "chinh_tai_lieu":
        return None
    return NgayCoNhan(uv.ngay, uv.loai, uv.trich, uv.dong_so, uv.manh_mo, uv.mo_ho)


# ───────────── tệp lệch quá ngưỡng: giải thích từng tệp ─────────────
#
# Các tệp này đã được đọc tay, từng tệp một. Khoá là tên tệp vì cùng một
# tệp nằm ở hai hồ sơ thì lời giải thích không đổi. `hop_le = True` nghĩa
# là hai ngày ĐỀU đúng và chênh nhau là đúng bản chất — không phải lỗi
# nhập liệu, không có gì để sửa.
#
# Khoá là tên tệp THẬT của kho, nên bảng nằm cạnh sổ ngoài cây git, không
# trong mã: `{"tep": {<tên tệp>: {"hop_le", "chu_the", "giai_thich"}}}`.
GIAI_THICH_LECH = Path.home() / ".private" / "so" / "giai_thich_lech.json"


def giai_thich_lech(tep: Path = GIAI_THICH_LECH) -> dict[str, dict[str, object]]:
    """Phán xét đọc tay theo tên tệp. Thiếu tệp thì rỗng: tệp lệch nào cũng
    thành `chua_phan_xet`, không có phán xét nào được bịa ra."""
    if not tep.is_file():
        return {}
    return json.loads(tep.read_text(encoding="utf-8"))["tep"]


# ─────────────── ba tầng thời gian trong ảnh chụp hội thoại ───────────────
#
# Một ảnh chụp chat trộn ba thứ trông giống nhau: ngày trong TÊN TỆP
# (`_ddmmyy`), đồng hồ của GIAO DIỆN chat (`13.43` dưới mỗi cụm tin, dòng
# phân cách `T4 01/10/2025`), và ngày người ta gõ TRONG LỜI (`trước 30/9`,
# thiếu năm). Đếm cả ba là ngày thì phần lớn "ngày" là giờ. Nên mỗi con số
# thời gian ở đây mang nhãn nguồn, và giờ đi danh sách riêng: giờ không
# phải ngày.
#
# Tệp nào là hội thoại, thuộc kênh nào, mốc năm là gì — đọc từ sổ kênh
# (`scripts/so_kenh.py`), không đoán lại. Dòng phân cách và giờ cũng đọc
# bằng chính hàm của sổ kênh, để hai sổ không bao giờ cho cùng một dòng hai
# ngày khác nhau.

KENH = Path.home() / ".private" / "so" / "kenh" / "hoi_thoai"

# Tập đóng nhãn nguồn của MỌI ngày trong sổ. Ba nhãn đầu là ba tầng của
# hội thoại; `mtime` là trường thứ ba của sổ từ trước.
NGUON_NGAY = ("ten_tep", "dong_ho_chat", "trong_loi", "mtime")


def _so_kenh():
    """so_kenh nhập so_ngay ngay đầu tệp, nên chiều ngược lại phải nhập muộn."""
    thu_muc = str(Path(__file__).resolve().parent)
    if thu_muc not in sys.path:
        sys.path.insert(0, thu_muc)
    import so_kenh

    return so_kenh


# Giờ: `d.dd`/`dd.dd` (hoặc dấu `:`) không dính cụm thứ ba — `8.10.2025`
# là ngày, `34.398.000` là tiền, `1:25-cv-…` là số vụ kiện. Đơn vị theo sau
# thì là cỡ tệp, là tiền: `1.26 MB` không phải 01:26. Ngưỡng ≤ 23:59 do
# `so_kenh.doc_gio` xét.
_GIO_TRONG_DONG = re.compile(
    r"(?<![a-z0-9$])(?<![0-9a-z][.:/\-])(\d{1,2}[.:]\d{2})"
    r"(?![0-9])(?![.:/\-][0-9a-z])(?!\s*(?:(?:kb|mb|gb|tb|usd|vnd)\b|%))"
)
_CHI_CO_GIO = re.compile(r"\W*\d{1,2}[.:]\d{2}\W*")

# Ngày thiếu năm trong lời: `30/9`, `28/05`. Chỉ dấu `/`: `24.10` quá 23.59
# nên không phải giờ, nhưng dấu chấm còn là dấu thập phân, và một ngày đoán
# ra từ một số thập phân là một ngày bịa.
_NGAY_THIEU_NAM = re.compile(r"(?<![a-z0-9/.\-])(\d{1,2})/(\d{1,2})(?![0-9])(?![/.\-][0-9])")


def _dong_hoi_thoai(dong: str) -> str:
    """Một dòng markdown về chữ trần, như sổ kênh thấy nó."""
    dong = re.sub(r"<!--.*?-->|<br\s*/?>|<[^>]+>", " ", dong)
    dong = re.sub(r"\[[A-Z_ ]+\]", " ", dong)  # `11:32 [LIKE_ICON]`
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", dong)).strip()


def _ghi_suy_nam(d: dt.date, moc: dt.date, nguon_moc: str) -> dict:
    ra: dict = {"so_voi": moc.isoformat(), "so_voi_nguon": nguon_moc,
                "lui_nam": d.year < moc.year}
    if ra["lui_nam"]:
        try:
            ra["neu_khong_lui"] = d.replace(year=moc.year).isoformat()
        except ValueError:  # 29/02 không có ở năm mốc
            pass
    return ra


def thoi_gian_hoi_thoai(
    markdown: str, ten_tep: NgayHienThi | None, moc_kenh: dt.date | None
) -> dict:
    """Mọi con số thời gian trong một ảnh chụp chat, mỗi cái một nhãn nguồn.

    `ngay` chỉ chứa ngày; giờ nằm ở `gio`. Nhãn nguồn:
      ten_tep       ngày trong tên tệp
      dong_ho_chat  giao diện chat in ra: giờ dưới cụm tin, dòng phân cách
      trong_loi     ngày viết trong nội dung — tin nhắn chat hoặc thân văn bản

    Ngày thiếu năm lấy năm của mốc. Mốc của ảnh là luật của sổ kênh: ngày
    tên tệp, tệp không ngày thì ngày tên tệp muộn nhất của kênh. Dòng phân
    cách dùng đúng mốc ấy, để khớp sổ kênh từng dòng. Ngày trong lời so với
    tin liền trước: dòng phân cách có ngày gần nhất phía trên nó trong cùng
    ảnh, không có thì mốc của ảnh. Rơi sau mốc thì lùi một năm, và `lui_nam`
    ghi lại việc đó kèm giá trị nếu không lùi — một hạn chót hẹn trước cũng
    rơi sau mốc, và với nó thì lùi là sai. Mọi ngày ở đây chỉ để hiển thị.
    """
    global _thu_tu_ngay_m_truoc
    _thu_tu_ngay_m_truoc = _tai_lieu_tieng_anh(markdown)
    sk = _so_kenh()
    moc = ten_tep.gia_tri if ten_tep else moc_kenh
    nguon_moc = "ten_tep" if ten_tep else "ten_tep_kenh"
    ngay: list[dict] = []
    gio: list[dict] = []
    if ten_tep:
        ngay.append({"gia_tri": ten_tep.gia_tri.isoformat(), "nguon": "ten_tep",
                     "nguyen_van": ten_tep.nguyen_van, "dong": None, "dung_de": "hien_thi"})
    moc_tin, nguon_moc_tin = moc, nguon_moc
    for so_dong, tho in enumerate(markdown.splitlines(), 1):
        dong = _dong_hoi_thoai(tho)
        if not dong:
            continue
        pc = sk.doc_phan_cach(dong, moc)
        if pc is not None:
            if pc.get("gio"):
                gio.append({"gia_tri": pc["gio"], "nguon": "dong_ho_chat",
                            "nguyen_van": pc["nguyen_van"], "dong": so_dong})
            muc = {"gia_tri": pc["ngay"], "nguon": "dong_ho_chat",
                   "nguyen_van": pc["nguyen_van"], "dong": so_dong, "dung_de": "hien_thi"}
            if pc.get("tuong_doi"):
                # `Hôm qua` so với lúc chụp, mà lúc chụp không ai ghi: sổ
                # kênh để trống giá trị, ở đây cũng vậy.
                muc["tuong_doi"] = pc["tuong_doi"]
                moc_tin, nguon_moc_tin = moc, nguon_moc
            elif pc["ngay"]:
                d = dt.date.fromisoformat(pc["ngay"])
                if pc.get("suy_nam"):
                    muc["suy_nam"] = _ghi_suy_nam(d, moc, nguon_moc)
                moc_tin, nguon_moc_tin = d, "dong_ho_chat"
            else:
                muc["thieu_moc_nam"] = True
            ngay.append(muc)
            continue

        kd = _bo_dau(dong)
        goc = dong if len(kd) == len(dong) else kd
        trich = che(dong)[:300]
        chiem: list[tuple[int, int]] = []
        for vt, d, mo_ho, het in _moi_ngay_trong_dong(kd):
            chiem.append((vt, het))
            ngay.append({"gia_tri": d.isoformat(), "nguon": "trong_loi",
                         "nguyen_van": goc[vt:het], "dong": so_dong, "dung_de": "hien_thi",
                         "mo_ho_thu_tu": mo_ho, "trich_dan": trich})
        for m in _NGAY_THIEU_NAM.finditer(kd):
            if any(a <= m.start() < b for a, b in chiem):
                continue
            ng, th = int(m[1]), int(m[2])
            muc = {"gia_tri": None, "nguon": "trong_loi", "nguyen_van": m[0],
                   "dong": so_dong, "dung_de": "hien_thi", "trich_dan": trich}
            if moc_tin is None:
                if _ngay(2000, th, ng) is None:  # 31/2, 1/13: không phải ngày
                    continue
                muc["thieu_moc_nam"] = True
            else:
                d = sk.ngay_thieu_nam(ng, th, moc_tin)
                if d is None:
                    continue
                muc["gia_tri"] = d.isoformat()
                muc["suy_nam"] = _ghi_suy_nam(d, moc_tin, nguon_moc_tin)
            chiem.append(m.span())
            ngay.append(muc)
        chi_gio = bool(_CHI_CO_GIO.fullmatch(dong))
        for m in _GIO_TRONG_DONG.finditer(kd):
            g = sk.doc_gio(m[1])
            if g is None or any(a <= m.start() < b for a, b in chiem):
                continue
            gio.append({"gia_tri": g, "nguon": "dong_ho_chat" if chi_gio else "trong_loi",
                        "nguyen_van": m[1], "dong": so_dong})

    theo_nguon = {n: sum(1 for x in ngay if x["nguon"] == n) for n in NGUON_NGAY[:3]}
    return {
        "moc_nam": {"gia_tri": moc.isoformat(), "nguon": nguon_moc} if moc else None,
        "ngay": ngay,
        "gio": gio,
        "dem": {
            "ngay_theo_nguon": theo_nguon,
            "ngay_co_gia_tri": sum(1 for x in ngay if x["gia_tri"]),
            "tuong_doi": sum(1 for x in ngay if "tuong_doi" in x),
            "suy_nam": sum(1 for x in ngay if "suy_nam" in x),
            "lui_nam": sum(1 for x in ngay if x.get("suy_nam", {}).get("lui_nam")),
            "gio": len(gio),
        },
    }


def nap_so_kenh(dich: Path | None = None) -> dict[str, dict]:
    """doc_id → {kenh_id, ban_parse, moc_kenh} cho mọi tệp sổ kênh nhận là chat.

    `moc_kenh` là ngày tên tệp muộn nhất của kênh, tính cả bản trùng, đọc
    bằng cùng `ngay_tu_ten_tep` — đúng mốc sổ kênh dùng cho ảnh không có
    ngày trong tên. Tệp không do sổ kênh sinh thì bỏ qua.
    """
    dich = dich or KENH
    ra: dict[str, dict] = {}
    if not dich.is_dir():
        return ra
    for f in sorted(dich.glob("*.json")):
        try:
            k = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if k.get("nguon_sinh") != _so_kenh().NGUON_SINH or not k.get("tin"):
            continue
        tep = []
        for t in k["tin"]:
            tep.append((t["doc_id"], t["duong_dan"], t.get("ban_parse")))
            tep += [(b["doc_id"], b["duong_dan"], None) for b in t.get("ban_trung", [])]
        moc_kenh = max(
            (n.gia_tri for _, p, _ in tep if (n := ngay_tu_ten_tep(Path(p).name))),
            default=None,
        )
        for doc_id, _, ban in tep:
            ra[doc_id] = {"kenh_id": k["kenh_id"], "ban_parse": ban, "moc_kenh": moc_kenh}
    return ra


def _doc_ban(ma: str, ban: str | None) -> str:
    """Markdown của đúng bản parse mà sổ kênh đã đọc."""
    if not ban:
        return ""
    try:
        return json.loads((KHO / ma / f"{ban}.json").read_text()).get("markdown") or ""
    except (json.JSONDecodeError, OSError):
        return ""


# ───────────────────────── dựng sổ ─────────────────────────


def _nap_kho() -> list[tuple[str, str, str]]:
    """(ma, đường dẫn tương đối, markdown) cho mọi tài liệu trong kho."""
    ra = []
    for thu_muc in sorted(KHO.iterdir()):
        if not thu_muc.is_dir():
            continue
        meta = None
        for ten in ("meta_pro.json", "meta.json"):
            f = thu_muc / ten
            if f.exists():
                meta = json.loads(f.read_text())
                break
        if meta is None:
            continue
        md = ""
        for ten in ("parse_pro.json", "parse.json"):
            f = thu_muc / ten
            if f.exists():
                try:
                    md = json.loads(f.read_text()).get("markdown") or ""
                except (json.JSONDecodeError, OSError):
                    md = ""
                if md:
                    break
        ra.append((thu_muc.name, meta.get("source", ""), md))
    return ra


def _ho_so(rel: str) -> str:
    """Tên hồ sơ = thư mục cấp 3 (`902. US. QUILLOW...`)."""
    phan = Path(rel).parts
    return phan[2] if len(phan) > 2 else (phan[-2] if len(phan) > 1 else "")


def _mtime(rel: str) -> NgayHienThi | None:
    f = NGUON / rel
    try:
        return NgayHienThi(
            dt.date.fromtimestamp(f.stat().st_mtime), "mtime", f"{f.stat().st_mtime:.0f}"
        )
    except OSError:
        return None


BAO_CAO_77 = (
    Path.home() / "ocr-lab" / "web" / "bao-cao" / "data.json"
)


def doi_chieu_bao_cao(ban_ghi: list[dict]) -> dict:
    """Ghim 77 dòng hai nguồn của báo cáo vào sổ để đếm được bằng máy.

    Tiêu chí bàn giao nói "cả 77 tệp hai nguồn đều đã gán nhãn hoặc đánh
    dấu chờ nhãn — không tệp nào bị bỏ lặng". Câu ấy chỉ kiểm được nếu
    biết 77 tệp đó là những tệp nào, nên ở đây đọc thẳng danh sách từ
    báo cáo cũ và soi từng dòng vào sổ mới. Báo cáo nằm ngoài worktree và
    có thể vắng mặt; vắng thì nói vắng, không đoán.
    """
    if not BAO_CAO_77.exists():
        return {"co_bao_cao": False, "duong_dan": str(BAO_CAO_77)}
    dong = json.loads(BAO_CAO_77.read_text(encoding="utf-8")).get("lech_ngay", [])
    theo_ten: dict[str, dict] = {}
    for b in ban_ghi:
        theo_ten.setdefault(b["ten_tep"], b)
    thieu, im_lang, trang_thai = [], [], {}
    for r in dong:
        b = theo_ten.get(r["file"])
        if b is None:
            thieu.append(r["file"])
            continue
        nvb = b["ngay_van_ban"]
        t = nvb["trang_thai"] if nvb else "khong_doc_duoc_ngay"
        trang_thai[t] = trang_thai.get(t, 0) + 1
        # "bỏ lặng" = không nhãn mà cũng không được đánh dấu là đang chờ
        if nvb and not nvb["loai"] and t not in ("cho_nhan", "khong_phai_cua_ho_so",
                                                 "sai_can_sua"):
            im_lang.append(r["file"])
        if nvb is None:
            im_lang.append(r["file"])
    return {
        "co_bao_cao": True,
        "duong_dan": str(BAO_CAO_77),
        "dong_bao_cao": len(dong),
        "ten_tep_rieng": len({r["file"] for r in dong}),
        "khop_duoc_trong_so": len(dong) - len(thieu),
        "khong_thay_trong_so": sorted(set(thieu)),
        "bo_lang": sorted(set(im_lang)),
        "theo_trang_thai": dict(sorted(trang_thai.items())),
    }


def dung_so() -> dict:
    phan_xet = giai_thich_lech()
    ban_ghi = []
    kenh = nap_so_kenh()
    for ma, rel, md in _nap_kho():
        if not rel:
            continue
        ten = Path(rel).name
        tep_ten = ngay_tu_ten_tep(ten)
        hk = kenh.get(ma)
        if hk:
            md = _doc_ban(ma, hk["ban_parse"]) or md
        uv, tong_ngay = doc_ngay_van_ban(md, ten)
        if uv and _mo_ho_o_xlsx(uv, rel):
            uv.mo_ho = True
        co_nhan = thanh_ngay_co_nhan(uv) if uv else None
        dia = _mtime(rel)

        if co_nhan is not None:
            vb: dict | None = {
                "gia_tri": co_nhan.gia_tri.isoformat(),
                "loai": co_nhan.loai,
                "chu_the": "chinh_tai_lieu",
                "trang_thai": "da_gan_nhan",
                "dung_de": "tinh_han",
                "trich_dan": co_nhan.trich_dan,
                "dong": co_nhan.dong,
                "manh_mo": co_nhan.manh_mo,
                "mo_ho_thu_tu": co_nhan.mo_ho_thu_tu,
            }
        elif uv is not None:
            vb = {
                "gia_tri": uv.ngay.isoformat(),
                "loai": uv.loai,
                "chu_the": uv.chu_the,
                # Hai lý do khác nhau, ghi khác nhau: một bên là chưa biết
                # ngày ấy là ngày gì, một bên là biết rõ nó là ngày của
                # người khác. Cả hai đều không tính được hạn.
                "trang_thai": "cho_nhan" if not uv.loai else "khong_phai_cua_ho_so",
                "dung_de": "hien_thi",
                "trich_dan": uv.trich,
                "dong": uv.dong_so,
                "manh_mo": uv.manh_mo,
                "mo_ho_thu_tu": uv.mo_ho,
            }
        else:
            vb = None

        ht = None
        if hk:
            ht = {"kenh_id": hk["kenh_id"], **thoi_gian_hoi_thoai(md, tep_ten, hk["moc_kenh"])}
        if vb is not None:
            tren_phan_cach = ht and any(
                x["dong"] == vb["dong"] and x["nguon"] == "dong_ho_chat" for x in ht["ngay"]
            )
            vb["nguon"] = "dong_ho_chat" if tren_phan_cach else "trong_loi"

        bg: dict = {
            "ma": ma,
            "ma_kiem": doc_id_for(rel),
            "duong_dan": rel,
            "ten_tep": ten,
            "ho_so": _ho_so(rel),
            "ngay_luu_tep": (
                {
                    "gia_tri": tep_ten.gia_tri.isoformat(),
                    "nguyen_van": tep_ten.nguyen_van,
                    "dung_de": "hien_thi",
                    "nguon": tep_ten.nguon,
                }
                if tep_ten
                else None
            ),
            "ngay_van_ban": vb,
            "ngay_sua_dia": (
                {"gia_tri": dia.gia_tri.isoformat(), "dung_de": "hien_thi", "nguon": dia.nguon}
                if dia
                else None
            ),
            "so_ngay_thay_trong_noi_dung": tong_ngay,
            "thu_tu_ngay_da_chon": thu_tu_ngay(md),
            "hoi_thoai": ht,
        }

        if tep_ten and vb:
            bg["ca_hai_nguon"] = True
            lech = (dt.date.fromisoformat(vb["gia_tri"]) - tep_ten.gia_tri).days
            bg["lech_ngay"] = lech
            bg["lech_qua_nguong"] = abs(lech) > NGUONG_LECH
            gt = phan_xet.get(ten)
            if abs(lech) > NGUONG_LECH:
                if gt:
                    bg["phan_xet"] = {
                        "hop_le": gt["hop_le"],
                        "giai_thich": gt["giai_thich"],
                        "chu_the": gt.get("chu_the", "chinh_tai_lieu"),
                    }
                    if gt["hop_le"] is False:
                        # đọc tay kết luận ngày trong nội dung SAI. Một ngày
                        # sai mà vẫn tính được hạn thì tệ hơn không có ngày.
                        bg["ngay_van_ban"]["dung_de"] = "hien_thi"
                        bg["ngay_van_ban"]["trang_thai"] = "sai_can_sua"
                    elif gt.get("chu_the") != "chinh_tai_lieu":
                        # đọc tay đã kết luận ngày ấy không phải của hồ sơ:
                        # hạ xuống hiển thị dù bộ đọc có gán nhãn hay không
                        bg["ngay_van_ban"]["dung_de"] = "hien_thi"
                        bg["ngay_van_ban"]["trang_thai"] = "khong_phai_cua_ho_so"
                else:
                    bg["phan_xet"] = {
                        "hop_le": None,
                        "giai_thich": "chưa đọc tay — cần người xem",
                        "chu_the": "chua_ro",
                    }
        else:
            bg["ca_hai_nguon"] = False
        ban_ghi.append(bg)

    ban_ghi.sort(key=lambda b: b["duong_dan"])
    ca_hai = [b for b in ban_ghi if b["ca_hai_nguon"]]
    qua = [b for b in ca_hai if b["lech_qua_nguong"]]
    cho_nhan = [
        b for b in ban_ghi
        if b["ngay_van_ban"] and b["ngay_van_ban"]["trang_thai"] == "cho_nhan"
    ]
    chat = [b["hoi_thoai"] for b in ban_ghi if b["hoi_thoai"]]
    moi_ngay = [
        n for b in ban_ghi
        for n in (b["ngay_luu_tep"], b["ngay_van_ban"], b["ngay_sua_dia"],
                  *(b["hoi_thoai"]["ngay"] if b["hoi_thoai"] else ()))
        if n
    ]
    return {
        "phien_ban": 2,
        "tao_luc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "nguon": {"kho": str(KHO), "goc": str(NGUON), "kenh": str(KENH)},
        "luat": {
            "nguong_lech_ngay": NGUONG_LECH,
            "loai_hop_le": list(LOAI_HOP_LE),
            "nguon_ngay": list(NGUON_NGAY),
            "cung": (
                "Chỉ ngày trong `ngay_van_ban` có `loai` khác null mới được "
                "đem tính hạn. `ngay_luu_tep` và `ngay_sua_dia` là ngày hiển "
                "thị: mọi đường tính hạn nhận chúng đều ném NgayKhongDuocTinh."
            ),
            "hoi_thoai": (
                "Giờ (`d.dd`/`dd.dd`, dấu `.` hay `:`, ≤ 23:59, không cụm số thứ "
                "ba) không phải ngày: nằm ở `hoi_thoai.gio`, không bao giờ ở "
                "`hoi_thoai.ngay`. Ngày thiếu năm lấy năm của mốc — ngày tên tệp, "
                "không có thì ngày tên tệp muộn nhất của kênh; ngày trong lời thì "
                "dòng phân cách có ngày gần nhất phía trên — rơi sau mốc thì lùi "
                "một năm và mang `suy_nam.lui_nam`. Mọi ngày trong `hoi_thoai` "
                "chỉ để hiển thị. `trong_loi` là ngày viết trong nội dung — tin "
                "nhắn chat hoặc thân văn bản."
            ),
        },
        "tong_ket": {
            "tai_lieu": len(ban_ghi),
            "co_ngay_ten_tep": sum(1 for b in ban_ghi if b["ngay_luu_tep"]),
            "co_ngay_van_ban": sum(1 for b in ban_ghi if b["ngay_van_ban"]),
            "co_ngay_sua_dia": sum(1 for b in ban_ghi if b["ngay_sua_dia"]),
            "ca_hai_nguon": len(ca_hai),
            "khop_trong_nguong": len(ca_hai) - len(qua),
            "lech_qua_nguong": len(qua),
            "lech_qua_nguong_theo_ten_tep": len({b["ten_tep"] for b in qua}),
            "da_gan_nhan": sum(
                1 for b in ban_ghi
                if b["ngay_van_ban"] and b["ngay_van_ban"]["loai"]
            ),
            "cho_nhan": len(cho_nhan),
            "ca_hai_nguon_cho_nhan": sum(
                1 for b in ca_hai if b["ngay_van_ban"]["trang_thai"] == "cho_nhan"
            ),
            "khong_phai_cua_ho_so": sum(
                1 for b in ban_ghi
                if b["ngay_van_ban"]
                and b["ngay_van_ban"]["trang_thai"] == "khong_phai_cua_ho_so"
            ),
            "tinh_han_duoc": sum(
                1 for b in ban_ghi
                if b["ngay_van_ban"] and b["ngay_van_ban"]["dung_de"] == "tinh_han"
            ),
            "chua_phan_xet": sum(1 for b in qua if b["phan_xet"]["hop_le"] is None),
            # key trong giai_thich_lech.json không ứng với tệp lệch quá ngưỡng
            # nào: hoặc gõ sai tên, hoặc tệp đã đổi tên. Đếm ra để nó
            # không nằm im trong bảng giả vờ là một phán xét.
            "phan_xet_khong_dung_vao_dau": sorted(
                set(phan_xet) - {b["ten_tep"] for b in qua}
            ),
            "ngay_thieu_nguon": sum(1 for n in moi_ngay if n.get("nguon") not in NGUON_NGAY),
            "hoi_thoai": {
                "tep": len(chat),
                "kenh": len({h["kenh_id"] for h in chat}),
                "ngay_theo_nguon": {
                    n: sum(h["dem"]["ngay_theo_nguon"][n] for h in chat)
                    for n in NGUON_NGAY[:3]
                },
                **{k: sum(h["dem"][k] for h in chat)
                   for k in ("ngay_co_gia_tri", "tuong_doi", "suy_nam", "lui_nam", "gio")},
            },
        },
        "doi_chieu_bao_cao_77": doi_chieu_bao_cao(ban_ghi),
        "tai_lieu": ban_ghi,
    }


# ───────────────────────── tự kiểm ─────────────────────────


def kiem_tra() -> int:
    """Kiểm chính cái luật cứng, không kiểm quanh nó."""
    loi = []

    def dung(dieu: str, ok: bool) -> None:
        print(("  ok   " if ok else "  HỎNG ") + dieu)
        if not ok:
            loi.append(dieu)

    print("luật cứng: ngày không nhãn không tính được hạn")
    tep = NgayHienThi(dt.date(2025, 9, 26), "ten_tep", "260925")
    try:
        han_tra_loi(tep, 30)  # type: ignore[arg-type]
        dung("han_tra_loi() từ chối ngày tên tệp", False)
    except NgayKhongDuocTinh:
        dung("han_tra_loi() từ chối ngày tên tệp", True)
    try:
        tep + dt.timedelta(days=30)  # type: ignore[operator]
        dung("NgayHienThi không cộng được", False)
    except NgayKhongDuocTinh:
        dung("NgayHienThi không cộng được", True)
    try:
        tep.cho_phep_tinh()
        dung("NgayHienThi không mở khoá tính được", False)
    except NgayKhongDuocTinh:
        dung("NgayHienThi không mở khoá tính được", True)

    nop = NgayCoNhan(dt.date(2025, 9, 24), "nop", "Filing date: September 24, 2025", 5, "filing date")
    dung("ngày có nhãn tính được hạn 6 tháng",
         han_tra_loi(nop, 183) == dt.date(2026, 3, 26))
    try:
        NgayCoNhan(dt.date(2025, 9, 24), "luu_tep", "", 1, "")
        dung("nhãn ngoài tập đóng bị chặn", False)
    except ValueError:
        dung("nhãn ngoài tập đóng bị chặn", True)

    print("đọc ngày")
    dung("tên tệp 260925 → 2025-09-26",
         str(ngay_tu_ten_tep("NH9001.US_Filing Receipt_260925.pdf")) == "2025-09-26")
    dung("số đề nghị thanh toán V2025-903 không bị đọc thành ngày",
         str(ngay_tu_ten_tep("TV9013_De nghi thanh toan V2025-903_080825.xlsx")) == "2025-08-08")
    dung("hoá đơn yyyy-mm-dd đầu tên",
         str(ngay_tu_ten_tep("2025-09-11 ACME - Refiny - Invoice 9001.pdf")) == "2025-09-11")
    dung("tên không có ngày → None", ngay_tu_ten_tep("Goods.docx") is None)

    def nhan(md, ten=""):
        uv, _ = doc_ngay_van_ban(md, ten)
        return thanh_ngay_co_nhan(uv) if uv else None, uv

    d, _ = nhan("Serial number: 91234567\nFiling date: September 24, 2025 at 3:01 PM ET\n")
    dung("biên nhận nộp đơn → nop 2025-09-24",
         d is not None and d.loai == "nop" and str(d) == "2025-09-24")
    d, _ = nhan("Amazon Brand Registry\n\nHanoi, May 19, 2025\nOur ref.: NH9002.US\n")
    dung("thư kháng → ky 2025-05-19",
         d is not None and d.loai == "ky" and str(d) == "2025-05-19")
    _, uv = nhan(
        "Ngày, tháng, năm sinh /Date of birth:\n15/03/1990\n"
        "Ngày cấp Căn cước công dân gần nhất: 12/07/2021\n"
    )
    dung("căn cước → cap 2021-07-12 của BÊN KÝ, không lấy ngày sinh, "
         "không tính hạn hồ sơ",
         uv is not None and uv.loai == "cap" and str(uv.ngay) == "2021-07-12"
         and uv.chu_the == "ben_ky" and thanh_ngay_co_nhan(uv) is None)
    _, uv = nhan("Số định danh cá nhân: 030099000002\nNgày cấp: 12/07/2021\n")
    dung("số định danh bị che trong trích dẫn",
         uv is not None and "030099000002" not in uv.trich)
    d, uv = nhan("Bảng kê ngày 03/09/2025 gửi kèm\n")
    dung("ngày không cụm nhãn → không tính hạn được, vẫn vào sổ",
         d is None and uv is not None and uv.loai is None)

    _, uv = nhan("Payment Due On: 11/07/2025\nThank you for your business.\n")
    dung("hoá đơn tiếng Anh → 11/07 đọc là 7 tháng 11",
         uv is not None and str(uv.ngay) == "2025-11-07" and uv.loai == "het_han"
         and uv.mo_ho)
    _, uv = nhan("Kính gửi CÔNG TY TNHH ZORBLAX\nNgày đề nghị thanh toán: 11/07/2025\n")
    dung("chứng từ tiếng Việt → 11/07 đọc là 11 tháng 7",
         uv is not None and str(uv.ngay) == "2025-07-11" and uv.loai == "ky")
    _, uv = nhan("12/3/25, 9:28 AM\nStatus Form\nIssue date: March 20, 2025\n")
    dung("đầu trang in của trình duyệt không thành ngày văn bản",
         uv is not None and str(uv.ngay) == "2025-03-20")
    dung("tên tệp yyyymmdd đọc trước giờ xuất tệp",
         str(ngay_tu_ten_tep("BQ093.US_1-149_Application_20250708_230511.pdf"))
         == "2025-07-08")
    _, uv = nhan("Ngày, tháng, năm sinh /Date of birth:\n15/03/1990\nNgày cấp: 12/07/2021\n")
    dung("ngày sinh ở dòng dưới nhãn vẫn bị chặn",
         uv is not None and str(uv.ngay) == "2021-07-12")

    print("ngày của ai")
    hd = ('HỢP ĐỒNG DỊCH VỤ PHÁP LÝ\nSố: NH9001/2025/HD-SHTT\n\n'
          'Vào ngày 19 tháng 9 năm 2025 (“**Ngày Ký**”), tại trụ sở CÔNG TY LUẬT\n'
          'BÊN A: Ông Nguyễn Văn A\nCăn cước công dân số: 001099000001 do Cục Cảnh sát\n'
          'xã hội cấp ngày 03/03/2020\n')
    d, _ = nhan(hd)
    dung("hợp đồng → ngày ký 2025-09-19, không phải ngày cấp căn cước",
         d is not None and d.loai == "ky" and str(d) == "2025-09-19")
    pl = ('PHỤ LỤC HỢP ĐỒNG\n'
          'Căn cứ vào Hợp đồng dịch vụ tư vấn pháp lý số 902/2024/HĐ-SHTT,\n'
          'ký ngày 20/11/2024 giữa CÔNG TY A và CÔNG TY LUẬT REFINY (gọi là\n'
          '"Hợp đồng"), Phụ lục số PL01/NH9002.US/2025 này (sau đây gọi là "Phụ\n'
          'lục") được các bên thống nhất ký ngày 28 tháng 08 năm 2025 (sau đây gọi là "Ngày có\n'
          'hiệu lực"), giữa và bởi:\n')
    d, _ = nhan(pl)
    dung("phụ lục → ngày ký phụ lục 2025-08-28, không phải ngày hợp đồng gốc",
         d is not None and str(d) == "2025-08-28")
    _, uv = nhan("Application Filing Date: Apr. 28, 2021\n",
                 "Tong hop doi chung_010125.pdf")
    dung("ngày trong bảng đối chứng là của bên thứ ba, không tính hạn",
         uv is not None and uv.chu_the == "ben_thu_ba"
         and thanh_ngay_co_nhan(uv) is None)

    print("ba tầng thời gian trong hội thoại")
    ht = thoi_gian_hoi_thoai(
        "T4 01/10/2025\nchị gửi giúp em trước 30/9 nhé\n13.43\n",
        NgayHienThi(dt.date(2025, 10, 8), "ten_tep", "ddmmyy"), None,
    )
    dung("giờ 13.43 vào danh sách giờ, không thành ngày",
         [g["gia_tri"] for g in ht["gio"]] == ["13:43"]
         and all(n["dong"] != 3 for n in ht["ngay"]))
    dung("ngày thiếu năm 30/9 lấy năm của tin liền trước",
         any(n["gia_tri"] == "2025-09-30" and n["nguon"] == "trong_loi"
             and not n["suy_nam"]["lui_nam"] for n in ht["ngay"]))
    dung("mỗi ngày một nhãn nguồn",
         [n["nguon"] for n in ht["ngay"]] == ["ten_tep", "dong_ho_chat", "trong_loi"])

    print(f"\n{len(loi)} hỏng" if loi else "\nkhông có gì hỏng")
    return 1 if loi else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kiem-tra", action="store_true", help="tự kiểm luật cứng rồi thoát")
    ap.add_argument("--ra", type=Path, default=SO, help=f"nơi ghi sổ (mặc định {SO})")
    a = ap.parse_args()
    if a.kiem_tra:
        return kiem_tra()

    so = dung_so()
    a.ra.parent.mkdir(parents=True, exist_ok=True)
    a.ra.write_text(json.dumps(so, ensure_ascii=False, indent=1), encoding="utf-8")
    t = so["tong_ket"]
    print(f"{a.ra}")
    for k, v in t.items():
        print(f"  {k:32} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
