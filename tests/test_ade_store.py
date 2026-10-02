"""Kho kết quả ADE: định danh tài liệu và vòng ghi/đọc."""

from ocr_lab.ade_store import doc_id_for, load_result, save_result


def test_doc_id_khac_nhau_giua_cac_file_trung_ten():
    # `CCCD.pdf` có mặt ở ít nhất 3 hồ sơ trong kho thật. Nếu định danh lấy
    # theo tên file thì hồ sơ sau ghi đè hồ sơ trước — mất kết quả đã trả tiền.
    a = doc_id_for("Phòng IP/901. ZORBLAX/0. Info/CCCD.pdf")
    b = doc_id_for("Phòng IP/98. Acme/0. Info/CCCD.pdf")
    assert a != b


def test_doc_id_on_dinh_qua_cac_lan_goi():
    # Không ổn định thì mỗi lần chạy lại sinh thư mục mới và trả tiền lại từ đầu.
    p = "Phòng IP/901. ZORBLAX/0. Info/CCCD.pdf"
    assert doc_id_for(p) == doc_id_for(p)


def test_doc_id_an_toan_cho_ten_thu_muc():
    # Đường dẫn thật có dấu tiếng Việt, khoảng trắng và dấu chấm. Định danh
    # phải là chuỗi hex trần để dùng làm tên thư mục và để kiểm bằng regex ở
    # tầng web (chặn path traversal).
    d = doc_id_for("Phòng IP/1. Đăng ký bảo hộ/901.US. ZORBLAX/CCCD.pdf")
    assert len(d) == 16
    assert all(c in "0123456789abcdef" for c in d)


def test_luu_roi_doc_lai_giu_nguyen_tieng_viet_co_dau(tmp_path):
    parse = {"markdown": "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM",
             "metadata": {"page_count": 1}}
    save_result(tmp_path, "abc123", parse,
                source="Phòng IP/x/CCCD.pdf", model="dpt-3-verity",
                credits=0.3, pages=[{"page": 1, "width": 1275, "height": 1650}])

    got = load_result(tmp_path, "abc123")
    assert got["parse"]["markdown"] == "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM"
    assert got["meta"]["source"] == "Phòng IP/x/CCCD.pdf"
    assert got["meta"]["credits"] == 0.3


def test_kich_thuoc_trang_duoc_luu_lai(tmp_path):
    # Toạ độ ADE là phân số, nên kích thước ảnh đã render là thông tin BẮT BUỘC
    # để vẽ đúng. Node trang của ADE từng có width/height nhưng đã bị bỏ.
    save_result(tmp_path, "def456", {"markdown": ""},
                source="x.pdf", model="dpt-3-verity", credits=0.3,
                pages=[{"page": 1, "width": 1275, "height": 1650}])

    pages = load_result(tmp_path, "def456")["meta"]["pages"]
    assert pages == [{"page": 1, "width": 1275, "height": 1650}]


def test_kho_duoc_tao_voi_quyen_700(tmp_path):
    # Kho chứa ảnh CCCD và bản chép của chúng. `mkdir` theo umask mặc định của
    # macOS (022) cho ra 755 — mọi tài khoản khác trên máy đọc được.
    store = tmp_path / "kho"
    save_result(store, "abc123", {"markdown": "x"},
                source="x.pdf", model="dpt-3-verity", credits=0.3)

    assert (store.stat().st_mode & 0o777) == 0o700
    assert ((store / "abc123").stat().st_mode & 0o777) == 0o700


def test_quyen_duoc_ep_lai_tren_kho_da_ton_tai(tmp_path):
    # Một kho lỡ tạo sai quyền phải được sửa ở lần ghi kế tiếp, chứ không giữ
    # nguyên sai quyền mãi mãi.
    store = tmp_path / "kho"
    store.mkdir()
    store.chmod(0o755)

    save_result(store, "abc123", {"markdown": "x"},
                source="x.pdf", model="dpt-3-verity", credits=0.3)

    assert (store.stat().st_mode & 0o777) == 0o700


# ── nhiều engine trong cùng một thư mục tài liệu ────────────────────────

def test_variant_ghi_ra_tep_rieng_khong_de_ban_cu(tmp_path):
    """Bản đã TRẢ TIỀN để có không được lần chạy khác ghi đè.

    Ghi đè kiểu đó hỏng âm thầm: tệp vẫn hợp lệ, chỉ là của engine khác.
    """
    from ocr_lab.ade_store import save_result

    save_result(tmp_path, "abc", {"markdown": "VERITY"},
                source="x.pdf", model="dpt-3-verity", credits=0.3)
    save_result(tmp_path, "abc", {"markdown": "PRO"},
                source="x.pdf", model="dpt-3-pro", credits=0.9, variant="pro")

    import json
    d = tmp_path / "abc"
    assert json.loads((d / "parse.json").read_text())["markdown"] == "VERITY"
    assert json.loads((d / "parse_pro.json").read_text())["markdown"] == "PRO"
    # meta cũng phải tách, kẻo giá của Pro ghi đè giá của Verity
    assert json.loads((d / "meta.json").read_text())["credits"] == 0.3
    assert json.loads((d / "meta_pro.json").read_text())["credits"] == 0.9


def test_cac_engine_dung_chung_anh_trang(tmp_path):
    """Cùng thư mục ⇒ dùng chung `pages/`. Tách thư mục thì mỗi engine render
    ảnh riêng, và khi đó khác biệt giữa hai bản chép lẫn cả khác biệt do ảnh."""
    from ocr_lab.ade_store import save_result

    save_result(tmp_path, "abc", {"markdown": "A"}, source="x.pdf",
                model="m1", credits=0.0)
    save_result(tmp_path, "abc", {"markdown": "B"}, source="x.pdf",
                model="m2", credits=0.0, variant="pro")
    assert (tmp_path / "abc" / "parse.json").is_file()
    assert (tmp_path / "abc" / "parse_pro.json").is_file()
    # đúng MỘT thư mục tài liệu
    assert len([p for p in tmp_path.iterdir() if p.is_dir()]) == 1
