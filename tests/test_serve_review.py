

# ── mức phơi bày mạng ───────────────────────────────────────────────────

def test_khong_bao_gio_bind_0000():
    """Kho chứa hồ sơ khách hàng: 0.0.0.0 mở ra cả LAN (quán cà phê, văn
    phòng chung). Chỉ được phép loopback hoặc địa chỉ tailnet cụ thể."""
    import pathlib
    src = pathlib.Path(__file__).parent.parent / "scripts" / "serve_review.py"
    code = src.read_text("utf-8")
    # Chỉ tính chỗ thực sự gọi uvicorn, không tính docstring giải thích.
    run_line = [l for l in code.splitlines() if "uvicorn.run(" in l]
    assert run_line, "không tìm thấy lời gọi uvicorn.run"
    assert '"0.0.0.0"' not in "".join(run_line)


def test_tailnet_ip_tra_ve_none_khi_khong_co_tailscale(monkeypatch):
    """Không vào tailnet thì phải trả None để script dừng hẳn, chứ không
    im lặng rơi về 0.0.0.0.

    PHẢI CHẶN CẢ HAI NGUỒN. `_tailnet_ip` hỏi `ifconfig` trước rồi mới tới
    CLI (vì dưới launchd CLI không chạy được — xem test_tailnet_ip.py), nên
    bản cũ chỉ giả lập thiếu CLI vẫn tìm thấy địa chỉ thật của máy này và
    test xanh nhầm. Bộ kiểm đầy đủ cho từng nguồn nằm ở test_tailnet_ip.py.
    """
    import importlib.util
    import pathlib
    import shutil
    import subprocess

    spec = importlib.util.spec_from_file_location(
        "sr", pathlib.Path(__file__).parent.parent / "scripts" / "serve_review.py")
    assert spec and spec.loader
    sr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sr)

    # Máy không có card nào trong dải tailnet…
    monkeypatch.setattr(subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(
                            a[0] if a else [], 0,
                            "lo0:\n\tinet 127.0.0.1 netmask 0xff000000\n", ""))
    # …và cũng không cài Tailscale.
    monkeypatch.setattr(shutil, "which", lambda _: None)
    monkeypatch.setattr(sr.Path, "exists", lambda self: False)
    assert sr._tailnet_ip() is None


def test_api_tra_ve_corrected_khi_co():
    """Web cần bản sửa đi kèm `parse` trong cùng một lượt gọi.

    Tách thành endpoint riêng thì giao diện phải xử lý thêm trạng thái "đã
    tải parse chưa tải corrected", mà hai thứ luôn được dùng cùng nhau.
    """
    import pathlib
    src = pathlib.Path(__file__).parent.parent / "scripts" / "serve_review.py"
    code = src.read_text("utf-8")
    assert '"corrected"' in code
    assert 'corrected.json' in code


def test_parse_json_khong_bi_ghi_de():
    """Bản sửa phải nằm ở tệp RIÊNG: mọi grounding.range neo vào `markdown`
    bằng offset ký tự, sửa tại chỗ là làm lệch toàn bộ span của trang."""
    import json
    import pathlib
    store = pathlib.Path.home() / ".private" / "ade_out"
    if not store.is_dir():
        return                      # chưa chạy pipeline trên máy này
    for d in store.iterdir():
        pj, cj = d / "parse.json", d / "corrected.json"
        if not (pj.is_file() and cj.is_file()):
            continue
        md = json.loads(pj.read_text("utf-8")).get("markdown", "")
        for ch in json.loads(cj.read_text("utf-8"))["chunks"]:
            if ch["original"] != ch["corrected"]:
                # bản GỐC vẫn còn nguyên trong parse.json
                assert ch["original"] in md


def test_api_tra_ve_vision_khi_co():
    """Bản chép engine thứ hai phải về cùng lượt với `parse`.

    Đổi engine mà phải chờ tải lại thì người soát sẽ ngại bấm qua bấm lại —
    nhưng bấm qua lại chính là cách so sánh hai engine.
    """
    import pathlib
    src = pathlib.Path(__file__).parent.parent / "scripts" / "serve_review.py"
    code = src.read_text("utf-8")
    assert '"vision"' in code and "vision.json" in code


def test_script_nam_sau_moi_phan_tu_no_gan_su_kien():
    """Thẻ <script> phải nằm SAU mọi id mà app.js gán sự kiện.

    Đã hỏng thật: thẻ script ở giữa trang, phía trên lớp phủ file manager,
    nên `$('btnBrowse')` chạy lúc phần tử chưa được phân tích → TypeError →
    toàn bộ phần script sau đó không chạy → trang chỉ còn khung trắng.

    Kiểu hỏng này im lặng với người dùng: server 200, HTML đủ, CSS đủ, chỉ
    có JS chết giữa chừng.
    """
    import pathlib
    import re

    web = pathlib.Path(__file__).parent.parent / "web"
    html = (web / "index.html").read_text("utf-8")
    js = (web / "app.js").read_text("utf-8")

    # Điểm vào đổi sang ES module khi chuyển qua Vite.
    vi_tri_script = html.index('src="/src/main.js"')
    for m in re.finditer(r"""on\(['"](\w+)['"],""", js):
        el_id = m.group(1)
        moc = f'id="{el_id}"'
        if moc not in html:
            continue
        assert html.index(moc) < vi_tri_script, (
            f"#{el_id} nằm SAU thẻ script — app.js sẽ không thấy nó")


def test_khong_gan_su_kien_truc_tiep_o_tam_module():
    """`$('x').onclick = …` ở tầm module ném TypeError khi #x chưa có, và
    một TypeError ở đó giết TOÀN BỘ phần script còn lại.

    Dùng `on(id, ev, fn)` — thiếu phần tử thì mất đúng chức năng đó thôi.
    """
    import pathlib
    import re

    js = (pathlib.Path(__file__).parent.parent / "web" / "app.js").read_text("utf-8")
    xau = re.findall(r"^\$\('[\w]+'\)\.(?:on\w+ =|addEventListener)", js, re.M)
    assert not xau, f"còn {len(xau)} chỗ gán trực tiếp ở tầm module"


def test_tai_nguyen_web_khong_bi_cache():
    """Mã đổi liên tục; một bản JS cũ trong cache gây 'trang trắng' mà người
    dùng không tự chẩn đoán được — server đúng, đĩa đúng, chỉ trình duyệt sai."""
    import pathlib

    code = (pathlib.Path(__file__).parent.parent / "scripts"
            / "serve_review.py").read_text("utf-8")
    assert "no-store" in code
    # phải áp cho cả ba: html, js, css
    assert code.count("_NO_CACHE") >= 4


def test_hidden_phai_thang_moi_luat_display():
    """`[hidden]` mặc định của trình duyệt có độ ưu tiên THẤP NHẤT.

    Bất kỳ `.lop { display: flex }` nào cũng đè lên nó, và khi đó
    `el.hidden = true` đặt đúng thuộc tính mà phần tử VẪN HIỆN.

    Đã hỏng thật: bấm ✕ đóng file manager, `fmOverlay.hidden` thành true,
    nhưng `.fmOverlay { display: flex }` giữ nó phủ kín màn hình. Test cũ
    kiểm `.hidden` nên báo xanh trong khi màn hình kẹt ở khung trắng — đó
    là lý do test này kiểm CSS chứ không kiểm thuộc tính.
    """
    import pathlib
    import re

    css = (pathlib.Path(__file__).parent.parent / "web"
           / "style.css").read_text("utf-8")
    # Bỏ comment trước khi dò: bản đầu của test này khớp phải chuỗi
    # "[hidden] { display: none }" nằm trong chính đoạn giải thích ở trên
    # luật, rồi báo hỏng dù CSS đúng.
    khong_comment = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    m = re.search(r"^\[hidden\]\s*\{([^}]*)\}", khong_comment, re.M)
    assert m, "thiếu luật [hidden] toàn cục"
    assert "none" in m.group(1) and "!important" in m.group(1)


def test_bo_cuc_khong_tran_o_man_hinh_hep():
    """Ba cột tối thiểu cộng lại 990px; dưới mức đó lưới tràn và cột phải bị
    cắt mất — nút Markdown/JSON nằm ngoài vùng nhìn, không cuộn tới được."""
    import pathlib
    import re

    css = (pathlib.Path(__file__).parent.parent / "web"
           / "style.css").read_text("utf-8")
    assert "@media (max-width: 1100px)" in css
    # điểm gãy phải THỰC SỰ đổi số cột, không chỉ khai báo suông
    khoi = css[css.index("@media (max-width: 1100px)"):][:400]
    assert "grid-template-columns" in khoi


def test_man_hinh_hep_khong_bao_gio_an_cay_ho_so():
    """Ở khổ hẹp, bỏ thứ TRANG TRÍ chứ không bỏ thứ ĐIỀU HƯỚNG.

    Đã hỏng thật: media query dưới 700px đặt `.tree { display: none }`, mà
    cây hồ sơ là cách DUY NHẤT để đi giữa 36 tài liệu. Trang mở ra trống
    trơn — dữ liệu vẫn trong DOM, người dùng chỉ không thấy gì và không có
    cách nào lấy lại.
    """
    import pathlib
    import re

    css = (pathlib.Path(__file__).parent.parent / "web"
           / "style.css").read_text("utf-8")
    for m in re.finditer(r"@media[^{]*\{(.*?)\n\}", css, re.S):
        khoi = m.group(1)
        # `.viewer` (ảnh xem trước) được phép ẩn; `.tree` thì không.
        assert not re.search(r"\.tree\s*\{[^}]*display\s*:\s*none", khoi), \
            "media query ẩn cây hồ sơ — người dùng mất đường điều hướng"


def test_moi_engine_deu_dua_tai_lieu_vao_cay():
    """Cây hồ sơ không được lọc theo riêng `meta.json` của ADE.

    Đã hỏng thật: `/api/run` chạy Vision ghi `vision.json` nhưng KHÔNG ghi
    `meta.json`, còn `/api/tree` bỏ qua thư mục thiếu `meta.json`. Kết quả:
    người dùng chạy OCR xong, thấy chấm xanh trong file manager, rồi tài
    liệu không hiện ở "Hồ sơ" — và không có cách nào mở nó.
    """
    import pathlib

    code = (pathlib.Path(__file__).parent.parent / "scripts"
            / "serve_review.py").read_text("utf-8")
    i = code.index('@app.get("/api/tree")')
    khoi = code[i:code.index("@app.get", i + 10)]
    assert "vision.json" in khoi, "cây chỉ nhận tài liệu chạy bằng ADE"


def test_doc_mo_duoc_khi_chi_co_vision():
    """`_doc_dir` và `/api/doc` không được đòi riêng `parse.json`.

    Đòi nó thì tài liệu chạy bằng Vision — đường MẶC ĐỊNH của file manager —
    mở ra 404 rồi 500.
    """
    import pathlib

    code = (pathlib.Path(__file__).parent.parent / "scripts"
            / "serve_review.py").read_text("utf-8")
    i = code.index("def _doc_dir")
    khoi = code[i:i + 800]
    assert "vision.json" in khoi

    j = code.index("def doc(doc_id")
    khoi2 = code[j:j + 700]
    assert "pf.is_file()" in khoi2, "/api/doc đọc cứng parse.json"


def test_run_vision_ghi_ca_meta_json():
    import pathlib

    code = (pathlib.Path(__file__).parent.parent / "scripts"
            / "serve_review.py").read_text("utf-8")
    # Logic chạy nằm trong `_chay_mot_tep` — hàm module dùng chung cho cả
    # chạy một tệp lẫn chạy hàng loạt, nên chỉ có MỘT nơi để kiểm.
    i = code.index("def _chay_mot_tep")
    khoi = code[i:code.index("@app.get", i + 10)]
    assert 'mf = d / "meta.json"' in khoi
    # không được ghi đè meta của ADE (mang credits đã trả tiền)
    assert "if not mf.is_file()" in khoi


def test_moi_engine_chay_doc_lap_khong_khoa_nhau():
    """Chạy một engine không được khoá hai engine kia.

    Đã hỏng thật: `daChay = verity || pro || vision` nên chạy xong Vision là
    tệp chuyển sang trạng thái "đã xong", bấm vào chỉ mở xem — không còn cách
    nào chạy ADE cho đúng tệp đó. Với ba engine thì "đã chạy" phải tính THEO
    TỪNG ENGINE.
    """
    import pathlib

    js = (pathlib.Path(__file__).parent.parent / "web"
          / "app.js").read_text("utf-8")
    # chấm trạng thái phải là <button> có onclick riêng
    i = js.index("class Dots" if "class Dots" in js else "fmDots")
    khoi = js[i:i + 1200]
    assert "createElement('button')" in khoi, "chấm trạng thái không bấm được"
    assert "stopPropagation" in khoi, "bấm chấm sẽ kích hoạt cả hàng"


def test_chan_tinh_tien_lan_hai_o_server():
    """Bấm nhầm engine đã chạy không được gọi lại API trả phí.

    Chặn ở SERVER chứ không chỉ ở giao diện: giao diện có thể lỡ nhịp khi
    danh sách chưa kịp nạp lại, còn tệp trên đĩa thì không nói dối.
    """
    import pathlib

    code = (pathlib.Path(__file__).parent.parent / "scripts"
            / "serve_review.py").read_text("utf-8")
    # Logic chạy nằm trong `_chay_mot_tep` — hàm module dùng chung cho cả
    # chạy một tệp lẫn chạy hàng loạt, nên chỉ có MỘT nơi để kiểm.
    i = code.index("def _chay_mot_tep")
    khoi = code[i:code.index("@app.get", i + 10)]
    assert "da_co=True" in khoi


def test_dong_file_manager_giua_chung_go_co_dang_chay():
    """Đóng lúc đang chạy phải đóng EventSource và gỡ cờ.

    Không thì kết nối treo, `fm.dang_chay` kẹt true, và mọi cú bấm sau đó bị
    `if (fm.dang_chay) return` nuốt im lặng — đúng triệu chứng "khoá luôn".
    """
    import pathlib

    js = (pathlib.Path(__file__).parent.parent / "web"
          / "app.js").read_text("utf-8")
    i = js.index("function fmShow")
    khoi = js[i:i + 700]
    assert "fm.es.close()" in khoi and "dang_chay = false" in khoi


def test_file_manager_hien_MOI_tep_khong_an_gi():
    """Duyệt hồ sơ phải thấy đủ mọi tệp, kể cả loại không OCR được.

    Kho thật: 300 pdf · 148 docx · 67 jpg · 33 png · 22 xlsx · 6 bpmn · 5 zip.
    Lọc theo `_OCR_SUFFIXES` rồi bỏ phần còn lại thì 185 tệp Office biến mất
    khỏi màn hình — người dùng không biết hồ sơ có gì, và không phân biệt
    được "không có tệp" với "có nhưng công cụ không đọc được".
    """
    import pathlib

    code = (pathlib.Path(__file__).parent.parent / "scripts"
            / "serve_review.py").read_text("utf-8")
    i = code.index("def browse")
    khoi = code[i:code.index("@app.get", i + 10)]
    # mọi tệp đều được thêm vào danh sách, chỉ khác NHÃN
    assert '"kind": kind' in khoi
    assert "_OFFICE_SUFFIXES" in khoi
    # không có nhánh `continue` bỏ tệp theo đuôi
    assert "if not can_ocr:\n            continue" not in khoi


def test_css_khong_bao_gio_nap_bang_link_tuyet_doi():
    """CSS phải đi qua `import` trong JS, không phải `<link href="/...">`.

    Đã hỏng thật: index.html có `<link rel="stylesheet" href="/style.css">`.
    Vite coi đường dẫn tuyệt đối là tài nguyên NGOÀI dự án, không đưa vào
    đồ thị phụ thuộc, và bản dựng ra thiếu hẳn tệp đó — trang hiện ra trắng
    toát mà console không một dòng lỗi.
    """
    import pathlib
    web = pathlib.Path(__file__).parent.parent / "web"
    html = (web / "index.html").read_text("utf-8")
    assert 'href="/style.css"' not in html, (
        "style.css nạp bằng <link> tuyệt đối — Vite sẽ bỏ nó khỏi bản dựng")

    main = (web / "src" / "main.js").read_text("utf-8")
    for css in ("theme.css", "style.css"):
        assert css in main, f"{css} phải được import trong main.js"
    # Thứ tự: theme.css khai báo biến, style.css dùng chúng.
    assert main.index("theme.css") < main.index("style.css")


def test_ten_bien_cu_deu_co_cau_noi_sang_theme():
    """Mọi biến màu style.css dùng phải được theme.css hoặc cầu nối định nghĩa.

    Đã hỏng thật: theme.css khai báo `--bg-app`, còn style.css (viết trước
    đó) dùng `--bg`. Tên không khớp nên `background: var(--bg)` nhận giá trị
    rỗng — nền trắng trên chủ đề tối, không có lỗi nào được báo.
    """
    import pathlib, re
    web = pathlib.Path(__file__).parent.parent / "web"
    style = (web / "style.css").read_text("utf-8")
    theme = (web / "src" / "styles" / "theme.css").read_text("utf-8")

    dung = set(re.findall(r"var\(\s*(--[a-z0-9-]+)", style))
    khai_bao = set(re.findall(r"^\s*(--[a-z0-9-]+)\s*:", style + theme, re.M))
    # Biến do JS đặt lúc chạy, không khai báo tĩnh.
    khai_bao |= {"--w-tree", "--w-panel"}

    thieu = dung - khai_bao
    assert not thieu, f"style.css dùng biến chưa ai định nghĩa: {sorted(thieu)}"


def test_bang_chon_chu_de_nam_tren_trinh_xem():
    """z-index bảng chủ đề phải CAO HƠN lớp phủ trình xem.

    Bảng chọn là thứ người dùng vừa bấm — nó phải nằm trên mọi thứ. Đã hỏng
    thật: bảng để z-index 60 còn trình xem 70, nên mở bảng lúc đang xem tài
    liệu thì nó bị che và nút trông như hỏng.
    """
    import pathlib, re
    css = (pathlib.Path(__file__).parent.parent / "web"
           / "style.css").read_text("utf-8")

    def z(selector):
        khoi = re.search(rf"{re.escape(selector)}\s*\{{(.*?)\}}", css, re.S)
        assert khoi, f"không tìm thấy {selector}"
        m = re.search(r"z-index:\s*(\d+)", khoi.group(1))
        assert m, f"{selector} không đặt z-index"
        return int(m.group(1))

    assert z(".themePanel") > z(".vwOverlay")


def test_splitter_co_gioi_han_khong_the_keo_mat_cot():
    """Kéo hết cỡ vẫn phải còn thấy cột — giới hạn min là bắt buộc.

    Cùng bài học với media query từng ẩn mất cây hồ sơ: ở khổ hẹp bỏ thứ
    TRANG TRÍ, không bao giờ bỏ thứ ĐIỀU HƯỚNG.
    """
    import pathlib, re
    js = (pathlib.Path(__file__).parent.parent / "web" / "src" / "lib"
          / "splitter.js").read_text("utf-8")
    for ten in ("tree", "panel"):
        m = re.search(rf"{ten}:\s*\{{\s*min:\s*(\d+)", js)
        assert m, f"cột {ten} không có giới hạn min"
        assert int(m.group(1)) >= 100, (
            f"cột {ten} có thể kéo xuống {m.group(1)}px — quá hẹp để đọc")


def test_app_js_phai_phoi_ham_ra_globalThis():
    """Vite gộp app.js vào module ⇒ mọi hàm thành RIÊNG TƯ.

    Đã hỏng thật: file manager bấm tệp gọi `openLocalFile` nhưng hàm đó chỉ
    tồn tại trong phạm vi module — không lỗi, không phản hồi, nút như chết.
    Đoạn cầu nối cũng từng bị mất một lần khi nối bằng lệnh shell vào cuối
    tệp 1000 dòng, nên test này khoá nó lại.
    """
    import pathlib
    js = (pathlib.Path(__file__).parent.parent / "web" / "app.js").read_text("utf-8")
    for ten in ("openLocalFile", "veLaiOverlay"):
        assert f"globalThis.{ten}" in js, f"app.js không phơi ra {ten}"


def test_ve_khung_bo_qua_chunk_khong_co_toa_do():
    """Chunk neo theo `path` (docx/xlsx) không có hộp — không được ném.

    Vòng vẽ duyệt MỌI chunk; gọi `drawBox` với `box == null` là hợp lệ.
    Đã hỏng thật: TypeError "Cannot read properties of null (reading 'xmin')".
    """
    import pathlib
    js = (pathlib.Path(__file__).parent.parent / "web" / "app.js").read_text("utf-8")
    than = js[js.index("function drawBox("):]
    than = than[:than.index("\n}")]
    assert "if (!box) return;" in than, "drawBox không chặn box rỗng"


def test_collect_chunks_nhan_ca_hai_kieu_neo():
    """`collectChunks` phải nhận cả `box` lẫn `path`.

    Đã hỏng thật: chỉ nhận `box`, nên docx trích ra 1.737 ký tự markdown mà
    danh sách chunk rỗng — nhìn y hệt một tệp không đọc được.
    """
    import pathlib
    js = (pathlib.Path(__file__).parent.parent / "web" / "app.js").read_text("utf-8")
    than = js[js.index("function collectChunks("):]
    than = than[:than.index("\n}\n")]
    assert "g.box || g.path" in than


def test_zoom_bat_tren_ca_khung_khong_rieng_vung_cuon():
    """Ctrl/Cmd + lăn chuột phải bắt trên KHUNG, không riêng vùng cuộn.

    Nội dung ngắn hơn khung thì con trỏ nằm ngoài `.vwScroll` và sự kiện
    không bao giờ tới — người dùng lăn mà không có gì xảy ra.
    """
    import pathlib
    js = (pathlib.Path(__file__).parent.parent / "web" / "src" / "lib"
          / "viewer.js").read_text("utf-8")
    assert "this.khung.addEventListener('wheel'" in js
    assert "e.metaKey" in js, "thiếu Cmd cho macOS"
    assert "{ passive: false }" in js, "thiếu passive:false ⇒ preventDefault bị bỏ qua"


def test_chay_xong_phai_mo_luon_tai_lieu():
    """Chạy OCR và xem kết quả là MỘT ý định, không phải hai.

    Đã hỏng thật: sự kiện `done` chỉ gọi `fmLoad` cập nhật chấm rồi dừng.
    Người dùng bấm một lần, thấy thanh tiến trình chạy xong mà màn hình
    không đổi gì, phải bấm lần hai mới mở được — lần bấm đầu trông như
    không ăn.
    """
    import pathlib
    js = (pathlib.Path(__file__).parent.parent / "web" / "app.js").read_text("utf-8")
    i = js.index("es.addEventListener('done'")
    than = js[i:js.index("es.addEventListener('error'", i)]
    assert "fmOpen(" in than, "chạy xong không mở tài liệu ⇒ phải bấm hai lần"


def test_chay_hang_loat_luon_du_toan_truoc():
    """Không được gọi `/api/batch/run` mà chưa qua `/api/batch/preview`.

    Chạy một thư mục bằng ADE Pro là hàng chục đô la và không lấy lại được.
    Người dùng phải thấy số tệp, số trang, số tiền TRƯỚC khi đồng ý.
    """
    import pathlib
    js = (pathlib.Path(__file__).parent.parent / "web" / "app.js").read_text("utf-8")
    than = js[js.index("async function fmBatch("):]
    than = than[:than.index("\n}\n")]
    assert than.index("batch/preview") < than.index("batch/run"), (
        "gọi batch/run trước khi dự toán")
    assert "confirm(" in than, "không hỏi xác nhận trước khi tiêu tiền"
    assert than.index("confirm(") < than.index("batch/run")


def test_bam_mot_lan_chon_bam_dup_moi_mo():
    """Tệp: một lần bấm CHỌN, hai lần MỞ. Thư mục: một lần bấm là vào.

    Một lần bấm mà mở luôn thì không có lúc nào nhìn vào tệp trước khi
    quyết định — và với ADE quyết định đó tốn tiền. Thư mục thì ngược lại:
    duyệt cây lặp liên tục, bắt bấm đúp mỗi cấp chỉ mệt tay.
    """
    import pathlib
    js = (pathlib.Path(__file__).parent.parent / "web" / "app.js").read_text("utf-8")
    than = js[js.index("function fmRow("):]
    than = than[:than.index("\n}\n")]
    assert "el.ondblclick = onclick" in than, "bấm đúp không mở tệp"
    assert "onselect()" in than, "bấm một lần không chọn"

    # Hàng thư mục dùng `onclick` trần (một lần bấm), hàng tệp dùng `onselect`.
    dirs = js[js.index("for (const dir of d.dirs)"):]
    dirs = dirs[:dirs.index("for (const f of d.files)")]
    assert "onselect" not in dirs, "thư mục không được đòi bấm đúp"


def test_xem_truoc_dung_peek_khong_dung_extract():
    """Xem trước phải gọi `/api/peek`, không phải `/api/extract`.

    `extract` đọc TOÀN BỘ tệp — một PDF 34 trang mất vài giây. Hàm xem
    trước chạy mỗi lần người dùng đổi lựa chọn, nên phải rẻ; dùng extract
    ở đây làm việc duyệt tệp giật.
    """
    import pathlib
    js = (pathlib.Path(__file__).parent.parent / "web" / "app.js").read_text("utf-8")
    than = js[js.index("async function fmPeek("):]
    than = than[:than.index("\n}\n")]
    assert "/api/peek?" in than
    assert "/api/extract" not in than


def test_xem_truoc_bo_ket_qua_den_muon():
    """Bấm nhanh qua nhiều tệp ⇒ yêu cầu về không đúng thứ tự.

    Không chặn thì khung xem trước hiện tệp CŨ đè lên tệp đang chọn — sai
    âm thầm, và người dùng sẽ bấm "Quét OCR" tưởng là cho tệp đang nhìn.
    """
    import pathlib
    js = (pathlib.Path(__file__).parent.parent / "web" / "app.js").read_text("utf-8")
    than = js[js.index("async function fmPeek("):]
    than = than[:than.index("\n}\n")]
    assert "peekSeq" in than and "if (seq !== peekSeq) return;" in than


def test_web_tu_nhan_ban_moi():
    """`no-store` chỉ áp cho lần TẢI SAU — tab đã mở vẫn giữ bản cũ.

    Đã xảy ra thật hai lần: người dùng báo "tính năng không có" trong khi
    nó đã chạy trên đĩa, và cả hai lần mất một lượt chỉ để chẩn đoán.
    Web phải tự hỏi dấu vân tay và tải lại khi lệch.
    """
    import pathlib
    main = (pathlib.Path(__file__).parent.parent / "web" / "src"
            / "main.js").read_text("utf-8")
    assert "/api/version" in main, "web không kiểm tra bản mới"
    assert "location.reload()" in main

    srv = (pathlib.Path(__file__).parent.parent / "scripts"
           / "serve_review.py").read_text("utf-8")
    assert '@app.get("/api/version")' in srv
