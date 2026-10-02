#!/usr/bin/env python3
"""Bóc ô dữ kiện từ kho tài liệu có ảnh chụp màn hình — phần cơ khí.

Hợp đồng bóc nằm ở `prompts/boc_hoi_thoai.md`; script này KHÔNG bóc.
Nó làm bốn việc mà người đọc không nên làm bằng tay:

    chon      chọn kho — mọi `.docx` có `word/media/*`, không phải 14 tệp
              mà bộ lọc hai tín hiệu tìm ra;
    van-ban   trải markdown ADE Pro ra đĩa, GIỮ NGUYÊN khối `<figure>`;
    anh-em    liệt kê tên tệp anh em trong cùng thư mục hồ sơ (lượt hai);
    kiem      kiểm sổ đã ghi: đủ tệp, không ô nào suy đoán, `kenh` có mặt.

VÌ SAO KHÔNG CẮT `<figure>`
───────────────────────────
ADE Pro đặt bản đọc ảnh chụp màn hình vào trong `<figure>`, kèm cả bảng
HTML. Với NH9006 thì TOÀN BỘ bảng kết quả tra cứu — bốn nhãn, mười một đối
chứng, bốn tỷ lệ — nằm trong đúng một khối `<figure type="CHART">`. Một
lượt bóc trước đây cắt figure đi và mất sạch lớp này; đó là lý do lệnh
`van-ban` mặc định giữ figure và phải truyền cờ tường minh mới bỏ được.

VÌ SAO SỔ NẰM NGOÀI CÂY GIT
───────────────────────────
Ô `dinh_danh` giữ mã số doanh nghiệp, merchant ID, số điện thoại, số vụ
kiện — định danh trực tiếp của người thật. Sổ ghi ra `~/.private/`, ngoài
mọi cây git, và không giá trị nào trong đó được phép lên tên tệp, tệp
commit hay báo cáo công khai.

BỘ LỌC HAI TÍN HIỆU CHỌN THIẾU BAO NHIÊU
────────────────────────────────────────
Lọc theo header `<partner> x REFINY` cộng `N thành viên` trả 14 tệp.
Lọc theo `word/media/*` trả 77. Chênh 63 tệp là các tài liệu có ảnh chụp
nhưng header bị ảnh nuốt, bị cắt mép, hoặc ảnh chụp từ kênh không có dòng
header — đúng nhóm mà bản tóm tắt văn xuôi đánh rơi.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ocr_lab.ade_store import doc_id_for  # noqa: E402

NGUON = Path.home() / ".private" / "refiny_data"
KHO = Path.home() / ".private" / "ade_out"
SO = Path.home() / ".private" / "ho_so_boc" / "o_du_kien.json"

#: Thư mục con trong hồ sơ. Thư mục hồ sơ là cha của chúng, không phải
#: thư mục chứa tệp: `901.US. ZORBLAX in Class 025/3. Office Action/x.docx`
#: thì hồ sơ là `901.US. ZORBLAX in Class 025`.
BUOC = re.compile(
    r"^(\d+\.\s|0\.\s|Accounting$|Case closed$|Filing$|Office Action$"
    r"|Info$|To\s|Từ\s|From\s)", re.IGNORECASE)

#: Ô bắt buộc có mặt trong mọi vân tay, kể cả khi rỗng. Ô rỗng phải được
#: ghi rỗng tường minh — "không có khoá" và "không có dữ liệu" là hai
#: trạng thái khác nhau, và chỉ cái sau mới là một phát hiện.
O_BAT_BUOC = (
    "id", "tep", "duong_dan", "kenh", "thanh_vien", "ho_so", "doi_tuong",
    "moc", "tra_cuu", "phuong_an", "goi", "phi", "quyet_dinh",
    "cau_hoi_khach", "cau_hoi_treo", "viec_tiep", "tep_trao_doi",
    "dinh_danh", "tham_chieu_ngoai", "nguon_quyet_dinh", "mau_thuan",
)

#: Ô mà mọi giá trị phải kèm nguồn. `null` hợp lệ, chuỗi trần thì không.
KHONG_SUY_DOAN = ("kenh", "thanh_vien")


# ── chọn kho ───────────────────────────────────────────────────────────

def co_anh_nhung(tep: Path) -> bool:
    """`.docx` có ảnh nhúng trong `word/media/` hay không.

    Đọc danh mục zip chứ không giải nén: một docx 17 MB toàn ảnh vẫn chỉ
    tốn một lần đọc central directory.
    """
    try:
        with zipfile.ZipFile(tep) as z:
            return any(t.startswith("word/media/") for t in z.namelist())
    except (zipfile.BadZipFile, OSError):
        return False


def thu_muc_ho_so(duong_dan_tuong_doi: str) -> str:
    """Thư mục hồ sơ của một tệp, tính từ đường dẫn tương đối.

    Hồ sơ là cấp ngay dưới "Phòng IP/<mảng>". Các cấp sau nó
    (`Accounting`, `3. Office Action`...) là bước xử lý, không phải hồ sơ
    mới — gộp nhầm thì lượt hai mất hẳn tầng tên tệp anh em, vốn là trọng
    tài duy nhất không đi qua OCR cho chính tả tên nhãn.
    """
    phan = Path(duong_dan_tuong_doi).parts
    return "/".join(phan[:3]) if len(phan) >= 3 else str(Path(duong_dan_tuong_doi).parent)


#: Dòng header của một nhóm chat: "<đối tác> x REFINY" và "N thành viên".
#: Đây là tín hiệu duy nhất không phụ thuộc định dạng tệp, nên nó là thứ
#: kéo được các ảnh chụp lưu dưới dạng `.pdf` và `.jpg` vào kho.
HEADER_CHAT = re.compile(
    r"[\U0001F464\U0001F465]\s*\d+\s*(?:thành viên|members)"   # 👤/👥 N thành viên
    r"|^[^\S\n]*\d+\s*(?:thành viên|members)[^\S\n]*$"        # dòng riêng "4 thành viên"
    r"|\bx\s*REFINY\b",                                        # "<đối tác> x REFINY"
    re.IGNORECASE | re.MULTILINE)


def ban_ghi_kho(rel: str, byte: int) -> dict:
    did = doc_id_for(rel)
    return {
        "id": did,
        "tep": Path(rel).name,
        "duong_dan": rel,
        "ho_so_thu_muc": thu_muc_ho_so(rel),
        "co_ban_doc_pro": (KHO / did / "parse_pro.json").exists(),
        "byte": byte,
    }


def anh_chup_trong_ban_doc(doc_id: str) -> bool:
    """Bản đọc ADE của tệp này có dòng header nhóm chat hay không."""
    p = KHO / doc_id / "parse_pro.json"
    if not p.exists():
        return False
    try:
        md = json.loads(p.read_text()).get("markdown") or ""
    except (json.JSONDecodeError, OSError):
        return False
    return bool(HEADER_CHAT.search(md))


def chon_kho() -> list[dict]:
    """Mọi tệp có ảnh chụp trò chuyện.

    Hai tín hiệu, không phải một:

    * `.docx` có `word/media/*` — 77 tệp. Rẻ, đọc danh mục zip là đủ, và
      bắt được cả tài liệu mà dòng header bị ảnh nuốt.
    * tệp bất kỳ mà bản đọc ADE có dòng header nhóm chat — kéo thêm 12 tệp
      `.pdf`, `.jpg` và `.png` là ảnh chụp trò chuyện lưu ngoài docx, thành
      89 tệp. Chỉ lọc `.docx` thì mất trọn một cuộc đàm phán settle, ba ảnh
      chụp kết quả tra cứu, và cả một chuỗi bốn lần đổi tên nhãn.
    """
    ra: dict[str, dict] = {}
    for tep in sorted(NGUON.rglob("*.docx")):
        if tep.name.startswith("~$") or not co_anh_nhung(tep):
            continue
        rel = unicodedata.normalize("NFC", str(tep.relative_to(NGUON)))
        ra[doc_id_for(rel)] = ban_ghi_kho(rel, tep.stat().st_size)

    for tep in sorted(NGUON.rglob("*")):
        if not tep.is_file() or tep.name.startswith("~$"):
            continue
        rel = unicodedata.normalize("NFC", str(tep.relative_to(NGUON)))
        did = doc_id_for(rel)
        if did in ra or not anh_chup_trong_ban_doc(did):
            continue
        ra[did] = ban_ghi_kho(rel, tep.stat().st_size)

    return sorted(ra.values(), key=lambda r: r["duong_dan"])


# ── trải văn bản ───────────────────────────────────────────────────────

FIGURE = re.compile(r"<figure\b", re.IGNORECASE)


def markdown_cua(doc_id: str, *, bo_figure: bool = False) -> str:
    """Markdown ADE Pro của một tài liệu.

    `bo_figure` mặc định False và nên ở nguyên đó: xem docstring đầu tệp.
    Cờ này chỉ tồn tại để đo xem cắt figure thì mất bao nhiêu.
    """
    p = KHO / doc_id / "parse_pro.json"
    if not p.exists():
        raise FileNotFoundError(f"chưa có bản đọc Pro: {p}")
    md = json.loads(p.read_text())["markdown"]
    if bo_figure:
        md = re.sub(r"<figure\b.*?</figure>", "", md, flags=re.S | re.I)
    return md


def dem_figure(md: str) -> int:
    return len(FIGURE.findall(md))


# ── kiểm sổ ────────────────────────────────────────────────────────────

def kiem_so(so: list[dict], kho: list[dict]) -> list[str]:
    """Trả về danh sách lỗi. Sổ hợp lệ ⇒ danh sách rỗng."""
    loi: list[str] = []
    id_kho = {d["id"] for d in kho}
    id_so = {d.get("id") for d in so}

    thieu = id_kho - id_so
    if thieu:
        loi.append(f"{len(thieu)} tệp trong kho chưa có vân tay: "
                   + ", ".join(sorted(thieu)[:5]))
    thua = id_so - id_kho
    if thua:
        loi.append(f"{len(thua)} vân tay không khớp tệp nào trong kho: "
                   + ", ".join(sorted(x for x in thua if x)[:5]))

    for van in so:
        ten = van.get("tep", van.get("id", "?"))
        for o in O_BAT_BUOC:
            if o not in van:
                loi.append(f"{ten}: thiếu ô `{o}`")
        for o in KHONG_SUY_DOAN:
            if o in van and van[o] is not None and not str(van[o]).strip():
                loi.append(f"{ten}: ô `{o}` là chuỗi rỗng — dùng null")
        for i, ch in enumerate(van.get("cau_hoi_khach") or []):
            if "hoi" not in ch or "dap" not in ch:
                loi.append(f"{ten}: cau_hoi_khach[{i}] thiếu `hoi` hoặc `dap`")
    return loi


def thong_ke(so: list[dict]) -> dict:
    def dem(o: str) -> int:
        return sum(len(v.get(o) or []) for v in so)

    hoi_thoai = [v for v in so if v.get("kenh")]
    return {
        "tep": len(so),
        "tep_hoi_thoai": len(hoi_thoai),
        "co_kenh": sum(1 for v in so if v.get("kenh")),
        "moc": dem("moc"),
        "quyet_dinh": dem("quyet_dinh"),
        "cau_hoi_khach": dem("cau_hoi_khach"),
        "cau_hoi_treo": dem("cau_hoi_treo"),
        "mau_thuan": dem("mau_thuan"),
        "viec_tiep": dem("viec_tiep"),
        "tep_trao_doi": dem("tep_trao_doi"),
        "dinh_danh": dem("dinh_danh"),
        "tham_chieu_ngoai": dem("tham_chieu_ngoai"),
        "doi_chung": sum(
            len(t.get("doi_chung") or []) for t in tra_cuu_cua(so)),
        "ty_le": sum(
            len(t.get("ty_le") or []) for t in tra_cuu_cua(so)),
        "con_treo": sum(1 for v in so if v.get("cau_hoi_treo")),
    }


def tra_cuu_cua(so: list[dict]):
    """`tra_cuu` là MỘT object theo hợp đồng; chấp cả dạng danh sách."""
    for v in so:
        t = v.get("tra_cuu")
        if isinstance(t, dict):
            yield t
        elif isinstance(t, list):
            yield from (x for x in t if isinstance(x, dict))


def dem_la(x) -> int:
    """Số dữ kiện lá: mọi giá trị vô hướng không rỗng trong cây."""
    if x is None or x == "" or x == [] or x == {}:
        return 0
    if isinstance(x, dict):
        return sum(dem_la(v) for v in x.values())
    if isinstance(x, list):
        return sum(dem_la(v) for v in x)
    return 1


# ── CLI ────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="lenh", required=True)

    sub.add_parser("chon", help="liệt kê kho docx_anh (JSON)")

    p = sub.add_parser("van-ban", help="trải markdown ra thư mục")
    p.add_argument("--ra", type=Path, required=True)
    p.add_argument("--bo-figure", action="store_true",
                   help="CẮT figure — chỉ để đo mất mát, đừng dùng để bóc")

    p = sub.add_parser("anh-em", help="tên tệp anh em theo thư mục hồ sơ")
    p.add_argument("--ra", type=Path)

    p = sub.add_parser("kiem", help="kiểm sổ đã ghi")
    p.add_argument("--so", type=Path, default=SO)

    a = ap.parse_args()
    kho = chon_kho()

    if a.lenh == "chon":
        thieu = [d for d in kho if not d["co_ban_doc_pro"]]
        print(json.dumps({
            "tep": len(kho),
            "ho_so": len({d["ho_so_thu_muc"] for d in kho}),
            "thieu_ban_doc_pro": len(thieu),
            "danh_sach": kho,
        }, ensure_ascii=False, indent=1))
        return 0

    if a.lenh == "van-ban":
        a.ra.mkdir(parents=True, exist_ok=True)
        a.ra.chmod(0o700)
        tong_fig = 0
        for d in kho:
            if not d["co_ban_doc_pro"]:
                continue
            md = markdown_cua(d["id"], bo_figure=a.bo_figure)
            tong_fig += dem_figure(md)
            (a.ra / f"{d['id']}.md").write_text(
                f"<!-- {d['duong_dan']} -->\n\n{md}\n")
        print(f"{sum(1 for d in kho if d['co_ban_doc_pro'])} tệp, "
              f"{tong_fig} khối figure, ra {a.ra}")
        return 0

    if a.lenh == "anh-em":
        theo_ho_so: dict[str, list[str]] = {}
        for d in kho:
            hs = NGUON / d["ho_so_thu_muc"]
            if d["ho_so_thu_muc"] in theo_ho_so:
                continue
            theo_ho_so[d["ho_so_thu_muc"]] = sorted(
                unicodedata.normalize("NFC", str(x.relative_to(hs)))
                for x in hs.rglob("*") if x.is_file()
                and not x.name.startswith((".", "~$")))
        out = json.dumps(theo_ho_so, ensure_ascii=False, indent=1)
        if a.ra:
            a.ra.write_text(out)
            a.ra.chmod(0o600)
            print(f"{len(theo_ho_so)} hồ sơ, "
                  f"{sum(len(v) for v in theo_ho_so.values())} tệp anh em → {a.ra}")
        else:
            print(out)
        return 0

    if a.lenh == "kiem":
        if not a.so.exists():
            print(f"chưa có sổ: {a.so}", file=sys.stderr)
            return 1
        so = json.loads(a.so.read_text())
        loi = kiem_so(so, kho)
        tk = thong_ke(so)
        tk["du_kien_la"] = sum(dem_la(v) for v in so)
        print(json.dumps(tk, ensure_ascii=False, indent=1))
        for l in loi:
            print(f"LỖI: {l}", file=sys.stderr)
        print(f"{len(loi)} lỗi", file=sys.stderr)
        return 1 if loi else 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
