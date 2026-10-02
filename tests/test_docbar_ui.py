"""Thanh tài liệu ở cột giữa: đường dẫn tệp + nút phóng to.

Chạy web thật trong trình duyệt thật (Playwright) thay vì đọc mã nguồn bằng
regex như phần còn lại của bộ test. Lý do: cả hai tính năng ở đây chỉ hỏng
theo kiểu "có mặt trong mã nhưng không chạy" — nguồn zoom chưa đăng ký, phần
trăm đứng yên sau khi bấm, ảnh không đổi bề rộng vì một luật CSS `max-width`
ở tệp khác. Kiểm bằng chuỗi ký tự thì cả ba lỗi đó đều lọt.

Bỏ qua khi thiếu playwright/chromium hoặc kho hồ sơ rỗng, để `make check`
trên máy chưa cài vẫn chạy được.
"""
from __future__ import annotations

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


def _cong_ranh() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def web():
    """Server thật + một trang thật, dùng chung cho cả module."""
    from ade_store_probe import mot_doc_co_anh  # type: ignore

    doc = mot_doc_co_anh()
    if doc is None:
        pytest.skip("kho rỗng — không có tài liệu nào để mở")

    cong = _cong_ranh()
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
            except Exception as e:                       # chưa tải chromium
                pytest.skip(f"không mở được chromium: {e}")
            pg = br.new_page(viewport={"width": 1500, "height": 950})
            pg.goto(f"http://127.0.0.1:{cong}/", wait_until="networkidle")
            pg.evaluate("id => window.moDoc?.(id)", doc)
            pg.wait_for_selector("#imgWrap:not([hidden]) img", timeout=15000)
            pg.wait_for_function(
                "() => document.querySelector('#imgWrap img')?.naturalWidth > 0")
            pg.wait_for_timeout(300)
            yield pg
            br.close()
    finally:
        p.terminate()
        p.wait(timeout=10)


def test_duong_dan_hien_du_thu_muc_va_ten_tep(web):
    """Thanh phải nói ĐANG XEM TỆP NÀO, gồm cả thư mục.

    Chỉ hiện tên tệp là không đủ: kho có nhiều `CCCD.pdf` ở các hồ sơ khác
    nhau, và người soát không phân biệt được chúng.
    """
    o = web.locator("#docPath")
    assert o.is_visible()
    ten = o.locator(".pthFile").inner_text().strip()
    assert ten and "/" not in ten
    assert "." in ten, f"tên tệp phải có đuôi, nhận: {ten!r}"

    # `title` mang đường dẫn TUYỆT ĐỐI — phần hiển thị có thể bị cắt bớt.
    assert ten in o.get_attribute("title")
    assert o.get_attribute("title").startswith("/")


def test_ten_tep_khong_bi_cat_khi_cot_hep(web):
    """Cột hẹp lại thì phần bị cắt phải là THƯ MỤC, không phải tên tệp.

    Đây là lỗi kinh điển của `text-overflow: ellipsis` đặt nhầm chỗ: thanh
    trông vẫn gọn, nhưng thứ duy nhất người dùng cần đọc thì mất.
    """
    truoc = web.locator("#docPath .pthFile").inner_text()
    web.set_viewport_size({"width": 1020, "height": 950})
    web.wait_for_timeout(200)
    try:
        o = web.locator("#docPath .pthFile")
        assert o.inner_text() == truoc
        # Không bị cắt: bề rộng cuộn bằng bề rộng hiển thị.
        assert o.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
    finally:
        web.set_viewport_size({"width": 1500, "height": 950})
        web.wait_for_timeout(200)


def test_nut_zoom_hien_va_doi_that_kich_thuoc_anh(web):
    """[−] 100% [+] phải CÓ và phải làm ảnh to/nhỏ thật.

    Kiểm bề rộng thật của ảnh chứ không chỉ kiểm nhãn phần trăm: nhãn đổi mà
    ảnh đứng yên là đúng cái lỗi `max-width: 100%` từng gây ra, và nó không
    để lại dấu vết nào trong mã JS.

    Bắt đầu từ 100% chứ không từ mức vừa-khung. Mức vừa khung là một số lẻ
    (60%, 67%…) không nằm trên nấc thang, nên từ đó bấm + rồi − ra 50% chứ
    không quay lại 60% — giống hệt Preview và Chrome, không phải lỗi.
    """
    nhan = web.locator("#zoomLabel")
    assert nhan.is_visible(), "không thấy nút zoom"
    assert nhan.inner_text().endswith("%")

    rong = lambda: web.evaluate(                                   # noqa: E731
        "() => document.querySelector('#imgWrap img').getBoundingClientRect().width")

    web.click("#zoomLabel")            # về đúng nấc 100%
    web.wait_for_timeout(250)
    r0 = rong()

    web.click("#zoomIn")
    web.wait_for_timeout(250)
    assert rong() > r0 + 1, f"bấm + mà ảnh không to ra: {r0} → {rong()}"
    assert nhan.inner_text() == "125%"

    web.click("#zoomOut")
    web.wait_for_timeout(250)
    assert rong() == pytest.approx(r0, abs=2), "bấm − không trả về nấc cũ"
    assert nhan.inner_text() == "100%"


def test_zoom_dung_lai_o_hai_dau_thang(web):
    """Bấm − mãi không được co về 0, bấm + mãi không được phóng vô hạn.

    Không chặn thì một cú giữ phím cho ra trang bé bằng hạt gạo hoặc một
    canvas vài chục nghìn điểm ảnh làm treo tab.
    """
    for _ in range(12):
        web.click("#zoomOut")
    web.wait_for_timeout(300)
    assert web.locator("#zoomLabel").inner_text() == "25%"

    for _ in range(14):
        web.click("#zoomIn")
    web.wait_for_timeout(300)
    assert web.locator("#zoomLabel").inner_text() == "400%"


def test_bam_nhan_tra_ve_100_phan_tram_that(web):
    """100% = một điểm ảnh tài liệu ăn một điểm ảnh màn hình.

    Không phải "vừa khung". Nếu định nghĩa trôi đi thì con số trên thanh trở
    thành vô nghĩa với người đang căn kích thước con dấu hay chữ ký.
    """
    web.click("#zoomLabel")
    web.wait_for_timeout(250)
    assert web.locator("#zoomLabel").inner_text() == "100%"
    tl = web.evaluate("""() => {
      const i = document.querySelector('#imgWrap img');
      return i.getBoundingClientRect().width / i.naturalWidth;
    }""")
    assert tl == pytest.approx(1.0, abs=0.02)


def test_mo_tai_lieu_thi_tu_thu_cho_vua_cot(web):
    """Mở ra phải THẤY CẢ TRANG, không phải một góc trang.

    Ảnh scan rộng ~1275px còn cột giữa chỉ ~700px: để nguyên 100% thì người
    dùng mở tệp ra và thấy góc trên bên trái, phải cuộn ngang mới biết mình
    đang xem gì.
    """
    web.reload(wait_until="networkidle")
    from ade_store_probe import mot_doc_co_anh  # type: ignore
    web.evaluate("id => window.moDoc?.(id)", mot_doc_co_anh())
    web.wait_for_selector("#imgWrap:not([hidden]) img")
    web.wait_for_function(
        "() => document.querySelector('#imgWrap img')?.naturalWidth > 0")
    web.wait_for_timeout(500)

    tran = web.evaluate("""() => {
      const w = document.querySelector('#imgWrap');
      const s = document.getElementById('stage');
      return w.getBoundingClientRect().width - s.clientWidth;
    }""")
    assert tran <= 0, f"trang tràn ra ngoài cột {tran:.0f}px khi vừa mở"

    # ...nhưng KHÔNG được phóng lên quá kích thước thật.
    assert web.evaluate("""() => {
      const i = document.querySelector('#imgWrap img');
      return i.getBoundingClientRect().width / i.naturalWidth;
    }""") <= 1.01


def test_phong_to_thi_cuon_toi_duoc_mep_trai(web):
    """Phóng quá bề ngang cột thì mép TRÁI vẫn phải xem được.

    `justify-content: center` trên vùng cuộn đẩy phần thừa ra cả hai bên,
    nhưng cuộn chỉ với tới bên phải — mép trái mất hẳn, không cách nào lấy
    lại. Lỗi này chỉ lộ ra khi phóng to, nên rất dễ lọt.
    """
    for _ in range(4):
        web.click("#zoomIn")
    web.wait_for_timeout(400)

    lech = web.evaluate("""() => {
      const s = document.getElementById('stage');
      s.scrollLeft = 0;
      const w = document.querySelector('#imgWrap').getBoundingClientRect();
      return w.left - s.getBoundingClientRect().left;
    }""")
    assert lech >= -1, f"mép trái của trang bị cắt mất {-lech:.0f}px"


def test_chuyen_trang_khong_xoa_muc_phong_dang_dung(web):
    """Lật trang giữ nguyên mức phóng người dùng vừa chọn.

    Người soát phóng to để đọc chữ nhỏ rồi sang trang sau — bị trả về mức
    ban đầu là phải phóng lại từng trang một.
    """
    from ade_store_probe import mot_doc_co_anh  # type: ignore

    nhieu = mot_doc_co_anh(it_nhat_trang=2)
    if nhieu is None:
        pytest.skip("kho không có tài liệu nhiều trang")

    web.evaluate("id => window.moDoc(id)", nhieu)
    web.wait_for_function(
        "() => document.querySelector('#imgWrap img')?.naturalWidth > 0")
    web.wait_for_timeout(400)
    assert web.locator("#pager").is_visible(), "nhiều trang mà không có bộ lật"

    web.click("#zoomLabel")            # về mốc 100% cho chắc
    web.click("#zoomIn")
    web.wait_for_timeout(300)
    truoc = web.locator("#zoomLabel").inner_text()

    web.click("#nextPage")
    web.wait_for_timeout(700)
    assert web.locator("#pageLabel").inner_text().startswith("2 /")
    assert web.locator("#zoomLabel").inner_text() == truoc
