"""Chọn một tài liệu THẬT trong kho để test giao diện chạy trên nó.

Tách riêng khỏi tệp test vì cả fixture lẫn một test cần gọi, và vì việc "kho
rỗng thì bỏ qua" phải trả lời cùng một câu ở mọi chỗ hỏi.
"""
from __future__ import annotations

import json
from pathlib import Path


def mot_doc_co_anh(it_nhat_trang: int = 1) -> str | None:
    """doc_id đầu tiên CÓ ảnh trang đã render, hoặc None nếu kho rỗng.

    Đòi ảnh trang chứ không phải tài liệu bất kỳ: docx/xlsx dựng bằng HTML,
    không có `#imgWrap` để đo bề rộng, nên chúng không kiểm được thứ các test
    này cần kiểm.

    `it_nhat_trang=2` để lấy tài liệu NHIỀU trang — cần cho test chuyển trang,
    mà phần lớn tài liệu trong kho chỉ có một trang.
    """
    from ocr_lab.ade_store import DEFAULT_STORE

    goc = Path(DEFAULT_STORE)
    if not goc.is_dir():
        return None
    for meta in sorted(goc.glob("*/meta.json")):
        try:
            d = json.loads(meta.read_text("utf-8"))
        except Exception:
            continue
        if len(d.get("pages") or ()) < it_nhat_trang:
            continue
        # Ảnh phải có THẬT trên đĩa: meta ghi `pages` cho cả docx, và có
        # thư mục `pages/` rỗng còn sót lại từ những lần chạy hỏng.
        # Không khoá đuôi tệp — kho hiện dùng .jpg, các bản trước dùng .png.
        pages = meta.parent / "pages"
        if len([f for f in pages.glob("*") if f.is_file()]) < it_nhat_trang:
            continue
        return meta.parent.name
    return None
