"""Chạy hàng loạt: dự toán trước, chặn Zip Slip, một tệp lỗi không dừng cả lượt."""
from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def _srv(source_root: Path):
    """Nạp server với SOURCE_ROOT trỏ vào thư mục tạm.

    Không dùng kho thật: test không bao giờ được đọc hay ghi vào dữ liệu
    khách hàng, kể cả chỉ để đọc.
    """
    spec = importlib.util.spec_from_file_location(
        "srv_test", ROOT / "scripts" / "serve_review.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["srv_test"] = m
    spec.loader.exec_module(m)
    m.SOURCE_ROOT = source_root
    return m


def _zip_co_zip_slip(td: Path) -> Path:
    z = td / "goi.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("that.txt", b"noi dung that")
        zf.writestr("../../evil.txt", b"thoat ra ngoai")
        zf.writestr("/tuyet/doi.txt", b"duong tuyet doi")
    return z


def test_zip_slip_bi_chan(tmp_path):
    """Tên tệp `../../x` trong zip KHÔNG được ghi ra ngoài thư mục đích.

    Đây là Zip Slip: một kho nén do người khác tạo có thể ghi đè tệp bất kỳ
    trên máy — ssh key, cron, mã nguồn. Kiểm bằng cách dựng zip độc thật
    rồi xác nhận không có gì rơi ra ngoài.
    """
    m = _srv(tmp_path)
    z = _zip_co_zip_slip(tmp_path)
    ra = m._giai_nen_zip(z)

    assert not (tmp_path.parent / "evil.txt").exists()
    assert not Path("/tuyet/doi.txt").exists()
    # Nội dung vẫn được giữ, chỉ bị kéo về trong thư mục đích.
    ten = {p.name for p in ra.rglob("*") if p.is_file()}
    assert "that.txt" in ten


def test_giai_nen_lai_khong_lam_lai_tu_dau(tmp_path):
    """Gọi hai lần trả về cùng thư mục, không giải nén lại.

    Chạy hàng loạt trên zip sẽ gọi cả ở bước dự toán lẫn bước chạy; giải
    nén hai lần là nhân đôi thời gian chờ trên kho lớn.
    """
    m = _srv(tmp_path)
    z = _zip_co_zip_slip(tmp_path)
    assert m._giai_nen_zip(z) == m._giai_nen_zip(z)


def test_zip_qua_nhieu_tep_bi_tu_choi(tmp_path):
    """Trần số tệp phải chặn trước khi ghi ra đĩa."""
    m = _srv(tmp_path)
    m.ZIP_MAX_FILES = 3
    z = tmp_path / "nhieu.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for i in range(10):
            zf.writestr(f"t{i}.txt", b"x")
    with pytest.raises(m.HTTPException):
        m._giai_nen_zip(z)


def test_du_toan_bo_qua_tep_da_chay(tmp_path):
    """Tệp đã có kết quả engine đó KHÔNG được tính vào dự toán.

    Chúng sẽ bị bỏ qua lúc chạy, nên tính vào là nói quá cả thời gian lẫn
    tiền — và người dùng quyết định dựa trên con số ấy.
    """
    m = _srv(tmp_path)
    store = tmp_path / "_store"
    store.mkdir()
    m.STORE = store

    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4\n")
    (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4\n")

    assert len(m._liet_ke_viec(tmp_path, "vision", True)) == 2

    # Đánh dấu a.pdf đã chạy vision.
    d = store / m.doc_id_for("a.pdf")
    d.mkdir(parents=True)
    (d / "vision.json").write_text("{}", "utf-8")

    con = m._liet_ke_viec(tmp_path, "vision", True)
    assert [v["name"] for v in con] == ["b.pdf"]


def test_moi_engine_dem_rieng(tmp_path):
    """Chạy vision rồi thì verity vẫn phải còn việc — không khoá chéo."""
    m = _srv(tmp_path)
    store = tmp_path / "_store"
    store.mkdir()
    m.STORE = store
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4\n")

    d = store / m.doc_id_for("a.pdf")
    d.mkdir(parents=True)
    (d / "vision.json").write_text("{}", "utf-8")

    assert m._liet_ke_viec(tmp_path, "vision", True) == []
    assert len(m._liet_ke_viec(tmp_path, "verity", True)) == 1
