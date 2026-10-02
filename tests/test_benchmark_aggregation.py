"""Kiểm cách bộ so sánh TỔNG HỢP số liệu.

Tệp này canh một lớp lỗi riêng: phép đo chạy đúng, từng trang tính đúng, mà
bảng tổng kết vẫn sai. Loại lỗi đó không lộ ra — nó cho một con số trông hợp
lý và ta đi kết luận về model dựa trên nó.

BÀI HỌC ĐẮT NHẤT: một lượt đo có 6/12 trang chạm trần token. Cảnh báo "BỊ CẮT"
đã bắt đúng cả sáu trang, nhưng phần tổng hợp vẫn cộng dồn chúng và in ra
"LOẠI — định danh 81,9%". Con số đó nói về ngân sách token của ta, không nói
gì về model. **Một cảnh báo mà phần tổng hợp phớt lờ là một cảnh báo vô dụng.**
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location(
    "benchmark", ROOT / "scripts" / "benchmark.py")
benchmark = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(benchmark)


# ── ghép ground truth theo thứ tự đọc ───────────────────────────────────────

def test_headers_come_first_and_footers_last_in_the_ground_truth():
    """Model đọc trang từ trên xuống, nên header phải đứng ĐẦU.

    MDPBench cho header/footer `order = None`. Đẩy chúng xuống cuối cho tiện
    là sai: Levenshtein phạt như đọc sai dù chữ đọc đúng từng ký tự. Đo trên
    `vi_academicpaper_17.jpg`: CER 0,389 (cuối) → 0,345 (đầu).
    """
    page = {"layout_dets": [
        {"category_type": "footer", "order": None, "text": "136"},
        {"category_type": "text_block", "order": 2, "text": "thân bài hai"},
        {"category_type": "header", "order": None, "text": "Tạp chí ABC"},
        {"category_type": "text_block", "order": 1, "text": "thân bài một"},
    ]}
    assert benchmark._ground_truth(page).splitlines() == [
        "Tạp chí ABC", "thân bài một", "thân bài hai", "136"]


def test_blocks_without_text_are_skipped_not_rendered_as_blank_lines():
    """Khối `figure` không có chữ — dòng trống thừa cũng làm CER nhích lên."""
    page = {"layout_dets": [
        {"category_type": "figure", "order": 0, "text": ""},
        {"category_type": "text_block", "order": 1, "text": "nội dung"},
    ]}
    assert benchmark._ground_truth(page) == "nội dung"


# ── loại trang không đo được ────────────────────────────────────────────────

class _FakeResult:
    def __init__(self, text, warnings=()):
        self.text, self.warnings = text, list(warnings)
        self.elapsed_ms, self.encode_ms = 1000.0, 0.0


class _FakeEngine:
    name, deployable_on_cpu_nas = "giả", True

    def __init__(self, by_page):
        self._by_page = by_page

    def read_page(self, path):
        return self._by_page[Path(path).name]


@pytest.fixture
def bench_dir(tmp_path, monkeypatch):
    images = tmp_path / "images"
    images.mkdir()
    for n in ("a.png", "b.png"):
        (images / n).write_bytes(b"x")
    monkeypatch.setattr(benchmark, "BENCH", tmp_path)
    return tmp_path


def _page(name, text):
    return {"page_info": {"image_path": name},
            "layout_dets": [{"category_type": "text_block", "order": 1,
                             "text": text}]}


def test_a_truncated_page_is_excluded_from_the_pooled_numbers(bench_dir):
    """Trang bị cắt phải bị LOẠI khỏi tổng hợp, không phải tính với điểm xấu.

    Số đo trên trang bị cắt không phải "kém chính xác" — nó VÔ NGHĨA: phần
    văn bản thiếu chưa từng được model đọc sai, nó chưa từng được model đọc.
    """
    pages = [_page("a.png", "Nghị định 56/2026/NĐ-CP ban hành ngày 12/03/2026"),
             _page("b.png", "Quyết định 1656/QĐ-TTg và số 789 kèm theo")]
    engine = _FakeEngine({
        # đọc hoàn hảo
        "a.png": _FakeResult("Nghị định 56/2026/NĐ-CP ban hành ngày 12/03/2026"),
        # bị cắt: mất sạch định danh, kèm cảnh báo
        "b.png": _FakeResult("Quyết định", ["CHẠM TRẦN 1024 token — BỊ CẮT"]),
    })

    s = benchmark._evaluate(engine, pages, bench_dir / "ra.json")

    assert s["pages_invalid"] == 1
    assert s["pages_read"] == 1, "chỉ trang đọc trọn mới được tính"
    assert s["identifier_preservation"] == 1.0, (
        "trang bị cắt kéo tỉ lệ xuống thì bảng điểm đang nói về ngân sách "
        "token, không nói về model")


def test_the_verdict_refuses_to_conclude_when_every_page_was_truncated(
        bench_dir, capsys):
    """Không còn trang hợp lệ nào ⇒ KHÔNG kết luận, thay vì kết luận bừa.

    Đưa ra phán quyết dựa trên phần sống sót là tự lừa mình: trang sống sót
    thường là trang ngắn, tức mẫu đã thiên lệch.
    """
    pages = [_page("a.png", "Nghị định 56/2026/NĐ-CP")]
    engine = _FakeEngine({
        "a.png": _FakeResult("Nghị", ["CHẠM TRẦN 1024 token — BỊ CẮT"])})

    s = benchmark._evaluate(engine, pages, bench_dir / "ra.json")
    assert s["pages_read"] == 0
    assert s["pages_invalid"] == 1
    assert s["cer"] is None, "không có gì để tính thì phải trả None"


def test_pooling_weights_by_length_instead_of_averaging_page_ratios(bench_dir):
    """Cộng dồn theo trọng số, không lấy trung bình các tỉ lệ.

    Một trang 5 ký tự sai hết sẽ kéo trung bình cộng xuống ngang một trang
    2 000 ký tự sai hết.
    """
    long_ref = "Điều khoản thi hành của nghị định này " * 12
    pages = [_page("a.png", long_ref), _page("b.png", "abc")]
    engine = _FakeEngine({"a.png": _FakeResult(long_ref),      # đúng hết
                          "b.png": _FakeResult("xyz")})        # sai hết

    s = benchmark._evaluate(engine, pages, bench_dir / "ra.json")

    # Trung bình cộng hai trang sẽ cho ~0,5. Cộng dồn theo ký tự cho gần 0.
    assert s["cer"] < 0.05, (
        f"CER gộp {s['cer']} — có vẻ đang lấy trung bình các tỉ lệ")
