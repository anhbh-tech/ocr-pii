"""Sổ đăng ký engine — một chỗ duy nhất để biết máy này chạy được những gì.

Cấu hình lấy từ BIẾN MÔI TRƯỜNG và đường dẫn tương đối, không cắm cứng. Bài
học thật từ `refiny_engine`: một tệp test cắm cứng đường dẫn của devbox Linux
đã ngừng chạy, nên hai test SKIP im lặng suốt nhiều tháng — báo cáo vẫn xanh
trong khi lưới canh không hề tồn tại.
"""

from __future__ import annotations

import os
from pathlib import Path

from .base import EngineUnavailable, OcrEngine, OcrResult
from .ade import AdeEngine
from .llamacpp_vlm import LlamaCppVlmEngine
from .openai_vision import OpenAiVisionEngine
from .tesseract import TesseractEngine

__all__ = ["OcrEngine", "OcrResult", "EngineUnavailable",
           "TesseractEngine", "LlamaCppVlmEngine", "OpenAiVisionEngine",
           "AdeEngine",
           "PROJECT_ROOT", "GGUF_DIR", "available_engines", "build_engine",
           "load_dotenv"]

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GGUF_DIR = Path(os.environ.get("OCR_LAB_GGUF_DIR",
                               PROJECT_ROOT / "models" / "gguf"))


def load_dotenv(path: Path | None = None) -> None:
    """Nạp `.env` ở gốc dự án vào biến môi trường.

    Tự viết thay vì thêm `python-dotenv`: mười dòng cho một dự án đo đạc thì
    rẻ hơn một phụ thuộc phải ghim phiên bản.

    KHÔNG ghi đè biến đã có sẵn trong môi trường — người chạy phải luôn ghi đè
    được `.env` bằng dòng lệnh, nếu không thì việc thử một khoá khác đòi hỏi
    phải sửa tệp, và tệp đó dễ bị commit nhầm.
    """
    env = path or PROJECT_ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = val

#: Model GGUF đã tải và chạy được, dạng (model ngôn ngữ, mmproj).
#:
#: LƯỢNG TỬ HOÁ mmproj — GIỮ NGUYÊN MODEL NGÔN NGỮ
#: ───────────────────────────────────────────────
#: Hai nửa của một VLM phải xử lý KHÁC NHAU. Đo tách biến trên 3 trang, cùng
#: 6 luồng (`scripts/compare_quantisations.py`):
#:
#:     cấu hình              mã hoá   tổng     CER   định danh
#:     bf16 chính chủ         374 s   456 s   0,343     0,905
#:     q4_k_m + mmproj q8      72 s    96 s   0,423     0,671   ← hỏng
#:     bf16 + mmproj q8        71 s   144 s   0,334     0,912   ← chọn
#:
#: Đổi RIÊNG mmproj đã lấy trọn 5,3× tốc độ mã hoá (374→71 s) mà chất lượng
#: còn NHỈNH HƠN bản gốc. Đó là vì mmproj BF16 không có kernel trên CPU ARM,
#: còn Q8_0 thì có — không phải vì bớt độ chính xác.
#:
#: Nhưng hạ tiếp model NGÔN NGỮ xuống Q4_K_M thì phá chất lượng: một trang
#: tụt định danh 0,962 → 0,288. Nhanh thêm 1,5× không bù nổi.
#:
#: BÀI HỌC: lượng tử hoá mạnh tay ở bộ mã hoá thị giác thì gần như miễn phí;
#: ở model ngôn ngữ thì phải trả giá. Đừng gộp hai quyết định làm một.
#:
#: (Phép đo một trang ban đầu từng cho thấy Q4 ổn — đó là ca may. Ba trang đã
#: đủ lộ ra vấn đề.)
_VLM_MODELS = {
    "paddleocr-vl": ("PaddleOCR-VL-1.6-GGUF.gguf", "mmproj-Q8_0.gguf"),
    "paddleocr-vl-bf16": ("PaddleOCR-VL-1.6-GGUF.gguf",
                          "PaddleOCR-VL-1.6-GGUF-mmproj.gguf"),
    "paddleocr-vl-q4": ("PaddleOCR-VL-1.6-Q4_K_M.gguf", "mmproj-Q8_0.gguf"),
}

#: Số luồng mặc định cho engine VLM.
#:
#: M4 có 10 nhân nhưng KHÔNG đồng nhất: 6 hiệu năng + 4 tiết kiệm. llama.cpp
#: đồng bộ theo rào chắn ở mỗi lớp, nên luồng chạy trên nhân tiết kiệm bắt cả
#: nhóm phải chờ. Dùng đúng số nhân hiệu năng thường nhanh hơn dùng hết.
#:
#: Đặt 0 = để engine tự lấy `os.cpu_count()`. Ghi đè bằng OCR_LAB_THREADS.
_DEFAULT_THREADS = int(os.environ.get("OCR_LAB_THREADS", "0"))


def build_engine(spec: str) -> OcrEngine:
    """Dựng engine từ chuỗi mô tả.

        tesseract                → tesseract vie+eng
        tesseract:vie            → chỉ tiếng Việt
        paddleocr-vl             → VLM lượng tử hoá (Q4_K_M + mmproj Q8)
        paddleocr-vl-bf16        → bản chính chủ BF16, để đối chiếu
        paddleocr-vl@1500        → thu nhỏ ảnh về cạnh dài 1500 trước khi đọc
        openai                   → API OpenAI, model mặc định (GỬI ẢNH RA NGOÀI)
        openai:gpt-4o-mini       → chỉ định model
        openai@1200              → thu ảnh về 1200 px để bớt token
        ade                      → LandingAI ADE, dpt-3-verity/standard (GỬI RA NGOÀI)
        ade:dpt-3-pro            → chỉ định model
        ade@priority             → đổi TIER (đắt gấp đôi), không phải kích thước ảnh

    Hậu tố `@N` có ý nghĩa KHÁC NHAU giữa hai loại engine:

    - Engine CỤC BỘ: không phải đòn bẩy tốc độ. Bộ tiền xử lý đã ép mọi ảnh về
      trần `max_pixels` ≈ 1 MP rồi, nên ảnh 6 MP và ảnh 2,8 MP mã hoá hết cùng
      một thời gian. Giữ lại cho ảnh lớn bất thường và để thử nghiệm.
    - Engine ĐÁM MÂY: là đòn bẩy CHI PHÍ thật. OpenAI tính token theo ô
      512×512, nên ảnh to gấp đôi tốn token gấp bốn.
    """
    spec, _, arg = spec.partition("@")
    kind, _, opt = spec.partition(":")

    if kind == "tesseract":
        return TesseractEngine(lang=opt or "vie+eng")

    if kind == "openai":
        # `.env` chỉ nạp khi thực sự cần khoá — engine cục bộ không phải chạm
        # tới tệp bí mật.
        load_dotenv()
        from ..prompts import GENERIC_OCR_PROMPT, LEGAL_OCR_SYSTEM
        return OpenAiVisionEngine(
            model=opt or os.environ.get("OCR_LAB_OPENAI_MODEL", "gpt-4o"),
            system=LEGAL_OCR_SYSTEM,
            prompt=GENERIC_OCR_PROMPT,
            max_side=int(arg) if arg else 2000)

    if kind == "ade":
        # `.env` chỉ nạp khi thực sự cần khoá — engine cục bộ không phải chạm
        # tới tệp bí mật.
        load_dotenv()
        # `@` ở đây là TIER, không phải kích thước ảnh: ADE tự xử lý ảnh, còn
        # tier mới là thứ quyết định giá gấp đôi.
        return AdeEngine(model=opt or "dpt-3-verity",
                         service_tier=arg or "standard")

    if kind in _VLM_MODELS:
        model, mmproj = _VLM_MODELS[kind]
        return LlamaCppVlmEngine(
            GGUF_DIR / model, GGUF_DIR / mmproj,
            max_long_edge=int(arg) if arg else None,
            threads=_DEFAULT_THREADS)

    raise ValueError(
        f"không biết engine {spec!r}; có: tesseract, openai, ade, "
        f"{', '.join(_VLM_MODELS)}")


def available_engines() -> dict[str, str]:
    """Engine nào dùng được trên máy NÀY, kèm lý do nếu không.

    Trả cả engine hỏng kèm lý do chứ không lặng lẽ bỏ qua — engine thiếu mà
    không ai biết là cách một bảng so sánh trở nên sai mà vẫn trông đầy đủ.
    """
    out: dict[str, str] = {}
    for spec in ["tesseract", "openai", "ade", *_VLM_MODELS]:
        try:
            eng = build_engine(spec)
            eng.ensure_ready()
            out[spec] = "sẵn sàng"
        except EngineUnavailable as exc:
            out[spec] = f"không dùng được: {exc}"
        except Exception as exc:              # lỗi lạ — vẫn phải hiện ra
            out[spec] = f"lỗi: {type(exc).__name__}: {exc}"
    return out
