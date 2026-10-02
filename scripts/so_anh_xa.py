#!/usr/bin/env python3
"""Bảng ánh xạ tên gọi: đọc dòng `Sản phẩm bắt buộc` như MỘT VÍ DỤ, không như luật so chuỗi.

Cổng tuân thủ đang chấm đỏ vì nó so tên tệp từng chữ. BPMN viết
`<Mã>_Client approval Info Sheet_<ddmmyy>.eml`; trên đĩa tệp tên là
`NH9001.US_(executed) Submission Information_010125.pdf`. Cùng một tài liệu,
khác tên, khác đuôi — nên cái đỏ đó là đỏ sai.

Sổ này nằm NGOÀI BPMN. BPMN là chuẩn tuân thủ, giữ nguyên từng byte; khoá của
sổ là chuỗi `Sản phẩm bắt buộc` nguyên văn, giá trị là các cách gọi được chấp
nhận. Mỗi cách gọi phải trỏ về một tệp có thật đã lộ ra nó — không có nguồn thì
không được vào sổ, kể cả khi nghe rất hợp lý.

Ba nguồn bằng chứng, đều đã có sẵn trên đĩa, không sinh thêm dữ liệu:
  1. 4 sơ đồ BPMN (284 hoạt động, 27 dòng `Sản phẩm bắt buộc`);
  2. nhãn thư mục + tên tệp của kho `~/.private/refiny_data`;
  3. phụ lục QUY ƯỚC ĐẶT TÊN trong `_Quy trinh chuan v2.0/` — nơi hãng tự ghi
     tiền tố trạng thái `(du thao) · (scan) · (both signed) · (executed) ·
     (filled) · (khong dung)` và khuôn `<Mã HS>_<Tên tài liệu>_<ddmmyy>[_v…]`.

Chạy: `python3 scripts/so_anh_xa.py` (chỉ thư viện chuẩn, không cần .venv).
Kho `refiny_data` chỉ được ĐỌC tên tệp; script không mở, không sửa, không dời.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import OrderedDict
from pathlib import Path

BPMN_DIR = Path.home() / "bpmn"
KHO = Path.home() / ".private" / "refiny_data"
SO = Path.home() / ".private" / "so" / "anh_xa_ten_goi.json"

NS = {"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL"}
HOAT_DONG = {
    "task", "userTask", "serviceTask", "manualTask", "scriptTask", "sendTask",
    "receiveTask", "businessRuleTask", "callActivity", "subProcess",
}

# Thư mục gốc của kho → sơ đồ BPMN điều chỉnh nhóm hồ sơ đó. macOS trả tên
# thư mục ở dạng NFD còn hằng số trong mã nguồn là NFC: cùng một chữ "Đăng ký"
# nhưng khác byte, nên mọi tra cứu đều phải chuẩn hoá NFC trước (xem `nfc`).
QUY_TRINH = {
    "1. Đăng ký bảo hộ nhãn hiệu tại Hoa Kỳ": "ban-sao-cua-dang-ky-bao-ho-nhan-hieu-tai-hoa-ky-4.nhap.bpmn",
    "2. Đăng ký bản quyền tại Hoa Kỳ": "ban-sao-cua-dang-ky-ban-quyen-tac-gia-tai-hoa-ky-usco-2.nhap.bpmn",
    "4. Gỡ Report": "go-report-shtt-tren-san-tmdt-hoa-ky-report-removal-schedule-a-settlement.nhap.bpmn",
    "5. C&D": "giai-quyet-thu-c-d-cease-desist-tu-chu-the-quyen-hoa-ky.nhap.bpmn",
}

# Phụ lục "QUY ƯỚC ĐẶT TÊN & MÃ HỒ SƠ" liệt kê đúng 6 tiền tố trạng thái này;
# các biến thể còn lại là cách viết thật đã gặp trong kho.
TRANG_THAI = [
    "fully executed", "both signed", "khong dung", "khach gui", "du thao",
    "executed", "signed", "filled", "draft", "scan", "final",
]

# Bằng chứng cho phụ lục quy ước đặt tên: dẫn nguồn khi ghi sổ.
NGUON_QUY_UOC = (
    "Phòng IP/1. Đăng ký bảo hộ nhãn hiệu tại Hoa Kỳ/_Quy trinh chuan v2.0/"
    "REFINY_Tu-dien-hoat-dong_BPMN-v2.0.md"
)

# Ánh xạ phán đoán: tên gọi mà bộ so từ KHÔNG bắc được cầu, nhưng có tệp thật
# làm chứng. Mỗi dòng phải nêu tệp nguồn; lúc chạy, tệp nào không còn trên đĩa
# thì dòng đó bị loại và báo ra — sổ không giữ ánh xạ mồ côi.
#
# Ứng viên đã soi và LOẠI cũng ghi lại, để lần sau khỏi đào lại, và để thấy
# cuộc rà là rà hết chứ không phải bỏ sót.
#
# Cả hai dẫn đường dẫn THẬT của kho nên nằm cạnh sổ, ngoài cây git:
# `{"anh_xa_phan_doan": [{khoa, ten, nguon, ly_do}], "ung_vien_loai": [{khoa, tep, ly_do}]}`.
# Dòng do `agent_hinh_thuc.py` ghi ngược mang thêm `cho_muc` (mục nào của khoá
# — khoá có hai mục thì không được mặc định mục đầu) và `phuong_phap: agent`.
PHAN_DOAN = Path.home() / ".private" / "so" / "anh_xa_phan_doan.json"


def _nap_phan_doan(tep: Path = PHAN_DOAN) -> tuple[list[dict], list[dict]]:
    if not tep.is_file():
        return [], []
    d = json.loads(tep.read_text(encoding="utf-8"))
    return d.get("anh_xa_phan_doan", []), d.get("ung_vien_loai", [])


ANH_XA_PHAN_DOAN, UNG_VIEN_LOAI = _nap_phan_doan()


KHOA_N44 = "<Mã>_Client approval Info Sheet_<ddmmyy>.eml"


def nfc(s: str) -> str:
    """macOS trả tên tệp dạng NFD; so sánh với chuỗi NFC trong mã sẽ trượt hết."""
    return unicodedata.normalize("NFC", s)


def bo_dau(s: str) -> str:
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode()


RE_MA_HO_SO = re.compile(r"^[\s,._-]*(?:(?:nh|tv|bq)\s*\d{2,6}[\w.]*\s*[,._\- ]\s*(?:us\b)?)+[\s,._-]*")
RE_NGOAC = re.compile(r"\(([^)]*)\)")
# `\b` không nhận ranh giới giữa `_` và chữ số — `_` là ký tự từ — nên
# `Submission Information_230925` giữ nguyên ngày. Dùng lookaround theo chữ/số.
D0, D1 = r"(?<![a-z0-9])", r"(?![a-z0-9])"
RE_NGAY = re.compile(
    D0 + r"(?:\d{6}|\d{8}|\d{2}[.\-/]\d{2}[.\-/]\d{2,4}|\d{4}-\d{2}-\d{2})" + D1)
RE_PHIEN_BAN = re.compile(D0 + r"v(?:er)?\s?\d+(?:\.\d+)?[a-z]{0,3}" + D1)
RE_SO_HIEU = re.compile(D0 + r"(?:[vek]\d{4}-\d{2,4}|\d{5,}|pl\d{2})" + D1)
RE_RAC = re.compile(r"[_\-–—.,;:'\"/\\]+")


def doc_trang_thai(trong_ngoac: str) -> str | None:
    """`(both signed)` → `both signed`, KHÔNG kèm `signed`. Nếu chuỗi chuẩn đòi
    cả hai nhãn mà tên tệp chỉ sinh một, mọi hồ sơ đều đỏ oan."""
    t = bo_dau(trong_ngoac).strip().lower()
    for nhan in TRANG_THAI:          # TRANG_THAI xếp dài trước, ngắn sau
        if nhan in t:
            return nhan
    return None


def chuan_hoa(ten: str, nhan_hieu: tuple[str, ...] = (),
              ma_so: str = "") -> tuple[str, list[str]]:
    """Rút lõi tên tài liệu: bỏ mã hồ sơ, trạng thái, ngày, phiên bản, số hiệu.

    Trả về (lõi, các trạng thái đọc được). Đuôi tệp bị bỏ hẳn — `duoi_tep_khong_tinh`.
    """
    s = bo_dau(ten).lower()
    s = re.sub(r"\.[a-z0-9]{1,5}$", "", s)          # đuôi tệp
    s = re.sub(r"\(\d+\)$", "", s).strip()           # bản sao "(1)" của hệ điều hành
    trang_thai: list[str] = []
    for trong_ngoac in RE_NGOAC.findall(s):
        nhan = doc_trang_thai(trong_ngoac)
        if nhan:
            trang_thai.append(nhan)
    s = RE_NGOAC.sub(" ", s)
    s = RE_MA_HO_SO.sub(" ", s)
    if ma_so:
        # Hồ sơ C&D và Gỡ Report đánh số trần ("97. …", "154. …"), không mang
        # tiền tố NH/TV/BQ. Số lấy từ chính nhãn thư mục nên vẫn là bằng chứng.
        s = re.sub(rf"^[\s.,_-]*{re.escape(ma_so)}[\s.,_-]+", " ", s)
    for nh in nhan_hieu:                             # tên nhãn hiệu của chính hồ sơ
        if nh and len(nh) >= 3:
            s = s.replace(bo_dau(nh).lower(), " ")
    s = RE_NGAY.sub(" ", s)
    s = RE_PHIEN_BAN.sub(" ", s)
    s = RE_SO_HIEU.sub(" ", s)
    s = RE_RAC.sub(" ", s)
    s = re.sub(r"\b(us|com|vn)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s, sorted(set(trang_thai))


RE_THE = re.compile(r"<[^>]*>|\[[^\]]*\]")   # <Mã>, <ddmmyy>, [Tên KH]


def tach_ve(than: str) -> list[str]:
    """Cắt chuỗi thành các sản phẩm rời tại ` + ` / ` · ` — nhưng chỉ khi dấu
    đó thật sự nối hai tệp.

    `…_Ket qua tra cuu_<ddmmyy>.docx + Tong hop doi chung.pdf` là hai sản phẩm:
    vế trái đã kết thúc bằng một đuôi tệp. `<Mã TV>_Tu van + Info_<ddmmyy>.docx`
    là MỘT tệp có dấu + trong tên; cắt ra sẽ đẻ ra mục "tu van" rồi khớp nhầm
    sang `Tu van giai quyet vu viec` của hoạt động khác.
    """
    diem = []
    for m in re.finditer(r"\s+[+·]\s+", than):
        trai = than[:m.start()].strip()
        if ("·" in m.group()
                or re.search(r"\.[a-z0-9]{2,5}$", trai, re.I)
                or re.match(r"\s+\+\s+(Annex|CCCD|GPKD)", than[m.start():])):
            diem.append((m.start(), m.end()))
    ve, truoc = [], 0
    for bat, ket in diem:
        ve.append(than[truoc:bat])
        truoc = ket
    ve.append(than[truoc:])
    return [v for v in (x.strip() for x in ve) if v]


def tach_muc(chuoi: str) -> list[dict]:
    """Bổ chuỗi `Sản phẩm bắt buộc` thành các mục bắt buộc.

    `A + B` và `A · B` nghĩa là phải có CẢ HAI. Ghi chú trong ngoặc
    ("03 trang", "thư mục KHÔNG được rỗng") là điều kiện, không phải tên tệp.
    """
    than = chuoi.split("⛔")[0]
    muc = []
    for phan in tach_ve(than):
        phan = phan.strip()
        if not phan:
            continue
        ghi_chu = [g.strip() for g in RE_NGOAC.findall(phan)]
        thu_muc = None
        m = re.search(r"lưu tại\s+([^/]+/)", phan)
        if m:
            thu_muc = m.group(1).strip().rstrip("/")
            phan = phan[:m.start()]
        khong_rong = any("rỗng" in g.lower() for g in ghi_chu)
        lo_i, trang_thai = chuan_hoa(RE_THE.sub(" ", RE_NGOAC.sub(" ", phan)))
        # trạng thái nằm trong ngoặc của CHÍNH chuỗi chuẩn là điều kiện bắt buộc
        bat_buoc_trang_thai = [t for t in (doc_trang_thai(g) for g in ghi_chu) if t]
        muc.append({
            "ten": lo_i,
            "nguyen_van": phan.strip(),
            "trang_thai_bat_buoc": sorted(set(bat_buoc_trang_thai + trang_thai)),
            "thu_muc": thu_muc,
            "thu_muc_khong_duoc_rong": khong_rong,
            "ghi_chu": [g for g in ghi_chu if g and not doc_trang_thai(g)],
        })
    return [m for m in muc if m["ten"]]


def doc_bpmn(duong_dan: Path) -> list[dict]:
    goc = ET.parse(duong_dan).getroot()
    ra = []
    for el in goc.iter():
        if el.tag.split("}")[-1] not in HOAT_DONG:
            continue
        tai_lieu = "\n".join((d.text or "") for d in el.findall("bpmn:documentation", NS))
        san_pham = None
        for dong in tai_lieu.splitlines():
            dong = dong.strip()
            if dong.startswith("Sản phẩm bắt buộc:"):
                san_pham = dong.split(":", 1)[1].strip()
        ra.append({
            "id": el.get("id", ""),
            "ten": (el.get("name") or "").strip(),
            "san_pham_bat_buoc": san_pham,
            "so_do": duong_dan.name,
        })
    return ra


def quet_kho(goc: Path) -> tuple[list[dict], set[str]]:
    """Đọc TÊN tệp và nhãn thư mục. Không mở tệp, không sửa, không dời."""
    ho_so, nhan_thu_muc = [], set()
    for phong in sorted(p for p in goc.iterdir() if p.is_dir()):
        for muc in sorted(p for p in phong.iterdir() if p.is_dir()):
            so_do = QUY_TRINH.get(nfc(muc.name).strip())
            for case in sorted(p for p in muc.iterdir() if p.is_dir()):
                if case.name.startswith("_"):
                    continue                      # `_Quy trinh chuan v2.0` không phải hồ sơ
                tep = []
                for f in sorted(case.rglob("*")):
                    if f.is_dir():
                        nhan_thu_muc.add(nfc(f.name))
                    elif f.name != ".DS_Store":
                        tep.append(nfc(str(f.relative_to(goc))))
                ho_so.append({
                    "ma": nfc(case.name),
                    "nhom": nfc(muc.name).strip(),
                    "so_do": so_do,
                    "nhan_hieu": doan_nhan_hieu(nfc(case.name)),
                    "ma_so": (re.match(r"\s*(\d+)", nfc(case.name)) or [None, ""])[1],
                    "tep": tep,
                })
    return ho_so, nhan_thu_muc


def doan_nhan_hieu(nhan: str) -> tuple[str, ...]:
    """`904.US. TRAVANO IN CLASS 016` → ('travano',). Nhãn thư mục là bằng chứng."""
    s = re.sub(r"^\s*\d+[.\s]*(us)?[.\s]*", "", nhan, flags=re.I)
    s = re.split(r"\bin\s+class\b", s, flags=re.I)[0]
    s = re.sub(r",?\s*(hinh|device|handmade device)\b", " ", s, flags=re.I)
    ra = [t for t in re.split(r"[.,]", s) if len(t.strip()) >= 3]
    return tuple(t.strip().lower() for t in ra)


def ghi_khoang_trong(muc: dict, do: dict, ho_so: list[dict]) -> None:
    """Ghi 5 hồ sơ THIẾU phê duyệt thành mục tra được, không để nó là chỗ trống.

    Một khoá vắng mặt chỉ nói "chưa xử lý"; một mục ghi rõ "đã soi, không có,
    vì thế này" mới là phát hiện. Đỏ mà đúng đáng giá hơn xanh mà sai — nên
    không nới luật nhận tên gọi cho đủ con số.
    """
    lien_quan = [c for c in do["chi_tiet"] if c["khoa"] == KHOA_N44]
    do_o_n44 = [c["ho_so"] for c in lien_quan if c["sau"] == "do"]
    if not do_o_n44:
        return
    theo_ma = {h["ma"]: h for h in ho_so}
    danh_sach = []
    for ma in sorted(do_o_n44):
        h = theo_ma[ma]
        info = [t for t in h["tep"] if "information sheet" in t.lower()]
        ung_vien = [uv["ly_do"] for uv in UNG_VIEN_LOAI
                    if uv["tep"] in h["tep"] and uv["khoa"] == KHOA_N44]
        ly_do = (
            "Trong hồ sơ chỉ có chính bản Information Sheet, không có văn bản "
            "khách chốt lại nội dung đó. Hậu tố `_v0.1C` / `_ver0.1Ha` trên các "
            "bản này là CHỮ TẮT NGƯỜI RÀ (từ điển hoạt động dòng 92, A052), "
            "không phải dấu hiệu khách đã duyệt."
        ) if info else "Không tìm thấy cả Information Sheet lẫn văn bản phê duyệt."
        danh_sach.append({
            "ho_so": ma,
            "ly_do": ly_do,
            "info_sheet_tim_duoc": info,
            "ung_vien_da_loai": ung_vien,
        })
    muc["khoang_trong_bang_chung"] = {
        "ket_luan": (
            f"N_4_4 xanh đúng {sum(1 for c in lien_quan if c['sau'] == 'xanh')}/"
            f"{len(lien_quan)} hồ sơ nhãn hiệu — đúng ở nơi có "
            "tệp phê duyệt thật, và chỉ ở đó. 5 hồ sơ còn lại KHÔNG phải đỏ oan "
            "do cổng đọc sai tên, mà là thiếu bằng chứng thật."
        ),
        "tieu_chi_da_sua": (
            "Tiêu chí ban đầu 'N_4_4 xanh cả 6 hồ sơ' giả định kho có bằng chứng "
            "phê duyệt; kho không có. Tiêu chí đúng: xanh đúng ở nơi có tệp phê "
            "duyệt thật, phần còn lại ghi thành khoảng trống bằng chứng."
        ),
        "khong_noi_luat": (
            "Giữ nguyên luật: không nhận tên gọi nào không có tệp thật làm chứng. "
            "Nới luật để chạm con số mục tiêu là bịa — cổng sẽ khẳng định điều kho "
            "không chứng minh được, trong chính hệ thống lập ra để giữ tính toàn "
            "vẹn của bằng chứng."
        ),
        "dong_y_voi_tu_dien": (
            "Khớp với từ điển của chính hãng: A053 đang gắn 🔴 'phê duyệt BẰNG VĂN "
            "BẢN', Điều 3.2 HĐ ghi tin nhắn Zalo/Viber không có giá trị pháp lý. "
            "Từ điển đòi văn bản; kho không có văn bản; nên đỏ là kết quả đúng."
        ),
        "ho_so_thieu": danh_sach,
    }


def khop(loi_muc: str, loi_tep: str) -> str | None:
    """`exact` · `chua_du_tu` · `gan_giong`, hoặc None."""
    if not loi_muc or not loi_tep:
        return None
    if loi_muc == loi_tep:
        return "exact"
    tu_muc, tu_tep = set(loi_muc.split()), set(loi_tep.split())
    if len(tu_muc) >= 2 and tu_muc <= tu_tep:
        return "chua_du_tu"
    if difflib.SequenceMatcher(None, loi_muc, loi_tep).ratio() >= 0.86:
        return "gan_giong"
    return None


def khop_nguyen_van(muc: dict, ten_tep: str) -> bool:
    """Cách cổng đang làm hôm nay: so nguyên chuỗi BPMN với tên tệp."""
    return ten_tep.lower() == muc["nguyen_van"].lower()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bpmn", type=Path, default=BPMN_DIR)
    ap.add_argument("--kho", type=Path, default=KHO)
    ap.add_argument("--so", type=Path, default=SO)
    ap.add_argument("--kho-thu", action="store_true", help="không ghi sổ, chỉ in số")
    tham_so = ap.parse_args()

    so_do = {p.name: doc_bpmn(p) for p in sorted(tham_so.bpmn.glob("*.bpmn"))}
    tat_ca_hd = [hd for ds in so_do.values() for hd in ds]
    co_cong = [hd for hd in tat_ca_hd if hd["san_pham_bat_buoc"]]
    print(f"{len(tat_ca_hd)} hoạt động · {len(co_cong)} có `Sản phẩm bắt buộc` "
          f"· {len({hd['san_pham_bat_buoc'] for hd in co_cong})} chuỗi khác nhau")

    ho_so, nhan_thu_muc = quet_kho(tham_so.kho)
    so_tep = sum(len(h["tep"]) for h in ho_so)
    print(f"{len(ho_so)} hồ sơ · {so_tep} tệp · {len(nhan_thu_muc)} nhãn thư mục")

    # ---- dựng sổ: khoá = chuỗi nguyên văn, giá trị = các cách gọi có nguồn ----
    sổ: "OrderedDict[str, dict]" = OrderedDict()
    for hd in co_cong:
        khoa = hd["san_pham_bat_buoc"]
        muc = sổ.setdefault(khoa, {
            "ten_goi_chap_nhan": [],
            "muc_bat_buoc": tach_muc(khoa),
            "duoi_tep_khong_tinh": True,
            "nguon": [],
            "hoat_dong": [],
            "bam_chuoi": hashlib.sha256(khoa.encode()).hexdigest()[:16],
        })
        muc["hoat_dong"].append({"id": hd["id"], "ten": hd["ten"], "so_do": hd["so_do"]})

    def them(khoa: str, ten: str, nguon: str, cach: str, muc_ten: str, ly_do: str = "") -> None:
        if not ten:
            return
        ds = sổ[khoa]["ten_goi_chap_nhan"]
        cu = next((a for a in ds if a["ten"] == ten and a["cho_muc"] == muc_ten), None)
        if cu is None:
            ds.append({"ten": ten, "cho_muc": muc_ten, "phuong_phap": cach,
                       "nguon": [nguon], **({"ly_do": ly_do} if ly_do else {})})
        elif nguon not in cu["nguon"]:
            cu["nguon"].append(nguon)
        if nguon not in sổ[khoa]["nguon"]:
            sổ[khoa]["nguon"].append(nguon)

    # tên gọi tự rút ra từ tệp thật: mỗi tệp khớp là một bằng chứng
    loi_tep: dict[str, list[tuple[str, str, list[str]]]] = {}
    for h in ho_so:
        ds = []
        for rel in h["tep"]:
            lõi, tt = chuan_hoa(Path(rel).name, h["nhan_hieu"], h["ma_so"])
            ds.append((rel, lõi, tt))
        loi_tep[h["ma"]] = ds

    for khoa, muc in sổ.items():
        for m in muc["muc_bat_buoc"]:
            for h in ho_so:
                if h["so_do"] != muc["hoat_dong"][0]["so_do"]:
                    continue
                for rel, lõi, _tt in loi_tep[h["ma"]]:
                    cach = khop(m["ten"], lõi)
                    if cach:
                        them(khoa, lõi, rel, cach, m["ten"])

    # ánh xạ phán đoán — chỉ nhận khi tệp nguồn còn trên đĩa
    bo_qua = []
    for ax in ANH_XA_PHAN_DOAN:
        if ax["khoa"] not in sổ:
            bo_qua.append((ax["ten"], "khoá không có trong BPMN"))
            continue
        if not (tham_so.kho / ax["nguon"]).exists():
            bo_qua.append((ax["ten"], "tệp nguồn không còn"))
            continue
        them(ax["khoa"], ax["ten"], ax["nguon"], ax.get("phuong_phap", "phan_doan"),
             ax.get("cho_muc") or sổ[ax["khoa"]]["muc_bat_buoc"][0]["ten"], ax["ly_do"])
    for ten, vi in bo_qua:
        print(f"  ⚠ loại ánh xạ `{ten}` — {vi}")

    if KHOA_N44 not in sổ:
        print(f"  ⚠ không thấy khoá N_4_4 trong BPMN: {KHOA_N44}")
    for uv in UNG_VIEN_LOAI:
        if uv["khoa"] in sổ:
            sổ[uv["khoa"]].setdefault("ung_vien_loai", []).append(
                {"tep": uv["tep"], "ly_do": uv["ly_do"]})

    # ---- đo lại cổng: trước (so nguyên văn) vs sau (đọc sổ) ----
    do = {"truoc_xanh": 0, "sau_xanh": 0, "doi_mau": 0, "lan_do": [], "chi_tiet": []}
    ten_goi = {k: {a["ten"] for a in v["ten_goi_chap_nhan"]} for k, v in sổ.items()}
    for h in ho_so:
        for hd in so_do.get(h["so_do"] or "", []):
            if not hd["san_pham_bat_buoc"]:
                continue
            khoa = hd["san_pham_bat_buoc"]
            muc_ds = sổ[khoa]["muc_bat_buoc"]
            truoc = all(any(khop_nguyen_van(m, Path(rel).name) for rel, _l, _t in loi_tep[h["ma"]])
                        for m in muc_ds)
            sau = True
            for m in muc_ds:
                dat = False
                for rel, lõi, tt in loi_tep[h["ma"]]:
                    if m["thu_muc"] and m["thu_muc"].lower() not in rel.lower():
                        continue
                    if m["trang_thai_bat_buoc"] and not set(m["trang_thai_bat_buoc"]) <= set(tt):
                        continue
                    if lõi in ten_goi[khoa] or khop(m["ten"], lõi):
                        dat = True
                        break
                if not dat:
                    sau = False
                    break
            do["truoc_xanh"] += truoc
            do["sau_xanh"] += sau
            if sau and not truoc:
                do["doi_mau"] += 1
            if not sau:
                do["lan_do"].append({"ho_so": h["ma"], "hoat_dong": hd["id"], "khoa": khoa})
            # `khoa` chứ không chỉ `hoat_dong`: id N_4_4 có ở CẢ sơ đồ nhãn hiệu
            # lẫn sơ đồ C&D, hai sản phẩm bắt buộc khác hẳn nhau. Đếm theo id sẽ
            # trộn hai cổng làm một.
            do["chi_tiet"].append({"ho_so": h["ma"], "hoat_dong": hd["id"],
                                   "khoa": khoa, "so_do": h["so_do"],
                                   "truoc": "xanh" if truoc else "do",
                                   "sau": "xanh" if sau else "do"})

    tong = len(do["chi_tiet"])
    print(f"\ncổng đo được: {tong} lượt ({len(co_cong)} hoạt động có cổng, "
          f"{len(tat_ca_hd) - len(co_cong)} hoạt động không có cổng)")
    print(f"  trước (so nguyên văn): {do['truoc_xanh']} xanh · {tong - do['truoc_xanh']} đỏ")
    print(f"  sau  (đọc bảng ánh xạ): {do['sau_xanh']} xanh · {tong - do['sau_xanh']} đỏ")
    print(f"  đổi màu nhờ bảng ánh xạ: {do['doi_mau']}")

    n44 = [c for c in do["chi_tiet"] if c["khoa"] == KHOA_N44]
    print(f"  N_4_4 trên {len(n44)} hồ sơ nhãn hiệu: "
          f"{sum(c['sau'] == 'xanh' for c in n44)} xanh sau ánh xạ")
    for c in sorted(n44, key=lambda x: x["ho_so"]):
        print(f"      {c['sau']:>4}  {c['ho_so']}")

    if KHOA_N44 in sổ:
        ghi_khoang_trong(sổ[KHOA_N44], do, ho_so)
        thu_dien_tu = [t for h in ho_so for t in h["tep"]
                       if t.lower().endswith((".eml", ".msg"))]
        sổ[KHOA_N44]["khoang_trong_bang_chung"]["su_kien_kho"] = {
            "tong_so_tep": so_tep,
            "so_tep_eml_msg": len(thu_dien_tu),
            "ghi_chu": (
                "Sản phẩm bắt buộc ghi đuôi `.eml`, nhưng kho không lưu thư điện "
                "tử dạng tệp — nên `duoi_tep_khong_tinh` là bắt buộc, không phải "
                "tiện tay nới."
            ),
        }

    so_ten_goi = sum(len(v["ten_goi_chap_nhan"]) for v in sổ.values())
    khong_nguon = [a["ten"] for v in sổ.values() for a in v["ten_goi_chap_nhan"] if not a["nguon"]]
    print(f"\n{len(sổ)} khoá · {so_ten_goi} tên gọi · "
          f"{len(khong_nguon)} tên gọi không có nguồn (phải bằng 0)")

    if tham_so.kho_thu:
        return 0

    tham_so.so.parent.mkdir(parents=True, exist_ok=True)
    tham_so.so.write_text(json.dumps({
        "phien_ban": 1,
        "nguon_bang_chung": {
            "bpmn": sorted(so_do),
            "kho": str(tham_so.kho),
            "quy_uoc_dat_ten": NGUON_QUY_UOC,
            "so_hoat_dong": len(tat_ca_hd),
            "so_tep": so_tep,
            "so_nhan_thu_muc": len(nhan_thu_muc),
        },
        "anh_xa": sổ,
        "do_luong": do,
    }, ensure_ascii=False, indent=1), "utf-8")
    print(f"→ {tham_so.so}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
