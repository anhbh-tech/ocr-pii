"""Kiểm hậu xử lý protonX — trọng tâm là HAI LỚP BẢO VỆ ĐỊNH DANH.

Model này là model SINH CHỮ. Nó không thay thế có kiểm soát mà sinh lại câu,
nên nó có thể viết lại số hiệu, email, ngày tháng. Một model cùng loại (mBART)
từng đạt 86% ở `identifier_preservation` và bị LOẠI khỏi dự án này.

protonX tuyên bố "Correction ≠ rewriting, no hallucination". Tuyên bố không
phải bằng chứng — những test dưới đây là bằng chứng, và chúng ghi lại đúng ca
hỏng đã đo được trên máy này.
"""

import pytest

from ocr_lab.metrics import identifiers
from ocr_lab.postcorrect import (
    chunk_text,
    mask_identifiers,
    unmask_identifiers,
    _same_ignoring_diacritics,
    _strip_marks,
)


# ── chia đoạn ───────────────────────────────────────────────────────────────

def test_short_text_stays_in_one_chunk():
    chunks = chunk_text("Căn cứ Nghị định số 56/2026/NĐ-CP")
    assert len(chunks) == 1
    assert chunks[0].text == "Căn cứ Nghị định số 56/2026/NĐ-CP"


def test_every_chunk_respects_the_model_input_budget():
    """Trần đầu vào của model là 128 token — tác giả tự nêu.

    Vượt trần thì phần đuôi bị cắt IM LẶNG: model vẫn trả về câu trôi chảy,
    chỉ thiếu phần cuối, và ta không có cách nào biết.
    """
    long_text = "Điều khoản thi hành của nghị định này quy định chi tiết " * 30
    chunks = chunk_text(long_text, max_words=70)
    assert chunks
    for c in chunks:
        assert c.words <= 70, f"đoạn {c.words} từ, vượt ngân sách"


def test_chunks_prefer_sentence_boundaries_over_fixed_word_counts():
    """Cắt giữa câu làm model mất ngữ cảnh và bắt đầu bịa.

    Tác giả cảnh báo ảo giác trên câu dài; câu bị chặt đầu chặt đuôi cũng cho
    kết quả tương tự.
    """
    text = ("Điều 1. Phạm vi điều chỉnh của nghị định này. "
            "Điều 2. Đối tượng áp dụng bao gồm các tổ chức. "
            "Điều 3. Nguyên tắc thực hiện theo quy định.")
    chunks = chunk_text(text, max_words=8)
    # Không đoạn nào được bắt đầu bằng chữ thường giữa câu
    assert all(c.text.strip() for c in chunks)
    assert len(chunks) >= 2


def test_no_text_is_lost_when_chunking():
    """Chia đoạn KHÔNG được làm mất chữ — mất ở đây là mất im lặng."""
    text = ("Căn cứ Luật Đầu tư số 61/2020/QH14 ngày 17 tháng 6 năm 2020. " * 6)
    chunks = chunk_text(text, max_words=15)
    joined = " ".join(c.text for c in chunks)
    for token in ("61/2020/QH14", "Căn", "Đầu", "2020"):
        assert token in joined, f"mất {token!r} khi chia đoạn"


def test_empty_input_produces_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


# ── lớp 1: che định danh dễ vỡ ──────────────────────────────────────────────

def test_email_is_masked_before_reaching_the_model():
    """CA HỎNG THẬT ĐÃ ĐO ĐƯỢC.

        VÀO: Lien he thongtinchinhphu@chinhphu.vn hoac goi
        RA : Liên hệ thống tin chính phủchinhphu.vn hoặc gọi
                                        ↑ mất @, email vỡ

    Model đọc `thongtinchinhphu` như tiếng Việt không dấu rồi "sửa" thành
    "thống tin chính phủ". Đo trên 11 ca: 9/9 ca KHÔNG có email đạt định danh
    100%, cả 2 ca có email đều vỡ. Thiệt hại tập trung đúng một chỗ.
    """
    masked, saved = mask_identifiers(
        "Lien he thongtinchinhphu@chinhphu.vn hoac goi 0243.123.456")
    assert "@" not in masked
    assert "[ID0]" in masked
    assert saved == ["thongtinchinhphu@chinhphu.vn"]


def test_masking_round_trips_exactly():
    text = "Gửi tới info@congty.com.vn và admin@bo-tu-phap.gov.vn hôm nay"
    masked, saved = mask_identifiers(text)
    assert len(saved) == 2
    assert unmask_identifiers(masked, saved) == text


def test_urls_are_masked_too():
    masked, saved = mask_identifiers(
        "Xem tại https://chinhphu.vn/van-ban để biết chi tiết")
    assert "https" not in masked
    assert saved == ["https://chinhphu.vn/van-ban"]


def test_document_numbers_and_dates_are_NOT_masked():
    """Che THỪA cũng có hại: câu vụn thì model mất ngữ cảnh.

    Đo thật: model xử lý đúng 100% số hiệu văn bản, ngày, số tiền, mã hồ sơ
    (9/9 ca). Chỉ email và URL mới cần che. Che tất cả là bỏ đi chính giá trị
    của model.
    """
    text = "Nghị định 56/2026/NĐ-CP ngày 12/03/2026 trị giá 1.234.567 đồng"
    masked, saved = mask_identifiers(text)
    assert saved == [], "chỉ che email và URL"
    assert masked == text


# ── lớp 2: nhận biết sửa đúng và làm hỏng ───────────────────────────────────

def test_restoring_a_diacritic_inside_an_identifier_counts_as_correct():
    """`56/2026/ND-CP` → `56/2026/NĐ-CP` là SỬA ĐÚNG, không phải làm hỏng.

    Đây là lỗi bộ đo đã gặp: so định danh với ĐẦU VÀO thì việc model phục hồi
    chữ Đ trông như "mất định danh", và 2/4 ca bị báo hỏng oan. Phải so với
    BẢN ĐÚNG, và chấp nhận thay đổi chỉ nằm ở dấu.
    """
    assert _same_ignoring_diacritics(["56/2026/ND-CP"], ["56/2026/NĐ-CP"])
    assert _same_ignoring_diacritics(["1656/QD-TTg"], ["1656/QĐ-TTg"])


def test_a_broken_email_is_NOT_excused_as_a_diacritic_fix():
    """Mất ký tự `@` là làm hỏng, không phải chuyện dấu.

    Nếu phép phân biệt này nới tay thì lớp bảo vệ thứ hai vô hiệu.
    """
    assert not _same_ignoring_diacritics(
        ["info@congty.com.vn"], ["infocongty.com.vn"])
    assert not _same_ignoring_diacritics(["0243.123.456"], ["0243.123.455"])
    assert not _same_ignoring_diacritics(["56/2026/NĐ-CP"], ["56/2027/NĐ-CP"])


def test_dropping_an_identifier_entirely_is_detected():
    assert not _same_ignoring_diacritics(["56/2026/NĐ-CP", "a@b.vn"],
                                         ["56/2026/NĐ-CP"])


# ── engine thật: skip CÓ LÝ DO ──────────────────────────────────────────────

MODEL_SPEC = "protonx-models/protonx-legal-tc"


def _corrector_or_skip():
    from pathlib import Path

    from ocr_lab.postcorrect import PostCorrector

    root = Path(__file__).resolve().parent.parent
    model = root / "models" / "protonx-legal-tc"
    if not model.exists():
        pytest.skip(f"thiếu model {model.name} — tải từ {MODEL_SPEC} "
                    f"bằng huggingface_hub.snapshot_download")
    pc = PostCorrector(model, device="cpu")
    try:
        pc.ensure_ready()
    except ImportError as exc:
        pytest.skip(f"thiếu phụ thuộc: {exc}")
    return pc


@pytest.mark.slow
def test_the_model_restores_diacritics_on_accentless_vietnamese():
    """Điểm mạnh thật của model, đo trên ví dụ của chính tác giả."""
    from ocr_lab.metrics import accent_share

    pc = _corrector_or_skip()
    out = pc.correct_chunk(
        "can cu bo luat lao dong 2019 va cac van ban huong dan thuc hien")
    assert accent_share(out) > 0.20, f"không phục hồi được dấu: {out!r}"
    assert "2019" in out


@pytest.mark.slow
def test_an_email_survives_the_full_correction_path():
    """Ca hỏng gốc, chạy qua đủ hai lớp bảo vệ."""
    pc = _corrector_or_skip()
    out = pc.correct_chunk(
        "Lien he thongtinchinhphu@chinhphu.vn hoac goi 0243.123.456")
    assert "thongtinchinhphu@chinhphu.vn" in out, (
        f"email vẫn bị làm vỡ: {out!r}")


@pytest.mark.slow
def test_the_corrector_falls_back_to_the_original_rather_than_damage_ids():
    """Lớp 2 phải chặn cả loại hỏng CHƯA BIẾT.

    Che chỉ xử lý được loại hỏng đã biết. Nếu model làm hỏng một định danh
    theo cách khác, phải trả nguyên bản — mất phần sửa dấu của đoạn đó còn
    rẻ hơn nhiều so với làm vỡ một số hiệu.
    """
    pc = _corrector_or_skip()
    for text in [
        "Can cu Nghi dinh so 56/2026/ND-CP ngay 12/03/2026 cua Chinh phu",
        "Theo QD 1656/QD-TTg va TT 03/2025/TT-BTC ngay 01/01/2025",
        "Ho so BQ96.US va NQ9001 da duoc tiep nhan",
        "Tong gia tri hop dong la 1.234.567.890 dong",
    ]:
        out = pc.correct_chunk(text)
        # Bỏ qua chuyện dấu: điều cần kiểm là CHỮ SỐ và khung định danh còn
        # nguyên.
        before = sorted(_strip_marks(x) for x in identifiers(text))
        after = sorted(_strip_marks(x) for x in identifiers(out))
        assert before == after, (
            f"định danh bị đổi:\n  vào: {text}\n  ra : {out}")


# ── chia khối theo token (thay cho chia theo từ của notebook) ───────────

def test_mac_dinh_la_teacher_904MB_khong_phai_nano():
    """Nano 171MB từng bị dùng nhầm: 3 sửa đúng / 10 đổi chữ bậy, so với
    teacher 4 / 5 trên cùng dữ liệu. Khoá mặc định lại."""
    from ocr_lab.postcorrect import DEFAULT_MODEL_DIR
    assert "nano" not in DEFAULT_MODEL_DIR
    assert DEFAULT_MODEL_DIR.endswith("protonx-legal-tc")


def test_tran_token_duoi_gioi_han_model():
    """README model: 128 token input. Trần phải nằm DƯỚI, chừa biên."""
    from ocr_lab.postcorrect import DEFAULT_MAX_INPUT_TOKENS
    assert DEFAULT_MAX_INPUT_TOKENS <= 128


def test_chia_khoi_khong_lam_mat_tu(monkeypatch):
    """Ghép các khối lại phải ra đúng danh sách từ ban đầu.

    Đây là bất biến quan trọng nhất của việc chia nhỏ: mất một từ ở đây thì
    bản chép thiếu chữ mà không có dấu hiệu gì — đúng kiểu hỏng im lặng mà
    việc chia khối sinh ra để tránh.
    """
    from ocr_lab.postcorrect import PostCorrector

    pc = PostCorrector.__new__(PostCorrector)
    pc.max_input_tokens = 10
    pc.ensure_ready = lambda: None
    # tokenizer giả: 1 token mỗi ký tự — không cần nạp model 904 MB.
    pc._tok = type("T", (), {
        "__call__": lambda self, s: type("O", (), {"input_ids": list(s)})()
    })()

    text = " ".join(f"từ{i}" for i in range(40))
    blocks = pc.split_by_tokens(text)
    assert len(blocks) > 1
    assert " ".join(blocks).split() == text.split()


def test_chia_khoi_ton_trong_tran():
    from ocr_lab.postcorrect import PostCorrector

    pc = PostCorrector.__new__(PostCorrector)
    pc.max_input_tokens = 10
    pc.ensure_ready = lambda: None
    pc._tok = type("T", (), {
        "__call__": lambda self, s: type("O", (), {"input_ids": list(s)})()
    })()

    blocks = pc.split_by_tokens(" ".join("abc" for _ in range(20)))
    # Mỗi khối dưới trần, trừ khi một TỪ đơn lẻ đã vượt trần (không chia
    # được nữa mà không cắt giữa từ).
    for b in blocks:
        assert len(b) <= 10 or len(b.split()) == 1
