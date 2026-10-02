"""Kiểm hạ tầng gold set — canh dữ liệu khách và canh tính hợp lệ của phép đo.

Hai nhóm rủi ro khác nhau, cùng nghiêm trọng:

  * **rò rỉ** — tài liệu thật của khách (căn cước công dân, biên lai ngân
    hàng) lọt vào git hoặc để quyền đọc công khai;
  * **xanh giả** — gold set trông đầy đủ nhưng thực ra là đầu ra của chính
    engine đang được chấm, nên mọi bảng điểm sau đều vô nghĩa.

Nhóm thứ hai nguy hiểm hơn vì nó không gây ra sự cố nào — chỉ cho ra những
con số đẹp và sai.
"""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "data" / "gold"

pytestmark = pytest.mark.skipif(
    not (GOLD / "manifest.json").exists(),
    reason="chưa dựng gold set — chạy `uv run python scripts/build_gold_set.py`")


@pytest.fixture(scope="module")
def manifest():
    import json
    return json.loads((GOLD / "manifest.json").read_text(encoding="utf-8"))


# ── chống rò rỉ ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sub", ["", "images", "draft", "truth"])
def test_every_gold_folder_is_owner_only(sub):
    """700 trên MỌI thư mục, kể cả `draft/`.

    `draft/` dễ bị bỏ quên vì nghe như dữ liệu tạm. Nhưng bản nháp chứa NGUYÊN
    VĂN nội dung ảnh — số căn cước, số tài khoản — nên nó nhạy cảm ngang ảnh
    gốc.
    """
    d = GOLD / sub if sub else GOLD
    if not d.exists():
        pytest.skip(f"chưa có {d.name}")
    mode = d.stat().st_mode & 0o777
    assert mode == 0o700, f"{d.name} có quyền {oct(mode)}"


@pytest.mark.parametrize("path", [
    "data/gold/images/cccd.jpg",
    "data/gold/draft/cccd.txt",
    "data/gold/truth/cccd.txt",
    "data/gold/manifest.json",
])
def test_git_refuses_to_track_any_gold_file(path):
    """Một lần commit nhầm là dữ liệu nằm vĩnh viễn trong lịch sử git."""
    r = subprocess.run(["git", "check-ignore", "-q", path],
                       cwd=ROOT, capture_output=True)
    assert r.returncode == 0, f"git KHÔNG chặn {path}"


def test_the_manifest_records_relative_paths_only(manifest):
    """Không lưu đường dẫn tuyệt đối của kho.

    Vừa lộ cấu trúc thư mục máy, vừa vô dụng khi chuyển máy — và chính
    manifest lại là tệp dễ bị chép đi chép lại nhất.
    """
    for item in manifest:
        src = item["source"]
        assert not src.startswith("/"), f"đường dẫn tuyệt đối: {src}"
        assert "/Users/" not in src and "/home/" not in src


def test_no_client_content_leaks_into_tracked_source():
    """Mã nguồn và script KHÔNG được chứa nội dung tài liệu khách.

    Ca thật dễ mắc: dán một đoạn văn bản OCR vào docstring hoặc test làm ví
    dụ. Nó trông vô hại nhưng là dữ liệu khách nằm trong git.
    """
    import re

    # Số căn cước 12 chữ số, số tài khoản 9+ chữ số liền.
    suspicious = re.compile(r"\b\d{9,}\b")
    for folder in ("src", "scripts", "tests"):
        for py in (ROOT / folder).rglob("*.py"):
            text = py.read_text(encoding="utf-8", errors="ignore")
            for m in suspicious.finditer(text):
                tok = m.group(0)
                # Dãy chữ số TĂNG DẦN liên tiếp ("0123456789") là bảng ký tự
                # hoặc ví dụ tự soạn, không phải số thật. Dùng dấu hiệu CẤU
                # TRÚC thay vì nới danh sách ngoại lệ theo từng ca — danh sách
                # ngoại lệ dài dần sẽ dần vô hiệu hoá cả phép kiểm.
                if all(int(b) == int(a) + 1 for a, b in zip(tok, tok[1:])):
                    continue
                line = text[:m.start()].count("\n") + 1
                pytest.fail(f"{py.relative_to(ROOT)}:{line} có chuỗi số dài "
                            f"{tok!r} — có phải dữ liệu khách không?")


# ── chống xanh giả ──────────────────────────────────────────────────────────

def test_truth_files_are_not_copies_of_the_vision_draft(manifest):
    """CANH LỖI NGUY HIỂM NHẤT TỆP NÀY.

    Nếu bản nháp Vision bị chép sang thư mục truth cho nhanh, ta sẽ chấm điểm
    Apple Vision bằng chính đầu ra của Apple Vision — ra CER 0,000 hoàn hảo,
    và mọi so sánh engine sau đó đều lệch theo hướng có lợi cho Vision.

    Đây là lý do `build_gold_set.py` tạo tệp truth RỖNG thay vì chép sẵn.
    """
    copied = []
    for item in manifest:
        stem = Path(item["gold_name"]).stem
        t, d = GOLD / "truth" / f"{stem}.txt", GOLD / "draft" / f"{stem}.txt"
        if not (t.exists() and d.exists()):
            continue
        tt, dd = t.read_text("utf-8").strip(), d.read_text("utf-8").strip()
        if tt and dd and tt == dd:
            copied.append(stem)
    assert not copied, (
        f"{len(copied)} tệp truth y hệt bản nháp Vision: {copied[:5]} — "
        f"phép đo sẽ chấm Vision bằng chính Vision")


def test_every_image_has_a_truth_file_even_if_empty(manifest):
    """Thiếu tệp truth thì ảnh đó bị bỏ qua IM LẶNG khi đo."""
    missing = [item["gold_name"] for item in manifest
               if not (GOLD / "truth" / f"{Path(item['gold_name']).stem}.txt")
               .exists()]
    assert not missing, f"thiếu tệp truth cho: {missing[:5]}"


def test_the_gold_set_covers_the_two_matters_that_lost_everything(manifest):
    """Gold set phải phủ đúng hai hồ sơ là lý do dự án tồn tại.

    Một hồ sơ mất 6/6 ảnh, hồ sơ kia mất 13/13. Nếu gold set không có chúng
    thì nó đang đo một bài toán khác. Hai hồ sơ đó đọc từ cấu hình ngoài cây
    git (`build_gold_set.GOLD_CONFIG`), vì tên thư mục hồ sơ là tên khách.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "build_gold_set", ROOT / "scripts" / "build_gold_set.py")
    bgs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bgs)
    if not bgs.TARGET_MATTERS:
        pytest.skip(f"không có {bgs.GOLD_CONFIG}")
    want = {m.split(".")[0].strip() for m in bgs.TARGET_MATTERS}
    codes = {item["gold_name"].split("__")[0] for item in manifest}
    assert want <= codes, f"thiếu {sorted(want - codes)}, chỉ thấy {codes}"


def test_product_photos_are_represented(manifest):
    """Ảnh sản phẩm là phép thử GẮT NHẤT và dễ bị bỏ qua nhất.

    Chúng gần như không có chữ, nên ground truth là chuỗi rỗng hoặc vài từ.
    Tesseract bịa ra 200–2 688 ký tự rác từ những ảnh này — lỗi "sinh chữ từ
    nhiễu" mà không chỉ số nào bắt được nếu gold set không có ảnh loại đó.
    """
    kinds = [item["kind"] for item in manifest]
    assert kinds.count("ảnh sản phẩm") >= 5, (
        "gold set cần đủ ảnh sản phẩm để bắt lỗi bịa chữ từ nhiễu")
