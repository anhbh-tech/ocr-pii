"""Lớp sửa chính tả chồng lên kết quả ADE.

Dùng corrector GIẢ, không nạp model 171 MB: thứ cần khoá ở đây là logic cổng
và logic bảo vệ định danh, không phải chất lượng model. Corrector giả còn cho
phép dựng chính xác những ca hỏng mà model thật hiếm khi tạo ra theo yêu cầu.
"""

import json

from ocr_lab.ade_postcorrect import (
    ACCENT_FLOOR, correct_parse, load_corrections, save_corrections,
    should_correct,
)


class FakeCorrector:
    """Corrector thay thế: áp một bảng thay thế cố định."""

    model_dir = "fake"

    def __init__(self, table: dict[str, str] | None = None):
        self.table = table or {}
        self.calls: list[str] = []
        #: Bản THÔ model trả về, trước khi `filter_to_tone_fixes` lọc. Cần
        #: giữ lại để test đo được mức an toàn của chính MODEL — nhìn bản đã
        #: lọc thì định danh luôn nguyên vẹn và chỉ số mất hết ý nghĩa.
        self.last_raw = ""

    def correct_chunk(self, text: str) -> str:
        self.calls.append(text)
        self.last_raw = self.table.get(text, text)
        return self.last_raw


def _parse_with(chunks: list[tuple[str, str]]) -> dict:
    """Dựng một `parse.json` tối thiểu: [(chunk_id, text), ...].

    Range tính từ vị trí thật trong markdown ghép — giống hệt cách ADE trả về,
    nên test cũng khoá luôn việc đọc range đúng.
    """
    md = ""
    children = []
    for cid, text in chunks:
        start = len(md)
        md += text + "\n"
        children.append({
            "type": "text", "id": cid,
            "grounding": {"page": 1,
                          "range": {"start": start, "end": start + len(text)},
                          "box": {"xmin": 0.1, "ymin": 0.1,
                                  "xmax": 0.9, "ymax": 0.2}},
        })
    return {"markdown": md,
            "structure": {"children": [{"grounding": {"page": 1},
                                        "children": children}]}}


# ── cổng mật độ dấu ─────────────────────────────────────────────────────

def test_van_ban_du_dau_thi_bo_qua():
    # Đây là trạng thái THẬT của kết quả ADE: 4 tài liệu CCCD đo được đều nằm
    # ở 0,202–0,237, tức trên mốc tiếng Việt 0,217. Gọi model lên văn bản đã
    # đủ dấu thì nó chỉ có thể làm hỏng.
    ok, why = should_correct(
        "Nơi thường trú: Hư Cấu, Mẫu Thử, Hà Nội\n"
        "Quê quán của công dân là xã Hư Cấu huyện Mẫu Thử")
    assert not ok
    assert "đã đủ" in why


def test_van_ban_mat_dau_thi_sua():
    ok, why = should_correct(
        "Noi thuong tru: Hu Cau, Mau Thu, Ha Noi\n"
        "Que quan cua cong dan la xa Hu Cau huyen Mau Thu")
    assert ok
    assert "thiếu dấu" in why


def test_dong_tieng_anh_khong_bi_coi_la_mat_dau():
    # CCCD in song ngữ. Tiếng Anh có tỉ lệ dấu bằng 0 nhưng hoàn toàn đúng —
    # gửi nó cho model tiếng Việt thì model sẽ "sửa" thành thứ gì đó.
    ok, why = should_correct(
        "SOCIALIST REPUBLIC OF VIET NAM\n"
        "Independence - Freedom - Happiness\nCitizen Identity Card")
    assert not ok
    assert "không phải tiếng Việt" in why


# ── chồng lớp lên parse ─────────────────────────────────────────────────

def test_chi_goi_model_cho_chunk_thieu_dau():
    parse = _parse_with([
        ("a", "Ho va ten cua cong dan la Nguyen Van A sinh nam 1990"),
        ("b", "Nơi thường trú của công dân là xã Hư Cấu, huyện Mẫu Thử"),
    ])
    fake = FakeCorrector()
    res = correct_parse(parse, fake)

    assert len(fake.calls) == 1                   # chỉ chunk 'a'
    assert "Ho va ten" in fake.calls[0]
    assert len(res.skipped) == 1 and "b:" in res.skipped[0]


def test_khong_doc_nham_range():
    # Range phải cắt đúng phần của chunk, không lấy cả markdown.
    parse = _parse_with([("a", "Chunk MOT khong dau gi ca o day"),
                         ("b", "Chunk HAI cung khong co dau nao het")])
    fake = FakeCorrector()
    correct_parse(parse, fake)

    assert len(fake.calls) == 2
    assert fake.calls[0] == "Chunk MOT khong dau gi ca o day"
    assert fake.calls[1] == "Chunk HAI cung khong co dau nao het"


def test_dem_dung_so_chunk_da_doi():
    parse = _parse_with([("a", "So hieu 56/2026/ND-CP ban hanh ngay hom qua")])
    fake = FakeCorrector({
        "So hieu 56/2026/ND-CP ban hanh ngay hom qua":
            "Số hiệu 56/2026/NĐ-CP ban hành ngày hôm qua"})
    res = correct_parse(parse, fake)

    assert res.n_changed == 1
    assert res.chunks[0].accent_after > res.chunks[0].accent_before


# ── bảo vệ định danh ────────────────────────────────────────────────────

def test_dinh_danh_tinh_theo_TONG_khong_theo_chunk():
    # Một chunk chứa 3 số hiệu mà hỏng 1 thì nặng hơn chunk chứa 1 số hiệu mà
    # hỏng 1. Đếm theo chunk gộp hai ca đó làm một và giấu mất mức độ.
    #
    # Số ở đây là BỊA — dãy chữ số tăng dần liên tiếp, đúng khuôn mà
    # `test_no_client_content_leaks_into_tracked_source` nhận là ví dụ tự soạn.
    # Test đó đã bắt đúng một lần khi bản nháp dùng số CCCD có thật nhìn thấy
    # trong ảnh; đây chính là kiểu rò rỉ nó sinh ra để chặn.
    parse = _parse_with([
        ("a", "Cac so 123456789 va 23456789 va 3456789 deu con day"),
    ])
    fake = FakeCorrector({
        "Cac so 123456789 va 23456789 va 3456789 deu con day":
            "Các số 123456789 và 23456789 và 3456780 đều còn đây"})
    res = correct_parse(parse, fake)

    # 3 định danh, giữ 2 ⇒ 2/3, KHÔNG phải 0/1.
    #
    # 3 định danh, giữ 2 ⇒ 2/3, KHÔNG phải 0/1.
    assert res.identifier_preservation < 1.0
    assert abs(res.identifier_preservation - 2 / 3) < 0.01


def test_khong_co_dinh_danh_thi_khong_phat():
    # Trang không có số hiệu nào phải cho 100%, không phải 0% — chia cho 0.
    parse = _parse_with([("a", "Cong dan co ho khau thuong tru tai xa nay")])
    res = correct_parse(parse, FakeCorrector())
    assert res.identifier_preservation == 1.0


# ── ghi ra đĩa ──────────────────────────────────────────────────────────

def test_ghi_tep_rieng_khong_dung_parse_json(tmp_path):
    # Mọi grounding.range neo vào `markdown` bằng offset ký tự. Sửa tại chỗ là
    # làm lệch toàn bộ 45 span của một trang CCCD.
    doc = tmp_path / "abc123"
    doc.mkdir()
    # Văn bản mất dấu THUẦN TUÝ: model chỉ đặt lại dấu, không đổi chữ nào,
    # nên `filter_to_tone_fixes` cho qua toàn bộ.
    parse = _parse_with([("a", "Noi thuong tru tai xa Hu Cau huyen nay")])
    (doc / "parse.json").write_text(json.dumps(parse), encoding="utf-8")
    before = (doc / "parse.json").read_text("utf-8")

    fake = FakeCorrector({"Noi thuong tru tai xa Hu Cau huyen nay":
                          "Nơi thường trú tại xã Hư Cấu huyện này"})
    save_corrections(tmp_path, "abc123", correct_parse(parse, fake))

    assert (doc / "parse.json").read_text("utf-8") == before   # BẤT BIẾN
    assert (doc / "corrected.json").is_file()

    got = load_corrections(tmp_path, "abc123")
    assert got is not None
    assert got["chunks"][0]["corrected"].startswith("Nơi thường trú")


def test_quyen_600_cho_tep_ban_sua(tmp_path):
    # Bản sửa chứa nguyên văn chữ trên CCCD — cùng mức nhạy cảm với parse.json.
    # Văn bản mất dấu THUẦN TUÝ: model chỉ đặt lại dấu, không đổi chữ nào,
    # nên `filter_to_tone_fixes` cho qua toàn bộ.
    parse = _parse_with([("a", "Noi thuong tru tai xa Hu Cau huyen nay")])
    f = save_corrections(tmp_path, "abc123", correct_parse(parse, FakeCorrector()))
    assert (f.stat().st_mode & 0o777) == 0o600


def test_force_bo_qua_cong():
    # Chỉ dùng khi đang ĐO xem cổng đặt đúng chỗ chưa.
    parse = _parse_with([("a", "Nơi thường trú của công dân là xã Hư Cấu")])
    fake = FakeCorrector()
    correct_parse(parse, fake, force=True)
    assert len(fake.calls) == 1


def test_nguong_mac_dinh_nam_duoi_moc_tieng_viet():
    # Cổng phải bỏ qua văn bản quanh mốc 0,217 (chính là kết quả ADE thật) mà
    # vẫn bắt được đầu ra tesseract (~0,080).
    assert 0.08 < ACCENT_FLOOR < 0.217
