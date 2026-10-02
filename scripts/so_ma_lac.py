"""Sổ mã lạc đàn: trong mỗi thư mục hồ sơ, mã nào lệch mã đa số, và vì sao.

VẤN ĐỀ
───────
Tên tệp trong kho mở đầu bằng mã hồ sơ (`NH501.US_...`). Trong một thư mục
hồ sơ, đa số tệp mang cùng một mã; vài tệp mang mã khác. Gộp hết thành "lỗi
OCR" là sai: cả hai chuỗi đều đọc từ hệ tệp, không có bước OCR nào. Mã lạc
đến từ ba nguồn khác hẳn nhau, và mỗi nguồn đòi một cách xử lý riêng:

  lỗi gõ              lệch 1–2 chữ số, chỉ một tệp mang
                      (NH502 giữa mười NH501) → đề xuất tên đúng; NGƯỜI đổi
  đánh số song song   khác tiền tố (TV2001 trong hồ sơ NH501): số tra cứu /
                      tư vấn, KHÔNG phải lỗi → nối hồ sơ ↔ số tra cứu
  để nhầm hồ sơ       khác mã VÀ tên tệp mang tên nhãn khác nhãn của thư mục
                      (NH777.US_BETA_* nằm trong thư mục ALPHA) → danh sách
                      giao người, script KHÔNG BAO GIỜ dời tệp

CÁCH PHÂN — cho mỗi thư mục hồ sơ F (Phòng IP/<mảng>/<số>. …), M = mã đa số
(đếm theo tệp, mỗi mã một lần/tệp; hoà thì chọn mã trùng số thư mục), X là
một mã khác M. Áp dụng theo thứ tự, gặp luật nào dừng ở đó:

  1. tiền tố X không thuộc hệ mã hồ sơ (tập tiền tố của các mã đa số) →
     `bo_qua` (vd NQ…, INV… — văn bản, hoá đơn, không phải mã hồ sơ).
  2. X là mã đa số / trùng số của một thư mục hồ sơ G khác → mọi tệp X
     trong F đều kèm M thì là tệp chung hai hồ sơ (`tep_nhieu_ho_so`, không
     phải mã lạc); còn tệp X không kèm M thì là `de_nham_ho_so`.
  3. tiền tố X khác tiền tố M → `danh_so_song_song`.
  4. tệp X không kèm M mang tên nhãn riêng (chữ HOA ≥3 ký tự, hoặc cụm
     `- <Nhãn> (<nhóm>)`) không thuộc nhãn của F → `de_nham_ho_so`.
     Token đi cùng ≥2 mã hay ≥2 thư mục (VAT, …) là từ chung, không tính.
  5. X chỉ ở MỘT tên tệp → ứng viên lỗi gõ. Ứng viên sửa: mã cùng tiền tố
     có ≥2 tệp trong F, trừ mã đã có sẵn trong chính tên tệp đó. Lệch ≤
     NGUONG_CHU_SO chữ số (khoảng cách sửa chuỗi trên phần số, GIỮ số 0
     đầu) → `loi_go`. Lệch hơn thì chỉ nội dung bản đọc ADE quyết được:
     nội dung nhắc mã/nhãn ứng viên mà không nhắc X → `loi_go` kèm
     `vuot_nguong`; không có bản đọc hay nội dung im lặng → chưa phân.
  6. còn lại → `chua_phan_loai`, ghi lý do để người xem.

Mỗi đề xuất có `can_nguoi_chot` khi nội dung nhắc chính X, nhắc một ứng
viên khác, hoặc có ứng viên khác gần bằng mà nội dung không phân xử.

RÀNG BUỘC
─────────
Kho `~/.private/refiny_data` là bản gốc, chỉ đọc: script chụp (đường dẫn,
cỡ, mtime) trước và sau, lệch thì thoát 1. Đề xuất đổi tên chỉ nằm trong
sổ; người quyết. Sổ ghi ra `~/.private/so/ma_lac_dan.json` (0600, ngoài
cây git). Dòng trích nội dung bị che số dài và số văn bản.

Serial USPTO trong tên tệp (`… - <8 chữ số>_<ddmmyy>`) chỉ được gom vào
mục `ban_giao_so_hieu_q4` để sổ số hiệu dựng tiếp — sổ này không đối chiếu.

    uv run python scripts/so_ma_lac.py            # ghi sổ, in tóm tắt
    uv run python scripts/so_ma_lac.py --khong-ghi
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ocr_lab.ade_store import DEFAULT_STORE, doc_id_for      # noqa: E402

PRIVATE = Path.home() / ".private" / "refiny_data"
DEFAULT_LEDGER = Path.home() / ".private" / "so" / "ma_lac_dan.json"
SO_BAN_SACH = Path.home() / ".private" / "so" / "ban_sach_vs_anh.json"

NGUONG_CHU_SO = 2
LOAI = ("loi_go", "danh_so_song_song", "de_nham_ho_so", "chua_phan_loai")
TRANG_THAI_GIAO = "chờ người quyết — không tự dời"
TRANG_THAI_DE_XUAT = "đề xuất — người quyết đổi tên, script không đổi"

# Một mã ở đầu tên tệp: tiền tố HOA, số (giữ số 0 đầu), đuôi `.2` / `-88`,
# rồi `.US` / `,US` / `. US` tuỳ cách gõ. Nhiều mã nối nhau bằng dấu phẩy.
MOT_MA = re.compile(
    r"(?P<tt>[A-Z]{2,3})\s?(?P<so>\d{2,5})"
    r"(?P<cham>\.\d{1,2}(?!\d))?(?P<gach>[-–]\d{1,4})?"
    r"(?:\s*[.,]\s*(?i:US|VN)(?![A-Za-z]))?"
    r"(?![A-Za-z0-9])")
TACH_MA = re.compile(r"\s*[,&+]\s*")
THU_MUC_HO_SO = re.compile(r"^\s*(\d+)\s*\.")
SERIAL = re.compile(r"\s-\s*(?P<serial>\d{8})(?:_(?P<ngay>\d{6}))?$")
NHAN_NHOM = re.compile(r"(?:^|[-_])\s*(?P<nhan>[^-()_]+?)\s*\((?P<nhom>\d{3})\)")
TU_BO = {"US", "VN", "CLASS", "PDF", "DOC", "DOCX", "XLSX", "JPG", "PNG"}


# ── Chuẩn hoá chuỗi ──────────────────────────────────────────────────────

def _nfc(s: str) -> str:
    """macOS trả tên tệp ở NFD; mọi so sánh chuỗi phải quy về NFC trước."""
    return unicodedata.normalize("NFC", s)


def khong_dau(s: str) -> str:
    """Bỏ dấu, giữ hoa/thường. `đ` không tách qua NFD nên thay tay trước."""
    s = _nfc(s).replace("Đ", "D").replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    return _nfc("".join(c for c in s if not unicodedata.combining(c)))


def khoang_cach(a: str, b: str) -> int:
    """Khoảng cách sửa chuỗi (Levenshtein) — `0071` và `071` lệch 1."""
    truoc = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        nay = [i]
        for j, cb in enumerate(b, 1):
            nay.append(min(truoc[j] + 1, nay[j - 1] + 1, truoc[j - 1] + (ca != cb)))
        truoc = nay
    return truoc[-1]


def _che(dong: str) -> str:
    """Dòng trích vào sổ: bỏ thẻ, che số văn bản và mọi dãy ≥5 chữ số."""
    s = re.sub(r"<[^>]+>", " ", dong)
    s = re.sub(r"\S+/\d{4}/\S+", "<số-văn-bản>", s)
    s = re.sub(r"\d{5,}", "<số>", s)
    return re.sub(r"\s+", " ", s).strip()[:160]


# ── Mã trong tên tệp ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class Ma:
    tien_to: str
    so: str          # chữ số thô, giữ số 0 đầu
    cham: str        # ".2" hoặc ""
    gach: str        # "-88" hoặc ""
    dau: int         # vị trí trong tên tệp, để thay đúng chỗ khi đề xuất
    cuoi: int

    @property
    def duoi(self) -> str:
        return self.cham + self.gach

    @property
    def khoa(self) -> str:
        return self.tien_to + self.so + self.duoi

    @property
    def goc(self) -> str:
        return self.tien_to + self.so

    @property
    def phan_so(self) -> str:
        return self.so + self.duoi


def tach_ma_dau(ten: str) -> tuple[list[Ma], str]:
    """Tách các mã hồ sơ đứng đầu tên tệp; trả (mã, phần tên còn lại)."""
    ten = _nfc(ten)
    out: list[Ma] = []
    i = 0
    while m := MOT_MA.match(ten, i):
        cuoi = max(m.end(g) for g in ("so", "cham", "gach") if m.group(g))
        out.append(Ma(m["tt"], m["so"], m["cham"] or "",
                      (m["gach"] or "").replace("–", "-"), m.start(), cuoi))
        i = m.end()
        t = TACH_MA.match(ten, i)
        if not (t and MOT_MA.match(ten, t.end())):
            break
        i = t.end()
    return out, (ten[i:].lstrip(" _-.,") if out else ten)


def _mau_nhac(m: Ma) -> re.Pattern:
    """Mã được nhắc trong chuỗi khác: cho phép dấu cách sau tiền tố và số 0 đầu."""
    return re.compile(rf"(?<![A-Za-z0-9]){m.tien_to}\s?0*{int(m.so)}"
                      rf"{re.escape(m.duoi)}(?!\d)")


def _khop_so(m: Ma, so: int | None) -> bool:
    return so is not None and (int(m.so) == so or (bool(m.gach) and int(m.gach[1:]) == so))


def nhan_thu_muc(ten: str) -> set[str]:
    """Tên nhãn trong tên thư mục hồ sơ: bỏ số đầu, `.US.`, `in class …`."""
    s = khong_dau(ten)
    s = re.sub(r"^\s*\d+\s*[.,]?\s*(?:(?:US|VN)\b\s*[.,]?)?", "", s)
    s = re.sub(r"\bin\s+class(?:es)?\b[\s\d,&-]*", " ", s, flags=re.I)
    out = set()
    for w in re.findall(r"[A-Za-z]+", s):
        if w.upper() in TU_BO:
            continue
        if (w.isupper() and len(w) >= 3) or (w[0].isupper() and w[1:].islower() and len(w) >= 4):
            out.add(w.upper())
    return out


def _than(ten: str) -> str:
    return ten.rsplit(".", 1)[0] if re.search(r"\.[A-Za-z0-9]{2,5}$", ten) else ten


def token_ten(con: str) -> tuple[set[str], list[str]]:
    """Từ HOA ≥3 ký tự và cụm `- <Nhãn> (<nhóm>)` trong phần tên sau mã."""
    con = _than(con)
    s = khong_dau(con)
    toks = {w for w in re.findall(r"[A-Za-z]+", s)
            if w.isupper() and len(w) >= 3 and w not in TU_BO}
    return toks, [m["nhan"].strip() for m in NHAN_NHOM.finditer(con)]


# ── Kho ──────────────────────────────────────────────────────────────────

@dataclass
class Tep:
    rel: str
    ho_so: str | None
    ma: list[Ma]
    con: str
    doc_id: str

    @property
    def ten(self) -> str:
        return self.rel.rsplit("/", 1)[-1]

    @property
    def khoa(self) -> list[str]:
        return [m.khoa for m in self.ma]

    def thu_muc_con(self) -> list[str]:
        """Các thư mục con giữa thư mục hồ sơ và tệp."""
        return self.rel.split("/")[3:-1]


def _duyet(kho: Path):
    for p in kho.rglob("*"):
        if p.is_file() and not p.name.startswith((".", "~$")):
            yield _nfc(p.relative_to(kho).as_posix()), p


def chup_kho(kho: Path) -> list[tuple[str, int, int]]:
    """Ảnh chụp kho gốc để chứng minh script không đụng tới: tên, cỡ, mtime."""
    out = []
    for p in Path(kho).rglob("*"):
        rel = _nfc(p.relative_to(kho).as_posix())
        if p.is_dir():
            out.append((rel + "/", 0, 0))
        elif p.name != ".DS_Store":
            st = p.stat()
            out.append((rel, st.st_size, st.st_mtime_ns))
    return sorted(out)


def _doc_md(store: Path, doc_id: str) -> str | None:
    for ten in ("parse_pro.json", "parse.json"):
        f = store / doc_id / ten
        if f.exists():
            try:
                return json.loads(f.read_text("utf-8")).get("markdown") or ""
            except Exception:                        # noqa: BLE001
                return None
    return None


def _tep_ra(t: Tep, store: Path) -> dict:
    return {"duong_dan": t.rel, "doc_id": t.doc_id,
            "co_ban_doc": _doc_md(store, t.doc_id) is not None}


# ── Lập sổ ───────────────────────────────────────────────────────────────

def lap_so(kho: Path, store: Path, so_ban_sach: Path | None = None) -> dict:
    kho, store = Path(kho), Path(store)
    teps: list[Tep] = []
    for rel, _p in _duyet(kho):
        parts = rel.split("/")
        hs = "/".join(parts[:3]) if len(parts) >= 4 and THU_MUC_HO_SO.match(parts[2]) else None
        ma, con = tach_ma_dau(parts[-1])
        teps.append(Tep(rel, hs, ma, con, doc_id_for(rel)))
    teps.sort(key=lambda t: t.rel)

    theo_hs: dict[str, list[Tep]] = defaultdict(list)
    for t in teps:
        if t.ho_so:
            theo_hs[t.ho_so].append(t)
    so_hs = {hs: int(THU_MUC_HO_SO.match(hs.split("/")[2])[1]) for hs in theo_hs}

    mau: dict[str, Ma] = {}
    for t in teps:
        for m in t.ma:
            mau.setdefault(m.khoa, m)

    dem: dict[str, Counter] = {}
    ma_da_so: dict[str, str] = {}
    for hs, ds in theo_hs.items():
        c = Counter(k for t in ds for k in dict.fromkeys(t.khoa))
        dem[hs] = c
        if c:
            ma_da_so[hs] = sorted(c, key=lambda k: (-c[k], not _khop_so(mau[k], so_hs[hs]), k))[0]
    tien_to_ho_so = sorted({mau[m].tien_to for m in ma_da_so.values()})

    # Từ chung: đi với ≥2 mã (xét tệp một mã) hoặc ≥2 thư mục → không phải tên nhãn.
    ma_cua_tu: dict[str, set] = defaultdict(set)
    hs_cua_tu: dict[str, set] = defaultdict(set)
    for t in teps:
        for w in token_ten(t.con)[0]:
            hs_cua_tu[w].add(t.ho_so)
            if len(t.ma) == 1:
                ma_cua_tu[w].add(t.ma[0].khoa)
    tu_chung = {w for w in hs_cua_tu if len(ma_cua_tu[w]) >= 2 or len(hs_cua_tu[w]) >= 2}

    def tu_rieng(ds: list[Tep], k: str) -> set[str]:
        return {w for t in ds if t.khoa == [k] for w in token_ten(t.con)[0] - tu_chung}

    nhan_hs = {hs: nhan_thu_muc(hs.split("/")[2]) | (tu_rieng(ds, ma_da_so[hs]) if hs in ma_da_so else set())
               for hs, ds in theo_hs.items()}

    def nhan_cua(k: str, hs: str) -> set[str]:
        if ma_da_so.get(hs) == k:
            return nhan_hs[hs]
        g = [h for h, m in ma_da_so.items() if m == k]
        return set().union(*(nhan_hs[h] for h in g)) if g else tu_rieng(theo_hs[hs], k)

    toan_kho = Counter(k for t in teps for k in dict.fromkeys(t.khoa))
    goc_o_hs: dict[str, set] = defaultdict(set)
    for t in teps:
        for m in t.ma:
            if t.ho_so:
                goc_o_hs[m.goc].add(t.ho_so)

    md_cache: dict[str, str | None] = {}

    def md_of(t: Tep) -> str | None:
        if t.doc_id not in md_cache:
            md_cache[t.doc_id] = _doc_md(store, t.doc_id)
        return md_cache[t.doc_id]

    ho_so, ma_lac, bo_qua, nhieu_hs = [], [], [], []
    for hs in sorted(theo_hs):
        ds, c = theo_hs[hs], dem[hs]
        M = ma_da_so.get(hs)
        co_ma = sum(1 for t in ds if t.ma)
        ho_so.append({
            "thu_muc": hs, "so_thu_muc": so_hs[hs], "nhan_thu_muc": sorted(nhan_hs[hs]),
            "ma_da_so": M, "so_tep_da_so": c[M] if M else 0, "so_tep_co_ma": co_ma,
            "so_tep": len(ds), "khop_so_thu_muc": _khop_so(mau[M], so_hs[hs]) if M else False,
            "ma_khac": {k: c[k] for k in sorted(c) if k != M},
        })
        if not M:
            continue
        mM = mau[M]
        for X in sorted(c):
            if X == M:
                continue
            mX = mau[X]
            tep_X = [t for t in ds if X in t.khoa]
            rieng = [t for t in tep_X if M not in t.khoa]
            dong = {
                "ho_so": hs, "ma_lac": X, "ma_da_so": M,
                "so_tep_da_so": c[M], "so_tep_co_ma": co_ma,
                "so_lan_xuat_hien": len(tep_X), "so_lan_toan_kho": toan_kho[X],
                "tep_lo_ra": [_tep_ra(t, store) for t in tep_X],
            }

            # 1. không thuộc hệ mã hồ sơ
            if mX.tien_to not in tien_to_ho_so:
                bo_qua.append({"ho_so": hs, "ma": X, "so_tep": len(tep_X),
                               "ly_do": f"tiền tố {mX.tien_to} không phải hệ mã hồ sơ "
                                        f"({', '.join(tien_to_ho_so)})",
                               "tep": [t.rel for t in tep_X]})
                continue

            # 2. mã của một thư mục hồ sơ khác
            G = sorted(g for g, m in ma_da_so.items() if g != hs and (
                m == X or (mau[m].tien_to == mX.tien_to and so_hs[g] == int(mX.so))))
            if G and not rieng:
                nhieu_hs.append({"ho_so": hs, "ma": X, "ma_da_so": M,
                                 "thu_muc_ho_so_cua_ma": G, "tep": [t.rel for t in tep_X]})
                continue
            if G:
                ma_lac.append({**dong, "loai": "de_nham_ho_so",
                               "ten_nhan": sorted(set().union(*(nhan_hs[g] for g in G))),
                               "ly_do": f"{X} là mã của thư mục hồ sơ khác; {len(rieng)} tệp "
                                        f"không kèm {M}"})
                continue

            # 3. hệ đánh số song song
            if mX.tien_to != mM.tien_to:
                ma_lac.append({**dong, "loai": "danh_so_song_song", "lien_ket_goc": mX.goc,
                               "ly_do": f"tiền tố {mX.tien_to} khác hệ {mM.tien_to} của hồ sơ: "
                                        "số tra cứu/tư vấn song song, không phải lỗi"})
                continue

            # 4. tên nhãn lạ trong tên tệp
            la = set()
            for t in rieng:
                toks, cum = token_ten(t.con)
                la |= {w for w in toks - tu_chung if w not in nhan_hs[hs]}
                for p in cum:
                    tu = {w.upper() for w in re.findall(r"[A-Za-z]+", khong_dau(p))}
                    if not tu & nhan_hs[hs]:
                        la.add(khong_dau(p).upper())
            if la:
                ma_lac.append({**dong, "loai": "de_nham_ho_so", "ten_nhan": sorted(la),
                               "ly_do": f"không có thư mục hồ sơ {mX.tien_to}{int(mX.so)}; "
                                        f"{len(rieng)} tệp không kèm {M} mang nhãn "
                                        f"{', '.join(sorted(la))} — nhãn thư mục: "
                                        f"{', '.join(sorted(nhan_hs[hs])) or '(không đọc được)'}"})
                continue

            # 5. lỗi gõ
            if len({t.ten for t in tep_X}) == 1:
                ma_lac.append(_xet_loi_go(dong, hs, X, M, mau, c, tep_X, co_ma,
                                          nhan_cua, md_of))
                continue

            # 6. còn lại
            ma_lac.append({**dong, "loai": "chua_phan_loai",
                           "ly_do": f"{len(tep_X)} tệp cùng hệ {mX.tien_to}, không có thư mục "
                                    "hồ sơ riêng, không mang nhãn lạ — cần người xem"})

    thu_tu = {l: i for i, l in enumerate(LOAI)}
    ma_lac.sort(key=lambda r: (r["ho_so"], thu_tu[r["loai"]], r["ma_lac"]))

    lien_ket = _lien_ket(ma_lac, theo_hs, mau, goc_o_hs)
    giao = _giao_nguoi(ma_lac, theo_hs, so_hs, ma_da_so, nhan_hs, mau, store)
    ban_giao = _ban_giao_serial(teps, tu_chung, store)
    doi_chieu = _doi_chieu(ma_lac, so_ban_sach)

    theo_loai = {l: sum(r["loai"] == l for r in ma_lac) for l in LOAI}
    dx = [r["de_xuat"] for r in ma_lac if "de_xuat" in r]
    tom_tat = {
        "so_tep": len(teps),
        "so_tep_trong_thu_muc_ho_so": sum(1 for t in teps if t.ho_so),
        "so_tep_ngoai_thu_muc_ho_so": sum(1 for t in teps if not t.ho_so),
        "so_tep_co_ma_dau": sum(1 for t in teps if t.ma),
        "so_ho_so": len(ho_so),
        "so_ho_so_co_ma_da_so": len(ma_da_so),
        "so_ho_so_co_ma_lac": len({r["ho_so"] for r in ma_lac}),
        "tien_to_ho_so": tien_to_ho_so,
        "so_ma_lac": len(ma_lac),
        "theo_loai": theo_loai,
        "so_de_xuat_can_nguoi_chot": sum(1 for d in dx if d["can_nguoi_chot"]),
        "so_de_xuat_vuot_nguong": sum(1 for d in dx if d["vuot_nguong"]),
        "so_lien_ket_so_tra_cuu": len(lien_ket),
        "so_giao_nguoi": len(giao),
        "so_tep_de_nham": sum(len(g["tep_de_nham"]) for g in giao),
        "so_tep_chung_trong_giao": sum(len(g["tep_chung"]) for g in giao),
        "so_tep_nhieu_ho_so": sum(len(r["tep"]) for r in nhieu_hs),
        "so_bo_qua": len(bo_qua),
        "so_serial": len(ban_giao),
        "so_tep_co_serial": sum(len(r["tep"]) for r in ban_giao),
        "doi_chieu_so_ban_sach": {
            "khop": sum(1 for r in doi_chieu if r["khop"] is True),
            "lech": sum(1 for r in doi_chieu if r["khop"] is False),
            "khong_phai_ma_lac": sum(1 for r in doi_chieu if r["khop"] is None),
        },
    }
    return {
        "tao_luc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "nguong_chu_so": NGUONG_CHU_SO,
        "ghi_chu": {
            "ma_lac": "mỗi dòng: mã lạc, loại, mã đa số, số lần xuất hiện, tệp làm lộ ra",
            "de_xuat": "chỉ là đề xuất; kho gốc không bị đổi tên — người quyết",
            "giao_nguoi_xu_ly": "tệp để nhầm hồ sơ; script không dời, người quyết",
            "ban_giao_so_hieu_q4": "serial trong tên tệp, chuyển sổ số hiệu; sổ này không đối chiếu",
        },
        "tom_tat": tom_tat,
        "ho_so": ho_so,
        "ma_lac": ma_lac,
        "giao_nguoi_xu_ly": giao,
        "lien_ket_so_tra_cuu": lien_ket,
        "tep_nhieu_ho_so": nhieu_hs,
        "bo_qua": bo_qua,
        "ban_giao_so_hieu_q4": ban_giao,
        "doi_chieu_so_khac": doi_chieu,
    }


def _xet_loi_go(dong, hs, X, M, mau, c, tep_X, co_ma, nhan_cua, md_of) -> dict:
    """Luật 5: một tên tệp duy nhất mang X — tìm mã đúng, nội dung phân xử khi cần."""
    mX = mau[X]
    t0 = tep_X[0]
    trong_ten = set(t0.khoa)
    uv = sorted((khoang_cach(mX.phan_so, mau[k].phan_so), -c[k], k) for k in c
                if k not in trong_ten and c[k] >= 2 and mau[k].tien_to == mX.tien_to)
    d_cua = {k: d for d, _, k in uv}

    md = next((m for m in map(md_of, tep_X) if m is not None), None)
    kd = khong_dau(md) if md else ""

    def nhac_ma(k: str) -> bool:
        return bool(md) and bool(_mau_nhac(mau[k]).search(md))

    def nhac_nhan(k: str) -> list[str]:
        if not md:
            return []
        return sorted(w for w in nhan_cua(k, hs)
                      if re.search(rf"(?<![A-Za-z0-9]){re.escape(w)}(?![A-Za-z0-9])", kd, re.I))

    def cung_so(k: str) -> bool:
        return int(mau[k].so) == int(mX.so) and mau[k].duoi == mX.duoi

    if M in d_cua and d_cua[M] <= NGUONG_CHU_SO:
        P = M
    elif uv and uv[0][0] <= NGUONG_CHU_SO:
        P = uv[0][2]
    elif md and not any(nhac_ma(k) for k in [X]):
        theo_ma = [k for _, _, k in uv if nhac_ma(k)]
        theo_nhan = [k for _, _, k in uv if nhac_nhan(k)]
        P = (theo_ma or theo_nhan or [None])[0]
    else:
        P = None

    ung_vien = [{"ma": k, "so_chu_so_lech": d, "so_tep": -n} for d, n, k in uv[:4]]
    if P is None:
        gan = uv[0] if uv else None
        if not uv:
            ly_do = "không có mã cùng hệ nào khác trong hồ sơ để đề xuất"
        elif md is None:
            ly_do = (f"lệch {gan[0]} chữ số so với {gan[2]} (> ngưỡng {NGUONG_CHU_SO}); "
                     "chưa có bản đọc nội dung để xác nhận")
        else:
            ly_do = (f"lệch {gan[0]} chữ số so với {gan[2]} (> ngưỡng {NGUONG_CHU_SO}); "
                     "nội dung không nhắc mã/nhãn ứng viên nào"
                     + (f", lại nhắc chính {X}" if nhac_ma(X) else ""))
        return {**dong, "loai": "chua_phan_loai", "ly_do": ly_do, "ung_vien": ung_vien}

    dP = d_cua[P]
    nhac_X = nhac_ma(X) and not cung_so(P)
    nhac_P = nhac_ma(P) or bool(nhac_nhan(P))
    khac = [k for _, _, k in uv if k != P and (nhac_ma(k) or nhac_nhan(k)) and not cung_so(k)]
    if md is None or not (nhac_X or nhac_P or khac):
        xac_nhan = None
    else:
        xac_nhan = nhac_P and not nhac_X

    ly_chot = []
    if nhac_X:
        ly_chot.append(f"nội dung cũng ghi {X}")
    if khac:
        ly_chot.append(f"nội dung nhắc cả {', '.join(khac)}")
    ngang = [k for d, _, k in uv if k != P and d <= dP]
    if xac_nhan is not True and ngang:
        ly_chot.append(f"{', '.join(ngang)} cũng lệch ≤ {dP} chữ số")
    if dong["so_lan_toan_kho"] > len(tep_X):
        ly_chot.append(f"{X} còn xuất hiện ở hồ sơ khác")

    dong_trich = None
    if md:
        mau_P = _mau_nhac(mau[P])
        nh = nhac_nhan(P)
        for l in md.splitlines():
            if mau_P.search(l):
                dong_trich = _che(l)
                break
        if dong_trich is None and nh:
            for l in md.splitlines():
                if any(re.search(rf"(?<![A-Za-z0-9]){re.escape(w)}(?![A-Za-z0-9])",
                                 khong_dau(l), re.I) for w in nh):
                    dong_trich = _che(l)
                    break

    mx = next(m for m in t0.ma if m.khoa == X)
    if P == M:
        bang_chung = f"{M} là mã đa số: {c[M]}/{co_ma} tệp có mã trong hồ sơ"
    else:
        bang_chung = (f"{P} có {c[P]} tệp trong hồ sơ; mã đa số {M} ({c[M]}/{co_ma}) "
                      "đã có sẵn trong chính tên tệp này" if M in trong_ten else
                      f"{P} có {c[P]} tệp trong hồ sơ, gần hơn mã đa số {M} ({c[M]}/{co_ma})")
    vuot = dP > NGUONG_CHU_SO
    return {
        **dong, "loai": "loi_go",
        "ly_do": f"lệch {dP} chữ số so với {P}, chỉ một tên tệp mang"
                 + (" — vượt ngưỡng, nội dung xác nhận" if vuot else ""),
        "de_xuat": {
            "duong_dan": t0.rel,
            "ma_hien_tai": X,
            "ma_de_xuat": P,
            "so_chu_so_lech": dP,
            "ten_hien_tai": t0.ten,
            "ten_de_xuat": t0.ten[:mx.dau] + P + t0.ten[mx.cuoi:],
            "bang_chung_da_so": bang_chung,
            "ung_vien": ung_vien,
            "vuot_nguong": vuot,
            "xac_nhan_noi_dung": xac_nhan,
            "noi_dung": {
                "co_ban_doc": md is not None,
                "nhac_ma_de_xuat": nhac_ma(P),
                "nhac_nhan_de_xuat": nhac_nhan(P),
                "nhac_ma_lac": nhac_X,
                "nhac_ung_vien_khac": khac,
                "dong_trich": dong_trich,
            },
            "can_nguoi_chot": bool(ly_chot),
            "ly_do_can_chot": ly_chot,
            "trang_thai": TRANG_THAI_DE_XUAT,
        },
    }


def _thu_muc_mang_so(ds: list[Tep], so: int) -> list[str]:
    mau_so = re.compile(rf"^0*{so}(?!\d)")
    out = set()
    for t in ds:
        con = t.thu_muc_con()
        for i, d in enumerate(con):
            if mau_so.match(d):
                out.add("/".join(con[:i + 1]))
    return sorted(out)


def _lien_ket(ma_lac, theo_hs, mau, goc_o_hs) -> list[dict]:
    nhom: dict[tuple, list] = defaultdict(list)
    for r in ma_lac:
        if r["loai"] == "danh_so_song_song":
            nhom[(r["ho_so"], r["lien_ket_goc"])].append(r)
    out = []
    for (hs, goc), rs in sorted(nhom.items()):
        ds = [t for t in theo_hs[hs] if any(mau[k].goc == goc for k in t.khoa)]
        so = int(mau[rs[0]["ma_lac"]].so)
        out.append({
            "ho_so": hs, "ma_ho_so": rs[0]["ma_da_so"], "goc": goc,
            "bien_the": sorted(r["ma_lac"] for r in rs),
            "so_tep": len(ds),
            "thu_muc_con_mang_so": _thu_muc_mang_so(theo_hs[hs], so),
            "thu_muc_chua_tep": sorted({"/".join(t.thu_muc_con()) for t in ds}),
            "noi_khac": sorted(goc_o_hs[goc] - {hs}),
            "tep": [t.rel for t in ds],
        })
    return out


def _giao_nguoi(ma_lac, theo_hs, so_hs, ma_da_so, nhan_hs, mau, store) -> list[dict]:
    out = []
    for r in ma_lac:
        if r["loai"] != "de_nham_ho_so":
            continue
        hs, X, M = r["ho_so"], r["ma_lac"], r["ma_da_so"]
        mX = mau[X]
        tep_X = [t for t in theo_hs[hs] if X in t.khoa]
        rieng = sorted(g for g, m in ma_da_so.items() if g != hs and (
            m == X or (mau[m].tien_to == mX.tien_to and so_hs[g] == int(mX.so))))
        mau_X = _mau_nhac(mX)
        khai = set()
        for t in tep_X:
            con = t.thu_muc_con()
            for i, d in enumerate(con):
                if mau_X.search(d):
                    khai.add("/".join(con[:i + 1]))
        serial = sorted({m["serial"] for t in tep_X if (m := SERIAL.search(_than(t.ten)))})
        out.append({
            "ho_so": hs, "ma": X, "ma_da_so": M,
            "ten_nhan": r["ten_nhan"], "nhan_thu_muc": sorted(nhan_hs[hs]),
            "co_thu_muc_ho_so_rieng": bool(rieng), "thu_muc_ho_so_rieng": rieng,
            "thu_muc_con_khai_ma": sorted(khai),
            "serial_trong_ten": serial,
            "tep_de_nham": [_tep_ra(t, store) for t in tep_X if M not in t.khoa],
            "tep_chung": [_tep_ra(t, store) for t in tep_X if M in t.khoa],
            "trang_thai": TRANG_THAI_GIAO,
        })
    return out


def _ban_giao_serial(teps, tu_chung, store) -> list[dict]:
    nhom: dict[str, list] = defaultdict(list)
    for t in teps:
        if m := SERIAL.search(_than(t.ten)):
            nhom[m["serial"]].append((t, m["ngay"]))
    out = []
    for serial, ds in sorted(nhom.items()):
        nhan = nhom_tm = None
        for t, _ in ds:
            if n := NHAN_NHOM.search(_than(t.con)):
                nhan, nhom_tm = n["nhan"].strip(), n["nhom"]
                break
        if nhan is None:
            tu = sorted({w for t, _ in ds for w in token_ten(t.con)[0] - tu_chung})
            nhan = " ".join(tu) or None
        out.append({
            "serial": serial, "nhan": nhan, "nhom": nhom_tm,
            "ngay_trong_ten": ds[0][1],
            "ho_so": sorted({t.ho_so for t, _ in ds if t.ho_so}),
            "ma_trong_ten": sorted({k for t, _ in ds for k in t.khoa}),
            "tep": [{**_tep_ra(t, store), "ngay_trong_ten": ngay} for t, ngay in ds],
            "trang_thai": "bàn giao sổ số hiệu (q4); sổ này không đối chiếu serial",
        })
    return out


def _doi_chieu(ma_lac, so_ban_sach) -> list[dict]:
    """Đối chiếu đề xuất đổi tên mà sổ bản sạch đã ghi với phân loại ở đây."""
    if not so_ban_sach or not Path(so_ban_sach).exists():
        return []
    ds = json.loads(Path(so_ban_sach).read_text("utf-8")).get("de_xuat_doi_ten") or []
    theo_tep = {(t["duong_dan"], r["ma_lac"]): r for r in ma_lac for t in r["tep_lo_ra"]}
    out = []
    for e in ds:
        dd = _nfc(e.get("duong_dan") or "")
        hien = tach_ma_dau(e.get("ma_hien_tai") or "")[0]
        de = tach_ma_dau(e.get("ma_de_xuat") or "")[0]
        kh = hien[0].khoa if hien else None
        kd = de[0].khoa if de else None
        r = theo_tep.get((dd, kh))
        if kh == kd:
            khop, ghi = None, "cùng một mã, chỉ khác cách viết — không phải mã lạc"
        elif r is None:
            khop, ghi = False, f"sổ này không ghi {kh} ở tệp này là mã lạc"
        elif r["loai"] == "loi_go" and r["de_xuat"]["ma_de_xuat"] == kd:
            khop, ghi = True, "cùng đề xuất"
        else:
            khop = False
            ghi = f"sổ này xếp {r['loai']}" + (
                f", đề xuất {r['de_xuat']['ma_de_xuat']}" if "de_xuat" in r else "")
        out.append({"duong_dan": dd, "ma_hien_tai": e.get("ma_hien_tai"),
                    "ma_de_xuat_so_kia": e.get("ma_de_xuat"),
                    "loai_o_day": r["loai"] if r else None,
                    "ma_de_xuat_o_day": (r.get("de_xuat") or {}).get("ma_de_xuat") if r else None,
                    "khop": khop, "ghi_chu": ghi})
    return out


# ── Tự kiểm ──────────────────────────────────────────────────────────────

def kiem_so(so: dict) -> list[str]:
    """Bất biến của sổ; trả danh sách lỗi (rỗng là đạt)."""
    loi = []
    giao = {(g["ho_so"], g["ma"]) for g in so["giao_nguoi_xu_ly"]}
    lk = {(l["ho_so"], b) for l in so["lien_ket_so_tra_cuu"] for b in l["bien_the"]}
    for r in so["ma_lac"]:
        ten = f"{r['ho_so']} · {r['ma_lac']}"
        if r["loai"] not in LOAI:
            loi.append(f"{ten}: loại lạ {r['loai']}")
        if not r["ma_da_so"] or r["ma_da_so"] == r["ma_lac"] or r["so_tep_da_so"] < 1:
            loi.append(f"{ten}: thiếu mã đa số")
        if r["so_lan_xuat_hien"] != len(r["tep_lo_ra"]) or not r["tep_lo_ra"]:
            loi.append(f"{ten}: số lần xuất hiện ≠ số tệp lộ ra")
        for t in r["tep_lo_ra"]:
            if not t["duong_dan"].startswith(r["ho_so"] + "/"):
                loi.append(f"{ten}: tệp ngoài hồ sơ")
            if t["duong_dan"] != _nfc(t["duong_dan"]) or t["doc_id"] != doc_id_for(t["duong_dan"]):
                loi.append(f"{ten}: đường dẫn chưa NFC hoặc doc_id lệch")
        if ("de_xuat" in r) != (r["loai"] == "loi_go"):
            loi.append(f"{ten}: đề xuất chỉ dành cho lỗi gõ")
        if r["loai"] == "loi_go":
            d = r["de_xuat"]
            if d["ma_de_xuat"] == r["ma_lac"] or d["ten_de_xuat"] == d["ten_hien_tai"]:
                loi.append(f"{ten}: đề xuất không đổi gì")
            if d["vuot_nguong"] and d["xac_nhan_noi_dung"] is not True:
                loi.append(f"{ten}: vượt ngưỡng mà nội dung không xác nhận")
        if r["loai"] == "de_nham_ho_so" and ((r["ho_so"], r["ma_lac"]) not in giao or not r["ten_nhan"]):
            loi.append(f"{ten}: để nhầm mà thiếu dòng giao người hoặc tên nhãn")
        if r["loai"] == "danh_so_song_song" and (r["ho_so"], r["ma_lac"]) not in lk:
            loi.append(f"{ten}: song song mà thiếu liên kết")
    t = so["tom_tat"]
    if sum(t["theo_loai"].values()) != len(so["ma_lac"]):
        loi.append("tóm tắt: tổng theo loại ≠ số dòng")
    return loi


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kho", type=Path, default=PRIVATE, help="kho hồ sơ gốc (chỉ đọc)")
    ap.add_argument("--store", type=Path, default=DEFAULT_STORE, help="kho parse ADE")
    ap.add_argument("--so-ban-sach", type=Path, default=SO_BAN_SACH,
                    help="sổ bản sạch để đối chiếu đề xuất đổi tên")
    ap.add_argument("--ra", type=Path, default=DEFAULT_LEDGER, help="sổ JSON ghi ra")
    ap.add_argument("--khong-ghi", action="store_true", help="chỉ in tóm tắt, không ghi sổ")
    a = ap.parse_args()

    if not a.kho.is_dir():
        print(f"không thấy kho hồ sơ: {a.kho}", file=sys.stderr)
        return 2

    truoc = chup_kho(a.kho)
    so = lap_so(a.kho, a.store, a.so_ban_sach)
    if chup_kho(a.kho) != truoc:
        print("KHO GỐC ĐÃ ĐỔI trong lúc chạy — dừng, không ghi sổ", file=sys.stderr)
        return 1
    loi = kiem_so(so)
    for l in loi:
        print(f"SỔ HỎNG: {l}", file=sys.stderr)

    if not a.khong_ghi and not loi:
        a.ra.parent.mkdir(parents=True, exist_ok=True)
        a.ra.write_text(json.dumps(so, ensure_ascii=False, indent=2), "utf-8")
        a.ra.chmod(0o600)

    t = so["tom_tat"]
    print(f"{t['so_tep']} tệp, {t['so_tep_trong_thu_muc_ho_so']} trong {t['so_ho_so']} thư mục "
          f"hồ sơ ({t['so_ho_so_co_ma_da_so']} có mã đa số), "
          f"{t['so_tep_ngoai_thu_muc_ho_so']} ngoài")
    print(f"mã lạc: {t['so_ma_lac']} dòng ở {t['so_ho_so_co_ma_lac']} hồ sơ — "
          + ", ".join(f"{k} {v}" for k, v in t["theo_loai"].items()))
    print(f"  đề xuất cần người chốt: {t['so_de_xuat_can_nguoi_chot']}, "
          f"vượt ngưỡng có nội dung xác nhận: {t['so_de_xuat_vuot_nguong']}")
    print(f"liên kết số tra cứu: {t['so_lien_ket_so_tra_cuu']}; giao người: {t['so_giao_nguoi']} mã, "
          f"{t['so_tep_de_nham']} tệp để nhầm + {t['so_tep_chung_trong_giao']} tệp chung")
    print(f"tệp chung hai hồ sơ: {t['so_tep_nhieu_ho_so']}; bỏ qua (không phải mã hồ sơ): "
          f"{t['so_bo_qua']}; serial bàn giao q4: {t['so_serial']} ({t['so_tep_co_serial']} tệp)")
    dc = t["doi_chieu_so_ban_sach"]
    print(f"đối chiếu sổ bản sạch: khớp {dc['khop']}, lệch {dc['lech']}, "
          f"không phải mã lạc {dc['khong_phai_ma_lac']}")
    if not a.khong_ghi and not loi:
        print(f"sổ: {a.ra}")
    return 1 if loi else 0


if __name__ == "__main__":
    raise SystemExit(main())
