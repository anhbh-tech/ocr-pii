"""Kiểm nhận dạng ngôn ngữ — trọng tâm là ca TIẾNG VIỆT MẤT DẤU.

Ca đó là lý do tồn tại của cả module. Nó không phải giả định: OCR trên kho
thật làm tỉ lệ dấu tụt từ 0,217 xuống 0,080, và 30–49% số tệp ra gần như
không còn dấu nào. Nếu bước nhận dạng gọi những tệp đó là tiếng Anh thì đường
định tuyến chọn sai engine và văn bản hỏng im lặng.

Ngưỡng ở đây hiệu chuẩn trên 2 652 trang / 17 ngôn ngữ của MDPBench — xem
`scripts/calibrate_language.py`.
"""

import unicodedata as ud

import pytest

from ocr_lab.language import (
    Language,
    detect_language,
    is_vietnamese_syllable,
    vietnamese_syllable_share,
)


def _strip(text: str) -> str:
    """Mô phỏng OCR nuốt sạch dấu — đúng lỗi tesseract trên kho thật."""
    text = text.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in ud.normalize("NFD", text) if not ud.combining(c))


# Đoạn văn hành chính thật, đúng loại văn bản trong kho.
VI_TEXT = (
    "Căn cứ Nghị định số 56/2026/NĐ-CP ngày 12 tháng 3 năm 2026 của Chính phủ "
    "quy định chi tiết một số điều của Luật Đầu tư về điều kiện đầu tư kinh "
    "doanh; theo đề nghị của Giám đốc Sở Kế hoạch và Đầu tư thành phố"
)

EN_TEXT = (
    "Pursuant to the provisions of the Investment Law and the implementing "
    "decrees, the Department of Planning and Investment hereby certifies that "
    "the enterprise has completed its business registration procedures"
)


# ── âm tiết ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("token", [
    "nguyen", "cong", "ty", "trach", "nhiem", "huu", "han", "nghi", "dinh",
    "thanh", "pho", "quyet", "khoan", "nghieng", "an", "uong", "oi",
])
def test_real_vietnamese_syllables_are_recognised(token):
    assert is_vietnamese_syllable(token), f"{token!r} phải là âm tiết hợp lệ"


@pytest.mark.parametrize("token", [
    "brown", "fox", "jumps", "black", "help", "world", "company",
    "investment", "registration", "strength",
])
def test_english_words_are_rejected_as_syllables(token):
    """`br`, `f`, `x` không có trong tập phụ âm đầu; `ck`, `mp`, `lp`, `ld`
    không có trong tập phụ âm cuối của tiếng Việt."""
    assert not is_vietnamese_syllable(token), f"{token!r} không phải âm tiết VN"


@pytest.mark.parametrize("token", ["the", "can", "ban", "com", "tin", "long"])
def test_some_english_words_ARE_valid_vietnamese_syllables_by_construction(
        token):
    """Một số từ tiếng Anh TRÙNG dạng âm tiết tiếng Việt — và điều đó không sao.

    "the" là dạng gỡ dấu của "thế/thể/thề"; "can" của "căn/cân/cần"; "long"
    của "lòng/lông". Chồng lấn ở mức TỪ ĐƠN là không tránh khỏi và cũng không
    cần tránh: chỉ số dùng để quyết định là TỈ LỆ trên cả đoạn, không phải
    phán quyết trên một token.

    Đo thật cho thấy chồng lấn này nhỏ: cả lát tiếng Anh 160 trang chỉ đạt tỉ
    lệ 0,214, cách xa ngưỡng 0,45.

    Test này tồn tại để người sau không "sửa" bằng cách thêm danh sách chặn từ
    tiếng Anh — làm vậy sẽ loại luôn những tiếng Việt hợp lệ trùng dạng.
    """
    assert is_vietnamese_syllable(token)


def test_syllable_check_ignores_diacritics_by_design():
    """Cùng một tiếng, có dấu hay không, đều phải hợp lệ.

    Đây là tính chất làm chỉ số này sống sót qua OCR mất dấu. Mất nó thì cả
    module vô dụng.
    """
    for with_acc, without in [("Nghị", "Nghi"), ("Đầu", "Dau"),
                              ("phố", "pho"), ("hữu", "huu"),
                              ("cứu", "cuu"), ("nghiên", "nghien")]:
        assert is_vietnamese_syllable(with_acc)
        assert is_vietnamese_syllable(without)


# ── ca chính: mất dấu ───────────────────────────────────────────────────────

def test_vietnamese_is_detected_when_accents_are_intact():
    r = detect_language(VI_TEXT)
    assert r.language is Language.VI
    assert r.accent_share > 0.1


def test_vietnamese_is_STILL_detected_after_ocr_strips_every_accent():
    """CA QUAN TRỌNG NHẤT TỆP NÀY.

    Tesseract trên kho thật làm tỉ lệ dấu tụt 0,217 → 0,080, và 30–49% số tệp
    ra gần như không còn dấu. Nếu ca này đỏ, những tệp đó bị định tuyến sang
    engine tiếng Anh và hỏng im lặng — không lỗi, không cảnh báo.
    """
    stripped = _strip(VI_TEXT)
    assert "ị" not in stripped and "ầ" not in stripped, "phải mất sạch dấu"

    r = detect_language(stripped)
    assert r.accent_share == 0.0, "không còn dấu nào — dấu vô dụng ở đây"
    assert r.language is Language.VI, (
        f"tiếng Việt mất dấu bị nhận nhầm thành {r.language.value}: {r.reason}")
    assert r.needs_vietnamese_postcorrect


def test_the_syllable_signal_does_not_move_when_accents_are_stripped():
    """Chỉ số cấu trúc phải gần như bất biến qua phép gỡ dấu.

    Đo trên toàn lát MDPBench: 0,842 → 0,842, chênh 0,000.
    """
    full = vietnamese_syllable_share(VI_TEXT)
    stripped = vietnamese_syllable_share(_strip(VI_TEXT))
    assert abs(full - stripped) < 0.05, f"{full:.3f} → {stripped:.3f}"


# ── không nhận nhầm ─────────────────────────────────────────────────────────

def test_english_is_not_mistaken_for_vietnamese():
    r = detect_language(EN_TEXT)
    assert r.language is Language.EN
    assert not r.needs_vietnamese_postcorrect


@pytest.mark.parametrize("text", [
    # Indonesian — Latin, không dấu, âm tiết mở giống tiếng Việt
    "Berdasarkan peraturan pemerintah tentang penanaman modal dan ketentuan "
    "pelaksanaannya maka perusahaan tersebut telah memenuhi persyaratan",
    # Spanish — lát cho tỉ lệ âm tiết cao nhất trong 16 lát ngoại (0,407)
    "De conformidad con las disposiciones del decreto sobre inversiones la "
    "direccion de planificacion certifica que la empresa ha completado",
    # Portuguese
    "Nos termos do decreto sobre investimentos a direcao de planeamento "
    "certifica que a empresa completou os procedimentos de registo comercial",
])
def test_other_latin_languages_are_not_mistaken_for_vietnamese(text):
    """Ba ngôn ngữ Latin gần tiếng Việt nhất trong MDPBench.

    Spanish và Portuguese là ca khó nhất đo được (0,407 / 0,404), không phải
    Indonesian như bản kế hoạch đầu giả định — Indonesian thực ra dễ nhất
    (0,067).
    """
    r = detect_language(text)
    assert r.language is not Language.VI, (
        f"nhận nhầm thành tiếng Việt: {r.reason}")


@pytest.mark.parametrize("lang, text", [
    ("Nhật", "これは日本語のテキストです。ドキュメントの内容を確認してください。"
             "ページ番号と日付が含まれています。"),
    ("Ả Rập", "هذا نص باللغة العربية يحتوي على معلومات مهمة حول المستند "
              "والتاريخ ورقم الصفحة المطلوبة"),
    ("Nga", "Это текст на русском языке содержащий важную информацию "
            "о документе и дате регистрации предприятия"),
])
def test_non_latin_scripts_with_combining_marks_are_not_taken_for_vietnamese(
        lang, text):
    """LỖI THẬT ĐÃ XẢY RA, không phải giả định.

    Bản đầu xét "có dấu tổ hợp ⇒ tiếng Việt" nên **44 trang tiếng Nhật, 4 Ả
    Rập, 4 Bồ Đào Nha** bị nhận nhầm. Dakuten (゛) và harakat cũng là dấu tổ
    hợp Unicode: `metrics.accent_share` của lát tiếng Nhật đạt 0,056 — cao hơn
    cả tiếng Pháp.

    Chữa bằng `vietnamese_accent_share`: chỉ đếm dấu tiếng Việt trên chữ cái
    Latin. Sau khi lọc, tiếng Nhật và Ả Rập về đúng 0,000.
    """
    from ocr_lab.metrics import accent_share as any_accent

    r = detect_language(text)
    assert r.language is not Language.VI, (
        f"{lang} bị nhận nhầm thành tiếng Việt: {r.reason}")
    if lang == "Nhật":
        assert any_accent(text) > 0, "tiếng Nhật CÓ dấu tổ hợp — đó là cái bẫy"
    assert r.accent_share == 0.0, "nhưng không có dấu TIẾNG VIỆT nào"


def test_vietnamese_accent_share_ignores_marks_from_other_scripts():
    from ocr_lab.language import vietnamese_accent_share
    from ocr_lab.metrics import accent_share as any_accent

    japanese = "ドキュメントの内容"
    assert any_accent(japanese) > 0
    assert vietnamese_accent_share(japanese) == 0.0
    assert vietnamese_accent_share("Điều khoản thi hành") > 0.2


# ── văn bản trộn ────────────────────────────────────────────────────────────

def test_mixed_text_still_routes_to_vietnamese_postcorrect():
    """Hợp đồng song ngữ phải được xử lý như có tiếng Việt.

    Bỏ sót tiếng Việt trong văn bản trộn tốn kém hơn là chạy thừa
    post-correct trên vài câu tiếng Anh.
    """
    mixed = ("Công ty cổ phần ABC (hereinafter referred to as the Company) "
             "cam kết thực hiện đầy đủ các nghĩa vụ theo hợp đồng này")
    r = detect_language(mixed)
    assert r.needs_vietnamese_postcorrect


# ── không đoán bừa ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", ["", "   ", "123 456", "...", "— — —"])
def test_text_without_letters_is_unknown_not_guessed(text):
    assert detect_language(text).language is Language.UNKNOWN


def test_a_few_words_without_accents_are_not_guessed():
    """"Hello world" vừa có thể là tiếng Anh, vừa là tên riêng trong văn bản VN.

    Đoán sai làm hỏng đường định tuyến, mà ta không có gì để bù lại. Trả
    UNKNOWN để bước sau biết là chưa đủ căn cứ.
    """
    r = detect_language("Hello world")
    assert r.language is Language.UNKNOWN
    assert "không đủ" in r.reason


def test_every_result_carries_a_checkable_reason():
    """Kết luận phải kèm lý do và số đo thô — để người đọc kiểm chứng được,
    và để gỡ lỗi một ca nhận nhầm mà không phải chạy lại debugger."""
    for text in (VI_TEXT, EN_TEXT, _strip(VI_TEXT), ""):
        r = detect_language(text)
        assert r.reason
        assert 0.0 <= r.accent_share <= 1.0
        assert 0.0 <= r.syllable_share <= 1.0
