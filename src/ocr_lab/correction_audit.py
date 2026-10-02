"""Phân loại từng thay đổi của corrector — thay cho một con số tổng mù.

VÌ SAO `accent_share` LÀ THƯỚC ĐO SAI CHO VIỆC NÀY
─────────────────────────────────────────────────
`accent_share` đếm CÓ BAO NHIÊU dấu, không đếm dấu ĐÚNG hay SAI:

    'Căn cước điện tứ'  accent_share = 0,3846
    'Căn cước điện tử'  accent_share = 0,3846   ← chênh lệch ĐÚNG BẰNG 0

`ứ` và `ử` đều là một dấu. Nên thước đo này chỉ bắt được ca "OCR rụng sạch
dấu" (tesseract), và MÙ HOÀN TOÀN với ca "OCR đọc nhầm thanh điệu" — mà đó
chính xác là loại lỗi ADE còn sót lại, và là loại lỗi corrector sửa được.

Dùng nó để kết luận "corrector không giúp gì" là đo nhầm thước: nó nói
0,241 → 0,240 trong khi model đang sửa `điện tứ` → `điện tử` một cách hoàn
toàn đúng.

BA LOẠI THAY ĐỔI, GIÁ TRỊ KHÁC HẲN NHAU
───────────────────────────────────────
    TONE_FIX     khung xương chữ giữ nguyên, chỉ đổi thanh điệu
                 'điện tứ' → 'điện tử'            ← ĐÚNG VIỆC, giữ
    WHITESPACE   chỉ đổi xuống dòng / khoảng trắng
                 'BỘ CÔNG AN\\nCỤC' → 'BỘ CÔNG AN CỤC'  ← PHÁ cấu trúc trường
    CHAR_EDIT    thêm/bớt/đổi ký tự thật
                 '4G ▪' → '4G '                   ← phải xem từng ca

Gộp ba loại vào một con số trung bình là cách chắc chắn nhất để kết luận sai.
"""

from __future__ import annotations

import unicodedata as ud
from dataclasses import dataclass
from enum import Enum

__all__ = ["ChangeKind", "Change", "classify_change", "diff_words",
           "filter_to_tone_fixes", "strip_all_marks",
           "strip_tone"]

#: Dấu THANH: huyền, sắc, ngã, hỏi, nặng. Đây là thứ corrector sửa.
#: KHÔNG gồm dấu tạo chữ cái (mũ â/ê/ô, trăng ă, móc ơ/ư) — mất mũ là thành
#: chữ khác hẳn, không phải sai thanh điệu.
_TONE_MARKS = "\u0300\u0301\u0303\u0309\u0323"

#: Dấu TẠO CHỮ CÁI trong tiếng Việt: mũ (â ê ô), trăng (ă), móc (ơ ư).
_LETTER_MARKS = "\u0302\u0306\u031b"

#: Mọi dấu phụ KHÁC hai nhóm trên đều là RÁC OCR, vì tiếng Việt không dùng
#: dấu nào ngoài 8 dấu trên. Thực tế đo được trên CCCD:
#:
#:     'Sęo'  ogonek U+0328      ← đọc nhầm của 'Sẹo'  (nặng U+0323)
#:     'thė'  chấm-trên U+0307   ← đọc nhầm của 'thẻ'  (hỏi  U+0309)
#:
#: Không gộp chúng thì `thė → thẻ` — một lần sửa thanh điệu HOÀN TOÀN ĐÚNG —
#: bị xếp nhầm thành "đổi chữ", và ta đếm thiếu đúng cái mình cần đếm.


def _is_ocr_artifact(c: str) -> bool:
    """Dấu phụ này có phải rác OCR không (tiếng Việt không hề dùng)."""
    return (ud.combining(c) != 0
            and c not in _TONE_MARKS
            and c not in _LETTER_MARKS)


def strip_tone(s: str) -> str:
    """Bỏ dấu THANH và rác OCR, giữ nguyên dấu tạo chữ cái.

    `tứ` và `tử` cùng khung xương `tư`; `tư` và `tu` thì KHÔNG — mũ/móc là bộ
    phận của chữ cái. Phân biệt được hai mức đó mới tách được "sửa thanh điệu"
    khỏi "đổi chữ".

    Rác OCR bị bỏ cùng với dấu thanh, vì nó CHÍNH LÀ dấu thanh bị đọc sai:
    `Sęo` và `Sẹo` phải cùng khung xương `Seo` thì mới nhận ra đó là việc sửa
    dấu, chứ không phải viết lại chữ.
    """
    return "".join(c for c in ud.normalize("NFD", s)
                   if c not in _TONE_MARKS and not _is_ocr_artifact(c))


class ChangeKind(str, Enum):
    TONE_FIX = "sửa thanh điệu"
    WHITESPACE = "đổi khoảng trắng"
    CHAR_EDIT = "đổi ký tự"
    NONE = "không đổi"


@dataclass(frozen=True)
class Change:
    before: str
    after: str
    kind: ChangeKind
    #: Thống kê theo TỪNG TỪ. Một thay đổi thật hiếm khi thuần một loại: model
    #: có thể vừa sửa dấu vừa xoá ký tự nhiễu trong cùng một đoạn. Đếm riêng
    #: từng loại giữ lại thông tin mà một nhãn duy nhất làm mất.
    n_tone: int = 0
    n_char: int = 0
    n_space: int = 0

    @property
    def is_improvement(self) -> bool:
        """Có sửa được thanh điệu nào không.

        Đây là câu hỏi đúng, thay cho "thay đổi này thuộc loại gì". Một đoạn
        vừa sửa `tứ`→`tử` vừa xoá ký tự nhiễu VẪN là cải thiện về thanh điệu —
        gán cho nó một nhãn CHAR_EDIT rồi kết luận "không cải thiện" chính là
        cách bỏ sót ca mà người dùng chỉ ra.
        """
        return self.n_tone > 0

    @property
    def damages_structure(self) -> bool:
        """Có nuốt xuống dòng không — trên biểu mẫu đó là mất ranh giới trường."""
        return self.n_space > 0


def classify_change(before: str, after: str) -> Change:
    """Phân loại một thay đổi, ĐẾM THEO TỪNG TỪ.

    Không gán một nhãn duy nhất cho cả đoạn: thay đổi thật thường hỗn hợp, và
    nhãn duy nhất sẽ giấu mất phần quan trọng. `kind` chỉ là nhãn trội, dùng để
    hiển thị gọn; quyết định đọc từ `n_tone` / `n_char` / `n_space`.
    """
    if before == after:
        return Change(before, after, ChangeKind.NONE)

    squash = lambda s: " ".join(s.split())

    # Nuốt xuống dòng: bản gốc có `\n`, bản sửa không còn. Trên biểu mẫu, xuống
    # dòng phân tách các TRƯỜNG, nên đây là thiệt hại chứ không phải dọn dẹp.
    n_space = 1 if ("\n" in before and "\n" not in after) else 0

    n_tone = n_char = 0
    for wb, wa in diff_words(squash(before), squash(after)):
        if not wb or not wa:
            n_char += 1                     # thêm/xoá hẳn một từ
        elif strip_tone(wb) == strip_tone(wa):
            n_tone += 1                     # cùng khung xương ⇒ chỉ đổi thanh
        else:
            n_char += 1

    kind = (ChangeKind.TONE_FIX if n_tone and not n_char
            else ChangeKind.CHAR_EDIT if n_char
            else ChangeKind.WHITESPACE if n_space
            else ChangeKind.NONE)

    return Change(before, after, kind, n_tone=n_tone, n_char=n_char,
                  n_space=n_space)


def diff_words(before: str, after: str) -> list[tuple[str, str]]:
    """Các cặp từ khác nhau giữa hai chuỗi, để soi đúng chỗ model đụng vào.

    In cả đoạn dài thì mắt người không thấy chỗ đổi. Trả về từng cặp từ để
    báo cáo chỉ thẳng vào `tứ → tử` thay vì bắt đọc lại cả câu.
    """
    import difflib

    a, b = before.split(), after.split()
    # `autojunk=False`: heuristic mặc định coi phần tử xuất hiện nhiều là
    # "rác", trên văn xuôi nghĩa là các từ thông dụng — làm lệch căn chỉnh.
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        out.append((" ".join(a[i1:i2]), " ".join(b[j1:j2])))
    return out


def strip_all_marks(s: str) -> str:
    """Bỏ MỌI dấu phụ, kể cả mũ/móc — khung xương chữ cái La-tinh trần.

    Dùng cho văn bản mất dấu HOÀN TOÀN (đầu ra tesseract: `Noi thuong tru`),
    nơi model phải thêm cả mũ lẫn thanh: `Noi` → `Nơi`, `Lien` → `Liên`.
    `strip_tone` cố ý coi việc thêm móc là "đổi chữ" để bảo vệ văn bản đã có
    dấu, nên nó chặn nhầm ở đây — hai bài toán khác nhau, hai thước khác nhau.
    """
    return "".join(c for c in ud.normalize("NFD", s) if not ud.combining(c))


def filter_to_tone_fixes(before: str, after: str,
                         *, restore_all: bool = False) -> str:
    """Giữ LẠI bản sửa của model chỉ ở những từ nó sửa thanh điệu.

    VÌ SAO CẦN LỚP NÀY
    ──────────────────
    Đo trên CCCD thật: model sửa đúng `tứ`→`tử`, `Nới`→`Nơi`, `nhân`→`nhận`,
    `thė`→`thẻ` — nhưng cùng lúc:

        'zen'  → 'trên'     PHÁ ĐỊA CHỈ ('tòa zen dự án Feliz Homes' —
                            Zen là tên toà nhà, không phải chữ đọc nhầm)
        'Sęo'  → 'Sao'      SAI, đúng phải là 'Sẹo'
        'Sex:' → 'SexV:'    bịa thêm ký tự

    Cùng một model vừa có ích vừa gây hại, nên không thể quyết định ở mức
    "bật hay tắt". Phải quyết ở mức TỪNG TỪ.

    QUY TẮC: nhận bản sửa khi khung xương chữ không đổi (chỉ thanh điệu
    khác); mọi trường hợp khác giữ nguyên bản gốc. Model không được phép
    viết lại chữ — nó chỉ được phép đặt lại dấu.

    Chú ý ca `Sęo`: bị chặn nên vẫn còn sai, nhưng sai theo kiểu NHÌN LÀ
    THẤY (ogonek không tồn tại trong tiếng Việt). Còn `Sao` thì sai mà trông
    hợp lý — người soát sẽ đọc lướt qua. Sai lộ liễu an toàn hơn sai êm.

    Xuống dòng của bản gốc luôn được giữ: trên biểu mẫu, `\\n` phân tách các
    TRƯỜNG, nuốt nó là mất ranh giới trường.
    """
    import difflib

    # `restore_all=True` cho văn bản mất dấu hoàn toàn: chấp nhận cả việc
    # thêm mũ/móc. Mặc định False vì trên văn bản ĐÃ có dấu (như bản chép
    # ADE), thêm móc thường là model viết lại chữ chứ không phải phục hồi.
    skeleton = strip_all_marks if restore_all else strip_tone

    a, b = before.split(), after.split()
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)

    out: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            out.extend(a[i1:i2])
        elif (tag == "replace" and (i2 - i1) == (j2 - j1)):
            # Xét TỪNG cặp từ một: một đoạn replace có thể chứa cả từ sửa
            # dấu đúng lẫn từ bị viết lại bậy.
            for wb, wa in zip(a[i1:i2], b[j1:j2]):
                out.append(wa if skeleton(wb) == skeleton(wa) else wb)
        else:
            # Thêm/xoá từ, hoặc replace lệch số từ ⇒ không phải sửa dấu.
            out.extend(a[i1:i2])

    fixed = " ".join(out)

    # Khôi phục xuống dòng: ghép lại theo đúng bố cục dòng của bản gốc.
    # `filter` ở trên làm việc trên chuỗi đã tách từ nên mất hết `\n`.
    if "\n" in before:
        it = iter(fixed.split())
        return "\n".join(
            " ".join(next(it, w) for w in line.split()) if line.strip() else line
            for line in before.split("\n")
        )
    return fixed
