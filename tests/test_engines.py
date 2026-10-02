"""Kiểm trình bao engine.

Nguyên tắc của tệp này: **test nào cần model thật thì SKIP CÓ LÝ DO RÕ RÀNG,
không bao giờ `except Exception → skip`.** Dự án này đã ghi bẫy đó vào sổ: nó
biến hỏng hóc thành xanh giả. Chạy `pytest -rs` để xem lý do skip.

Phần lớn test ở đây dùng engine giả — chúng kiểm HỢP ĐỒNG của lớp cơ sở
(bấm giờ, nạp một lần, tách thời gian mã hoá), không kiểm chất lượng OCR.
"""

import time
from pathlib import Path

import pytest

from ocr_lab.engines import (
    EngineUnavailable,
    LlamaCppVlmEngine,
    OcrEngine,
    OcrResult,
    TesseractEngine,
    available_engines,
    build_engine,
)

ROOT = Path(__file__).resolve().parent.parent


class FakeEngine(OcrEngine):
    """Engine giả — đếm số lần nạp để kiểm hợp đồng của lớp cơ sở."""

    name = "fake"
    deployable_on_cpu_nas = True

    def __init__(self, text="xin chào", delay=0.01, encode_ms=0.0):
        super().__init__()
        self.text, self.delay, self.encode_ms = text, delay, encode_ms
        self.loads = 0
        self.reads = 0

    def _load(self):
        self.loads += 1

    def _read(self, image_path):
        self.reads += 1
        time.sleep(self.delay)
        return OcrResult(self.text, self.name, 0.0, encode_ms=self.encode_ms)


@pytest.fixture
def image(tmp_path):
    from PIL import Image

    p = tmp_path / "trang.png"
    Image.new("RGB", (64, 32), "white").save(p)
    return p


# ── hợp đồng của lớp cơ sở ──────────────────────────────────────────────────

def test_the_model_is_loaded_once_no_matter_how_many_pages_are_read(image):
    """Nạp lại model cho mỗi trang là lỗi tốn kém nhất của một vòng OCR.

    Đúng lỗi này làm `pytesseract` chậm gấp đôi `tesserocr`: nó nạp lại
    traineddata ở mỗi lần gọi.
    """
    eng = FakeEngine()
    for _ in range(5):
        eng.read_page(image)
    assert eng.loads == 1
    assert eng.reads == 5


def test_loading_is_not_counted_in_the_time_of_the_first_page(image):
    """Thời gian nạp phải nằm ngoài thời gian đọc trang.

    Gộp vào thì trang đầu tiên trông chậm bất thường và ta sẽ so sai giữa các
    engine — engine nào nạp lâu sẽ bị phạt oan dù đọc nhanh.
    """
    eng = FakeEngine(delay=0.01)

    class SlowLoading(type(eng)):
        def _load(self):
            time.sleep(0.3)
            super()._load()

    slow = SlowLoading(delay=0.01)
    slow.ensure_ready()                 # nạp trước, như bộ so sánh vẫn làm
    r = slow.read_page(image)
    assert r.elapsed_ms < 200, f"{r.elapsed_ms:.0f} ms — lẫn cả thời gian nạp"


def test_every_engine_is_timed_by_the_same_clock(image):
    eng = FakeEngine(delay=0.05)
    r = eng.read_page(image)
    assert 40 <= r.elapsed_ms <= 400


def test_encode_time_is_reported_separately_from_generation(image):
    """Tách hai giai đoạn, vì nút thắt không nằm ở chỗ ai cũng nghĩ.

    Đo thật trên llama.cpp: 261 giây mã hoá ảnh / 306 giây tổng. Chỉ nhìn tổng
    thì ta sẽ đi tối ưu phần sinh token — tức nhầm chỗ hoàn toàn.
    """
    eng = FakeEngine(delay=0.05, encode_ms=30.0)
    r = eng.read_page(image)
    assert r.encode_ms == 30.0
    assert r.generate_ms == pytest.approx(r.elapsed_ms - 30.0)
    assert r.generate_ms >= 0


def test_generate_time_never_goes_negative(image):
    """Engine báo encode_ms lớn hơn tổng (đồng hồ lệch) không được ra số âm."""
    eng = FakeEngine(delay=0.001, encode_ms=9999.0)
    assert eng.read_page(image).generate_ms == 0.0


def test_a_missing_image_fails_loudly(tmp_path):
    """Ảnh thiếu phải ném lỗi, không được trả kết quả rỗng.

    Trả rỗng sẽ lẫn vào thống kê thành "engine đọc trượt trang này", và ta đi
    truy lỗi chất lượng OCR trong khi thật ra là thiếu tệp.
    """
    with pytest.raises(FileNotFoundError):
        FakeEngine().read_page(tmp_path / "không-có.png")


def test_empty_output_is_detectable(image):
    assert FakeEngine(text="   ").read_page(image).is_empty
    assert not FakeEngine(text="chữ").read_page(image).is_empty


# ── ràng buộc triển khai ────────────────────────────────────────────────────

def test_every_engine_declares_whether_it_runs_on_the_cpu_only_nas():
    """Ràng buộc đích triển khai phải là TRƯỜNG DỮ LIỆU, không phải chú thích.

    Nửa ngày đo đạc đã mất vì Apple Vision thắng mọi chỉ số rồi mới phát hiện
    nó chỉ chạy trên macOS + Neural Engine, không đưa lên NAS được. Trường này
    tồn tại để chuyện đó không lặp lại — bảng so sánh phải in nó ra.
    """
    for cls in (TesseractEngine, LlamaCppVlmEngine, FakeEngine):
        assert isinstance(cls.deployable_on_cpu_nas, bool)
    assert TesseractEngine.deployable_on_cpu_nas
    assert LlamaCppVlmEngine.deployable_on_cpu_nas


def test_an_engine_that_forgets_the_contract_cannot_be_instantiated():
    """Quên `_read`/`_load` là lỗi NGAY, không phải lỗi lúc chạy nửa mẻ đo."""
    class Broken(OcrEngine):
        name = "broken"

    with pytest.raises(TypeError):
        Broken()


# ── dựng engine từ chuỗi mô tả ──────────────────────────────────────────────

def test_the_default_quantises_the_vision_encoder_but_not_the_language_model():
    """Hai nửa của VLM phải xử lý khác nhau — đo tách biến mới thấy.

    mmproj BF16 không có kernel trên CPU ARM; Q8_0 thì có. Đổi RIÊNG mmproj
    lấy 5,3× tốc độ mã hoá (374→71 s) mà chất lượng còn nhỉnh hơn.

    Nhưng hạ tiếp model NGÔN NGỮ xuống Q4_K_M thì phá chất lượng: định danh
    gộp 0,912 → 0,671, một trang tụt 0,962 → 0,288.

        cấu hình              mã hoá   tổng     CER   định danh
        bf16 chính chủ         374 s   456 s   0,343     0,905
        q4_k_m + mmproj q8      72 s    96 s   0,423     0,671
        bf16 + mmproj q8        71 s   144 s   0,334     0,912  ← mặc định

    Test này canh cả hai hướng sai: quay về BF16 toàn phần (chậm 3×) và hạ
    luôn model ngôn ngữ (mất định danh).
    """
    default = build_engine("paddleocr-vl")
    assert "Q8_0" in default.mmproj.name, (
        "mmproj phải lượng tử hoá — đó là chỗ nghẽn, và gần như miễn phí")
    assert "Q4" not in default.model.name, (
        "model ngôn ngữ KHÔNG được hạ xuống Q4: định danh tụt 0,912 → 0,671")

    official = build_engine("paddleocr-vl-bf16")
    assert "mmproj.gguf" in official.mmproj.name, "giữ lại để đối chiếu"
    assert build_engine("paddleocr-vl-q4").model.name != default.model.name


def test_engine_specs_parse_into_the_right_configuration():
    assert build_engine("tesseract").lang == "vie+eng"
    assert build_engine("tesseract:vie").lang == "vie"

    plain = build_engine("paddleocr-vl")
    assert plain.max_long_edge is None

    scaled = build_engine("paddleocr-vl@1500")
    assert scaled.max_long_edge == 1500, (
        "hậu tố @N là đòn bẩy tốc độ chính của engine VLM")


def test_an_unknown_engine_name_is_rejected_with_a_helpful_message():
    with pytest.raises(ValueError, match="không biết engine"):
        build_engine("engine-không-tồn-tại")


def test_no_absolute_machine_paths_are_baked_into_the_engine_registry():
    """Đường dẫn phải tính từ gốc dự án hoặc lấy từ biến môi trường.

    Bài học `refiny_engine`: test cắm cứng đường dẫn devbox cũ đã skip im lặng
    hàng tháng trời.
    """
    src = (ROOT / "src" / "ocr_lab" / "engines" / "__init__.py").read_text()
    assert "/Users/" not in src and "/home/" not in src


# ── engine thật: skip CÓ LÝ DO, không nuốt lỗi ──────────────────────────────

def _engine_or_skip(spec):
    """Dựng engine thật; thiếu công cụ thì skip kèm lý do CỤ THỂ.

    Chỉ bắt `EngineUnavailable` — mọi ngoại lệ khác phải nổ ra. Bắt
    `Exception` ở đây chính là cái bẫy "biến hỏng hóc thành xanh giả".
    """
    try:
        eng = build_engine(spec)
        eng.ensure_ready()
        return eng
    except EngineUnavailable as exc:
        pytest.skip(f"{spec} không dùng được: {exc}")


def test_tesseract_reads_an_image_end_to_end(image):
    eng = _engine_or_skip("tesseract")
    r = eng.read_page(image)
    assert r.engine == "tesseract"
    assert r.elapsed_ms > 0
    assert isinstance(r.text, str)      # ảnh trắng → có thể rỗng, vẫn hợp lệ


def test_tesseract_refuses_to_run_without_vietnamese_traineddata():
    """Thiếu `vie` thì tesseract vẫn chạy bằng model tiếng Anh và cho số SAI.

    Thà chết ngay lúc nạp còn hơn cho ra một bảng điểm trông hợp lệ.
    """
    eng = TesseractEngine(lang="vie+eng+ngôn-ngữ-không-tồn-tại")
    with pytest.raises(EngineUnavailable, match="thiếu traineddata"):
        eng._check_languages()


def test_the_vlm_engine_reports_why_it_cannot_run_when_models_are_absent(
        tmp_path):
    eng = LlamaCppVlmEngine(tmp_path / "không-có.gguf",
                            tmp_path / "cũng-không-có.gguf")
    with pytest.raises(EngineUnavailable, match="thiếu tệp|llama-mtmd-cli"):
        eng.ensure_ready()


def test_the_availability_report_names_every_engine_with_a_verdict():
    """Báo cáo phải liệt kê CẢ engine hỏng kèm lý do.

    Bỏ qua lặng lẽ là cách một bảng so sánh trở nên sai mà vẫn trông đầy đủ.
    """
    report = available_engines()
    assert "tesseract" in report and "paddleocr-vl" in report
    for spec, verdict in report.items():
        assert verdict, f"{spec} không có kết luận"


# ── phát hiện văn bản bị cắt ────────────────────────────────────────────────

def _vlm(tmp_path, n_predict=1024):
    return LlamaCppVlmEngine(tmp_path / "m.gguf", tmp_path / "p.gguf",
                             n_predict=n_predict)


def test_text_stopping_mid_sentence_is_flagged_as_truncated(tmp_path):
    """CA THẬT: model dừng giữa câu vì hết ngân sách token.

    `vi_academicpaper_17.jpg` (trang tài liệu tham khảo) dừng ở "J Sci Food
    Agric", mất 12/67 định danh. Cả BA cấu hình model đều cho đúng 0,821 —
    con số giống hệt nhau qua ba model khác nhau chính là dấu hiệu lỗi nằm ở
    PHÉP ĐO, không ở model.

    Không bắt được thì trang bị cắt lặng lẽ làm xấu CER và tỉ lệ định danh,
    rồi ta đổ oan cho chất lượng model.
    """
    # n_predict nhỏ để đoạn mẫu này nằm quá nửa ngân sách — giống ca thật,
    # nơi trang 2 844 ký tự dùng gần hết 1024 token rồi mới đứt.
    eng = _vlm(tmp_path, n_predict=64)
    assert eng._looks_truncated(
        "Gofman, F., & Bergman, C. (2004). Rice kernel phenolic content "
        "and its relationship with antiradical efficiency. J Sci Food Agric")


def test_a_short_reply_ending_oddly_is_not_flagged(tmp_path):
    """Dùng ít token mà kết thúc lạ ⇒ model dừng vì HẾT NỘI DUNG.

    Trang gần trống hoặc chỉ có một nhãn hình là ca bình thường, không phải
    lỗi. Gạt nhầm chúng khỏi phép đo là mất dữ liệu.
    """
    eng = _vlm(tmp_path, n_predict=2560)
    assert not eng._looks_truncated("Hình 2")


def test_text_ending_on_punctuation_is_not_flagged(tmp_path):
    """Trang đọc trọn gần như luôn kết thúc bằng dấu câu hoặc số trang."""
    eng = _vlm(tmp_path)
    for ending in ["Kết thúc văn bản.", "xem bảng 3:", "(Ghi chú: A, B, C)",
                   "trang 136", "kết quả nghiên cứu…"]:
        assert not eng._looks_truncated(ending), ending


def test_a_screenshot_page_ending_in_browser_chrome_is_not_called_truncated(
        tmp_path):
    """BÁO ĐỘNG GIẢ ĐÃ GẶP: ảnh chụp MÀN HÌNH, không phải ảnh chụp giấy.

    Trang `vi_academicpaper_17_blur_indoor_screen_top.jpg` là ảnh chụp màn
    hình; model đọc đúng cả thanh tìm kiếm trình duyệt nên văn bản kết thúc
    bằng "Q 搜索". Quy tắc "không kết thúc bằng dấu câu ⇒ bị cắt" gạt nhầm
    trang đó khỏi phép đo — mất dữ liệu vì một luật quá thô.

    Sửa: dấu hiệu kết thúc lạ chỉ được xét khi đã dùng quá NỬA ngân sách.
    Dùng ít token mà kết thúc lạ nghĩa là model dừng vì hết nội dung, và nội
    dung lạ chỉ là nội dung lạ.
    """
    eng = _vlm(tmp_path, n_predict=2560)
    text = ("Graham, R. (2002). A proposal for IRRI to establish a grain "
            "quality and nutrition research center (No. 2169-2019-1615).\n\n"
            "136\n\nQ 搜索")
    assert not eng._looks_truncated(text)


def test_output_near_the_token_budget_is_flagged_even_if_it_ends_cleanly(
        tmp_path):
    """Chạm trần token là dấu hiệu đủ, kể cả khi câu tình cờ kết thúc gọn.

    Ngưỡng cũ `len > n_predict * 2.5` bỏ lọt ca thật vì tỉ lệ đo được là
    2,61 ký tự/token — ngay TRÊN ngưỡng. Đoán một con số sát mép là vô dụng.
    """
    eng = _vlm(tmp_path, n_predict=100)
    assert eng._looks_truncated("x" * 250 + ".")
    assert not eng._looks_truncated("x" * 50 + ".")


def test_empty_text_is_not_reported_as_truncated(tmp_path):
    """Rỗng là lỗi khác hẳn — phải báo đúng tên của nó."""
    assert not _vlm(tmp_path)._looks_truncated("")
    assert not _vlm(tmp_path)._looks_truncated("   ")


def test_repeated_hallucinated_lines_are_detected(tmp_path):
    """LỖI THỨ BA: ảo giác lặp — model kẹt vòng, sinh lại cùng một đoạn.

    Đo thật trên 36 trang: 2 trang cho coverage 1,96 và 1,67 — gần GẤP ĐÔI
    nội dung trang. Nguy hiểm hơn đọc sai vì văn bản bịa vẫn đọc trôi chảy,
    và nó kéo tỉ lệ định danh xuống (0,154) trong khi model không hề "đọc
    kém" — nó đang bịa.
    """
    eng = _vlm(tmp_path)
    line = "Căn cứ Nghị định số 56 quy định chi tiết một số điều của Luật"
    assert eng._repetition_ratio("\n".join([line] * 8)) > 0.30
    assert eng._repetition_ratio(
        "\n".join([line, line, line, line + " khác", "dòng hoàn toàn khác "
                   "với nội dung dài hơn hai mươi lăm ký tự"])) > 0.30


def test_a_normal_page_is_not_flagged_as_repetitive(tmp_path):
    """Tài liệu thật lặp dòng NGẮN rất nhiều — ô bảng, số mục, nhãn.

    Đếm cả dòng ngắn sẽ gạt oan mọi trang có bảng biểu.
    """
    eng = _vlm(tmp_path)
    table = "\n".join(["1.", "A", "Nâu", "2.", "B", "Nâu", "3.", "C", "Nâu"])
    assert eng._repetition_ratio(table) == 0.0

    prose = "\n".join(f"Điều {i}. Quy định chi tiết về nội dung thứ {i} của "
                      f"nghị định này" for i in range(6))
    assert eng._repetition_ratio(prose) == 0.0


def test_short_output_is_not_judged_for_repetition(tmp_path):
    """Dưới 4 dòng dài thì mẫu quá nhỏ để kết luận."""
    eng = _vlm(tmp_path)
    line = "Một dòng văn bản dài hơn hai mươi lăm ký tự để tính"
    assert eng._repetition_ratio("\n".join([line] * 3)) == 0.0


# ── thu nhỏ ảnh ─────────────────────────────────────────────────────────────

def test_resizing_shrinks_a_large_page_to_the_requested_long_edge(tmp_path):
    """Thu nhỏ là đòn bẩy tốc độ chính — phải đúng tỉ lệ và đúng cạnh dài."""
    from PIL import Image

    src = tmp_path / "to.png"
    Image.new("RGB", (4096, 3072), "white").save(src)

    eng = LlamaCppVlmEngine(tmp_path / "m.gguf", tmp_path / "p.gguf",
                            max_long_edge=1500)
    out = eng._prepare_image(src, str(tmp_path))
    w, h = Image.open(out).size
    assert max(w, h) == 1500
    assert abs(w / h - 4096 / 3072) < 0.01, "phải giữ nguyên tỉ lệ khung"


def test_a_palette_image_is_converted_before_resizing(tmp_path):
    """Ảnh PNG bảng màu (mode "P") không ghi ra JPEG được — lỗi thật đã gặp.

    `vi_exampaper_3.png` trong MDPBench là ảnh như vậy và nó làm chết cả một
    lượt quét độ phân giải.
    """
    from PIL import Image

    src = tmp_path / "bang-mau.png"
    Image.new("P", (3000, 2000)).save(src)
    assert Image.open(src).mode == "P"

    eng = LlamaCppVlmEngine(tmp_path / "m.gguf", tmp_path / "p.gguf",
                            max_long_edge=1000)
    out = eng._prepare_image(src, str(tmp_path))
    assert max(Image.open(out).size) == 1000


def test_a_small_image_is_never_upscaled(tmp_path):
    """Phóng to KHÔNG thêm thông tin, chỉ thêm token ảnh và thêm thời gian.

    Bài học đã ghi: render lại ở DPI cao cho thêm 7% ký tự nhưng ÍT DẤU HƠN
    (nhiễu) và chậm gấp đôi.
    """
    from PIL import Image

    src = tmp_path / "nho.png"
    Image.new("RGB", (800, 600), "white").save(src)

    eng = LlamaCppVlmEngine(tmp_path / "m.gguf", tmp_path / "p.gguf",
                            max_long_edge=2000)
    assert eng._prepare_image(src, str(tmp_path)) == src, "không được phóng to"
