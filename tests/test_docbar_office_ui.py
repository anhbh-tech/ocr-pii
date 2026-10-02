"""Thanh tài liệu với docx/xlsx — nhánh dựng bằng HTML, không có ảnh trang.

Tách khỏi `test_docbar_ui.py` vì đây là NGUỒN ZOOM KHÁC (`nguonHtml` trong
app.js): nó phóng bằng cỡ chữ chứ không bằng bề rộng ảnh. Cùng một thanh nút
gọi vào hai cài đặt khác nhau, nên một nhánh chạy không nói gì về nhánh kia —
đúng kiểu hỏng mà test chỉ chạy trên PDF sẽ bỏ lọt.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="chưa cài playwright"
).sync_playwright


def _mot_doc_office() -> str | None:
    """doc_id của một docx/xlsx đã chạy, hoặc None."""
    from ocr_lab.ade_store import DEFAULT_STORE

    goc = Path(DEFAULT_STORE)
    if not goc.is_dir():
        return None
    for meta in sorted(goc.glob("*/meta.json")):
        try:
            d = json.loads(meta.read_text("utf-8"))
        except Exception:
            continue
        if str(d.get("source", "")).lower().endswith((".docx", ".xlsx")):
            return meta.parent.name
    return None


@pytest.fixture(scope="module")
def web_office():
    doc = _mot_doc_office()
    if doc is None:
        pytest.skip("kho không có docx/xlsx nào đã chạy")

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        cong = s.getsockname()[1]

    p = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "serve_review.py"),
         "--port", str(cong)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", cong), 0.2):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.skip("server không lên kịp")

        with sync_playwright() as pw:
            try:
                br = pw.chromium.launch()
            except Exception as e:
                pytest.skip(f"không mở được chromium: {e}")
            pg = br.new_page(viewport={"width": 1500, "height": 950})
            pg.goto(f"http://127.0.0.1:{cong}/", wait_until="networkidle")
            pg.evaluate("id => window.moDoc(id)", doc)
            pg.wait_for_selector("#docHtml:not([hidden])", timeout=15000)
            pg.wait_for_timeout(400)
            yield pg
            br.close()
    finally:
        p.terminate()
        p.wait(timeout=10)


def test_docx_co_du_duong_dan_va_nut_zoom(web_office):
    """docx cũng phải có thanh giống PDF — không được thiếu nút nào.

    Nửa số tệp trong kho là docx. Nếu nút phóng to chỉ hiện với PDF thì với
    người dùng, tính năng này coi như thỉnh thoảng biến mất.
    """
    assert web_office.locator("#docPath .pthFile").inner_text().endswith(
        (".docx", ".xlsx"))
    assert web_office.locator("#zoomGrp").is_visible()
    assert web_office.locator("#zoomLabel").inner_text() == "100%"


def test_docx_phong_to_lam_chu_to_that(web_office):
    """Bấm + phải làm CHỮ to lên thật, không chỉ đổi con số trên nhãn."""
    co = lambda: web_office.evaluate(                              # noqa: E731
        "() => parseFloat(getComputedStyle(document.getElementById('docHtml'))"
        ".fontSize)")

    c0 = co()
    web_office.click("#zoomIn")
    web_office.wait_for_timeout(250)
    assert co() > c0 + 0.5, f"bấm + mà cỡ chữ không đổi: {c0}"
    assert web_office.locator("#zoomLabel").inner_text() == "125%"

    web_office.click("#zoomOut")
    web_office.wait_for_timeout(250)
    assert co() == pytest.approx(c0, abs=0.2)
    assert web_office.locator("#zoomLabel").inner_text() == "100%"


def test_docx_khong_hien_o_hinh_vo_o_dai_files(web_office):
    """docx không có ảnh trang thì dải Files phải ẨN, không hiện ô hình vỡ.

    `meta.pages` vẫn ghi `[{page:1}]` cho docx nên vòng lặp dựng thumbnail
    vẫn chạy, thẻ <img> trỏ vào endpoint trả 404, và người dùng thấy một ô
    vỡ ngay dưới tài liệu đang mở bình thường — trông như tệp hỏng.
    """
    assert web_office.locator("#files").is_hidden(), \
        "docx vẫn hiện dải Files (ô hình vỡ)"
    assert not web_office.evaluate("""() => [...document.querySelectorAll(
      '#filesStrip img')].some(i => i.complete && i.naturalWidth === 0)""")


def test_docx_phong_to_khong_sinh_cuon_ngang(web_office):
    """Phóng chữ thì đoạn văn xuống dòng lại, không đẩy ra thanh cuộn ngang.

    Đây là lý do nhánh HTML phóng bằng cỡ chữ thay vì `transform: scale()`:
    scale làm dòng dài ra đúng theo tỉ lệ và người đọc phải kéo ngang từng
    dòng một.
    """
    for _ in range(3):
        web_office.click("#zoomIn")
    web_office.wait_for_timeout(400)

    tran = web_office.evaluate("""() => {
      const s = document.getElementById('stage');
      return s.scrollWidth - s.clientWidth;
    }""")
    # Bảng xlsx rộng cố định vẫn có thể tràn chút ít; chỉ chặn tràn do chữ.
    assert tran < 40, f"phóng chữ xong sinh cuộn ngang {tran}px"
