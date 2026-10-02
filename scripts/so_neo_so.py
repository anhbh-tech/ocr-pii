#!/usr/bin/env python3
"""Sổ neo số: nối số trong tệp hội thoại về hồ sơ — số trước, chữ sau.

OCR phá dấu tiếng Việt trong ảnh chụp chat ("sản phẩm" → "sän phấm", "đăng
ký" → "dăng ký"), nên so chuỗi CÓ DẤU trượt gần hết; chữ số thì sống sót. Ba
bước, đúng thứ tự:

  1. Bóc số trước, không cần nhãn đứng trước: dãy 8 chữ số (số đơn USPTO),
     dãy 7 chữ số hoặc `d,ddd,ddd` (số văn bằng), và `0NN` trong 001–045
     (nhóm Nice).
  2. So số với sổ trước khi so chữ. Số 7–8 chữ số so với sổ số hiệu
     (`so_so_hieu.py` → so_hieu.json); nhóm Nice so với nhóm trên tên thư
     mục hồ sơ của tệp (sổ danh tính), hoặc đi theo số văn bằng/số đơn đứng
     trước nó trên cùng dòng (nhóm của nhãn đối chứng).
  3. Chỉ khi buộc phải so chữ — xếp loại số không có trong sổ, gạt dãy
     "U.S. Class" khỏi nhóm Nice — thì bỏ dấu CẢ HAI phía rồi mới so.

Tệp hội thoại không tự suy lại: là hợp các sổ đã có — sổ kênh
(`kenh/hoi_thoai`), khung chat của sổ hình thức (trừ tệp `tron`, vd. thông báo
USPTO dài có kẹp một ảnh chat), vai `anh_hoi_thoai` của sổ vai ảnh, và bản
ảnh chụp trong cặp `anh_chup_chat` của sổ bản sạch. Mỗi tệp đọc MỌI bản parse
có (pro2, pro, chuẩn): bản chuẩn là bản hỏng dấu, và chính nó là chỗ chứng
minh chữ có dấu trượt mà số vẫn nối được (`chung_minh`).

Bảng: chỉ số nối được vào bảng CÔNG KHAI của sổ số hiệu mới mang giá trị. Số
trùng dòng nhạy cảm/chưa xếp chỉ được đếm. Số không có trong sổ chỉ mang giá
trị khi nhãn (đã bỏ dấu) ngay trước nó nói đó là số USPTO; không thì chỉ ghi
hình dạng và vị trí — dãy 7–8 chữ số trơn có thể là mẩu số điện thoại hay số
tài khoản.

Sổ ghi ra ~/.private/so/neo_so.json (0600), ngoài mọi cây git. Chỉ in số
đếm; không đổi gì trong kho gốc hay các sổ đầu vào.

    python3 scripts/so_neo_so.py [--ade-out DIR] [--so DIR] [--ra FILE]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import so_so_hieu as ssh  # noqa: E402

KHO = Path.home() / ".private" / "ade_out"
SO_DIR = Path.home() / ".private" / "so"
RA = SO_DIR / "neo_so.json"

bo_dau = ssh.bo_dau
nfc = ssh.nfc

SO_DON = "so_don"
SO_VAN_BANG = "so_van_bang"
NHOM_NICE = "nhom_nice"

# Loại trong sổ số hiệu mà mỗi hình dạng được phép nối vào.
LOAI_SO_HIEU = {SO_DON: "so_don_uspto", SO_VAN_BANG: "so_van_bang_uspto"}

# Bản parse, từ sạch tới hỏng dấu: bản đứng trước là bản gốc khi chứng minh.
BIEN_THE = (("pro2", "parse_pro2.json"), ("pro", "parse_pro.json"), ("chuan", "parse.json"))
META = ("meta_pro2.json", "meta_pro.json", "meta.json")


# --------------------------------------------------------------------------
# Bước 1: bóc số, không nhìn nhãn
# --------------------------------------------------------------------------

# Chặn hai phía bằng chữ-số và các dấu nối: dãy nằm trong URL, mã hex hay
# `doc_id=parse-01m2...` không phải số hiệu; `số 7654320,` (phẩy rồi cách) là.
_SO = re.compile(r"(?<![\w,./=:-])(\d{8}|\d{7}|\d,\d{3},\d{3})(?!\w|[,./:-]\d)")
_NICE = re.compile(r"(?<![\w,./=:-])(0(?:0[1-9]|[1-3]\d|4[0-5]))(?!\w|[,./:-]\d)")


def boc_so(md: str) -> list[dict]:
    """Mọi số 7–8 chữ số và nhóm Nice trong một bản parse, theo dòng."""
    ra = []
    for i, tho in enumerate(md.split("\n")):
        dong = ssh.phang(tho)
        if not dong:
            continue
        for m in _SO.finditer(dong):
            v = re.sub(r"\D", "", m.group(1))
            ra.append({"hinh": SO_DON if len(v) == 8 else SO_VAN_BANG, "gia_tri": v,
                       "dong": i + 1, "vi_tri": m.start(1), "trich": dong})
        nhan = _nhan_lop(dong)
        for m in _NICE.finditer(dong):
            if _la_lop_hoa_ky(nhan, m.start(1)):
                continue
            ra.append({"hinh": NHOM_NICE, "gia_tri": m.group(1),
                       "dong": i + 1, "vi_tri": m.start(1), "trich": dong})
    return ra


# --------------------------------------------------------------------------
# Bước 3: so chữ — luôn bỏ dấu cả hai phía
# --------------------------------------------------------------------------

def chuan_chu(s: str) -> str:
    """Chữ để so: bỏ dấu, bỏ dấu câu, gộp khoảng trắng. Áp cho CẢ HAI phía."""
    return re.sub(r"[^0-9A-Z]+", " ", bo_dau(s)).strip()


def co_chua(kim: str, rom: str) -> bool:
    """`kim` có nằm trong `rom` không, sau khi bỏ dấu cả hai."""
    k = chuan_chu(kim)
    return bool(k) and f" {k} " in f" {chuan_chu(rom)} "


# Bản in TSDR ghi "U.S. Class(es): 002, 027" cạnh "International Class(es): 014";
# dãy sau nhãn Hoa Kỳ không phải nhóm Nice. Nhãn tìm trên chữ đã bỏ dấu nhưng
# giữ nguyên độ dài, để vị trí khớp lại được với dòng gốc.
_NHAN_LOP = re.compile(r"U\.?\s?S\.?\s*CLASS|INTERNATIONAL\s*CLASS|\bCLASS\b|\bNHOM\b")


def _nhan_lop(dong: str) -> list[tuple[int, bool]]:
    return [(m.start(), m.group(0).startswith("U")) for m in _NHAN_LOP.finditer(ssh._bo_dau_giu_vi_tri(dong))]


def _la_lop_hoa_ky(nhan: list[tuple[int, bool]], vi_tri: int) -> bool:
    truoc = [hk for p, hk in nhan if p < vi_tri]
    return bool(truoc) and truoc[-1]


# Nhãn nói một số là số USPTO, dù số đó không có trong sổ. So sau khi bỏ dấu.
NHAN_SO_HIEU = {
    SO_DON: ("SERIAL", "APPLICATION NO", "APPLICATION NUMBER", "SO DON", "DON DANG KY SO"),
    SO_VAN_BANG: ("REGISTRATION", "REG NO", "VAN BANG"),
}


# "International Registration", "Foreign registration number": số đăng ký quốc
# tế / nước ngoài, không phải văn bằng USPTO.
_TIEN_TO_KHAC = ("INTERNATIONAL", "FOREIGN")


def nhan_truoc(trich: str, vi_tri: int, hinh: str) -> str | None:
    """Nhãn USPTO trong 40 ký tự ngay trước số, hoặc None."""
    truoc = trich[max(0, vi_tri - 40):vi_tri]
    return next((n for n in NHAN_SO_HIEU[hinh] if co_chua(n, truoc)
                 and not any(co_chua(f"{t} {n}", truoc) for t in _TIEN_TO_KHAC)), None)


# --------------------------------------------------------------------------
# Tệp hội thoại (hợp các sổ đã có)
# --------------------------------------------------------------------------

def _doc_json(p: Path):
    return json.loads(p.read_text("utf-8")) if p.exists() else None


def tep_hoi_thoai(so_dir: Path) -> tuple[dict[str, list[str]], dict[str, bool]]:
    """doc_id -> các sổ nhận nó là hội thoại; kèm sổ nào có mặt."""
    ra: dict[str, set[str]] = {}

    def them(doc_id: str | None, nguon: str) -> None:
        if doc_id:
            ra.setdefault(doc_id, set()).add(nguon)

    kenh = sorted((so_dir / "kenh" / "hoi_thoai").glob("*.json"))
    for p in kenh:
        for tin in json.loads(p.read_text("utf-8")).get("tin", []):
            them(tin.get("doc_id"), "so_kenh")
            for b in tin.get("ban_trung", []):
                them(b.get("doc_id"), "so_kenh")

    hinh_thuc = _doc_json(so_dir / "hinh_thuc.json")
    for x in (hinh_thuc or {}).get("tai_lieu", []):
        th = x.get("tin_hieu") or {}
        if th.get("khung_chat") and th.get("cau_truc") != "tron":
            them(x.get("id"), "hinh_thuc_khung_chat")

    vai_anh = _doc_json(so_dir / "vai_anh.json")
    for x in (vai_anh or {}).get("tai_lieu", []):
        if x.get("vai") == "anh_hoi_thoai":
            them(x.get("id"), "vai_anh_hoi_thoai")

    ban_sach = _doc_json(so_dir / "ban_sach_vs_anh.json")
    for c in (ban_sach or {}).get("cap_ban_sach", []):
        if c.get("quan_he") == "anh_chup_chat":
            for n in c.get("nguon", []):
                if n.get("vai_tro") == "anh_chup":
                    them(n.get("doc_id"), "ban_sach_anh_chup_chat")

    co_mat = {"so_kenh": bool(kenh), "hinh_thuc": hinh_thuc is not None,
              "vai_anh": vai_anh is not None, "ban_sach_vs_anh": ban_sach is not None}
    return {d: sorted(n) for d, n in sorted(ra.items())}, co_mat


def nap_ban_parse(kho: Path, doc_id: str) -> tuple[str | None, dict[str, str]]:
    """(đường dẫn nguồn NFC, {tên bản: markdown}) — mọi bản có, sạch trước."""
    thu_muc = kho / doc_id
    nguon = None
    for m in META:
        meta = _doc_json(thu_muc / m)
        if meta and meta.get("source"):
            nguon = nfc(meta["source"])
            break
    ban = {}
    for ten, tep in BIEN_THE:
        d = _doc_json(thu_muc / tep)
        if d is not None:
            ban[ten] = d.get("markdown") or ""
    return nguon, ban


# --------------------------------------------------------------------------
# Bước 2: so số với sổ
# --------------------------------------------------------------------------

_LOP_THU_MUC = re.compile(r"\bclass(?:es)?\s*((?:\d{1,3}\s*(?:,|&|and|va|\s)\s*)*\d{1,3})\b", re.I)


def lop_cua_ho_so(thu_muc: str | None) -> set[str]:
    """'901. US. X IN CLASS 016' -> {'016'}; 'in class 9, 16' -> {'009', '016'}."""
    m = _LOP_THU_MUC.search(bo_dau(thu_muc or ""))
    return {f"{int(x):03d}" for x in re.findall(r"\d{1,3}", m.group(1))} if m else set()


def chi_muc_so_hieu(so_hieu: list[dict]) -> dict[str, list[dict]]:
    ra: dict[str, list[dict]] = {}
    for g in so_hieu:
        ra.setdefault(g["chuan"], []).append(g)
    return ra


def _hamming_1(a: str, b: str) -> bool:
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1


def noi_so(doc_id: str, hinh: str, v: str, chi_muc: dict[str, list[dict]],
           hoi_thoai: set[str], ho_so_tep: set[str]) -> dict:
    """Một số 7–8 chữ số -> kết quả so với sổ số hiệu.

    `da_noi`: có dòng CÔNG KHAI đúng loại. `bi_giu`: chỉ trùng dòng không công
    khai — không ghi giá trị. `nghi_hong_ocr`: không có trong sổ nhưng lệch
    đúng một chữ số với một số công khai cùng hồ sơ (OCR đọc nhầm chữ số)."""
    dong = chi_muc.get(v, [])
    cong_khai = [g for g in dong if g["bang"] == ssh.CONG_KHAI and g["loai"] == LOAI_SO_HIEU[hinh]]
    if cong_khai:
        return {"ket_qua": "da_noi", "noi": [_noi_ho_so(g, doc_id, hoi_thoai, ho_so_tep) for g in cong_khai]}
    if dong:
        return {"ket_qua": "bi_giu", "bang": sorted({g["bang"] for g in dong})}
    gan = sorted({(k, g["ho_so"]) for k, gs in chi_muc.items() for g in gs
                  if g["bang"] == ssh.CONG_KHAI and g["loai"] == LOAI_SO_HIEU[hinh]
                  and g["ho_so"] in ho_so_tep and _hamming_1(k, v)})
    if len({k for k, _ in gan}) == 1:
        return {"ket_qua": "nghi_hong_ocr", "gan_voi": gan[0][0], "ho_so": sorted({h for _, h in gan})}
    return {"ket_qua": "chua_noi"}


def _noi_ho_so(g: dict, doc_id: str, hoi_thoai: set[str], ho_so_tep: set[str]) -> dict:
    """Một dòng sổ số hiệu -> hồ sơ và các tệp hồ sơ in số đó."""
    lan = [l for l in g["lan_xuat_hien"] if l["doc_id"] != doc_id]
    return {
        "ho_so": g["ho_so"], "ma_ho_so": g.get("ma_ho_so"), "loai": g["loai"],
        "chu_so_huu": g.get("chu_so_huu"), "nhan_hieu": g.get("nhan_hieu"),
        "cung_ho_so_voi_tep": g["ho_so"] in ho_so_tep,
        "tep_ho_so": sorted({l["tep"] for l in lan if l["doc_id"] not in hoi_thoai}),
        "tep_hoi_thoai_khac": sorted({l["tep"] for l in lan if l["doc_id"] in hoi_thoai}),
    }


def noi_nhom(v: str, dong: int, vi_tri: int, lop_ho_so: dict[str, set[str]],
             so_tren_dong: list[tuple[int, dict]]) -> dict:
    """Một lần nhắc nhóm Nice -> hồ sơ.

    Nhóm trên tên thư mục hồ sơ của tệp thì nối vào hồ sơ đó. Không thì nhóm
    thuộc số văn bằng/số đơn gần nhất ĐỨNG TRƯỚC nó trên cùng dòng ("văn bằng
    số N đăng ký cho các sản phẩm nhóm 009") và đi theo hồ sơ của số ấy."""
    cua_tep = sorted(h for h, lop in lop_ho_so.items() if v in lop)
    if cua_tep:
        return {"ket_qua": "da_noi", "cach": "nhom_ho_so", "ho_so": cua_tep}
    truoc = [kq for p, kq in so_tren_dong if p < vi_tri]
    if truoc and truoc[-1]["ket_qua"] == "da_noi":
        kq = truoc[-1]
        return {"ket_qua": "da_noi", "cach": "theo_so", "so": kq["gia_tri"],
                "ho_so": sorted({n["ho_so"] for n in kq["noi"]})}
    return {"ket_qua": "chua_noi"}


# --------------------------------------------------------------------------
# Một tệp
# --------------------------------------------------------------------------

def neo_tep(doc_id: str, nguon: str | None, ban: dict[str, str], chi_muc: dict[str, list[dict]],
            hoi_thoai: set[str], danh_tinh: dict[str, dict], thu_muc_ho_so: dict[str, str]) -> dict:
    """Mọi số và nhóm Nice của một tệp hội thoại, gộp qua các bản parse."""
    rec = danh_tinh.get(nguon or "")
    ho_so_tep = {h["ho_so"] for h in (rec or {}).get("ho_so", [])}
    lop_ho_so = {h: lop_cua_ho_so(thu_muc_ho_so.get(h)) for h in ho_so_tep}

    gop: dict[tuple[str, str], dict] = {}
    for ten, md in ban.items():
        so_dong: dict[int, list[tuple[int, dict]]] = {}
        dem: Counter = Counter()
        for x in boc_so(md):
            k = (x["hinh"], x["gia_tri"])
            dem[k] += 1
            if x["hinh"] == NHOM_NICE:
                kq = noi_nhom(x["gia_tri"], x["dong"], x["vi_tri"], lop_ho_so, so_dong.get(x["dong"], []))
            else:
                kq = noi_so(doc_id, x["hinh"], x["gia_tri"], chi_muc, hoi_thoai, ho_so_tep)
                if kq["ket_qua"] == "chua_noi" and (n := nhan_truoc(x["trich"], x["vi_tri"], x["hinh"])):
                    kq = {**kq, "nhan": n}
                so_dong.setdefault(x["dong"], []).append((x["vi_tri"], {**kq, "gia_tri": x["gia_tri"]}))
            g = gop.setdefault(k, {"hinh": x["hinh"], "gia_tri": x["gia_tri"], "ban_parse": [],
                                   "lan_nhac": 0, "dong": {}, "da_noi_o_ban": [], "_kq": []})
            if ten not in g["ban_parse"]:
                g["ban_parse"].append(ten)
            g["dong"].setdefault(ten, []).append(x["dong"])
            g["_kq"].append(kq)
            if kq["ket_qua"] == "da_noi" and ten not in g["da_noi_o_ban"]:
                g["da_noi_o_ban"].append(ten)
        for k, n in dem.items():
            gop[k]["lan_nhac"] = max(gop[k]["lan_nhac"], n)

    so, nhom = [], []
    for g in gop.values():
        kqs = g.pop("_kq")
        if g["hinh"] == NHOM_NICE:
            noi = [k for k in kqs if k["ket_qua"] == "da_noi"]
            g["ket_qua"] = "da_noi" if noi else "chua_noi"
            g["cach"] = sorted({k["cach"] for k in noi})
            g["ho_so"] = sorted({h for k in noi for h in k["ho_so"]})
            g["theo_so"] = sorted({k["so"] for k in noi if k["cach"] == "theo_so"})
            nhom.append(g)
        else:
            so.append(_chot_so(g, kqs))
    so.sort(key=lambda g: (g["ket_qua"], g["hinh"], g.get("gia_tri") or ""))
    nhom.sort(key=lambda g: g["gia_tri"])
    return {
        "doc_id": doc_id, "duong_dan": nguon,
        "ho_so": sorted(ho_so_tep),
        **({"xung_dot": rec["xung_dot"]} if rec and rec.get("xung_dot") else {}),
        **({} if rec else {"ngoai_so_danh_tinh": True}),
        "ban_parse": list(ban),
        "so": so, "nhom_nice": nhom,
    }


_THU_TU_KQ = ("da_noi", "nghi_hong_ocr", "bi_giu", "chua_noi")


def _chot_so(g: dict, kqs: list[dict]) -> dict:
    """Các bản parse cho cùng một số cùng một kết quả (cùng sổ); lấy kết quả
    mạnh nhất. Giá trị chỉ ở lại khi số là số công khai."""
    kq = min(kqs, key=lambda k: _THU_TU_KQ.index(k["ket_qua"]))
    g = {**g, **{k: v for k, v in kq.items() if k != "gia_tri"}}
    if kq["ket_qua"] == "bi_giu" or (kq["ket_qua"] == "chua_noi" and not kq.get("nhan")):
        g["so_chu_so"] = len(g["gia_tri"])
        g["gia_tri"] = None
    return g


# --------------------------------------------------------------------------
# Chứng minh: chữ có dấu trượt, số vẫn nối
# --------------------------------------------------------------------------

CUA_SO_CHU = 4


def cum_quanh(md: str, v: str, dong: int) -> str | None:
    """Tối đa CUA_SO_CHU từ mỗi bên số `v` trên dòng `dong` (tính từ 1), gồm cả số."""
    dong_md = md.split("\n")
    if not 1 <= dong <= len(dong_md):
        return None
    tu = ssh.phang(dong_md[dong - 1]).split()
    for i, t in enumerate(tu):
        if re.sub(r"\D", "", t) == v:
            return " ".join(tu[max(0, i - CUA_SO_CHU):i + CUA_SO_CHU + 1])
    return None


def che_so_khac(cum: str | None, v: str) -> str | None:
    """Che mọi dãy ≥ 6 chữ số không phải `v` trong cụm lưu lại: cửa sổ quanh một
    số công khai có thể quét trúng số điện thoại hay số tài khoản cạnh nó."""
    if cum is None:
        return None
    muc = "|".join(re.escape(x) for x in {v, f"{int(v):,}"})
    day = re.compile(rf"(?<!\d)(?:{muc})(?!\d)|\d(?:[,.\s-]?\d)*")
    return day.sub(lambda m: m.group(0) if len(re.sub(r"\D", "", m.group(0))) < 6
                   or re.sub(r"\D", "", m.group(0)) == v else "[so]", cum)


def _chu_co_dau(s: str) -> str:
    """Như `chuan_chu` nhưng GIỮ dấu: chỉ hạ chữ, bỏ dấu câu, gộp khoảng trắng."""
    return re.sub(r"[\W_]+", " ", nfc(s).lower()).strip()


def chung_minh(tep: dict, ban: dict[str, str]) -> list[dict]:
    """Mỗi số/nhóm đã nối có mặt trong ≥ 2 bản parse: lấy cụm chữ quanh nó ở
    bản sạch hơn, tìm trong bản kia theo ba cách — chuỗi có dấu, chuỗi đã bỏ
    dấu cả hai phía, và chỉ con số."""
    ra = []
    ten_ban = list(ban)
    for g in tep["so"] + tep["nhom_nice"]:
        if g["ket_qua"] != "da_noi" or len(g["ban_parse"]) < 2:
            continue
        goc = g["ban_parse"][0]
        for khac in g["ban_parse"][1:]:
            cum = cum_quanh(ban[goc], g["gia_tri"], g["dong"][goc][0])
            if not cum:
                continue
            md_khac = " ".join(ssh.phang(d) for d in ban[khac].split("\n"))
            co_dau = f" {_chu_co_dau(cum)} " in f" {_chu_co_dau(md_khac)} "
            ra.append({
                "doc_id": tep["doc_id"], "hinh": g["hinh"], "gia_tri": g["gia_tri"],
                "ban_goc": goc, "ban_so": khac, "cum_goc": che_so_khac(cum, g["gia_tri"]),
                "cum_ban_so": che_so_khac(cum_quanh(ban[khac], g["gia_tri"], g["dong"][khac][0]), g["gia_tri"]),
                "khop_co_dau": co_dau,
                "khop_bo_dau": co_chua(cum, md_khac),
                "khop_so": khac in g["da_noi_o_ban"],
                "ho_so": g.get("ho_so") or sorted({n["ho_so"] for n in g.get("noi", [])}),
            })
    ra.sort(key=lambda c: (c["doc_id"], ten_ban.index(c["ban_so"]) if c["ban_so"] in ten_ban else 9, c["gia_tri"]))
    return ra


# --------------------------------------------------------------------------
# Dựng sổ
# --------------------------------------------------------------------------

def dung(kho: Path, so_dir: Path) -> dict:
    so_hieu_p = so_dir / "so_hieu.json"
    danh_tinh_p = so_dir / "danh_tinh.json"
    for p, sinh in ((so_hieu_p, "so_so_hieu.py"), (danh_tinh_p, "so_danh_tinh.py")):
        if not p.exists():
            raise SystemExit(f"thiếu {p}: chạy scripts/{sinh} trước")
    so_hieu = json.loads(so_hieu_p.read_text("utf-8"))["so_hieu"]
    chi_muc = chi_muc_so_hieu(so_hieu)
    danh_tinh = ssh.nap_danh_tinh(danh_tinh_p)
    thu_muc_ho_so = {h["ho_so"]: h.get("thu_muc") or ""
                     for h in json.loads(danh_tinh_p.read_text("utf-8"))["ho_so"]}

    hoi_thoai, co_mat = tep_hoi_thoai(so_dir)
    tep, chung, khong_parse = [], [], []
    for doc_id, nguon_nd in hoi_thoai.items():
        nguon, ban = nap_ban_parse(kho, doc_id)
        if not ban:
            khong_parse.append(doc_id)
            continue
        t = neo_tep(doc_id, nguon, ban, chi_muc, set(hoi_thoai), danh_tinh, thu_muc_ho_so)
        t["nhan_dien"] = nguon_nd
        tep.append(t)
        chung += chung_minh(t, ban)
    return {
        "tao_luc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "nguon": {"kho_bang_chung": str(kho), "so_hieu": str(so_hieu_p), "danh_tinh": str(danh_tinh_p),
                  "so_nhan_dien_hoi_thoai": co_mat},
        "quy_tac": {
            "thu_tu": ["bóc số trước (8/7 chữ số, nhóm Nice 001–045)",
                       "so số với sổ số hiệu / nhóm trên thư mục hồ sơ trước khi so chữ",
                       "so chữ chỉ khi buộc phải, và bỏ dấu cả hai phía"],
            "bang": "chỉ số nối vào bảng công khai của sổ số hiệu, hoặc có nhãn USPTO, mới mang giá trị",
        },
        "tom_tat": tom_tat(tep, chung, khong_parse),
        "tep": tep,
        "chung_minh": chung,
        "khong_co_parse": khong_parse,
    }


def tom_tat(tep: list[dict], chung: list[dict], khong_parse: list[str]) -> dict:
    so = [g for t in tep for g in t["so"]]
    nhom = [g for t in tep for g in t["nhom_nice"]]
    ho_so_cua = [n for g in so if g["ket_qua"] == "da_noi" for n in g["noi"]]
    chi_vi_dau = [c for c in chung if not c["khop_co_dau"] and c["khop_bo_dau"] and c["khop_so"]]
    return {
        "tep_hoi_thoai": len(tep) + len(khong_parse),
        "tep_co_parse": len(tep),
        "tep_theo_so_nhan_dien": dict(Counter(n for t in tep for n in t["nhan_dien"])),
        "tep_co_so_hoac_nhom": sum(1 for t in tep if t["so"] or t["nhom_nice"]),
        "so": {
            "cap_tep_so": len(so),
            "lan_nhac": sum(g["lan_nhac"] for g in so),
            "theo_hinh": dict(Counter(g["hinh"] for g in so)),
            "theo_ket_qua": dict(Counter(g["ket_qua"] for g in so)),
            "gia_tri_rieng_da_noi": len({g["gia_tri"] for g in so if g["ket_qua"] == "da_noi"}),
            "noi_ho_so": len(ho_so_cua),
            "noi_cung_ho_so_voi_tep": sum(1 for n in ho_so_cua if n["cung_ho_so_voi_tep"]),
            "noi_co_tep_ho_so_ngoai_hoi_thoai": sum(1 for n in ho_so_cua if n["tep_ho_so"]),
            "chua_noi_co_nhan_uspto": sum(1 for g in so if g["ket_qua"] == "chua_noi" and g.get("nhan")),
        },
        "nhom_nice": {
            "cap_tep_nhom": len(nhom),
            "lan_nhac": sum(g["lan_nhac"] for g in nhom),
            "theo_ket_qua": dict(Counter(g["ket_qua"] for g in nhom)),
            "theo_cach": dict(Counter(c for g in nhom for c in g["cach"])),
        },
        "chung_minh": {
            "so_lan_so": len(chung),
            "co_dau_truot": sum(1 for c in chung if not c["khop_co_dau"]),
            "bo_dau_khop": sum(1 for c in chung if c["khop_bo_dau"]),
            "so_khop": sum(1 for c in chung if c["khop_so"]),
            "lech_chi_vi_dau_ma_so_van_noi": len(chi_vi_dau),
            "tep_co_ca_lech_chi_vi_dau": len({c["doc_id"] for c in chi_vi_dau}),
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ade-out", type=Path, default=KHO)
    ap.add_argument("--so", type=Path, default=SO_DIR, help="thư mục các sổ đầu vào")
    ap.add_argument("--ra", type=Path, default=RA)
    args = ap.parse_args(argv)

    ket = dung(args.ade_out, args.so)
    ssh._ghi_rieng(args.ra, json.dumps(ket, ensure_ascii=False, indent=2) + "\n")

    # Chỉ in số đếm: giá trị và nguyên văn chỉ nằm trong sổ riêng.
    t = ket["tom_tat"]
    print(f"so neo so: {args.ra}")
    print(f"  tep hoi thoai: {t['tep_hoi_thoai']}  co parse: {t['tep_co_parse']}  co so/nhom: {t['tep_co_so_hoac_nhom']}")
    print(f"  so: {t['so']}")
    print(f"  nhom nice: {t['nhom_nice']}")
    print(f"  chung minh: {t['chung_minh']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
