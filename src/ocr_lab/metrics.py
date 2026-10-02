"""Bộ đo chất lượng OCR.

Viết TRƯỚC khi chạy bất kỳ engine nào. Lý do: Task 5 (tái lập bảng điểm
SenOCR-Vi trên MDPBench) là bài kiểm tra cho chính tệp này. Nếu ta chạy model
của họ trên đúng dữ liệu của họ mà ra số khác xa con số họ công bố, thì lỗi gần
như chắc chắn nằm ở đây, không nằm ở model. Bộ đo sai thì mọi so sánh engine
sau đó đều vô nghĩa — và cái sai đó không tự lộ ra, nó chỉ cho ra những con số
trông hợp lý.

BA CÁI BẪY UNICODE CỦA TIẾNG VIỆT
─────────────────────────────────
Ba bẫy dưới đây làm hai chuỗi ĐỌC RA GIỐNG HỆT NHAU nhưng so sánh byte thì
khác. Không xử lý thì CER phồng lên vô cớ và ta sẽ loại oan một engine tốt.

1. NFC và NFD — "ề" có hai cách mã hoá
       NFC: U+1EC1                         (1 ký tự)
       NFD: U+0065 U+0302 U+0300  (e + ◌̂ + ◌̀, 3 ký tự)
   Cùng một chữ, độ dài khác nhau 3 lần. Engine khác nhau xuất ra dạng khác
   nhau; PyTorch/transformers thường trả NFC, một số công cụ macOS trả NFD.

2. Vị trí dấu thanh — "hòa" và "hoà"
       hòa : h + o(huyền) + a      ← kiểu cũ, dấu trên nguyên âm đầu
       hoà : h + o + a(huyền)      ← kiểu mới, dấu trên nguyên âm chính
   CẢ HAI đều đúng chính tả và đều là NFC hợp lệ, chỉ khác quy ước đặt dấu.
   Ground truth gõ kiểu này, engine xuất kiểu kia ⇒ sai một ký tự trên mỗi
   âm tiết có dấu. Với văn bản tiếng Việt đặc dấu, đó là CER phồng thêm nhiều
   phần trăm — đủ để đảo ngược thứ hạng giữa hai engine.

   Cách xử lý ở đây: `canonical_vi()` gỡ dấu thanh ra khỏi cụm nguyên âm rồi
   gắn lại ở CUỐI cụm. Ta không phán xử kiểu nào đúng — chỉ cần hai kiểu quy
   về cùng một dạng để so sánh. Đây là chuẩn hoá PHỤC VỤ ĐO, không phải chuẩn
   hoá chính tả.

3. Ký tự trông giống nhau
   Dấu gạch nối U+2010/U+2013 và dấu trừ ASCII; nháy cong U+2018/U+2019 và
   nháy thẳng. OCR hay đổi qua lại; với người đọc thì không khác gì.

`accent_share` thì NGƯỢC LẠI — nó phải đo trên NFD, vì nó đếm đúng cái dấu
tổ hợp. Mốc hiệu chuẩn: tiếng Việt thật ≈ 0,217 (đo trên ground truth của
MDPBench). Engine cho ra 0,08 nghĩa là đã nuốt hơn nửa số dấu.

VÌ SAO `identifier_preservation` LÀ CỔNG CHẶN CHỨ KHÔNG PHẢI CHỈ TIÊU PHỤ
────────────────────────────────────────────────────────────────────────
Văn bản đi tiếp vào đường lược danh tính (PII). Ở đó, số hiệu văn bản, email,
ngày tháng, mã hồ sơ là thứ phải khớp NGUYÊN VĂN. Một engine đọc trôi chảy
nhưng đổi `56/2026/NĐ-CP` thành `56/2026/NĐ-CP.` hay `s6/2026` thì phần lược
danh tính phía sau hỏng im lặng — không ném lỗi, chỉ bỏ sót.

Một model sửa lỗi chính tả (mBART) từng đạt 86% ở chỉ số này và bị LOẠI, dù nó
làm tăng tỉ lệ dấu. Ngưỡng 99% giữ nguyên cho mọi model mới.
"""

from __future__ import annotations

import re
import unicodedata as ud
from dataclasses import dataclass

__all__ = [
    "nfc", "canonical_vi", "normalize_for_compare",
    "levenshtein", "cer", "wer", "accent_share", "stroke_letter_share",
    "identifiers", "identifier_preservation",
    "one_minus_edit_distance", "PageScore", "score",
]


# ── chuẩn hoá ───────────────────────────────────────────────────────────────

#: Dấu THANH (huyền, sắc, ngã, hỏi, nặng). Chúng cưỡi lên nguyên âm và có thể
#: đặt ở vị trí khác nhau tuỳ quy ước gõ — đây là thứ ta phải di dời.
_TONE_MARKS = {"\u0300", "\u0301", "\u0303", "\u0309", "\u0323"}

#: Dấu TẠO CHỮ CÁI (mũ â/ê/ô, trăng ă, móc ơ/ư). Chúng là bộ phận của chữ cái,
#: KHÔNG được di dời — "â" mà mất mũ thì thành chữ khác hẳn.
_LETTER_MARKS = {"\u0302", "\u0306", "\u031b"}

#: Nguyên âm cơ sở của tiếng Việt (đã bỏ dấu tạo chữ cái).
_VOWELS = set("aeiouy")

#: Ký tự trông giống nhau, quy về một mối khi so sánh.
_LOOKALIKES = {
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
    "\u2014": "-", "\u2015": "-", "\u2212": "-",
    "\u2018": "'", "\u2019": "'", "\u201b": "'", "\u02bc": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"',
    "\u00a0": " ", "\u2007": " ", "\u202f": " ", "\u2009": " ",
    "\u2026": "...",
}


def nfc(text: str) -> str:
    """Quy về NFC — dạng dựng sẵn, một chữ cái là một ký tự."""
    return ud.normalize("NFC", text)


def canonical_vi(text: str) -> str:
    """Đưa dấu thanh về cuối cụm nguyên âm, để "hòa" và "hoà" bằng nhau.

    Chỉ dùng ĐỂ SO SÁNH. Kết quả có thể sai quy ước chính tả — không được ghi
    ra ngoài như văn bản cho người đọc.

    Cách làm: tách NFD, đi qua từng cụm nguyên âm liền nhau; dấu thanh gặp
    trong cụm được giữ lại rồi gắn vào nguyên âm CUỐI của cụm đó. Dấu tạo chữ
    cái (mũ, trăng, móc) ở nguyên chỗ cũ.

    Không cần biết quy ước nào đúng: chỉ cần mọi quy ước hội tụ về một dạng.
    """
    d = ud.normalize("NFD", text)
    out: list[str] = []
    i = 0
    n = len(d)

    while i < n:
        ch = d[i]
        if ch.lower() not in _VOWELS:
            out.append(ch)
            i += 1
            continue

        # Gom trọn cụm nguyên âm: chữ cái nguyên âm + các dấu dính theo nó.
        cluster: list[list[str]] = []   # mỗi phần tử: [chữ cái, dấu tạo chữ…]
        tones: list[str] = []
        while i < n:
            c = d[i]
            if c.lower() in _VOWELS:
                cluster.append([c])
                i += 1
                while i < n and d[i] in _LETTER_MARKS | _TONE_MARKS:
                    if d[i] in _TONE_MARKS:
                        tones.append(d[i])
                    else:
                        cluster[-1].append(d[i])
                    i += 1
            else:
                break

        if tones:
            # Gắn toàn bộ dấu thanh vào nguyên âm cuối cụm.
            cluster[-1].extend(tones)
        for part in cluster:
            out.append("".join(part))

    return ud.normalize("NFC", "".join(out))


def normalize_for_compare(text: str) -> str:
    """Chuẩn hoá đầy đủ trước khi so hai chuỗi.

    Gộp khoảng trắng: OCR ngắt dòng ở đâu là chuyện trình bày, không phải
    chuyện đọc đúng hay sai. Nếu đếm cả khoảng trắng thì một engine xuống dòng
    khác ground truth sẽ bị phạt như đọc sai chữ.
    """
    text = nfc(text)
    for bad, good in _LOOKALIKES.items():
        text = text.replace(bad, good)
    text = canonical_vi(text)
    return " ".join(text.split())


# ── khoảng cách sửa ─────────────────────────────────────────────────────────

try:                                   # đường nhanh: C++, dùng khi có
    from rapidfuzz.distance import Levenshtein as _rf_lev

    def _distance(a: str, b: str) -> int:
        return _rf_lev.distance(a, b)

    _BACKEND = "rapidfuzz"
except ImportError:                     # đường lui: thuần Python, vẫn đúng
    def _distance(a: str, b: str) -> int:
        return _levenshtein_py(a, b)

    _BACKEND = "python"


def _levenshtein_py(a, b) -> int:
    """Bản tham chiếu thuần Python — chậm nhưng đọc hiểu và kiểm chứng được.

    Giữ lại kể cả khi đã có rapidfuzz: test so hai bản với nhau, nên nếu
    rapidfuzz đổi hành vi giữa các phiên bản thì test đỏ ngay.
    """
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1,          # xoá
                           cur[j - 1] + 1,        # thêm
                           prev[j - 1] + (ca != cb)))  # thay
        prev = cur
    return prev[-1]


def levenshtein(a, b) -> int:
    """Số phép sửa tối thiểu. Nhận chuỗi (theo ký tự) hoặc list (theo từ)."""
    if isinstance(a, str) and isinstance(b, str):
        return _distance(a, b)
    return _levenshtein_py(list(a), list(b))


# ── chỉ số ──────────────────────────────────────────────────────────────────

def cer(ref: str, hyp: str, *, normalize: bool = True) -> float:
    """Tỉ lệ sai ở mức KÝ TỰ = khoảng cách sửa / độ dài tham chiếu.

    Có thể vượt 1,0 khi engine sinh thừa rất nhiều — đó là thông tin thật
    (model ảo giác), không cắt về 1,0 để khỏi che mất.
    """
    if normalize:
        ref, hyp = normalize_for_compare(ref), normalize_for_compare(hyp)
    if not ref:
        return 0.0 if not hyp else 1.0
    return levenshtein(ref, hyp) / len(ref)


def wer(ref: str, hyp: str, *, normalize: bool = True) -> float:
    """Tỉ lệ sai ở mức TỪ.

    Với tiếng Việt, "từ" ở đây là tiếng (âm tiết) vì ta tách theo khoảng
    trắng. Vẫn dùng được để so tương đối giữa các engine trên cùng văn bản.
    """
    if normalize:
        ref, hyp = normalize_for_compare(ref), normalize_for_compare(hyp)
    rw, hw = ref.split(), hyp.split()
    if not rw:
        return 0.0 if not hw else 1.0
    return levenshtein(rw, hw) / len(rw)


def one_minus_edit_distance(ref: str, hyp: str) -> float:
    """`1 - Edit_dist` — đúng chỉ số SenOCR-Vi công bố (họ báo 86,7%).

    Cắt về khoảng [0, 1] để so trực tiếp với bảng của họ.
    """
    return max(0.0, min(1.0, 1.0 - cer(ref, hyp)))


def accent_share(text: str) -> float:
    """Tỉ lệ chữ cái mang dấu tổ hợp.

    Phải DỰNG VỀ NFC TRƯỚC rồi mới tách từng chữ cái ra NFD. Bỏ bước dựng thì
    đầu vào sẵn ở dạng NFD sẽ ra 0,0: khi dấu đã tách rời, nó là ký tự loại Mn
    — `isalpha()` trả False nên dấu bị loại khỏi phép đếm, còn chữ cái cơ sở
    thì trần trụi không mang dấu nào. Kết quả: một engine đọc đúng hoàn toàn
    nhưng xuất ra NFD sẽ bị chấm "mất sạch dấu". Test canh đúng chỗ này.

    ĐIỂM MÙ ĐÃ BIẾT: `đ`/`Đ` (U+0111/U+0110) KHÔNG phân rã ra dấu tổ hợp —
    Unicode coi nét gạch ngang là bộ phận của chữ cái, không phải dấu. Nên
    engine đọc "đường" thành "dường" KHÔNG làm tụt chỉ số này chút nào. Đây là
    lỗi tesseract hay mắc, và nó phải được bắt bằng CER, không bắt bằng đây.

    Không sửa bằng cách đếm thêm `đ`: mốc hiệu chuẩn 0,217 đo theo đúng định
    nghĩa "dấu tổ hợp". Đổi định nghĩa thì con số đó không còn so được nữa.
    Xem `stroke_letter_share` nếu cần theo dõi riêng trục `đ`.

    Mốc: tiếng Việt thật ≈ 0,217. Tesseract trên kho thật chỉ đạt 0,080
    (ảnh) / 0,102 (PDF) — mất hơn nửa số dấu.
    """
    text = ud.normalize("NFC", text)
    alpha = [c for c in text if c.isalpha()]
    if not alpha:
        return 0.0
    marked = sum(1 for c in alpha
                 if any(ud.combining(m) for m in ud.normalize("NFD", c)))
    return marked / len(alpha)


def stroke_letter_share(text: str) -> float:
    """Tỉ lệ chữ cái là `đ`/`Đ` — trục mà `accent_share` không nhìn thấy.

    Tách riêng chứ không gộp vào `accent_share`, để mốc hiệu chuẩn 0,217 giữ
    nguyên định nghĩa và vẫn so được với bảng của bên khác.

    Dùng khi nghi engine đọc `đ` thành `d`: bản gốc có tỉ lệ này ~0,03–0,05
    còn bản OCR về 0 thì gần như chắc chắn là nuốt nét gạch ngang.
    """
    text = ud.normalize("NFC", text)
    alpha = [c for c in text if c.isalpha()]
    if not alpha:
        return 0.0
    return sum(1 for c in alpha if c in "đĐ") / len(alpha)


# ── định danh ───────────────────────────────────────────────────────────────

#: Thứ tự QUAN TRỌNG: mẫu dài khớp trước, nếu không `56/2026/NĐ-CP` bị mẫu số
#: đơn giản xé thành "56", "2026" và ta sẽ báo "còn nguyên" cho một chuỗi đã vỡ.
_IDENTIFIER_PATTERNS: list[tuple[str, str]] = [
    # email — trước mọi mẫu khác, vì nó chứa cả chữ lẫn số lẫn dấu chấm
    ("email", r"[\w.+-]+@[\w-]+\.[\w.-]+"),

    # số hiệu văn bản pháp quy VN: 56/2026/NĐ-CP · 1656/QĐ-TTg · 03/2025/TT-BTC
    ("legal_ref", r"\b\d+(?:/\d+)*/[\w\u00c0-\u1ef9]+(?:-[\w\u00c0-\u1ef9]+)*"),

    # ngày: 12/03/2026 · 12-03-2026 · 2026-03-12
    ("date", r"\b\d{1,4}[/-]\d{1,2}[/-]\d{2,4}\b"),

    # mã có chữ dính số: NQ9001 · BQ96 · v3_5 · ISO9001
    ("code", r"\b(?=[A-Za-z]*\d)(?=\d*[A-Za-z])[A-Za-z0-9]{2,}\b"),

    # số tiền / số lượng có phân nhóm: 1.234.567 · 1,234.56
    ("number", r"\b\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?\b"),

    # số trần
    ("number", r"\b\d+\b"),
]

_IDENTIFIER_RE = re.compile(
    "|".join(f"(?P<{name}_{i}>{pat})"
             for i, (name, pat) in enumerate(_IDENTIFIER_PATTERNS)))


#: Mã ĐÁNH MÁY của LaTeX — không phải nội dung tài liệu, phải bỏ trước khi
#: rút định danh.
#:
#: Ca thật: ground truth MDPBench giữ nguyên công thức dạng LaTeX, nên
#: `\\[8pt]` (lệnh giãn dòng) bị tính là định danh `8pt` cần bảo toàn. Model
#: đọc ra công thức đúng nhưng dùng cách xuống dòng khác ⇒ bị trừ điểm oan.
#: 44/160 trang có ký hiệu LaTeX, nên đây không phải ca hiếm.
#:
#: Chỉ bỏ phần ĐIỀU KHIỂN TRÌNH BÀY. Số liệu thật trong công thức (`k2\pi`,
#: chỉ số dưới, hệ số) vẫn phải giữ — chúng là nội dung.
_LATEX_TYPESETTING_RE = re.compile(
    r"\\?\[[\d.]+(?:pt|ex|em|cm|mm|in|bp|dd|pc)\]"   # \\[8pt] giãn dòng
    r"|\\(?:hspace|vspace|quad|qquad|,|;|!)\s*"        # lệnh khoảng cách
    r"|\\begin\{[a-zA-Z*]+\}|\\end\{[a-zA-Z*]+\}"    # môi trường
)


def identifiers(text: str) -> list[str]:
    """Rút mọi định danh cần sống sót nguyên văn.

    Trả LIST chứ không phải SET: `56` xuất hiện ba lần mà engine chỉ giữ lại
    một thì đó là mất hai, và kiểu set sẽ giấu mất điều đó.

    Không chuẩn hoá dấu ở đây — định danh phải khớp đúng từng ký tự.

    Bỏ mã đánh máy LaTeX trước khi rút: xem `_LATEX_TYPESETTING_RE`. Cổng
    kiểm định danh phải phạt engine làm mất SỐ LIỆU, không phạt nó vì chọn
    cách trình bày công thức khác với ground truth.
    """
    text = nfc(text)
    for bad, good in _LOOKALIKES.items():
        text = text.replace(bad, good)
    text = _LATEX_TYPESETTING_RE.sub(" ", text)
    return [m.group(0) for m in _IDENTIFIER_RE.finditer(text)]


def identifier_preservation(ref: str, hyp: str) -> float:
    """Tỉ lệ định danh của bản gốc còn nguyên vẹn trong bản OCR.

    CỔNG CHẶN: dưới 0,99 là loại engine, bất kể CER đẹp đến đâu.

    Đối chiếu theo BỘI SỐ (multiset): mỗi lần xuất hiện ở bản gốc phải có một
    lần tương ứng ở bản OCR. Nhờ vậy, mất bớt một lần lặp vẫn bị tính là mất.

    Bản gốc không có định danh nào ⇒ trả 1,0. Không có gì để mất thì không thể
    coi là thất bại — nhưng khi tổng hợp nhiều trang phải cộng dồn theo SỐ
    ĐỊNH DANH, đừng lấy trung bình các trang (xem `score`).
    """
    from collections import Counter

    ref_ids = Counter(identifiers(ref))
    if not ref_ids:
        return 1.0
    hyp_ids = Counter(identifiers(hyp))
    kept = sum(min(c, hyp_ids[tok]) for tok, c in ref_ids.items())
    return kept / sum(ref_ids.values())


# ── tổng hợp ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PageScore:
    """Điểm của một trang, kèm số đếm thô để cộng dồn được về sau."""

    cer: float
    wer: float
    accent_ref: float
    accent_hyp: float
    identifier_preservation: float
    identifiers_total: int
    identifiers_kept: int
    ref_chars: int

    @property
    def one_minus_edit_distance(self) -> float:
        return max(0.0, min(1.0, 1.0 - self.cer))

    @property
    def passes_identifier_gate(self) -> bool:
        return self.identifier_preservation >= 0.99


def score(ref: str, hyp: str) -> PageScore:
    """Chấm một trang.

    Giữ lại cả số đếm thô (`identifiers_total`, `ref_chars`) vì tổng hợp nhiều
    trang phải cộng dồn theo trọng số, không phải lấy trung bình cộng các tỉ
    lệ: một trang 5 ký tự sai hết sẽ kéo trung bình xuống ngang một trang
    2 000 ký tự sai hết, dù nó không đáng kể.
    """
    from collections import Counter

    ref_ids = Counter(identifiers(ref))
    hyp_ids = Counter(identifiers(hyp))
    total = sum(ref_ids.values())
    kept = sum(min(c, hyp_ids[t]) for t, c in ref_ids.items())

    return PageScore(
        cer=cer(ref, hyp),
        wer=wer(ref, hyp),
        accent_ref=accent_share(ref),
        accent_hyp=accent_share(hyp),
        identifier_preservation=(kept / total) if total else 1.0,
        identifiers_total=total,
        identifiers_kept=kept,
        ref_chars=len(normalize_for_compare(ref)),
    )
