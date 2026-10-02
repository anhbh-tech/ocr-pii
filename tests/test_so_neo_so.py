"""Sổ neo số: số trong tệp hội thoại nối về hồ sơ trước khi so chữ.

Mọi nhãn, số, đường dẫn và câu chat ở đây là bịa; chữ hỏng dấu cũng bịa theo
kiểu OCR hay làm. Không đưa số thật của hồ sơ vào kho git.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import stat
import unicodedata

from ocr_lab import danh_tinh as dt
from ocr_lab.ade_store import doc_id_for


def _nap():
    """`scripts/` không phải package nên không import theo tên được."""
    p = pathlib.Path(__file__).parent.parent / "scripts" / "so_neo_so.py"
    spec = importlib.util.spec_from_file_location("so_neo_so_thu", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


nn = _nap()

HO_SO_A = "Phòng IP/1. Đăng ký/911.US. VOLPIX IN CLASS 025"
HO_SO_B = "Phòng IP/1. Đăng ký/912.US. KRENDO IN CLASS 009"
SERIAL_A, VAN_BANG_A, VAN_BANG_B = "97000001", "6900001", "5800002"
HOA_DON = "30000077"                 # dòng nhạy cảm trong sổ số hiệu
MA_GIAO_DICH = "4455667"             # không có trong sổ, không nhãn
VAN_BANG_LA = "4455668"              # không có trong sổ, có nhãn USPTO
VAN_BANG_HONG = "6900007"            # OCR đọc nhầm một chữ số của VAN_BANG_A

CHAT = f"{HO_SO_A}/5. Tin nhan/anh chat.png"
CHAT_KHAC = f"{HO_SO_A}/5. Tin nhan/anh chat 2.png"
FILING_A = f"{HO_SO_A}/1. Filing/Filing receipt.pdf"
TSDR_B = f"{HO_SO_B}/0. Info/TSDR.pdf"

SACH = "\n".join([
    "VOLPIX x REFINY",
    "3 thành viên",
    "Khách: bên em kiểm tra giúp khả năng đăng ký sản phẩm nhóm 025 với ạ",
    f"REFINY: đơn số {SERIAL_A} đã nộp, văn bằng số {VAN_BANG_B}, đăng ký cho các sản phẩm nhóm 009 là của nhãn khác",
    f"Văn bằng số {VAN_BANG_A} của mình ạ",
    f"Hóa đơn {HOA_DON} đã gửi, mã giao dịch {MA_GIAO_DICH} nhé",
    f"Registration No. {VAN_BANG_LA} là nhãn khác",
    "Còn nhóm 041 thì sao ạ",
    "https://x.example/p/86420975 và mã 1a2b3c4d86420975 và 864209753 và nhóm 050",
    "U.S. Class(es): 002, 039 · International Class(es): 025",
])
# Cùng ảnh chụp, bản parse chuẩn: dấu hỏng, chữ số sống — trừ một chữ số.
HONG = (SACH.replace("khả năng đăng ký sản phẩm", "khä năng dăng ký sän phấm")
        .replace("đã nộp", "dã nộp").replace("đăng ký cho các sản phẩm", "dăng ký cho các sän phấm")
        .replace(f"số {VAN_BANG_A}", f"số {VAN_BANG_HONG}"))


def _dong(ho_so, loai, bang, chuan, lan):
    return {"ho_so": ho_so, "ma_ho_so": ho_so.split(".")[0], "loai": loai, "bang": bang,
            "chuan": chuan, "gia_tri": chuan, "chu_so_huu": "ta", "nhan_hieu": "BỊA",
            "lan_xuat_hien": [{"doc_id": doc_id_for(t), "tep": t} for t in lan]}


def _so_danh_tinh():
    return dt.dung_so([(n, f"bam{i}") for i, n in enumerate([CHAT, CHAT_KHAC, FILING_A, TSDR_B])],
                      doc_id_for=doc_id_for)


def _ho_so(so_dt, thu_muc):
    return next(h["ho_so"] for h in so_dt["ho_so"] if h.get("thu_muc") and thu_muc.endswith(h["thu_muc"]))


def _so_hieu(so_dt):
    a, b = _ho_so(so_dt, HO_SO_A), _ho_so(so_dt, HO_SO_B)
    return [
        _dong(a, "so_don_uspto", "cong_khai", SERIAL_A, [FILING_A, CHAT, CHAT_KHAC]),
        _dong(a, "so_van_bang_uspto", "cong_khai", VAN_BANG_A, [FILING_A]),
        _dong(b, "so_van_bang_uspto", "cong_khai", VAN_BANG_B, [TSDR_B]),
        _dong(a, "so_hoa_don", "nhay_cam", HOA_DON, [FILING_A]),
    ]


def _dung_kho(tmp_path, ban=(("pro", SACH), ("chuan", HONG))):
    """ade_out có ảnh chat (hai bản parse) và sổ danh tính + số hiệu bịa."""
    kho, so = tmp_path / "ade_out", tmp_path / "so"
    d = kho / doc_id_for(CHAT)
    d.mkdir(parents=True)
    tep = {"pro": ("meta_pro.json", "parse_pro.json"), "chuan": ("meta.json", "parse.json")}
    for ten, md in ban:
        meta, parse = tep[ten]
        # meta ghi đường dẫn NFD như Finder trả; vẫn phải khớp sổ danh tính
        (d / meta).write_text(json.dumps({"source": unicodedata.normalize("NFD", CHAT)}), "utf-8")
        (d / parse).write_text(json.dumps({"markdown": md}, ensure_ascii=False), "utf-8")
    so_dt = _so_danh_tinh()
    (so / "kenh" / "hoi_thoai").mkdir(parents=True)
    (so / "hang_cho_xung_dot.jsonl").write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in so_dt.pop("hang_cho_xung_dot")), "utf-8")
    (so / "danh_tinh.json").write_text(json.dumps(so_dt, ensure_ascii=False), "utf-8")
    (so / "so_hieu.json").write_text(json.dumps({"so_hieu": _so_hieu(so_dt)}, ensure_ascii=False), "utf-8")
    (so / "kenh" / "hoi_thoai" / "k1.json").write_text(json.dumps({"tin": [
        {"doc_id": doc_id_for(CHAT), "ban_trung": [{"doc_id": doc_id_for(CHAT_KHAC)}]}]}), "utf-8")
    return kho, so, so_dt


def _gia_tri(md):
    return [(x["hinh"], x["gia_tri"]) for x in nn.boc_so(md)]


# --------------------------------------------------------------------------
# Bước 1: bóc số
# --------------------------------------------------------------------------

def test_boc_so_khong_can_nhan_va_chan_bien():
    ra = _gia_tri(SACH)
    so = [v for h, v in ra if h != nn.NHOM_NICE]
    assert so == [SERIAL_A, VAN_BANG_B, VAN_BANG_A, HOA_DON, MA_GIAO_DICH, VAN_BANG_LA]
    # phẩy sau số vẫn bắt; URL, mã hex, dãy 9 chữ số thì không
    assert "86420975" not in so and "864209753" not in so


def test_boc_so_van_bang_co_phay_ngan_nghin():
    assert _gia_tri("Reg. No. 6,900,001; serial 97000001.") == [
        (nn.SO_VAN_BANG, VAN_BANG_A), (nn.SO_DON, SERIAL_A)]


def test_nhom_nice_trong_001_045_va_bo_day_us_class():
    nhom = [v for h, v in _gia_tri(SACH) if h == nn.NHOM_NICE]
    # 025 hai lần (câu khách + International Class), 009, 041; không 050, 002, 039
    assert nhom == ["025", "009", "041", "025"]


# --------------------------------------------------------------------------
# Bước 3: so chữ bỏ dấu cả hai phía
# --------------------------------------------------------------------------

def test_so_chu_bo_dau_ca_hai_phia():
    assert nn.co_chua("khả năng đăng ký sản phẩm", "khä năng dăng ký sän phấm")
    assert nn.co_chua("Văn bằng", "van bang")
    assert not nn.co_chua("đăng ký", "dang kiem")


def test_nhan_uspto_tim_sau_khi_bo_dau():
    trich = f"văn bằng bảo hộ số {VAN_BANG_LA}"
    assert nn.nhan_truoc(trich, trich.index(VAN_BANG_LA), nn.SO_VAN_BANG) == "VAN BANG"
    trich = f"mã giao dịch {MA_GIAO_DICH}"
    assert nn.nhan_truoc(trich, trich.index(MA_GIAO_DICH), nn.SO_VAN_BANG) is None


def test_lop_cua_ho_so_tu_ten_thu_muc():
    assert nn.lop_cua_ho_so(HO_SO_A) == {"025"}
    assert nn.lop_cua_ho_so("913.US. BỊA in class 9, 16") == {"009", "016"}
    assert nn.lop_cua_ho_so(None) == set()


# --------------------------------------------------------------------------
# Tệp hội thoại
# --------------------------------------------------------------------------

def test_tep_hoi_thoai_la_hop_cac_so_va_bo_tep_tron(tmp_path):
    (tmp_path / "kenh" / "hoi_thoai").mkdir(parents=True)
    (tmp_path / "kenh" / "hoi_thoai" / "k.json").write_text(json.dumps(
        {"tin": [{"doc_id": "a", "ban_trung": [{"doc_id": "b"}]}]}))
    (tmp_path / "hinh_thuc.json").write_text(json.dumps({"tai_lieu": [
        {"id": "a", "tin_hieu": {"khung_chat": True, "cau_truc": "don"}},
        {"id": "c", "tin_hieu": {"khung_chat": True, "cau_truc": "tron"}},
        {"id": "d", "tin_hieu": {"khung_chat": False, "cau_truc": "don"}}]}))
    (tmp_path / "ban_sach_vs_anh.json").write_text(json.dumps({"cap_ban_sach": [
        {"quan_he": "anh_chup_chat", "nguon": [{"vai_tro": "anh_chup", "doc_id": "e"},
                                               {"vai_tro": "ban_sach", "doc_id": "f"}]},
        {"quan_he": "ban_quet", "nguon": [{"vai_tro": "anh_chup", "doc_id": "g"}]}]}))
    ra, co_mat = nn.tep_hoi_thoai(tmp_path)
    assert ra == {"a": ["hinh_thuc_khung_chat", "so_kenh"], "b": ["so_kenh"],
                  "e": ["ban_sach_anh_chup_chat"]}
    assert co_mat == {"so_kenh": True, "hinh_thuc": True, "vai_anh": False, "ban_sach_vs_anh": True}


# --------------------------------------------------------------------------
# Bước 2 và cả sổ
# --------------------------------------------------------------------------

def _tep(so):
    (t,) = so["tep"]
    return {(g["hinh"], g["gia_tri"] or f"?{g['so_chu_so']}"): g for g in t["so"]}, \
        {g["gia_tri"]: g for g in t["nhom_nice"]}, t


def test_so_noi_ve_ho_so_va_tep_ho_so(tmp_path):
    kho, so_dir, so_dt = _dung_kho(tmp_path)
    so = nn.dung(kho, so_dir)
    a, b = _ho_so(so_dt, HO_SO_A), _ho_so(so_dt, HO_SO_B)
    so_, nhom, t = _tep(so)
    assert t["ho_so"] == [a] and t["nhan_dien"] == ["so_kenh"]

    (noi,) = so_[(nn.SO_DON, SERIAL_A)]["noi"]
    assert noi["ho_so"] == a and noi["cung_ho_so_voi_tep"]
    assert noi["tep_ho_so"] == [unicodedata.normalize("NFC", FILING_A)]
    assert noi["tep_hoi_thoai_khac"] == [unicodedata.normalize("NFC", CHAT_KHAC)]
    assert so_[(nn.SO_DON, SERIAL_A)]["ban_parse"] == ["pro", "chuan"]
    # số của nhãn đối chứng nối sang hồ sơ khác, không phải hồ sơ của tệp
    (noi,) = so_[(nn.SO_VAN_BANG, VAN_BANG_B)]["noi"]
    assert noi["ho_so"] == b and not noi["cung_ho_so_voi_tep"]
    assert noi["tep_ho_so"] == [unicodedata.normalize("NFC", TSDR_B)]


def test_so_nhay_cam_va_so_tron_khong_mang_gia_tri(tmp_path):
    kho, so_dir, _ = _dung_kho(tmp_path)
    so = nn.dung(kho, so_dir)
    so_, _, _ = _tep(so)
    giu = [g for g in so_.values() if g["ket_qua"] == "bi_giu"]
    assert [(g["gia_tri"], g["so_chu_so"], g["bang"]) for g in giu] == [(None, 8, ["nhay_cam"])]
    tron = [g for g in so_.values() if g["ket_qua"] == "chua_noi" and not g.get("nhan")]
    assert [(g["gia_tri"], g["so_chu_so"]) for g in tron] == [(None, 7)]
    assert so_[(nn.SO_VAN_BANG, VAN_BANG_LA)]["nhan"] == "REGISTRATION"
    ghi = json.dumps(so, ensure_ascii=False)
    assert HOA_DON not in ghi and MA_GIAO_DICH not in ghi


def test_so_hong_mot_chu_so_la_nghi_hong_ocr(tmp_path):
    kho, so_dir, so_dt = _dung_kho(tmp_path)
    so_, _, _ = _tep(nn.dung(kho, so_dir))
    g = so_[(nn.SO_VAN_BANG, VAN_BANG_HONG)]
    assert g["ket_qua"] == "nghi_hong_ocr" and g["gan_voi"] == VAN_BANG_A
    assert g["ho_so"] == [_ho_so(so_dt, HO_SO_A)] and g["ban_parse"] == ["chuan"]
    assert so_[(nn.SO_VAN_BANG, VAN_BANG_A)]["ban_parse"] == ["pro"]


def test_nhom_nice_noi_theo_ho_so_hoac_theo_so_dung_truoc(tmp_path):
    kho, so_dir, so_dt = _dung_kho(tmp_path)
    _, nhom, _ = _tep(nn.dung(kho, so_dir))
    assert nhom["025"]["cach"] == ["nhom_ho_so"] and nhom["025"]["ho_so"] == [_ho_so(so_dt, HO_SO_A)]
    assert nhom["025"]["lan_nhac"] == 2
    assert nhom["009"]["cach"] == ["theo_so"] and nhom["009"]["theo_so"] == [VAN_BANG_B]
    assert nhom["009"]["ho_so"] == [_ho_so(so_dt, HO_SO_B)]
    assert nhom["041"]["ket_qua"] == "chua_noi"


def test_chung_minh_chu_co_dau_truot_ma_so_van_noi(tmp_path):
    kho, so_dir, _ = _dung_kho(tmp_path)
    so = nn.dung(kho, so_dir)
    lech = [c for c in so["chung_minh"] if not c["khop_co_dau"] and c["khop_bo_dau"] and c["khop_so"]]
    assert {(c["hinh"], c["gia_tri"]) for c in lech} >= {(nn.NHOM_NICE, "025"), (nn.SO_DON, SERIAL_A)}
    c = next(c for c in lech if c["gia_tri"] == SERIAL_A)
    assert (c["ban_goc"], c["ban_so"]) == ("pro", "chuan")
    assert "đã nộp" in c["cum_goc"] and "dã nộp" in c["cum_ban_so"]
    assert so["tom_tat"]["chung_minh"]["lech_chi_vi_dau_ma_so_van_noi"] == len(lech)


def test_cum_chung_minh_che_so_khac():
    assert nn.che_so_khac(f"số {SERIAL_A} và {HOA_DON}, 6,900,001 nhóm 025", SERIAL_A) == \
        f"số {SERIAL_A} và [so], [so] nhóm 025"


def test_mot_ban_parse_thi_khong_co_chung_minh(tmp_path):
    kho, so_dir, _ = _dung_kho(tmp_path, ban=(("pro", SACH),))
    so = nn.dung(kho, so_dir)
    assert so["chung_minh"] == []
    assert so["tom_tat"]["so"]["theo_ket_qua"]["da_noi"] == 3


def test_main_ghi_so_0600_va_chi_in_so_dem(tmp_path, capsys):
    kho, so_dir, _ = _dung_kho(tmp_path)
    ra = tmp_path / "rieng" / "neo_so.json"
    assert nn.main(["--ade-out", str(kho), "--so", str(so_dir), "--ra", str(ra)]) == 0
    assert stat.S_IMODE(ra.stat().st_mode) == 0o600
    assert stat.S_IMODE(ra.parent.stat().st_mode) == 0o700
    ket = json.loads(ra.read_text("utf-8"))
    assert ket["tom_tat"]["tep_hoi_thoai"] == 2 and ket["khong_co_parse"] == [doc_id_for(CHAT_KHAC)]
    out = capsys.readouterr().out
    for bi_mat in (SERIAL_A, VAN_BANG_A, VAN_BANG_B, HOA_DON, MA_GIAO_DICH, "VOLPIX", "khả năng"):
        assert bi_mat not in out


def test_cum_chung_minh_che_so_dien_thoai_tach_nhom():
    for dt_ in ("0907 318 264", "0907.318.264", "0907-318-264"):
        assert nn.che_so_khac(f"đơn số {SERIAL_A}, liên hệ {dt_}", SERIAL_A) == \
            f"đơn số {SERIAL_A}, liên hệ [so]"
    assert nn.che_so_khac(f"số {SERIAL_A} 0907 318 264", SERIAL_A) == f"số {SERIAL_A} [so]"
    assert nn.che_so_khac("nhóm 009 0907 318 264 năm 2025", "009") == "nhóm 009 [so] năm 2025"


def test_nhan_dang_ky_quoc_te_hay_nuoc_ngoai_khong_la_van_bang_uspto():
    for trich in (f"International Registration {VAN_BANG_LA}",
                  f"Foreign registration number {VAN_BANG_LA}"):
        assert nn.nhan_truoc(trich, trich.index(VAN_BANG_LA), nn.SO_VAN_BANG) is None
    trich = f"Registration No. {VAN_BANG_LA}"
    assert nn.nhan_truoc(trich, trich.index(VAN_BANG_LA), nn.SO_VAN_BANG) == "REGISTRATION"


def test_cum_quanh_neo_dung_tu_khong_neo_vao_ngay():
    md = "Ngày 12/10/2009 khách hỏi về nhóm 009 ạ"
    assert nn.cum_quanh(md, "009", 1) == "khách hỏi về nhóm 009 ạ"


def test_khop_so_tinh_theo_chinh_ban_so(tmp_path):
    # bản chuẩn đọc hỏng số văn bằng đứng trước nhóm 009: ở bản đó 009 không nối
    hong = HONG.replace(f"số {VAN_BANG_B}", "số 5800007")
    kho, so_dir, _ = _dung_kho(tmp_path, ban=(("pro", SACH), ("chuan", hong)))
    so = nn.dung(kho, so_dir)
    _, nhom, _ = _tep(so)
    assert nhom["009"]["da_noi_o_ban"] == ["pro"]
    (c,) = [c for c in so["chung_minh"] if c["gia_tri"] == "009"]
    assert c["ban_so"] == "chuan" and not c["khop_co_dau"] and c["khop_bo_dau"] and not c["khop_so"]
    lech = [c for c in so["chung_minh"] if not c["khop_co_dau"] and c["khop_bo_dau"] and c["khop_so"]]
    assert so["tom_tat"]["chung_minh"]["lech_chi_vi_dau_ma_so_van_noi"] == len(lech)
