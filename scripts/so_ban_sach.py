"""Dò bản sạch ↔ ảnh chụp màn hình, và mạch tư vấn nhiều phần, trên toàn kho.

VẤN ĐỀ
───────
Ảnh chụp một đoạn chat là BẢN SAO HAO HỤT của một tài liệu thường nằm ngay
cạnh nó trên đĩa. Ví dụ đã kiểm bằng tay (tên bịa, hình dạng thật), thư mục
`0. Info`:

  TV071-98_Tu van_010125.docx        bản sạch, ~2.5k ký tự, không bị cắt
  TV071-98_Tin nhan tu van_010125.docx   cùng nội dung dán vào chat rồi chụp
                                     màn hình, ~7.1k ký tự OCR, cụt giữa câu
                                     trả lời 3
  TV0071-98_Tu van 2_020125.docx     phần tiếp theo (`TV0071` là lỗi gõ thứ 2)

Không bản nào thay được bản kia: bản sạch KHÔNG chứa ba câu hỏi của khách —
ba câu đó chỉ có trong ảnh chụp.

Hậu quả nếu không nối chúng lại:
  - cổng định dạng đánh trượt cả mạch vì chấm trên bản ảnh chụp, trong khi
    bản sạch nằm ngay bên cạnh;
  - agent trích xuất tuyên bố "câu hỏi không được trả lời" trong khi câu trả
    lời nằm ở tệp anh em.

BA PHÉP DÒ
──────────
1. Cặp bản sạch ↔ ảnh chụp. Tên tệp chỉ là GỢI Ý, không phải bằng chứng —
   xem `QUY_TAC_TEN_KHONG_DU_TIN` bên dưới. Xác nhận bằng độ trùng nội dung
   giữa hai bản parse ADE.
2. Mạch nhiều phần: `Tu van` → `Tu van 2` → …, ghép được cả khi mã hồ sơ
   trong tên bị gõ sai (`TV0071` với `TV071`).
3. Mỗi cặp: ghi rõ phần CHỈ có ở ảnh chụp và phần CHỈ có ở bản sạch. Không
   bao giờ gộp hai tệp thành một bản ghi — ghi là HAI NGUỒN của MỘT mạch.

Thêm: câu hỏi mà câu trả lời không nằm trong bất kỳ `.docx` nào của mạch,
nhưng kết quả là một tệp anh em thuộc định dạng khác (`tra_loi_khac_dinh_dang`).

QUY TẮC TÊN KHÔNG ĐỦ TIN
────────────────────────
Đo thật trên kho này:
  - một `.../Tra cuu so bo/Tin nhan tra cuu so bo.docx` mang chữ "Tin nhan"
    nhưng có 21.320 ký tự text và không phải ảnh chụp;
  - một cặp đã xác nhận có NGÀY KHÁC NHAU trong tên (cách nhau một tuần),
    nên luật "cùng ngày" sẽ bỏ sót;
  - một `<Mã>.US_Tu van so bo_<ddmmyy>.docx` là ảnh chụp thuần tuý mà trong tên
    không hề có chữ "Tin nhan".
Vì vậy ảnh chụp được nhận ra từ CẤU TRÚC TỆP (docx chỉ có ảnh, không có run
text; pdf không có lớp text), còn cặp được xác nhận từ ĐỘ TRÙNG NỘI DUNG.
Luật tên vẫn được chấm và ghi lại, để thấy nó đúng/sai bao nhiêu. Điểm trên
toàn kho: 7 tên có chữ "tin nhan", 4 trong số đó thật sự là ảnh chụp; còn 197
ảnh chụp mà tên không hề nói.

RA ĐÂU
──────
Sổ JSON tại `~/.private/so/ban_sach_vs_anh.json` — NGOÀI cây git, cùng vùng
tin cậy với `~/.private/ade_out`, vì nó chứa nguyên văn lời khách. Cổng định
dạng đọc sổ này; script không sửa điểm của cổng, không đổi tên, không xoá gì.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ocr_lab.ade_store import DEFAULT_STORE, doc_id_for      # noqa: E402
from ocr_lab.danh_tinh import chuan_ma                      # noqa: E402

#: Kho hồ sơ gốc. CHỈ ĐỌC — không đổi tên, không di chuyển, không xoá.
PRIVATE = Path.home() / ".private" / "refiny_data"

#: Sổ ra. Đường duy nhất script này được phép ghi ngoài cây làm việc.
DEFAULT_LEDGER = Path.home() / ".private" / "so" / "ban_sach_vs_anh.json"

# ── Ngưỡng ───────────────────────────────────────────────────────────────
#: Độ dài n-gram từ dùng để so nội dung. 4 đủ dài để không trùng ngẫu nhiên
#: giữa hai văn bản pháp lý cùng mẫu câu, đủ ngắn để chịu được lỗi OCR rải rác.
NGRAM = 4

#: Chứa-trong = |A∩B| / min(|A|,|B|). Bản sạch nằm GỌN trong ảnh chụp (ảnh
#: chụp có thêm khung chat, câu hỏi khách), nên Jaccard thấp giả tạo; phải
#: dùng chứa-trong. Đo thật: 3 cặp đúng ở 0,80–0,97; tệp không cùng mạch cao
#: nhất chỉ 0,41. Đặt 0,60 — giữa hai cụm, cách mỗi bên một quãng rộng.
NGUONG_TRUNG = 0.60

#: docx dưới ngần này ký tự text mà vẫn có ảnh nhúng → coi là ảnh chụp thuần.
#: Đo thật: 12 tệp như vậy trong kho đều có ĐÚNG 0 ký tự; 200 là mép an toàn
#: cho tệp lỡ dính một dòng chú thích.
TOI_DA_KY_TU_ANH_CHUP = 200

#: Số phần tối đa của một mạch. Chặn số hoá đơn bị đọc nhầm thành số phần
#: (`Invoice 1473`, `Bill 29194`, `Letter of Representation_2025`).
TOI_DA_SO_PHAN = 20

#: Token trong tên tệp xuất hiện ở ngần này tệp trở lên là token chung
#: (`hop`, `dong`, `letter`, `payment`…), không dùng để nhận ra một hiện vật.
DF_TOKEN_CHUNG = 12

#: Token phải hiếm cỡ này trong tên tệp toàn kho mới được coi là TÊN HIỆN VẬT
#: (`pnl`). Hiếm thì mới trỏ đúng một tệp, không trỏ cả rổ.
DF_TOKEN_HIEN_VAT = 4

#: …và phải hiếm cả trong NỘI DUNG. Đo thật trên 421 bản parse: `pnl` có mặt
#: ở 5 tài liệu, còn `status` 104, `thu` 129, `phi` 131 — từ nghiệp vụ phổ
#: thông lọt lưới tên-tệp-hiếm nhưng không trỏ tới hiện vật nào cả.
DF_NOI_DUNG_HIEN_VAT = 10

#: Bản sạch phải có ít nhất ngần này n-gram. Chứa-trong lấy mẫu số là bên NHỎ,
#: nên một tệp tí hon (45 n-gram: bảng số tài khoản) nằm lọt trong một hợp đồng
#: quét dài sẽ đạt 1,000 mà không phải bản sao của nó. Mọi cặp thật trong kho
#: có bản sạch ≥ 288 n-gram.
TOI_THIEU_NGRAM_BAN_SACH = 100

#: Ảnh chụp chat DÀI HƠN bản sạch (thêm khung chat, thêm câu hỏi của khách);
#: bản quét chỉ là cùng tài liệu chụp lại nên dài xấp xỉ bản gõ. Đo thật:
#: bản quét 0,97–1,08 lần; ảnh chụp chat 1,31–2,81 lần. Cắt ở 1,2.
NGUONG_TY_LE_ANH_CHUP = 1.2

#: Một dòng có dưới ngần này phần trăm n-gram chung với bản kia thì tính là
#: "chỉ có ở bản này". Nới tay vì OCR ảnh chụp sai dấu liên tục.
NGUONG_DONG_RIENG = 0.34

#: Đuôi tệp coi là hiện vật đọc được. Ngoài danh sách này thì không chấm.
DUOI_DOC_DUOC = {".docx", ".doc", ".pdf", ".xlsx", ".jpg", ".jpeg", ".png"}

#: Đuôi tệp bản chất là ảnh.
#: Đuôi tệp của THƯ TỪ — nơi câu hỏi của khách thực sự nằm.
DUOI_THU_TU = {".docx", ".doc", ".pdf"}
DUOI_ANH = {".jpg", ".jpeg", ".png"}

#: Hư từ tiếng Việt (đã bỏ dấu) — loại trước khi lấy từ khoá câu hỏi.
HU_TU = set("""
la va cua co the cac nhung mot minh ban anh chi em ta ho khi nen cho den tu voi tai trong ngoai
ve nhu vay thi ma con neu se da dang duoc khong phai rat cung hay hoac boi nay do kia ay sau truoc
gi nao sao ra vao len xuong cai chiec viec thuc hien theo tren duoi giua qua lai moi day
toi chung ai dau gio nua roi chua van luon deu ca tat tinh hai ba bon nam
""".split())

#: Dấu hiệu một câu là CÂU HỎI. Dấu `?` là chính; các cụm còn lại bắt câu hỏi
#: mà OCR nuốt mất dấu hỏi ở cuối.
DAU_HOI = re.compile(
    r"\?|như thế nào|bao nhiêu|có cần|làm sao|đúng không|hay không",
    re.IGNORECASE,
)

# ── Chuẩn hoá chuỗi ──────────────────────────────────────────────────────

def _nfc(s: str) -> str:
    """macOS trả tên tệp ở NFD; mọi so sánh chuỗi phải quy về NFC trước."""
    return unicodedata.normalize("NFC", s)


def bo_dau(s: str) -> list[str]:
    """Tách từ sau khi bỏ dấu và hạ chữ.

    OCR ảnh chụp sai dấu gần như mọi câu (`yêu cău` thay `yêu cầu`), nên so
    có dấu là so sai. Bỏ dấu rồi so thì hai bản của cùng một đoạn khớp nhau.
    """
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c)).replace("đ", "d")
    return re.sub(r"[^a-z0-9\s]", " ", s).split()


def ngrams(text: str, n: int = NGRAM) -> set[str]:
    w = bo_dau(text)
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


def tu_khoa(text: str) -> set[str]:
    return {w for w in bo_dau(text) if len(w) > 2 and w not in HU_TU and not w.isdigit()}


def go_chu_thich(md: str) -> str:
    """Bỏ chú thích HTML mà ADE gắn cuối bản parse (`<!-- doc_id=... -->`)."""
    return re.sub(r"<!--.*?-->", "", md, flags=re.S)


def gop_dong(md: str) -> str:
    """Nối các dòng bị ngắt cứng thành một mạch chữ liền.

    ADE xuống dòng theo mép ảnh, không theo câu. Không nối lại thì mọi câu
    hỏi đều bị cắt làm đôi và không bao giờ thấy được dấu `?` cùng chủ ngữ.
    """
    t = go_chu_thich(md)
    return re.sub(r"\s+", " ", re.sub(r"[ \t]*\n[ \t]*", " ", t)).strip()


def cac_cau(md: str) -> list[str]:
    """Cắt câu. Cắt cả trước dấu đánh số `1.`, `2.` vì chat hay liệt kê."""
    return [s.strip() for s in re.split(r"(?<=[.?!])\s+|(?=\s\d\.\s)", gop_dong(md)) if s.strip()]


# ── Tên tệp ──────────────────────────────────────────────────────────────

#: Mã hồ sơ ở đầu tên: `TV071-98_`, `NH9003.US_`, `BQ093,US_`, `1.2.`…
MA_HO_SO = re.compile(
    r"^\s*((?:[A-Z]{2}\d+|\d+)(?:[.,]\s*[A-Z]{2,3})?(?:[-–]\d+)?(?:\.\d+)?)[\s_.,]+",
    re.IGNORECASE,
)
#: Ngày cuối tên: `_050626`, `_12122025`, `_18.11.2024`.
NGAY = re.compile(r"[_\s]\(?(\d{6}|\d{8}|\d{2}[._]\d{2}[._]\d{2,4})\)?$")
#: Số bản: `_v0.1C`, `_ver0.1Ha`.
BAN = re.compile(r"[_\s]+v(er)?\s*\d+(\.\d+)?[A-Za-z]*$", re.IGNORECASE)
#: Số phần cuối nhãn: `Tu van 2`, `Tra cuu lan 2`, `Dot 2`, `Round 1`.
SO_PHAN = re.compile(r"(?:^|[\s_])(?:lan|dot|phan|ky|part)?\s*(\d{1,4})$", re.IGNORECASE)
#: Tiền tố "tin nhắn" — luật tên mà đề bài nêu, chấm để đối chiếu, không tin.
#: Chấm trên chuỗi ĐÃ bỏ dấu và tách từ, vì hai lần sai đo được khi chấm thẳng
#: trên tên gốc: `\b` không nhận ranh giới sau gạch dưới nên `_Tin nhan tu van`
#: bị bỏ sót, còn `thong tin nhan hieu` (nhãn hiệu) thì bị bắt nhầm.
TIEN_TO_TIN_NHAN = re.compile(r"\btin nhan\b(?! hieu)")


def ten_noi_tin_nhan(stem: str) -> bool:
    """Tên tệp có tự nhận là tin nhắn không."""
    return bool(TIEN_TO_TIN_NHAN.search(" ".join(bo_dau(stem))))


def tach_ten(stem: str) -> tuple[str, str, str]:
    """Tách `stem` thành (mã hồ sơ, nhãn, ngày).

    Nhãn là phần còn lại sau khi gỡ mã hồ sơ, ngày và số bản — đây mới là thứ
    ghép được hai phần của cùng một mạch, vì mã hồ sơ có thể bị gõ sai và ngày
    thì mỗi phần một khác.
    """
    s = _nfc(stem)
    m = MA_HO_SO.match(s)
    ma = m.group(1) if m else ""
    if m:
        s = s[m.end():]
    ngay = ""
    for _ in range(3):                      # `_v0.1C_120626` cần hai vòng
        d = NGAY.search(s)
        if d and not ngay:
            ngay = d.group(1)
        s2 = BAN.sub("", NGAY.sub("", s)).strip(" _-.")
        if s2 == s:
            break
        s = s2
    return ma, s.strip(" _-."), ngay


def tach_phan(nhan: str) -> tuple[str, int]:
    """Trả (nhãn gốc, số phần). Không thấy số phần thì coi là phần 1."""
    m = SO_PHAN.search(nhan)
    if not m:
        return nhan, 1
    so = int(m.group(1))
    if so < 1 or so > TOI_DA_SO_PHAN:       # số hoá đơn, năm — không phải phần
        return nhan, 1
    return nhan[:m.start()].strip(" _-."), so


# ── Kiểm kê kho ──────────────────────────────────────────────────────────

class HienVat:
    """Một tệp trong kho, kèm phân loại nguồn và bản parse (nếu có)."""

    __slots__ = ("rel", "path", "doc_id", "duoi", "ho_so", "thu_muc", "ma",
                 "nhan", "ngay", "phan", "loai", "ly_do", "md", "_grams")

    def __init__(self, rel: str, path: Path):
        self.rel = rel
        self.path = path
        self.doc_id = doc_id_for(rel)
        self.duoi = path.suffix.lower()
        phan_duong = rel.split("/")
        # `Phòng IP / <nhóm dịch vụ> / <hồ sơ> / …` — hồ sơ là cấp 3.
        self.ho_so = "/".join(phan_duong[:3])
        self.thu_muc = str(Path(rel).parent)
        self.ma, nhan, self.ngay = tach_ten(path.stem)
        self.nhan, self.phan = tach_phan(nhan)
        self.loai = "chua_phan_loai"
        self.ly_do = ""
        self.md: str | None = None
        self._grams: set[str] | None = None

    @property
    def grams(self) -> set[str]:
        if self._grams is None:
            self._grams = ngrams(go_chu_thich(self.md or ""))
        return self._grams

    @property
    def la_anh_chup(self) -> bool:
        return self.loai == "anh_chup"

    def tom_tat(self, vai_tro: str = "") -> dict:
        d = {
            "duong_dan": self.rel,
            "doc_id": self.doc_id,
            "loai_nguon": self.loai,
            "so_ky_tu_parse": len(go_chu_thich(self.md or "")),
            "ngay_trong_ten": self.ngay,
            "ma_trong_ten": self.ma,
        }
        if vai_tro:
            d = {"vai_tro": vai_tro, **d}
        return d


def _do_docx(path: Path) -> tuple[int, int]:
    """(số ảnh nhúng, số ký tự text) của một .docx.

    Đây là phép phân biệt ảnh chụp CHẮC CHẮN nhất trong kho: docx dán ảnh chụp
    có ảnh nhúng và 0 run text; docx soạn tay thì ngược lại. Đọc thẳng zip,
    không cần thư viện ngoài, không đụng vào tệp gốc.
    """
    with zipfile.ZipFile(path) as z:
        anh = sum(1 for n in z.namelist() if n.startswith("word/media/"))
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    text = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml, re.S))
    return anh, len(text.strip())


def phan_loai(hv: HienVat) -> None:
    """Gán `loai` ∈ {anh_chup, van_ban, tron, chua_doc_duoc}."""
    if hv.duoi in DUOI_ANH:
        hv.loai, hv.ly_do = "anh_chup", "tệp ảnh rời"
        return
    if hv.duoi == ".docx":
        try:
            anh, chu = _do_docx(hv.path)
        except Exception as e:                       # noqa: BLE001 — tệp hỏng
            hv.loai, hv.ly_do = "chua_doc_duoc", f"docx không mở được: {e}"
            return
        if anh and chu < TOI_DA_KY_TU_ANH_CHUP:
            hv.loai, hv.ly_do = "anh_chup", f"{anh} ảnh nhúng, {chu} ký tự text"
        elif anh:
            hv.loai, hv.ly_do = "tron", f"{anh} ảnh nhúng, {chu} ký tự text"
        else:
            hv.loai, hv.ly_do = "van_ban", f"{chu} ký tự text"
        return
    if hv.duoi == ".pdf":
        try:
            from ocr_lab.classify import classify_pdf, SourceKind
        except Exception:                            # noqa: BLE001
            hv.loai, hv.ly_do = "chua_phan_loai", "thiếu pymupdf, không chấm được pdf"
            return
        try:
            r = classify_pdf(hv.path)
        except Exception as e:                       # noqa: BLE001
            hv.loai, hv.ly_do = "chua_doc_duoc", f"pdf không mở được: {e}"
            return
        hv.loai = {
            SourceKind.SCANNED_PDF: "anh_chup",
            SourceKind.BORN_DIGITAL_PDF: "van_ban",
            SourceKind.HYBRID_PDF: "tron",
        }.get(r.kind, "chua_doc_duoc")
        hv.ly_do = r.kind.value
        return
    hv.loai, hv.ly_do = "van_ban", f"đuôi {hv.duoi}"


def kiem_ke(kho: Path, store: Path) -> list[HienVat]:
    out: list[HienVat] = []
    for p in sorted(kho.rglob("*")):
        if not p.is_file() or p.name.startswith("~$") or p.name == ".DS_Store":
            continue
        rel = _nfc(str(p.relative_to(kho)))
        hv = HienVat(rel, p)
        if hv.duoi not in DUOI_DOC_DUOC:
            hv.loai, hv.ly_do = "chua_doc_duoc", f"đuôi {hv.duoi} ngoài phạm vi"
        else:
            phan_loai(hv)
        f = store / hv.doc_id / "parse.json"
        if f.exists():
            try:
                hv.md = json.loads(f.read_text("utf-8")).get("markdown") or ""
            except Exception:                        # noqa: BLE001
                hv.md = None
        out.append(hv)
    return out


# ── Phép dò 1: cặp bản sạch ↔ ảnh chụp ───────────────────────────────────

def _chua_trong(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def dong_rieng(a: str, b_grams: set[str], toi_da: int = 60) -> list[str]:
    """Các dòng của `a` gần như không có trong `b`.

    Trả về NGUYÊN VĂN, không tóm tắt: người đọc sổ cần thấy đúng câu hỏi của
    khách, không phải lời mô tả về nó.
    """
    out = []
    for ln in go_chu_thich(a).split("\n"):
        ln = ln.strip()
        w = bo_dau(ln)
        if len(w) < NGRAM + 1:
            continue
        g = {" ".join(w[i:i + NGRAM]) for i in range(len(w) - NGRAM + 1)}
        if g and len(g & b_grams) / len(g) < NGUONG_DONG_RIENG:
            out.append(ln)
        if len(out) >= toi_da:
            break
    return out


def tim_cap(hvs: list[HienVat]) -> tuple[list[dict], list[dict]]:
    """Ghép mỗi ảnh chụp với bản sạch của nó, xác nhận bằng nội dung.

    Chỉ tìm trong cùng HỒ SƠ chứ không chỉ cùng thư mục: cặp đã xác nhận đầu
    tiên nằm cùng thư mục, nhưng luật "cùng thư mục" là điều kiện đủ chứ
    không cần — nới ra rồi để độ trùng nội dung quyết định thì bắt được nhiều
    hơn mà không sinh dương tính giả (tệp ngoài mạch cao nhất chỉ 0,41).
    """
    theo_ho_so: dict[str, list[HienVat]] = defaultdict(list)
    for hv in hvs:
        theo_ho_so[hv.ho_so].append(hv)

    cap, le_loi = [], []
    for hv in hvs:
        if not hv.la_anh_chup or not hv.md:
            continue
        ung_vien = []
        for o in theo_ho_so[hv.ho_so]:
            if o.rel == hv.rel or o.la_anh_chup or not o.md:
                continue
            if len(o.grams) < TOI_THIEU_NGRAM_BAN_SACH:
                continue                    # mẩu giấy lọt trong tài liệu dài
            ung_vien.append((_chua_trong(hv.grams, o.grams), o))
        ung_vien.sort(key=lambda x: -x[0])
        tot = ung_vien[0] if ung_vien else (0.0, None)
        if tot[0] < NGUONG_TRUNG or tot[1] is None:
            le_loi.append({
                **hv.tom_tat(),
                "ly_do_phan_loai": hv.ly_do,
                "ban_sach_gan_nhat": (
                    {"duong_dan": tot[1].rel, "chua_trong": round(tot[0], 3)}
                    if tot[1] else None
                ),
                "ket_luan": "không có bản sạch bên cạnh — cổng định dạng đành chấm trên ảnh chụp",
            })
            continue
        sach = tot[1]
        ty_le = len(hv.grams) / len(sach.grams)
        # Ảnh chụp chat mang THÊM nội dung (khung chat, câu hỏi khách) nên dài
        # hơn hẳn; bản quét chỉ là chính tài liệu ấy chụp lại nên dài xấp xỉ.
        # Phân biệt được thì mới nói đúng cho cổng: với ảnh chụp chat, bản sạch
        # là bản ĐỦ HƠN; với bản quét, bản gõ chỉ đẹp chữ hơn, còn bản ký mới
        # là bản có hiệu lực.
        chat = ty_le >= NGUONG_TY_LE_ANH_CHUP
        cap.append({
            "ho_so": hv.ho_so.split("/")[-1],
            "thu_muc": hv.thu_muc,
            "quan_he": "anh_chup_chat" if chat else "ban_quet",
            # HAI NGUỒN của MỘT mạch — không gộp nội dung lại làm một.
            "nguon": [hv.tom_tat("anh_chup"), sach.tom_tat("ban_sach")],
            "do_trung": {
                "chua_trong": round(tot[0], 3),
                "jaccard": round(_jaccard(hv.grams, sach.grams), 3),
                "ty_le_do_dai": round(ty_le, 3),
                "n_gram": NGRAM,
            },
            "quy_tac_ten": {
                "cung_thu_muc": hv.thu_muc == sach.thu_muc,
                "cung_ngay": bool(hv.ngay) and hv.ngay == sach.ngay,
                "khac_moi_tien_to_tin_nhan": ten_noi_tin_nhan(hv.path.stem)
                and not ten_noi_tin_nhan(sach.path.stem),
            },
            "chi_co_o_anh_chup": dong_rieng(hv.md, sach.grams),
            "chi_co_o_ban_sach": dong_rieng(sach.md, hv.grams),
            "cong_dinh_dang_nen_dung": sach.rel,
            "luu_y": None if chat else (
                "ban quet la ban co chu ky — chi lay CHU tu ban go, "
                "khong coi ban go la ban thay the"
            ),
        })
    cap.sort(key=lambda c: -c["do_trung"]["chua_trong"])
    return cap, le_loi


# ── Phép dò 2: mạch nhiều phần ───────────────────────────────────────────

def tim_mach(hvs: list[HienVat], cap: list[dict]) -> list[dict]:
    """Gom các phần của cùng một mạch, kể cả khi mã hồ sơ trong tên gõ sai.

    Khoá gom là (hồ sơ, nhãn đã gỡ số phần). Mã hồ sơ CỐ TÌNH không nằm trong
    khoá — đúng chỗ nó bị gõ sai (`TV0071` với `TV071`) thì đưa vào khoá là tự
    tay tách đôi mạch. Mã được chuẩn hoá riêng rồi đối chiếu để BÁO lỗi gõ.
    """
    anh_theo_ban_sach = {
        c["nguon"][1]["duong_dan"]: c["nguon"][0] for c in cap
    }
    nhom: dict[tuple[str, str], list[HienVat]] = defaultdict(list)
    for hv in hvs:
        if not hv.nhan:
            continue
        nhom[(hv.ho_so, hv.nhan.lower())].append(hv)

    mach = []
    for (ho_so, nhan), thanh_vien in sorted(nhom.items()):
        cac_phan = sorted({hv.phan for hv in thanh_vien})
        if len(cac_phan) == 1 and cac_phan[0] == 1:
            continue                        # mạch một phần — không có gì để nói
        thieu = [p for p in range(1, max(cac_phan) + 1) if p not in cac_phan]
        # Tiền tố đánh số thuần số (`1.2. Product photo`) cũng bị gỡ như mã hồ
        # sơ để gom nhãn, nhưng nó KHÔNG phải mã hồ sơ — không đưa vào phần báo
        # lỗi gõ, kẻo `['1', '1.1', '2'…]` bị đọc thành mã lệch.
        ma_bien_the = sorted({
            hv.ma for hv in thanh_vien
            if hv.ma and any(c.isalpha() for c in hv.ma)
        })
        ma_chuan = sorted({chuan_ma(m) for m in ma_bien_the})
        co_van_ban = any(hv.loai in ("van_ban", "tron") for hv in thanh_vien)

        ds_phan = []
        for hv in sorted(thanh_vien, key=lambda h: (h.phan, h.rel)):
            muc = {"phan": hv.phan, **hv.tom_tat()}
            gan = anh_theo_ban_sach.get(hv.rel)
            if gan:
                # Ảnh chụp là NGUỒN THỨ HAI của chính phần này, không phải
                # một phần riêng — nếu không neo vào đây thì đếm phần sẽ sai.
                muc["nguon_anh_chup"] = gan
            ds_phan.append(muc)

        mach.append({
            "ho_so": ho_so.split("/")[-1],
            "nhan": nhan,
            "co_van_ban": co_van_ban,
            "so_phan_co": len(cac_phan),
            "cac_phan": ds_phan,
            "phan_thieu": thieu,
            "ma_ho_so_trong_ten": {
                "cac_bien_the": ma_bien_the,
                "sau_chuan_hoa": ma_chuan,
                "co_loi_go": len(ma_bien_the) > 1 and len(ma_chuan) == 1,
            },
        })
    mach.sort(key=lambda m: (not m["co_van_ban"], m["ho_so"], m["nhan"]))
    return mach


# ── Phép dò 3: câu hỏi có kết quả ở định dạng khác ───────────────────────

def tim_tra_loi_khac_dinh_dang(hvs: list[HienVat]) -> list[dict]:
    """Câu hỏi nhắc tên một HIỆN VẬT, mà hiện vật đó là tệp không phải .docx.

    Cách người thật tìm: câu hỏi nói "ở file PnL…", và trong hồ sơ có đúng một
    tệp tên `…PnL - ZORB….xlsx`. Nên phép dò bắt token HIẾM dùng chung giữa
    câu hỏi và TÊN tệp anh em — đếm từ chung theo kiểu túi từ thì không ra, vì
    từ pháp lý phổ thông lấn át (đã thử: xlsx không lọt top 6).

    Script KHÔNG tự kết luận câu hỏi đã được trả lời bằng chữ hay chưa — đó là
    việc đọc hiểu. Sổ ghi đủ bằng chứng hai phía: đoạn văn bản gần nhất trong
    các `.docx` của mạch, và tệp kết quả ở định dạng khác.
    """
    df = Counter()
    df_nd = Counter()                        # tần suất trong NỘI DUNG
    for hv in hvs:
        df.update(set(bo_dau(hv.path.stem)))
        if hv.md:
            df_nd.update(set(bo_dau(go_chu_thich(hv.md))))
    chung = {w for w, c in df.items() if c >= DF_TOKEN_CHUNG}

    theo_ho_so: dict[str, list[HienVat]] = defaultdict(list)
    for hv in hvs:
        theo_ho_so[hv.ho_so].append(hv)

    ra, da_thay = [], set()
    for hv in hvs:
        if not hv.md:
            continue
        # Chỉ hỏi trong THƯ TỪ của hồ sơ. Đo được: 4/5 bản ghi đầu tiên là nhiễu
        # từ hai chỗ — `.xlsx` biểu mẫu (dấu `?` là tiêu đề cột: "Case Number
        # (khách hàng không điền mục này)") và thư mục quy trình chuẩn
        # `_Quy trinh chuan v2.0` (dấu `?` là nhãn cổng quyết định BPMN:
        # "Tra cuu chuyen sau qua LS Hoa Ky?"). Cả hai đều không phải khách hỏi.
        if hv.duoi not in DUOI_THU_TU or hv.ho_so.split("/")[-1].startswith("_"):
            continue
        cau = cac_cau(hv.md)
        for i, s in enumerate(cau):
            if not DAU_HOI.search(s):
                continue
            # Câu hỏi hay bị OCR cắt rời khỏi chủ ngữ — kèm câu liền trước.
            hoi = (cau[i - 1] + " " if i else "") + s
            tk = set(bo_dau(hoi))
            hien_vat = []
            for o in theo_ho_so[hv.ho_so]:
                if o.rel == hv.rel or o.duoi in (".docx", ".doc"):
                    continue
                token = {
                    w for w in (tk & set(bo_dau(o.path.stem)))
                    if len(w) > 2 and w not in chung and w not in HU_TU
                    and not w.isdigit() and df[w] <= DF_TOKEN_HIEN_VAT
                    and df_nd[w] <= DF_NOI_DUNG_HIEN_VAT
                }
                if token:
                    hien_vat.append({
                        "duong_dan": o.rel,
                        "doc_id": o.doc_id,
                        "dinh_dang": o.duoi,
                        "token_hien_vat": sorted(token),
                    })
            if not hien_vat:
                continue
            khoa = sorted({t for h in hien_vat for t in h["token_hien_vat"]})
            # Câu hỏi bị OCR ngắt đôi sinh hai câu chồng nhau cùng trỏ một
            # hiện vật; giữ lần đầu, bỏ bản trùng.
            van_tay = (hv.rel, tuple(khoa), tuple(sorted(h["duong_dan"] for h in hien_vat)))
            if van_tay in da_thay:
                continue
            da_thay.add(van_tay)

            # Chữ trong các .docx của hồ sơ có nhắc tên hiện vật không?
            trong_docx = []
            for o in theo_ho_so[hv.ho_so]:
                if o.duoi not in (".docx", ".doc") or not o.md:
                    continue
                for c2 in cac_cau(o.md):
                    tk2 = set(bo_dau(c2))
                    if all(k in tk2 for k in khoa) and c2 != s:
                        trong_docx.append({"duong_dan": o.rel, "cau": c2[:400]})
                        break
            ra.append({
                "ho_so": hv.ho_so.split("/")[-1],
                "cau_hoi": hoi.strip()[:500],
                "hoi_trong": hv.rel,
                "hoi_trong_doc_id": hv.doc_id,
                "token_hien_vat": khoa,
                "ket_qua_dinh_dang_khac": hien_vat,
                "nhac_lai_trong_docx": trong_docx,
                "co_tra_loi_bang_chu": bool(trong_docx),
            })
    return ra


# ── Sổ ────────────────────────────────────────────────────────────────────

def lap_so(kho: Path, store: Path) -> dict:
    hvs = kiem_ke(kho, store)
    cap, le_loi = tim_cap(hvs)
    mach = tim_mach(hvs, cap)
    kdd = tim_tra_loi_khac_dinh_dang(hvs)

    # Luật tên mà đề bài nêu, chấm để biết nó đúng bao nhiêu — KHÔNG để dùng.
    ten_noi_anh_chup = {hv.rel for hv in hvs if ten_noi_tin_nhan(hv.path.stem)}
    that_su_anh_chup = {hv.rel for hv in hvs if hv.la_anh_chup}
    cap_dung_ten = sum(1 for c in cap if c["quy_tac_ten"]["khac_moi_tien_to_tin_nhan"])
    cap_dung_ngay = sum(1 for c in cap if c["quy_tac_ten"]["cung_ngay"])

    mach_van_ban = [m for m in mach if m["co_van_ban"]]
    anh_co_parse = [hv for hv in hvs if hv.la_anh_chup and hv.md]
    anh_chua_doc = [hv for hv in hvs if hv.la_anh_chup and not hv.md]
    cap_chat = [c for c in cap if c["quan_he"] == "anh_chup_chat"]
    cap_quet = [c for c in cap if c["quan_he"] == "ban_quet"]
    uu_tien = {
        c["nguon"][0]["doc_id"]: {
            "vai_tro": "anh_chup",
            "thay_bang_doc_id": c["nguon"][1]["doc_id"],
            "thay_bang_duong_dan": c["nguon"][1]["duong_dan"],
            "chua_trong": c["do_trung"]["chua_trong"],
            "quan_he": c["quan_he"],
            "luu_y": c["luu_y"],
        }
        for c in cap
    }

    return {
        "tao_luc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kho_ho_so": str(kho),
        "kho_bang_chung": str(store),
        "quy_tac": (
            "anh chup nhan ra tu cau truc tep (docx chi co anh, pdf khong co lop text); "
            "cap xac nhan bang do trung n-gram giua hai ban parse ADE, khong tin ten tep; "
            "mach ghep theo nhan sau khi go ma ho so, ngay va so ban; "
            "moi cap ghi la hai nguon cua mot mach, khong gop lam mot"
        ),
        "nguong": {
            "n_gram": NGRAM,
            "chua_trong": NGUONG_TRUNG,
            "toi_da_ky_tu_anh_chup": TOI_DA_KY_TU_ANH_CHUP,
            "toi_da_so_phan": TOI_DA_SO_PHAN,
            "df_token_hien_vat": DF_TOKEN_HIEN_VAT,
        },
        "tom_tat": {
            "so_tep": len(hvs),
            "so_tep_co_parse": sum(1 for h in hvs if h.md is not None),
            "phan_loai_nguon": dict(Counter(h.loai for h in hvs)),
            "so_anh_chup": len(that_su_anh_chup),
            "so_anh_chup_co_parse_de_doi_chieu": len(anh_co_parse),
            "so_anh_chup_chua_co_parse": len(anh_chua_doc),
            "so_anh_chup_co_ban_sach": len(cap),
            "trong_do_anh_chup_chat": len(cap_chat),
            "trong_do_ban_quet_cua_ban_go": len(cap_quet),
            "so_anh_chup_khong_co_ban_sach": len(le_loi),
            "so_mach_nhieu_phan": len(mach),
            "so_mach_nhieu_phan_co_van_ban": len(mach_van_ban),
            "so_mach_co_tu_2_phan_co_van_ban": sum(
                1 for m in mach_van_ban if m["so_phan_co"] >= 2
            ),
            "so_mach_thieu_phan": sum(1 for m in mach if m["phan_thieu"]),
            "so_mach_thieu_phan_co_van_ban": sum(
                1 for m in mach_van_ban if m["phan_thieu"]
            ),
            "so_mach_lech_ma_ho_so": sum(
                1 for m in mach if m["ma_ho_so_trong_ten"]["co_loi_go"]
            ),
            "so_cau_hoi_co_ket_qua_dinh_dang_khac": len(kdd),
            "quy_tac_ten_tep_dung_bao_nhieu": {
                "ten_co_chu_tin_nhan": len(ten_noi_anh_chup),
                "trong_do_that_su_la_anh_chup": len(ten_noi_anh_chup & that_su_anh_chup),
                "anh_chup_ma_ten_khong_noi": len(that_su_anh_chup - ten_noi_anh_chup),
                "cap_dung_luat_tien_to_tin_nhan": cap_dung_ten,
                "cap_dung_luat_cung_ngay": cap_dung_ngay,
                "ket_luan": "luat ten bat thieu va bat nham — chi dung de doi chieu",
            },
        },
        "cap_ban_sach": cap,
        "anh_chup_khong_co_ban_sach": le_loi,
        "mach_tu_van": mach,
        "tra_loi_khac_dinh_dang": kdd,
        "uu_tien_cho_cong_dinh_dang": {
            "cach_dung": (
                "cong dinh dang tra doc_id trong 'theo_doc_id'; co thi cham tren "
                "'thay_bang_doc_id' (ban sach) thay vi tren anh chup"
            ),
            "theo_doc_id": uu_tien,
        },
        "de_xuat_doi_ten": [
            {
                "duong_dan": p["duong_dan"],
                "ma_hien_tai": p["ma_trong_ten"],
                "ma_de_xuat": chuan_de_xuat,
                "ly_do": f"lech ma voi cac phan khac cua mach '{m['nhan']}'",
                "trang_thai": "chi de xuat — script khong doi ten bat ky tep nao",
            }
            for m in mach if m["ma_ho_so_trong_ten"]["co_loi_go"]
            for chuan_de_xuat in [min(
                m["ma_ho_so_trong_ten"]["cac_bien_the"], key=len
            )]
            for p in m["cac_phan"]
            if p["ma_trong_ten"] and p["ma_trong_ten"] != chuan_de_xuat
        ],
    }


# ── Tự kiểm ──────────────────────────────────────────────────────────────

#: Ca đã kiểm bằng tay; mọi thay đổi script phải giữ nguyên nó. Đuôi đường
#: dẫn là tên tệp thật nên ca nằm ngoài cây git:
#: `{"ho_so", "anh_chup", "ban_sach", "mach", "bien_the_ma", "ket_qua_pnl"}`.
CA_MAU = Path.home() / ".private" / "so" / "ca_mau_ban_sach.json"


def tu_kiem(so: dict, ca: dict) -> list[str]:
    loi = []

    def ck(dieu: bool, msg: str) -> None:
        if not dieu:
            loi.append(msg)

    hs = ca["ho_so"]
    cap = [c for c in so["cap_ban_sach"] if c["ho_so"].startswith(hs)]
    ck(len(cap) == 1, f"hồ sơ mẫu phải có đúng 1 cặp, thấy {len(cap)}")
    if cap:
        c = cap[0]
        anh, sach = c["nguon"][0], c["nguon"][1]
        ck(anh["duong_dan"].endswith(ca["anh_chup"]),
           f"ảnh chụp sai: {anh['duong_dan']}")
        ck(sach["duong_dan"].endswith(ca["ban_sach"]),
           f"bản sạch sai: {sach['duong_dan']}")
        ck(c["do_trung"]["chua_trong"] >= 0.90,
           f"độ trùng cặp mẫu chỉ {c['do_trung']['chua_trong']}")
        ck(len(c["nguon"]) == 2, "cặp phải là hai nguồn, không gộp")
        # Ba câu hỏi của khách chỉ có trong ảnh chụp.
        rieng = " ".join(c["chi_co_o_anh_chup"]).lower()
        ck("thắc mắc" in rieng, "phần chỉ có ở ảnh chụp thiếu câu hỏi của khách")
        ck("pnl" in rieng.lower(), "phần chỉ có ở ảnh chụp thiếu câu hỏi về PnL")
        ck(c["cong_dinh_dang_nen_dung"] == sach["duong_dan"],
           "cổng định dạng phải được chỉ sang bản sạch")
        ck(so["uu_tien_cho_cong_dinh_dang"]["theo_doc_id"]
           .get(anh["doc_id"], {}).get("thay_bang_doc_id") == sach["doc_id"],
           "bảng ưu tiên không trỏ ảnh chụp sang bản sạch")

    mach = [m for m in so["mach_tu_van"]
            if m["ho_so"].startswith(hs) and m["nhan"] == ca["mach"]]
    ck(len(mach) == 1, f"phải có đúng 1 mạch '{ca['mach']}' ở hồ sơ mẫu, thấy {len(mach)}")
    if mach:
        m = mach[0]
        ck([p["phan"] for p in m["cac_phan"]] == [1, 2],
           f"mạch mẫu phải có phần 1 và 2, thấy {[p['phan'] for p in m['cac_phan']]}")
        ck(m["ma_ho_so_trong_ten"]["co_loi_go"],
           "phải phát hiện lỗi gõ mã hồ sơ giữa các biến thể")
        ck(set(m["ma_ho_so_trong_ten"]["cac_bien_the"]) == set(ca["bien_the_ma"]),
           f"biến thể mã sai: {m['ma_ho_so_trong_ten']['cac_bien_the']}")
        ck(any("nguon_anh_chup" in p for p in m["cac_phan"]),
           "ảnh chụp phải được neo vào phần 1 như nguồn thứ hai")

    pnl = [q for q in so["tra_loi_khac_dinh_dang"]
           if q["ho_so"].startswith(hs) and "pnl" in q["token_hien_vat"]]
    ck(bool(pnl), "không dò ra câu hỏi PnL của hồ sơ mẫu")
    if pnl:
        dich = {h["duong_dan"] for q in pnl for h in q["ket_qua_dinh_dang_khac"]}
        ck(any(d.endswith(ca["ket_qua_pnl"]) for d in dich),
           f"câu hỏi PnL không trỏ tới tệp xlsx kết quả: {sorted(dich)}")
    return loi


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kho", type=Path, default=PRIVATE, help="kho hồ sơ gốc (chỉ đọc)")
    ap.add_argument("--store", type=Path, default=DEFAULT_STORE, help="kho parse ADE")
    ap.add_argument("--ra", type=Path, default=DEFAULT_LEDGER, help="sổ JSON ghi ra")
    ap.add_argument("--tu-kiem", action="store_true",
                    help=f"chạy khẳng định trên ca đã kiểm tay ({CA_MAU}); khác thì thoát 1")
    ap.add_argument("--khong-ghi", action="store_true", help="chỉ in tóm tắt, không ghi sổ")
    a = ap.parse_args()

    if not a.kho.is_dir():
        print(f"không thấy kho hồ sơ: {a.kho}", file=sys.stderr)
        return 2

    so = lap_so(a.kho, a.store)

    if not a.khong_ghi:
        a.ra.parent.mkdir(parents=True, exist_ok=True)
        a.ra.write_text(json.dumps(so, ensure_ascii=False, indent=2), "utf-8")
        a.ra.chmod(0o600)

    t = so["tom_tat"]
    print(f"{t['so_tep']} tệp, {t['so_tep_co_parse']} có parse ADE")
    print(f"tệp chỉ có ảnh: {t['so_anh_chup']} "
          f"({t['so_anh_chup_co_parse_de_doi_chieu']} đã có parse để đối chiếu, "
          f"{t['so_anh_chup_chua_co_parse']} chưa đọc)")
    print(f"  có bản sạch bên cạnh: {t['so_anh_chup_co_ban_sach']} "
          f"({t['trong_do_anh_chup_chat']} ảnh chụp chat, "
          f"{t['trong_do_ban_quet_cua_ban_go']} bản quét của bản gõ); "
          f"không có: {t['so_anh_chup_khong_co_ban_sach']}")
    print(f"mạch nhiều phần: {t['so_mach_nhieu_phan']} "
          f"({t['so_mach_nhieu_phan_co_van_ban']} có văn bản, trong đó "
          f"{t['so_mach_co_tu_2_phan_co_van_ban']} có từ 2 phần và "
          f"{t['so_mach_thieu_phan_co_van_ban']} thiếu phần); "
          f"lệch mã hồ sơ: {t['so_mach_lech_ma_ho_so']}")
    print(f"câu hỏi có kết quả ở định dạng khác: {t['so_cau_hoi_co_ket_qua_dinh_dang_khac']}")
    if not a.khong_ghi:
        print(f"sổ: {a.ra}")

    if a.tu_kiem:
        if not CA_MAU.is_file():
            print(f"không thấy ca mẫu: {CA_MAU}", file=sys.stderr)
            return 2
        loi = tu_kiem(so, json.loads(CA_MAU.read_text(encoding="utf-8")))
        for l in loi:
            print(f"TỰ KIỂM HỎNG: {l}", file=sys.stderr)
        print("tự kiểm: ĐẠT" if not loi else f"tự kiểm: HỎNG {len(loi)} khẳng định")
        return 1 if loi else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
