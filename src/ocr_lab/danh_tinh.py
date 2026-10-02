"""Danh tính hồ sơ: khoá chuẩn, bí danh, bản trùng và hàng chờ xung đột.

VÌ SAO CÓ MODULE NÀY
────────────────────
Các sổ trước (hợp đồng, ngày, vai ảnh, bản sạch) mỗi sổ tự suy "tệp này thuộc
hồ sơ nào" theo một kiểu riêng — từ thư mục, từ tên tệp, hoặc từ số in trong
văn bản. Bốn kiểu gãy đo được trên kho thật:

  1. Một chứng từ dùng chung cho nhiều hồ sơ (một lần chuyển tiền trả cho ba
     nhãn) bị ép vào trường một-một ⟶ hai trong ba hồ sơ mất chứng từ.
  2. Một mã viết hai kiểu vì thừa số 0 đệm ⟶ hai khoá cho một hồ sơ.
  3. Một hồ sơ mang nhiều mã theo giai đoạn (mã tư vấn rồi mã đăng ký), cộng
     bản sao y hệt nằm rải trong `New folder`, `(1)` ⟶ đếm trùng.
  4. Một tệp mang ba danh tính lệch nhau: mã trên tên tệp, thư mục chứa nó,
     và tiêu đề kênh chat trong nội dung.

Module này là chỗ trả lời chung cho câu hỏi đó; `scripts/so_danh_tinh.py` chỉ
đọc kho, băm tệp rồi gọi `dung_so`.

KHÔNG TỰ CHỌN DANH TÍNH
───────────────────────
Tên tệp nói một hồ sơ, thư mục nói hồ sơ khác: không có cách nào biết bên nào
sai — có thể tên gõ nhầm, cũng có thể tệp bị đặt nhầm chỗ. Cái biết chắc là
CÓ mâu thuẫn. Vậy ghi cả hai, gắn `xung_dot`, đẩy vào hàng chờ với
`trang_thai: cho_nguoi_xac_nhan`. Tệp vẫn được xếp tạm theo chỗ nó nằm, và
bản ghi nói rõ đó là xếp tạm.

Ngoại lệ hẹp duy nhất là thừa đúng một số 0 BÊN TRONG mà kết quả trùng một mã
chính đường dẫn khai ra — thư mục `Thanh toan (NH4001, NH4002)` chứa tệp
`NH40001…`. Khi đó có mỏ neo viết tay độc lập với tên tệp; mã gốc vẫn ghi ở
`ma_goc`. Chữ số khác nhau (`NH955` trong thư mục `959`) thì không có mỏ neo
nào, nên là xung đột.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass

__all__ = ["Ma", "RE_MA", "bo_dau", "chuan_ma", "ma_tren_ten_tep",
           "ma_tren_duong_dan", "doc_thu_muc_ho_so", "sua_so_0_thua",
           "la_nhap", "kenh_id", "dung_so", "gop_hang_cho", "kiem_tra",
           "CHO_NGUOI_XAC_NHAN"]

CHO_NGUOI_XAC_NHAN = "cho_nguoi_xac_nhan"


# ── Chuỗi ────────────────────────────────────────────────────────────────

def _nfc(s: str) -> str:
    """macOS trả tên tệp ở NFD; mọi so sánh chuỗi phải quy về NFC trước."""
    return unicodedata.normalize("NFC", s)


def bo_dau(s: str) -> str:
    """Bỏ dấu, hạ chữ thường. `đ` phải thay TRƯỚC NFD — NFD không tách nó."""
    s = _nfc(s).replace("Đ", "D").replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def chuan_ma(ma: str) -> str:
    """Quy mã hồ sơ về dạng so được: bỏ khoảng trắng, bỏ số 0 vô nghĩa.

    Giữ nguyên đuôi nước và mọi dấu phân cách khác — đây là phép quy của sổ
    bản sạch, đủ hẹp để không gộp nhầm hai hồ sơ (`NH955` ≠ `NH959` vì chữ số
    khác nhau, không phải vì số 0 thừa). Khoá hồ sơ thì dùng `Ma.khoa`.
    """
    if not ma:
        return ""
    s = _nfc(ma).upper().replace(" ", "")
    return re.sub(r"\d+", lambda m: str(int(m.group())), s)


# ── Mã hồ sơ ─────────────────────────────────────────────────────────────

#: Một mã: tiền tố, số, số vụ việc sau gạch (`TV012-77` = tư vấn 12 của vụ
#: 77), đuôi nước (`.US`, `,US`, `. US`) và số giai đoạn (`TV3001.3`).
RE_MA = re.compile(
    r"(?<![A-Z0-9])(?P<tien_to>NH|BQ|TV)(?P<so>\d{2,6})(?:[-–](?P<vu>\d{1,5}))?"
    r"(?:\s*[.,]\s*(?P<nuoc>US|VN|EU)(?![A-Z]))?(?:\.(?P<giai_doan>\d{1,2})(?!\d))?",
    re.IGNORECASE,
)

#: Thư mục hồ sơ: `500. US. TEN NHAN`, `77. A v. B`.
RE_THU_MUC_HO_SO = re.compile(r"^(\d{2,4})\s*\.?\s*(US|VN)?(?![A-Z])", re.IGNORECASE)


@dataclass(frozen=True)
class Ma:
    tien_to: str
    so: str
    vu: str = ""
    nuoc: str = ""
    goc: str = ""

    @classmethod
    def tu_khop(cls, m: re.Match) -> "Ma":
        return cls(m["tien_to"].upper(), m["so"], m["vu"] or "",
                   (m["nuoc"] or "").upper(), m.group(0).strip())

    @property
    def khoa(self) -> str:
        """Khoá chuẩn: bỏ số 0 đệm, bỏ đuôi nước và số giai đoạn."""
        k = f"{self.tien_to}{int(self.so)}"
        return f"{k}-{int(self.vu)}" if self.vu else k

    @property
    def than(self) -> str:
        """Thân mã đúng như người gõ (giữ số 0), bỏ đuôi — dùng làm bí danh."""
        k = f"{self.tien_to}{self.so}"
        return f"{k}-{self.vu}" if self.vu else k

    @property
    def ho_so(self) -> int | None:
        """Số hồ sơ mã này trỏ tới. Mã tư vấn trơn (`TV3001`) là mã giai đoạn
        của hồ sơ chứa nó, không tự trỏ tới hồ sơ nào."""
        if self.tien_to == "TV":
            return int(self.vu) if self.vu else None
        return int(self.so)

    def doi_so(self, so: int) -> "Ma":
        """Đổi số hồ sơ mà mã trỏ tới — với `TV…-n` đó là số vụ việc `n`."""
        if self.tien_to == "TV" and self.vu:
            return Ma(self.tien_to, self.so, str(so), self.nuoc, self.goc)
        return Ma(self.tien_to, str(so), self.vu, self.nuoc, self.goc)


def ma_tren_ten_tep(ten: str) -> list[Ma]:
    """Các mã đứng đầu tên tệp: `NH4001.US, BQ402.US_…` cho hai mã.

    Chỉ mã ĐẦU tên mới là lời tên tệp tự nhận; số nằm giữa tên (số hoá đơn,
    số đơn) không phải mã hồ sơ.
    """
    s, pos, ra = _nfc(ten).strip(), 0, []
    while (m := RE_MA.match(s, pos)):
        ra.append(Ma.tu_khop(m))
        sep = re.compile(r"\s*,\s*").match(s, m.end())
        if not sep or sep.end() == m.end():
            break
        pos = sep.end()
    return ra


def ma_tren_duong_dan(thu_muc: list[str]) -> list[Ma]:
    """Mã mà thư mục con khai ra, ở bất kỳ đâu trong tên: `Thanh toan (NH4001)`."""
    return [Ma.tu_khop(m) for t in thu_muc for m in RE_MA.finditer(_nfc(t))]


def doc_thu_muc_ho_so(ten: str) -> tuple[int, str] | None:
    """(số hồ sơ, nhãn) từ tên thư mục hồ sơ: `500. US. X` ⟶ (500, '500.US')."""
    m = RE_THU_MUC_HO_SO.match(_nfc(ten).strip())
    if not m:
        return None
    nuoc = (m[2] or "").upper()
    return int(m[1]), f"{int(m[1])}.{nuoc}" if nuoc else str(int(m[1]))


def sua_so_0_thua(so: int, neo: set[int]) -> int | None:
    """Bỏ đúng một số 0 bên trong `so`; trả kết quả nếu nó trùng DUY NHẤT một mỏ neo."""
    s = str(so)
    trung = {int(s[:i] + s[i + 1:]) for i, c in enumerate(s) if c == "0" and i > 0} & neo
    return trung.pop() if len(trung) == 1 else None


# ── Tệp ──────────────────────────────────────────────────────────────────

#: Số bản 0.x: `_v0.1C`, `_ver0.2Ha`. Bản 1.0 trở lên không phải nháp.
RE_BAN_NHAP = re.compile(r"(?:^|[\s_.-])v(?:er)?\s*0\.\d+", re.IGNORECASE)
DAU_HIEU_NHAP = ("du thao", "draft")


def la_nhap(rel: str) -> bool:
    """Bản nháp theo đường dẫn: thư mục/tên có `du thao`/`draft`, hoặc số bản 0.x."""
    return (any(k in bo_dau(rel) for k in DAU_HIEU_NHAP)
            or bool(RE_BAN_NHAP.search(_nfc(rel).rsplit("/", 1)[-1])))


def _diem_ban_chinh(rel: str) -> tuple:
    """Khoá sắp xếp chọn bản chính trong các bản y hệt nhau; nhỏ hơn là tốt hơn."""
    ten = rel.rsplit("/", 1)[-1]
    return (la_nhap(rel),
            "new folder" in bo_dau(rel),
            bool(re.search(r"\(\d+\)(?=\.[^.]+$)", ten)),          # `…(1).pdf`
            bool(re.search(r"(\.[a-z0-9]{2,4})\1$", ten.lower())),  # `….pdf.pdf`
            rel.count("/"), rel)


#: Dấu hiệu chữ ký trên tên tệp hợp đồng, xếp từ mạnh tới yếu. Chỉ là điều
#: tên tệp KHAI — sổ ghi lại căn cứ để người đọc biết đã không nhìn chữ ký.
DAU_HIEU_KY = (("both signed", "fully executed", "da ky 2 ben", "hai ben ky"),
               ("signed", "scan", "da ky"))


def _hang_chu_ky(rel: str) -> tuple[int, str]:
    if la_nhap(rel):
        return len(DAU_HIEU_KY) + 1, "ban_nhap"
    ten = bo_dau(rel.rsplit("/", 1)[-1])
    for hang, dau in enumerate(DAU_HIEU_KY):
        for d in dau:
            if d in ten:
                return hang, f"ten_tep: {d}"
    return len(DAU_HIEU_KY), "ten_tep_khong_noi_da_ky"


# ── Kênh chat ────────────────────────────────────────────────────────────

#: Từ không mang danh tính trong tiêu đề kênh: dấu nối hai bên và tên phòng.
TU_BO_KENH = {"x", "ip"}
#: Tên hãng mình, bên nào của mọi kênh cũng có. So theo bộ chữ cái để bắt cả
#: lỗi gõ đảo chữ (đo thật trên kho: một kênh ghi sai tên hãng như vậy).
TEN_HANG = "refiny"


def kenh_id(tieu_de: str) -> str:
    """Khoá kênh từ tiêu đề: băm ngắn của tiêu đề đã bỏ dấu, tên hãng và từ nối.

    Bỏ dấu để hai bản OCR của cùng tiêu đề (lệch `ế`/`ể`) về một kênh. Không
    chữ nào của tiêu đề lọt vào khoá — tiêu đề kênh thường chứa tên người; bản
    đầy đủ chỉ nằm trong bản ghi kênh ở `~/.private`.
    """
    s = bo_dau(tieu_de).replace("×", " x ")
    tu = [re.sub(r"[^a-z0-9]", "", t) for t in re.split(r"[\s_|/-]+", s)]
    tu = [t for t in tu if t and t not in TU_BO_KENH and sorted(t) != sorted(TEN_HANG)]
    if not tu:
        return "k-khong-ten"
    return "k-" + hashlib.sha256("-".join(tu).encode()).hexdigest()[:10]


# ── Loại hồ sơ ───────────────────────────────────────────────────────────

def loai_ho_so(nhom: str) -> str:
    """Loại theo nhóm dịch vụ (thư mục cấp 2)."""
    n = bo_dau(nhom)
    if "c&d" in n or "tranh chap" in n or "dispute" in n:
        return "tranh_chap"
    if "go report" in n:
        return "go_report"
    if "dang ky" in n:
        return "dang_ky"
    return "khac"


#: Hồ sơ tranh chấp: sổ không tóm tắt được lập luận, nên thay vì hứa, nó chỉ
#: sẵn tệp phải mở. Vai nhận theo từ khoá trên đường dẫn trong hồ sơ; thứ tự
#: quan trọng — `Response C&D Letters` là thư phản hồi, không phải thư cảnh báo.
VAI_TRANH_CHAP = (
    ("thu_phan_hoi", ("response", "phan hoi")),
    ("dam_phan", ("negotiation", "dam phan", "round")),
    ("thu_canh_bao", ("cease", "desist", "unauthori", "infring", "canh bao")),
)
TU_KHAI_TRANH_CHAP = "khong_tom_tat_duoc_lap_luan_phai_mo_toan_van"


def _vai_tranh_chap(rel_trong_ho_so: str) -> str | None:
    n = bo_dau(rel_trong_ho_so)
    for vai, tu in VAI_TRANH_CHAP:
        if any(t in n for t in tu):
            return vai
    return None


# ── Phân giải một tệp ────────────────────────────────────────────────────

def _phan_giai(rel: str) -> dict | None:
    """Danh tính một tệp, theo SỐ hồ sơ. None nếu tệp không nằm trong hồ sơ nào."""
    parts = _nfc(rel).split("/")
    if len(parts) < 4 or not (vv := doc_thu_muc_ho_so(parts[2])):
        return None
    m_so = vv[0]
    F, D = ma_tren_ten_tep(parts[-1]), ma_tren_duong_dan(parts[3:-1])
    nd = {c.ho_so for c in D if c.ho_so is not None}
    xung_dot, sua, ma_tep = [], [], []
    if nd and m_so not in nd:
        xung_dot.append("ma_duong_dan_khac_thu_muc")

    for c in F:
        n = c.ho_so
        if n is not None and n != m_so and n not in nd and (r := sua_so_0_thua(n, nd)):
            sua.append({"ma_goc": c.goc, "ma": c.doi_so(r).khoa,
                        "ly_do": "thua_so_0; neo: ma khai tren duong dan"})
            c = c.doi_so(r)
        ma_tep.append(c)

    nf = {c.ho_so for c in ma_tep if c.ho_so is not None}
    xep_tam = nd | {m_so}
    if not nf or nf & xep_tam:
        thuoc = nf or xep_tam
    else:
        xung_dot.append("ma_ten_tep_khac_thu_muc")
        thuoc = xep_tam

    nguon = {n: sorted(({"ten_tep"} if n in nf else set())
                       | ({"duong_dan"} if n in nd else set())
                       | ({"thu_muc"} if n == m_so else set())) for n in thuoc}
    return {"m_so": m_so, "m_nhan": vv[1], "nhom": parts[1], "ma_tep": ma_tep,
            "ma_duong_dan": D, "nf": nf, "thuoc": thuoc, "nguon": nguon,
            "xung_dot": xung_dot, "sua_ma": sua, "trong_ho_so": "/".join(parts[3:])}


# ── Dựng sổ ──────────────────────────────────────────────────────────────

def _so_ho_so(nhan: str) -> int:
    if (m := re.match(r"\d+", nhan)) is None:
        raise ValueError(f"nhãn hồ sơ không bắt đầu bằng số: {nhan!r}")
    return int(m.group())


def dung_so(tep: list[tuple[str, str]], *, doc_id_for,
            kenh_theo_doc: dict[str, dict] | None = None,
            hop_dong: list[dict] | None = None) -> dict:
    """Dựng sổ danh tính từ danh sách (đường dẫn tương đối, băm nội dung).

    `kenh_theo_doc`: doc_id ⟶ {tieu_de, thanh_vien} từ sổ ô dữ kiện.
    `hop_dong`: bản ghi sổ hợp đồng (đã gộp theo số trong văn bản).
    """
    kenh_theo_doc = kenh_theo_doc or {}
    tep = sorted((_nfc(r), b) for r, b in tep)
    pg = {r: _phan_giai(r) for r, _ in tep}
    trong = {r: p for r, p in pg.items() if p}     # tệp nằm trong hồ sơ

    # Nhãn của mọi số hồ sơ: thư mục nếu có, không thì từ đuôi nước trên mã.
    nhan: dict[int, str] = {}
    thu_muc: dict[int, str] = {}
    nhom: dict[int, str] = {}
    for r, p in pg.items():
        if p:
            nhan[p["m_so"]] = p["m_nhan"]
            thu_muc[p["m_so"]] = r.split("/")[2]
            nhom[p["m_so"]] = p["nhom"]
    nuoc: dict[int, Counter] = defaultdict(Counter)
    for p in filter(None, pg.values()):
        for c in p["ma_tep"] + p["ma_duong_dan"]:
            if c.ho_so is not None:
                nuoc[c.ho_so][c.nuoc] += 1
    for n, dem in nuoc.items():
        if n not in nhan:
            nc = sorted((k for k in dem if k), key=lambda k: (-dem[k], k))
            nhan[n] = f"{n}.{nc[0]}" if nc else str(n)
    # Chỉ số nằm trong thư mục hoặc được xếp vào mới là hồ sơ; mã xung đột
    # chỉ có nhãn để hiện trong hàng chờ, không thành hồ sơ.
    co_ho_so = set(thu_muc) | {n for p in filter(None, pg.values()) for n in p["thuoc"]}

    # Mã giai đoạn trơn nằm ở hai hồ sơ thì không biết nó thuộc hồ sơ nào.
    giai_doan_o: dict[str, set[int]] = defaultdict(set)
    for p in filter(None, pg.values()):
        for c in p["ma_tep"]:
            if c.ho_so is None:
                giai_doan_o[c.khoa].add(p["m_so"])
    for p in filter(None, pg.values()):
        if any(c.ho_so is None and len(giai_doan_o[c.khoa]) > 1 for c in p["ma_tep"]):
            p["xung_dot"].append("ma_giai_doan_o_nhieu_ho_so")

    # Mã nào thuộc hồ sơ nào — tính từ tên tệp TRƯỚC mọi bản ghi, để các sổ
    # khác (số hợp đồng in trong văn bản) nối được vào cùng một khoá.
    ma_chinh: dict[int, Counter] = defaultdict(Counter)
    ma_cua: dict[int, set[Ma]] = defaultdict(set)
    for p in filter(None, pg.values()):
        for c in p["ma_tep"]:
            if c.ho_so is None and "ma_giai_doan_o_nhieu_ho_so" not in p["xung_dot"]:
                ma_cua[p["m_so"]].add(c)
            elif c.ho_so is not None and "ma_ten_tep_khac_thu_muc" not in p["xung_dot"]:
                ma_cua[c.ho_so].add(c)
                ma_chinh[c.ho_so][c.khoa] += 1
    chu_khoa = {c.khoa: n for n, cs in ma_cua.items() for c in cs}

    def nhans(so_set) -> list[str]:
        return [nhan[n] for n in sorted(so_set)]

    # Bản ghi từng tệp.
    ban_ghi_tep: dict[str, dict] = {}
    ngoai_ho_so = []
    for r, bam in tep:
        p = pg[r]
        did = doc_id_for(r)
        if not p:
            ngoai_ho_so.append({"doc_id": did, "duong_dan": r, "bam_noi_dung": bam})
            continue
        k = kenh_theo_doc.get(did)
        nhap = la_nhap(r)
        ban_ghi_tep[r] = {
            "doc_id": did, "duong_dan": r, "bam_noi_dung": bam,
            "thu_muc_ho_so": p["m_nhan"],
            # Mã đúng như tên tệp viết — mã đã sửa vẫn giữ chữ gốc ở đây.
            "bi_danh": sorted({c.goc for c in p["ma_tep"]}),
            "thuoc_ho_so": nhans(p["thuoc"]),
            "nguon_ma": sorted({x for v in p["nguon"].values() for x in v}),
            "nguon_ho_so": {nhan[n]: v for n, v in sorted(p["nguon"].items())},
            "nhap": nhap,
            "trang_thai": CHO_NGUOI_XAC_NHAN if p["xung_dot"] else ("nhap" if nhap else "dung_duoc"),
            "xung_dot": list(p["xung_dot"]),
            "kenh": kenh_id(k["tieu_de"]) if k else None,
            "la_ban_sao_cua": None,
        }
        if p["sua_ma"]:
            ban_ghi_tep[r]["sua_ma"] = p["sua_ma"]

    # Số hồ sơ đọc trong VĂN BẢN (sổ hợp đồng) lệch chỗ tệp được xếp: một danh
    # tính nữa, cũng chỉ ghi lại và chờ người. Hợp đồng không in số thì mã của
    # nó lấy từ tên tệp, so với chính nó là vòng tròn — bỏ qua.
    theo_doc = {b["doc_id"]: b for b in ban_ghi_tep.values()}
    for hd in hop_dong or []:
        if not hd.get("co_so_trong_van_ban") or (n := _chu_hop_dong(hd, chu_khoa, nhan)) is None:
            continue
        for t in hd.get("tep", []):
            b = theo_doc.get(t["ade_id"])
            if b and nhan.get(n, str(n)) not in b["thuoc_ho_so"]:
                b["xung_dot"].append("ma_noi_dung_khac_ten_tep")
                b["ho_so_trong_van_ban"] = {"ho_so": nhan.get(n, str(n)), "so_hop_dong": hd["khoa"]}
                b["trang_thai"] = CHO_NGUOI_XAC_NHAN

    # Gộp bản y hệt theo băm nội dung.
    theo_bam: dict[str, list[str]] = defaultdict(list)
    for r, b in ban_ghi_tep.items():
        theo_bam[b["bam_noi_dung"]].append(r)
    tai_lieu = []
    for bam, rs in sorted(theo_bam.items(), key=lambda kv: min(kv[1], key=_diem_ban_chinh)):
        rs.sort(key=_diem_ban_chinh)
        chinh = ban_ghi_tep[rs[0]]
        for r in rs[1:]:
            ban_ghi_tep[r]["la_ban_sao_cua"] = chinh["doc_id"]
            ban_ghi_tep[r]["cach_gop"] = "bam_noi_dung"
        thuoc = sorted({n for r in rs for n in trong[r]["thuoc"]})
        nguon: dict[str, set] = defaultdict(set)
        for r in rs:
            for n, v in trong[r]["nguon"].items():
                nguon[nhan[n]].update(v)
        xd = sorted({x for r in rs for x in ban_ghi_tep[r]["xung_dot"]})
        tl = {
            "id": chinh["doc_id"], "bam_noi_dung": bam,
            "ban_chinh": chinh["duong_dan"],
            "thuoc_ho_so": nhans(thuoc),
            "nguon_ma": sorted({x for v in nguon.values() for x in v}),
            "nguon_ho_so": {k: sorted(v) for k, v in nguon.items()},
            "vai": "chung_tu_dung_chung" if len(thuoc) > 1 else None,
            "kenh": sorted({ban_ghi_tep[r]["kenh"] for r in rs if ban_ghi_tep[r]["kenh"]}),
            "xung_dot": xd,
            "trang_thai": (CHO_NGUOI_XAC_NHAN if xd else
                           "nhap" if all(ban_ghi_tep[r]["nhap"] for r in rs) else "dung_duoc"),
            "so_ban": len(rs),
            "tep": [ban_ghi_tep[r] for r in rs],
        }
        tai_lieu.append(tl)

    # Hồ sơ.
    ho_so: dict[int, dict] = {}
    for n in sorted(co_ho_so):
        ho_so[n] = {"ho_so": nhan[n], "so": n, "co_thu_muc": n in thu_muc,
                    "thu_muc": thu_muc.get(n), "loai_ho_so": loai_ho_so(nhom[n]) if n in nhom else None,
                    "khoa": None, "ma_chuan": [], "bi_danh": [], "ma_goc_da_sua": [],
                    "ma_xung_dot": [],
                    "nam_trong": [], "so_tep": 0, "so_tai_lieu": 0, "so_ban_trung": 0,
                    "so_tep_thuoc": 0, "tai_lieu": []}
    bam_trong: dict[int, list[str]] = defaultdict(list)     # tệp NẰM trong thư mục
    tep_thuoc: Counter = Counter()                           # tệp THUỘC, kể cả từ nơi khác
    for r, b in ban_ghi_tep.items():
        p = trong[r]
        m = p["m_so"]
        bam_trong[m].append(b["bam_noi_dung"])
        for n in p["thuoc"]:
            tep_thuoc[n] += 1
        for c in p["ma_tep"]:
            if (c.ho_so is None and "ma_giai_doan_o_nhieu_ho_so" in p["xung_dot"]) or (
                    c.ho_so is not None and "ma_ten_tep_khac_thu_muc" in p["xung_dot"]):
                ho_so[m]["ma_xung_dot"].append(c.goc)
        for s in p["sua_ma"]:
            k = RE_MA.fullmatch(s["ma"])
            if k is None or (n := Ma.tu_khop(k).ho_so) is None:
                continue
            if s["ma_goc"] not in ho_so[n]["ma_goc_da_sua"]:
                ho_so[n]["ma_goc_da_sua"].append(s["ma_goc"])
        for n in p["thuoc"]:
            if n != m and nhan[m] not in ho_so[n]["nam_trong"] and n not in thu_muc:
                ho_so[n]["nam_trong"].append(nhan[m])
    for n, h in ho_so.items():
        if ma_chinh[n]:
            h["khoa"] = sorted(ma_chinh[n].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        h["ma_chuan"] = sorted({c.khoa for c in ma_cua[n]})
        h["bi_danh"] = sorted({c.than for c in ma_cua[n]})
        h["ma_xung_dot"] = sorted(set(h["ma_xung_dot"]))
        h["so_tep"] = len(bam_trong[n])
        h["so_tai_lieu"] = len(set(bam_trong[n]))
        h["so_ban_trung"] = h["so_tep"] - h["so_tai_lieu"]
        h["so_tep_thuoc"] = tep_thuoc[n]
    for tl in tai_lieu:
        for lb in tl["thuoc_ho_so"]:
            ho_so[_so_ho_so(lb)]["tai_lieu"].append(tl["id"])

    # Hồ sơ tranh chấp tự khai giới hạn và chỉ tệp phải mở.
    for n, h in ho_so.items():
        if h["loai_ho_so"] != "tranh_chap":
            continue
        h["tu_khai"] = TU_KHAI_TRANH_CHAP
        mo: dict[str, list] = defaultdict(list)
        for tl in tai_lieu:
            if h["ho_so"] in tl["thuoc_ho_so"] and tl["trang_thai"] == "dung_duoc":
                if vai := _vai_tranh_chap(trong[tl["ban_chinh"]]["trong_ho_so"]):
                    mo[vai].append({"id": tl["id"], "duong_dan": tl["ban_chinh"]})
        h["phai_mo_toan_van"] = {v: mo[v] for v, _ in VAI_TRANH_CHAP if mo[v]}

    hop_dong_ra = _noi_hop_dong(hop_dong or [], chu_khoa, nhan, ho_so)

    kenh = _dung_kenh(tai_lieu, kenh_theo_doc)
    hang_cho = _dung_hang_cho(tai_lieu, pg, nhan, thu_muc)

    return {
        "tom_tat": {
            "so_tep": len(tep),
            "so_tep_trong_ho_so": len(ban_ghi_tep),
            "so_tep_ngoai_ho_so": len(ngoai_ho_so),
            "so_tai_lieu": len(tai_lieu),
            "so_nhom_ban_trung": sum(1 for t in tai_lieu if t["so_ban"] > 1),
            "so_ban_trung": sum(t["so_ban"] - 1 for t in tai_lieu),
            "so_tai_lieu_dung_chung": sum(1 for t in tai_lieu if t["vai"]),
            "so_ho_so": len(ho_so),
            "so_ho_so_khong_thu_muc": sum(1 for h in ho_so.values() if not h["co_thu_muc"]),
            "so_ma_da_sua": sum(len(b.get("sua_ma", [])) for b in ban_ghi_tep.values()),
            "so_kenh": len(kenh),
            "hang_cho": {"so_ca": len(hang_cho),
                         "theo_loai": dict(Counter(c["xung_dot"] for c in hang_cho))},
        },
        "ho_so": list(ho_so.values()),
        "tai_lieu": tai_lieu,
        "hop_dong": hop_dong_ra,
        "kenh": kenh,
        "hang_cho_xung_dot": hang_cho,
        "ngoai_ho_so": ngoai_ho_so,
    }


def _chu_hop_dong(hd: dict, chu_khoa: dict[str, int], nhan: dict[int, str]) -> int | None:
    """Số hồ sơ chủ của một hợp đồng: mã in trong số hợp đồng, qua khoá chuẩn.

    Mã giai đoạn trơn (`TV3001`) chỉ có chủ khi tên tệp nào đó đã gắn nó vào
    một hồ sơ; mã `NH`/`BQ`/`TV…-n` tự mang số hồ sơ.
    """
    if (ma := hd.get("ma_ho_so")):
        if (m := RE_MA.fullmatch(ma)):
            c = Ma.tu_khop(m)
            return chu_khoa.get(c.khoa, c.ho_so)
        return int(ma) if ma.isdigit() and int(ma) in nhan else None
    tm = hd.get("thu_muc_ho_so") or []
    if len(tm) == 1 and (vv := doc_thu_muc_ho_so(tm[0])):
        return vv[0]
    return None


def _noi_hop_dong(hop_dong, chu_khoa, nhan, ho_so) -> list[dict]:
    """Nối sổ hợp đồng vào hồ sơ qua khoá chuẩn, rồi đếm cổng theo hồ sơ.

    Sổ hợp đồng đã gộp các tệp theo SỐ in trong văn bản; ở đây chỉ chọn bản
    chính trong mỗi hợp đồng và trỏ các bản còn lại về nó. Mã giai đoạn (mã tư
    vấn) được nối về hồ sơ chủ, nên hợp đồng tư vấn chỉ có bản nháp không còn
    bị đếm như hồ sơ thứ hai.
    """
    ra = []
    for hd in hop_dong:
        n = _chu_hop_dong(hd, chu_khoa, nhan)
        chu = nhan.get(n) if n in ho_so else None
        tep = sorted(hd.get("tep", []), key=lambda t: (_hang_chu_ky(t["duong_dan"])[0],
                                                       _diem_ban_chinh(t["duong_dan"])))
        chinh = tep[0] if tep else None
        nhap = all(la_nhap(t["duong_dan"]) for t in tep)
        vai = (hd.get("doi_tac") or {}).get("vai_tro")
        rec = {
            "khoa": hd["khoa"], "loai": hd.get("loai"), "vai_tro": vai,
            "ma_ho_so": hd.get("ma_ho_so"), "ho_so": chu,
            "trang_thai": "nhap" if nhap else "dung_duoc",
            "ban_chinh": ({"doc_id": chinh["ade_id"], "duong_dan": chinh["duong_dan"],
                           "can_cu": _hang_chu_ky(chinh["duong_dan"])[1]} if chinh else None),
            "tep": [{"doc_id": t["ade_id"], "duong_dan": t["duong_dan"],
                     "la_ban_sao_cua": chinh["ade_id"] if chinh and t is not chinh else None,
                     "cach_gop": None if t is chinh else "so_hop_dong",
                     "trang_thai": "nhap" if la_nhap(t["duong_dan"]) else "dung_duoc"}
                    for t in tep],
        }
        ra.append(rec)
        if n is None or n not in ho_so:
            continue
        cong = ho_so[n].setdefault(
            "cong_hop_dong", {"hop_dong_khach_da_ky": [], "nhap": [], "phu_luc": [], "khac": []})
        if nhap:
            cong["nhap"].append(hd["khoa"])
        elif hd.get("loai") == "phu_luc":
            cong["phu_luc"].append(hd["khoa"])
        elif vai == "khach_hang" and hd.get("da_ky"):
            cong["hop_dong_khach_da_ky"].append(hd["khoa"])
        else:
            cong["khac"].append(hd["khoa"])
    for h in ho_so.values():
        if "cong_hop_dong" in h:
            h["cong_hop_dong"]["so_hop_dong_khach_da_ky"] = len(h["cong_hop_dong"]["hop_dong_khach_da_ky"])
    return ra


def _dung_kenh(tai_lieu, kenh_theo_doc) -> list[dict]:
    """Bản ghi kênh: một kênh chạm nhiều hồ sơ, một hồ sơ có nhiều kênh (n–n)."""
    theo: dict[str, dict] = {}
    for tl in tai_lieu:
        for b in tl["tep"]:
            k = kenh_theo_doc.get(b["doc_id"])
            if not k:
                continue
            kid = kenh_id(k["tieu_de"])
            e = theo.setdefault(kid, {"tieu_de": Counter(), "thanh_vien": set(),
                                      "tep": 0, "tai_lieu": [], "thuoc": set()})
            e["tieu_de"][k["tieu_de"]] += 1
            if k.get("thanh_vien") is not None:
                e["thanh_vien"].add(k["thanh_vien"])
            e["tep"] += 1
            if tl["id"] not in e["tai_lieu"]:
                e["tai_lieu"].append(tl["id"])
            e["thuoc"].update(tl["thuoc_ho_so"])
    ra = []
    for kid, e in sorted(theo.items()):
        td = sorted(e["tieu_de"].items(), key=lambda kv: (-kv[1], kv[0]))
        tv = sorted(e["thanh_vien"])
        ra.append({"kenh_id": kid, "tieu_de": td[0][0],
                   "tieu_de_bien_the": [t for t, _ in td[1:]],
                   "thanh_vien": tv[0] if len(tv) == 1 else tv,
                   "thuoc_ho_so": sorted(e["thuoc"], key=_so_ho_so),
                   "tin": {"truoc_gop": e["tep"], "sau_gop": len(e["tai_lieu"])},
                   "tai_lieu": e["tai_lieu"]})
    return ra


def _dung_hang_cho(tai_lieu, pg, nhan, thu_muc) -> list[dict]:
    """Một dòng cho mỗi ca: một nội dung (mọi bản y hệt của nó) × một kiểu xung đột."""
    ra = []
    for tl in tai_lieu:
        for loai in tl["xung_dot"]:
            bs = [b for b in tl["tep"] if loai in b["xung_dot"]]
            b = bs[0]
            p = pg[b["duong_dan"]]
            ung_vien = [{"ho_so": nhan[n], "nguon": p["nguon"][n],
                         "co_thu_muc_trong_kho": n in thu_muc} for n in sorted(p["thuoc"])]
            ung_vien += [{"ho_so": nhan[n], "nguon": ["ten_tep"], "co_thu_muc_trong_kho": n in thu_muc}
                         for n in sorted(p["nf"] - p["thuoc"])]
            vb = b.get("ho_so_trong_van_ban")
            if loai == "ma_noi_dung_khac_ten_tep" and vb:
                ung_vien.append({"ho_so": vb["ho_so"], "nguon": ["noi_dung"],
                                 "co_thu_muc_trong_kho": _so_ho_so(vb["ho_so"]) in thu_muc})
            ra.append({
                "ca": f"{loai}/{tl['bam_noi_dung'][:16]}",
                "xung_dot": loai,
                "trang_thai": CHO_NGUOI_XAC_NHAN,
                "doc_id": b["doc_id"], "duong_dan": b["duong_dan"],
                "ban_khac": [x["duong_dan"] for x in bs[1:]],
                "danh_tinh": {"ten_tep": b["bi_danh"], "thu_muc": p["m_nhan"],
                              "duong_dan": sorted({c.goc for c in p["ma_duong_dan"]}),
                              "noi_dung": vb["ho_so"] if vb else None,
                              "kenh": b["kenh"]},
                "ung_vien": ung_vien,
                "xep_tam": b["thuoc_ho_so"],
                "nhap": b["nhap"],
            })
    return ra


#: Trường người duyệt ghi vào hàng chờ; một lần chạy lại không được xoá chúng.
TRUONG_NGUOI_DUYET = ("trang_thai", "quyet_dinh", "nguoi_xac_nhan", "xac_nhan_luc", "ghi_chu")


def gop_hang_cho(cu: list[dict], moi: list[dict]) -> list[dict]:
    """Giữ quyết định của người duyệt qua các lần dựng lại sổ.

    Ca đã được quyết (trang_thai khác `cho_nguoi_xac_nhan`) giữ nguyên các
    trường người duyệt; ca đã quyết mà không còn trong kho (tệp đã đổi tên,
    đã chuyển) vẫn được giữ, gắn `con_trong_kho: false`, để còn lần lại.
    """
    da_quyet = {c["ca"]: c for c in cu if c.get("trang_thai") != CHO_NGUOI_XAC_NHAN}
    ra = []
    for c in moi:
        if (q := da_quyet.pop(c["ca"], None)):
            c = {**c, **{k: q[k] for k in TRUONG_NGUOI_DUYET if k in q}}
        ra.append(c)
    return ra + [{**q, "con_trong_kho": False} for q in da_quyet.values()]


def kiem_tra(so: dict, tep: list[tuple[str, str]]) -> list[str]:
    """Bất biến của sổ; trả danh sách lỗi (rỗng là đạt)."""
    loi = []
    thay = Counter(b["duong_dan"] for tl in so["tai_lieu"] for b in tl["tep"])
    thay.update(x["duong_dan"] for x in so["ngoai_ho_so"])
    for r, _ in tep:
        if thay[_nfc(r)] != 1:
            loi.append(f"tệp xuất hiện {thay[_nfc(r)]} lần: {r}")
    ca = {c["ca"] for c in so["hang_cho_xung_dot"]}
    for tl in so["tai_lieu"]:
        goc = [b for b in tl["tep"] if b["la_ban_sao_cua"] is None]
        if len(goc) != 1 or goc[0]["doc_id"] != tl["id"]:
            loi.append(f"tài liệu {tl['id']}: cần đúng một bản chính")
        if any(b["la_ban_sao_cua"] not in (None, tl["id"]) for b in tl["tep"]):
            loi.append(f"tài liệu {tl['id']}: bản sao trỏ ra ngoài nhóm")
        if not tl["thuoc_ho_so"]:
            loi.append(f"tài liệu {tl['id']}: thuoc_ho_so rỗng")
        for x in tl["xung_dot"]:
            if f"{x}/{tl['bam_noi_dung'][:16]}" not in ca:
                loi.append(f"tài liệu {tl['id']}: xung đột {x} không có trong hàng chờ")
    for c in so["hang_cho_xung_dot"]:
        if not c.get("trang_thai"):
            loi.append(f"ca {c['ca']}: thiếu trang_thai")
    chu: dict[str, str] = {}
    for h in so["ho_so"]:
        for k in h["ma_chuan"]:
            if k in chu:
                loi.append(f"khoá {k} thuộc hai hồ sơ: {chu[k]}, {h['ho_so']}")
            chu[k] = h["ho_so"]
        for bd in h["bi_danh"]:
            m = RE_MA.fullmatch(bd)
            if not m or Ma.tu_khop(m).khoa not in h["ma_chuan"]:
                loi.append(f"hồ sơ {h['ho_so']}: bí danh {bd} không quy về ma_chuan")
    return loi
