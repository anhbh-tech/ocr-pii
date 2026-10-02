"""Chép đường dẫn và kéo-để-di-chuyển: kiểm trong Chromium THẬT.

Hai tính năng này chỉ hỏng trong ngữ cảnh thật nên không mô phỏng được:

  * `navigator.clipboard` là `undefined` trên HTTP không phải localhost
    (không phải "secure context"). Test ở `127.0.0.1` sẽ XANH NHẦM vì
    localhost được coi là an toàn — phải trỏ đúng địa chỉ tailnet.

  * Kéo-để-di-chuyển cần sự kiện chuột thật có toạ độ; gọi hàm trực tiếp
    không chứng minh được chuỗi pointerdown→move→up hoạt động.

Chạy:  .venv/bin/python -m pytest tests/test_viewer_drag_ui.py -q
Bỏ qua khi không có server (CI, máy không vào tailnet).
"""
from __future__ import annotations

import os
import urllib.request

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

BASE = os.environ.get("OCRLAB_URL", "http://100.101.172.22:8811")


def _co_server() -> bool:
    try:
        with urllib.request.urlopen(f"{BASE}/api/version", timeout=3) as r:
            return r.status == 200
    except Exception:       # noqa: BLE001 — không có server thì bỏ qua cả tệp
        return False


pytestmark = pytest.mark.skipif(
    not _co_server(), reason=f"không có server ở {BASE}")


@pytest.fixture(scope="module")
def trang():
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        pg = br.new_page(viewport={"width": 1600, "height": 1000})
        loi: list[str] = []
        pg.on("pageerror", lambda e: loi.append(str(e)))
        pg.goto(BASE, wait_until="networkidle")
        yield pg, loi
        br.close()


def _mo(pg, doc_id: str) -> None:
    pg.evaluate("id => window.moDoc(id)", doc_id)
    pg.wait_for_timeout(2500)


def _phong_to(pg, lan: int = 4) -> None:
    """Phóng to bằng nút thật cho tới khi trang tràn khung."""
    for _ in range(lan):
        pg.locator("#zoomIn").click()
        pg.wait_for_timeout(150)
    pg.wait_for_timeout(500)


def test_ngu_canh_khong_an_toan_dung_la_ca_dang_kiem(trang):
    """Chốt tiền đề: nếu trang này là secure context thì test dưới vô nghĩa.

    Bản lỗi chỉ lộ ra khi `navigator.clipboard` vắng mặt. Chạy bộ test này qua
    HTTPS hay localhost sẽ xanh cả trước lẫn sau khi sửa — nên phải khẳng định
    ngữ cảnh đang kiểm đúng là ngữ cảnh người dùng gặp.
    """
    pg, _ = trang
    r = pg.evaluate("({s: window.isSecureContext, c: !!navigator.clipboard})")
    assert r["s"] is False, "phải test qua HTTP tailnet, không phải localhost"
    assert r["c"] is False, "ca đang kiểm là ca KHÔNG có navigator.clipboard"


def test_bam_duong_dan_van_chep_duoc_khi_khong_co_clipboard_api(trang):
    """Bấm đường dẫn phải chép thật, dù `navigator.clipboard` không tồn tại.

    LỖI GỐC người dùng báo: bấm vào đường dẫn của
    `NH9001.US_Tin nhan ket qua tra cuu_190925.pdf` không có phản ứng gì.
    Nguyên nhân: `navigator.clipboard?.writeText(...)` — toán tử `?.` nuốt
    luôn lệnh chép khi API vắng mặt, không lỗi, không phản hồi.
    """
    pg, _ = trang
    _mo(pg, "b749be9c71f6f82b")

    o = pg.locator(".docPath")
    assert o.count() == 1, "thanh tài liệu phải có đúng một ô đường dẫn"
    o.click()
    pg.wait_for_timeout(400)

    lop = o.get_attribute("class") or ""
    assert "daChep" in lop, (
        f"phải báo 'đã chép'; class hiện tại = {lop!r}. "
        "Nếu thấy 'chepLoi' thì đường lùi execCommand cũng hỏng.")


def test_bao_loi_ra_mat_khi_chep_that_bai(trang):
    """Chép hỏng phải NÓI ra, không im lặng như bản cũ.

    Giả lập bằng cách chặn cả hai đường: xoá `navigator.clipboard` và ép
    `execCommand` trả về false.
    """
    pg, _ = trang
    _mo(pg, "b749be9c71f6f82b")
    pg.evaluate("document.execCommand = () => false")

    o = pg.locator(".docPath")
    o.click()
    pg.wait_for_timeout(400)
    assert "chepLoi" in (o.get_attribute("class") or ""), (
        "chép hỏng mà không báo gì thì người dùng bấm mãi không biết vì sao")

    pg.reload(wait_until="networkidle")       # trả lại execCommand thật


def test_keo_chuot_trai_di_chuyen_duoc_tai_lieu(trang):
    """Giữ chuột trái trong vùng xem rồi kéo thì tài liệu phải trượt theo."""
    pg, _ = trang
    _mo(pg, "b749be9c71f6f82b")

    _phong_to(pg)

    v = pg.locator(".stage")
    truoc = pg.evaluate(
        "() => {const s=document.querySelector('.stage');"
        "return {t: s.scrollTop, l: s.scrollLeft};}")

    h = v.bounding_box()
    assert h, "không tìm thấy vùng cuộn"
    pg.mouse.move(h["x"] + h["width"] / 2, h["y"] + h["height"] / 2)
    pg.mouse.down()
    # Nhiều bước nhỏ: một bước nhảy đơn lẻ không giống thao tác người thật và
    # có thể lọt qua ngưỡng chống-rung 3px theo cách không mong muốn.
    for i in range(1, 7):
        pg.mouse.move(h["x"] + h["width"] / 2 - i * 25,
                      h["y"] + h["height"] / 2 - i * 20)
    pg.mouse.up()
    pg.wait_for_timeout(300)

    sau = pg.evaluate(
        "() => {const s=document.querySelector('.stage');"
        "return {t: s.scrollTop, l: s.scrollLeft};}")
    assert sau["t"] > truoc["t"] or sau["l"] > truoc["l"], (
        f"kéo xong tài liệu không nhúc nhích: {truoc} → {sau}")


def test_bam_khong_keo_van_chon_duoc_chunk(trang):
    """Bấm gọn (không kéo) phải giữ nguyên chức năng chọn chunk.

    Bản chặn-click sau khi kéo dễ chặn nhầm cú bấm thường, làm mất hẳn thao
    tác chọn vùng trên trang — tính năng chính của công cụ soát.
    """
    pg, _ = trang
    _mo(pg, "b749be9c71f6f82b")
    _phong_to(pg)

    v = pg.locator(".stage")
    h = v.bounding_box()
    assert h, "không tìm thấy vùng cuộn"
    pg.mouse.move(h["x"] + h["width"] / 2, h["y"] + h["height"] / 2)
    pg.mouse.down()
    pg.mouse.up()                      # bấm gọn, không di chuyển
    pg.wait_for_timeout(200)

    # Cú bấm kế tiếp KHÔNG được bị nuốt: kiểm bằng một cờ tự gắn.
    pg.evaluate("window.__thu = 0;"
                "document.querySelector('.stage')"
                ".addEventListener('click', () => window.__thu++)")
    pg.mouse.click(h["x"] + h["width"] / 2, h["y"] + h["height"] / 2)
    pg.wait_for_timeout(200)
    assert pg.evaluate("window.__thu") == 1, (
        "cú bấm sau khi bấm-gọn bị nuốt — bộ chặn click đang chặn nhầm")


def test_khong_co_loi_js_trong_suot_qua_trinh(trang):
    """Không lỗi JS nào trong suốt các thao tác trên."""
    _, loi = trang
    assert loi == [], f"có lỗi JS: {loi}"


def test_con_tro_doi_thanh_ban_tay_nam_khi_dang_keo(trang):
    """Đang kéo thì con trỏ phải là `grabbing`, không còn `grab`.

    Không có phản hồi thị giác thì người dùng không biết thao tác đã bắt đầu —
    và bản đầu đúng là vẫn hiện `grab` suốt lúc kéo vì quy tắc `:has(...)` có
    cùng độ đặc hiệu với `.dangKeo`.
    """
    pg, _ = trang
    _mo(pg, "b749be9c71f6f82b")
    _phong_to(pg)

    khung = pg.locator(".stage")
    h = khung.bounding_box()
    assert h, "không tìm thấy vùng xem"
    cx, cy = h["x"] + h["width"] / 2, h["y"] + h["height"] / 2

    assert pg.evaluate(
        "getComputedStyle(document.querySelector('.stage')).cursor") == "grab"

    pg.mouse.move(cx, cy)
    pg.mouse.down()
    for i in range(1, 6):
        pg.mouse.move(cx - i * 30, cy - i * 22)
    dang = pg.evaluate(
        "getComputedStyle(document.querySelector('.stage')).cursor")
    pg.mouse.up()
    pg.wait_for_timeout(200)

    assert dang == "grabbing", f"đang kéo mà con trỏ vẫn là {dang!r}"
    assert pg.evaluate(
        "getComputedStyle(document.querySelector('.stage')).cursor") == "grab", (
        "thả chuột rồi con trỏ phải trở lại 'grab'")
