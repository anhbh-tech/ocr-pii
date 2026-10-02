#!/usr/bin/env python3
"""Sổ hợp đồng: gộp các bản sao của cùng một hợp đồng theo số ghi trong văn bản.

Một hợp đồng thường nằm rải rác trong nhiều tệp - bản dự thảo, bản scan, bản
hai bên đã ký, và thêm một bản nữa trong thư mục thanh toán. Bốn tên tệp khác
nhau không phải là bốn hợp đồng. Khoá duy nhất là dòng "Số:" (hoặc "No.:")
in trong chính văn bản, nên sổ này gom theo số đó và đếm mỗi hợp đồng một lần.

Ngày ký cũng lấy từ trong văn bản, không lấy từ đuôi ngày trên tên tệp: tên tệp
hay mang ngày scan hoặc ngày lưu, lệch với ngày ký thật.

Vai trò của đối tác quyết định chiều tiền, nên phải ghi lại: hợp đồng mà REFINY
đứng ở bên B thì đối tác là bên A - khách hàng, tiền vào; hợp đồng mà REFINY
đứng ở bên A thì đối tác là bên B - đại diện/cộng sự, tiền ra. Cổng "đã ký hợp
đồng với khách hàng" chỉ đếm loại thứ nhất.

Số hợp đồng là thông tin nhạy cảm: nó chỉ nằm trong sổ riêng dưới ~/.private/,
không được đưa vào tên tệp, vào tệp commit hay vào báo cáo công khai.

Không xoá, không đổi tên, không di chuyển gì trong kho gốc. Chỗ nào tên tệp sai
ngày thì ghi đề xuất sửa vào sổ để người quyết định.

    python3 scripts/so_hop_dong.py [--ade-out DIR] [--ra FILE] [--in-tom-tat]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict

ADE_OUT_MAC_DINH = os.path.expanduser("~/.private/ade_out")
SO_MAC_DINH = os.path.expanduser("~/.private/so/hop_dong.json")

# Chỉ đọc phần đầu văn bản: dòng số hợp đồng luôn nằm ngay dưới tiêu đề.
CUA_SO_TIEU_DE = 3000
# Phần thân dùng để đọc các bên; đủ dài để qua hết khối "BÊN A/BÊN B".
CUA_SO_CAC_BEN = 6000

TEN_HANG_CHUNG_TA = "REFINY"


# --------------------------------------------------------------------------
# Chuẩn hoá chữ
# --------------------------------------------------------------------------

def bo_dau(s: str) -> str:
    """Bỏ dấu tiếng Việt và hạ về chữ in, để so khớp được với bản OCR lỗi dấu."""
    s = s.replace("Đ", "D").replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().upper()


def go_dinh_dang(s: str) -> str:
    """Bỏ đậm/nghiêng markdown và dấu ngoặc bao quanh."""
    s = re.sub(r"[*_`]+", "", s)
    return s.strip().strip("()").strip()


def chuan_so_hop_dong(so: str) -> str:
    """Khoá gộp: bỏ dấu, thống nhất gạch ngang, bỏ khoảng trắng thừa."""
    so = go_dinh_dang(so)
    so = so.replace("–", "-").replace("—", "-").replace("−", "-")
    so = re.sub(r"\s*-\s*", "-", so)
    so = re.sub(r"\s*/\s*", "/", so)
    return bo_dau(so)


# --------------------------------------------------------------------------
# Nhận ra một văn bản có phải hợp đồng không
# --------------------------------------------------------------------------

# Tiêu đề hợp đồng sau khi bỏ dấu. "HỢP ĐỒNG", "HỌP ĐÔNG", "HOP DONG" đều về
# cùng một chuỗi, nên OCR sai dấu vẫn khớp.
DAU_HIEU_TIEU_DE = ("HOP DONG", "AGREEMENT", "CONTRACT")

# Dòng số: "Số: NH0000/2025/HD-SHTT" hoặc "(No.: NH0000.US - REFINY Law Firm)".
RE_SO_VN = re.compile(r"S[ốồôóòọ0o]\s*[:.]\s*(.+)", re.I)
RE_SO_EN = re.compile(r"No\.?\s*[:.]\s*(.+)", re.I)

# Số hợp đồng hợp lệ: có năm/loại (0000/2024/HĐ-SHTT) hoặc là mã vụ việc kèm tên
# hãng (NH0000.US - REFINY Law Firm).
RE_DANG_SO = re.compile(r"^[A-Z0-9][A-Z0-9./-]*\d")


# Biên bản thanh lý / bàn giao nhắc chữ "hợp đồng" nhưng không phải hợp đồng.
DAU_HIEU_KHONG_PHAI = ("BIEN BAN", "THANH LY", "BAN GIAO")

# Dòng ảnh/bảng chèn giữa văn bản, không phải tiêu đề.
RE_DONG_BO = re.compile(r"^[<|]")


def tim_tieu_de_hop_dong(markdown: str):
    """Tiêu đề hợp đồng đứng riêng một dòng ở ngay đầu văn bản."""
    dem = 0
    for raw in markdown[:CUA_SO_TIEU_DE].split("\n"):
        line = go_dinh_dang(raw)
        if not line or RE_DONG_BO.match(line):
            continue
        dem += 1
        if dem > 6:
            return None
        tn = bo_dau(line)
        if len(line) < 80 and ":" not in line and any(dh in tn for dh in DAU_HIEU_TIEU_DE):
            if any(kh in tn for kh in DAU_HIEU_KHONG_PHAI):
                return None
            return line
    return None


def tim_so_hop_dong(markdown: str):
    """Trả về (số thô, dòng tiêu đề) nếu văn bản này LÀ một hợp đồng."""
    dong = markdown[:CUA_SO_TIEU_DE].split("\n")
    for i, raw in enumerate(dong):
        line = go_dinh_dang(raw)
        if not line:
            continue
        m = RE_SO_VN.match(line) or RE_SO_EN.match(line)
        if not m:
            continue
        so = go_dinh_dang(m.group(1))
        if len(so) < 4 or not RE_DANG_SO.match(bo_dau(so)):
            continue
        # Tiêu đề phải nằm trong 3 dòng có chữ ngay trước dòng số. Cửa sổ hẹp
        # này loại được số công văn ("1656/NQ-UBTVQH15") và số tham chiếu trên
        # hoá đơn ("Our Ref: 8780/US/1"), vì chúng không có tiêu đề hợp đồng.
        truoc = []
        j = i - 1
        while j >= 0 and len(truoc) < 3:
            t = go_dinh_dang(dong[j])
            if t:
                truoc.append(t)
            j -= 1
        for t in truoc:
            tn = bo_dau(t)
            if any(dh in tn for dh in DAU_HIEU_TIEU_DE):
                return so, t
    return None, None


# --------------------------------------------------------------------------
# Ngày ký - lấy trong văn bản, không lấy trên tên tệp
# --------------------------------------------------------------------------

RE_NGAY_VN = re.compile(
    r"ng[aà]y\s*(\d{1,2})\s*th[aá]ng\s*(\d{1,2})\s*n[aă]m\s*(\d{4})", re.I
)
THANG_EN = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
RE_NGAY_EN = re.compile(
    r"\b([A-Z][a-z]{2,8})\s+(\d{1,2})(?:<sup>)?(?:st|nd|rd|th)?(?:</sup>)?\s*,?\s*(\d{4})"
)


def doc_ngay_ky(markdown: str):
    """(ngày ISO, trích dẫn) - ưu tiên câu có 'Ngày Ký'/'Signing Date'."""
    dau = markdown[:CUA_SO_CAC_BEN]
    phang = re.sub(r"\s+", " ", dau)

    uu_tien = []
    for m in re.finditer(r"(Ng[aà]y K[yý]|Ng[aà]y c[oó] hi[eệ]u l[uự]c"
        r"|(?:Signing|Effective)\s*\*{0,2}\s*Date)", phang, re.I):
        uu_tien.append(phang[max(0, m.start() - 220): m.start()])
    for doan in uu_tien + [phang]:
        m = RE_NGAY_VN.search(doan)
        if m:
            d, thg, n = (int(x) for x in m.groups())
            try:
                return dt.date(n, thg, d).isoformat(), m.group(0).strip()
            except ValueError:
                pass
        for m in RE_NGAY_EN.finditer(doan):
            thg = THANG_EN.get(bo_dau(m.group(1))[:3])
            if not thg:
                continue
            try:
                return dt.date(int(m.group(3)), thg, int(m.group(2))).isoformat(), m.group(0).strip()
            except ValueError:
                continue
    return None, None


# --------------------------------------------------------------------------
# Các bên - ai bán dịch vụ, ai mua dịch vụ
# --------------------------------------------------------------------------
#
# Ô A/B một mình KHÔNG nói được chiều tiền. Hợp đồng BQ093.US đặt hãng luật Hoa Kỳ
# (đại diện Hoa Kỳ) ở ô A và REFINY ở ô B, nhưng REFINY vẫn là bên trả tiền.
# Thứ quyết định chiều tiền là bên nào cung cấp dịch vụ: REFINY bán dịch vụ thì
# đối tác là khách hàng (tiền vào); REFINY mua dịch vụ thì đối tác là đại diện
# (tiền ra).

RE_DAU_KHOI_BEN = re.compile(
    r"^(?:\d+\s*[.)]\s*)?(?:(B[E\u00ca]N|PARTY)\s*([AB])\b\s*(?:\([^)]{0,40}\))?"
    r"|(B[E\u00ca]N\s+(?:S[\u1eec\u1ee8U]\s*D[\u1ee4U]NG|CUNG\s*C[\u1ea4A]P)\s+D[\u1ecaI]CH\s*V[\u1ee4U]))"
    r"\s*[:.]\s*(.*)$",
    re.I,
)
RE_GOI_LA_BEN = re.compile(r"g[\u1ecdo]i\s*l[\u00e0a]\s*[\u201c\"']?\s*B[\u00caE]N\s*([AB])", re.I)
RE_DONG_TRUONG = re.compile(r"^[^:]{1,40}:\s*$")

# Điều khoản chỉ ra ai cung cấp dịch vụ.
RE_CUNG_CAP_VN = re.compile(
    r"B[\u00eae]n\s*([AB])\b\s*(?:theo\s*\u0111\u00e2y\s*)?(?:\u0111\u00e3\s*)?"
    r"\u0111[\u1ed3o]ng\s*\u00fd\s*cung\s*c[\u1ea5a]p",
    re.I,
)
RE_CUNG_CAP_EN = re.compile(r"(?:agrees?|wishes)\s+(?:and\s+wishes\s+)?to\s+provide", re.I)
RE_NHAC_BEN_EN = re.compile(r"Party\s*([AB])\b", re.I)


def tu_dinh_danh(ten: str):
    """Từ đầu đủ dài trong tên một bên, dùng để nhận ra bên đó trong thân bài."""
    for tu in re.findall(r"[A-Z]+", bo_dau(ten)):
        if len(tu) >= 5:
            return tu
    return None


def doc_cac_khoi_ben(markdown: str) -> list:
    """Tách khối mở đầu thành các khối bên, mỗi khối là một ô trong hợp đồng."""
    dong = [go_dinh_dang(d) for d in markdown[:CUA_SO_CAC_BEN].split("\n")]
    dau = []
    for i, line in enumerate(dong):
        m = RE_DAU_KHOI_BEN.match(line)
        if m:
            dau.append((i, m))
    khoi = []
    for k, (i, m) in enumerate(dau):
        het = dau[k + 1][0] if k + 1 < len(dau) else len(dong)
        than = [d for d in dong[i + 1:het] if d]
        nhan = bo_dau(m.group(3) or "")
        ten = go_dinh_dang(m.group(4)).strip(' "\u201c\u201d')
        ten = re.sub(r"\s*\(.*$", "", ten).strip()
        if not ten:
            # Bản scan hay tách nhãn trường ra khỏi giá trị; lấy dòng đầu tiên
            # không phải nhãn trường và không phải chú thích "(Sau đây gọi là…)".
            for d in than:
                if RE_DONG_TRUONG.match(d) or d.startswith("("):
                    continue
                ten = d.strip(' "\u201c\u201d')
                break
        o = (m.group(2) or "").upper() or None
        if not o:
            g = RE_GOI_LA_BEN.search(" ".join([line] + than[:12]))
            if g:
                o = g.group(1).upper()
        khoi.append({
            "o": o,
            "ten": ten or None,
            "la_ben_cung_cap": "CUNG CAP" in nhan,
            "la_ben_su_dung": "SU DUNG" in nhan,
            # Chỉ soi tên và vài dòng địa chỉ ngay dưới: đọc cả khối sẽ chạm
            # vào phần "Xét rằng" bên dưới, chỗ tên cả hai bên đều xuất hiện.
            "co_refiny": TEN_HANG_CHUNG_TA in bo_dau(" ".join([ten or ""] + than[:3])),
        })
    return khoi


def tim_o_cung_cap(markdown: str, khoi: list):
    """Ô của bên cung cấp dịch vụ, kèm căn cứ đã dùng."""
    # 1. Nhãn tiếng Việt ghi thẳng trên khối bên.
    for k in khoi:
        if k["la_ben_cung_cap"] and k["o"]:
            return k["o"], "nhan_ben_cung_cap_dich_vu"
    for k in khoi:
        if k["la_ben_su_dung"] and k["o"]:
            return ("B" if k["o"] == "A" else "A"), "nhan_ben_su_dung_dich_vu"

    dau = re.sub(r"[*_`]+", "", re.sub(r"\s+", " ", markdown[:12000]))
    # 2. Điều khoản "Bên X … cung cấp dịch vụ".
    m = RE_CUNG_CAP_VN.search(dau)
    if m:
        return m.group(1).upper(), "dieu_khoan_cung_cap_dich_vu"
    # 3. Bản tiếng Anh: bên được nhắc gần nhất ngay trước "to provide".
    for m in RE_CUNG_CAP_EN.finditer(dau):
        truoc = dau[max(0, m.start() - 200): m.start()]
        gan_nhat, o_gan = -1, None
        for g in RE_NHAC_BEN_EN.finditer(truoc):
            if g.start() > gan_nhat:
                gan_nhat, o_gan = g.start(), g.group(1).upper()
        for k in khoi:
            if not k["ten"] or not k["o"]:
                continue
            tu_khoa = tu_dinh_danh(k["ten"])
            if not tu_khoa:
                continue
            vt = bo_dau(truoc).rfind(tu_khoa)
            if vt > gan_nhat:
                gan_nhat, o_gan = vt, k["o"]
        if o_gan:
            return o_gan, "cau_cung_cap_dich_vu_tieng_anh"
    return None, None


def phan_vai(markdown: str) -> dict:
    """Xác định đối tác và chiều tiền từ hướng cung cấp dịch vụ."""
    khoi = doc_cac_khoi_ben(markdown)
    ten_theo_o = {k["o"]: k["ten"] for k in khoi if k["o"]}
    chua_ro = {
        "o_cua_refiny": None, "o_cua_doi_tac": None, "ten_doi_tac": None,
        "o_cung_cap_dich_vu": None, "can_cu": None,
        "vai_tro_doi_tac": "khong_ro", "chieu_tien": None,
    }

    o_ta = [k["o"] for k in khoi if k["co_refiny"] and k["o"]]
    if len(set(o_ta)) != 1:
        # Không bên nào là REFINY: hợp đồng của bên thứ ba do khách gửi vào hồ
        # sơ. Không thuộc chiều tiền nào của hãng.
        if not o_ta and khoi:
            chua_ro["vai_tro_doi_tac"] = "ben_thu_ba"
        return chua_ro
    ta = o_ta[0]
    doi_tac = "B" if ta == "A" else "A"

    o_cung_cap, can_cu = tim_o_cung_cap(markdown, khoi)
    if not o_cung_cap:
        chua_ro["o_cua_refiny"] = ta
        chua_ro["o_cua_doi_tac"] = doi_tac
        chua_ro["ten_doi_tac"] = ten_theo_o.get(doi_tac)
        return chua_ro

    refiny_ban = o_cung_cap == ta
    return {
        "o_cua_refiny": ta,
        "o_cua_doi_tac": doi_tac,
        "ten_doi_tac": ten_theo_o.get(doi_tac),
        "o_cung_cap_dich_vu": o_cung_cap,
        "can_cu": can_cu,
        # REFINY bán dịch vụ => đối tác là khách hàng, tiền vào.
        # REFINY mua dịch vụ => đối tác là đại diện/cộng sự, tiền ra.
        "vai_tro_doi_tac": "khach_hang" if refiny_ban else "dai_dien",
        "chieu_tien": "doanh_thu" if refiny_ban else "chi_phi",
    }


# --------------------------------------------------------------------------
# Tên tệp: ngày ở đuôi tên và dấu hiệu bản dự thảo
# --------------------------------------------------------------------------

RE_NGAY_TEN_TEP = re.compile(r"_(\d{2})(\d{2})(\d{2})(?=[^0-9]|$)")
DAU_HIEU_DU_THAO = ("DU THAO", "DRAFT")


def ngay_tren_ten_tep(ten: str):
    """Đuôi _DDMMYY trên tên tệp -> ngày ISO, hoặc None."""
    goc = os.path.splitext(ten)[0]
    m = None
    for m in RE_NGAY_TEN_TEP.finditer(goc):
        pass  # lấy cụm cuối cùng: đó là chỗ quy ước đặt ngày
    if not m:
        return None
    d, thg, n = (int(x) for x in m.groups())
    try:
        return dt.date(2000 + n, thg, d).isoformat()
    except ValueError:
        return None


RE_MA_TREN_TEN_TEP = re.compile(r"^([A-Z]{0,3}\d{2,4})(?:\.[A-Z]{2})?[_.\s]")


def cung_ho_so(a: str, b: str) -> bool:
    """So hai mã hồ sơ theo phần số; tiền tố NH/BQ/TV chỉ là quy ước đặt tên."""
    sa, sb = re.sub(r"\D", "", a).lstrip("0"), re.sub(r"\D", "", b).lstrip("0")
    return sa == sb


def ma_ho_so_tren_ten_tep(ten: str):
    """Mã hồ sơ mà tên tệp tự nhận, để đối chiếu với số in trong văn bản."""
    m = RE_MA_TREN_TEN_TEP.match(ten.strip())
    return m.group(1).upper() if m else None


def la_du_thao(duong_dan: str) -> bool:
    n = bo_dau(duong_dan)
    return any(dh in n for dh in DAU_HIEU_DU_THAO)


def de_xuat_ten_moi(ten: str, ngay_ky: str):
    """Tên tệp đề xuất khi đuôi ngày lệch ngày ký. Không đổi gì trên đĩa."""
    goc, duoi = os.path.splitext(ten)
    d = dt.date.fromisoformat(ngay_ky)
    moi = d.strftime("%d%m%y")
    vi_tri = None
    for m in RE_NGAY_TEN_TEP.finditer(goc):
        vi_tri = m
    if not vi_tri:
        return None
    return goc[: vi_tri.start(1)] + moi + goc[vi_tri.end(3):] + duoi


# --------------------------------------------------------------------------
# Loại văn bản và mã hồ sơ đọc từ chính số hợp đồng
# --------------------------------------------------------------------------

# "PHỤ LỤC HỢP ĐỒNG DÀNH CHO VỤ VIỆC / Số: PL01/NH0000.US/2026" là văn bản sửa
# đổi một hợp đồng đã có, không phải một hợp đồng mới, nên đếm riêng.
RE_HOP_DONG_ME = re.compile(
    r"H[\u1ee3o]p\s*\u0111[\u1ed3o]ng[^\n]{0,80}?s[\u1ed1o]\s+([^\s,]{4,40})", re.I
)
RE_MA_HO_SO = re.compile(r"^([A-Z]{0,3}\d{2,4})(?:\.[A-Z]{2})?$", re.I)


def doc_loai(so: str, tieu_de: str) -> str:
    if "PHU LUC" in bo_dau(tieu_de or "") or bo_dau(so).startswith("PL"):
        return "phu_luc"
    return "hop_dong"


def doc_hop_dong_me(markdown: str):
    """Phụ lục nào cũng dẫn số hợp đồng gốc ngay dưới tiêu đề."""
    m = RE_HOP_DONG_ME.search(re.sub(r"\s+", " ", markdown[:1800]))
    return chuan_so_hop_dong(m.group(1)) if m else None


def doc_ma_ho_so(so: str, loai: str):
    """Mã hồ sơ nằm trong chính số hợp đồng: NH0000/2025/HD-SHTT -> NH0000."""
    phan = [p for p in re.split(r"[/\s-]+", chuan_so_hop_dong(so)) if p]
    if loai == "phu_luc":
        phan = phan[1:]  # bỏ "PL01", lấy mã hợp đồng gốc
    for p in phan:
        m = RE_MA_HO_SO.match(p)
        if m and not re.fullmatch(r"(19|20)\d{2}", m.group(1)):
            return m.group(1).upper()
    return None


# --------------------------------------------------------------------------
# Vụ việc: thư mục hồ sơ chứa tệp
# --------------------------------------------------------------------------

RE_VU_VIEC = re.compile(r"^(\d{2,4})\s*\.?\s*(US|VN)?", re.I)


def doc_vu_viec(source: str):
    """Mã vụ việc suy từ tên thư mục hồ sơ, ví dụ '901.US. ZORBLAX in Class 025'."""
    for phan in source.split("/"):
        m = RE_VU_VIEC.match(phan.strip())
        if m:
            so = m.group(1)
            hau_to = (m.group(2) or "").upper()
            return f"{so}.{hau_to}" if hau_to else so
    return None


# --------------------------------------------------------------------------
# Đọc kho bằng chứng
# --------------------------------------------------------------------------

def doc_ban_ghi(thu_muc: str):
    """Sinh (nguồn, engine, markdown). Ưu tiên ADE Pro, có bản thường thì đọc cả."""
    for ten_meta, ten_parse, engine in (
        ("meta_pro.json", "parse_pro.json", "pro"),
        ("meta.json", "parse.json", "chuan"),
    ):
        p_meta = os.path.join(thu_muc, ten_meta)
        p_parse = os.path.join(thu_muc, ten_parse)
        if not (os.path.exists(p_meta) and os.path.exists(p_parse)):
            continue
        try:
            meta = json.load(open(p_meta, encoding="utf-8"))
            parse = json.load(open(p_parse, encoding="utf-8"))
        except (ValueError, OSError):
            continue
        yield meta.get("source", ""), engine, parse.get("markdown", "") or ""


def quet(ade_out: str):
    """Mỗi tệp gốc -> một bản trích hợp đồng (nếu có), gộp hai engine."""
    tai_lieu = []
    for ma in sorted(os.listdir(ade_out)):
        thu_muc = os.path.join(ade_out, ma)
        if not os.path.isdir(thu_muc):
            continue
        tot = None
        for source, engine, md in doc_ban_ghi(thu_muc):
            so, tieu_de = tim_so_hop_dong(md)
            thieu_so = False
            if not so:
                # Vài hợp đồng với đại diện nước ngoài không in số nào cả. Bỏ
                # qua chúng thì phía chi phí bị hụt, nên vẫn nhận và đánh dấu
                # để người xem lại; khoá thay thế dựng từ hồ sơ và ngày ký.
                tieu_de = tim_tieu_de_hop_dong(md)
                if not tieu_de or len(doc_cac_khoi_ben(md)) < 2:
                    continue
                thieu_so = True
                so = None
            ngay, trich = doc_ngay_ky(md)
            vai = phan_vai(md)
            loai = doc_loai(so or "", tieu_de)
            if thieu_so:
                ma = ma_ho_so_tren_ten_tep(os.path.basename(source)) or "?"
                khoa = f"KHONG-GHI-SO/{ma}/{ngay or '?'}"
            else:
                khoa = chuan_so_hop_dong(so)
            diem = (1 if ngay else 0) + (1 if vai["ten_doi_tac"] else 0)
            if tot is None or diem > tot["_diem"]:
                tot = {
                    "_diem": diem,
                    "ade_id": ma,
                    "engine": engine,
                    "source": source,
                    "so_tho": so,
                    "khoa": khoa,
                    "thieu_so": thieu_so,
                    "tieu_de": tieu_de,
                    "loai": loai,
                    "hop_dong_me": doc_hop_dong_me(md) if loai == "phu_luc" else None,
                    "ngay_ky": ngay,
                    "trich_ngay": trich,
                    "vai": vai,
                }
        if tot:
            tot.pop("_diem")
            tai_lieu.append(tot)
    return tai_lieu


# --------------------------------------------------------------------------
# Gộp thành sổ
# --------------------------------------------------------------------------

def gan_ban_mat_so(tai_lieu: list) -> int:
    """Bản sao bị OCR nuốt mất dòng số vẫn là bản sao của hợp đồng đã có số.

    Ghép nó vào hợp đồng cùng hồ sơ, cùng loại, cùng ngày ký - nếu để riêng
    thì chính nó thành một hợp đồng thứ hai, đúng cái đếm trùng cần bỏ.
    """
    co_so = [t for t in tai_lieu if not t["thieu_so"]]
    da_ghep = 0
    for t in tai_lieu:
        if not t["thieu_so"]:
            continue
        ma = ma_ho_so_tren_ten_tep(os.path.basename(t["source"]))
        if not ma or not t["ngay_ky"]:
            continue
        for u in co_so:
            ma_u = doc_ma_ho_so(u["so_tho"], u["loai"])
            if not ma_u or not cung_ho_so(ma, ma_u):
                continue
            if u["loai"] != t["loai"] or u["ngay_ky"] != t["ngay_ky"]:
                continue
            vai_t, vai_u = t["vai"]["vai_tro_doi_tac"], u["vai"]["vai_tro_doi_tac"]
            if vai_t != vai_u and "khong_ro" not in (vai_t, vai_u):
                continue
            t["khoa"] = u["khoa"]
            t["so_tho"] = u["so_tho"]
            t["thieu_so"] = False
            t["mat_so_do_ocr"] = True
            da_ghep += 1
            break
    return da_ghep


def gop(tai_lieu: list) -> list:
    nhom = defaultdict(list)
    for t in tai_lieu:
        nhom[t["khoa"]].append(t)

    ban_ghi = []
    for khoa, ds in sorted(nhom.items()):
        ds.sort(key=lambda t: t["source"])
        canh_bao = []
        loai = max({t["loai"] for t in ds}, key=lambda l: sum(1 for t in ds if t["loai"] == l))

        # Ngày ký: lấy ngày mà phần lớn bản sao đồng ý.
        cac_ngay = [t["ngay_ky"] for t in ds if t["ngay_ky"]]
        ngay_ky = max(set(cac_ngay), key=cac_ngay.count) if cac_ngay else None
        if not ngay_ky:
            canh_bao.append("khong_doc_duoc_ngay_ky_trong_van_ban")
        elif len(set(cac_ngay)) > 1:
            canh_bao.append("cac_ban_sao_ghi_ngay_ky_khac_nhau: " + ", ".join(sorted(set(cac_ngay))))

        # Vai trò: các bản sao của cùng hợp đồng phải cho cùng một chiều tiền.
        vai = next((t["vai"] for t in ds if t["vai"]["chieu_tien"]), ds[0]["vai"])
        chieu = {t["vai"]["chieu_tien"] for t in ds if t["vai"]["chieu_tien"]}
        if len(chieu) > 1:
            canh_bao.append("cac_ban_sao_cho_chieu_tien_khac_nhau: " + ", ".join(sorted(chieu)))
        if vai["vai_tro_doi_tac"] == "khong_ro":
            canh_bao.append("khong_doc_duoc_ben_nao_cung_cap_dich_vu")
        elif vai["vai_tro_doi_tac"] == "ben_thu_ba":
            canh_bao.append("hop_dong_cua_ben_thu_ba_khong_co_refiny")

        thieu_so = all(t["thieu_so"] for t in ds)
        if thieu_so:
            canh_bao.append("van_ban_khong_ghi_so_hop_dong - khoa tam theo ho so va ngay ky")
        ma_ho_so = None
        if vai["vai_tro_doi_tac"] != "ben_thu_ba":
            ma_ho_so = (ma_ho_so_tren_ten_tep(os.path.basename(ds[0]["source"]))
                        if thieu_so else doc_ma_ho_so(ds[0]["so_tho"], loai))
        thu_muc = sorted({doc_vu_viec(t["source"]) for t in ds if doc_vu_viec(t["source"])})
        if len(thu_muc) > 1:
            canh_bao.append(
                "cac_ban_sao_nam_o_nhieu_thu_muc_ho_so: " + ", ".join(thu_muc)
                + " - so trong van ban co the bi chep nham tu mau, can nguoi xem lai"
            )

        me = {t["hop_dong_me"] for t in ds if t.get("hop_dong_me")}
        hop_dong_me = sorted(me)[0] if me else None

        tep = []
        for t in ds:
            ten = os.path.basename(t["source"])
            ngay_ten = ngay_tren_ten_tep(ten)
            lech = bool(ngay_ky and ngay_ten and ngay_ten != ngay_ky)
            muc = {
                "duong_dan": t["source"],
                "ade_id": t["ade_id"],
                "engine": t["engine"],
                "la_du_thao": la_du_thao(t["source"]),
                "ngay_tren_ten_tep": ngay_ten,
                "ngay_ten_tep_lech_ngay_ky": lech,
            }
            if t.get("mat_so_do_ocr"):
                muc["ban_sao_khong_doc_duoc_so"] = True
            if lech:
                moi = de_xuat_ten_moi(ten, ngay_ky)
                if moi and moi != ten:
                    # Chỉ là đề xuất; kho gốc không bị đụng tới.
                    muc["de_xuat_ten_theo_ngay_ky"] = moi
            ma_tren_ten = ma_ho_so_tren_ten_tep(ten)
            if ma_ho_so and ma_tren_ten and not cung_ho_so(ma_tren_ten, ma_ho_so):
                muc["ma_ho_so_tren_ten_tep"] = ma_tren_ten
                muc["ten_tep_khac_ma_trong_van_ban"] = True
                canh_bao.append(f"ten_tep_ghi_ma_ho_so_khac_van_ban: {ten}")
            tep.append(muc)

        ban_ghi.append({
            "so_hop_dong": ds[0]["so_tho"],
            "khoa": khoa,
            "co_so_trong_van_ban": not thieu_so,
            "loai": loai,
            "hop_dong_me": hop_dong_me,
            "ma_ho_so": ma_ho_so,
            "thu_muc_ho_so": thu_muc,
            "ngay_ky": ngay_ky,
            "nguon_ngay_ky": "trong_van_ban" if ngay_ky else None,
            "doi_tac": {
                "ten": vai["ten_doi_tac"],
                "o": vai["o_cua_doi_tac"],
                "o_cung_cap_dich_vu": vai["o_cung_cap_dich_vu"],
                "can_cu_vai_tro": vai["can_cu"],
                "vai_tro": vai["vai_tro_doi_tac"],
                "chieu_tien": vai["chieu_tien"],
            },
            "da_ky": any(not t["la_du_thao"] for t in tep),
            "so_tep": len(tep),
            "tep": tep,
            "canh_bao": canh_bao,
        })
    return ban_ghi


def canh_bao_ban_khong_so_trung_nhau(ban_ghi: list) -> None:
    """Hai bản không ghi số, cùng đối tác, cùng ngày ký rất có thể là một.

    Không tự gộp: tên tệp của chúng ghi mã hồ sơ khác nhau, nên việc đó là
    quyết định của người, không phải của script.
    """
    theo_cap = defaultdict(list)
    for r in ban_ghi:
        if r["co_so_trong_van_ban"] or not r["ngay_ky"]:
            continue
        theo_cap[(r["doi_tac"]["ten"], r["ngay_ky"])].append(r)
    for ds in theo_cap.values():
        if len(ds) < 2:
            continue
        ma = ", ".join(sorted(str(r["ma_ho_so"]) for r in ds))
        for r in ds:
            r["canh_bao"].append(
                "cac_ban_khong_so_cung_doi_tac_cung_ngay_ky: " + ma
                + " - co the la mot hop dong, can nguoi xem lai"
            )


def tom_tat(ban_ghi: list) -> dict:
    # "Trước": sổ cũ đếm mỗi tệp hợp đồng là một hợp đồng, gom theo thư mục hồ
    # sơ. "Sau": gom theo số in trong văn bản.
    truoc = defaultdict(int)
    sau = defaultdict(set)
    for r in ban_ghi:
        for t in r["tep"]:
            v = doc_vu_viec(t["duong_dan"]) or "khong_ro"
            truoc[v] += 1
            sau[v].add(r["khoa"])
    trung = {v: (n, len(sau[v])) for v, n in truoc.items() if n > len(sau[v])}

    hd = [r for r in ban_ghi if r["loai"] == "hop_dong"]
    cong_khach = sorted({
        r["ma_ho_so"] for r in hd
        if r["doi_tac"]["vai_tro"] == "khach_hang" and r["da_ky"] and r["ma_ho_so"]
    })
    return {
        "so_tep_hop_dong": sum(r["so_tep"] for r in ban_ghi),
        "so_hop_dong": len(hd),
        "so_phu_luc": sum(1 for r in ban_ghi if r["loai"] == "phu_luc"),
        "so_ho_so_co_hop_dong": len(truoc),
        "ho_so_bi_dem_trung_truoc_khi_gop": len(trung),
        "ho_so_bi_dem_trung_sau_khi_gop": 0,
        "chi_tiet_dem_trung": {
            v: {"tep_hop_dong": a, "hop_dong_that": b} for v, (a, b) in sorted(trung.items())
        },
        "cong_da_ky_hop_dong_voi_khach_hang": {
            "so_ho_so": len(cong_khach), "ho_so": cong_khach,
        },
        "phan_theo_chieu_tien": {
            "doanh_thu_khach_hang": sum(1 for r in hd if r["doi_tac"]["chieu_tien"] == "doanh_thu"),
            "chi_phi_dai_dien": sum(1 for r in hd if r["doi_tac"]["chieu_tien"] == "chi_phi"),
            "khong_tinh_chieu_tien": sum(1 for r in hd if not r["doi_tac"]["chieu_tien"]),
        },
        "so_tep_co_de_xuat_ten_theo_ngay_ky": sum(
            1 for r in ban_ghi for t in r["tep"] if t["ngay_ten_tep_lech_ngay_ky"]
        ),
        "so_tep_ten_khac_ma_ho_so": sum(
            1 for r in ban_ghi for t in r["tep"] if t.get("ten_tep_khac_ma_trong_van_ban")
        ),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ade-out", default=ADE_OUT_MAC_DINH, help="kho bằng chứng đã parse")
    ap.add_argument("--ra", default=SO_MAC_DINH, help="tệp sổ hợp đồng (JSON)")
    ap.add_argument("--in-tom-tat", action="store_true", help="in tóm tắt ra stdout")
    args = ap.parse_args(argv)

    ade_out = os.path.expanduser(args.ade_out)
    if not os.path.isdir(ade_out):
        print(f"khong thay kho bang chung: {ade_out}", file=sys.stderr)
        return 2

    tai_lieu = quet(ade_out)
    gan_ban_mat_so(tai_lieu)
    hop_dong = gop(tai_lieu)
    canh_bao_ban_khong_so_trung_nhau(hop_dong)
    so = {
        "tao_luc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "kho_bang_chung": ade_out,
        "quy_tac": "khoa theo so ghi trong van ban; ngay ky lay trong van ban; moi hop dong dem mot lan",
        "luu_y": (
            "de_xuat_ten_theo_ngay_ky chi la de xuat, chua doi gi tren dia. Ngay tren "
            "ten tep nhieu khi la ngay scan hoac ngay ban giao chu khong phai ngay ky "
            "sai; nguoi phai xac nhan tung tep truoc khi doi ten."
        ),
        "tom_tat": tom_tat(hop_dong),
        "hop_dong": hop_dong,
    }

    ra = os.path.expanduser(args.ra)
    os.makedirs(os.path.dirname(ra), exist_ok=True)
    with open(ra, "w", encoding="utf-8") as f:
        json.dump(so, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.chmod(ra, 0o600)

    t = so["tom_tat"]
    print(f"so hop dong: {ra}")
    print(f"  tep hop dong: {t['so_tep_hop_dong']} -> hop dong: {t['so_hop_dong']}")
    print(f"  ho so dem trung truoc: {t['ho_so_bi_dem_trung_truoc_khi_gop']}"
          f"  sau: {t['ho_so_bi_dem_trung_sau_khi_gop']}")
    print(f"  cong da ky hop dong voi khach hang: {t['cong_da_ky_hop_dong_voi_khach_hang']['so_ho_so']} ho so")
    if args.in_tom_tat:
        # Không in số hợp đồng: đó là thông tin nhạy cảm, chỉ nằm trong sổ riêng.
        for hd in hop_dong:
            print(f"  {hd['loai']:9s} {hd['ma_ho_so'] or '?':8s} {hd['ngay_ky'] or '?':10s} "
                  f"{hd['doi_tac']['vai_tro']:12s} {hd['so_tep']} tep"
                  + ("  canh_bao: " + "; ".join(hd["canh_bao"]) if hd["canh_bao"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
