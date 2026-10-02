"""Kho kết quả ADE trên đĩa, và phép đổi toạ độ.

VÌ SAO TOẠ ĐỘ LÀ CHỖ NGUY HIỂM NHẤT
───────────────────────────────────
ADE v2 trả box dưới dạng PHÂN SỐ [0,1] của chiều trang, không phải pixel. Các
trường `width`/`height`/`dpi` trên node trang đã bị bỏ khỏi API, nên phía hiển
thị BẮT BUỘC phải tự biết kích thước ảnh nó đang vẽ lên — và tự lưu lại con số
đó lúc render.

Sai ở đây không làm chương trình chết. Nó vẽ ra những khung trông hợp lý ở sai
chỗ, và người soát sẽ tin vào chúng. Vì vậy mọi lối vào đều kiểm biên, và mọi
trường hợp đáng ngờ đều NÉM LỖI thay vì đoán một giá trị mặc định.

VÌ SAO KHO NẰM NGOÀI CÂY DỰ ÁN
──────────────────────────────
`parse.json` chứa nguyên văn chữ đọc từ CCCD; ảnh trang render là ảnh giấy tờ
thật. Để trong repo thì chỉ cần một lần `git add -A` là chúng nằm vĩnh viễn
trong lịch sử. `.gitignore` chặn được sự cố thường ngày, không chặn được sự cố
hiếm — nên dữ liệu đặt hẳn ra ngoài, nơi `git add` không với tới.
"""

from __future__ import annotations

import hashlib
import unicodedata
import json
from datetime import datetime, timezone
from pathlib import Path

__all__ = ["box_to_pixels", "doc_id_for", "save_result", "load_result",
           "render_pages", "DEFAULT_STORE", "DISPLAY_DPI"]

#: Kho kết quả. Quyền 700, ngoài cây dự án — xem docstring đầu tệp.
DEFAULT_STORE = Path.home() / ".private" / "ade_out"

#: DPI render ảnh trang để HIỂN THỊ trên web.
#:
#: 150 chứ không phải 300: ảnh này chỉ để mắt người nhìn và để vẽ khung lên,
#: KHÔNG phải để OCR — ADE đọc thẳng file gốc. Đo trên hồ sơ thật cho thấy
#: render cao hơn DPI của bản quét gốc chỉ nội suy thêm điểm ảnh không có thật:
#: nhiều ký tự hơn 7% nhưng tỉ lệ dấu THẤP hơn, vì chữ thêm ra là nhiễu viền.
DISPLAY_DPI = 150

_KEYS = ("xmin", "ymin", "xmax", "ymax")


def box_to_pixels(box: dict, *, width: int, height: int) -> tuple[int, int, int, int]:
    """Đổi box chuẩn hoá [0,1] sang pixel của ảnh đang hiển thị.

    Ném lỗi thay vì trả giá trị mặc định: một khung vẽ sai chỗ trông y hệt một
    khung vẽ đúng chỗ, và đó là kiểu sai mà người soát không phát hiện được.
    """
    missing = [k for k in _KEYS if box.get(k) is None]
    if missing:
        raise ValueError(f"box thiếu trường: {', '.join(missing)}")

    vals = {k: float(box[k]) for k in _KEYS}

    bad = {k: v for k, v in vals.items() if not 0.0 <= v <= 1.0}
    if bad:
        # Gần như luôn nghĩa là đang đọc cây `grounding` cấp cao nhất (bản cũ,
        # đơn vị pixel) thay vì `element.grounding` inline.
        raise ValueError(
            f"toạ độ ngoài khoảng [0,1]: {bad} — có phải đang đọc cây "
            f"`grounding` cũ (đơn vị pixel) thay vì `element.grounding` không?")

    if vals["xmax"] < vals["xmin"] or vals["ymax"] < vals["ymin"]:
        # Chiều âm: canvas vẽ im lặng ra một khung vô hình, phần tử biến mất
        # khỏi overlay mà không có lỗi nào.
        raise ValueError(f"box đảo ngược (max < min): {vals}")

    return (round(vals["xmin"] * width), round(vals["ymin"] * height),
            round(vals["xmax"] * width), round(vals["ymax"] * height))


def doc_id_for(relative_path: str) -> str:
    """Định danh tài liệu từ ĐƯỜNG DẪN TƯƠNG ĐỐI, không từ tên file.

    `CCCD.pdf` xuất hiện ở ít nhất 3 hồ sơ khác nhau trong kho thật. Dùng tên
    file làm khoá thì hồ sơ sau ghi đè hồ sơ trước — mất dữ liệu đã trả tiền để
    có, mà không có thông báo nào.

    Băm thay vì làm sạch tên: đường dẫn thật có dấu tiếng Việt, khoảng trắng và
    dấu chấm; mọi phép làm sạch đều có thể đưa hai đường dẫn khác nhau về cùng
    một tên.

    CHUẨN HOÁ NFC TRƯỚC KHI BĂM — BẮT BUỘC
    ──────────────────────────────────────
    macOS trả tên tệp ở dạng **NFD**: `ă` thành `a` + U+0306 (dấu rời), nên
    `"Đăng ký"` từ `os.listdir` dài hơn `"Đăng ký"` gõ tay 10 byte và băm ra
    một id HOÀN TOÀN khác. Đo thật trên kho này: cùng một tệp CCCD.pdf cho
    `50926b1970597ef1` (đường từ đĩa) và `8227cd6f3a2d9be5` (đường gõ tay).

    Hậu quả nếu không chuẩn hoá: kho im lặng nhân đôi — mỗi tài liệu có hai
    thư mục, file manager báo "chưa chạy" cho tệp đã chạy, và người dùng trả
    tiền ADE lần thứ hai cho đúng tài liệu đó.
    """
    return hashlib.sha1(
        unicodedata.normalize("NFC", relative_path).encode("utf-8")
    ).hexdigest()[:16]


def _ensure_private(path: Path) -> None:
    """Tạo thư mục với quyền 700 và ép lại quyền nếu đã tồn tại.

    `mkdir(parents=True)` của Python dùng umask của tiến trình, mà umask mặc
    định trên macOS là 022 ⇒ thư mục ra 755: mọi tài khoản khác trên máy đọc
    được. Kho này chứa ảnh CCCD và bản chép của chúng, nên quyền phải đặt
    tường minh chứ không phó mặc cho umask.

    Ép lại cả thư mục đã tồn tại: một kho lỡ tạo sai quyền sẽ giữ nguyên sai
    quyền đó mãi nếu ta chỉ đặt lúc tạo mới.
    """
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)


def save_result(store: Path, doc_id: str, parse: dict, *,
                source: str, model: str, credits: float,
                pages: list[dict] | None = None,
                variant: str = "") -> Path:
    """Ghi kết quả parse và siêu dữ liệu của nó.

    `parse` là dict THÔ của API, không phải đối tượng SDK đã đóng gói: kho trên
    đĩa phải sống lâu hơn phiên bản thư viện. Một bản nâng cấp SDK đổi tên
    trường không được làm hỏng kết quả đã trả tiền để có.

    `variant` tách các engine ra tệp riêng trong CÙNG thư mục tài liệu:

        parse.json          ADE Verity  (mặc định, variant="")
        parse_pro.json      ADE Pro     (variant="pro")
        vision.json         Apple Vision

    Cùng thư mục vì chúng nói về CÙNG một tài liệu và dùng chung ảnh trang đã
    render — tách thư mục thì mỗi engine lại render ảnh riêng, và khi đó khác
    biệt giữa hai bản chép lẫn cả khác biệt do ảnh.

    Tệp riêng chứ không phải một tệp gộp: bản đã trả tiền để có không được
    một lần chạy khác ghi đè. Ghi đè kiểu đó hỏng âm thầm — tệp vẫn hợp lệ,
    chỉ là của engine khác.
    """
    _ensure_private(store)
    d = store / doc_id
    _ensure_private(d)

    suffix = f"_{variant}" if variant else ""
    (d / f"parse{suffix}.json").write_text(
        json.dumps(parse, ensure_ascii=False, indent=2), encoding="utf-8")

    (d / f"meta{suffix}.json").write_text(json.dumps({
        "source": source,
        "model": model,
        "credits": credits,
        # Kích thước pixel từng trang. PHẢI lưu: toạ độ ADE là phân số, nên
        # phía web không vẽ đúng được nếu không biết nó đang vẽ lên ảnh to bao
        # nhiêu. Node trang của ADE từng có width/height/dpi nhưng đã bỏ.
        "pages": pages or [],
        "parsed_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    return d


def load_result(store: Path, doc_id: str) -> dict:
    d = store / doc_id
    return {
        "parse": json.loads((d / "parse.json").read_text("utf-8")),
        "meta": json.loads((d / "meta.json").read_text("utf-8")),
    }


def render_pages(src: Path, out_dir: Path, dpi: int = DISPLAY_DPI) -> list[dict]:
    """Render từng trang thành JPG, trả về kích thước pixel của từng trang.

    Kích thước phải trả về VÀ được lưu lại — xem chú thích `pages` trong
    `save_result`.
    """
    import pymupdf
    from PIL import Image

    _ensure_private(out_dir)
    pages: list[dict] = []

    if src.suffix.lower() == ".pdf":
        with pymupdf.open(src) as doc:
            for n in range(doc.page_count):
                pix = doc[n].get_pixmap(dpi=dpi)
                im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                im.save(out_dir / f"p{n + 1}.jpg", quality=88)
                pages.append({"page": n + 1, "width": pix.width,
                              "height": pix.height})
    else:
        im = Image.open(src)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        im.save(out_dir / "p1.jpg", quality=88)
        pages.append({"page": 1, "width": im.width, "height": im.height})

    return pages
