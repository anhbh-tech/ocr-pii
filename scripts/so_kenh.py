"""Sổ kênh hội thoại: gom các ảnh chụp đoạn chat trong kho thành từng kênh.

Tên tệp không nói tệp nào là ảnh chụp chat (AGENTS.md). Nội dung thì nói:
một ảnh chụp nhóm chat luôn in dòng tiêu đề nhóm `<đối tác> x REFINY` và
ngay dưới là dòng `N thành viên`. Bộ nhận diện đòi CẢ HAI dấu hiệu trong
CÙNG một bản parse — riêng dòng "thành viên" thì giấy đăng ký doanh nghiệp
nào cũng có ("Danh sách thành viên góp vốn", "công ty TNHH hai thành viên").

Một kênh là một thực thể riêng, không phải thuộc tính của hồ sơ: cùng một
nhóm chat có thể nói về nhiều hồ sơ, và một tệp chụp có thể được lưu y hệt
vào hai hồ sơ. Nên mỗi kênh trỏ tới danh sách hồ sơ (`thuoc_ho_so`, n–n) và
mỗi tin trỏ tới `doc_id` sẵn có trong `~/.private/ade_out`; hai tệp cùng nội
dung gộp làm một tin, giữ cả hai `doc_id`.

Người nói suy từ GIỌNG, không từ tên: người xưng "em"/"bên em" và gọi
"anh/chị" là Refiny; người gọi "em ơi", nhờ "giúp chị" là khách. Không đủ
dấu hiệu thì để trống, không đoán. Người nhận lấy từ tiêu đề kênh, không từ
chỗ `@` — OCR hay nuốt mất tên sau `@`.

Ba lớp thời gian, không lớp nào thay lớp nào:
  1. ngày trong tên tệp (`ddmmyy`) — ngày lưu, chỉ để sắp xếp (`so_ngay.py`);
  2. giờ chat `hh:mm`/`hh.mm` cuối mỗi cụm tin;
  3. dải phân cách của ứng dụng (`T4 01/10/2025`, `Hôm qua`); ngày thiếu năm
     lấy năm của tệp (tên tệp không có ngày thì lấy ngày tệp muộn nhất của
     kênh), rơi vào tương lai so với mốc ấy thì lùi một năm.

Đầu ra nằm ngoài cây git vì chứa nguyên văn lời khách:
  ~/.private/so/kenh/hoi_thoai/<kenh_id>.json   một tệp một kênh
  ~/.private/so/nhan_dien_kenh.json             ai trúng, ai chỉ có một dấu hiệu

`~/.private/so/kenh/` là nhà chung của sổ kênh; tệp `*.json` ngay trong đó
thuộc sổ danh tính, và sổ ấy dọn mọi `*.json` lạ ở cấp đó. Nên sổ này ghi
vào thư mục con riêng và chỉ dọn tệp do chính nó sinh.

Khoá kênh là `ocr_lab.danh_tinh.kenh_id` — một hàm cho cả hai sổ, nên cùng
một tiêu đề ra cùng một `kenh_id` ở đây và trong sổ danh tính. Đừng chép
lại luật chuẩn hoá ở đây.

    python scripts/so_kenh.py            # dựng và ghi
    python scripts/so_kenh.py --dry-run  # chỉ in số đếm
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from ocr_lab.ade_store import DEFAULT_STORE  # noqa: E402
from ocr_lab.danh_tinh import kenh_id  # noqa: E402
from so_ban_sach import MA_HO_SO, chuan_ma  # noqa: E402
from so_ngay import _bo_dau, ngay_tu_ten_tep  # noqa: E402

DICH = Path.home() / ".private" / "so" / "kenh" / "hoi_thoai"
SO_NHAN_DIEN = Path.home() / ".private" / "so" / "nhan_dien_kenh.json"

TEN_HANG = "refiny"
NGUON_SINH = "scripts/so_kenh.py"
PARSE = (("parse_pro", "parse_pro.json"), ("parse", "parse.json"))


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


# ───────────────────────── bộ nhận diện ─────────────────────────

# `Mr. A x Refiny`, `Mr. B x REFINY - Review`, `C/ D x Refiny | Nhãn hiệu`.
# Tên hãng so theo chữ cái chứ không theo chính tả: OCR đã trả `Renify`.
DONG_TIEU_DE = re.compile(
    r"^\W{0,4}(?P<doi_tac>\w.{0,59}?)\s+[x×]\s+(?P<hang>[a-z]{6})"
    r"(?P<duoi>\s*[-–|:]\s*\w.{0,39}?)?\W{0,6}$",
    re.IGNORECASE,
)
# Ô soạn tin nhắc lại tên kênh: `Nhập @, tin nhắn tới <tên kênh>`.
O_SOAN = re.compile(r"^\W*(?:nhập\b|message\b|@,)|tin nhắn tới", re.IGNORECASE)
# `👤 4 thành viên | 🔲`, `7 members`. Phải có CHỮ SỐ và dòng phải ngắn:
# "HAI THÀNH VIÊN", "Danh sách thành viên góp vốn" đều không phải dòng này.
DONG_THANH_VIEN = re.compile(
    r"^\W{0,4}(?P<so>\d{1,3})\s*(?:thành viên|thanh vien|members?)\b\W{0,20}$",
    re.IGNORECASE,
)


def _la_hang(tu: str) -> bool:
    return sorted(tu.lower()) == sorted(TEN_HANG)


def tieu_de_trong(md: str) -> list[tuple[str, str]]:
    """Các dòng tiêu đề kênh: [(tiêu đề chuẩn `A × REFINY`, đối tác)]."""
    ra = []
    for dong in md.splitlines():
        dong = _nfc(dong).strip()
        if not dong or O_SOAN.search(dong) or dong.startswith("@"):
            continue
        m = DONG_TIEU_DE.match(dong)
        if m and _la_hang(m["hang"]):
            doi_tac = m["doi_tac"].strip()
            duoi = re.sub(r"\s*([-–|:])\s*", r" \1 ", m["duoi"] or "", count=1).rstrip()
            ra.append((f"{doi_tac} × REFINY{duoi}", doi_tac))
    return ra


def thanh_vien_trong(md: str) -> list[int]:
    return [
        int(m["so"])
        for dong in md.splitlines()
        if (m := DONG_THANH_VIEN.match(_nfc(dong).strip()))
    ]


@dataclass
class TaiLieu:
    doc_id: str
    duong_dan: str
    parse: dict[str, str]  # tên bản parse → markdown

    @property
    def ho_so_thu_muc(self) -> str:
        phan = Path(self.duong_dan).parts
        return phan[2] if len(phan) > 3 else ""

    @property
    def ho_so(self) -> str:
        """Mã hồ sơ từ thư mục cấp 3: `902. US. …` → `902.US`."""
        m = MA_HO_SO.match(self.ho_so_thu_muc)
        return chuan_ma(m.group(1)) if m else self.ho_so_thu_muc


@dataclass
class KetQua:
    tai_lieu: TaiLieu
    ban: str | None  # bản parse có đủ hai dấu hiệu
    tieu_de: list[tuple[str, str]] = field(default_factory=list)
    thanh_vien: list[int] = field(default_factory=list)
    co_tieu_de: bool = False
    co_thanh_vien: bool = False

    @property
    def trung(self) -> bool:
        return self.ban is not None


def nhan_dien(tl: TaiLieu) -> KetQua:
    """Trúng khi MỘT bản parse có cả dòng tiêu đề lẫn dòng thành viên.

    Đọc bản Pro trước. Dấu hiệu nằm rải ở hai bản khác nhau thì không tính:
    mỗi bản là một lần đọc cùng một ảnh, và ảnh chụp chat thật thì một lần
    đọc thấy cả hai dòng nằm cạnh nhau.
    """
    kq = KetQua(tl, None)
    for ban, _ in PARSE:
        md = tl.parse.get(ban) or ""
        td, tv = tieu_de_trong(md), thanh_vien_trong(md)
        kq.co_tieu_de |= bool(td)
        kq.co_thanh_vien |= bool(tv)
        if td and tv and kq.ban is None:
            kq.ban, kq.tieu_de, kq.thanh_vien = ban, td, tv
    return kq


# ───────────────────────── hình: giao diện hay chứng cứ ─────────────────────────

# `[PROFILE_PICTURE]`, `[LIKE_ICON]`: nhãn viết hoa ADE gắn cho chi tiết giao diện.
NHAN_GIAO_DIEN = re.compile(r"^[A-Z_ ]+$")
MO_TA_GIAO_DIEN = re.compile(
    r"profile|avatar|\bicons?\b|emoji|toolbar|button|reaction|camera|magnif|"
    r"\blike\b|heart|layout|add people",
    re.IGNORECASE,
)
HINH = re.compile(r"<figure(?P<thuoc_tinh>[^>]*)>(?P<than>.*?)</figure>", re.S)
MO_TA = re.compile(r"<description>(.*?)</description>", re.S)
O_BANG = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
HANG_BANG = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)


def phan_loai_hinh(mo_ta: str, co_bang: bool = False) -> bool:
    """True = chi tiết giao diện, bỏ đi. Bảng số liệu luôn là chứng cứ."""
    if co_bang:
        return False
    return bool(NHAN_GIAO_DIEN.match(mo_ta) or MO_TA_GIAO_DIEN.search(mo_ta))


def _tach_hinh(md: str, hinh: list[dict]) -> str:
    """Thay mỗi `<figure>` bằng phần chứng cứ của nó, ghi hình vào `hinh`.

    ADE Pro có khi bọc cả một màn chat trong một `<figure type="CHART">`:
    lời tả bằng tiếng Anh là của máy, bảng bên trong mới là của người gửi.
    """

    def thay(m: re.Match[str]) -> str:
        than = m["than"]
        kieu = re.search(r'type="([^"]+)"', m["thuoc_tinh"])
        mt = MO_TA.search(than)
        mo_ta = re.sub(r"\s+", " ", mt.group(1) if mt else re.sub(r"<[^>]+>", " ", than)).strip()
        hang = [
            " | ".join(re.sub(r"<[^>]+>", " ", o).strip() for o in O_BANG.findall(h))
            for h in HANG_BANG.findall(than)
        ]
        giao_dien = phan_loai_hinh(mo_ta, bool(hang))
        hinh.append(
            {"kieu": kieu.group(1) if kieu else "figure", "giao_dien": giao_dien}
            | ({} if giao_dien else {"mo_ta": mo_ta[:300]})
        )
        return "" if giao_dien else "\n" + "\n".join(hang) + "\n"

    return HINH.sub(thay, md)


# ───────────────────────── cắt cụm tin ─────────────────────────

GIO = re.compile(r"^(\d{1,2})[:.](\d{2})$")
TUONG_DOI = {"hôm nay": "hom_nay", "hôm qua": "hom_qua", "today": "hom_nay", "yesterday": "hom_qua"}
PHAN_CACH = re.compile(
    r"^(?:(?P<gio>\d{1,2}[:.]\d{2})\s+)?"
    r"(?:(?P<tuong_doi>hôm nay|hôm qua|today|yesterday)"
    r"|(?:(?:t[2-7]|cn|thứ\s+\w+)\s+)?(?P<d>\d{1,2})/(?P<m>\d{1,2})(?:/(?P<y>\d{4}))?)"
    r"(?:\s+(?P<gio2>\d{1,2}[:.]\d{2}))?$",
    re.IGNORECASE,
)
TRANG_THAI = re.compile(r"^(?:đã nhận|đã xem|đã gửi|seen|received|sent)$", re.IGNORECASE)
AT_MAT_TEN = re.compile(r"@(?=[\s,.:;!?]|$)")


def doc_gio(s: str) -> str | None:
    """`13.43` → `13:43`. Hai cụm số, ≤ 23.59, không có cụm thứ ba: là giờ.

    `8.10.2025` có cụm thứ ba nên là ngày; `24.10` quá 23 giờ nên không phải.
    """
    m = GIO.match(s.strip())
    if not m:
        return None
    h, p = int(m[1]), int(m[2])
    return f"{h:02d}:{p:02d}" if h <= 23 and p <= 59 else None


def ngay_thieu_nam(ngay: int, thang: int, moc: dt.date) -> dt.date | None:
    """Ngày không ghi năm lấy năm của mốc; rơi sau mốc thì lùi một năm."""
    for nam in (moc.year, moc.year - 1):
        try:
            d = dt.date(nam, thang, ngay)
        except ValueError:
            continue
        if d <= moc:
            return d
    return None


def doc_phan_cach(dong: str, moc: dt.date | None) -> dict | None:
    m = PHAN_CACH.match(dong.strip())
    if not m:
        return None
    ra: dict = {"nguyen_van": dong.strip(), "ngay": None}
    gio = m["gio"] or m["gio2"]
    if gio:
        if not doc_gio(gio):
            return None
        ra["gio"] = doc_gio(gio)
    if m["tuong_doi"]:
        ra["tuong_doi"] = TUONG_DOI[m["tuong_doi"].lower()]
        return ra
    d, t = int(m["d"]), int(m["m"])
    if m["y"]:
        try:
            ra["ngay"] = dt.date(int(m["y"]), t, d).isoformat()
        except ValueError:
            return None
    elif moc:
        ngay = ngay_thieu_nam(d, t, moc)
        if ngay is None:
            return None
        ra["ngay"], ra["suy_nam"] = ngay.isoformat(), True
    elif not 1 <= t <= 12 or not 1 <= d <= 31:
        return None
    return ra


def _dong_sach(md: str, hinh: list[dict]) -> list[str]:
    """Bỏ khung ứng dụng, giữ lời người gửi và chứng cứ, mỗi phần tử một dòng."""
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    md = _tach_hinh(md, hinh)
    md = re.sub(r"<br\s*/?>", " ", md)
    md = re.sub(r"<[^>]+>", " ", md)
    ra = []
    for dong in md.splitlines():
        dong = _nfc(dong).strip()
        if not re.search(r"[^\W\d_]{2}|\d", dong) or re.fullmatch(r"\W*\d{1,2}\W*", dong):
            continue  # hàng biểu tượng, đếm lượt thả tim
        mg = re.fullmatch(r"\[([^\]]*)\]", dong)
        if mg:
            if phan_loai_hinh(mg[1]):
                hinh.append({"kieu": "nhan", "giao_dien": True})
                continue
            hinh.append({"kieu": "nhan", "giao_dien": False, "mo_ta": mg[1]})
        dong = re.sub(r"\s*\[[A-Z_ ]+\]\s*", " ", dong).strip()  # `11:32 [LIKE_ICON]`
        if (
            not dong
            or O_SOAN.search(dong)
            or TRANG_THAI.match(dong)
            or DONG_THANH_VIEN.match(dong)
            or tieu_de_trong(dong)
        ):
            continue
        ra.append(dong)
    return ra


def cat_doan(md: str, moc: dt.date | None) -> tuple[list[dict], list[dict]]:
    """Cắt bản parse thành các cụm tin. Trả (đoạn, hình).

    Mỗi cụm kết thúc ở dòng giờ đứng riêng — Zalo in giờ dưới cụm tin cuối
    của một người. Dòng phân cách ngày mở một mốc mới cho các cụm sau nó.
    """
    hinh: list[dict] = []
    dong = _dong_sach(md, hinh)
    doan: list[dict] = []
    dang: list[str] = []
    moc_hien: dict | None = None

    def chot(gio: str | None) -> None:
        if dang:
            doan.append({"gio": gio, "moc": moc_hien, "dong": list(dang)})
            dang.clear()

    i = 0
    while i < len(dong):
        d = dong[i]
        sau = dong[i + 1] if i + 1 < len(dong) else ""
        gio = doc_gio(d)
        # `16:25` rồi `Hôm qua` ở dòng dưới là MỘT dải phân cách bị ADE cắt đôi.
        if gio and sau.lower() in TUONG_DOI:
            chot(None)
            moc_hien = {"nguyen_van": f"{d} {sau}", "ngay": None, "gio": gio,
                        "tuong_doi": TUONG_DOI[sau.lower()]}
            i += 2
            continue
        if gio:
            chot(gio)
        elif (pc := doc_phan_cach(d, moc)) is not None:
            chot(None)
            moc_hien = pc
        else:
            dang.append(d)
        i += 1
    chot(None)
    return doan, hinh


# ───────────────────────── người nói ─────────────────────────
#
# Luật xưng hô: Refiny xưng "em", gọi khách "anh/chị"; khách xưng "chị/anh/
# mình", gọi người của Refiny "em/bạn". Mỗi dấu hiệu là một mẫu có tên để
# người đọc sổ thấy vì sao một cụm được gán cho bên nào.

_DAU = r"^(?:@\S+\s+)?"  # cụm tin hay mở bằng `@tên`

DAU_HIEU_REFINY: tuple[tuple[str, re.Pattern[str], bool], ...] = (
    # (tên, mẫu, so trên bản CÓ dấu?) — "dạ" bỏ dấu thì trùng "đã".
    ("ben_em", re.compile(r"\bben em\b"), False),
    ("mo_dau_da_vang", re.compile(_DAU + r"(?:d[aạ]|v[âà]ng)\b", re.M), True),
    ("em_tu_xung", re.compile(r"\bem (?:xin|nhan|gui|da|se|dang|cam on|bao|kiem tra|xac nhan|vua)\b"), False),
    ("nho_khach", re.compile(r"\b(?:giup|cho) em\b"), False),
    # "Anh Nam ơi", "Chị @ ơi", "Chị ơi". Sau `@tên` phải còn ít nhất một chữ
    # nữa trước "ơi": `@Kim Chi ơi` là khách gọi tên nhân viên, không phải gọi chị.
    ("goi_anh_chi", re.compile(
        r"^(?:(?:@\S+\s+)?(?:anh|chi|a|c)\s+(?:\S+\s+){1,3}?|(?:anh|chi|a|c)\s+)oi\b", re.M
    ), False),
    ("a_le_phep", re.compile(r"(?<!\w)ạ(?!\w)"), True),
)
DAU_HIEU_KHACH: tuple[tuple[str, re.Pattern[str], bool], ...] = (
    ("goi_em", re.compile(r"\b(?:em|e|ban|b) oi\b"), False),
    ("hoi_em_cuoi_cau", re.compile(r"\b(?:ko|khong|k|chua|nhi|nhe|nha|a|ha)\s+(?:e|em|b|ban)\s*[?.!]*$", re.M), False),
    ("dan_em", re.compile(r"(?<!ben )(?<!giup )(?<!cho )\b(?:e|em|b|ban)\s+(?:nhe|nha|nhi)\b"), False),
    ("goi_ban", re.compile(r"\b(?:cam on|nho|giup|chao) (?:ban|b)\b"), False),
    ("nho_giup_minh", re.compile(r"\bgiup (?:chi|anh|minh|toi|c|a)\b"), False),
    ("cho_minh", re.compile(r"\b(?:cho|de) minh (?:hoi|dien|gui|xem|biet)\b"), False),
    ("dap_cut", re.compile(_DAU + r"(?:uh|uhm|um|uk)\b", re.M), False),
)


def nguoi_noi(dong: list[str]) -> tuple[str | None, list[str]]:
    """(bên nói, các dấu hiệu). Một bên → bên đó; cả hai → bên gấp đôi bên
    kia, không thì để trống; không dấu hiệu nào → để trống."""
    co_dau = "\n".join(_nfc(d).lower() for d in dong)
    khong_dau = "\n".join(_bo_dau(d) for d in dong)
    thay = {"refiny": [], "khach": []}
    for ben, mau in (("refiny", DAU_HIEU_REFINY), ("khach", DAU_HIEU_KHACH)):
        for ten, rx, dung_co_dau in mau:
            if rx.search(co_dau if dung_co_dau else khong_dau):
                thay[ben].append(ten)
    r, k = len(thay["refiny"]), len(thay["khach"])
    dau_hieu = [f"refiny:{t}" for t in thay["refiny"]] + [f"khach:{t}" for t in thay["khach"]]
    if r and not k or r >= 2 * k > 0:
        return "refiny", dau_hieu
    if k and not r or k >= 2 * r > 0:
        return "khach", dau_hieu
    return None, dau_hieu


# ───────────────────────── dựng kênh ─────────────────────────


def _bam(dong_tin: list[str]) -> str:
    """Khoá nội dung để gộp bản trùng: hai tệp chụp y hệt → cùng khoá."""
    s = re.sub(r"\s+", " ", " ".join(dong_tin)).strip().lower()
    return hashlib.sha1(s.encode()).hexdigest()[:12]


def dung_tin(kq: KetQua, doi_tac: str, moc_kenh: dt.date | None = None) -> dict:
    tl = kq.tai_lieu
    ten = Path(tl.duong_dan).name
    ngay_tep = ngay_tu_ten_tep(ten)
    moc = ngay_tep.gia_tri if ngay_tep else moc_kenh
    doan, hinh = cat_doan(tl.parse[kq.ban], moc)
    ra_doan = []
    for i, d in enumerate(doan):
        ben, dau_hieu = nguoi_noi(d["dong"])
        nhan = None
        if ben == "refiny":
            nhan = {"vai": "khach", "ten": doi_tac, "nguon": "tieu_de_kenh"}
        elif ben == "khach":
            nhan = {"vai": "refiny", "ten": "REFINY", "nguon": "tieu_de_kenh"}
        noi_dung = "\n".join(d["dong"])
        ra_doan.append({
            "stt": i,
            "su_kien": "activity",
            "gio": d["gio"],
            "moc": d["moc"],
            "nguoi_noi": ben,
            "dau_hieu": dau_hieu,
            "nguoi_nhan": nhan,
            "at_mat_ten": len(AT_MAT_TEN.findall(noi_dung)),
            "noi_dung": noi_dung,
        })
    ngay_nd = sorted({d["moc"]["ngay"] for d in doan if d["moc"] and d["moc"].get("ngay")})
    dong_tin = [x for d in doan for x in d["dong"]]
    return {
        "tin_id": "t-" + _bam(dong_tin or [tl.doc_id]),
        "doc_id": tl.doc_id,
        "ho_so": [tl.ho_so],
        "tep": ten,
        "duong_dan": tl.duong_dan,
        "ban_parse": kq.ban,
        "ban_trung": [],
        "thoi_diem": (
            {"ngay": ngay_tep.gia_tri.isoformat(), "nguon": ngay_tep.nguon,
             "nguyen_van": ngay_tep.nguyen_van}
            if ngay_tep else None
        ),
        "ngay_trong_noi_dung": ngay_nd,
        "thanh_vien": sorted(set(kq.thanh_vien)),
        "hinh": hinh,
        "doan": ra_doan,
    }


def _khoa_thoi_gian(tin: dict) -> tuple:
    """Số trước chữ: ngày tệp, rồi ngày muộn nhất in trong màn chat, rồi đường dẫn."""
    ngay = tin["thoi_diem"]["ngay"] if tin["thoi_diem"] else "9999-12-31"
    nd = tin["ngay_trong_noi_dung"][-1] if tin["ngay_trong_noi_dung"] else ""
    return (ngay, nd, tin["duong_dan"])


def dung_kenh(ket_qua: list[KetQua], sinh_luc: str = "") -> dict[str, dict]:
    """Gom các tài liệu trúng thành kênh, gộp bản trùng, xếp tin theo thời gian."""
    nhom: dict[str, list[KetQua]] = {}
    for kq in ket_qua:
        if kq.trung:
            nhom.setdefault(kenh_id(kq.tieu_de[0][0]), []).append(kq)
    ra = {}
    for kid, cac_kq in sorted(nhom.items()):
        bien_the = Counter(td for kq in cac_kq for td, _ in kq.tieu_de[:1])
        tieu_de = bien_the.most_common(1)[0][0]
        doi_tac = next(dt_ for kq in cac_kq for td, dt_ in kq.tieu_de if td == tieu_de)
        ngay_cac_tep = [
            n.gia_tri for kq in cac_kq if (n := ngay_tu_ten_tep(Path(kq.tai_lieu.duong_dan).name))
        ]
        moc_kenh = max(ngay_cac_tep, default=None)
        theo_khoa: dict[str, dict] = {}
        for kq in sorted(cac_kq, key=lambda k: k.tai_lieu.duong_dan):
            tin = dung_tin(kq, doi_tac, moc_kenh)
            if tin["tin_id"] in theo_khoa:
                goc = theo_khoa[tin["tin_id"]]
                goc["ban_trung"].append(
                    {"doc_id": tin["doc_id"], "ho_so": tin["ho_so"][0], "duong_dan": tin["duong_dan"]}
                )
                if tin["ho_so"][0] not in goc["ho_so"]:
                    goc["ho_so"].append(tin["ho_so"][0])
            else:
                theo_khoa[tin["tin_id"]] = tin
        tin_list = sorted(theo_khoa.values(), key=_khoa_thoi_gian)
        cac_tv = sorted({n for kq in cac_kq for n in kq.thanh_vien})
        tv_moi_nhat = tin_list[-1]["thanh_vien"][-1] if tin_list[-1]["thanh_vien"] else None
        xung_dot = []
        if len(cac_tv) > 1:
            xung_dot.append({"loai": "thanh_vien", "gia_tri": cac_tv})
        if len({_bo_dau(t) for t in bien_the}) > 1:
            xung_dot.append({"loai": "tieu_de", "gia_tri": sorted(bien_the)})
        theo_khong_dau: dict[str, set[str]] = {}
        for t in bien_the:
            theo_khong_dau.setdefault(_bo_dau(t), set()).add(_nfc(t).lower())
        khac_dau = sorted(t for t in bien_the if len(theo_khong_dau[_bo_dau(t)]) > 1)
        if khac_dau:
            xung_dot.append({"loai": "tieu_de_dau", "gia_tri": khac_dau})
        thu_muc = {kq.tai_lieu.ho_so: kq.tai_lieu.ho_so_thu_muc for kq in cac_kq}
        doan = [d for t in tin_list for d in t["doan"]]
        ra[kid] = {
            "kenh_id": kid,
            "tieu_de": tieu_de,
            "tieu_de_bien_the": dict(bien_the.most_common()),
            "doi_tac": doi_tac,
            "thanh_vien": {"so": tv_moi_nhat, "cac_gia_tri": cac_tv, "nhat_quan": len(cac_tv) == 1},
            "thuoc_ho_so": sorted(thu_muc),
            "ho_so_thu_muc": dict(sorted(thu_muc.items())),
            "so_tin": {"truoc_gop": len(cac_kq), "sau_gop": len(tin_list)},
            "so_doan": {
                "tong": len(doan),
                "refiny": sum(d["nguoi_noi"] == "refiny" for d in doan),
                "khach": sum(d["nguoi_noi"] == "khach" for d in doan),
                "chua_ro": sum(d["nguoi_noi"] is None for d in doan),
            },
            "at_mat_ten": sum(d["at_mat_ten"] for d in doan),
            "xung_dot": xung_dot,
            "tin": tin_list,
            "nguon_sinh": NGUON_SINH,
            "sinh_luc": sinh_luc,
        }
    return ra


# ───────────────────────── đọc kho, ghi sổ ─────────────────────────


def nap_kho(kho: Path) -> list[TaiLieu]:
    ra = []
    for thu_muc in sorted(p for p in kho.iterdir() if p.is_dir()):
        meta = next(
            (json.loads(f.read_text()) for f in (thu_muc / "meta_pro.json", thu_muc / "meta.json")
             if f.exists()),
            None,
        )
        if meta is None:
            continue
        parse = {}
        for ban, ten in PARSE:
            f = thu_muc / ten
            if f.exists():
                try:
                    parse[ban] = json.loads(f.read_text()).get("markdown") or ""
                except (json.JSONDecodeError, OSError):
                    pass
        if parse:
            ra.append(TaiLieu(thu_muc.name, _nfc(meta.get("source", "")), parse))
    return ra


def _ghi(f: Path, du_lieu: dict) -> None:
    f.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    f.write_text(json.dumps(du_lieu, ensure_ascii=False, indent=2) + "\n")


def _cua_so_nay(f: Path) -> bool:
    try:
        return json.loads(f.read_text()).get("nguon_sinh") == NGUON_SINH
    except (json.JSONDecodeError, OSError, AttributeError):
        return False


def ghi_so(kenh: dict[str, dict], ket_qua: list[KetQua], dich: Path, so: Path, sinh_luc: str) -> None:
    dich.mkdir(parents=True, exist_ok=True, mode=0o700)
    for kid, ban_ghi in kenh.items():
        _ghi(dich / f"{kid}.json", ban_ghi)
    for cu in dich.glob("*.json"):  # kênh không còn trúng: bỏ tệp cũ, nhưng chỉ tệp của sổ này
        if cu.stem not in kenh and _cua_so_nay(cu):
            cu.unlink()
    _ghi(so, {
        "sinh_luc": sinh_luc,
        "so_tai_lieu_quet": len(ket_qua),
        "trung": [
            {"doc_id": k.tai_lieu.doc_id, "duong_dan": k.tai_lieu.duong_dan,
             "kenh_id": kenh_id(k.tieu_de[0][0]), "ban_parse": k.ban}
            for k in ket_qua if k.trung
        ],
        # Chỉ một dấu hiệu: đây là chỗ dương tính giả sẽ nằm nếu luật lỏng ra.
        "mot_dau_hieu": [
            {"doc_id": k.tai_lieu.doc_id, "duong_dan": k.tai_lieu.duong_dan,
             "co_tieu_de": k.co_tieu_de, "co_thanh_vien": k.co_thanh_vien}
            for k in ket_qua if not k.trung and (k.co_tieu_de or k.co_thanh_vien)
        ],
    })


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kho", type=Path, default=DEFAULT_STORE)
    ap.add_argument("--dich", type=Path, default=DICH)
    ap.add_argument("--so", type=Path, default=SO_NHAN_DIEN)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    sinh_luc = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    ket_qua = [nhan_dien(tl) for tl in nap_kho(a.kho)]
    kenh = dung_kenh(ket_qua, sinh_luc)
    trung = [k for k in ket_qua if k.trung]
    print(f"quét {len(ket_qua)} tài liệu · trúng {len(trung)} · {len(kenh)} kênh · "
          f"chỉ tiêu đề {sum(k.co_tieu_de and not k.trung for k in ket_qua)} · "
          f"chỉ thành viên {sum(k.co_thanh_vien and not k.trung for k in ket_qua)}")
    for kid, k in kenh.items():
        print(f"  {kid}: {k['so_tin']['truoc_gop']} tệp → {k['so_tin']['sau_gop']} tin · "
              f"hồ sơ {k['thuoc_ho_so']} · đoạn {k['so_doan']} · @ mất tên {k['at_mat_ten']}"
              + (f" · xung đột {[x['loai'] for x in k['xung_dot']]}" if k["xung_dot"] else ""))
    if not a.dry_run:
        ghi_so(kenh, ket_qua, a.dich, a.so, sinh_luc)
        print(f"ghi {len(kenh)} tệp vào {a.dich}, sổ nhận diện {a.so}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
