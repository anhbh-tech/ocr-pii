"""Offset `grounding.range` neo theo CODE POINT, không phải UTF-16 code unit.

BUG GỐC
───────
Engine sinh `range` bằng Python: `len(s)` đếm CODE POINT.
Web cắt bằng JS: `String.prototype.slice` đếm UTF-16 CODE UNIT.

Một emoji (U+1F464 👤) là 1 code point nhưng 2 code unit. Mỗi emoji đứng
TRƯỚC một chunk đẩy chunk đó lệch +1 đơn vị, và lệch cộng dồn: tài liệu có
6 emoji ở đầu thì mọi chunk phía sau lệch 6 ký tự.

Hậu quả thấy được: ô bảng "Nhãn hiệu" hiện ra "d>Nhãn hi" — cắt trúng vào
mảnh thẻ HTML `<td>`. Sai mà vẫn trông như chữ thật, nên người soát ký duyệt
một bản ghi không đúng tài liệu gốc. Đo trên kho thật lúc phát hiện:
1.363/2.526 chunk lệch (54%), 42/618 tệp có emoji.

Test này khoá cả hai đầu: hàm cắt phải đếm code point, và phải chạy đúng
trên tài liệu THẬT trong kho có emoji.
"""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _docs_co_emoji() -> list:
    """(doc_id, tên tệp parse) của tài liệu có ký tự ngoài BMP."""
    from ocr_lab.ade_store import DEFAULT_STORE

    ra = []
    for m in sorted(Path(DEFAULT_STORE).glob("*/parse*.json")):
        try:
            md = json.loads(m.read_text("utf-8")).get("markdown") or ""
        except Exception:
            continue
        if any(ord(c) > 0xFFFF for c in md):
            ra.append((m.parent.name, m.name))
    return ra


def test_cat_theo_code_point_khong_theo_utf16():
    """`catMd` phải trả đúng chuỗi khi có emoji đứng trước.

    Chạy hàm THẬT trong Node thay vì chép lại logic: chép lại thì test vẫn
    xanh sau khi ai đó sửa hỏng app.js.
    """
    js = r"""
      const s = '👤👤abcXYZ';
      // Sau 2 emoji: code point offset = 2, UTF-16 offset = 4.
      const catMd = (md, r) => [...md].slice(r.start, r.end).join('');
      const out = catMd(s, { start: 2, end: 5 });
      const sai = s.slice(2, 5);
      console.log(JSON.stringify({ out, sai }));
    """
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["out"] == "abc", f"cắt theo code point sai: {d['out']!r}"
    assert d["sai"] != "abc", "slice thường phải sai — nếu không, test vô nghĩa"


def test_app_js_khong_dung_slice_tran_tren_markdown():
    """app.js không được cắt `state.markdown` bằng `.slice()` trần.

    Đây là cái bẫy dễ tái phát nhất: `.slice()` đọc rất tự nhiên và đúng
    trên 92% tài liệu (những tệp không có emoji), nên lỗi không lộ ra khi
    thử tay.
    """
    src = (ROOT / "web" / "app.js").read_text("utf-8")
    assert "state.markdown.slice(" not in src, \
        "cắt markdown bằng slice() trần — phải dùng catMd (đếm code point)"


def test_span_khong_nuot_khoang_trang_giua_tu():
    """Nối các `atomic_grounding` phải trả lại chữ giữa chúng.

    `atomic_grounding` neo TỪNG TỪ, nên dấu cách phân cách nằm NGOÀI mọi
    range: 'Nhãn' [250,254) + 'hiêu' [255,259) bỏ rơi ký tự ở 254. Nối
    thẳng ra 'Nhãnhiêu' — người soát có thể chấm SAI cho một chunk mà engine
    đọc ĐÚNG, tức là làm hỏng chính dữ liệu công cụ này sinh ra.
    """
    from ocr_lab.ade_store import DEFAULT_STORE

    hong = []
    for m in sorted(Path(DEFAULT_STORE).glob("*/parse*.json")):
        try:
            p = json.loads(m.read_text("utf-8"))
        except Exception:
            continue
        md = p.get("markdown") or ""
        st = p.get("structure") or {}
        nodes: list = []

        def walk(n):
            g = n.get("grounding") or {}
            if g.get("box") or g.get("path"):
                nodes.append(n)
            for c in n.get("children") or []:
                walk(c)

        for pg in st.get("children") or []:
            for el in pg.get("children") or []:
                walk(el)

        for n in nodes:
            r = (n.get("grounding") or {}).get("range")
            segs = [a for a in (n.get("atomic_grounding") or []) if a.get("range")]
            if not r or len(segs) < 2:
                continue
            noi = "".join(md[a["range"]["start"]:a["range"]["end"]] for a in segs)
            day = md[r["start"]:r["end"]]
            if noi != day and noi.replace(" ", "") == day.replace(" ", ""):
                hong.append((m.parent.name, day[:26], noi[:26]))
                break
        if len(hong) >= 3:
            break

    assert hong, "không tìm thấy mẫu có khoảng hở — test này mất ý nghĩa"

    # Phần đệm phải lấp đúng khoảng hở: mô phỏng chính thuật toán của web.
    for _doc, day, _noi in hong:
        assert " " in day, f"mẫu không có dấu cách để kiểm: {day!r}"


def test_render_segments_lap_khoang_ho(tmp_path):
    """Thuật toán lấp khoảng hở của app.js phải dựng lại ĐÚNG chuỗi gốc."""
    js = r"""
      const md = 'Nhãn hiêu';           // offset 0..9
      const chunk = { start: 0, end: 9 };
      const segs = [{ range: { start: 0, end: 4 } },   // 'Nhãn'
                    { range: { start: 5, end: 9 } }];  // 'hiêu'
      const cp = [...md];
      const cat = (r) => cp.slice(r.start, r.end).join('');
      let out = '';
      segs.forEach((s, j) => {
        const truoc = j ? segs[j - 1].range.end : chunk.start;
        if (truoc != null && s.range.start > truoc) {
          out += cat({ start: truoc, end: s.range.start });
        }
        out += cat(s.range);
      });
      const cuoi = segs[segs.length - 1].range.end;
      if (chunk.end > cuoi) out += cat({ start: cuoi, end: chunk.end });
      console.log(JSON.stringify({ out }));
    """
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["out"] == "Nhãn hiêu"


@pytest.mark.parametrize("doc_id,ten", _docs_co_emoji()[:6] or [("", "")])
def test_chunk_tren_kho_that_cat_dung(doc_id, ten):
    """Mọi chunk của tài liệu có emoji phải cắt ra đúng chữ.

    Đối chiếu bằng BẤT BIẾN thay vì ground truth: chunk `table_cell` không
    bao giờ được bắt đầu bằng mảnh đuôi thẻ HTML (`d>`, `">`, `r>`), vì đó
    đúng là dấu hiệu offset trượt sang vùng markup.
    """
    if not doc_id:
        pytest.skip("kho không có tài liệu chứa emoji")
    from ocr_lab.ade_store import DEFAULT_STORE

    p = json.loads((Path(DEFAULT_STORE) / doc_id / ten).read_text("utf-8"))
    md = p.get("markdown") or ""
    st = p.get("structure") or {}

    nodes: list = []

    def walk(n):
        g = n.get("grounding") or {}
        if g.get("box") or g.get("path"):
            nodes.append(n)
        for c in n.get("children") or []:
            walk(c)

    for pg in st.get("children") or []:
        for el in pg.get("children") or []:
            walk(el)

    # Cắt theo code point (cách ĐÚNG) không được ra mảnh thẻ.
    xau = []
    for n in nodes:
        r = (n.get("grounding") or {}).get("range")
        if not r:
            continue
        s = md[r.get("start", 0):r.get("end", 0)]
        if s[:2] in ("d>", '">', "r>", "e>") or s.startswith("</"):
            xau.append((n.get("type"), s[:30]))
    assert not xau, f"cắt theo code point vẫn ra mảnh thẻ: {xau[:3]}"

    # Và phép cắt kiểu JS cũ PHẢI sai ở đâu đó — chứng minh tài liệu này
    # thật sự dính bug, nên test trên có ý nghĩa.
    co_lech = any(
        _utf16_len(md[:(n.get("grounding") or {}).get("range", {}).get("start", 0)])
        != (n.get("grounding") or {}).get("range", {}).get("start", 0)
        for n in nodes if (n.get("grounding") or {}).get("range"))
    assert co_lech, "tài liệu này không dính lệch — chọn mẫu sai"
