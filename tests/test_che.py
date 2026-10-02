"""Che PII lên ảnh trang bằng box ADE Pro — `src/ocr_lab/che.py`.

Mọi giá trị ở đây là bịa (xem AGENTS.md: không định danh thật trong git).
pii-core được thay bằng `_PiiGia`: field là mọi lần xuất hiện của các giá
trị cho sẵn, token tất định — thứ được kiểm là đường field → markdown → box.
"""
from __future__ import annotations

import hashlib
import json
import re

import pytest

from ocr_lab import che
from ocr_lab.che import Truong, Vung, chung_minh, dong_cua, lam_sach, nung, tim_vung

_BANG = {"PERSON": "PSEUDONYMISE", "EMAIL": "PSEUDONYMISE", "PHONE": "PSEUDONYMISE",
         "NATIONAL_ID": "ANONYMISE", "APP_SERIAL": "PSEUDONYMISE", "NICE_CLASS": "KEEP",
         "DATE": "PSEUDONYMISE", "MONEY": "PSEUDONYMISE", "GEO": "ANONYMISE",
         "ADDRESS": "PSEUDONYMISE", "MARK": "PSEUDONYMISE"}


def _token(cat: str, v: str) -> str:
    return f"[{cat}-{hashlib.sha1(f'{cat}|{v}'.encode()).hexdigest()[:6]}]"


class _PiiGia(che.PiiCore):
    """pii-core giả. `gia_tri`: {giá trị: hạng mục}; hành động theo `_BANG`."""

    def __init__(self, gia_tri: dict[str, str] | None = None, **bang: str):
        super().__init__({**_BANG, **bang}, "gia")
        self.gia_tri = gia_tri or {}
        self.goi: list[tuple[list[str], str]] = []

    def quyet(self, texts: list[str], group: str = "") -> list[list[Truong]]:
        self.goi.append((list(texts), group))
        out = []
        for t in texts:
            fs = []
            for v, cat in self.gia_tri.items():
                act = self.hanh_dong(cat)
                thay = (v if act == "KEEP" else _token(cat, v) if act == "PSEUDONYMISE"
                        else f"[{cat}]" if act == "ANONYMISE" else "")
                fs += [Truong(m.start(), m.end(), cat, act, thay, "gia")
                       for m in re.finditer(re.escape(v), t)]
            out.append(fs)
        return out


def _atom(page: int, s: int, e: int, box: tuple[float, float, float, float]) -> dict:
    return {"page": page, "range": {"start": s, "end": e},
            "box": dict(zip(("xmin", "ymin", "xmax", "ymax"), box)), "confidence": None}


def _parse(md: str, children: list[dict]) -> dict:
    return {"markdown": md, "metadata": {"page_count": 1},
            "structure": {"type": "document", "children": [
                {"type": "page", "grounding": _atom(1, 0, len(md), (0, 0, 1, 1)),
                 "children": children}]}}


def _text(md: str, line: str, y: float) -> dict:
    s = md.index(line)
    return {"type": "text", "grounding": _atom(1, s, s + len(line), (0.1, y, 0.9, y + 0.04)),
            "atomic_grounding": [_atom(1, s, s + len(line), (0.1, y, 0.9, y + 0.04))]}


def _vung(parse: dict, nguon: che.PiiCore, *a, **kw) -> list[Vung]:
    return tim_vung(parse, nguon, *a, **kw).vung


def test_lam_sach_giu_duong_ve_vi_tri_goc():
    raw = "<td>A&amp;B **x**</td>"
    chu, m = lam_sach(raw)
    assert chu.strip() == "A&B x"
    assert raw[m[chu.index("x")]] == "x"


def test_trang_ade_pro_dem_tu_1_nhu_anh_trang():
    md = "Họ và tên: Nguyễn Văn Zorblax"
    assert dong_cua(_parse(md, [_text(md, md, 0.1)]))[0].page == 1


def test_nung_ra_pdf_chi_anh_va_chung_minh_dat(tmp_path):
    from PIL import Image, ImageDraw
    img = tmp_path / "p1.jpg"
    im = Image.new("RGB", (600, 400), "white")
    ImageDraw.Draw(im).text((100, 100), "ZORBLAX 079912345678", fill="black")
    im.save(img)
    v = [Vung(1, {"xmin": 0.15, "ymin": 0.24, "xmax": 0.6, "ymax": 0.3}, "NATIONAL_ID",
              "ANONYMISE", "pii_core")]
    rects = nung({1: img}, v, tmp_path / "che.pdf")
    assert chung_minh(tmp_path / "che.pdf", rects) == []


def test_chung_minh_bat_vung_chua_to(tmp_path):
    from PIL import Image
    img = tmp_path / "p1.jpg"
    Image.new("RGB", (600, 400), "white").save(img)
    nung({1: img}, [], tmp_path / "che.pdf")
    loi = chung_minh(tmp_path / "che.pdf", {1: [(10, 10, 200, 100, 0)]})
    assert loi and "điểm sáng" in loi[0]


def test_nhan_cua_o_nay_khong_rơi_vao_o_ben_canh(tmp_path):
    from PIL import Image
    img = tmp_path / "p1.jpg"
    Image.new("RGB", (600, 400), "white").save(img)
    # Hai vùng liền nhau trên một dòng, chồng nhau vài px vì phần nới.
    a = Vung(1, {"xmin": 0.10, "ymin": 0.2, "xmax": 0.40, "ymax": 0.3}, "PERSON", "PSEUDONYMISE", "pii_core")
    b = Vung(1, {"xmin": 0.39, "ymin": 0.2, "xmax": 0.70, "ymax": 0.3}, "EMAIL", "PSEUDONYMISE", "pii_core")
    rects = nung({1: img}, [a, b], tmp_path / "che.pdf")
    assert chung_minh(tmp_path / "che.pdf", rects) == []


def test_box_noi_toi_bien_tu_va_mot_ky_tu():
    md = "Zorblax Quimbyxx"
    d = dong_cua(_parse(md, [_text(md, md, 0.1)]))[0]
    b = che._hop_con(d, md, 0, 10)          # cắt giữa từ thứ hai
    assert b["xmax"] >= 0.9                   # nới tới hết từ, không lộ đuôi


def _anh_dong(tmp_path, tu: list[str], w: int = 800, h: int = 120, cao: int = 24,
              khe: int = 9):
    """Ảnh trang tổng hợp: mỗi từ là một khối đen rộng theo bề rộng chữ,
    cách nhau `khe` px, trên dòng y 40..40+cao. Trả (đường dẫn, box dòng, x từng từ)."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), "white")
    dr = ImageDraw.Draw(im)
    x, xs = 50, []
    for t in tu:
        ww = round(sum(che._rong(c) for c in t) * 11)
        dr.rectangle((x, 44, x + ww - 1, 40 + cao - 4), fill=(20, 20, 20))
        xs.append((x, x + ww))
        x += ww + khe
    f = tmp_path / "p1.jpg"
    im.save(f, quality=90)
    box = (40 / w, 40 / h, (x - khe + 10) / w, (40 + cao) / h)
    return f, box, xs


def test_box_mot_chu_so_nho_duoc_va_van_chung_minh_dat(tmp_path):
    tu = ["Tầng", "7", "phòng", "họp"]
    md = " ".join(tu)
    f, box, xs = _anh_dong(tmp_path, tu)
    d = dong_cua(_parse(md, [{"type": "text", "grounding": _atom(1, 0, len(md), box),
                              "atomic_grounding": [_atom(1, 0, len(md), box)]}]))[0]
    b = che._hop_muc(d, md, 5, 6, che.AnhTrang({1: f}))
    assert b is not None
    assert (b["xmax"] - b["xmin"]) * 800 <= (xs[1][1] - xs[1][0]) + 2
    v = Vung(1, b, "MONEY", "PSEUDONYMISE", "pii_core", "muc")
    rects = nung({1: f}, [v], tmp_path / "che.pdf")
    assert chung_minh(tmp_path / "che.pdf", rects) == []


def test_khop_tu_tu_choi_khi_lech_qua():
    # 3 từ ngang nhau nhưng mực là một cụm to + hai cụm li ti: khớp bừa là che
    # sai từ. Phải trả None để rơi về nội suy (nới rộng, an toàn hơn).
    assert che._khop_tu([1.0, 1.0, 1.0], [(0, 300), (310, 312), (320, 322)]) is None


# ── pii-core quyết, che.py chỉ đặt box ───────────────────────────────────

def test_field_pii_core_tren_dong_che_gia_tri_khong_che_nhan_va_in_token():
    md = "Họ và tên: ZORBLAX QUIMBY"
    kq = tim_vung(_parse(md, [_text(md, md, 0.1)]), _PiiGia({"ZORBLAX QUIMBY": "PERSON"}))
    v, = kq.vung
    assert (v.code, v.action, v.luat, v.thay) == (
        "PERSON", "PSEUDONYMISE", "pii_core", _token("PERSON", "ZORBLAX QUIMBY"))
    assert (kq.truong, kq.khong_dinh_vi) == (1, 0)
    # Tính theo bề rộng chữ, nhãn chiếm ~32% đầu dòng; box nới một ký tự
    # sang trái nhưng không nuốt nhãn.
    assert v.box["xmin"] > 0.1 + 0.8 * 0.28


def test_keep_cua_pii_core_khong_bi_che_va_khong_tinh():
    md = "Nice class 35, email zq@vidu.test"
    kq = tim_vung(_parse(md, [_text(md, md, 0.2)]),
                  _PiiGia({"35": "NICE_CLASS", "zq@vidu.test": "EMAIL"}))
    assert [v.code for v in kq.vung] == ["EMAIL"] and kq.truong == 1


def test_hanh_dong_lay_nguyen_tu_pii_core_khong_ghi_de():
    # GEO: pii-core nói ANONYMISE thì ô che mang ANONYMISE và nhãn lớp — không
    # còn ghi đè nào ở ocr-lab.
    md = "Quê quán: Xã Zorb"
    v, = _vung(_parse(md, [_text(md, md, 0.1)]), _PiiGia({"Xã Zorb": "GEO"}))
    assert (v.action, v.thay) == ("ANONYMISE", "[GEO]")
    assert not hasattr(che, "nap_pii_lab") and not hasattr(che, "_GHI_DE_HANH_DONG")


def test_field_hai_dong_che_ca_hai_dong():
    md = "Địa chỉ: 901 Zorb Street,\nQuimby Ward, Blax City\nKết thúc"
    lines = md.split("\n")
    kids = [_text(md, t, 0.1 + 0.1 * k) for k, t in enumerate(lines)]
    kq = tim_vung(_parse(md, kids), _PiiGia({"901 Zorb Street,\nQuimby Ward, Blax City": "ADDRESS"}))
    assert sorted(round(v.box["ymin"], 2) for v in kq.vung) == [0.1, 0.2]
    assert kq.khong_dinh_vi == 0


def test_vi_tri_qua_the_html_entity_va_dam_ve_dung_o_bang():
    cells = ["*Name", "Zorb &amp; Quimby", "*Email", "zq@vidu.test"]
    td = [f"<td>**{c}**</td>" for c in cells[:2]] + [f"<td>{c}</td>" for c in cells[2:]]
    md = "<table><tr>" + "".join(td[:2]) + "</tr><tr>" + "".join(td[2:]) + "</tr></table>"
    kids = []
    for i, t in enumerate(td):
        s = md.index(t)
        kids.append({"type": "table_cell", "row": i // 2, "col": i % 2,
                     "grounding": _atom(1, s, s + len(t),
                                        (0.1 + 0.4 * (i % 2), 0.1 * (i // 2 + 1),
                                         0.5 + 0.4 * (i % 2), 0.1 * (i // 2 + 2)))})
    nguon = _PiiGia({"Zorb & Quimby": "PERSON", "zq@vidu.test": "EMAIL"})
    kq = tim_vung(_parse(md, [{"type": "table", "children": kids}]), nguon)
    assert "Zorb & Quimby" in nguon.goi[0][0][0]           # pii-core nhận chữ sạch
    # Cả ô, đo không được thì lấy cả box ô (không nội suy).
    assert [(v.code, v.box["xmin"], v.box["ymin"], v.dinh_vi) for v in kq.vung] == [
        ("PERSON", 0.5, 0.1, "dong"), ("EMAIL", 0.5, 0.2, "dong")]


def test_field_khong_nam_trong_dong_nao_thi_dem_khong_dinh_vi():
    md = "Tiêu đề không có box\nEmail: zq@vidu.test"
    kid = _text(md, "Email: zq@vidu.test", 0.3)
    kq = tim_vung(_parse(md, [kid]), _PiiGia({"không có box": "PERSON", "zq@vidu.test": "EMAIL"}))
    assert [v.code for v in kq.vung] == ["EMAIL"]
    assert (kq.truong, kq.khong_dinh_vi) == (2, 1)


def test_chung_minh_hong_khi_co_field_khong_dinh_vi(tmp_path):
    from PIL import Image
    img = tmp_path / "p1.jpg"
    Image.new("RGB", (600, 400), "white").save(img)
    rects = nung({1: img}, [], tmp_path / "che.pdf")
    assert chung_minh(tmp_path / "che.pdf", rects) == []
    loi = chung_minh(tmp_path / "che.pdf", rects, khong_dinh_vi=2)
    assert loi and "2 field" in loi[0]


def test_che_tai_lieu_ghi_chung_minh_hong_khi_khong_dinh_vi(tmp_path):
    from PIL import Image
    md = "Không box: ZORBLAX\nEmail: zq@vidu.test"
    d = tmp_path / "abc"
    (d / "pages").mkdir(parents=True)
    Image.new("RGB", (400, 300), "white").save(d / "pages" / "p1.jpg")
    (d / "parse_pro.json").write_text(json.dumps(
        _parse(md, [_text(md, "Email: zq@vidu.test", 0.3)])), "utf-8")
    t = che.che_tai_lieu(d, _PiiGia({"ZORBLAX": "PERSON", "zq@vidu.test": "EMAIL"}),
                         tmp_path / "out")
    assert t["khong_dinh_vi"] == 1 and t["chung_minh"] != "đạt"
    j = json.loads((tmp_path / "out" / "abc" / "che.json").read_text("utf-8"))
    assert j["chung_minh"] != "đạt" and j["khong_dinh_vi"] == 1
    assert "zq@vidu.test" not in json.dumps(j) and "ZORBLAX" not in json.dumps(j)


def test_che_ho_so_hoi_pii_core_mot_lan_cho_ca_nhom(tmp_path):
    from PIL import Image
    dirs = []
    for k, md in enumerate(["Email: zq@vidu.test", "Gửi zq@vidu.test"]):
        d = tmp_path / f"doc{k}"
        (d / "pages").mkdir(parents=True)
        Image.new("RGB", (400, 300), "white").save(d / "pages" / "p1.jpg")
        (d / "parse_pro.json").write_text(json.dumps(_parse(md, [_text(md, md, 0.2)])), "utf-8")
        dirs.append(d)
    nguon = _PiiGia({"zq@vidu.test": "EMAIL"})
    tom = che.che_ho_so(dirs, nguon, tmp_path / "out", group="NH9001")
    assert len(nguon.goi) == 1 and len(nguon.goi[0][0]) == 2 and nguon.goi[0][1] == "NH9001"
    assert [t["theo_hang_muc"] for t in tom] == [{"EMAIL": 1}, {"EMAIL": 1}]
    assert all(t["chung_minh"] == "đạt" for t in tom)


# ── hình: không phải chữ, pii-core không thấy ────────────────────────────

def test_hinh_anh_nguoi_chu_ky_qr_bi_che_ca_box_dong_chu_logo_thi_khong():
    md = "[Profile picture of a man]\nZorblax\n[handwritten_signature]\n[qr code]\n[zorblax logo]"
    kids = [_text(md, t, 0.1 + 0.1 * k) for k, t in enumerate(md.split("\n"))]
    v = _vung(_parse(md, kids), _PiiGia())
    # Hạng mục ảnh vắng mặt trong bảng pii-core → REMOVE (như Policy.action_for).
    assert [(x.code, x.luat, x.action, x.thay) for x in v] == [
        ("FACE_PHOTO", "hinh", "REMOVE", "[FACE_PHOTO]"),
        ("SIGNATURE", "hinh", "REMOVE", "[SIGNATURE]"),
        ("SCAN_CODE", "hinh", "REMOVE", "[SCAN_CODE]")]
    assert v[0].box == kids[0]["atomic_grounding"][0]["box"]


def test_hinh_theo_bang_pii_core_keep_thi_khong_che():
    md = "QR"
    code = {"type": "scan_code", "grounding": _atom(1, 0, 2, (0.7, 0.7, 0.9, 0.9))}
    assert _vung(_parse(md, [code]), _PiiGia(SCAN_CODE="KEEP")) == []
    v, = _vung(_parse(md, [code]), _PiiGia())
    assert (v.code, v.action, v.luat) == ("SCAN_CODE", "REMOVE", "ma_quet")


def test_mau_nhan_dang_hinh_va_logo_che_ca_phan_tu():
    md = ('<figure type="ILLUSTRATION">Blue zorb device ZORBLAX</figure>\n'
          "ZORBLAX CO\nNội dung thư")
    fig_s = 0
    fig_e = md.index("\n")
    logo_s = md.index("ZORBLAX CO")
    logo_e = logo_s + len("ZORBLAX CO")
    fig = {"type": "figure", "grounding": _atom(1, fig_s, fig_e, (0.1, 0.1, 0.4, 0.3)),
           "atomic_grounding": [_atom(1, fig_s, fig_e, (0.1, 0.1, 0.4, 0.3))]}
    logo = {"type": "logo", "grounding": _atom(1, logo_s, logo_e, (0.6, 0.02, 0.9, 0.08)),
            "atomic_grounding": [_atom(1, logo_s, logo_e, (0.62, 0.03, 0.88, 0.07))]}
    kq = tim_vung(_parse(md, [fig, logo, _text(md, "Nội dung thư", 0.5)]),
                  _PiiGia({"ZORBLAX": "MARK"}))
    # Cả box phần tử, kể cả chữ pii-core thấy trong nó: không thêm ô con, và
    # field trong hình được tính là có vùng.
    assert sorted((v.code, v.luat, v.box["xmin"]) for v in kq.vung) == [
        ("MARK_IMAGE", "hinh_ade", 0.1), ("MARK_IMAGE", "hinh_ade", 0.6)]
    assert (kq.truong, kq.khong_dinh_vi) == (2, 0)


# ── nung: in token ───────────────────────────────────────────────────────

def test_nung_in_token_pii_core_len_o_du_cao(tmp_path):
    from PIL import Image
    img = tmp_path / "p1.jpg"
    Image.new("RGB", (600, 400), "white").save(img)
    v = Vung(1, {"xmin": 0.1, "ymin": 0.1, "xmax": 0.7, "ymax": 0.2}, "PERSON",
             "PSEUDONYMISE", "pii_core", "muc", _token("PERSON", "ZORBLAX"))
    rects = nung({1: img}, [v], tmp_path / "che.pdf")
    assert rects[1][0][4] == che._NHAN_CAO                 # nhãn đã in
    assert chung_minh(tmp_path / "che.pdf", rects) == []


def test_nhan_o_la_token_khong_ascii_thi_nhan_lop():
    v = Vung(1, {}, "DATE", "PSEUDONYMISE", "pii_core", thay="[DATE-0a1b2c]")
    assert che._nhan(v) == "[DATE-0a1b2c]"
    assert che._nhan(Vung(1, {}, "DATE", "PSEUDONYMISE", "pii_core", thay="ngày 9 tháng 1")) == "[DATE]"
    assert che._nhan(Vung(1, {}, "SIGNATURE", "REMOVE", "hinh")) == "[SIGNATURE]"


def test_vung_o_trang_khong_co_anh_thi_khong_ghi(tmp_path):
    from PIL import Image
    md = "Họ và tên: ZORBLAX QUIMBY"
    parse = _parse(md, [_text(md, md, 0.1)])
    parse["structure"]["children"][0]["children"][0]["atomic_grounding"][0]["page"] = 2
    d = tmp_path / "abc"
    (d / "pages").mkdir(parents=True)
    Image.new("RGB", (60, 40), "white").save(d / "pages" / "p1.jpg")
    (d / "parse_pro.json").write_text(json.dumps(parse), "utf-8")
    t = che.che_tai_lieu(d, _PiiGia({"ZORBLAX QUIMBY": "PERSON"}), tmp_path / "out")
    assert "trang không có ảnh" in t["bo_qua"]
    assert not (tmp_path / "out" / "abc").exists()


# ── nguồn pii-core thật: HTTP và thư viện ────────────────────────────────

def test_pii_core_http_goi_decisions_va_document(monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    nhan: list[tuple[str, str, dict | None]] = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # noqa: ANN002
            pass

        def _gui(self, body: dict) -> None:
            b = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):  # noqa: N802
            nhan.append(("GET", self.path, None))
            self._gui({"decisions": [{"category": "EMAIL", "action": "PSEUDONYMISE"}]})

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            nhan.append(("POST", self.path, {**body, "ct": self.headers["Content-Type"]}))
            t = body["text"]
            s = t.index("zq@vidu.test")
            self._gui({"fields": [{"category": "EMAIL", "action": "PSEUDONYMISE", "start": s,
                                   "end": s + 12, "replacement": "[EMAIL-0a1b2c]",
                                   "matched_by": "pattern:email", "reason": "", "label": "",
                                   "provisional": False}]})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("PII_CORE_URL", f"http://127.0.0.1:{srv.server_port}")
        nguon = che.nap_pii_core()
        assert isinstance(nguon, che.PiiCoreHttp)
        assert nguon.hanh_dong("EMAIL") == "PSEUDONYMISE" and nguon.hanh_dong("MARK_IMAGE") == "REMOVE"
        md = "Email: zq@vidu.test"
        v, = _vung(_parse(md, [_text(md, md, 0.1)]), nguon, group="NH9001")
        assert v.thay == "[EMAIL-0a1b2c]"
        assert nhan[1][:2] == ("POST", "/v1/document")
        assert nhan[1][2] == {"text": md, "group": "NH9001", "ct": "application/json"}
    finally:
        srv.shutdown()


def test_pii_core_khong_goi_duoc_thi_bao_thieu():
    with pytest.raises(che.PiiCoreThieu):
        che.PiiCoreHttp("http://127.0.0.1:9", timeout=2)


def test_mac_dinh_tim_pii_core_trong_repo(monkeypatch):
    monkeypatch.delenv("PII_CORE_SRC", raising=False)
    monkeypatch.setattr(che.sys, "path", [p for p in che.sys.path if p != str(che.PII_CORE_SRC)])
    che.them_duong_pii_core()
    assert che.sys.path[0] == str(che.PII_CORE_SRC)
    assert (che.PII_CORE_SRC / "pii_core" / "__init__.py").is_file()


def test_pii_core_src_ghi_de_ban_trong_repo(monkeypatch, tmp_path):
    (tmp_path / "pii_core").mkdir()
    (tmp_path / "pii_core" / "__init__.py").write_text("")
    monkeypatch.setenv("PII_CORE_SRC", str(tmp_path))
    monkeypatch.setattr(che.sys, "path", list(che.sys.path))
    che.them_duong_pii_core()
    assert che.sys.path[0] == str(tmp_path)


def test_thu_vien_pii_core_that(monkeypatch):
    monkeypatch.delenv("PII_CORE_SRC", raising=False)
    che.them_duong_pii_core()
    from pii_core import Policy
    nguon = che.PiiCoreThuVien(Policy("khoa-thu-khong-dung-that-0123456789abcdef"))
    md = "Email: zorblax@example.test"
    v, = [x for x in _vung(_parse(md, [_text(md, md, 0.1)]), nguon) if x.code == "EMAIL"]
    assert v.thay.startswith("[EMAIL-") and v.action == "PSEUDONYMISE"


# ── web: cùng vùng, không chữ gốc ────────────────────────────────────────

def _server(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path

    from fastapi.testclient import TestClient
    spec = importlib.util.spec_from_file_location(
        "sr_che", Path(__file__).parent.parent / "scripts" / "serve_review.py")
    sr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sr)
    md = "Email: zorblax@example.test"
    d = tmp_path / "store" / "abcdef0123456789"
    (d / "pages").mkdir(parents=True)
    (d / "parse_pro.json").write_text(json.dumps(_parse(md, [_text(md, md, 0.1)])), "utf-8")
    monkeypatch.setattr(sr, "STORE", tmp_path / "store")
    monkeypatch.setattr(sr, "_NGUON", [_PiiGia({"zorblax@example.test": "EMAIL"})])
    monkeypatch.setattr(che, "DEFAULT_OUT", tmp_path / "che")
    return TestClient(sr.app), d, md, sr


def test_api_che_tra_box_va_token_khong_tra_chu_goc(tmp_path, monkeypatch):
    c, d, md, _ = _server(tmp_path, monkeypatch)
    from PIL import Image
    Image.new("RGB", (400, 300), "white").save(d / "pages" / "p1.jpg")
    r = c.get("/api/doc/abcdef0123456789/che")
    assert r.status_code == 200
    j = r.json()
    assert j["dem"] == {"EMAIL": 1} and j["vung"][0]["page"] == 1
    assert j["vung"][0]["thay"] == _token("EMAIL", "zorblax@example.test")
    assert (j["truong"], j["khong_dinh_vi"], j["pii_core"]) == (1, 0, "gia")
    assert "zorblax" not in r.text          # chỉ box + hạng mục + token, không chữ
    p = c.get("/api/doc/abcdef0123456789/che.pdf")
    assert p.status_code == 200 and p.content[:4] == b"%PDF"


def test_api_che_pdf_dung_lai_ban_cu_khong_do_pii_core(tmp_path, monkeypatch):
    c, d, _, _ = _server(tmp_path, monkeypatch)
    from PIL import Image
    Image.new("RGB", (400, 300), "white").save(d / "pages" / "p1.jpg")
    cu = tmp_path / "che" / "abcdef0123456789"
    cu.mkdir(parents=True)
    (cu / "che.pdf").write_bytes(b"%PDF-cu")
    (cu / "che.json").write_text(json.dumps({"doc_id": "abcdef0123456789",
                                             "pii_lab": "cu", "chung_minh": "đạt"}), "utf-8")
    assert c.get("/api/doc/abcdef0123456789/che").json()["co_pdf"] is False
    p = c.get("/api/doc/abcdef0123456789/che.pdf")
    assert p.status_code == 200 and p.content[:4] == b"%PDF" and p.content != b"%PDF-cu"
    assert json.loads((cu / "che.json").read_text("utf-8"))["pii_core"] == "gia"
    assert c.get("/api/doc/abcdef0123456789/che").json()["co_pdf"] is True


def test_api_che_pdf_tu_choi_khi_khong_co_anh_trang(tmp_path, monkeypatch):
    c, _, _, _ = _server(tmp_path, monkeypatch)
    assert c.get("/api/doc/abcdef0123456789/che").json()["ly_do"]
    assert c.get("/api/doc/abcdef0123456789/che.pdf").status_code == 409


def test_api_che_503_khi_khong_co_pii_core(tmp_path, monkeypatch):
    c, _, _, sr = _server(tmp_path, monkeypatch)
    monkeypatch.setattr(sr, "_NGUON", [])

    def tat() -> che.PiiCore:
        raise che.PiiCoreThieu("tắt")
    monkeypatch.setattr(che, "nap_pii_core", tat)
    assert c.get("/api/doc/abcdef0123456789/che").status_code == 503



def test_giu_tra_ca_field_keep_ma_khong_dem_vao_che():
    # Lớp soát trên web cần thấy cả cái được GIỮ, nhưng KEEP không phải thứ
    # thiếu vùng che — không được đẩy truong/khong_dinh_vi.
    md = "Nhóm 25, ông ZORBLAX"
    p = _parse(md, [_text(md, md, 0.1)])
    nguon = _PiiGia({"25": "NICE_CLASS", "ZORBLAX": "PERSON"})
    kq = tim_vung(p, nguon, giu=True)
    keep, = [v for v in kq.vung if v.action == "KEEP"]
    assert keep.code == "NICE_CLASS" and keep.thay == ""
    assert (kq.truong, kq.khong_dinh_vi) == (1, 0)
    assert kq.dem == {"KEEP": 1, "PSEUDONYMISE": 1}
    assert kq.dem_hang_muc == {"NICE_CLASS": {"KEEP": 1}, "PERSON": {"PSEUDONYMISE": 1}}
    assert all(v.action != "KEEP" for v in tim_vung(p, nguon).vung)


def test_api_truong_tra_ca_keep_va_dem_theo_hanh_dong(tmp_path, monkeypatch):
    c, d, _, sr = _server(tmp_path, monkeypatch)
    md = "Email: zorblax@example.test nhóm 25"
    (d / "parse_pro.json").write_text(json.dumps(_parse(md, [_text(md, md, 0.1)])), "utf-8")
    monkeypatch.setattr(sr, "_NGUON", [_PiiGia({"zorblax@example.test": "EMAIL", "25": "NICE_CLASS"})])
    from PIL import Image
    Image.new("RGB", (400, 300), "white").save(d / "pages" / "p1.jpg")
    r = c.get("/api/doc/abcdef0123456789/truong")
    assert r.status_code == 200
    j = r.json()
    assert j["dem"] == {"PSEUDONYMISE": 1, "KEEP": 1} and j["ly_do"] is None
    assert j["theo_hang_muc"]["NICE_CLASS"] == {"KEEP": 1}
    assert {v["action"] for v in j["vung"]} == {"PSEUDONYMISE", "KEEP"}
    assert "zorblax" not in r.text          # KEEP không mang chữ gốc ra web
    assert c.get("/api/doc/khongco/truong").status_code == 404


# ── box: đo mực, nội suy, sửa box pro ────────────────────────────────────

def test_markdown_dam_khong_day_box_lech():
    # `**` không hiện trên trang: đếm nó là đẩy box sang phải.
    md = "**Kính gửi** ông ZORBLAX, email zorblax@vidu.test"
    tron = "Kính gửi ông ZORBLAX, email zorblax@vidu.test"
    nguon = _PiiGia({"zorblax@vidu.test": "EMAIL"})
    a, = _vung(_parse(md, [_text(md, md, 0.1)]), nguon)
    b, = _vung(_parse(tron, [_text(tron, tron, 0.1)]), nguon)
    assert a.box == b.box


def test_box_khit_theo_muc_tren_anh_trang(tmp_path):
    tu = ["Liên", "hệ", "0912345678", "ngay", "hôm", "nay"]
    md = " ".join(tu)
    f, box, xs = _anh_dong(tmp_path, tu)
    kid = {"type": "text", "grounding": _atom(1, 0, len(md), box),
           "atomic_grounding": [_atom(1, 0, len(md), box)]}
    v, = _vung(_parse(md, [kid]), _PiiGia({"0912345678": "PHONE"}), {1: f})
    assert v.dinh_vi == "muc"
    x0, x1 = v.box["xmin"] * 800, v.box["xmax"] * 800
    a, b = xs[2]
    assert abs(x0 - a) <= 1 and abs(x1 - b) <= 1        # khít mép mực ±1 px
    assert x0 > xs[1][1] and x1 < xs[3][0]               # không chạm từ bên cạnh


def test_khong_co_anh_thi_noi_suy_va_ghi_ro():
    md = "Liên hệ 0912345678 ngay"
    v, = _vung(_parse(md, [_text(md, md, 0.2)]), _PiiGia({"0912345678": "PHONE"}))
    assert v.dinh_vi == "noi_suy"


def test_ngay_tren_vien_xam_khong_che_ca_vien(tmp_path):
    # Ảnh chat: ngày in trên "viên" xám (200) giữa nền trắng. Box dòng ADE
    # rộng hơn viên. Ô che phải ôm CHỮ, không ôm viên.
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (800, 120), "white")
    dr = ImageDraw.Draw(im)
    dr.rounded_rectangle((300, 40, 500, 70), 12, fill=(200, 200, 200))
    dr.rectangle((360, 47, 440, 63), fill=(60, 60, 60))       # chữ "09/07/2026"
    f = tmp_path / "p1.jpg"
    im.save(f, quality=90)
    md = "09/07/2026"
    box = (280 / 800, 38 / 120, 520 / 800, 72 / 120)
    kid = {"type": "text", "grounding": _atom(1, 0, len(md), box),
           "atomic_grounding": [_atom(1, 0, len(md), box)]}
    v, = _vung(_parse(md, [kid]), _PiiGia({md: "DATE"}), {1: f})
    assert v.dinh_vi == "muc"
    assert abs(v.box["xmin"] * 800 - 360) <= 2 and abs(v.box["xmax"] * 800 - 441) <= 2


def test_box_pro_gan_lech_lay_box_ban_thuong_theo_muc(tmp_path):
    # Bản pro gán "Xa Zorb Quux" vào box của dòng trên (nhãn, ít chữ hơn);
    # bản thường đặt đúng. Mực phân xử → vùng che nằm ở dòng thật.
    from PIL import Image, ImageDraw
    W, H = 800, 400
    im = Image.new("RGB", (W, H), "white")
    dr = ImageDraw.Draw(im)

    def viet(y, tu):
        x = 50
        for t in tu:
            ww = round(sum(che._rong(c) for c in t) * 11)
            dr.rectangle((x, y + 4, x + ww - 1, y + 20), fill=(20, 20, 20))
            x += ww + 9
        return (40 / W, y / H, (x + 1) / W, (y + 24) / H)
    tu = [["Alpha", "Beta"], ["Gamma", "Delta", "Omega"], ["Quê", "quán:"], ["Xa", "Zorb", "Quux"], ["Kappa", "Lambda"]]
    boxes = [viet(40 + 40 * k, t) for k, t in enumerate(tu)]
    f = tmp_path / "p1.jpg"
    im.save(f, quality=95)
    lines = [" ".join(t) for t in tu]
    md = "\n".join(lines)

    def kid(line, box):
        s = md.index(line)
        return {"type": "text", "grounding": _atom(1, s, s + len(line), box),
                "atomic_grounding": [_atom(1, s, s + len(line), box)]}
    thuong = _parse(md, [kid(l, b) for l, b in zip(lines, boxes)])
    # pro: dòng 3 (giá trị) mang box dòng 4, dòng 4 mang box dòng 3.
    pro = _parse(md, [kid(lines[0], boxes[0]), kid(lines[1], boxes[1]), kid(lines[2], boxes[2]),
                      kid(lines[3], boxes[4]), kid(lines[4], boxes[3])])
    nguon = _PiiGia({"Xa Zorb Quux": "GEO"})
    sai = _vung(pro, nguon, {1: f})
    dung = _vung(pro, nguon, {1: f}, thuong)
    assert sai and abs(sai[0].box["ymin"] * H - 200) < 6          # không có bản thường: che nhầm dòng
    assert any(abs(v.box["ymin"] * H - 164) < 4 for v in dung)     # có: che đúng dòng giá trị
    # box pro bị bỏ vì bản thường đặt chữ khác ("Kappa Lambda") lên đó
    assert not any(abs(v.box["ymin"] * H - 200) < 6 for v in dung)


def test_email_trong_ngoac_nhon_khong_bi_coi_la_the_html():
    chu, _ = lam_sach("Zorb Quimby <zorb.q@zorblax.com> wrote:<br>hi")
    assert "<zorb.q@zorblax.com>" in chu and "<br>" not in chu


def test_gach_chan_ca_dong_khong_lam_hong_do_muc(tmp_path):
    from PIL import Image, ImageDraw
    tu = ["Liên", "hệ", "0912345678", "ngay", "hôm", "nay"]
    md = " ".join(tu)
    f, box, xs = _anh_dong(tmp_path, tu)
    im = Image.open(f)
    ImageDraw.Draw(im).line((45, 62, xs[-1][1] + 5, 62), fill=(20, 20, 20), width=2)
    im.save(f, quality=90)
    kid = {"type": "text", "grounding": _atom(1, 0, len(md), box),
           "atomic_grounding": [_atom(1, 0, len(md), box)]}
    v, = _vung(_parse(md, [kid]), _PiiGia({"0912345678": "PHONE"}), {1: f})
    assert v.dinh_vi == "muc"
    assert abs(v.box["xmin"] * 800 - xs[2][0]) <= 1 and abs(v.box["xmax"] * 800 - xs[2][1]) <= 1


def test_o_bang_nhieu_dong_che_tung_dong_khit(tmp_path):
    from PIL import Image, ImageDraw
    hang = [["Liên", "hệ", "số", "máy"], ["0912345678", "ngay", "hôm", "nay"]]
    im = Image.new("RGB", (800, 200), "white")
    dr = ImageDraw.Draw(im)
    xs = []
    for r, tu in enumerate(hang):
        x, y = 50, 44 + 30 * r
        for t in tu:
            ww = round(sum(che._rong(c) for c in t) * 11)
            dr.rectangle((x, y, x + ww - 1, y + 15), fill=(20, 20, 20))
            xs.append((x, x + ww, y, y + 16))
            x += ww + 9
    f = tmp_path / "p1.jpg"
    im.save(f, quality=90)
    md = " ".join(hang[0] + hang[1])
    box = (40 / 800, 40 / 200, 360 / 800, 94 / 200)
    kid = {"type": "text", "grounding": _atom(1, 0, len(md), box),
           "atomic_grounding": [_atom(1, 0, len(md), box)]}
    v, = _vung(_parse(md, [kid]), _PiiGia({"0912345678": "PHONE"}), {1: f})
    a, b, y0, y1 = xs[4]
    assert v.dinh_vi == "muc"
    assert abs(v.box["xmin"] * 800 - a) <= 1 and abs(v.box["xmax"] * 800 - b) <= 1
    assert abs(v.box["ymin"] * 200 - y0) <= 1 and abs(v.box["ymax"] * 200 - y1) <= 1


_ARIAL = ("/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",
          "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
          "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


@pytest.mark.parametrize("gia_tri", ["ÔNG ZORBLAX", "PHỆ QUIMBY", "phố Zorblax", "Lạc Quimby"])
def test_dau_tach_roi_chu_nam_trong_o_den(tmp_path, gia_tri):
    # Dấu tách rời chữ (mũ của Ô/Ệ, sắc của ố, chấm dưới ạ/ệ) là hàng mực thưa:
    # box khít theo mực không được cắt nó ra ngoài ô đen.
    import os
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    font = next((p for p in _ARIAL if os.path.exists(p)), None)
    if font is None:
        pytest.skip("không có phông Arial/DejaVu")
    f_ = ImageFont.truetype(font, 28)
    nhan = "Địa chỉ liên hệ của bên nộp đơn: "
    md = nhan + gia_tri
    W, H, x, y = 1000, 140, 40, 50
    im = Image.new("L", (W, H), 255)
    ImageDraw.Draw(im).text((x, y), md, font=f_, fill=0)
    rieng = Image.new("L", (W, H), 255)          # mực của riêng giá trị
    ImageDraw.Draw(rieng).text((x + f_.getlength(nhan), y), gia_tri, font=f_, fill=0)
    p = tmp_path / "p1.png"
    im.save(p)
    _, t, _, b = ImageDraw.Draw(im).textbbox((x, y), md, font=f_)
    box = ((x - 6) / W, (t - 2) / H, (x + f_.getlength(md) + 6) / W, (b + 2) / H)
    d = dong_cua(_parse(md, [{"type": "text", "grounding": _atom(1, 0, len(md), box),
                              "atomic_grounding": [_atom(1, 0, len(md), box)]}]))[0]
    bb = che._hop_muc(d, md, len(nhan), len(md), che.AnhTrang({1: p}))
    assert bb is not None
    ys, xs = np.nonzero(np.asarray(rieng) < 128)
    x0, y0 = bb["xmin"] * W, bb["ymin"] * H
    x1, y1 = bb["xmax"] * W, bb["ymax"] * H
    ngoai = ~((xs >= x0 - 1) & (xs < x1 + 1) & (ys >= y0) & (ys < y1))
    assert not ngoai.any(), (y0, y1, sorted(set(ys[ngoai].tolist())))
    assert y0 >= box[1] * H - 1 and y1 <= box[3] * H + 1   # không lấn dòng khác


# ── con dấu, chữ ký: phần tử `attestation` của ADE ───────────────────────

def _chung_thuc(md: str, mo_ta: str, box: tuple[float, float, float, float]) -> dict:
    s = md.index(mo_ta)
    return {"type": "attestation", "grounding": _atom(1, s, s + len(mo_ta), box),
            "atomic_grounding": [_atom(1, s, s + len(mo_ta), box)]}


def test_con_dau_che_ca_phan_tu_va_field_trong_no_khong_can_o_rieng():
    md = "Nội dung thư\n[Stamped: ZORBLAX CO seal]\n[Signed by Zorb Quimby]"
    dau = _chung_thuc(md, "[Stamped: ZORBLAX CO seal]", (0.6, 0.6, 0.9, 0.85))
    ky = _chung_thuc(md, "[Signed by Zorb Quimby]", (0.1, 0.6, 0.4, 0.8))
    kq = tim_vung(_parse(md, [_text(md, "Nội dung thư", 0.1), dau, ky]),
                  _PiiGia({"ZORBLAX CO": "ORG", "Zorb Quimby": "PERSON"}, ORG="PSEUDONYMISE"))
    # Cả box phần tử, hạng mục theo lời tả của ADE; STAMP vắng trong bảng
    # pii-core nên đóng ở REMOVE. Field nằm trong dấu/chữ ký: không ô riêng,
    # nhưng vẫn tính là có vùng.
    assert sorted((v.code, v.luat, v.action, v.box["xmin"]) for v in kq.vung) == [
        ("SIGNATURE", "chung_thuc", "REMOVE", 0.1), ("STAMP", "chung_thuc", "REMOVE", 0.6)]
    assert (kq.truong, kq.khong_dinh_vi) == (2, 0)


def test_con_dau_theo_bang_pii_core_keep_thi_khong_che():
    md = "[Stamped: ZORBLAX CO seal]"
    p = _parse(md, [_chung_thuc(md, md, (0.6, 0.6, 0.9, 0.85))])
    assert _vung(p, _PiiGia(STAMP="KEEP")) == []


def test_con_dau_de_len_dong_chu_cat_o_field_ma_khong_lo_gi():
    # Dấu đè nửa phải của dòng chữ. Ô của field trên dòng bị cắt bỏ phần nằm
    # dưới dấu (dấu nghiêm hơn: REMOVE), phần còn lại vẫn phủ phần lộ ra.
    md = "Người ký: ZORBLAX QUIMBY\n[Stamped: ZORBLAX CO]"
    dau = _chung_thuc(md, "[Stamped: ZORBLAX CO]", (0.6, 0.05, 0.95, 0.3))
    kq = tim_vung(_parse(md, [_text(md, "Người ký: ZORBLAX QUIMBY", 0.1), dau]),
                  _PiiGia({"ZORBLAX QUIMBY": "PERSON"}))
    s, = [v for v in kq.vung if v.code == "STAMP"]
    ps = [v for v in kq.vung if v.code == "PERSON"]
    assert ps and all(v.box["xmax"] <= s.box["xmin"] + 1e-9 for v in ps)
    assert sum(v.nhan for v in ps) == 1                  # một token cho một field
    goc, = _vung(_parse(md, [_text(md, "Người ký: ZORBLAX QUIMBY", 0.1)]),
                 _PiiGia({"ZORBLAX QUIMBY": "PERSON"}))
    assert _phu_het(goc.box, [v.box for v in kq.vung])
    assert kq.khong_dinh_vi == 0


def test_api_truong_tra_con_dau_la_loai_vung_rieng(tmp_path, monkeypatch):
    c, d, _, sr = _server(tmp_path, monkeypatch)
    md = "Email: zorblax@example.test\n[Stamped: ZORBLAX CO]"
    (d / "parse_pro.json").write_text(json.dumps(_parse(md, [
        _text(md, "Email: zorblax@example.test", 0.1),
        _chung_thuc(md, "[Stamped: ZORBLAX CO]", (0.6, 0.5, 0.9, 0.8))])), "utf-8")
    from PIL import Image
    Image.new("RGB", (400, 300), "white").save(d / "pages" / "p1.jpg")
    j = c.get("/api/doc/abcdef0123456789/truong").json()
    assert {(v["code"], v["luat"]) for v in j["vung"]} == {("EMAIL", "pii_core"), ("STAMP", "chung_thuc")}
    assert "ZORBLAX" not in json.dumps(j)


# ── vùng chồng nhau ──────────────────────────────────────────────────────

def _phu_het(b: dict, cac: list[dict], n: int = 400) -> bool:
    """Box `b` nằm trọn trong hợp các box `cac` (đo trên lưới n×n)."""
    import numpy as np
    m = np.zeros((n, n), bool)
    for c in cac:
        m[round(c["ymin"] * n):round(c["ymax"] * n), round(c["xmin"] * n):round(c["xmax"] * n)] = True
    return bool(m[round(b["ymin"] * n):round(b["ymax"] * n), round(b["xmin"] * n):round(b["xmax"] * n)].all())


def _chong(a: dict, b: dict) -> float:
    w = min(a["xmax"], b["xmax"]) - max(a["xmin"], b["xmin"])
    h = min(a["ymax"], b["ymax"]) - max(a["ymin"], b["ymin"])
    return max(0.0, w) * max(0.0, h)


def test_tru_hop_con_lai_dung_phan_ngoai():
    import random
    rd = random.Random(7)
    for _ in range(300):
        def hop():
            x0, y0 = rd.random() * 0.8, rd.random() * 0.8
            return {"xmin": x0, "ymin": y0, "xmax": x0 + 0.05 + rd.random() * 0.2,
                    "ymax": y0 + 0.05 + rd.random() * 0.2}
        p, a = hop(), hop()
        manh = che._tru(p, a)
        assert all(_chong(m, a) < 1e-12 and che._trong(m, p, 0) for m in manh)
        assert all(_chong(x, y) < 1e-12 for i, x in enumerate(manh) for y in manh[i + 1:])
        dt = sum(che._dien_tich(m) for m in manh)
        assert abs(dt - (che._dien_tich(p) - _chong(p, a))) < 1e-9


def test_org_geo_chong_nhau_anonymise_thang_va_khong_lo_muc(tmp_path):
    # Hai field liền nhau trên một dòng, box nội suy nới một ký tự nên chồng
    # lên nhau. GEO (ANONYMISE) nghiêm hơn ORG (PSEUDONYMISE): GEO giữ nguyên,
    # ORG bị cắt; không còn gì chồng, nhãn không in đè, mực không lộ.
    import numpy as np
    tu = ["Công", "ty", "ZORBLAX", "QUIMBY", "Xã", "Zorb", "Quux", "năm", "nay"]
    md = " ".join(tu)
    f, box, xs = _anh_dong(tmp_path, tu, w=900, cao=40, khe=6)
    kid = {"type": "text", "grounding": _atom(1, 0, len(md), box),
           "atomic_grounding": [_atom(1, 0, len(md), box)]}
    p = _parse(md, [kid])
    org, = _vung(p, _PiiGia({"ZORBLAX QUIMBY": "ORG"}, ORG="PSEUDONYMISE"))
    geo, = _vung(p, _PiiGia({"Xã Zorb Quux": "GEO"}))
    assert _chong(org.box, geo.box) > 0                    # tiền đề: chồng thật
    kq = tim_vung(p, _PiiGia({"ZORBLAX QUIMBY": "ORG", "Xã Zorb Quux": "GEO"}, ORG="PSEUDONYMISE"))
    assert [v.box for v in kq.vung if v.code == "GEO"] == [geo.box]
    assert all(_chong(a.box, b.box) < 1e-12 for i, a in enumerate(kq.vung) for b in kq.vung[i + 1:])
    assert _phu_het(org.box, [v.box for v in kq.vung])
    assert sum(v.nhan for v in kq.vung if v.code == "ORG") == 1
    rects = nung({1: f}, kq.vung, tmp_path / "che.pdf", ghi_nhan=False)
    assert chung_minh(tmp_path / "che.pdf", rects) == []
    import io
    import pymupdf
    from PIL import Image
    with pymupdf.open(tmp_path / "che.pdf") as d:
        o = np.asarray(Image.open(io.BytesIO(d.extract_image(d[0].get_images()[0][0])["image"])).convert("L"))
    for k in range(2, 7):                                  # mực của cả hai giá trị
        a, b = xs[k]
        assert o[45:60, a:b].max() < 100, tu[k]
    # Nhãn: mỗi field một token, và dải nhãn không chạm ô nào khác.
    rects = nung({1: f}, kq.vung, tmp_path / "che2.pdf")
    dai = [r for r in rects[1] if r[4]]
    assert all(not che._giao((r[0], r[1], r[2], r[1] + r[4]), o) for r in dai
               for o in rects[1] if o is not r)


def test_keep_khong_bao_gio_mo_o_che_va_o_che_nhu_nhau_khi_co_keep():
    md = "Nhóm 25 ZORBLAX 2025 hôm nay"
    p = _parse(md, [_text(md, md, 0.1)])
    # "25 ZORBLAX 2025" KEEP (nhóm Nice), "ZORBLAX" PERSON nằm giữa nó.
    nguon = _PiiGia({"25 ZORBLAX 2025": "NICE_CLASS", "ZORBLAX": "PERSON"})
    co = tim_vung(p, nguon, giu=True).vung
    khong = tim_vung(p, nguon).vung
    assert [v for v in co if v.action != "KEEP"] == khong
    keep = [v for v in co if v.action == "KEEP"]
    assert keep and all(_chong(k.box, v.box) < 1e-12 for k in keep for v in khong)


def test_box_trung_cua_cung_mot_field_gop_thanh_mot():
    a = Vung(1, {"xmin": 0.10, "ymin": 0.20, "xmax": 0.40, "ymax": 0.26}, "PERSON", "PSEUDONYMISE",
             "pii_core", thay="[PERSON-0a1b2c]")
    b = Vung(1, {"xmin": 0.11, "ymin": 0.21, "xmax": 0.42, "ymax": 0.27}, "PERSON", "PSEUDONYMISE",
             "pii_core", thay="[PERSON-0a1b2c]")
    v, = che._giai_chong([a, b])
    assert v.box == {"xmin": 0.10, "ymin": 0.20, "xmax": 0.42, "ymax": 0.27} and v.nhan


# ── trang nghiêng: ô che nghiêng theo dòng chữ ───────────────────────────

_DONG_NGHIENG = ["Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu",
                 "Kính gửi ông bà về việc nộp đơn đăng ký nhãn hiệu cho sản phẩm",
                 "Địa chỉ liên hệ của bên nộp đơn: PHỆ QUIMBY ZORBLAX số 901 phố Quux",
                 "Người đại diện theo pháp luật ký tên đóng dấu xác nhận hồ sơ này",
                 "Omicron pi rho sigma tau upsilon phi chi psi omega alpha beta"]


def _trang_nghieng(tmp_path, goc: float, gia_tri: str):
    """Trang scan lệch `goc` độ (dương: dòng đi xuống về bên phải): năm dòng
    dài, sát nhau, nên hộp bao thẳng của dòng này ăn vào dòng kia. Box ADE là
    hộp bao của từng dòng xiên, như ADE Pro trả trên bản scan lệch. Trả (ảnh,
    parse, mặt nạ mực của riêng giá trị, mặt nạ mực của phần còn lại)."""
    import os
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    font = next((p for p in _ARIAL if os.path.exists(p)), None)
    if font is None:
        pytest.skip("không có phông Arial/DejaVu")
    f_ = ImageFont.truetype(font, 26)
    W, H = 1100, 420

    def ve(chi: int | None = None, rieng: bool = False):
        im = Image.new("L", (W, H), 255)
        dr = ImageDraw.Draw(im)
        for k, t in enumerate(_DONG_NGHIENG):
            if chi is not None and k != chi:
                continue
            x, y = 60, 90 + 42 * k
            if not rieng:
                dr.text((x, y), t, font=f_, fill=0)
            elif gia_tri in t:
                dr.text((x + f_.getlength(t[:t.index(gia_tri)]), y), gia_tri, font=f_, fill=0)
        return im.rotate(-goc, resample=Image.BICUBIC, fillcolor=255)
    trang = ve()
    f = tmp_path / "p1.png"
    trang.save(f)
    md = "\n".join(_DONG_NGHIENG)
    kids = []
    for k, t in enumerate(_DONG_NGHIENG):
        ys, xs = np.nonzero(np.asarray(ve(chi=k)) < 128)
        box = ((xs.min() - 2) / W, (ys.min() - 2) / H, (xs.max() + 3) / W, (ys.max() + 3) / H)
        s = md.index(t)
        kids.append({"type": "text", "grounding": _atom(1, s, s + len(t), box),
                     "atomic_grounding": [_atom(1, s, s + len(t), box)]})
    rieng = np.asarray(ve(rieng=True)) < 128
    return f, _parse(md, kids), rieng, (np.asarray(trang) < 128) & ~rieng


def _mat_na(vung: list[Vung], W: int, H: int):
    """Điểm ảnh nằm dưới ô che, đúng như `nung` tô."""
    import numpy as np
    from PIL import Image, ImageDraw
    m = Image.new("L", (W, H), 0)
    dr = ImageDraw.Draw(m)
    for v in vung:
        q = che._da_giac(v, W, H)
        if q:
            dr.polygon(q, fill=255)
        else:
            dr.rectangle(che._pixel(v.box, W, H), fill=255)
    return np.asarray(m) > 0


@pytest.mark.parametrize("goc", [2.0, -3.0])
def test_trang_nghieng_o_che_nghieng_theo_dong_va_khong_lo_muc(tmp_path, goc):
    import io
    import math
    import numpy as np
    import pymupdf
    from PIL import Image
    gia_tri = "PHỆ QUIMBY ZORBLAX"                 # có dấu tách rời: mũ, chấm dưới
    f, p, rieng, khac = _trang_nghieng(tmp_path, goc, gia_tri)
    anh = che.AnhTrang({1: f})
    k = anh.dat_khung(dong_cua(p))[1]
    assert abs(k.goc - goc) <= 0.1
    v, = _vung(p, _PiiGia({gia_tri: "PERSON"}), {1: f})
    assert v.dinh_vi == "muc" and v.tu_giac is not None
    (x0, y0), (x1, y1) = v.tu_giac[0], v.tu_giac[1]
    assert abs(math.degrees(math.atan2((y1 - y0) * 420, (x1 - x0) * 1100)) - goc) <= 0.3
    # Không điểm mực nào của giá trị nằm ngoài ô che, và ô che không ăn vào
    # mực của chữ bên cạnh hay dòng trên/dưới.
    m = _mat_na([v], 1100, 420)
    assert int((rieng & ~m).sum()) == 0
    assert int((khac & m).sum()) <= 0.002 * int(khac.sum())
    # Trên tệp đã nung: mực giá trị tối hẳn, và phép chứng minh đạt (cả khi in nhãn).
    rects = nung({1: f}, [v], tmp_path / "che.pdf", ghi_nhan=False)
    with pymupdf.open(tmp_path / "che.pdf") as d:
        o = np.asarray(Image.open(io.BytesIO(d.extract_image(d[0].get_images()[0][0])["image"])).convert("L"))
    assert int((o[rieng] > 100).sum()) == 0
    assert chung_minh(tmp_path / "che.pdf", rects) == []
    rects = nung({1: f}, [v], tmp_path / "nhan.pdf")
    assert len(rects[1][0]) == 6 and chung_minh(tmp_path / "nhan.pdf", rects) == []


def test_trang_thang_khong_xoay_gi(tmp_path):
    f, p, _, _ = _trang_nghieng(tmp_path, 0.0, "PHỆ QUIMBY ZORBLAX")
    assert che.AnhTrang({1: f}).dat_khung(dong_cua(p)) == {}
    v, = _vung(p, _PiiGia({"PHỆ QUIMBY ZORBLAX": "PERSON"}), {1: f})
    assert v.tu_giac is None


def test_khung_sai_goc_lam_roi_muc_thi_bo(tmp_path):
    # Góc sai (ngược dấu): box nắn thẳng để mực của box ADE rơi ra ngoài mọi
    # box — không được dùng khung đó, không thì mực giá trị lộ.
    f, p, _, _ = _trang_nghieng(tmp_path, 2.0, "PHỆ QUIMBY ZORBLAX")
    anh = che.AnhTrang({1: f})
    k = anh.dat_khung(dong_cua(p))[1]
    # Đúng góc: khung giữ. Dòng mà đầu phải không có chân chữ thì hộp bao
    # nói dòng mỏng hơn thật, nắn hụt chân chữ giữa dòng — riêng dòng đó
    # lui về hộp bao thẳng (`ca`), không mất mực.
    assert len(k.ca) <= 1
    hop = [d.box for d in dong_cua(p)]
    assert che._mat_muc(anh.goc(1), che.Khung.tao(-k.goc, 1100, 420, k.day), hop) is None


def test_chung_minh_bat_o_tu_giac_chua_to(tmp_path):
    from PIL import Image
    img = tmp_path / "p1.jpg"
    Image.new("RGB", (600, 400), "white").save(img)
    nung({1: img}, [], tmp_path / "che.pdf")
    q = ((100.0, 100.0), (300.0, 110.0), (298.0, 150.0), (98.0, 140.0))
    loi = chung_minh(tmp_path / "che.pdf", {1: [(98, 100, 300, 150, 0, q)]})
    assert loi and "điểm sáng" in loi[0]
