"""Cổng hồi quy: ngưỡng ngôn ngữ phải giữ được sự tách bạch trên dữ liệu THẬT.

Vì sao tách khỏi `test_language.py`: những test kia dùng câu tự soạn nên luôn
chạy được. Test ở đây cần 73 MB ground truth MDPBench, nên nó SKIP khi chưa
tải. Trộn hai loại vào một tệp thì một ngày nào đó không ai để ý là phần quan
trọng đang bị bỏ qua.

Con số dưới đây đông cứng kết quả hiệu chuẩn trên 2 652 trang / 17 ngôn ngữ.
Chúng bảo vệ một tính chất mà ta sẽ không tự phát hiện được nếu vỡ: bảng âm vị
trong `language.py` nhìn có vẻ vô hại khi sửa, nhưng thêm một vần rộng tay có
thể kéo tỉ lệ của tiếng Tây Ban Nha vượt ngưỡng, và từ đó văn bản ngoại ngữ bị
đưa vào đường xử lý tiếng Việt.

Nếu test này đỏ sau khi bạn sửa bảng âm vị: chạy lại
`uv run python scripts/calibrate_language.py`, xem khoảng trống còn bao nhiêu,
rồi mới quyết định đổi ngưỡng hay hoàn lại phần sửa. ĐỪNG nới con số ở đây cho
vừa với thay đổi — nó là lưới canh, không phải chỉ tiêu cần đạt.
"""

import json
import unicodedata as ud
from pathlib import Path

import pytest

from ocr_lab.language import (
    _SYLLABLE_IS_VIETNAMESE,
    Language,
    detect_language,
    vietnamese_syllable_share,
)

ROOT = Path(__file__).resolve().parent.parent
GT = ROOT / "data" / "benchmarks" / "mdpbench" / "MDPBench_public.json"

pytestmark = pytest.mark.skipif(
    not GT.exists(),
    reason=f"thiếu ground truth MDPBench ({GT.name}) — chạy "
           f"`uv run python scripts/fetch_mdpbench.py --no-images`")

#: Trang ngắn hơn mức này thì tỉ lệ âm tiết là nhiễu — trùng với
#: `_MIN_TOKENS_FOR_STRUCTURE` trong `language.py`.
_MIN_WORDS = 8


def _strip(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in ud.normalize("NFD", text) if not ud.combining(c))


@pytest.fixture(scope="module")
def slices() -> dict[str, list[str]]:
    """Văn bản từng trang, gom theo ngôn ngữ. Ghép theo đúng thứ tự đọc."""
    data = json.loads(GT.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for page in data:
        lang = page.get("page_info", {}).get("page_attribute", {}).get("language")
        dets = sorted(page.get("layout_dets", []),
                      key=lambda d: (d.get("order") is None, d.get("order") or 0))
        text = "\n".join(d["text"] for d in dets if d.get("text"))
        if text.strip() and len(text.split()) >= _MIN_WORDS:
            out.setdefault(lang, []).append(text)
    return out


def test_the_benchmark_still_has_the_seventeen_language_slices(slices):
    """Bộ dữ liệu đổi thì mọi ngưỡng hiệu chuẩn trên nó phải xem lại."""
    assert len(slices) == 17, f"có {len(slices)} lát, hiệu chuẩn dựa trên 17"
    assert "Vietnamese" in slices


def test_stripping_accents_does_not_move_the_syllable_signal(slices):
    """TÍNH CHẤT CỐT LÕI: chỉ số phải bất biến khi mất dấu.

    Đây là điều làm nó dùng được cho đầu ra OCR mất dấu. Đo trên cả lát:
    0,842 → 0,842. Nếu tính chất này vỡ thì module không còn lý do tồn tại.
    """
    joined = "\n".join(slices["Vietnamese"])
    before = vietnamese_syllable_share(joined)
    after = vietnamese_syllable_share(_strip(joined))
    assert before > 0.80
    assert abs(before - after) < 0.01, f"{before:.3f} → {after:.3f}"


def test_every_vietnamese_page_stays_above_every_foreign_page(slices):
    """Khoảng trống phải còn nguyên: 0,407 (ngoại cao nhất) → 0,494 (VN thấp nhất).

    Đây là test đắt nhất tệp này và cũng đáng nhất: nó kiểm TỪNG trang trong
    2 652 trang, chứ không kiểm con số tổng. Tổng có thể đẹp trong khi vài
    trang riêng lẻ vẫn xếp nhầm — mà đường định tuyến chạy theo từng trang.
    """
    vi_lo = min(vietnamese_syllable_share(_strip(t))
                for t in slices["Vietnamese"])
    foreign = {lang: max(vietnamese_syllable_share(t) for t in texts)
               for lang, texts in slices.items() if lang != "Vietnamese"}
    fo_hi = max(foreign.values())
    worst = max(foreign, key=lambda k: foreign[k])

    assert fo_hi < vi_lo, (
        f"hết khoảng trống: {worst} đạt {fo_hi:.3f}, trang tiếng Việt thấp "
        f"nhất {vi_lo:.3f}")
    assert fo_hi < _SYLLABLE_IS_VIETNAMESE < vi_lo, (
        f"ngưỡng {_SYLLABLE_IS_VIETNAMESE} không còn nằm giữa "
        f"[{fo_hi:.3f}, {vi_lo:.3f}]")
    assert vi_lo - fo_hi > 0.05, (
        f"biên chỉ còn {vi_lo - fo_hi:.3f} — quá hẹp để tin")


def test_no_vietnamese_page_is_lost_after_accents_are_stripped(slices):
    """160/160 trang tiếng Việt mất dấu vẫn phải được nhận là tiếng Việt.

    Đây chính là hình dạng lỗi thật trên kho: tesseract làm tỉ lệ dấu tụt
    0,217 → 0,080, và 30–49% số tệp ra gần như không còn dấu nào.
    """
    missed = [i for i, t in enumerate(slices["Vietnamese"])
              if detect_language(_strip(t)).language is not Language.VI]
    assert not missed, (
        f"{len(missed)}/{len(slices['Vietnamese'])} trang tiếng Việt mất dấu "
        f"bị nhận nhầm")


def test_no_foreign_page_is_routed_into_the_vietnamese_path(slices):
    """Không trang ngoại ngữ nào trong 2 492 trang được nhận là tiếng Việt."""
    wrong = {lang: sum(1 for t in texts
                       if detect_language(t).language is Language.VI)
             for lang, texts in slices.items() if lang != "Vietnamese"}
    offenders = {k: v for k, v in wrong.items() if v}
    assert not offenders, f"nhận nhầm thành tiếng Việt: {offenders}"


def test_the_hardest_adversarial_slices_are_the_romance_languages(slices):
    """Ghi lại ca khó nhất THẬT SỰ, vì kế hoạch gốc đoán sai.

    Kế hoạch cho rằng Indonesian là ca đối kháng khó nhất (cũng Latin, cũng
    không dấu). Đo thật: Indonesian dễ nhất (0,067), còn khó nhất là các thứ
    tiếng Rôman — Spanish 0,407 · Portuguese 0,404 · Italian 0,395.

    Test này neo sự thật đó lại, để lần sau ai muốn nới ngưỡng thì biết phải
    nhìn lát nào.
    """
    tops = sorted(((max(vietnamese_syllable_share(t) for t in texts), lang)
                   for lang, texts in slices.items() if lang != "Vietnamese"),
                  reverse=True)[:3]
    assert {lang for _, lang in tops} == {"Spanish", "Portuguese", "Italian"}
    assert vietnamese_syllable_share(
        "\n".join(slices["Indonesian"])) < 0.15, "Indonesian phải là lát dễ"
