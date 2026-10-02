"""Engine OCR gọi API thị giác của OpenAI.

ĐÂY LÀ ENGINE ĐẦU TIÊN ĐƯA DỮ LIỆU RA KHỎI MÁY
──────────────────────────────────────────────
Mọi engine trước đó — tesseract, llama.cpp — đọc ảnh ngay trên máy. Engine này
thì không: mỗi ảnh được mã hoá base64 rồi gửi tới máy chủ OpenAI. Với hồ sơ
khách hàng (CCCD, biên lai, hợp đồng) đó là một quyết định pháp lý, không phải
một lựa chọn kỹ thuật.

Vì vậy `keeps_data_on_device = False`, và bộ so sánh phải in cờ đó ra cạnh mọi
con số của engine này. Nhanh hơn và chính xác hơn KHÔNG bù lại được việc tài
liệu rời khỏi máy, nếu hợp đồng với khách hàng không cho phép.

VÌ SAO KHÔNG DÙNG THƯ VIỆN `openai`
───────────────────────────────────
Gọi thẳng HTTP bằng `urllib` trong thư viện chuẩn. Lý do là để KHÔNG thêm một
phụ thuộc nữa vào một dự án đo đạc: thư viện `openai` kéo theo httpx, pydantic
và một chuỗi phụ thuộc riêng, mỗi cái là một ràng buộc phiên bản phải bảo trì.
Ở đây ta chỉ cần POST một tệp JSON tới một địa chỉ — không đáng đánh đổi.

VÌ SAO CÓ `max_side` MẶC ĐỊNH 2000
──────────────────────────────────
Khác hẳn engine cục bộ, ở đây kích thước ảnh ĐÚNG LÀ tiền. PaddleOCR-VL ép mọi
ảnh về trần ~1 MP nên thu nhỏ ảnh không giúp gì; còn OpenAI tính token theo ô
512×512, nên ảnh to gấp đôi thì tốn token gấp bốn. 2000 px cạnh dài là đủ cho
chữ trên giấy A4 quét 200 DPI mà không trả tiền cho điểm ảnh thừa.

VỀ CHI PHÍ VÀ TRẦN SỐ ẢNH
─────────────────────────
Engine có `max_images` (mặc định 0 = không chặn) để script gọi nó tự áp trần.
Một vòng lặp lỗi trên 300 ảnh là một hoá đơn, không phải một lần chạy thử hỏng.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from .base import EngineUnavailable, OcrEngine, OcrResult

__all__ = ["OpenAiVisionEngine"]

#: Lời nhắc. Cố ý KHÔNG yêu cầu model "hiểu" hay "tóm tắt" — chỉ chép lại.
#:
#: Một model sinh văn bản được hỏi "tài liệu này nói gì" sẽ diễn giải, và diễn
#: giải là ảo giác đội lốt OCR. Yêu cầu chép nguyên văn giữ nó ở đúng vai trò
#: một bộ đọc, và giữ cho tỉ lệ định danh có ý nghĩa.
_DEFAULT_PROMPT = (
    "Chép lại TOÀN BỘ chữ nhìn thấy trong ảnh này, giữ nguyên thứ tự đọc "
    "từ trên xuống dưới, trái sang phải.\n"
    "- Giữ nguyên chính tả, dấu tiếng Việt, chữ hoa/thường, dấu câu.\n"
    "- Giữ nguyên mọi con số, mã số, ngày tháng, email đúng từng ký tự.\n"
    "- Xuống dòng ở đúng chỗ tài liệu xuống dòng.\n"
    "- KHÔNG tóm tắt, KHÔNG giải thích, KHÔNG thêm bất cứ lời dẫn nào.\n"
    "- Nếu một chỗ không đọc được, ghi [không đọc được] tại đúng vị trí đó.\n"
    "Chỉ trả về phần chữ đã chép."
)

#: Đuôi tệp → kiểu MIME. API từ chối kiểu nó không biết, nên phải khai đúng
#: chứ không đoán bằng `image/jpeg` cho mọi thứ.
_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
         ".gif": "image/gif", ".webp": "image/webp"}

#: Câu mở đầu của một lần TỪ CHỐI. Model từ chối trả về văn xuôi lịch sự thay
#: vì chữ trong ảnh — nhìn qua giống một lần đọc kém, nhưng thực chất là KHÔNG
#: CÓ kết quả. Hai thứ đó phải tách bạch, nếu không một lần từ chối sẽ vào bảng
#: điểm như một lần đọc sai và kéo tụt điểm của model một cách vô nghĩa.
_REFUSAL_MARKERS = (
    "i'm sorry", "i am sorry", "i can't", "i cannot", "i'm unable",
    "unable to", "can't assist", "cannot assist", "can't help with",
    "xin lỗi", "tôi không thể", "không thể hỗ trợ",
)


class OpenAiVisionEngine(OcrEngine):
    """Đọc ảnh bằng một model thị giác của OpenAI qua Chat Completions."""

    name = "openai-vision"

    # NAS chỉ cần mạng là gọi được — ràng buộc phần cứng không phải vấn đề ở
    # đây. Vấn đề nằm ở dòng dưới.
    deployable_on_cpu_nas = True

    # Ảnh rời khỏi máy. Đây là lý do engine này không thể là mặc định cho hồ
    # sơ khách hàng, bất kể nó đọc tốt đến đâu.
    keeps_data_on_device = False

    def __init__(self, model: str = "gpt-4o", *,
                 prompt: str = _DEFAULT_PROMPT,
                 system: str | None = None,
                 max_side: int = 2000,
                 detail: str = "high",
                 timeout_s: int = 180,
                 max_tokens: int = 4096,
                 pdf_dpi: int = 200,
                 api_key: str | None = None,
                 base_url: str | None = None) -> None:
        super().__init__()
        self.model = model
        self.prompt = prompt
        #: Lời nhắc hệ thống. `None` = không gửi.
        #:
        #: Tách khỏi `prompt` vì hai thứ đổi theo nhịp khác nhau: lời nhắc hệ
        #: thống đặt ngữ cảnh MỘT LẦN cho cả lượt chạy, còn `prompt` đổi theo
        #: từng loại tài liệu (giấy tờ tuỳ thân xuất theo trường, đơn từ chép
        #: tự do). Gộp lại thì đổi loại tài liệu là mất ngữ cảnh.
        self.system = system
        #: Thu ảnh về cạnh dài này trước khi gửi. Ở engine đám mây đây là đòn
        #: bẩy CHI PHÍ thật sự, khác với engine cục bộ (xem docstring đầu tệp).
        self.max_side = max_side
        #: "high" = model nhìn ảnh ở độ phân giải đầy đủ. "low" rẻ hơn nhiều
        #: nhưng ép ảnh về 512×512 — vô dụng cho chữ trên tài liệu.
        self.detail = detail
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        #: DPI khi dựng ảnh từ trang PDF.
        #:
        #: 200 chứ không phải 300/400: đo thật trên hồ sơ quét cho thấy dựng ở
        #: DPI cao hơn ảnh gốc chỉ nội suy thêm điểm ảnh không có thật — nhiều
        #: ký tự hơn 7% nhưng tỉ lệ dấu THẤP hơn, vì chữ thêm ra là nhiễu viền.
        #: Chất lượng bị chặn bởi bản quét gốc, không bởi số DPI ta chọn.
        self.pdf_dpi = pdf_dpi
        self._api_key = api_key
        self.base_url = (base_url or os.environ.get(
            "OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        #: Tổng token đã dùng, cộng dồn qua các ảnh — để script gọi ước tính
        #: chi phí thật thay vì đoán.
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def _load(self) -> None:
        key = self._api_key or os.environ.get("OPENAI_API_KEY", "")
        if not key.strip():
            raise EngineUnavailable(
                "thiếu OPENAI_API_KEY — điền vào ~/ocr-lab/.env "
                "hoặc xuất ra biến môi trường")
        self._api_key = key.strip()

    def _encode(self, path: Path) -> tuple[str, str]:
        """Trả về (base64, mime). Thu nhỏ ảnh nếu vượt `max_side`.

        PDF được dựng thành ảnh trước — xem `_render_pdf`.
        """
        import io

        from PIL import Image

        suffix = path.suffix.lower()

        if suffix == ".pdf":
            im = self._render_pdf(path)
        elif suffix in _MIME:
            im = Image.open(path)
            # Ảnh đã vừa khổ thì gửi nguyên byte gốc: mã hoá lại một tấm JPEG
            # là mất chất lượng mà không được gì.
            if max(im.size) <= self.max_side:
                return (base64.b64encode(path.read_bytes()).decode(),
                        _MIME[suffix])
        else:
            raise ValueError(f"kiểu tệp không hỗ trợ: {suffix}")

        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")

        if max(im.size) > self.max_side:
            scale = self.max_side / max(im.size)
            new = (round(im.width * scale), round(im.height * scale))
            # LANCZOS: giữ nét mảnh của dấu tiếng Việt — thứ không được mất.
            im = im.resize(new, Image.Resampling.LANCZOS)

        # Đã phải dựng/thu nhỏ thì luôn xuất JPEG: PNG của ảnh chụp tài liệu
        # thường nặng gấp nhiều lần mà không sắc nét hơn, và ở đây byte là tiền.
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=92)
        return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"

    def _render_pdf(self, path: Path):
        """Dựng TRANG ĐẦU của PDF thành một ảnh.

        VÌ SAO GHÉP CẢ TRANG CHỨ KHÔNG TÁCH TỪNG ẢNH NHÚNG
        ──────────────────────────────────────────────────
        Một trang PDF chứa CCCD thường có hai ảnh nhúng (mặt trước, mặt sau).
        Rút riêng từng ảnh nghe có vẻ gọn hơn, nhưng làm mất thứ tự và mất mọi
        chữ nằm trên trang chứ không nằm trong ảnh. Dựng cả trang giữ nguyên
        những gì người xem thấy — và đó chính là thứ ta muốn chép lại.

        CHỈ TRANG ĐẦU: engine này đọc MỘT ảnh cho mỗi lần gọi, đúng giao diện
        `OcrEngine.read_page`. PDF nhiều trang phải do lớp gọi tách ra, nếu
        không thì các trang sau bị bỏ qua âm thầm — đúng kiểu mất dữ liệu mà
        không ai biết. `read_pdf_pages()` làm việc đó một cách tường minh.
        """
        import pymupdf
        from PIL import Image

        with pymupdf.open(path) as doc:
            if doc.page_count == 0:
                raise ValueError(f"PDF không có trang nào: {path.name}")
            pix = doc[0].get_pixmap(dpi=self.pdf_dpi)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    def read_pdf_pages(self, path: Path) -> list[OcrResult]:
        """Đọc MỌI trang của một PDF, mỗi trang một lần gọi API.

        Tách riêng khỏi `read_page` chứ không cho nó tự lặp: mỗi trang là một
        lần gọi có tính tiền, nên việc "một tệp = bao nhiêu lần gọi" phải nhìn
        thấy được ở nơi gọi, không giấu bên trong.
        """
        import tempfile

        import pymupdf
        from PIL import Image

        results: list[OcrResult] = []
        with pymupdf.open(path) as doc:
            for n in range(doc.page_count):
                pix = doc[n].get_pixmap(dpi=self.pdf_dpi)
                im = Image.frombytes("RGB", (pix.width, pix.height),
                                     pix.samples)
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_img = Path(tmp) / f"{path.stem}_p{n + 1}.png"
                    im.save(tmp_img)
                    results.append(self.read_page(tmp_img))
        return results

    def _read(self, image_path: Path) -> OcrResult:
        b64, mime = self._encode(image_path)
        messages = []
        if self.system:
            messages.append({"role": "system", "content": self.system})
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": self.prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:{mime};base64,{b64}",
                    "detail": self.detail}},
            ],
        })
        payload = {
            "model": self.model,
            "max_completion_tokens": self.max_tokens,
            "messages": messages,
        }

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self._api_key}",
                     "Content-Type": "application/json"})

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                body = json.loads(r.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            # Trả OcrResult rỗng kèm cảnh báo chứ không ném: một ảnh hỏng
            # không được làm sập cả lượt chạy đã trả tiền cho các ảnh trước.
            return OcrResult("", self.name, 0.0,
                             warnings=[f"HTTP {exc.code}: {detail}"])
        except urllib.error.URLError as exc:
            return OcrResult("", self.name, 0.0,
                             warnings=[f"lỗi mạng: {exc.reason}"])

        use = body.get("usage", {})
        self.usage["prompt_tokens"] += use.get("prompt_tokens", 0)
        self.usage["completion_tokens"] += use.get("completion_tokens", 0)

        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message", {})

        # Trường `refusal` là lời từ chối TƯỜNG MINH của API — chắc chắn hơn
        # mọi phép dò chuỗi, nên xét trước.
        explicit = message.get("refusal")
        text = (message.get("content") or "").strip()

        warnings = []
        if explicit:
            return OcrResult("", self.name, 0.0, warnings=[
                f"MODEL TỪ CHỐI (trường refusal của API): {explicit[:200]}"])

        if not text:
            warnings.append("model không trả về chữ nào")
        # `length` = chạm trần token ⇒ văn bản BỊ CẮT. Phải báo, vì trang bị
        # cắt vẫn đọc trôi chảy và sẽ lặng lẽ kéo CER/tỉ lệ định danh xuống,
        # rồi ta đổ oan cho chất lượng model (bài học từ engine llama.cpp).
        if choice.get("finish_reason") == "length":
            warnings.append(
                f"CHẠM TRẦN {self.max_tokens} token — văn bản BỊ CẮT, "
                f"CER và tỉ lệ định danh của ảnh này KHÔNG dùng được")
        elif self._looks_like_refusal(text):
            # Từ chối "mềm": model trả văn xuôi lịch sự thay vì chữ trong ảnh.
            # Đây là KHÔNG CÓ kết quả, không phải đọc sai — phải tách bạch,
            # nếu không nó vào bảng điểm như một lần đọc kém.
            warnings.append(
                "MODEL TỪ CHỐI đọc ảnh này — đây là KHÔNG CÓ kết quả, "
                "không phải đọc sai; loại khỏi mọi phép tính trung bình")

        return OcrResult(text, self.name, 0.0, warnings=warnings)

    @staticmethod
    def _looks_like_refusal(text: str) -> bool:
        """Đoán xem đây là lời từ chối hay bản chép thật.

        NGƯỠNG ĐỘ DÀI LÀ PHẦN QUAN TRỌNG NHẤT, KHÔNG PHẢI DANH SÁCH TỪ KHOÁ.
        Một bản chép CCCD thật hoàn toàn có thể chứa chuỗi "không thể" (trong
        một dòng ghi chú in trên thẻ, hay trong tên tài liệu). Chỉ khi đầu ra
        NGẮN mà lại mang giọng xin lỗi thì mới là từ chối.

        400 ký tự: dài hơn mọi câu từ chối đã gặp, ngắn hơn mọi bản chép giấy
        tờ thật (CCCD đủ trường ≈ 900 ký tự). Khoảng cách rộng nên ngưỡng
        không cần chính xác.
        """
        head = text[:400].lower()
        return len(text) < 400 and any(m in head for m in _REFUSAL_MARKERS)
