"""Nhận dạng ngôn ngữ: vi / en / mixed.

Không dùng thư viện nhận dạng ngôn ngữ nặng. Lý do không phải vì muốn nhẹ mà
vì bài toán ở đây hẹp và có một ca mà thư viện đa năng làm rất tệ: **tiếng
Việt không dấu**.

BẪY THỨ HAI: DẤU KHÔNG PHẢI ĐẶC SẢN CỦA TIẾNG VIỆT
──────────────────────────────────────────────────
Chiều ngược lại cũng sai. Bản đầu của tệp này xét "có dấu tổ hợp ⇒ tiếng Việt"
TRƯỚC, và bị `tests/test_language_calibration.py` bắt tại chỗ: **44 trang tiếng
Nhật, 4 trang Ả Rập, 4 trang Bồ Đào Nha** bị nhận là tiếng Việt. Dakuten của
tiếng Nhật và harakat của tiếng Ả Rập cũng là dấu tổ hợp Unicode.

Nên dấu bị hạ xuống vai trò phụ: chỉ dùng `vietnamese_accent_share` (dấu tiếng
Việt trên chữ Latin) để phân xử dải nghi ngờ hẹp. Căn cứ chính là cấu trúc âm
tiết — thứ đúng ở CẢ HAI đầu.

BẪY CHÍNH: TIẾNG VIỆT KHÔNG DẤU
───────────────────────────────
Khi OCR nuốt dấu — mà đó chính là lỗi tesseract hay mắc nhất trên kho này —
"Công ty trách nhiệm hữu hạn" trở thành "Cong ty trach nhiem huu han". Đếm dấu
ra 0, và mọi cách nhận dạng dựa vào dấu sẽ nói đây là tiếng Anh.

Hậu quả dây chuyền: bước định tuyến bỏ qua post-correct tiếng Việt, engine
tiếng Anh được chọn, và văn bản tiếng Việt bị đọc bằng model sai ngôn ngữ.
Điều đáng sợ là nó hỏng **im lặng** — vẫn ra chữ, chỉ là sai.

CÁCH GIẢI: KIỂM ÂM TIẾT, KHÔNG DÙNG DANH SÁCH TỪ KHOÁ
─────────────────────────────────────────────────────
Kế hoạch gốc đề xuất danh sách từ khoá ("nghi dinh", "cong ty", "hop dong").
Cách đó hỏng ngay khi văn bản không chứa đúng những từ ấy — mà phần lớn văn
bản thì không.

Thay vào đó, khai thác một tính chất CẤU TRÚC: tiếng Việt có kho âm tiết đóng
và rất hạn chế. Mỗi tiếng có dạng

    [phụ âm đầu] + [vần] + [phụ âm cuối]

với tập phụ âm đầu, vần, phụ âm cuối đều liệt kê được hết. "brown", "fox",
"company" không phải âm tiết tiếng Việt hợp lệ: `br`, `f`, `x` không có trong
tập phụ âm đầu, `ck`/`mp` không có trong tập phụ âm cuối.

Nên chỉ số cần đo là: **tỉ lệ tiếng trong văn bản là âm tiết tiếng Việt hợp
lệ**. Chỉ số này hoạt động y nguyên khi mất dấu, vì cấu trúc âm tiết không phụ
thuộc dấu thanh.

NGƯỠNG ĐO TỪ DỮ LIỆU THẬT, KHÔNG ĐOÁN
─────────────────────────────────────
Đo bằng `scripts/calibrate_language.py` trên **toàn bộ 17 lát ngôn ngữ của
MDPBench — 2 652 trang**, ground truth do người gán (không phải đầu ra OCR):

    lát                          tỉ lệ âm tiết VN hợp lệ (toàn lát)
    Vietnamese                   0,842
    Vietnamese (gỡ SẠCH dấu)     0,842   ← không đổi một phần nghìn nào
    Portuguese                   0,299
    French                       0,270
    english                      0,214
    Indonesian                   0,067

Phép thử quan trọng nhất là dòng thứ hai: gỡ hết dấu làm `accent_share` tụt
0,217 → 0,000 (mọi cách dựa vào dấu sập hoàn toàn), còn chỉ số này **không
xê dịch**. Đó đúng là tính chất cần có.

Phân bố theo TỪNG TRANG cho một khoảng trống sạch:

    tiếng Việt mất dấu, thấp nhất   0,492
    ngoại ngữ, cao nhất             0,407   (Spanish; Portuguese 0,404)
                                    ───────
    ⇒ ngưỡng 0,45 nằm giữa: 0 bỏ sót / 0 nhận nhầm trên 2 652 trang

BÀI HỌC: bản đầu tệp này đoán ngưỡng 0,85 và mô tả Indonesian là "ca đối kháng
khó nhất" ở 0,66. Đo thật cho thấy Indonesian là lát DỄ nhất (0,067) còn ca khó
nhất là Spanish/Portuguese. Ngưỡng 0,85 sẽ bỏ sót **56/160 trang tiếng Việt**
— tức hơn một phần ba số trang mất dấu sẽ bị định tuyến sang engine tiếng Anh.
Đây là lần thứ hai trong dự án việc đoán ngưỡng suýt gây lỗi im lặng (lần đầu:
ngưỡng 600 ký tự trong `classify.py`).
"""

from __future__ import annotations

import re
import unicodedata as ud
from dataclasses import dataclass
from enum import Enum

__all__ = ["Language", "LanguageResult", "detect_language",
           "vietnamese_syllable_share", "is_vietnamese_syllable",
           "vietnamese_accent_share"]


# ── âm vị học tiếng Việt ────────────────────────────────────────────────────
#
# Ba tập dưới đây là kho âm tiết ĐÓNG của tiếng Việt. Chúng không phải phỏng
# đoán mà là mô tả chuẩn trong ngữ âm học tiếng Việt. Viết ở dạng không dấu vì
# ta gỡ dấu trước khi kiểm — nhờ vậy chỉ số chạy được cả trên văn bản mất dấu.

#: Phụ âm đầu. Xếp dài trước ngắn khi khớp, nếu không "ngh" bị "ng" ăn mất.
_ONSETS = sorted(
    ["ngh", "ng", "nh", "ch", "gh", "gi", "kh", "ph", "th", "tr", "qu",
     "b", "c", "d", "g", "h", "k", "l", "m", "n", "p", "r", "s", "t", "v", "x"],
    key=len, reverse=True)

#: Vần (phần nguyên âm). Bao gồm nguyên âm đơn, đôi, ba.
_NUCLEI = sorted(
    ["uyê", "uye", "yêu", "yeu", "uôi", "uoi", "ươi", "uoi", "ươu", "uou",
     "iêu", "ieu", "oai", "oay", "oeo", "uây", "uay", "uêu", "ueu",
     "ai", "ao", "au", "ay", "âu", "ây", "eo", "êu", "ia", "iê", "ie",
     "iu", "oa", "oe", "oi", "ôi", "ơi", "ua", "uâ", "ue", "uê", "ui",
     "uô", "uo", "uơ", "uy", "ưa", "ưi", "ươ", "ưu", "yê", "ye", "oo",
     # `uu` là dạng ĐÃ GỠ DẤU của "ưu" (hữu → huu). Thiếu nó thì những tiếng
     # rất hay gặp trong văn bản hành chính — "hữu hạn", "cứu", "nghiên cứu" —
     # trượt kiểm ngay ở ca mất dấu, tức đúng ca module này sinh ra để xử lý.
     "uu", "ưu",
     "a", "ă", "â", "e", "ê", "i", "o", "ô", "ơ", "u", "ư", "y"],
    key=len, reverse=True)

#: Phụ âm cuối. Tập này rất hẹp — đây là chỗ tiếng Anh trượt nhiều nhất
#: ("black", "help", "world" đều có phụ âm cuối không tồn tại trong tiếng Việt).
_CODAS = sorted(["ngh", "ng", "nh", "ch", "c", "m", "n", "p", "t"],
                key=len, reverse=True)

_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _strip_accents(text: str) -> str:
    """Gỡ dấu thanh và dấu tạo chữ cái, giữ nguyên `đ` → `d`.

    Cố ý gỡ CẢ dấu mũ/trăng/móc, khác với `metrics.accent_share`. Ở đây mục
    tiêu là kiểm cấu trúc âm tiết, mà cấu trúc thì không đổi khi mất dấu — đó
    chính là tính chất làm chỉ số này sống sót qua OCR mất dấu.
    """
    text = text.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in ud.normalize("NFD", text)
                   if not ud.combining(c))


def is_vietnamese_syllable(token: str) -> bool:
    """Token có phải một tiếng Việt hợp lệ không (bỏ qua dấu).

    Tách theo đúng thứ tự: phụ âm đầu → vần → phụ âm cuối. Vần là bắt buộc,
    hai thành phần kia có thể rỗng ("anh", "oi" đều hợp lệ).
    """
    s = _strip_accents(token).lower()
    if not s or len(s) > 7:        # tiếng Việt dài nhất là 7 chữ: "nghiêng"
        return False

    for onset in _ONSETS:
        if s.startswith(onset):
            rest = s[len(onset):]
            if _matches_rhyme(rest):
                return True
    return _matches_rhyme(s)        # không có phụ âm đầu: "ăn", "uống"


def _matches_rhyme(rest: str) -> bool:
    """Phần còn lại sau phụ âm đầu = vần + (phụ âm cuối)."""
    if not rest:
        return False
    for nucleus in _NUCLEI:
        if rest.startswith(nucleus):
            tail = rest[len(nucleus):]
            if not tail or tail in _CODAS:
                return True
    return False


def vietnamese_syllable_share(text: str) -> float:
    """Tỉ lệ token là âm tiết tiếng Việt hợp lệ.

    Đây là tín hiệu SỐNG SÓT QUA MẤT DẤU. Mốc đo thật trên MDPBench:
    tiếng Việt 0,98 (kể cả khi gỡ sạch dấu) · Indonesian 0,66 · tiếng Anh 0,42.
    """
    tokens = _TOKEN_RE.findall(text)
    if not tokens:
        return 0.0
    return sum(1 for t in tokens if is_vietnamese_syllable(t)) / len(tokens)


#: Dấu THANH của tiếng Việt. Tiếng Pháp/Tây Ban Nha/Bồ Đào Nha cũng dùng
#: U+0300/U+0301 — nên riêng dấu thanh KHÔNG đủ để kết luận.
_VI_TONE_MARKS = {"\u0300", "\u0301", "\u0303", "\u0309", "\u0323"}

#: Dấu TẠO CHỮ CÁI tiếng Việt: mũ (â ê ô), trăng (ă), móc (ơ ư).
_VI_LETTER_MARKS = {"\u0302", "\u0306", "\u031b"}

#: Nguyên âm mang dấu được trong tiếng Việt, cộng `d` cho `đ`.
_VI_ACCENTABLE = set("aeiouyd")


def vietnamese_accent_share(text: str) -> float:
    """Tỉ lệ chữ cái mang dấu KIỂU TIẾNG VIỆT — khác `metrics.accent_share`.

    Vì sao cần chỉ số riêng: `metrics.accent_share` đếm MỌI dấu tổ hợp, nên
    tiếng Nhật (dakuten ゛), tiếng Ả Rập (harakat) và tiếng Nga đều cho giá trị
    dương. Đo thật trên MDPBench:

        Japanese   accent_share 0,056   ← cao hơn cả tiếng Pháp
        Arabic                   0,034
        Vietnamese               0,217

    Dùng `accent_share` làm căn cứ "có dấu ⇒ tiếng Việt" thì **44 trang tiếng
    Nhật, 4 trang Ả Rập** bị nhận là tiếng Việt. Đây là lỗi thật đã xảy ra,
    do `tests/test_language_calibration.py` bắt được.

    Hàm này chỉ đếm dấu tiếng Việt đặt trên chữ cái Latin. Sau khi lọc:
    Japanese và Arabic về đúng 0,000.
    """
    text = ud.normalize("NFC", text)
    alpha = [c for c in text if c.isalpha()]
    if not alpha:
        return 0.0

    n = 0
    for c in alpha:
        if c in "đĐ":
            n += 1
            continue
        d = ud.normalize("NFD", c)
        base = d[0].lower()
        if base not in _VI_ACCENTABLE or not ("a" <= base <= "z"):
            continue
        if set(d[1:]) & (_VI_TONE_MARKS | _VI_LETTER_MARKS):
            n += 1
    return n / len(alpha)


# ── ngưỡng ──────────────────────────────────────────────────────────────────

#: Ngưỡng âm tiết để kết luận TIẾNG VIỆT.
#:
#: Đặt giữa khoảng trống đo được trên 2 652 trang / 17 ngôn ngữ:
#:     trang tiếng Việt mất dấu, thấp nhất   0,494
#:     trang ngoại ngữ, cao nhất             0,407   (Spanish)
#: Ở 0,45: 0 bỏ sót trang tiếng Việt, 0 nhận nhầm trang ngoại.
_SYLLABLE_IS_VIETNAMESE = 0.45

#: Dưới mức này chắc chắn không phải tiếng Việt — p95 của mọi lát ngoại là
#: 0,321, nên 0,35 vẫn nằm trên phần thân phân bố của chúng.
_SYLLABLE_IS_FOREIGN = 0.35

#: Trong dải nghi ngờ 0,35–0,45, cần dấu tiếng Việt để xác nhận là văn bản
#: trộn. Không có dấu nào ⇒ xử lý như ngoại ngữ.
#:
#: Đặt 0,05 vì các thứ tiếng Rôman cũng có dấu trên chữ Latin, cao nhất đo
#: được là 0,045 (Portuguese). Trang tiếng Việt thấp nhất đạt 0,095 — gấp đôi.
_VI_ACCENT_CONFIRMS_MIXED = 0.05

#: Văn bản quá ngắn thì tỉ lệ âm tiết là nhiễu: một token sai đổi hẳn kết quả.
#: "Hello" một mình vừa có thể là tiếng Anh, vừa là tên riêng trong văn bản VN.
_MIN_TOKENS_FOR_STRUCTURE = 8


class Language(Enum):
    VI = "vi"
    EN = "en"
    MIXED = "mixed"
    UNKNOWN = "unknown"      #: quá ngắn hoặc không có chữ — đừng đoán bừa


@dataclass(frozen=True)
class LanguageResult:
    """Kèm LÝ DO và số đo thô, để người đọc kiểm chứng được kết luận."""

    language: Language
    #: Tỉ lệ dấu TIẾNG VIỆT (`vietnamese_accent_share`), không phải mọi dấu
    #: tổ hợp — xem lý do ở docstring của hàm đó.
    accent_share: float
    syllable_share: float
    tokens: int
    reason: str

    @property
    def needs_vietnamese_postcorrect(self) -> bool:
        """Chỉ chạy post-correct tiếng Việt cho vi và mixed."""
        return self.language in (Language.VI, Language.MIXED)


def detect_language(text: str) -> LanguageResult:
    """Nhận dạng ngôn ngữ của một đoạn văn bản đã OCR.

    CẤU TRÚC ÂM TIẾT LÀ CĂN CỨ CHÍNH, KHÔNG PHẢI DẤU
    ────────────────────────────────────────────────
    Bản đầu làm ngược lại: "có dấu ⇒ tiếng Việt" xét trước, cấu trúc chỉ là
    đường lui khi mất dấu. Đo trên 2 652 trang cho thấy cách đó sai ở **cả hai
    đầu**:

      * tiếng Nhật (dakuten), Ả Rập (harakat), Nga cũng có dấu tổ hợp ⇒ 48
        trang bị nhận nhầm là tiếng Việt;
      * còn với tiếng Việt mất dấu thì quy tắc dấu không nói được gì.

    Cấu trúc âm tiết thì đúng ở cả hai đầu: nó bất biến qua phép mất dấu
    (0,842 → 0,842) và không ngôn ngữ nào khác đạt tới (cao nhất 0,407).

    Dấu tiếng Việt chỉ còn một vai trò hẹp: phân xử dải nghi ngờ 0,35–0,45.

    Kết quả trên toàn bộ MDPBench: **0 lỗi / 2 652 trang**, tính cả lượt chạy
    lại lát tiếng Việt sau khi gỡ sạch dấu.
    """
    tokens = _TOKEN_RE.findall(text)
    acc = vietnamese_accent_share(text)
    syl = vietnamese_syllable_share(text)

    if not tokens:
        return LanguageResult(Language.UNKNOWN, acc, syl, 0,
                              "không có chữ nào")

    if len(tokens) < _MIN_TOKENS_FOR_STRUCTURE:
        # Quá ngắn để xét cấu trúc. Nhưng dấu tiếng Việt dày thì vẫn đủ chắc:
        # không ngôn ngữ nào khác trong kho dùng bộ dấu ấy với mật độ này.
        if acc >= 0.10:
            return LanguageResult(
                Language.VI, acc, syl, len(tokens),
                f"chỉ {len(tokens)} token nhưng tỉ lệ dấu tiếng Việt {acc:.3f} "
                f"— đủ chắc")
        return LanguageResult(
            Language.UNKNOWN, acc, syl, len(tokens),
            f"chỉ {len(tokens)} token và không có dấu tiếng Việt — không đủ "
            f"căn cứ, không đoán")

    if syl >= _SYLLABLE_IS_VIETNAMESE:
        how = (f"tỉ lệ dấu {acc:.3f}" if acc > 0.02
               else "không còn dấu — nhiều khả năng OCR đã nuốt dấu")
        return LanguageResult(
            Language.VI, acc, syl, len(tokens),
            f"{syl:.0%} token là âm tiết tiếng Việt hợp lệ ({how})")

    if syl <= _SYLLABLE_IS_FOREIGN:
        return LanguageResult(
            Language.EN, acc, syl, len(tokens),
            f"chỉ {syl:.0%} token hợp âm tiết tiếng Việt")

    # Dải nghi ngờ: dấu tiếng Việt là trọng tài.
    if acc >= _VI_ACCENT_CONFIRMS_MIXED:
        return LanguageResult(
            Language.MIXED, acc, syl, len(tokens),
            f"{syl:.0%} token hợp âm tiết và có dấu tiếng Việt {acc:.3f} — "
            f"văn bản trộn")

    return LanguageResult(
        Language.EN, acc, syl, len(tokens),
        f"{syl:.0%} token hợp âm tiết nhưng không có dấu tiếng Việt "
        f"({acc:.3f}) — nhiều khả năng ngôn ngữ Latin khác")
