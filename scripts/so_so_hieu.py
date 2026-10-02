#!/usr/bin/env python3
"""Sổ số hiệu: mọi số định danh trong nội dung hồ sơ, chia hai bảng, kèm dòng trích.

Tên tệp gần như không nói số nào nằm trong tài liệu, nên sổ này đọc NỘI DUNG
(bản parse ADE trong ~/.private/ade_out) và ghi mỗi số một lần cho mỗi hồ sơ,
kèm loại, chủ sở hữu, tệp nguồn và từng dòng trích.

Hai bảng, và một ngăn chờ:

- CÔNG KHAI: số đơn và số văn bằng USPTO. Tra cứu công khai được, được phép
  lên tên tệp.
- NHẠY CẢM: Mã cơ quan thuế, số và ký hiệu hoá đơn, số hợp đồng, CCCD, số
  tài khoản, số điện thoại. CẤM lên tên tệp: tên tệp lộ ra trong ảnh chụp màn
  hình, danh sách thư mục, bản sao lưu, email đính kèm.
- CHƯA XẾP: số không thuộc hai bảng trên (số đăng ký quốc tế, mã số thuế,
  docket, số đề nghị thanh toán...). Mặc định cấm như bảng nhạy cảm cho tới
  khi người xếp nó vào một bảng.

Chủ sở hữu của một số: `ta` (khách hàng và REFINY), `doi_chung` (chủ nhãn bị
tra cứu hoặc bị trích dẫn), `doi_tac` (đại diện, nhà cung cấp, cơ quan), hoặc
`chua_ro` kèm lý do khi quy tắc không đủ căn cứ. Với số USPTO, số là của ta
khi trường "Mark" gần nó nhất trùng nhãn của hồ sơ; một phiếu bầu `ta` ở BẤT
KỲ tệp nào trong hồ sơ thì cả hồ sơ nhận. Phải quét cả hồ sơ chứ không quét
theo thư mục: số đơn có khi chỉ nằm trong nhánh khiếu nại, không nằm trong
nhánh nộp đơn.

Tệp thuộc hồ sơ nào thì đọc từ sổ danh tính (`scripts/so_danh_tinh.py`), không
tự suy từ thư mục hay tên tệp: chứng từ dùng chung ghi số dưới MỌI hồ sơ nó
thuộc; tệp còn ca chờ người trong hàng chờ xung đột thì số của nó nằm ở dòng
`ho_so: null` kèm `xung_dot` trỏ về ca đó, và ca đã quyết thì theo quyết định.

Phần cuối quét mọi đường dẫn trong kho gốc và chứng minh tên tệp nào mang số
nhạy cảm, theo hai đường độc lập: (a) lấy từng số nhạy cảm tìm được trong nội
dung, so với mọi đường dẫn; (b) xếp loại mọi dãy chữ số và mọi dạng số nhạy
cảm có trên tên tệp, dãy nào không giải thích được thì liệt kê. Tên tệp
mang số cấm mà người có quyền đã quyết giữ nguyên thì ghi trong một tệp riêng
(--chap-nhan, cũng trong ~/.private); sổ vẫn liệt kê chúng, đánh dấu
`da_chap_nhan`, và chỉ khớp đúng (tệp, loại, số) đã ghi — số mới trên cùng tên
vẫn là vi phạm mở.

Sổ ghi ra ~/.private/so/so_hieu.json (0600), ngoài mọi cây git. Không in số
nhạy cảm ra màn hình; không đổi tên, không di chuyển gì trong kho gốc.

    python3 scripts/so_so_hieu.py [--ade-out DIR] [--nguon DIR] [--danh-tinh FILE] [--ra FILE] [--chap-nhan FILE]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import so_hop_dong  # noqa: E402
from ocr_lab.danh_tinh import CHO_NGUOI_XAC_NHAN  # noqa: E402

KHO = Path.home() / ".private" / "ade_out"
NGUON = Path.home() / ".private" / "refiny_data"
SO = Path.home() / ".private" / "so" / "so_hieu.json"
DANH_TINH = Path.home() / ".private" / "so" / "danh_tinh.json"
CHAP_NHAN = Path.home() / ".private" / "so" / "ten_tep_chap_nhan.json"

CONG_KHAI = "cong_khai"
NHAY_CAM = "nhay_cam"
CHUA_XEP = "chua_xep"

BANG_CUA_LOAI = {
    "so_don_uspto": CONG_KHAI,
    "so_van_bang_uspto": CONG_KHAI,
    "ma_cqt": NHAY_CAM,
    "so_hoa_don": NHAY_CAM,
    "ky_hieu_hoa_don": NHAY_CAM,
    "so_hop_dong": NHAY_CAM,
    "cccd": NHAY_CAM,
    "so_tai_khoan": NHAY_CAM,
    "so_dien_thoai": NHAY_CAM,
    "so_dang_ky_quoc_te": CHUA_XEP,
    "so_dang_ky_nuoc_ngoai": CHUA_XEP,
    "so_dang_ky_ban_quyen": CHUA_XEP,
    "so_yeu_cau_ban_quyen": CHUA_XEP,
    "so_the_luat_su": CHUA_XEP,
    "ma_so_thue": CHUA_XEP,
    "ma_theo_doi": CHUA_XEP,
    "so_de_nghi_thanh_toan": CHUA_XEP,
}

# Nhóm chỉ để đếm trong tóm tắt: định danh nhãn đã đăng ký tách khỏi số liên
# lạc, mã số thuế và các loại còn lại.
NHOM_LOAI = {
    "so_don_uspto": "dinh_danh_nhan",
    "so_van_bang_uspto": "dinh_danh_nhan",
    "so_dang_ky_quoc_te": "dinh_danh_nhan",
    "so_dang_ky_nuoc_ngoai": "dinh_danh_nhan",
    "so_dien_thoai": "so_dien_thoai",
    "ma_so_thue": "ma_so_thue",
}

# Trường "Mark" gần số nhất quyết định chủ sở hữu, nhưng chỉ trong cửa sổ này.
# Rộng hơn thì thông báo từ chối (nhãn của ta ở đầu, nhãn đối chứng ở giữa
# văn bản) sẽ gán nhầm số của bên khác cho ta.
CUA_SO_NHAN = 25

CHUA_CAP_SO = "<Chưa cấp số>"


# --------------------------------------------------------------------------
# Chuẩn hoá
# --------------------------------------------------------------------------

bo_dau = so_hop_dong.bo_dau

# Chỉ gỡ thẻ HTML thật; "<Chưa cấp số>" trên hoá đơn nháp phải sống sót.
_THE_HTML = re.compile(
    r"</?(?:table|thead|tbody|tr|td|th|br|b|i|u|p|div|span|a|img|sup|sub|ul|ol|li|h\d)\b[^>]*>",
    re.I,
)
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")


def phang(dong: str) -> str:
    """Một dòng markdown/HTML thành chữ thường: ô bảng thành ' | ', bỏ **."""
    dong = _THE_HTML.sub(" | ", dong).replace("**", "")
    dong = re.sub(r"(?:\s*\|\s*)+", " | ", dong)
    return re.sub(r"\s+", " ", dong).strip(" |")


def chuan_nhan(s: str) -> str:
    """'Zor Blax' và 'ZOR BLAX' là một; 'ZORBLAX' là nhãn khác."""
    return re.sub(r"[^0-9A-Z]+", " ", bo_dau(s)).strip()


def chuan_gia_tri(loai: str, v: str) -> str:
    if v == CHUA_CAP_SO:
        return v
    if loai == "so_hop_dong":
        return so_hop_dong.chuan_so_hop_dong(v)
    return re.sub(r"[^0-9A-Z]", "", bo_dau(v))


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


# --------------------------------------------------------------------------
# Hồ sơ
# --------------------------------------------------------------------------

NGOAI_HO_SO = "(ngoai ho so)"


_NHAN_TREN_THU_MUC = re.compile(r"^\d{2,4}\s*\.?\s*(?:US|VN)?\s*\.?\s*(.+?)\s+in\s+class\b", re.I)
# Chữ mô tả KIỂU nhãn trên tên thư mục, không thuộc chữ của nhãn.
_KIEU_NHAN = {"HINH", "DEVICE", "LOGO"}


def nhan_cua_ho_so(ho_so: str) -> str | None:
    """'901. US. ZORBLAX, hinh in CLASS 009' -> 'ZORBLAX';
    '902. US. FOO, handmade device IN CLASS 021' -> 'FOO HANDMADE'."""
    m = _NHAN_TREN_THU_MUC.match(ho_so)
    if not m:
        return None
    chu = [t for t in chuan_nhan(m.group(1)).split() if t not in _KIEU_NHAN]
    return " ".join(chu) or None


def theo_danh_tinh(so_dt: dict, hang_cho: list[dict], hang_cho_tep: str = "") -> dict[str, dict]:
    """Đường dẫn NFC -> hồ sơ của tệp theo sổ danh tính.

    `ho_so`: mọi hồ sơ tệp thuộc (n–n), mỗi cái kèm khoá và nhãn. Tệp có xung
    đột mà còn ca chưa quyết (hoặc quyết mà không ghi `quyet_dinh`) thì `ho_so`
    rỗng và `xung_dot` nói ca nào, xếp tạm ở đâu; không chọn thay người."""
    ho_so = {h["ho_so"]: h for h in so_dt["ho_so"]}
    ca_cua: dict[str, list[dict]] = defaultdict(list)
    for c in hang_cho:
        for r in [c["duong_dan"], *c.get("ban_khac", [])]:
            ca_cua[nfc(r)].append(c)

    def cac_ho_so(nhans) -> list[dict]:
        return [{"ho_so": n, "ma": (ho_so.get(n) or {}).get("khoa"),
                 "nhan": nhan_cua_ho_so((ho_so.get(n) or {}).get("thu_muc") or "")} for n in nhans]

    ra = {}
    for tl in so_dt["tai_lieu"]:
        for b in tl["tep"]:
            rel = nfc(b["duong_dan"])
            if not b["xung_dot"]:
                ra[rel] = {"ho_so": cac_ho_so(b["thuoc_ho_so"]), "xung_dot": None}
                continue
            cs = ca_cua[rel]
            cho = [c for c in cs if c.get("trang_thai") == CHO_NGUOI_XAC_NHAN or not c.get("quyet_dinh")]
            if cho or not cs:
                ra[rel] = {"ho_so": [], "xung_dot": {
                    "ca": sorted(c["ca"] for c in cho), "loai": sorted(b["xung_dot"]),
                    "xep_tam": b["thuoc_ho_so"], "hang_cho": hang_cho_tep}}
                continue
            quyet = {n for c in cs for n in ([c["quyet_dinh"]] if isinstance(c["quyet_dinh"], str)
                                             else c["quyet_dinh"])}
            ra[rel] = {"ho_so": cac_ho_so(sorted(quyet)), "xung_dot": None}
    return ra


def nap_danh_tinh(p: Path) -> dict[str, dict]:
    """Sổ danh tính và hàng chờ xung đột nằm cạnh nó (cả hai do so_danh_tinh ghi)."""
    hang_cho_tep = p.with_name("hang_cho_xung_dot.jsonl")
    hang_cho = ([json.loads(d) for d in hang_cho_tep.read_text("utf-8").splitlines() if d.strip()]
                if hang_cho_tep.exists() else [])
    return theo_danh_tinh(json.loads(p.read_text("utf-8")), hang_cho, str(hang_cho_tep))


def _xep_vao(rel: str, rec: dict | None) -> list[dict]:
    """Các nhóm hồ sơ một tệp góp số vào: mỗi hồ sơ nó thuộc, hoặc một nhóm xung đột."""
    if rec is None:
        return [{"khoa": NGOAI_HO_SO, "ho_so": NGOAI_HO_SO, "ma": None, "nhan": None, "xung_dot": None}]
    if rec["xung_dot"]:
        x = rec["xung_dot"]
        return [{"khoa": ("xung_dot", *(x["ca"] or [rel])), "ho_so": None, "ma": None, "nhan": None,
                 "xung_dot": x}]
    return [{"khoa": h["ho_so"], **h, "xung_dot": None} for h in rec["ho_so"]]


_TAI_LIEU_TRA_CUU = re.compile(r"doi chung|cited|office action|tra cuu|search|refusal", re.I)


# --------------------------------------------------------------------------
# Nạp kho
# --------------------------------------------------------------------------

BIEN_THE = (
    ("meta_pro2.json", "parse_pro2.json", "pro2"),
    ("meta_pro.json", "parse_pro.json", "pro"),
    ("meta.json", "parse.json", "chuan"),
)


def nap_kho(kho: Path) -> list[dict]:
    """Mỗi tài liệu một bản parse, ưu tiên pro2 > pro > chuẩn."""
    ra = []
    for thu_muc in sorted(kho.iterdir()):
        if not thu_muc.is_dir():
            continue
        for ten_meta, ten_parse, engine in BIEN_THE:
            p_meta, p_parse = thu_muc / ten_meta, thu_muc / ten_parse
            if not (p_meta.exists() and p_parse.exists()):
                continue
            try:
                meta = json.loads(p_meta.read_text(encoding="utf-8"))
                md = json.loads(p_parse.read_text(encoding="utf-8")).get("markdown") or ""
            except (json.JSONDecodeError, OSError):
                continue
            ra.append({
                "doc_id": thu_muc.name,
                "nguon": nfc(meta.get("source", "")),
                "engine": engine,
                "markdown": md,
            })
            break
    return ra


# --------------------------------------------------------------------------
# Trích số theo nhãn
# --------------------------------------------------------------------------

# Thứ tự có nghĩa: luật đứng trước giữ chỗ trên dòng, luật sau không được bắt
# lại cùng đoạn đó ("International Registration Number" không phải số văn bằng).
LUAT = [
    ("so_dang_ky_quoc_te", re.compile(
        r"international\s+registration(?:\s+(?:number|no\.?))?\s*[:|]?\s*\|?\s*(?<![\d,])(\d[\d,]{5,9}\d)(?![\d,])", re.I)),
    ("so_dang_ky_nuoc_ngoai", re.compile(
        r"foreign\s+registration\s+(?:number|no\.?)\s*[:|]?\s*([A-Z]{0,4}\d[\d,]{3,12})", re.I)),
    ("so_the_luat_su", re.compile(
        r"bar\s+membership\s+or\s+registration(?:\s+number)?\s*[:|]?\s*(\d{4,10})", re.I)),
    ("so_dang_ky_ban_quyen", re.compile(
        r"registration\s+(?:number|no\.?)\s*[:|]?\s*((?:VAu?|TXu?|PAu?|SRu?)\s*\d[\d-]{4,14}\d)\b", re.I)),
    ("so_yeu_cau_ban_quyen", re.compile(
        r"(?:service\s+request|case)\s*(?:#|no\.?|number)?\s*[:|]?\s*(1-\d{9,12})(?!\d)", re.I)),
    ("so_don_uspto", re.compile(
        r"(?:serial\s*(?:number|no\.?|#)?|application\s*(?:serial\s*)?(?:no\.?|number|#)|s[ốo]\s*đ[ơo]n(?:\s*USPTO)?)"
        r"[^\d\n]{0,30}?(?<![\d,])([789]\d{7})(?![\d,])", re.I)),
    ("so_van_bang_uspto", re.compile(
        r"(?:registration\s*(?:number|no\.?|#)|reg\.?\s*(?:no\.?|number|#)|s[ốo]\s*v[ăa]n\s*b[ằa]ng)"
        r"[^\d\n]{0,30}?(?<![\d,])(\d{7}|\d,\d{3},\d{3})(?![\d,])", re.I)),
    ("ma_cqt", re.compile(
        r"m[ãa]\s*(?:của\s*)?(?:CQT|c[ơo]\s*quan\s*thu[ếe])\s*[:|]?\s*([0-9A-F]{20,40})\b", re.I)),
    ("so_hoa_don", re.compile(
        r"\binvoice\s*(?:no\.?|number|#)?\s*[:.]?\s*#?\s*"
        r"((?=[A-Z0-9/-]*\d)[A-Z]{0,6}-?\d[A-Z0-9/-]{2,20})", re.I)),
    ("so_hop_dong", re.compile(
        r"(?<![A-Z0-9])([A-Z]{0,4}\d{2,5}(?:\.\d+)?\s*/\s*20\d\d\s*/\s*[A-ZĐ][A-ZĐ-]*[A-ZĐ])")),
    ("so_hop_dong", re.compile(
        r"(?:h[ợo]p\s*đ[ồo]ng|\bHĐ\b|contract|agreement)\s*(?:s[ốo]|no\.?|number)\s*[:.]?\s*"
        r"([A-Z0-9][A-Z0-9./-]*\d[A-Z0-9./Đ-]*)", re.I)),
    ("cccd", re.compile(
        r"(?:CCCD|c[ăa]n\s*c[ưu][ớo]c(?:\s*c[ôo]ng\s*d[âa]n)?|CMND|ch[ứu]ng\s*minh\s*(?:nh[âa]n\s*d[âa]n|th[ưu])"
        r"|s[ốo]\s*đ[ịi]nh\s*danh\s*c[áa]\s*nh[âa]n)[^\d\n]{0,25}?(?<!\d)(\d{12}|\d{9})(?!\d)", re.I)),
    ("so_tai_khoan", re.compile(
        r"(?:s[ốo]\s*t[àa]i\s*kho[ảa]n|\bSTK\b|account\s*(?:no\.?|number|#)|\bA/C\b(?:\s*(?:no\.?|number))?"
        r"|acct\.?\s*no\.?|beneficiary\s*account(?:\s*(?:no\.?|number))?)\s*[:.]?\s*(?<!\d)(\d[\d \-]{4,24}\d)(?!\d)", re.I)),
    ("so_dien_thoai", re.compile(
        r"(?:đi[ệe]n\s*tho[ạa]i|\bĐT\b|\bSĐT\b|\btel(?:ephone)?\b|\bphone(?:\s*number)?\b|\bmobile\b|\bhotline\b"
        r"|\bfax\b|\bzalo\b)\s*[:.|]?\s*(\+?\(?\d[\d\s().\-]{7,18}\d)", re.I)),
    ("ma_so_thue", re.compile(
        r"(?:m[ãa]\s*s[ốo]\s*thu[ếe]|\bMST\b|tax\s*code|taxcode|tax\s*id)\s*[:.]?\s*(?<!\d)(\d{10}(?:-\d{3})?|\d{12})(?!\d)", re.I)),
    ("ma_theo_doi", re.compile(
        r"docket\s*(?:number|no\.?)?\s*[:.|]?\s*([A-Z]{1,4}\d{6,12})\b", re.I)),
    ("so_de_nghi_thanh_toan", re.compile(r"(?<![A-Z0-9])((?:K?V|E)20\d\d-\d{2,4})(?!\d)")),
]

_KY_HIEU = re.compile(r"k[ýy]\s*hi[ệe]u(?:\s*\((?:serial|series)\))?\s*[:|]\s*([0-9][A-Z0-9]{4,9})\b", re.I)
_SO_HD_VAT = re.compile(r"^s[ốo]\s*(?:\((?:invoice\s*)?no\.?\))?\s*[:|]\s*(\d{6,8}|<Chưa cấp số>)", re.I)


# "Nghị quyết số 12/2025/QH15", "Nghị định số 01/2021/NĐ-CP": số hiệu văn bản
# pháp luật trích trong hợp đồng, không phải số hợp đồng.
_VAN_BAN_PHAP_LUAT = re.compile(r"^(?:QH|UBTVQH|ND|NQ|TT|QD|CT|L)(?:\b|-|\d)")


def _du_chu_so(loai: str, v: str) -> bool:
    so = len(re.sub(r"\D", "", v))
    if loai == "so_dien_thoai":
        return 9 <= so <= 13
    if loai == "so_tai_khoan":
        return so >= 6
    return True


def la_hoa_don_vat(md: str) -> bool:
    b = bo_dau(md[:4000])
    return "HOA DON" in b and ("MA CQT" in b or "KY HIEU" in b)


def trich_dong(md: str) -> list[dict]:
    """Mọi số có nhãn trong một tài liệu: (loại, giá trị thô, dòng, trích)."""
    ra = []
    dong = md.split("\n")
    vat = la_hoa_don_vat(md)
    for i, tho in enumerate(dong):
        sach = phang(tho)
        if not sach or "caseNumber=" in sach:
            continue
        chiem: list[tuple[int, int]] = []

        def them(loai: str, m: re.Match, g: int = 1) -> None:
            a, b = m.span(g)
            if any(a < y and x < b for x, y in chiem):
                return
            v = m.group(g).strip(" -/.")
            if not _du_chu_so(loai, v):
                return
            if loai == "so_hop_dong" and _VAN_BAN_PHAP_LUAT.match(bo_dau(v.rsplit("/", 1)[-1])):
                return
            chiem.append((a, b))
            ra.append({"loai": loai, "tho": v, "dong": i + 1, "trich": _EMAIL.sub("[email]", sach)[:240]})

        if vat:
            for m in _KY_HIEU.finditer(sach):
                them("ky_hieu_hoa_don", m)
            m = _SO_HD_VAT.match(sach)
            if m and any(_KY_HIEU.search(phang(x)) for x in dong[max(0, i - 4):i]):
                them("so_hoa_don", m)
        for loai, r in LUAT:
            for m in r.finditer(sach):
                them(loai, m)
    return ra


# --------------------------------------------------------------------------
# Chủ sở hữu
# --------------------------------------------------------------------------

_TRUONG_MARK = re.compile(r"(?:^|\|)\s*(?:word\s+)?mark\s*(?::\s*\|?|\|)\s*([^|]{1,80})", re.I)
_KHONG_PHAI_NHAN = {"", "INFORMATION", "SERIAL NUMBER", "REGISTRATION NUMBER", "STATUS"}
_CASE_NUMBER = re.compile(r"caseNumber=(\d{8})")
_MARK_TRONG = re.compile(r"^(?:word\s+)?mark\s*:?$", re.I)
_DONG_HINH = re.compile(r"^\[[^\]]{3,120}\]$")


def truong_nhan(dong: list[str], nhan_ho_so: str | None) -> list[tuple[int, str, str]]:
    """(chỉ số dòng, nhãn đã chuẩn hoá, kiểu) cho mỗi trường Mark trong tài liệu.

    Giấy chứng nhận đăng ký in nhãn thành một dòng riêng, không có chữ "Mark",
    nên dòng nào chỉ gồm đúng nhãn của hồ sơ cũng tính là một trường. Nhãn
    hình trên TSDR để trống "Mark:" và in mô tả hình ở dòng sau, dạng "[...]".
    """
    ra = []
    for i, tho in enumerate(dong):
        sach = phang(tho)
        if _MARK_TRONG.match(sach):
            sau = next((phang(x) for x in dong[i + 1:i + 5] if phang(x) and not x.lstrip().startswith("<")), "")
            v = chuan_nhan(sau)
            if v:
                ra.append((i, v, "mark"))
            continue
        for m in _TRUONG_MARK.finditer(sach):
            v = chuan_nhan(m.group(1))
            if v not in _KHONG_PHAI_NHAN:
                ra.append((i, v, "mark"))
                break
        else:
            if nhan_ho_so and chuan_nhan(sach.lstrip("# ")) == nhan_ho_so:
                ra.append((i, nhan_ho_so, "dong_nhan"))
            elif _DONG_HINH.match(sach):
                ra.append((i, chuan_nhan(sach), "hinh"))
    return ra


def trang_tsdr(dong: list[str]) -> list[str | None]:
    """Bản in TSDR: mỗi trang kết thúc bằng URL caseNumber=<serial>. Mỗi dòng
    thuộc bản ghi của URL cuối trang chứa nó; tài liệu khác trả toàn None."""
    ra: list[str | None] = [None] * len(dong)
    hien = None
    for i in range(len(dong) - 1, -1, -1):
        m = _CASE_NUMBER.search(dong[i])
        if m:
            hien = m.group(1)
        ra[i] = hien
    return ra


def phieu_nhan(i: int, truong: list[tuple], trang: list[str | None]) -> tuple | None:
    """Trường Mark quyết định cho số ở dòng i: cùng bản ghi TSDR nếu có, không
    thì trường gần nhất trong CUA_SO_NHAN dòng."""
    if trang[i] is not None:
        cung = [t for t in truong if trang[t[0]] == trang[i]]
        chu = [t for t in cung if t[2] != "hinh"]
        return (chu or cung or [None])[0]
    gan = [t for t in truong if abs(t[0] - i) <= CUA_SO_NHAN and t[2] != "hinh"]
    return min(gan, key=lambda t: abs(t[0] - i)) if gan else None


def chu_khong_uspto(loai: str, trich: str, chuan: str = "") -> tuple[str, str]:
    """Chủ sở hữu cho số không phải USPTO, suy từ loại và dòng trích."""
    b = bo_dau(trich)
    if loai in ("ma_cqt", "ky_hieu_hoa_don"):
        return "ta", "hoá đơn điện tử REFINY phát hành cho khách"
    if loai == "so_hoa_don":
        if "INVOICE" not in b or "REFINY INVOICE" in b:
            return "ta", "hoá đơn REFINY phát hành"
        return "doi_tac", "hoá đơn của đại diện/nhà cung cấp gửi REFINY"
    if loai == "so_tai_khoan":
        if "REFINY" in b:
            return "ta", "tài khoản nhận tiền của REFINY"
        if re.search(r"BENEFICIARY|ACCOUNT|A/C|ACCT", b):
            return "doi_tac", "tài khoản thụ hưởng trên hoá đơn đại diện nước ngoài"
        return "ta", "nhãn tiếng Việt: tài khoản bên ta hoặc khách"
    if loai == "so_dien_thoai":
        if chuan.startswith("0") or (chuan.startswith("84") and len(chuan) in (11, 12)):
            return "ta", "số Việt Nam: khách hoặc REFINY"
        return "doi_tac", "số nước ngoài: đại diện, cơ quan hoặc sàn"
    if loai == "cccd":
        return "ta", "giấy tờ tuỳ thân của khách hoặc người đại diện bên ta"
    if loai == "ma_so_thue":
        if "MISA" in b:
            return "doi_tac", "MST của nhà cung cấp phần mềm hoá đơn"
        return "ta", "MST bên bán (REFINY) hoặc bên mua (khách)"
    if loai in ("so_the_luat_su", "ma_theo_doi"):
        return "doi_tac", "định danh do luật sư đại diện Hoa Kỳ cấp"
    if loai in ("so_de_nghi_thanh_toan", "so_yeu_cau_ban_quyen", "so_dang_ky_ban_quyen"):
        return "ta", "chứng từ/đơn của chính hồ sơ"
    return "chua_ro", "không có quy tắc cho loại này"


# --------------------------------------------------------------------------
# Dựng sổ
# --------------------------------------------------------------------------

def _chu_hop_dong(kho: Path) -> dict[str, tuple[str, str]]:
    """Khoá hợp đồng -> (chủ, lý do), lấy từ sổ hợp đồng (chiều tiền)."""
    ra = {}
    tai_lieu = so_hop_dong.quet(str(kho))
    so_hop_dong.gan_ban_mat_so(tai_lieu)
    for hd in so_hop_dong.gop(tai_lieu):
        chieu = (hd.get("doi_tac") or {}).get("chieu_tien")
        if chieu == "doanh_thu":
            ra[hd["khoa"]] = ("ta", "hợp đồng REFINY ký với khách")
        elif chieu == "chi_phi":
            ra[hd["khoa"]] = ("doi_tac", "hợp đồng REFINY ký với đại diện")
        else:
            ra[hd["khoa"]] = ("chua_ro", f"sổ hợp đồng: vai trò {(hd.get('doi_tac') or {}).get('vai_tro')}")
    return ra


def dung_so(tai_lieu: list[dict], danh_tinh: dict[str, dict], chu_hop_dong: dict | None = None) -> list[dict]:
    """Gom mọi lần xuất hiện theo (hồ sơ, loại, giá trị chuẩn), rồi gán chủ.
    `danh_tinh`: kết quả `theo_danh_tinh`; tệp không có trong đó là ngoài hồ sơ."""
    chu_hop_dong = chu_hop_dong or {}
    nhom: dict[tuple, dict] = {}
    for tl in tai_lieu:
        rel = tl["nguon"]
        dong = tl["markdown"].split("\n")
        trang = trang_tsdr(dong)
        cac_so = trich_dong(tl["markdown"])
        for hs in _xep_vao(rel, danh_tinh.get(rel)):
            truong = truong_nhan(dong, hs["nhan"])
            for x in cac_so:
                chuan = chuan_gia_tri(x["loai"], x["tho"])
                k = (hs["khoa"], x["loai"], chuan)
                if k not in nhom:
                    nhom[k] = {
                        "ho_so": hs["ho_so"], "ma_ho_so": hs["ma"], "nhan_ho_so": hs["nhan"],
                        **({"xung_dot": hs["xung_dot"]} if hs["xung_dot"] else {}),
                        "loai": x["loai"], "bang": BANG_CUA_LOAI[x["loai"]],
                        "gia_tri": x["tho"], "chuan": chuan,
                        "lan_xuat_hien": [], "_phieu": [],
                    }
                lan = {"doc_id": tl["doc_id"], "tep": rel, "engine": tl["engine"],
                       "dong": x["dong"], "trich": x["trich"]}
                if x["loai"] in ("so_don_uspto", "so_van_bang_uspto"):
                    p = phieu_nhan(x["dong"] - 1, truong, trang)
                    lan["nhan_gan_nhat"] = p[1] if p else None
                    nhom[k]["_phieu"].append((p, lan))
                nhom[k]["lan_xuat_hien"].append(lan)

    so = []
    for g in nhom.values():
        phieu = g.pop("_phieu")
        if g["bang"] == CONG_KHAI:
            g["chu_so_huu"], g["ly_do"] = _chu_uspto(g, phieu)
            nhan = Counter(p[0][1] for p in phieu if p[0])
            g["nhan_hieu"] = nhan.most_common(1)[0][0] if nhan else None
        elif g["loai"] == "so_hop_dong":
            g["chu_so_huu"], g["ly_do"] = chu_hop_dong.get(
                g["chuan"], ("chua_ro", "số không có trong sổ hợp đồng"))
        else:
            chu = Counter(chu_khong_uspto(g["loai"], l["trich"], g["chuan"]) for l in g["lan_xuat_hien"])
            g["chu_so_huu"], g["ly_do"] = chu.most_common(1)[0][0]
        if g["chuan"] == CHUA_CAP_SO:
            g["chua_cap_so"] = True
        g["so_tep"] = len({l["doc_id"] for l in g["lan_xuat_hien"]})
        so.append(g)
    so.sort(key=lambda g: (g["ho_so"] or "", g["bang"], g["loai"], g["chuan"]))
    return so


def _chu_uspto(g: dict, phieu: list) -> tuple[str, str]:
    """Số USPTO: của ta nếu ở bất kỳ tệp nào trong hồ sơ, trường Mark gần nó
    trùng nhãn hồ sơ. Không thì đối chứng nếu có nhãn khác, hoặc nếu chỉ nằm
    trong tài liệu tra cứu/thông báo từ chối."""
    if g.get("xung_dot"):
        return "chua_ro", "tệp chờ người xác nhận hồ sơ trong hàng chờ xung đột"
    nhan_hs = g["nhan_ho_so"]
    ta = [(p, l) for p, l in phieu if p and nhan_hs and p[1] == nhan_hs]
    if ta:
        p, l = ta[0]
        return "ta", f"trường Mark = {nhan_hs} ở {Path(l['tep']).name} dòng {p[0] + 1}"
    khac = [(p, l) for p, l in phieu if p and p[1] != nhan_hs]
    if khac:
        p, l = khac[0]
        return "doi_chung", f"trường Mark = {p[1]} ≠ {nhan_hs} ở {Path(l['tep']).name} dòng {p[0] + 1}"
    if all(_TAI_LIEU_TRA_CUU.search(bo_dau(l["tep"])) for _, l in phieu):
        return "doi_chung", "chỉ nằm trong tài liệu tra cứu/thông báo, không có trường Mark gần"
    return "chua_ro", "không có trường Mark gần số trong tệp nào"


# --------------------------------------------------------------------------
# Bảng đối chứng
# --------------------------------------------------------------------------

_OWNER = re.compile(r"(?:owner|registrant)\s*name\s*[:|]\s*([^|]{2,120})", re.I)


def bang_doi_chung(tl: dict, so: list[dict], danh_tinh: dict[str, dict]) -> list[dict]:
    """Phân giải một bản tổng hợp đối chứng (bản in TSDR ghép) theo bản ghi."""
    dong = tl["markdown"].split("\n")
    trang = trang_tsdr(dong)
    ho_so = (danh_tinh.get(tl["nguon"]) or {}).get("ho_so") or []
    nhan_hs = {h["nhan"] for h in ho_so if h["nhan"]}
    ban_ghi: dict[str, dict] = {}
    so_cua_ta = {g["chuan"] for g in so
                 if g["ho_so"] in {h["ho_so"] for h in ho_so} and g["chu_so_huu"] == "ta"}
    for x in trich_dong(tl["markdown"]):
        serial = trang[x["dong"] - 1]
        if serial is None:
            continue
        r = ban_ghi.setdefault(serial, {"so": []})
        r["so"].append({"loai": x["loai"], "gia_tri": chuan_gia_tri(x["loai"], x["tho"]), "dong": x["dong"]})
    for serial, r in ban_ghi.items():
        cac_dong = [i for i, s in enumerate(trang) if s == serial]
        r["nhan_hieu"] = next((v for i, v, _ in truong_nhan(dong, None) if i in cac_dong), None)
        r["chu_nhan"] = next((m.group(1).strip() for i in cac_dong for m in [_OWNER.search(phang(dong[i]))] if m), None)
        # một số xuất hiện nhiều trang: giữ lần đầu
        thay, gon = set(), []
        for s in r["so"]:
            if (s["loai"], s["gia_tri"]) not in thay:
                thay.add((s["loai"], s["gia_tri"]))
                gon.append(s)
        r["so"] = gon
        r["cua_ta"] = r["nhan_hieu"] in nhan_hs or any(s["gia_tri"] in so_cua_ta for s in gon)
    return list(ban_ghi.values())


# --------------------------------------------------------------------------
# Chứng minh tên tệp
# --------------------------------------------------------------------------

_ZALO = re.compile(r"z\d{13}_[0-9a-f]{32}", re.I)
_TIEN = re.compile(r"\d{1,3}(?:[.,]\d{3})+\s*(?:VND|D|USD)", re.I)

# Dạng có tên trên tên tệp. Dãy số nằm trọn trong một khoảng khớp thì được
# giải thích bằng lớp đó — trừ lớp mang bảng CHUA_XEP: lớp ấy chỉ đặt tên cho
# dãy, dãy vẫn bị liệt kê vì chưa ai cho phép nó lên tên tệp.
_DANG_TREN_TEN = [
    ("ma_xuat_zalo", _ZALO, None),
    ("so_tien", _TIEN, None),
    # mã hồ sơ / mã yêu cầu tư vấn nội bộ: NH901.US, TV100-200, TV1000.1
    ("ma_ho_so", re.compile(r"(?<![A-Z0-9])(?:NH|BQ|TV)\d{2,5}(?:\.\d{1,2})?(?:-\d{1,4})?(?!\d)"), None),
    ("dang_so_de_nghi_thanh_toan", re.compile(r"(?<![A-Z0-9])(?:K?V|E)20\d\d-\d{2,4}(?!\d)"), CHUA_XEP),
    ("dang_so_yeu_cau_ban_quyen", re.compile(r"(?<!\d)1-\d{9,12}(?!\d)"), CHUA_XEP),
]


def _bo_dau_giu_vi_tri(s: str) -> str:
    """Như `bo_dau` nhưng giữ nguyên độ dài, để khoảng khớp chỉ đúng chỗ trên tên."""
    s = unicodedata.normalize("NFC", s).replace("Đ", "D").replace("đ", "d")
    return "".join(unicodedata.normalize("NFD", c)[0].upper() for c in s)


def _day_so(s: str) -> set[str]:
    """Dãy chữ số trên tên, cả dạng bị ngăn bởi . , - hay khoảng trắng đơn."""
    return set(re.findall(r"\d+", s)) | {re.sub(r"\D", "", m) for m in re.findall(r"\d(?:[.,\s-]?\d)*", s)}


def _la_ngay(d: str) -> bool:
    def hop_le(ng, th, nam):
        try:
            dt.date(nam, th, ng)
            return 1990 <= nam <= 2040
        except ValueError:
            return False
    if len(d) == 6:
        return hop_le(int(d[:2]), int(d[2:4]), 2000 + int(d[4:]))
    if len(d) == 8:
        # ddmmyyyy, yyyymmdd, và mmddyyyy của tệp phía đối tác Mỹ gửi
        return (hop_le(int(d[:2]), int(d[2:4]), int(d[4:])) or hop_le(int(d[6:]), int(d[4:6]), int(d[:4]))
                or hop_le(int(d[2:4]), int(d[:2]), int(d[4:])))
    return False


def kiem_ke(nguon: Path) -> list[str]:
    """Mọi tệp trong kho gốc, đường dẫn tương đối NFC."""
    return sorted(nfc(str(p.relative_to(nguon))) for p in nguon.rglob("*") if p.is_file())


# Số hoá đơn VAT đệm số 0 ("00000042") thường lên tên ở dạng ngắn ngay sau từ
# khoá: "Hoa don 42", "HD_so_42". Chỉ ngay sau từ khoá mới nhận dạng ngắn dưới
# 4 chữ số; đứng trơn thì "42" là quá nhiều thứ khác.
_SAU_TU_KHOA_HOA_DON = re.compile(
    r"(?<![A-Z0-9])(?:(?:HD|HOA[\s_]*DON|VAT|INVOICE|SO)(?![A-Z0-9])[\W_]{0,3})+0*(\d+)(?!\d)")


def chung_minh_ten_tep(tep: list[str], so: list[dict], chap_nhan: frozenset = frozenset(),
                       danh_tinh: dict[str, dict] | None = None) -> dict:
    """(a) mọi số cấm tìm thấy trong nội dung, so với mọi đường dẫn;
    (b) mọi dãy >= 5 chữ số và mọi dạng số nhạy cảm trên tên, xếp loại.
    `chap_nhan`: các bộ (tệp, loại, số) đã được quyết giữ nguyên tên."""
    cam = [g for g in so if g["bang"] != CONG_KHAI and g["chuan"] != CHUA_CAP_SO]
    cong_khai = {g["chuan"] for g in so if g["bang"] == CONG_KHAI}
    theo_gia_tri: dict[tuple, list[dict]] = defaultdict(list)
    for g in cam:
        theo_gia_tri[(g["loai"], g["chuan"])].append(g)

    vi_pham, xep_loai, khong_giai_thich = [], Counter(), []
    for rel in tep:
        day = _day_so(rel)
        chu = re.sub(r"[^0-9A-Z]", "", bo_dau(rel))
        sau_tu_khoa = set(_SAU_TU_KHOA_HOA_DON.findall(_bo_dau_giu_vi_tri(Path(rel).name)))
        trung = []
        for (loai, v), gs in theo_gia_tri.items():
            if v.isdigit():
                gon = v.lstrip("0")
                khop = v in day or (len(gon) >= 4 and gon in day) or (
                    loai == "so_hoa_don" and gon != "" and gon in sau_tu_khoa)
            else:
                # số hợp đồng giữ `/` và `-` trong sổ; tên tệp thì không mang được `/`
                khop = len(_chu_so(v)) >= 5 and _chu_so(v) in chu
            if khop:
                trung.append({
                    "loai": loai, "bang": gs[0]["bang"], "chuan": v,
                    "da_chap_nhan": (rel, loai, v) in chap_nhan,
                    "chu_so_huu": sorted({g["chu_so_huu"] for g in gs}),
                    "noi_dung_o": sorted({l["tep"] for g in gs for l in g["lan_xuat_hien"]})[:5],
                })
        if trung:
            vi_pham.append({"tep": rel, "so": trung,
                            "trang_thai": "da_chap_nhan" if all(t["da_chap_nhan"] for t in trung) else "mo"})

        # (b) theo hình dạng, không cần sổ
        ten = _bo_dau_giu_vi_tri(Path(rel).name)
        for lop, d in _xep_day_so(ten, trung, cong_khai):
            if lop is None or lop.startswith("dang_"):
                khong_giai_thich.append({"tep": rel, "day_so": d, "dang": lop or _dang_nhay_cam(d)})
            else:
                xep_loai[lop] += 1
        if not trung:
            for m in re.finditer(r"\b(INVOICE|HOA DON|HOP DONG|CONTRACT|CCCD|STK|TAI KHOAN)\W{0,3}[A-Z]{0,6}-?\d{4,}", ten):
                khong_giai_thich.append({"tep": rel, "day_so": m.group(0),
                                         "dang": "tu_khoa_" + m.group(1).lower().replace(" ", "_")})
    return {
        "so_tep": len(tep),
        "so_tep_trong_ho_so": sum(1 for r in tep if r in (danh_tinh or {})),
        "so_gia_tri_cam_da_so": len(theo_gia_tri),
        "vi_pham": vi_pham,
        "xep_loai_day_so": dict(xep_loai),
        "khong_giai_thich": khong_giai_thich,
    }


def _mau_gia_tri(v: str) -> str:
    """Regex tìm lại một giá trị của sổ trên tên, cho phép dấu ngăn giữa các ký tự."""
    if v.isdigit():
        loi = v.lstrip("0") if len(v.lstrip("0")) >= 4 else v
        return r"(?<!\d)(?:0[.,\s-]?)*" + r"[.,\s-]?".join(loi) + r"(?!\d)"
    return r"[\W_]{0,3}".join(map(re.escape, _chu_so(v)))


def _chu_so(v: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", bo_dau(v))


def _xep_day_so(ten: str, trung: list[dict], cong_khai: set[str]):
    """Mỗi cụm >= 5 chữ số trên tên -> (lớp, dãy). Lớp None: không giải thích được."""
    da_so = [m.span() for t in trung for m in re.finditer(_mau_gia_tri(t["chuan"]), ten)]
    dang = [(lop, m.span()) for lop, rx, _ in _DANG_TREN_TEN for m in rx.finditer(ten)]

    def lop_cua(a: int, b: int, d: str) -> str | None:
        if any(x <= a and b <= y for x, y in da_so):
            return "so_cam_da_liet_ke_o_a"
        if _la_ngay(d):
            return "ngay"
        if d in cong_khai:
            return "so_cong_khai_uspto"
        return next((lop for lop, (x, y) in dang if x <= a and b <= y), None)

    for m in re.finditer(r"\d(?:[.,\s-]?\d)*", ten):
        d = re.sub(r"\D", "", m.group(0))
        if len(d) < 5:
            continue
        lop = lop_cua(*m.span(), d)
        man = [(m.start() + r.start(), m.start() + r.end(), r.group(0)) for r in re.finditer(r"\d+", m.group(0))]
        dai = [x for x in man if len(x[2]) >= 5]
        if lop is None and len(man) > 1 and dai:
            # cụm ghép từ nhiều mẩu ("Round 2 010825"): xét từng mẩu dài; cụm toàn
            # mẩu ngắn ("0900 111 222") thì giữ nguyên, vì đó là dạng số điện thoại
            for a, b, x in dai:
                yield lop_cua(a, b, x), x
            continue
        yield lop, d


def _dang_nhay_cam(d: str) -> str | None:
    """Hình dạng của một dãy số lạ, để người đọc biết cần soi gì."""
    if len(d) == 12:
        return "dang_cccd"
    if re.fullmatch(r"0\d{9,10}", d):
        return "dang_so_dien_thoai"
    if re.fullmatch(r"000\d{5}", d):
        return "dang_so_hoa_don_vat"
    if 13 <= len(d) <= 16:
        return "dang_so_tai_khoan"
    return None


# --------------------------------------------------------------------------
# Tóm tắt
# --------------------------------------------------------------------------

def tom_tat(so: list[dict], tai_lieu: list[dict], ten_tep: dict) -> dict:
    co_so = {l["doc_id"] for g in so for l in g["lan_xuat_hien"] if g["chuan"] != CHUA_CAP_SO}
    theo_nhom: dict[str, dict] = defaultdict(lambda: {"so_dong": 0, "_tl": set()})
    for g in so:
        n = theo_nhom[NHOM_LOAI.get(g["loai"], "khac")]
        n["so_dong"] += 1
        if g["chuan"] != CHUA_CAP_SO:
            n["_tl"].update(l["doc_id"] for l in g["lan_xuat_hien"])
    return {
        "so_tai_lieu": len(tai_lieu),
        "so_tai_lieu_co_so_hieu": len(co_so),
        "so_dong_so": len(so),
        "theo_bang": dict(Counter(g["bang"] for g in so)),
        "theo_loai": dict(sorted(Counter(g["loai"] for g in so).items())),
        "theo_nhom_loai": {k: {"so_dong": v["so_dong"], "so_tai_lieu": len(v["_tl"])}
                           for k, v in sorted(theo_nhom.items())},
        "so_dong_cho_xac_nhan_ho_so": sum(1 for g in so if g.get("xung_dot")),
        "theo_chu_so_huu": dict(Counter(f"{g['bang']}/{g['chu_so_huu']}" for g in so)),
        "hoa_don_chua_cap_so": sum(1 for g in so if g.get("chua_cap_so")),
        "ten_tep": {
            "so_tep": ten_tep["so_tep"],
            "so_tep_trong_ho_so": ten_tep["so_tep_trong_ho_so"],
            "tep_mang_so_nhay_cam": sum(1 for v in ten_tep["vi_pham"] if any(s["bang"] == NHAY_CAM for s in v["so"])),
            "tep_mang_so_nhay_cam_chua_chap_nhan": sum(
                1 for v in ten_tep["vi_pham"] if any(s["bang"] == NHAY_CAM and not s["da_chap_nhan"] for s in v["so"])),
            "tep_mang_so_chua_xep": sum(1 for v in ten_tep["vi_pham"] if any(s["bang"] == CHUA_XEP for s in v["so"])),
            "day_so_khong_giai_thich": len(ten_tep["khong_giai_thich"]),
            "khong_giai_thich_theo_dang": dict(Counter(k["dang"] or "khong_ro" for k in ten_tep["khong_giai_thich"])),
            "xep_loai_day_so": ten_tep["xep_loai_day_so"],
        },
    }


def _ghi_rieng(ra: Path, noi_dung: str) -> None:
    """Sổ chứa số nhạy cảm: tệp mang quyền 0600 ngay từ lúc tạo (thư mục mới
    0700), không có khoảnh khắc nào người khác đọc được; ghi tệp tạm rồi thay."""
    ra.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tam = ra.with_name(f".{ra.name}.{os.getpid()}.tmp")
    fd = os.open(tam, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(noi_dung)
        os.replace(tam, ra)
    except BaseException:
        tam.unlink(missing_ok=True)
        raise


def nap_chap_nhan(p: Path) -> tuple[dict | None, frozenset]:
    """Không có tệp quyết định thì không tên nào được chấp nhận."""
    if not p.exists():
        return None, frozenset()
    d = json.loads(p.read_text("utf-8"))
    return d.get("quyet_dinh"), frozenset(
        (unicodedata.normalize("NFC", t["tep"]), t["loai"], t["chuan"]) for t in d["tep"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ade-out", type=Path, default=KHO)
    ap.add_argument("--nguon", type=Path, default=NGUON)
    ap.add_argument("--danh-tinh", type=Path, default=DANH_TINH)
    ap.add_argument("--ra", type=Path, default=SO)
    ap.add_argument("--chap-nhan", type=Path, default=CHAP_NHAN)
    args = ap.parse_args(argv)

    if not args.danh_tinh.exists():
        ap.error(f"thiếu sổ danh tính {args.danh_tinh}: chạy scripts/so_danh_tinh.py trước")
    danh_tinh = nap_danh_tinh(args.danh_tinh)
    tai_lieu = nap_kho(args.ade_out)
    so = dung_so(tai_lieu, danh_tinh, _chu_hop_dong(args.ade_out))
    quyet_dinh, chap_nhan = nap_chap_nhan(args.chap_nhan)
    ten_tep = chung_minh_ten_tep(kiem_ke(args.nguon), so, chap_nhan, danh_tinh)
    ten_tep["chap_nhan"] = {"tep_quyet_dinh": str(args.chap_nhan), "quyet_dinh": quyet_dinh}
    doi_chung = {
        tl["nguon"]: bang_doi_chung(tl, so, danh_tinh)
        for tl in tai_lieu if re.search(r"doi chung", bo_dau(Path(tl["nguon"]).name), re.I)
    }
    ket = {
        "tao_luc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "kho_bang_chung": str(args.ade_out),
        "kho_goc": str(args.nguon),
        "so_danh_tinh": str(args.danh_tinh),
        "bang": {b: sorted(l for l, x in BANG_CUA_LOAI.items() if x == b) for b in (CONG_KHAI, NHAY_CAM, CHUA_XEP)},
        "quy_tac": {
            CONG_KHAI: "được phép lên tên tệp",
            NHAY_CAM: "cấm lên tên tệp",
            CHUA_XEP: "chưa thuộc bảng nào; cấm cho tới khi người xếp",
        },
        "tom_tat": tom_tat(so, tai_lieu, ten_tep),
        "so_hieu": so,
        "ten_tep": ten_tep,
        "bang_doi_chung": doi_chung,
    }
    _ghi_rieng(args.ra, json.dumps(ket, ensure_ascii=False, indent=2) + "\n")

    # Chỉ in số đếm: giá trị nhạy cảm chỉ nằm trong sổ riêng.
    t = ket["tom_tat"]
    print(f"so so hieu: {args.ra}")
    print(f"  tai lieu: {t['so_tai_lieu']}  co so hieu: {t['so_tai_lieu_co_so_hieu']}  dong so: {t['so_dong_so']}")
    print(f"  theo bang: {t['theo_bang']}")
    print(f"  ten tep: {t['ten_tep']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
