"""VietOCR làm bộ ĐỌC, RapidOCR làm bộ DÒ — engine tự host cho CPU.

VÌ SAO PHẢI GHÉP HAI THỨ
────────────────────────
VietOCR chỉ nhận một ảnh DÒNG chữ đã cắt sẵn và trả về chuỗi. Nó không
biết dòng nằm ở đâu trên trang. Đưa cả trang A4 vào thì nó ép ảnh về chiều
cao 32 pixel và trả ra một chuỗi vô nghĩa — hỏng im lặng, không báo lỗi.

Nên cần một bộ dò dòng. Dùng phần DÒ của RapidOCR (DB-mobilenet, 4,7 MB,
ONNX) và bỏ phần đọc của nó — chính phần đọc ấy là thứ đã đo được tỉ lệ
dấu 0,000 vì model đi kèm là tiếng Trung.

Cách ghép này giữ đúng nguyên tắc đã đặt: mỗi phần dùng thứ nó giỏi.

VÌ SAO vgg_seq2seq CHỨ KHÔNG PHẢI vgg_transformer
─────────────────────────────────────────────────
Chính tác giả VietOCR đo: seq2seq 12ms/dòng so với transformer 86ms/dòng,
trong khi chất lượng chênh 0,8701 so với 0,8800 toàn chuỗi. Mua 7 lần tốc
độ bằng 1% chất lượng — trên CPU 4 nhân thì không có gì phải cân nhắc.

KÍCH THƯỚC
──────────
    vgg_seq2seq.pth   85,4 MB   (89.575.371 byte)
    DB det ONNX        4,7 MB
    ───────────────────────────
    tổng              ~90 MB

Nhỏ hơn EasyOCR (91,6 MB) và không kéo theo CRAFT — bộ dò nặng nhất trong
các ứng viên đã đo.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from pathlib import Path

import numpy as np

#: Weights tải sẵn về đây. Đường dẫn cục bộ chứ không để thư viện tự tải:
#: nó tải qua Google Drive, và một lần chạy đo không được phụ thuộc vào
#: việc Drive có chặn hay không.
DEFAULT_WEIGHTS = Path(__file__).resolve().parents[3] / "models" / "vgg_seq2seq.pth"

#: Bỏ qua hộp thấp hơn mức này — gần như luôn là nhiễu viền hoặc vệt bẩn,
#: và mỗi hộp là một lượt gọi model nên lọc sớm là tiết kiệm thật.
MIN_BOX_HEIGHT = 8


def _va_pillow10() -> None:
    """Trả lại `Image.ANTIALIAS` cho Pillow >= 10.

    vietocr gọi `img.resize(..., Image.ANTIALIAS)`, mà hằng số đó bị bỏ ở
    Pillow 10 (thay bằng `Image.Resampling.LANCZOS` — cùng thuật toán, chỉ
    đổi tên). Không có nó thì MỌI lượt đọc dòng ném AttributeError.

    Đây là kiểu hỏng nguy hiểm nhất nếu vòng gọi có `except`: engine trả về
    0 dòng và trông y hệt "trang này không có chữ". Đã mất một vòng vì đúng
    chuyện đó, nên lỗi đọc dòng nay được ĐẾM và báo ra, xem `doc_anh`.
    """
    from PIL import Image
    if not hasattr(Image, "ANTIALIAS"):
        Image.ANTIALIAS = Image.Resampling.LANCZOS   # type: ignore[attr-defined]


def _chan_gdown() -> None:
    """Chặn `import gdown` của vietocr bằng một module giả.

    vietocr ghim `gdown` bản cũ, mà bản đó `import pkg_resources` — thứ đã
    bị bỏ khỏi Python 3.12. Nâng gdown lên thì xung đột với ghim của
    vietocr, hạ Python xuống thì kéo theo cả dự án.

    Module này chỉ dùng để TẢI weights từ Google Drive; ta đã tải sẵn bằng
    `curl` và trỏ đường dẫn cục bộ, nên nó không bao giờ được gọi. Thay nó
    bằng một module rỗng là cách can thiệp nhỏ nhất.
    """
    if "gdown" in sys.modules:
        return
    gia = types.ModuleType("gdown")
    gia.download = lambda *a, **k: None          # type: ignore[attr-defined]
    sys.modules["gdown"] = gia


@dataclass
class Dong:
    """Một dòng chữ đọc được, kèm hộp bao chuẩn hoá [0,1]."""

    text: str
    box: dict          # {xmin, ymin, xmax, ymax} — phân số, đúng quy ước ADE
    conf: float | None = None


class VietOcrEngine:
    """Dò dòng bằng RapidOCR, đọc dòng bằng VietOCR."""

    def __init__(self, weights: Path | None = None, *, device: str = "cpu",
                 threads: int = 4):
        _chan_gdown()
        _va_pillow10()
        from vietocr.tool.config import Cfg
        from vietocr.tool.predictor import Predictor

        w = Path(weights or DEFAULT_WEIGHTS)
        if not w.is_file():
            raise FileNotFoundError(
                f"chưa có weights VietOCR ở {w}\n"
                f"  tải: curl -sL -o {w} https://vocr.vn/data/vietocr/vgg_seq2seq.pth")

        cfg = Cfg.load_config_from_name("vgg_seq2seq")
        cfg["weights"] = str(w)
        cfg["device"] = device
        # `beamsearch=False`: tìm kiếm chùm đắt hơn nhiều trên CPU và tác
        # giả không báo cải thiện đáng kể. Bật lên là việc của một lần đo
        # riêng, không phải mặc định.
        cfg["predictor"]["beamsearch"] = False
        self.doc = Predictor(cfg)

        import torch
        # Mặc định PyTorch chỉ lấy một phần số lõi. Máy đích 4 nhân nên đặt
        # thẳng; đặt cao hơn số nhân thật thì các luồng tranh nhau và chậm đi.
        torch.set_num_threads(threads)

        from rapidocr_onnxruntime import RapidOCR
        # Chỉ dùng phần DÒ. Tắt phân loại hướng (cls) vì tài liệu ở đây luôn
        # đúng chiều, và nó tốn thêm một lượt suy luận cho mỗi dòng.
        self.do = RapidOCR()

    def doc_anh(self, path: Path) -> list[Dong]:
        """Đọc một ảnh trang, trả về danh sách dòng theo thứ tự đọc."""
        from PIL import Image

        im = Image.open(path)
        if im.mode != "RGB":
            im = im.convert("RGB")
        W, H = im.size

        hop, _ = self.do(str(path), use_det=True, use_cls=False, use_rec=False)
        if not hop:
            return []

        ra: list[Dong] = []
        self.loi_doc = 0        # đếm dòng đọc hỏng — KHÔNG nuốt im lặng
        for diem in hop:
            xs = [p[0] for p in diem]
            ys = [p[1] for p in diem]
            x0, x1 = max(0, int(min(xs))), min(W, int(max(xs)))
            y0, y1 = max(0, int(min(ys))), min(H, int(max(ys)))
            if y1 - y0 < MIN_BOX_HEIGHT or x1 - x0 < MIN_BOX_HEIGHT:
                continue

            # Nới nhẹ: hộp dò thường cắt sát chữ, và VietOCR đọc kém hẳn khi
            # nét trên/dưới bị xén — đúng chỗ dấu tiếng Việt nằm.
            m = max(1, (y1 - y0) // 10)
            crop = im.crop((max(0, x0 - m), max(0, y0 - m),
                            min(W, x1 + m), min(H, y1 + m)))
            try:
                text = self.doc.predict(crop)
            except Exception:       # noqa: BLE001 — một dòng hỏng không dừng cả trang
                # Nhưng PHẢI đếm: nếu mọi dòng đều hỏng thì đây là lỗi cấu
                # hình (thiếu hằng số Pillow, sai dtype), không phải trang
                # trắng — và hai thứ đó trông giống hệt nhau ở đầu ra.
                self.loi_doc += 1
                continue
            # `predict` trả chuỗi, hoặc (chuỗi, xác suất) khi bật return_prob.
            if isinstance(text, tuple):
                text = text[0]
            text = (text or "").strip()
            if not text:
                continue
            ra.append(Dong(text=text,
                           box={"xmin": x0 / W, "ymin": y0 / H,
                                "xmax": x1 / W, "ymax": y1 / H}))

        # Thứ tự đọc: trên xuống dưới, trái sang phải. Bộ dò trả theo thứ tự
        # phát hiện, không phải thứ tự đọc — không sắp thì văn bản xáo trộn
        # và mọi phép so khớp với ground truth đều sai.
        ra.sort(key=lambda d: (round(d.box["ymin"] * 200), d.box["xmin"]))

        # Dò ra hộp mà đọc hỏng HẾT ⇒ nói thẳng. Trả về danh sách rỗng ở đây
        # là nói dối: trang có chữ, chỉ là bộ đọc không chạy.
        if hop and not ra and self.loi_doc:
            raise RuntimeError(
                f"dò được {len(hop)} dòng nhưng đọc hỏng cả {self.loi_doc} — "
                f"lỗi cấu hình bộ đọc, không phải trang trắng")
        return ra

    def doc_van_ban(self, path: Path) -> str:
        return "\n".join(d.text for d in self.doc_anh(path))


__all__ = ["VietOcrEngine", "Dong", "DEFAULT_WEIGHTS", "MIN_BOX_HEIGHT"]
