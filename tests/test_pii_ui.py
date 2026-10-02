"""Lớp tô thông tin nhạy cảm trong trang đối chiếu.

Chạy web thật trong trình duyệt thật, không đọc mã bằng regex. Lý do: cả ba
lỗi nguy hiểm nhất của tính năng này đều "có mặt trong mã mà không chạy" —
biến CSS viết sai tên nên vùng tô trong suốt, offset lệch sau khi escape HTML
nên tô trúng chữ bên cạnh, và bảng tổng kết đếm trên `state.chunks` rỗng.
Kiểm bằng chuỗi ký tự thì cả ba đều lọt.

Vì sao phải có test riêng cho phần này: tô SAI chỗ còn tệ hơn không tô. Người
soát tin vào màu, nên một vùng tô lệch hai ký tự sẽ khiến họ ký duyệt một
đoạn vẫn còn số căn cước thật.
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
    """Server thật + trang thật, mở sẵn một tài liệu CÓ CHỮ.

    Tài liệu ảnh thuần không chứng minh được gì: không có chữ thì không có gì
    để tô, và test sẽ xanh cả khi tính năng hỏng hoàn toàn.
    """
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
            pg.wait_for_timeout(800)

            docs = pg.locator(".docItem")
            if not docs.count():
                pytest.skip("kho rỗng — không có tài liệu nào để mở")

            for i in range(min(12, docs.count())):
                docs.nth(i).click()
                pg.wait_for_timeout(1800)
                if pg.locator(".chunk").count() >= 8:
                    break
            else:
                pytest.skip("không tìm được tài liệu đủ chữ để soát")

            yield pg
            br.close()
    finally:
        p.terminate()
        p.wait(timeout=10)


def _bat(pg):
    if not pg.locator("mark.pii").count():
        pg.locator("#tabPII").click()
        pg.wait_for_timeout(700)


def test_nut_bat_tat_lop_nhay_cam(web):
    """Mặc định TẮT, bấm thì bật, bấm lại thì sạch hoàn toàn.

    Mặc định phải tắt vì soát chính tả mới là việc thường ngày: bật sẵn thì
    màu tô che mất chính lỗi OCR mà người ta mở trang này để tìm.
    """
    assert web.locator("mark.pii").count() == 0, "lớp nhạy cảm không được bật sẵn"

    web.locator("#tabPII").click()
    web.wait_for_timeout(700)
    assert web.locator("mark.pii").count() > 0, "bật rồi mà không tô gì"
    assert web.locator("#piiPanel").count() == 1

    web.locator("#tabPII").click()
    web.wait_for_timeout(700)
    assert web.locator("mark.pii").count() == 0, "tắt rồi mà vùng tô còn sót"
    assert web.locator("#piiPanel").count() == 0, "tắt rồi mà bảng còn sót"


def test_vung_to_hien_ra_that_khong_trong_suot(web):
    """Vùng tô phải NHÌN THẤY được.

    Viết sai tên biến CSS (`--accent-bg` thay vì `--accent-dim`) thì trình
    duyệt bỏ qua cả dòng: thẻ `<mark>` vẫn có trong DOM, test đếm DOM vẫn
    xanh, mà trên màn hình không có gì. Nên phải đo MÀU THẬT sau khi tính.
    """
    _bat(web)
    m = web.locator("mark.pii").first
    st = m.evaluate(
        "e => { const c = getComputedStyle(e);"
        " return {mau: c.borderBottomColor, rong: c.borderBottomWidth,"
        "         kieu: c.borderBottomStyle, nen: c.backgroundColor,"
        "         chu: getComputedStyle(e.parentElement).color}; }")
    assert st["kieu"] != "none", "không có gạch chân"
    assert st["rong"] not in ("0px", ""), "gạch chân dày 0px"
    assert "rgba(0, 0, 0, 0)" not in st["mau"], f"gạch chân trong suốt: {st}"

    # Biến CSS viết sai tên KHÔNG làm mất gạch chân — `border-color` không hợp
    # lệ thì trình duyệt lấy `color` của chữ, nên vạch vẫn hiện, chỉ là cùng
    # màu chữ và mất hết ý nghĩa phân loại. Phải bắt đúng chỗ đó.
    assert st["mau"] != st["chu"], (
        f"gạch chân cùng màu chữ ({st['mau']}) — nhiều khả năng tên biến CSS "
        "sai nên trình duyệt rơi về `color` mặc định")


def test_hai_cach_xu_ly_phan_biet_duoc_khong_chi_bang_mau(web):
    """Bút danh và ẩn danh phải khác nhau ở KIỂU gạch, không chỉ ở màu.

    Đo màu thật trên chủ đề đang dùng: accent #f0883e và warn #d29922 có độ
    tương phản 1.0 — cùng độ sáng, nên in đen trắng hay mắt mù màu đỏ-lục thì
    hai loại trông y hệt nhau. Hệ quả không chấp nhận được: nhầm 'ẩn danh,
    mất vĩnh viễn' thành 'bút danh, hoàn nguyên được'.
    """
    _bat(web)
    kieu = web.evaluate(
        "() => {"
        " const g = s => { const e = document.querySelector(s);"
        "   return e ? getComputedStyle(e).borderBottomStyle : null; };"
        " return {p: g('mark.pii.pseudo'), a: g('mark.pii.anon')}; }")
    if kieu["p"] is None or kieu["a"] is None:
        pytest.skip("tài liệu này không có đủ cả hai loại để so")
    assert kieu["p"] != kieu["a"], (
        f"hai cách xử lý cùng kiểu gạch {kieu['p']!r} — chỉ khác màu là không đủ")


def test_bang_tong_ket_dem_dung_so_vung(web):
    """Số trong bảng phải KHỚP số vùng tô thật trên trang.

    Bảng đếm lại từ `state.chunks` còn vùng tô sinh trong lúc dựng HTML — hai
    đường đi khác nhau, lệch nhau là có thật. Con số sai thì người soát tưởng
    đã xử lý hết trong khi còn sót.
    """
    _bat(web)
    dau = web.locator("#piiPanel .pp-head").inner_text()
    so_bang = int(dau.split()[0])
    so_to = web.locator("mark.pii").count()
    assert so_bang == so_to, f"bảng nói {so_bang} vùng, trang tô {so_to} vùng"


def test_moi_vung_to_co_giai_thich_vi_sao(web):
    """Rê chuột phải nói ĐÂY LÀ GÌ và VÌ SAO, không chỉ tô màu câm.

    Người soát không nhớ nổi thang R/L/N; nếu màu không tự giải thích thì họ
    sẽ đoán, và đoán sai theo hướng dễ dãi.
    """
    _bat(web)
    tt = web.locator("mark.pii").first.get_attribute("title") or ""
    assert len(tt) > 40, f"tooltip quá sơ sài: {tt!r}"
    assert "bút danh hoá" in tt or "ẩn danh hoá" in tt, (
        f"tooltip không nói cách xử lý: {tt!r}")


def test_chu_giai_noi_ro_cai_nao_hoan_nguyen_duoc(web):
    """Khác biệt PHÁP LÝ giữa hai cách phải viết thẳng ra trên màn hình.

    Bút danh hoá còn hoàn nguyên được nên theo GDPR VẪN LÀ dữ liệu cá nhân;
    ẩn danh hoá thì không. Nhầm hai cái là nhầm nghĩa vụ pháp lý, nên không
    được để nó nằm trong tài liệu ngoài mà phải ở ngay cạnh vùng tô.
    """
    _bat(web)
    cg = web.locator("#piiPanel .pp-legend").inner_text()
    assert "hoàn nguyên được" in cg
    assert "KHÔNG hoàn nguyên" in cg


def test_khong_to_van_ban_khuon_mau(web):
    """Quốc hiệu, tiêu ngữ xuất hiện ở MỌI hồ sơ nên không chỉ về ai.

    Tô cả những thứ vô hại là cách nhanh nhất làm người soát mất tin vào màu
    và bắt đầu bỏ qua tất cả.
    """
    _bat(web)
    xau = web.evaluate(
        "() => [...document.querySelectorAll('mark.pii')]"
        ".map(e => e.textContent).filter(t =>"
        " t.includes('CỘNG HÒA') || t.includes('Độc lập'))")
    assert xau == [], f"tô nhầm văn bản khuôn mẫu: {xau}"


def test_khong_lam_vo_html_khi_van_ban_co_ky_tu_dac_biet(web):
    """Chữ `<`, `&` trong tài liệu không được biến thành thẻ HTML.

    Phải tìm PII trên văn bản THÔ rồi escape từng mảnh. Làm ngược lại thì
    '&' nở thành '&amp;' và mọi offset sau nó lệch 4 ký tự.
    """
    _bat(web)
    hong = web.evaluate(
        "() => [...document.querySelectorAll('.chunk')]"
        ".filter(e => e.innerHTML.includes('&amp;lt;')"
        "          || e.innerHTML.includes('&amp;amp;')).length")
    assert hong == 0, f"{hong} chunk bị escape hai lần"
