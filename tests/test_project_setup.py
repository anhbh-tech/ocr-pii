"""Kiểm hạ tầng dự án — chạy TRƯỚC khi viết logic OCR.

Không phải test cho vui. Mỗi test ở đây canh một thứ đã từng hỏng trong
`refiny_engine` và làm hỏng cả chuỗi công việc phía sau:

  * đường dẫn cắm cứng của máy cũ  → test skip im lặng, không ai biết
  * dữ liệu khách lọt vào git      → không gỡ được khỏi lịch sử
  * phụ thuộc thiếu                → lỗi hiện ra giữa lúc đo, mất cả mẻ
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_core_dependencies_import():
    """Phụ thuộc lõi phải nạp được.

    Đặt ở đây để lỗi thiếu gói hiện ra NGAY, chứ không phải giữa một mẻ đo
    kéo dài hàng chục phút rồi mất toàn bộ kết quả.
    """
    import numpy
    import PIL
    import pymupdf

    assert pymupdf.__doc__, "pymupdf nạp được nhưng không có metadata"
    assert numpy.__version__
    assert PIL.__version__


def test_pymupdf_is_imported_by_its_real_name_without_warnings():
    """`import pymupdf`, KHÔNG phải `import fitz`.

    Tên `fitz` đã lỗi thời từ PyMuPDF 1.24 và sẽ bị bỏ. Nó vẫn chạy, nhưng in
    `DeprecationWarning` ở mọi lệnh gọi — đủ để lấp mất cảnh báo thật trong
    log của một mẻ đo dài.
    """
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        import pymupdf  # noqa: F401  — không được ném cảnh báo


@pytest.mark.parametrize("folder", [
    "data/gold/images",
    "data/gold/truth",
    "data/benchmarks",
    "reports",
])
def test_data_folders_exist(folder):
    """Thư mục dữ liệu phải có sẵn.

    Nếu thiếu, script tải benchmark sẽ ghi sang chỗ khác — thường là thư mục
    hiện hành — và dữ liệu khách rơi ra ngoài vùng được bảo vệ.
    """
    assert (ROOT / folder).is_dir(), f"thiếu thư mục {folder}"


@pytest.mark.parametrize("folder", ["data", "data/gold", "data/gold/images",
                                    "data/gold/truth"])
def test_client_data_folders_are_private(folder):
    """Thư mục chứa tài liệu khách phải là 700 (chỉ chủ sở hữu đọc được).

    `data/gold/` giữ tài liệu THẬT của khách hàng cùng bản gõ tay. Quyền mặc
    định 755 cho phép mọi tài khoản trên máy đọc được.
    """
    mode = (ROOT / folder).stat().st_mode & 0o777
    assert mode == 0o700, f"{folder} có quyền {oct(mode)}, phải là 0o700"


@pytest.mark.skipif(shutil.which("git") is None, reason="không có git")
@pytest.mark.parametrize("path", [
    "data/gold/images/anh-khach.jpg",
    "data/gold/truth/ban-go-tay.txt",
    "data/benchmarks/mdpbench/trang.png",
    "reports/ket-qua.json",
])
def test_git_refuses_to_track_client_data(path, tmp_path):
    """git phải TỪ CHỐI theo dõi mọi thứ trong `data/` và `reports/`.

    Đây là test quan trọng nhất tệp này. Một lần commit nhầm là tài liệu khách
    nằm vĩnh viễn trong lịch sử git — xoá ở commit sau không gỡ được, phải viết
    lại toàn bộ lịch sử.

    Kiểm bằng `git check-ignore` trên đường dẫn giả lập: hỏi thẳng git chứ
    không đọc `.gitignore` rồi tự suy luận. Không tạo tệp thật, nên test này
    an toàn kể cả khi có dữ liệu khách trong thư mục.
    """
    r = subprocess.run(["git", "check-ignore", "-q", path],
                       cwd=ROOT, capture_output=True)
    assert r.returncode == 0, (
        f"git KHÔNG chặn {path!r} — dữ liệu khách có thể lọt vào lịch sử git")


def test_gitignore_blocks_the_data_folder_itself():
    """Chặn cả thư mục `data/`, không chỉ từng phần con.

    Chặn lẻ từng thư mục con để lại lỗ: thư mục mới thêm sau này (ví dụ
    `data/scratch/`) sẽ không được chặn, và không ai nhớ ra cho tới khi muộn.
    """
    txt = (ROOT / ".gitignore").read_text(encoding="utf-8")
    lines = {l.strip() for l in txt.splitlines() if l.strip()
             and not l.strip().startswith("#")}
    assert "data/" in lines, "`.gitignore` phải chặn nguyên thư mục `data/`"
    assert "reports/" in lines, "`.gitignore` phải chặn `reports/`"


def test_no_absolute_home_paths_are_hardcoded_in_source():
    """Mã nguồn KHÔNG được cắm cứng đường dẫn tuyệt đối của một máy.

    Bài học thật từ `refiny_engine`: `tests/test_doc_class.py` cắm cứng
    `/home/anhbh/.private/refiny-corpus/...` — đường dẫn của một devbox Linux
    đã ngừng chạy. Trên máy hiện tại nó không tồn tại, nên hai test SKIP IM
    LẶNG và chưa từng chạy ở đây. Báo cáo vẫn xanh suốt nhiều tháng, còn lưới
    canh thì không có.

    Đường dẫn phải lấy từ cấu hình hoặc tính tương đối từ gốc dự án.
    """
    offenders = []
    for py in (ROOT / "src").rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="ignore")
        for bad in ("/Users/", "/home/"):
            if bad in text:
                offenders.append(f"{py.relative_to(ROOT)}: {bad}")
    assert not offenders, "đường dẫn tuyệt đối bị cắm cứng: " + ", ".join(offenders)
