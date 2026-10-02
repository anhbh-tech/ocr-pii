"""Không một định danh thật nào của kho được nằm trong cây git.

Token lấy LÚC CHẠY từ các sổ JSON trong `~/.private/so` (ngoài cây git): mã
hồ sơ, số hợp đồng/phụ lục, số đơn, tên nhãn, tên đối tác, tên tệp gốc. Tệp
này không chứa token thật nào — chỉ chứa hình dạng của chúng. Máy không có
`~/.private/so` thì bỏ qua sạch.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re
import subprocess
import unicodedata

import pytest

GOC = pathlib.Path(__file__).resolve().parent.parent
SO = pathlib.Path(os.environ.get("OCR_LAB_SO", pathlib.Path.home() / ".private" / "so"))

pytestmark = pytest.mark.skipif(
    not SO.is_dir(), reason="không có ~/.private/so (máy không có dữ liệu thật)")

#: Hình dạng định danh trong mọi chuỗi của sổ.
_MA = re.compile(r"(?<![A-Za-z0-9])(?:[A-ZĐ]{2,5}\d{2,}(?:-\d+)?|V\d{4}-\d{2,})(?![0-9])")
#: `V<năm>-<số>`: số đề nghị thanh toán, văn bản hay viết trần không có `V`.
_SO_DE_NGHI = re.compile(r"V\d{4}-\d{2,}")
_SO_HOP_DONG = re.compile(r"\d{2,}/\d{4}/[A-ZĐ][A-ZĐ\-]*[A-ZĐ]")
_MA_HO_SO = re.compile(r"(?<![0-9.])\d{2,4}\.\s?US\b")
_CHUOI_SO = re.compile(r"(?<![A-Za-z0-9])\d{7,}(?![A-Za-z0-9])")

#: Khoá mà giá trị là tên riêng: nhãn hiệu, đối tác.
_KHOA_TEN = {"nhan_hieu", "nhan_gan_nhat", "nhan_ho_so"}
#: Khoá mà giá trị là đường dẫn / tên tệp gốc.
_KHOA_TEP = {"ten_tep", "duong_dan", "tep", "ban_chinh"}
#: Tên tệp chỉ tính khi mang ngày lưu (`_ddmmyy`, `yyyymmdd`): tên chung
#: chung như "Ket qua tra cuu" hay tên sổ `hang_cho_xung_dot` không định danh ai.
_NGAY_TRONG_TEN = re.compile(r"(?<!\d)(?:\d{6}|\d{8})(?!\d)")
#: Trùng hình dạng nhưng không định danh gì: `MARK` là nhãn trường TSDR mà
#: bản parse đọc nhầm thành tên nhãn; `PL01` là số thứ tự phụ lục, hợp đồng
#: nào cũng có.
_KHONG_PHAI_DINH_DANH = {"MARK", "PL01"}
#: Thư mục con của `~/.private/so` không phải sổ.
_THU_MUC_KHONG_PHAI_SO = ("quarantine", "tmp", "_")


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _la_ngay(s: str) -> bool:
    """`12122025`, `20250708`: ngày trong tên tệp, không định danh ai."""
    if len(s) != 8:
        return False
    for f in ("%d%m%Y", "%Y%m%d"):
        try:
            _dt.datetime.strptime(s, f)
            return True
        except ValueError:
            pass
    return False


def _ten_trong_thu_muc(thu_muc: str) -> set[str]:
    """`<số>. US. <NHÃN>, hinh IN CLASS 022` / `<số>. <A> v. <B> (<C>)` →
    các tên riêng. Tên thư mục hồ sơ là nơi tên khách và tên nhãn nằm."""
    ra = set()
    for s in _nfc(thu_muc).split("/"):
        if not re.match(r"\s*\d{2,4}\.", s):  # "0. Info" là thư mục con, không phải hồ sơ
            continue
        s = re.sub(r"^\s*\d+\.\s*(?:US\.)?\s*", "", s)
        s = re.sub(r"\s+in\s+class\s+\d+.*$", "", s, flags=re.I)
        for manh in re.split(r"\s+v\.\s+|[(),]", s):
            manh = re.sub(r"^(?:\d+\s+)?(?:tac pham(?: hoa tiet tat)?)\s*", "",
                          manh.strip(), flags=re.I)
            manh = re.sub(r"\s+(?:published|hinh|handmade device)$", "", manh, flags=re.I)
            if len(manh) >= 3 and not manh.islower():
                ra.add(manh)
    return ra


def _token_that() -> set[str]:
    tok: set[str] = set()

    def lay(x, khoa=None):
        if isinstance(x, dict):
            for k, v in x.items():
                lay(k)
                lay(v, k)
                if k == "doi_tac" and isinstance(v, dict) and isinstance(v.get("ten"), str):
                    tok.add(_nfc(v["ten"]).strip())
                if k == "thu_muc" and isinstance(v, str):
                    tok.update(_ten_trong_thu_muc(v))
        elif isinstance(x, list):
            for v in x:
                lay(v, khoa)
        elif isinstance(x, str):
            s = _nfc(x)
            for m in _MA.finditer(s):
                tok.add(m.group())
                if _SO_DE_NGHI.fullmatch(m.group()):
                    tok.add(m.group()[1:])
            tok.update(m.group() for m in _SO_HOP_DONG.finditer(s))
            tok.update(re.sub(r"\s", "", m.group()) for m in _MA_HO_SO.finditer(s))
            tok.update(m.group() for m in _CHUOI_SO.finditer(s)
                       if not _la_ngay(m.group()) and len(set(m.group())) > 2)
            if khoa in _KHOA_TEN and len(s.strip()) >= 3:
                tok.add(s.strip())
            if khoa in _KHOA_TEP:
                goc = os.path.splitext(s.rsplit("/", 1)[-1])[0]
                if len(goc) >= 14 and _NGAY_TRONG_TEN.search(goc):
                    tok.add(goc)

    for f in sorted(SO.rglob("*.json")):
        # Chỉ sổ: thư mục cách ly và nháp (`tmp/`, `_…`) chứa cả đầu ra test,
        # tức toàn token bịa của chính cây này.
        if any(p.startswith(_THU_MUC_KHONG_PHAI_SO) for p in f.relative_to(SO).parts[:-1]):
            continue
        try:
            lay(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return {t for t in tok if len(t) >= 3} - _KHONG_PHAI_DINH_DANH


def _tep_theo_doi() -> list[pathlib.Path]:
    ra = subprocess.run(["git", "ls-files", "-z"], cwd=GOC, capture_output=True,
                        text=True, check=True).stdout
    return [GOC / p for p in ra.split("\0") if p and not p.endswith(".lock")]


def _than(t: str) -> str:
    # "NNN.US" phải bắt cả "NNN. US".
    return re.escape(t).replace(r"\.US", r"\.\s?US")


def test_cay_git_khong_chua_dinh_danh_that():
    tok = _token_that()
    assert tok, "sổ trong ~/.private/so không cho token nào — kiểm lại cách đọc"
    # Một phép thay thế cho mọi token, dài trước. Ranh giới là chữ/số, không
    # phải `\w`: tên tệp nối bằng `_`, nên `_` phải tính là ranh giới.
    mau = re.compile(r"(?<![^\W_])(?:"
                     + "|".join(_than(t) for t in sorted(tok, key=len, reverse=True))
                     + r")(?![^\W_])")
    lo: list[str] = []
    for p in _tep_theo_doi():
        try:
            van_ban = _nfc(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        for k in mau.finditer(van_ban):
            dong = van_ban.count("\n", 0, k.start()) + 1
            # Chỉ in vị trí và độ dài, không in token: log CI cũng là nơi công khai.
            lo.append(f"{p.relative_to(GOC)}:{dong} (token dài {len(k.group())})")
    assert not lo, "định danh thật trong tệp git:\n" + "\n".join(lo)
