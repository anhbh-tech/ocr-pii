"""Hợp đồng `POST /api/classify`: khuôn JSON, đường đi, độ tin cậy, không bao giờ vỡ.

Mọi tài liệu ở đây là tài liệu TỔNG HỢP dựng ngay trong test — không có tệp
nào của khách hàng.
"""

from __future__ import annotations

import importlib.util
import io
import json
import math
import pathlib
import unicodedata
import zipfile

import pytest

from ocr_lab import classify_api as api
from ocr_lab.classify_api import (
    CONTRACT, ROUTES, _do_ben, _pdf_route, _PDF_RANH_CHARS, _PDF_RANH_COVER,
    _tin_cay, classify_bytes, classify_path,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "docs" / "classify-api.schema.json").read_text("utf-8"))

pymupdf = pytest.importorskip("pymupdf")

LOREM = ("Điều 1. Bên A đồng ý bán và Bên B đồng ý mua lô hàng theo đơn giá "
         "thoả thuận, thanh toán trong vòng ba mươi ngày kể từ ngày nhận hoá "
         "đơn hợp lệ. ") * 4


# ── kiểm khuôn theo JSON Schema (tập con đủ dùng, không thêm phụ thuộc) ─────

def _hop_le(v, s, duong="$"):
    if "$ref" in s:
        s = SCHEMA["$defs"][s["$ref"].rsplit("/", 1)[1]]
    if "const" in s:
        assert v == s["const"], duong
    if "enum" in s:
        assert v in s["enum"], f"{duong}: {v!r} ngoài {s['enum']}"
    kieu = s.get("type")
    if kieu is not None:
        kieu = kieu if isinstance(kieu, list) else [kieu]
        khop = {"object": dict, "array": list, "string": str, "null": type(None),
                "integer": int, "number": (int, float)}
        assert any(isinstance(v, khop[k]) and not isinstance(v, bool)
                   for k in kieu), f"{duong}: {v!r} không phải {kieu}"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "minimum" in s:
            assert v >= s["minimum"], duong
        if "maximum" in s:
            assert v <= s["maximum"], duong
    if isinstance(v, dict):
        for k in s.get("required", []):
            assert k in v, f"{duong}: thiếu {k}"
        if s.get("additionalProperties") is False:
            du = set(v) - set(s.get("properties", {}))
            assert not du, f"{duong}: thừa {du}"
        for k, con in s.get("properties", {}).items():
            if k in v:
                _hop_le(v[k], con, f"{duong}.{k}")
    if isinstance(v, list) and "items" in s:
        for i, x in enumerate(v):
            _hop_le(x, s["items"], f"{duong}[{i}]")


def _kiem(r: dict) -> dict:
    """Mọi kết quả, kể cả khi lỗi, phải đúng khuôn và tự nhất quán."""
    _hop_le(r, SCHEMA)
    assert r["contract"] == CONTRACT
    assert r["pages_needing_ocr"] == [p["index"] for p in r["pages"]
                                      if p["route"] == "ocr"]
    assert r["signals"]["page_count"] == len(r["pages"])
    if r["pages"] and r["kind"] not in ("unreadable", "unsupported"):
        assert r["confidence"] == min(p["confidence"] for p in r["pages"])
    return r


# ── dựng tài liệu tổng hợp ─────────────────────────────────────────────────

def _pdf(*trang: str) -> bytes:
    """Mỗi phần tử một trang: "text", "scan" (ảnh phủ ~90%, không chữ), "blank"."""
    doc = pymupdf.open()
    for loai in trang:
        pg = doc.new_page(width=595, height=842)
        if loai == "text":
            pg.insert_textbox(pymupdf.Rect(50, 50, 545, 792), LOREM, fontsize=10)
        elif loai == "scan":
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 560))
            pix.clear_with(200)
            pg.insert_image(pymupdf.Rect(20, 20, 575, 822), pixmap=pix)
    data = doc.tobytes()
    doc.close()
    return data


_DOCX_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:v="urn:schemas-microsoft-com:vml" '
            'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
            'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"')

#: Khổ A4 theo EMU: 210 mm × 297 mm.
_A4_EMU = (7560000, 10692000)


def _anh_drawing(cx: int, cy: int) -> str:
    return (f'<w:r><w:drawing><wp:inline><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<a:graphic><a:graphicData><a:blip/></a:graphicData></a:graphic>'
            f'</wp:inline></w:drawing></w:r>')


def _docx(text: str = "", than_them: str = "", *, xml: str | None = None) -> bytes:
    if xml is None:
        chu = f"<w:r><w:t>{text}</w:t></w:r>" if text else ""
        xml = (f'<?xml version="1.0" encoding="UTF-8"?><w:document {_DOCX_NS}>'
               f'<w:body><w:p>{chu}{than_them}</w:p>'
               f'<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>'
               f'</w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def _png_chu() -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    im = Image.new("RGB", (1200, 900), "white")
    ve = ImageDraw.Draw(im)
    font = ImageFont.load_default(size=40)
    for i, dong in enumerate(["HOP DONG MUA BAN SO 12/2025", "BEN A: CONG TY ABC",
                              "BEN B: CONG TY XYZ", "GIA TRI: 150.000.000 VND",
                              "NGAY KY: 01/02/2025"]):
        ve.text((60, 80 + i * 140), dong, fill="black", font=font)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _png_canh() -> bytes:
    """Ảnh "cảnh vật" không có chữ: dải màu trơn."""
    from PIL import Image

    im = Image.linear_gradient("L").resize((800, 600)).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "JPEG")
    return buf.getvalue()


def _do_gia(n: int):
    """Bộ dò giả trả đúng `n` vùng chữ — để test không phụ thuộc model."""
    hop = [[[0, 0], [10, 0], [10, 10], [0, 10]]] * n
    return lambda arr, **kw: (hop or None, None)


# ── PDF ────────────────────────────────────────────────────────────────────

def test_pdf_digital_doc_thang():
    r = _kiem(classify_bytes(_pdf("text", "text"), "hd.pdf"))
    assert (r["kind"], r["route"]) == ("born_digital_pdf", "read_direct")
    assert r["pages_needing_ocr"] == []
    assert r["confidence"] == 1.0
    assert r["source"] == {"name": "hd.pdf", "format": "pdf",
                           "bytes": len(_pdf("text", "text"))}


def test_pdf_scan_di_ocr():
    r = _kiem(classify_bytes(_pdf("scan", "scan"), "scan.pdf"))
    assert (r["kind"], r["route"]) == ("scanned_pdf", "ocr")
    assert r["pages_needing_ocr"] == [0, 1]
    assert r["confidence"] == 1.0


def test_pdf_lai_chi_ocr_trang_anh():
    r = _kiem(classify_bytes(_pdf("text", "scan", "text"), "lai.pdf"))
    assert (r["kind"], r["route"]) == ("hybrid_pdf", "ocr")
    assert r["pages_needing_ocr"] == [1]
    assert [p["route"] for p in r["pages"]] == ["read_direct", "ocr", "read_direct"]
    assert r["signals"]["route_agreement"] == pytest.approx(1 / 3, abs=1e-3)
    assert r["signals"]["text_layer_coverage"] == pytest.approx(2 / 3, abs=1e-3)


def test_pdf_trang_trong():
    r = _kiem(classify_bytes(_pdf("blank"), "trong.pdf"))
    assert r["kind"] == "born_digital_pdf"
    assert r["pages"][0]["kind"] == "blank"
    assert r["signals"]["blank_pages"] == 1
    assert r["route"] == "agent_context"


def test_pdf_moi_trang_trong_de_agent_xem():
    """Không lớp text, không ảnh (vd. chữ vẽ thành đường cong): đọc thẳng ra rỗng."""
    r = _kiem(classify_bytes(_pdf("blank", "blank"), "outline.pdf"))
    assert (r["kind"], r["route"], r["confidence"]) == (
        "born_digital_pdf", "agent_context", 1.0)
    assert [p["route"] for p in r["pages"]] == ["agent_context"] * 2
    assert r["pages_needing_ocr"] == []


def _pdf_chu(chu: str, *trang_trong: str) -> bytes:
    doc = pymupdf.open()
    doc.new_page(width=595, height=842).insert_text((50, 80), chu, fontsize=10)
    for _ in trang_trong:
        doc.new_page(width=595, height=842)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.mark.parametrize("n, route", [(60, "read_direct"), (40, "agent_context")])
def test_pdf_trang_chu_duy_nhat_sat_nguong_50(n, route):
    """Trang chữ duy nhất: rơi dưới 50 ký tự là cả tệp đổi đường — hai phía đều hạ."""
    for data in (_pdf_chu("x" * n), _pdf_chu("x" * n, "blank")):
        r = _kiem(classify_bytes(data, "ngan.pdf"))
        chars = r["pages"][0]["chars"]
        assert r["route"] == route
        assert r["confidence"] == pytest.approx(
            _tin_cay(abs(math.log2(chars / 49.5))), abs=0.001)
        assert r["confidence"] < 0.9


def test_pdf_chu_lan_trang_trong_van_doc_thang():
    r = _kiem(classify_bytes(_pdf("text", "blank"), "hd.pdf"))
    assert (r["kind"], r["route"]) == ("born_digital_pdf", "read_direct")
    assert [p["route"] for p in r["pages"]] == ["read_direct", "read_direct"]
    assert r["pages"][1]["kind"] == "blank"


def test_noi_dung_thang_duoi_tep():
    """Loại theo byte, không theo tên: PDF đặt tên .docx vẫn là PDF."""
    r = _kiem(classify_bytes(_pdf("scan"), "ho_so.docx"))
    assert r["kind"] == "scanned_pdf" and r["source"]["format"] == "pdf"


def test_pdf_hong_va_co_mat_khau():
    r = _kiem(classify_bytes(b"%PDF-1.7\nkhong phai pdf", "hong.pdf"))
    assert (r["kind"], r["route"], r["confidence"]) == ("unreadable", "agent_context", 0.0)
    assert r["error"]

    doc = pymupdf.open(stream=_pdf("text"), filetype="pdf")
    khoa = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256,
                       owner_pw="o", user_pw="u")
    r = _kiem(classify_bytes(khoa, "khoa.pdf"))
    assert r["kind"] == "unreadable" and "mật khẩu" in r["error"]


# ── DOCX ───────────────────────────────────────────────────────────────────

def test_docx_text():
    r = _kiem(classify_bytes(_docx(LOREM), "hd.docx"))
    assert (r["kind"], r["route"], r["confidence"]) == ("docx_text", "read_direct", 1.0)
    assert r["pages"][0]["kind"] == "text_layer"
    assert r["signals"]["images"] == 0


def test_docx_chi_la_anh():
    r = _kiem(classify_bytes(_docx("", _anh_drawing(*_A4_EMU)), "tin nhan.docx"))
    assert (r["kind"], r["route"]) == ("docx_image_only", "ocr")
    assert r["pages_needing_ocr"] == [0]
    assert r["pages"][0]["image_cover"] == pytest.approx(1.0, abs=0.01)
    assert r["confidence"] == 1.0


def test_docx_lai():
    r = _kiem(classify_bytes(_docx(LOREM, _anh_drawing(3780000, 2400000)), "x.docx"))
    assert (r["kind"], r["route"]) == ("docx_hybrid", "ocr")
    assert r["pages"][0]["kind"] == "mixed"


def test_docx_logo_nho_van_la_text():
    """Logo dưới 1% trang là vệt trang trí — cùng ngưỡng với trang PDF."""
    r = _kiem(classify_bytes(_docx(LOREM, _anh_drawing(500000, 500000)), "x.docx"))
    assert (r["kind"], r["route"]) == ("docx_text", "read_direct")
    assert r["signals"]["images"] == 1


def test_docx_hinh_ve_khong_blip_khong_phai_anh():
    ve = ('<w:r><w:drawing><wp:inline><wp:extent cx="7560000" cy="10692000"/>'
          '</wp:inline></w:drawing></w:r>')
    r = _kiem(classify_bytes(_docx(LOREM, ve), "x.docx"))
    assert r["kind"] == "docx_text" and r["signals"]["images"] == 0


def test_docx_anh_vml():
    vml = ('<w:r><w:pict><v:shape style="width:595pt;height:842pt">'
           '<v:imagedata/></v:shape></w:pict></w:r>')
    r = _kiem(classify_bytes(_docx("", vml), "cu.docx"))
    assert r["kind"] == "docx_image_only"
    assert r["pages"][0]["image_cover"] > 0.9


def test_docx_rong_de_agent_xem():
    r = _kiem(classify_bytes(_docx(""), "rong.docx"))
    assert (r["kind"], r["route"], r["confidence"]) == ("docx_text", "agent_context", 1.0)
    assert r["pages"][0]["kind"] == "blank"


def _hop_chu(ben_trong: str, *, cx: int, cy: int, du_phong: str) -> str:
    """Hộp chữ như Word lưu: bản DrawingML trong Choice, bản VML trong Fallback."""
    return (f'<w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:drawing>'
            f'<wp:anchor><wp:extent cx="{cx}" cy="{cy}"/><a:graphic><a:graphicData>'
            f'<wps:wsp><wps:txbx><w:txbxContent><w:p>{ben_trong}</w:p>'
            f'</w:txbxContent></wps:txbx></wps:wsp></a:graphicData></a:graphic>'
            f'</wp:anchor></w:drawing></mc:Choice><mc:Fallback><w:pict>'
            f'<v:shape style="width:595pt;height:842pt"><v:textbox><w:txbxContent>'
            f'<w:p>{du_phong}</w:p></w:txbxContent></v:textbox></v:shape></w:pict>'
            f'</mc:Fallback></mc:AlternateContent></w:r>')


def test_docx_hop_chu_choice_fallback_dem_mot_lan():
    chu = "<w:r><w:t>Số hồ sơ 001099000001 ngày 01/02</w:t></w:r>"
    r = _kiem(classify_bytes(_docx("", _hop_chu(chu, cx=3000000, cy=1000000,
                                                du_phong=chu)), "hop.docx"))
    assert r["pages"][0]["chars"] == len("Số hồ sơ 001099000001 ngày 01/02")
    assert r["signals"]["images"] == 0
    assert r["route"] == "agent_context"


def test_docx_hop_chu_boc_anh_dem_anh_mot_lan():
    anh = _anh_drawing(_A4_EMU[0], _A4_EMU[1] // 2)
    vml = '<w:r><w:pict><v:shape style="width:595pt;height:421pt"><v:imagedata/></v:shape></w:pict></w:r>'
    r = _kiem(classify_bytes(_docx(LOREM, _hop_chu(anh, cx=_A4_EMU[0], cy=_A4_EMU[1],
                                                   du_phong=vml)), "hop.docx"))
    assert r["signals"]["images"] == 1
    assert r["pages"][0]["image_cover"] == pytest.approx(0.5, abs=0.01)
    assert r["kind"] == "docx_hybrid"


def test_docx_xml_hong():
    r = _kiem(classify_bytes(_docx(xml="<w:document><khong dong"), "hong.docx"))
    assert (r["kind"], r["route"], r["confidence"]) == ("unreadable", "agent_context", 0.0)


# ── ẢNH ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("n, route, conf", [
    (0, "agent_context", 1.0),
    (1, "agent_context", 0.792),
    (2, "ocr", 0.708),
    (3, "ocr", 1.0),
    (40, "ocr", 1.0),
])
def test_anh_theo_so_vung_chu(monkeypatch, n, route, conf):
    monkeypatch.setattr(api, "_bo_do_chu", lambda: _do_gia(n))
    r = _kiem(classify_bytes(_png_canh(), "anh.jpg"))
    assert (r["kind"], r["route"]) == ("image", route)
    assert r["confidence"] == pytest.approx(conf, abs=0.002)
    assert r["signals"]["text_regions"] == n


def test_anh_khong_co_bo_do_thi_ocr_nua_tin(monkeypatch):
    monkeypatch.setattr(api, "_bo_do_chu", lambda: None)
    r = _kiem(classify_bytes(_png_chu(), "x.png"))
    assert (r["route"], r["confidence"]) == ("ocr", 0.5)
    assert r["signals"]["text_regions"] is None


def test_heic_khong_giai_ma_duoc_van_co_ket_qua(monkeypatch):
    monkeypatch.setattr(api, "_bo_do_chu", lambda: _do_gia(5))
    heic = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 64
    r = _kiem(classify_bytes(heic, "IMG_0001.HEIC"))
    assert (r["kind"], r["source"]["format"]) == ("image", "heic")
    assert (r["route"], r["confidence"]) == ("ocr", 0.5)


def test_bo_do_that_phan_biet_giay_to_va_canh():
    pytest.importorskip("rapidocr_onnxruntime")
    if api._bo_do_chu() is None:
        pytest.skip("RapidOCR không nạp được model")
    giay = _kiem(classify_bytes(_png_chu(), "cccd.png"))
    assert giay["route"] == "ocr" and giay["signals"]["text_regions"] >= 2
    canh = _kiem(classify_bytes(_png_canh(), "canh.jpg"))
    assert canh["route"] == "agent_context"


# ── còn lại: văn bản, không hỗ trợ, hỏng ───────────────────────────────────

def test_van_ban_thuan():
    r = _kiem(classify_bytes(LOREM.encode("utf-8"), "ghi_chu.txt"))
    assert (r["kind"], r["route"], r["confidence"]) == ("text", "read_direct", 1.0)


def test_van_ban_gan_trong_de_agent_xem():
    r = _kiem(classify_bytes("  \n ok \n".encode("utf-8"), "ghi_chu.txt"))
    assert (r["kind"], r["route"]) == ("text", "agent_context")
    assert r["pages"][0]["kind"] == "blank"


@pytest.mark.parametrize("data, fmt", [
    (b"", "empty"),
    (b"PK\x03\x04 zip bi cat cut", "zip"),
])
def test_dau_vao_hong(data, fmt):
    r = _kiem(classify_bytes(data, "x"))
    assert (r["kind"], r["route"], r["confidence"]) == ("unreadable", "agent_context", 0.0)
    assert r["source"]["format"] == fmt and r["error"]


def _zip(member: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(member, "<x/>")
    return buf.getvalue()


@pytest.mark.parametrize("data, fmt", [
    (_zip("xl/workbook.xml"), "xlsx"),
    (_zip("ppt/presentation.xml"), "pptx"),
    (_zip("khac.txt"), "zip"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504, "ole"),
    (bytes(range(256)) * 8, "unknown"),
])
def test_dinh_dang_chua_ho_tro(data, fmt):
    r = _kiem(classify_bytes(data, "x"))
    assert (r["kind"], r["route"], r["confidence"]) == ("unsupported", "agent_context", 0.0)
    assert r["source"]["format"] == fmt and r["error"] is None


def test_khong_bao_gio_nem(monkeypatch):
    def no(*a, **k):
        raise RuntimeError("hỏng giả")
    monkeypatch.setattr(api, "_pdf", no)
    r = _kiem(classify_bytes(_pdf("text"), "x.pdf"))
    assert r["kind"] == "unreadable" and "hỏng giả" in r["error"]


def test_classify_path(tmp_path):
    nfd = unicodedata.normalize("NFD", "Hợp đồng.pdf")
    f = tmp_path / nfd
    f.write_bytes(_pdf("text"))
    r = _kiem(classify_path(f))
    assert r["source"]["name"] == unicodedata.normalize("NFC", "Hợp đồng.pdf")
    assert r["kind"] == "born_digital_pdf"

    r = _kiem(classify_path(tmp_path / "khong_co.pdf"))
    assert r["kind"] == "unreadable" and r["confidence"] == 0.0


# ── độ tin cậy ─────────────────────────────────────────────────────────────

def _conf_pdf(chars, cover):
    return _tin_cay(_do_ben(_pdf_route, chars, cover, _PDF_RANH_CHARS, _PDF_RANH_COVER))


@pytest.mark.parametrize("chars, cover, conf", [
    (0, 0.0, 1.0),        # trang trắng: hai cực
    (0, 0.9, 1.0),        # scan thuần
    (2000, 0.0, 1.0),     # văn bản số
    (6, 0.55, 0.569),     # ảnh phủ 55%, sát ngưỡng 50%
    (310, 0.45, 0.576),   # văn bản 310 ký tự, ảnh 45%
    (299, 0.6, 0.501),    # đúng mép 300 ký tự
])
def test_do_tin_cay_pdf(chars, cover, conf):
    assert _conf_pdf(chars, cover) == pytest.approx(conf, abs=0.001)


def test_do_tin_cay_dung_nghia_nhan_doi():
    """Định nghĩa: dịch tín hiệu ít hơn d lần nhân đôi thì KHÔNG đổi đường."""
    for chars in (0, 1, 5, 30, 49, 50, 120, 250, 299, 300, 450, 800, 5000):
        for cover in (0.0, 0.005, 0.02, 0.2, 0.3, 0.45, 0.5, 0.7, 1.0):
            d = _do_ben(_pdf_route, chars, cover, _PDF_RANH_CHARS, _PDF_RANH_COVER)
            goc = _pdf_route(chars, cover)
            for t in (0.0, 0.25, 0.5, 0.75, 0.99):
                buoc = d * t
                for sa in (-1, 0, 1):
                    for sb in (-1, 0, 1):
                        # Ranh giới đếm nguyên nằm ở nửa số (299,5), nên
                        # tín hiệu dịch đi được làm tròn về số nguyên GẦN NHẤT.
                        c2 = round(chars * 2 ** (sa * buoc))
                        v2 = min(cover * 2 ** (sb * buoc), 1.0)
                        assert _pdf_route(c2, v2) == goc, (chars, cover, d, t, sa, sb)


def test_route_luon_nam_trong_ba_duong():
    assert set(ROUTES) == {"read_direct", "ocr", "agent_context"}
    assert set(SCHEMA["$defs"]["route"]["enum"]) == set(ROUTES)


# ── server ─────────────────────────────────────────────────────────────────

def _server():
    spec = importlib.util.spec_from_file_location(
        "serve_classify", ROOT / "scripts" / "serve_classify.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def sc():
    return _server()


@pytest.fixture
def client(sc):
    from fastapi.testclient import TestClient
    return TestClient(sc.app, base_url="http://127.0.0.1")


def test_server_tai_len(client):
    r = client.post("/api/classify", params={"filename": "scan.pdf"},
                    content=_pdf("scan"),
                    headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 200
    body = _kiem(r.json())
    assert body["kind"] == "scanned_pdf" and body["source"]["name"] == "scan.pdf"


def test_server_tep_rong_van_200(client):
    r = client.post("/api/classify", content=b"")
    assert r.status_code == 200 and _kiem(r.json())["kind"] == "unreadable"


def test_server_duong_dan(client, tmp_path):
    f = tmp_path / "hd.docx"
    f.write_bytes(_docx(LOREM))
    r = client.post("/api/classify", json={"path": str(f)})
    assert r.status_code == 200 and _kiem(r.json())["kind"] == "docx_text"


@pytest.mark.parametrize("body, ma", [
    ({"path": "tuong/doi.pdf"}, 400),
    ({"path": "/khong/co/tep/nay.pdf"}, 404),
    ({"path": "/"}, 400),
    ({"duong_dan": "/x"}, 422),
    ({"path": "/x", "them": 1}, 422),
])
def test_server_duong_dan_sai(client, body, ma):
    assert client.post("/api/classify", json=body).status_code == ma


def test_server_tu_choi_multipart(client):
    """FormData của trình duyệt/Next: thân là ranh giới multipart, không phải byte tệp."""
    r = client.post("/api/classify", files={"file": ("a.jpg", _png_canh(), "image/jpeg")})
    assert r.status_code == 415
    assert "?filename=" in r.json()["detail"]


def test_server_json_hong(client):
    r = client.post("/api/classify", content=b"{khong phai json",
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_server_qua_tran(client, sc, monkeypatch, tmp_path):
    monkeypatch.setattr(sc, "MAX_BYTES", 100)
    r = client.post("/api/classify", content=b"x" * 101,
                    headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 413
    f = tmp_path / "to.pdf"
    f.write_bytes(b"x" * 101)
    assert client.post("/api/classify", json={"path": str(f)}).status_code == 413


def test_server_chan_host_la(sc):
    """DNS rebinding: tên miền lạ trỏ về 127.0.0.1 phải bị từ chối."""
    from fastapi.testclient import TestClient
    r = TestClient(sc.app, base_url="http://evil.example").post(
        "/api/classify", content=b"abc")
    assert r.status_code == 400


def test_server_phuc_vu_schema(client):
    r = client.get("/api/classify/schema")
    assert r.status_code == 200 and r.json() == SCHEMA


@pytest.mark.parametrize("argv, port", [([], 8812), (["--port", "9123"], 9123)])
def test_server_chi_nghe_localhost(sc, monkeypatch, argv, port):
    """Endpoint nhận đường dẫn bất kỳ trên đĩa: host ghi cứng, không cờ nào đổi được."""
    import uvicorn
    goi = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: goi.append((app, kw)))
    monkeypatch.setattr("sys.argv", ["serve_classify.py", *argv])
    sc.main()
    assert len(goi) == 1
    app, kw = goi[0]
    assert app is sc.app
    assert kw["host"] == "127.0.0.1" and kw["port"] == port


@pytest.mark.parametrize("argv", [["--host", "0.0.0.0"], ["--tailnet"]])
def test_server_tu_choi_co_doi_host(sc, monkeypatch, argv):
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: pytest.fail("không được chạy"))
    monkeypatch.setattr("sys.argv", ["serve_classify.py", *argv])
    with pytest.raises(SystemExit):
        sc.main()


def test_pdf_song_song_giong_tuan_tu():
    """Server chạy request trong threadpool: phân loại song song phải khớp tuần tự."""
    from concurrent.futures import ThreadPoolExecutor
    tep = [_pdf(*m) for m in (["text", "text"], ["scan"], ["text", "scan", "blank"],
                              ["blank"], ["scan", "scan", "text"])] * 4
    tuan_tu = [classify_bytes(d, "x.pdf") for d in tep]
    with ThreadPoolExecutor(max_workers=8) as ex:
        song_song = list(ex.map(lambda d: classify_bytes(d, "x.pdf"), tep))
    assert song_song == tuan_tu
