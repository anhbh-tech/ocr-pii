"""Agent hình thức & số hiệu: lời nhắc, kiểm dòng trích, đối chiếu sổ, ghi ngược.

Toàn bộ dữ liệu ở đây là bịa — hồ sơ, nhãn hiệu, số đơn đều không có thật.
Không test nào gọi model: `goi` là hàm giả trả câu trả lời dựng sẵn.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def _nap():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "agent_hinh_thuc_test", ROOT / "scripts" / "agent_hinh_thuc.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["agent_hinh_thuc_test"] = m
    spec.loader.exec_module(m)
    return m


aht = _nap()
ag = aht.ag

NHOM, SO_DO = "Nhóm ZZ", "zz.bpmn"
THU_MUC = "901. US. ZORBLAX in class 099"
REL_BC = f"Phòng/{NHOM}/{THU_MUC}/2. Tra cuu/901_Bao cao zz_010125.docx"
REL_B = f"Phòng/{NHOM}/{THU_MUC}/3. Phe duyet/901_Submission Information_010125.pdf"
KHOA_TC = "<Mã TV>_Bao cao zz_<ddmmyy>.docx"
KHOA_PD = "Phe duyet zz.eml"


def _muc(ten, nguyen_van):
    return {"ten": ten, "nguyen_van": nguyen_van, "trang_thai_bat_buoc": [], "ghi_chu": []}


SO_AX = {"anh_xa": {
    KHOA_TC: {"hoat_dong": [{"id": "N_9_1", "ten": "Tra cứu ZZ", "so_do": SO_DO}],
              "muc_bat_buoc": [_muc("bao cao zz", KHOA_TC)],
              "ten_goi_chap_nhan": [{"ten": "bao cao zz", "cho_muc": "bao cao zz",
                                     "phuong_phap": "exact", "nguon": [REL_BC]}],
              "nguon": [REL_BC]},
    KHOA_PD: {"hoat_dong": [{"id": "N_9_2", "ten": "Phê duyệt ZZ", "so_do": SO_DO}],
              "muc_bat_buoc": [_muc("phe duyet zz", KHOA_PD)],
              "ten_goi_chap_nhan": [], "nguon": []},
    "Khac.pdf": {"hoat_dong": [{"id": "N_8_1", "ten": "Sơ đồ khác", "so_do": "khac.bpmn"}],
                 "muc_bat_buoc": [_muc("khac", "Khac.pdf")],
                 "ten_goi_chap_nhan": [], "nguon": []},
}}

# Kiểu B: phiếu thông tin đã ký đứng thay email phê duyệt.
MD_B = "\n".join([
    "# SUBMISSION INFORMATION",
    "<a id='neo-1'></a>",
    "Mark: ZORBLAX",
    "Serial Number: 99000901",
    "Signature: /zz/ Date: 01/02/2025",
    "<table><tr><td>Class</td><td>099</td></tr></table>",
])

SO_HIEU = [
    {"ho_so": "HS901", "loai": "so_don_uspto", "gia_tri": "99000901", "chuan": "99000901",
     "bang": "cong_khai", "chu_so_huu": "ta"},
    {"ho_so": "HS901", "loai": "so_van_bang_uspto", "gia_tri": "7000901", "chuan": "7000901",
     "bang": "cong_khai", "chu_so_huu": "ta"},
    {"ho_so": "HS901", "loai": "so_don_uspto", "gia_tri": "99000902", "chuan": "99000902",
     "bang": "cong_khai", "chu_so_huu": "doi_chung"},
    {"ho_so": "HS901", "loai": "so_tai_khoan", "gia_tri": "1234500901", "chuan": "1234500901",
     "bang": "nhay_cam", "chu_so_huu": "ta"},
    {"ho_so": "HS902", "loai": "so_don_uspto", "gia_tri": "99000903", "chuan": "99000903",
     "bang": "cong_khai", "chu_so_huu": "ta"},
]
DANH_TINH = {"ho_so": [{"ho_so": "HS901", "ma": "901", "nhan": "ZORBLAX"}], "xung_dot": None}

TRA_LOI_B = {
    "loai_tai_lieu": {"gia_tri": "bieu_mau", "mo_ta": "phiếu đã ký", "dong": [1],
                      "trich": "SUBMISSION INFORMATION"},
    "buoc": {"hoat_dong": "N_9_2", "khoa": KHOA_PD, "ly_do": "phiếu ký thay email",
             "dong": [5], "trich": "Signature: /zz/"},
    "ten_tep": {"ket_luan": "khop", "ly_do": "", "dong": [1], "trich": "Submission Information"},
    "hinh_thuc": {"muc": "du_noi_dung_sai_hinh_thuc", "ly_do": "phiếu, không phải email",
                  "dong": [5], "trich": "Signature: /zz/"},
    "muc_bat_buoc": [{"muc": "phe duyet zz", "dap_ung": "co", "ly_do": "đã ký", "dong": [5],
                      "trich": "Signature: /zz/ Date: 01/02/2025"}],
    "so_hieu": [{"loai": "so_don_uspto", "gia_tri": "99000901", "chu_so_huu": "ta",
                 "ly_do": "Mark trùng nhãn hồ sơ", "dong": [3, 4],
                 "trich": "Mark: ZORBLAX Serial Number: 99000901"}],
    "ngay": [{"nhan": "ky", "gia_tri": "2025-01-02", "ly_do": "MM/DD/YYYY", "dong": [5],
              "trich": "Date: 01/02/2025"}],
    "do_chac": "cao", "ly_do_do_chac": "",
}


class GoiGia:
    def __init__(self, tra_loi):
        self.tra_loi, self.lan = tra_loi, []

    def __call__(self, he_thong, nguoi_dung):
        self.lan.append((he_thong, nguoi_dung))
        van_ban = self.tra_loi if isinstance(self.tra_loi, str) else json.dumps(self.tra_loi, ensure_ascii=False)
        return ag.PhanHoi(van_ban, "claude-sonnet-5", usd=0.0123,
                          token={"input_tokens": 3000, "output_tokens": 900}, thoi_gian_ms=1000)


@pytest.fixture(autouse=True)
def _quy_trinh(monkeypatch):
    monkeypatch.setitem(aht.so_anh_xa.QUY_TRINH, NHOM, SO_DO)


def _tl(md=MD_B, rel=REL_B):
    return {"doc_id": "d0000000000000b1", "nguon": rel, "engine": "pro", "markdown": md}


def _dau_vao(md=MD_B):
    return aht.dung_dau_vao(_tl(md), DANH_TINH, SO_AX, SO_HIEU)[0]


# ── dòng và lời nhắc ─────────────────────────────────────────────────────

def test_dong_noi_dung_giu_so_dong_cua_markdown():
    d = ag.dong_noi_dung(MD_B + "\nSố: <Chưa cấp số>")
    assert 2 not in d                       # dòng chỉ có neo: bỏ, số dòng không dồn
    assert d[3] == "Mark: ZORBLAX"
    assert d[6] == "Class | 099"
    assert d[7] == "Số: <Chưa cấp số>"      # không nhầm là thẻ HTML


def test_ten_tep_chi_nam_duoi_nhan_phong_doan_sau_noi_dung():
    _, nd = ag.dung_loi_nhac(_dau_vao())
    phong_doan = nd.index("# PHỎNG ĐOÁN TỪ TÊN TỆP")
    assert nd.index("# NỘI DUNG") < phong_doan
    assert nd.count("Submission Information_010125") == 1
    assert nd.index("Submission Information_010125") > phong_doan
    # Tên tệp không mang số dòng nên không trích được.
    assert not nd[phong_doan:].split("\n")[1].startswith("L")
    assert "L3| Mark: ZORBLAX" in nd


def test_so_hieu_gui_di_chi_so_co_mat_va_so_cong_khai_cua_ta():
    gui = {g["gia_tri"] for g in _dau_vao()["so_hieu"]}
    # 99000901 có trong tài liệu; 7000901 công khai của ta. Số đối chứng vắng
    # mặt, số tài khoản nhạy cảm vắng mặt, số của hồ sơ khác: không gửi.
    assert gui == {"99000901", "7000901"}


def test_buoc_ung_vien_chi_cua_so_do_ho_so():
    assert {b["hoat_dong"] for b in _dau_vao()["buoc_ung_vien"]} == {"N_9_1", "N_9_2"}


# ── kiểm từng khẳng định ─────────────────────────────────────────────────

def test_kiem_trich():
    d = ag.dong_noi_dung(MD_B)
    assert ag.kiem_trich({"dong": [3, 4], "trich": "ZORBLAX Serial Number"}, d) is None
    assert ag.kiem_trich({"dong": [2], "trich": "x"}, d).startswith("dòng không có")
    assert ag.kiem_trich({"trich": "Mark"}, d) == "không chỉ ra dòng"
    assert ag.kiem_trich({"dong": [1], "trich": "Serial"}, d) == "trích không nằm trong các dòng đã chỉ"
    assert ag.kiem_trich({"dong": [1], "trich": "“SUBMISSION  information”"[1:-1]}, d) is None


def test_kiem_trich_neo_lai_trich_lech_mot_dong():
    d = ag.dong_noi_dung(MD_B)
    kd = {"dong": [3], "trich": "ZORBLAX Serial Number"}     # trích vắt 3–4, model chỉ 3
    assert ag.kiem_trich(kd, d) is None
    assert (kd["dong"], kd["dong_goc"]) == ([3, 4], [3])
    kd = {"dong": [5], "trich": "Serial Number"}             # chỉ 5, trích ở 4
    assert ag.kiem_trich(kd, d) is None and kd["dong"] == [4]
    # Xa hơn một dòng thì không neo: bỏ.
    assert ag.kiem_trich({"dong": [6], "trich": "Serial Number"}, d) is not None


@pytest.mark.parametrize("iso,trich,duoc", [
    ("2025-03-05", "filed March 5, 2025", True),
    ("2025-03-05", "Mark 5 2025", False),          # "Mark" không phải tháng Ba
    ("2025-03-05", "_050325.pdf", True),           # ddmmyy dính liền
    ("2025-03-05", "ngày 5 tháng 3 năm 2025", True),
    ("2024-03-05", "March 5, 2025", False),        # năm bịa
    ("2025-01-02", "Date: 01/02/2025", True),
    ("2025-13-01", "Date: 13/01/2025", True),      # hình dạng ISO; lịch không kiểm
    ("05/03/2025", "05/03/2025", False),           # không phải ISO
    ("2025-05-25", "25/05/2019", False),           # ngày 25 không đứng thay năm 2025
    ("2025-05-25", "May 25, 25", True),            # không có năm 4 chữ số thì nhận 2 chữ số
])
def test_ngay_doc_lai_duoc(iso, trich, duoc):
    assert ag.ngay_doc_lai_duoc(iso, trich) is duoc


def test_kiem_chung_bo_khang_dinh_lay_tu_ten_tep():
    dv = _dau_vao()
    kq = ag.kiem_chung(copy.deepcopy(TRA_LOI_B), dv["dong"], dv["buoc_ung_vien"], {})
    # "Submission Information" (chữ thường) có trên tên tệp, trên dòng 1 thì
    # viết hoa — casefold cho qua. Đổi sang trích thật từ tên tệp thì bị bỏ.
    assert kq["ten_tep"]["ket_luan"] == "khop"
    tl = copy.deepcopy(TRA_LOI_B)
    tl["ten_tep"]["trich"] = "Submission Information_010125"
    tl["so_hieu"].append({"loai": "so_don_uspto", "gia_tri": "010125", "chu_so_huu": "ta",
                          "dong": [1], "trich": "Submission Information_010125"})
    kq = ag.kiem_chung(tl, dv["dong"], dv["buoc_ung_vien"], {})
    assert kq["ten_tep"] is None
    assert [s["gia_tri"] for s in kq["so_hieu"]] == ["99000901"]
    assert {b["truong"] for b in kq["bi_bo"]} == {"ten_tep", "so_hieu"}
    assert kq["do_chac"] == "vua"          # cao hạ một bậc khi có khẳng định bị bỏ


def test_kiem_chung_buoc_ngoai_bang_anh_xa_la_khong_nhan_ra():
    dv = _dau_vao()
    tl = copy.deepcopy(TRA_LOI_B)
    tl["buoc"]["hoat_dong"] = "N_8_1"      # có trong bảng ánh xạ nhưng khác sơ đồ
    kq = ag.kiem_chung(tl, dv["dong"], dv["buoc_ung_vien"], {})
    assert kq["buoc"]["hoat_dong"] is None
    assert kq["muc_bat_buoc"] == [] and kq["muc_khong_xet"] == []
    assert kq["do_chac"] == "thap"


def test_kiem_chung_so_hieu_bang_theo_loai_va_chua_cap_so():
    d = ag.dong_noi_dung("Số: <Chưa cấp số>\nSố HĐ: HD-901")
    tl = {"so_hieu": [
        {"loai": "so_hop_dong", "gia_tri": "<Chưa cấp số>", "chu_so_huu": "ta", "dong": [1],
         "trich": "Số: <Chưa cấp số>"},
        {"loai": "loai_la", "gia_tri": "HD-901", "chu_so_huu": "ta", "dong": [2], "trich": "HD-901"},
        {"loai": "so_hop_dong", "gia_tri": "HD-902", "chu_so_huu": "ta", "dong": [2], "trich": "HD-901"},
        {"loai": "so_hop_dong", "gia_tri": "HD-901", "chu_so_huu": "khach", "dong": [2], "trich": "HD-901"},
    ]}
    kq = ag.kiem_chung(tl, d, [], {"so_hop_dong": "nhay_cam"})
    assert [(s["gia_tri"], s["bang"], s["cong_khai"]) for s in kq["so_hieu"]] == [
        ("<Chưa cấp số>", "nhay_cam", False), ("HD-901", "chua_xep", False)]
    assert [b["ly_do"] for b in kq["bi_bo"] if b["truong"] == "so_hieu"] == [
        "số không nằm trong trích", "chủ ngoài miền: 'khach'"]


def test_kiem_chung_muc_con_thieu_va_khong_xet():
    buoc = [{"hoat_dong": "N_9_3", "ten": "", "khoa": "K",
             "muc": [_muc("a", "A"), _muc("b", "B"), _muc("c", "C")]}]
    d = {1: "A có", 2: "B trống:"}
    tl = {"buoc": {"hoat_dong": "N_9_3", "dong": [1], "trich": "A có"},
          "muc_bat_buoc": [
              {"muc": "a", "dap_ung": "co", "dong": [1], "trich": "A có"},
              {"muc": "b", "dap_ung": "thieu", "dong": [2], "trich": "B trống"},
              {"muc": "z", "dap_ung": "co", "dong": [1], "trich": "A"},
              {"muc": "a", "dap_ung": "co", "dong": [1], "trich": "A"}]}
    kq = ag.kiem_chung(tl, d, buoc, {})
    assert kq["buoc"]["khoa"] == "K"
    assert kq["muc_con_thieu"] == ["b"] and kq["muc_khong_xet"] == ["c"]
    assert [b["ly_do"] for b in kq["bi_bo"] if b["truong"] == "muc_bat_buoc"] == [
        "mục không thuộc bước đã nhận", "mục nói hai lần"]


# ── một lượt gọi ─────────────────────────────────────────────────────────

def test_chay_tu_choi_noi_dung_qua_tran_khong_goi():
    goi = GoiGia(TRA_LOI_B)
    dv = {**_dau_vao(), "dong": {1: "x" * (ag.TRAN_KY_TU + 1)}}
    kq = ag.chay(dv, goi, {})
    assert kq["cho_nguoi"] and "vượt trần" in kq["loi"] and goi.lan == []


def test_chay_doc_duoc_rao_json_va_ghi_chi_phi():
    goi = GoiGia("Đây:\n```json\n" + json.dumps(TRA_LOI_B) + "\n```")
    kq = ag.chay(_dau_vao(), goi, {"so_don_uspto": "cong_khai"})
    assert kq["do_chac"] == "cao" and not kq["cho_nguoi"] and kq["bi_bo"] == []
    assert kq["so_hieu"][0]["cong_khai"] is True
    assert kq["chi_phi"]["usd"] == 0.0123 and kq["chi_phi"]["ky_tu_loi_nhac"] > 0


def test_chay_luu_tra_loi_tho_chua_bi_kiem_sua():
    tl = copy.deepcopy(TRA_LOI_B)
    tl["so_hieu"][0]["dong"] = [3]          # trích vắt 3–4: kiểm neo lại, bản thô giữ [3]
    kq = ag.chay(_dau_vao(), GoiGia(tl), {})
    assert kq["so_hieu"][0]["dong"] == [3, 4]
    assert kq["tra_loi_tho"] == tl


def test_chay_loi_goi_va_tra_loi_hong_chuyen_nguoi():
    def hong(_h, _n):
        raise ag.LoiGoi("claude -p thoát mã 1")
    assert ag.chay(_dau_vao(), hong, {}) == {"loi": "claude -p thoát mã 1", "cho_nguoi": True}
    kq = ag.chay(_dau_vao(), GoiGia("không có JSON"), {})
    assert kq["cho_nguoi"] and kq["loi"].startswith("câu trả lời không đọc được")


def test_claude_cli_khong_cong_cu_va_doc_chi_phi(monkeypatch):
    bat = {}

    def run(lenh, **kw):
        bat.update(lenh=lenh, **kw)
        out = {"result": "{}", "total_cost_usd": 0.02, "duration_ms": 5,
               "usage": {"input_tokens": 10, "output_tokens": 3},
               "modelUsage": {"claude-sonnet-5": {}}}
        return subprocess.CompletedProcess(lenh, 0, json.dumps(out), "")

    monkeypatch.setattr(ag.subprocess, "run", run)
    ph = ag.ClaudeCli("sonnet")("HỆ", "NGƯỜI")
    lenh = bat["lenh"]
    assert lenh[lenh.index("--tools") + 1] == "" and "--strict-mcp-config" in lenh
    assert lenh[lenh.index("--system-prompt") + 1] == "HỆ" and bat["input"] == "NGƯỜI"
    assert not Path(bat["cwd"]).exists()     # thư mục trống đã dọn
    assert (ph.usd, ph.model, ph.token["input_tokens"]) == (0.02, "claude-sonnet-5", 10)

    monkeypatch.setattr(ag.subprocess, "run", lambda lenh, **kw: subprocess.CompletedProcess(
        lenh, 0, json.dumps({"is_error": True, "subtype": "x"}), ""))
    with pytest.raises(ag.LoiGoi):
        ag.ClaudeCli()("a", "b")


# ── đối chiếu sổ và ghi ngược ────────────────────────────────────────────

def test_doi_chieu_so():
    so_so = [SO_HIEU[0], {**SO_HIEU[2], "gia_tri": "99000902"}]
    ra = aht.doi_chieu_so([
        {"loai": "so_don_uspto", "gia_tri": "99000901", "chu_so_huu": "ta"},
        {"loai": "so_don_uspto", "gia_tri": "99000902", "chu_so_huu": "ta"},
        {"loai": "so_don_uspto", "gia_tri": "99000904", "chu_so_huu": "doi_chung"},
    ], so_so)
    assert [r["so_voi_so"]["trang_thai"] for r in ra] == ["khop", "lech_chu", "moi"]
    assert ra[1]["so_voi_so"]["chu_trong_so"] == ["doi_chung"]
    [r] = aht.doi_chieu_so([{"loai": "so_hoa_don", "gia_tri": "<Chưa cấp số>", "chu_so_huu": "ta"}], so_so)
    assert r["so_voi_so"] == {"trang_thai": "chua_cap_so"}


def _tep(tmp_path):
    ax, pd = tmp_path / "anh_xa.json", tmp_path / "phan_doan.json"
    ax.write_text(json.dumps(SO_AX, ensure_ascii=False), encoding="utf-8")
    pd.write_text(json.dumps({"anh_xa_phan_doan": [], "ung_vien_loai": []}), encoding="utf-8")
    return ax, pd


def test_kieu_b_ghi_nguoc_cach_goi_moi_mot_lan(tmp_path):
    ax, pd = _tep(tmp_path)
    bg = aht.xu_ly(_tl(), DANH_TINH, SO_AX, SO_HIEU, GoiGia(TRA_LOI_B))
    assert bg["doi_chieu_anh_xa"]["trang_thai"] == "agent_moi"
    assert bg["so_hieu"][0]["so_voi_so"]["trang_thai"] == "khop"
    [c] = bg["cach_goi_moi"]
    assert (c["khoa"], c["cho_muc"], c["ten"], c["phuong_phap"]) == (
        KHOA_PD, "phe duyet zz", "submission information", "agent")
    assert "dòng [5]" in c["ly_do"]
    assert aht.ghi_nguoc(bg["cach_goi_moi"], ax, pd) == 1
    assert aht.ghi_nguoc(bg["cach_goi_moi"], ax, pd) == 0          # lặp lại không nhân đôi
    so_ax = json.loads(ax.read_text("utf-8"))["anh_xa"][KHOA_PD]
    assert [(t["ten"], t["cho_muc"], t["nguon"]) for t in so_ax["ten_goi_chap_nhan"]] == [
        ("submission information", "phe duyet zz", [REL_B])]
    assert so_ax["nguon"] == [REL_B]
    [dong] = json.loads(pd.read_text("utf-8"))["anh_xa_phan_doan"]
    # Đúng khuôn `so_anh_xa.py` đọc lại khi dựng sổ: khoá có hai mục thì cần `cho_muc`.
    assert {"khoa", "ten", "nguon", "ly_do", "cho_muc", "phuong_phap"} <= set(dong)
    assert os.stat(ax).st_mode & 0o777 == 0o600


def test_khong_ghi_nguoc_khi_do_chac_thap_hoac_da_co():
    tl = copy.deepcopy(TRA_LOI_B)
    tl["do_chac"] = "thap"
    bg = aht.xu_ly(_tl(), DANH_TINH, SO_AX, SO_HIEU, GoiGia(tl))
    assert bg["cach_goi_moi"] == [] and bg["cho_nguoi"]
    assert bg["o_khong_ghi"][0]["ly_do"].startswith("độ chắc thấp")

    so_ax = copy.deepcopy(SO_AX)
    so_ax["anh_xa"][KHOA_PD]["ten_goi_chap_nhan"].append(
        {"ten": "submission information", "cho_muc": "phe duyet zz", "nguon": []})
    bg = aht.xu_ly(_tl(), DANH_TINH, so_ax, SO_HIEU, GoiGia(TRA_LOI_B))
    assert bg["cach_goi_moi"] == []
    assert "đã có" in bg["o_khong_ghi"][0]["ly_do"]


def test_cach_goi_da_co_o_muc_khac_van_ghi_nguoc_cho_muc_nay():
    so_ax = copy.deepcopy(SO_AX)
    v = so_ax["anh_xa"][KHOA_PD]
    v["muc_bat_buoc"].append(_muc("muc khac zz", KHOA_PD))
    v["ten_goi_chap_nhan"].append(
        {"ten": "submission information", "cho_muc": "muc khac zz", "nguon": [REL_B]})
    bg = aht.xu_ly(_tl(), DANH_TINH, so_ax, SO_HIEU, GoiGia(TRA_LOI_B))
    [c] = bg["cach_goi_moi"]
    assert (c["ten"], c["cho_muc"]) == ("submission information", "phe duyet zz")


@pytest.mark.parametrize("sua,ly_do", [
    (lambda tl: tl["muc_bat_buoc"][0].update(dap_ung="mot_phan"), "một phần"),
    (lambda tl: tl["hinh_thuc"].update(muc="khong_dat"), "hình thức không đạt"),
])
def test_khong_ghi_nguoc_khi_mot_phan_hoac_hinh_thuc_khong_dat(tmp_path, sua, ly_do):
    ax, pd = _tep(tmp_path)
    tl = copy.deepcopy(TRA_LOI_B)
    sua(tl)
    bg = aht.xu_ly(_tl(), DANH_TINH, SO_AX, SO_HIEU, GoiGia(tl))
    assert bg["doi_chieu_anh_xa"]["chi_agent"] == [(KHOA_PD, "phe duyet zz")]
    assert bg["cach_goi_moi"] == []
    [o] = bg["o_khong_ghi"]
    assert ly_do in o["ly_do"]
    assert aht.ghi_nguoc(bg["cach_goi_moi"], ax, pd) == 0
    assert json.loads(ax.read_text("utf-8"))["anh_xa"][KHOA_PD]["ten_goi_chap_nhan"] == []


def test_anh_xa_giu_o_ma_agent_khong_thay_thi_chuyen_nguoi():
    tl = copy.deepcopy(TRA_LOI_B)
    tl["buoc"] = {"hoat_dong": "N_9_1", "dong": [1], "trich": "SUBMISSION"}
    tl["muc_bat_buoc"] = [{"muc": "bao cao zz", "dap_ung": "thieu", "dong": [1],
                           "trich": "SUBMISSION INFORMATION"}]
    bg = aht.xu_ly(_tl(rel=REL_BC), DANH_TINH, SO_AX, SO_HIEU, GoiGia(tl))
    assert bg["doi_chieu_anh_xa"]["chi_anh_xa"] == [(KHOA_TC, "bao cao zz")]
    assert bg["cho_nguoi"] and bg["muc_con_thieu"] == ["bao cao zz"]


def test_tep_xung_dot_khong_goi_model():
    goi = GoiGia(TRA_LOI_B)
    bg = aht.xu_ly(_tl(), {"ho_so": [], "xung_dot": {"ca": ["x"]}}, SO_AX, SO_HIEU, goi)
    assert bg["khong_goi_model"] and bg["cho_nguoi"] and goi.lan == []


# ── dòng lệnh ────────────────────────────────────────────────────────────

def _kho(tmp_path):
    ade = tmp_path / "ade_out"
    d = ade / "d0000000000000b1"
    d.mkdir(parents=True)
    (d / "meta_pro.json").write_text(json.dumps({"source": REL_B}, ensure_ascii=False), "utf-8")
    (d / "parse_pro.json").write_text(json.dumps({"markdown": MD_B}), "utf-8")
    ax, pd = _tep(tmp_path)
    sh = tmp_path / "so_hieu.json"
    sh.write_text(json.dumps({"so_hieu": SO_HIEU}), "utf-8")
    return ["--ade-out", str(ade), "--so-anh-xa", str(ax), "--phan-doan", str(pd),
            "--so-hieu", str(sh), "--danh-tinh", str(tmp_path / "khong_co.json"),
            "--ra", str(tmp_path / "ra.json")]


def test_mac_dinh_chi_uoc_luong(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ag, "ClaudeCli", lambda *a, **k: pytest.fail("không được gọi model"))
    assert aht.main(_kho(tmp_path) + ["--doc-id", "d0000000000000b1"]) == 0
    out = capsys.readouterr().out
    assert "ước lượng 1 tài liệu" in out and "ZORBLAX" not in out
    assert not (tmp_path / "ra.json").exists()


def test_tran_moi_luot(tmp_path):
    ids = [f"--doc-id=d{i:015d}" for i in range(aht.TRAN_MOI_LUOT + 1)]
    args = _kho(tmp_path)
    with pytest.raises(SystemExit, match="trần"):
        aht.main(args + ids)
    with pytest.raises(SystemExit, match="doc-id"):
        aht.main(args)


def test_goi_ghi_so_rieng_va_khong_in_dinh_danh(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ag, "ClaudeCli", lambda *a, **k: GoiGia(TRA_LOI_B))
    monkeypatch.setattr(aht.so_so_hieu, "nap_danh_tinh", lambda p: {REL_B: DANH_TINH})
    args = _kho(tmp_path)
    (tmp_path / "khong_co.json").write_text("{}")
    assert aht.main(args + ["--doc-id", "d0000000000000b1", "--goi"]) == 0
    out = capsys.readouterr().out
    assert "ZORBLAX" not in out and "99000901" not in out and "Submission" not in out
    so = json.loads((tmp_path / "ra.json").read_text("utf-8"))
    assert os.stat(tmp_path / "ra.json").st_mode & 0o777 == 0o600
    assert so["chi_phi"]["usd_moi_tai_lieu"]["trung_binh"] == 0.0123
    assert so["giu_du_lieu_tren_may"] is False
    assert so["ghi_nguoc_anh_xa"][0]["moi_that"] == 1


def test_kiem_lai_dung_cau_tra_loi_da_luu_khong_goi_model(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ag, "ClaudeCli", lambda *a, **k: GoiGia(TRA_LOI_B))
    monkeypatch.setattr(aht.so_so_hieu, "nap_danh_tinh", lambda p: {REL_B: DANH_TINH})
    args = _kho(tmp_path) + ["--doc-id", "d0000000000000b1"]
    (tmp_path / "khong_co.json").write_text("{}")
    aht.main(args + ["--goi"])
    truoc = json.loads((tmp_path / "ra.json").read_text("utf-8"))["tai_lieu"]["d0000000000000b1"]
    monkeypatch.setattr(ag, "ClaudeCli", lambda *a, **k: pytest.fail("không được gọi model"))
    assert aht.main(args + ["--kiem-lai"]) == 0
    sau = json.loads((tmp_path / "ra.json").read_text("utf-8"))["tai_lieu"]["d0000000000000b1"]
    assert sau["chay_luc"] == truoc["chay_luc"] and "kiem_lai_luc" in sau
    assert sau["chi_phi"]["usd"] == truoc["chi_phi"]["usd"]
    assert sau["so_hieu"] == truoc["so_hieu"]

    monkeypatch.setattr(ag, "HE_THONG", ag.HE_THONG + " ")    # lời nhắc đổi: câu cũ hết giá trị
    with pytest.raises(SystemExit, match="lời nhắc đã đổi"):
        aht.main(args + ["--kiem-lai"])


def test_trich_noi_lien_hai_dong_van_qua():
    d = ag.dong_noi_dung(MD_B)
    assert ag.kiem_trich({"dong": [3, 4], "trich": "Mark: ZORBLAXSerial Number: 99000901"}, d) is None


def test_thuc_the_html_giai_va_trich_theo_thu_tu_model_liet_ke():
    d = ag.dong_noi_dung("Signatory&#x27;s name | ZZ\nx\nMark: ZORBLAX\n&lt;Chưa cấp số&gt;")
    assert d[1] == "Signatory's name | ZZ" and d[4] == "<Chưa cấp số>"
    assert ag.kiem_trich({"dong": [3, 1], "trich": "Mark: ZORBLAX Signatory's name"}, d) is None
