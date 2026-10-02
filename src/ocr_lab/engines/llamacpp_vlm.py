"""Engine VLM chạy qua llama.cpp — đường duy nhất đưa VLM lên CPU được.

VÌ SAO llama.cpp CHỨ KHÔNG PHẢI PyTorch
───────────────────────────────────────
Cùng model, cùng máy, cùng ảnh:

    PyTorch fp32       > 6 phút/ảnh, chưa xong đã phải dừng
    PyTorch bfloat16   > 6 phút/ảnh, RSS 2,42 GB
    llama.cpp GGUF     5 phút 6 giây/ảnh, xong hẳn, có kết quả

PyTorch trên CPU ARM không có kernel cho bfloat16 — phép nhân ma trận rơi về
vòng lặp vô hướng, **chậm hơn float32 540 lần**. llama.cpp có kernel viết tay
cho ARM NEON.

NÚT THẮT LÀ BỘ MÃ HOÁ ẢNH, VÀ NGUYÊN NHÂN LÀ ĐỊNH DẠNG BF16
──────────────────────────────────────────────────────────
Nhật ký llama.cpp tách bạch hai giai đoạn:

    mtmd batch encoding done in 273 822 ms
    tổng                          410 s

**274/410 giây là BỘ MÃ HOÁ ẢNH**, không phải sinh chữ. Kết luận này NGƯỢC với
chẩn đoán cũ trên PyTorch ("toàn bộ thời gian ở sinh token"). Cùng model, đổi
runtime thì nút thắt dời chỗ.

HAI GIẢ THUYẾT SAI ĐÃ LOẠI BẰNG ĐO ĐẠC:

1. "Số token ảnh tỉ lệ với số điểm ảnh, nên thu nhỏ ảnh sẽ nhanh hơn."
   SAI. `preprocessor_config.json` khai `max_pixels = 1 003 520` (≈1 MP): bộ
   tiền xử lý đã tự ép mọi ảnh về trần đó rồi. Ảnh 6 MP và ảnh 2,8 MP cho ra
   **cùng 1 280 token** và mã hoá hết đúng cùng một thời gian (273,8s vs
   274,5s). Hạ hẳn xuống 578 token (ảnh 800px) cũng chỉ giảm 10%.

2. "Thời gian tỉ lệ với số token."
   SAI, theo chính số liệu ở trên: giảm một nửa số token chỉ tiết kiệm 10%.

NGUYÊN NHÂN THẬT: **mmproj phát hành ở BF16**, và CPU Apple Silicon không có
kernel BF16 — phép nhân ma trận rơi về vòng lặp vô hướng. Cùng ảnh, cùng 6
luồng, chỉ đổi định dạng:

    mmproj BF16 (841 MB)   mã hoá 274 s   tổng 410 s
    mmproj Q8_0 (570 MB)   mã hoá  66 s   tổng  82 s
                           ─────────────────────────
                           nhanh gấp 5,0 lần, chữ đọc được NHIỀU HƠN

Phần ngôn ngữ thì không sao: `llama-bench` cho 565 token/s ngay ở BF16. Toàn
bộ thiệt hại nằm ở mmproj.

BÀI HỌC: khi đánh giá VLM trên CPU, phải kiểm định dạng của **mmproj riêng**.
Model ngôn ngữ và bộ mã hoá thị giác thường được phát hành ở định dạng khác
nhau, và các bảng benchmark gần như chỉ nói về phần ngôn ngữ.

`max_long_edge` vì vậy KHÔNG phải đòn bẩy tốc độ (trần 1 MP đã chặn trước nó).
Giữ lại làm tuỳ chọn cho ảnh lớn bất thường, mặc định để `None`.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .base import EngineUnavailable, OcrEngine, OcrResult

__all__ = ["LlamaCppVlmEngine"]

_ENCODE_RE = re.compile(r"batch encoding done in (\d+) ms")

#: Dòng nhật ký của llama.cpp có dạng "0.12.345.678 I nội dung".
_LOG_LINE_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+ [IWED] ")


class LlamaCppVlmEngine(OcrEngine):
    """Gọi `llama-mtmd-cli` trên một model GGUF đa phương thức.

    Chạy qua tiến trình con thay vì nối thư viện: `llama-mtmd-cli` là đường đi
    mà llama.cpp bảo đảm tương thích, còn API C thay đổi giữa các bản. Chi phí
    khởi động ~2 giây, không đáng kể so với 300 giây xử lý — và nó cũng chặn
    được ca model treo, vì tiến trình con giết được.
    """

    name = "llamacpp-vlm"
    deployable_on_cpu_nas = True     # GGUF + kernel CPU, không cần GPU

    def __init__(self, model: Path, mmproj: Path, *,
                 max_long_edge: int | None = None,
                 threads: int = 0, n_predict: int = 2560,
                 prompt: str = "OCR:", timeout_s: int = 900) -> None:
        super().__init__()
        self.model = Path(model)
        self.mmproj = Path(mmproj)
        #: Thu nhỏ ảnh về cạnh dài này trước khi đưa vào model. `None` = giữ
        #: nguyên. Đây là đòn bẩy tốc độ mạnh nhất của engine — xem docstring
        #: đầu tệp.
        self.max_long_edge = max_long_edge
        self.threads = threads or (__import__("os").cpu_count() or 4)
        #: Ngân sách token sinh ra. Mặc định 2560, KHÔNG phải 1024.
        #:
        #: Đo thật: tiếng Việt tốn ~2,6 ký tự/token (nhiều hơn tiếng Anh vì
        #: dấu). Trang dày nhất trong lát MDPBench là 2 844 ký tự ⇒ cần ~1 100
        #: token chỉ để chép hết, chưa kể ký hiệu công thức.
        #:
        #: Với 1024, **6/12 trang trong một lượt đo bị cắt** và bảng điểm báo
        #: định danh 81,9% — con số đó nói về ngân sách token, không nói gì về
        #: model. Đặt rộng tay: token thừa không tốn gì vì model dừng khi hết
        #: nội dung, còn token thiếu thì hỏng cả phép đo.
        self.n_predict = n_predict
        self.prompt = prompt
        self.timeout_s = timeout_s

    def _load(self) -> None:
        if shutil.which("llama-mtmd-cli") is None:
            raise EngineUnavailable(
                "không tìm thấy `llama-mtmd-cli` — cài bằng "
                "`brew install llama.cpp`")
        for path, what in ((self.model, "model"), (self.mmproj, "mmproj")):
            if not path.exists():
                raise EngineUnavailable(f"thiếu tệp {what}: {path}")

    def _prepare_image(self, src: Path, tmpdir: str) -> Path:
        """Thu nhỏ ảnh nếu cần. Trả về đường dẫn ảnh sẽ đưa vào model."""
        if self.max_long_edge is None:
            return src

        from PIL import Image

        im = Image.open(src)
        if max(im.size) <= self.max_long_edge:
            return src

        # Ảnh bảng màu (mode "P") không ghi ra JPEG được, và nội suy trên chỉ
        # số bảng màu là vô nghĩa — phải đổi sang RGB trước.
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")

        scale = self.max_long_edge / max(im.size)
        new = (round(im.width * scale), round(im.height * scale))
        # LANCZOS giữ nét mảnh của dấu tiếng Việt tốt hơn BILINEAR — mà dấu
        # chính là thứ ta không được phép làm mất.
        dst = Path(tmpdir) / f"{src.stem}__{self.max_long_edge}.jpg"
        im.resize(new, Image.Resampling.LANCZOS).save(dst, quality=95)
        return dst

    def _read(self, image_path: Path) -> OcrResult:
        with tempfile.TemporaryDirectory() as tmp:
            img = self._prepare_image(image_path, tmp)
            cmd = [
                "llama-mtmd-cli",
                "-m", str(self.model), "--mmproj", str(self.mmproj),
                "--image", str(img),
                "-p", self.prompt, "-n", str(self.n_predict),
                "--temp", "0",
                # Ép chạy CPU hoàn toàn: đích là NAS không có GPU, nên số đo
                # trên GPU/MPS là vô nghĩa cho quyết định.
                "-ngl", "0", "--no-mmproj-offload",
                "-t", str(self.threads),
                # Không có --jinja thì llama.cpp chết ngay lúc dựng prompt:
                # "this custom template is not supported, try using --jinja".
                "--jinja",
            ]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=self.timeout_s)
            except subprocess.TimeoutExpired:
                return OcrResult(
                    "", self.name, 0.0,
                    warnings=[f"quá {self.timeout_s}s — bỏ qua ảnh này"])

        if r.returncode != 0:
            return OcrResult("", self.name, 0.0,
                             warnings=[f"llama-mtmd-cli lỗi (mã "
                                       f"{r.returncode}): "
                                       f"{r.stderr.strip()[-300:]}"])

        blob = r.stderr + r.stdout
        m = _ENCODE_RE.search(blob)
        encode_ms = float(m.group(1)) if m else 0.0

        text = "\n".join(ln for ln in r.stdout.splitlines()
                         if not _LOG_LINE_RE.match(ln)).strip()

        warnings = []
        if not text:
            warnings.append("model không trả về chữ nào")
        elif self._repetition_ratio(text) > 0.30:
            # ẢO GIÁC LẶP: model kẹt vòng, sinh lại cùng một đoạn nhiều lần.
            # Đo thật: 2/36 trang cho `coverage` 1,96 và 1,67 — gần gấp đôi
            # nội dung trang. Khác hẳn với đọc sai, và cũng khác với bị cắt.
            warnings.append(
                f"ẢO GIÁC LẶP — {self._repetition_ratio(text):.0%} số dòng là "
                f"bản lặp; CER và tỉ lệ định danh của trang này không dùng được")
        elif self._looks_truncated(text):
            warnings.append(
                f"CHẠM TRẦN {self.n_predict} token — văn bản BỊ CẮT, "
                f"CER và tỉ lệ định danh của trang này KHÔNG dùng được")

        return OcrResult(text, self.name, 0.0, encode_ms=encode_ms,
                         warnings=warnings)

    #: Số ký tự trung bình mỗi token cho văn bản tiếng Việt, đo trên đầu ra
    #: thật của model này. Tiếng Việt tốn token hơn tiếng Anh vì dấu.
    _CHARS_PER_TOKEN = 2.6

    @staticmethod
    def _repetition_ratio(text: str) -> float:
        """Tỉ lệ dòng là BẢN LẶP của một dòng khác.

        Ảo giác lặp là lỗi thứ ba, khác hẳn hai lỗi kia:

            bị CẮT      thiếu đuôi, kết thúc giữa câu   (lỗi ngân sách token)
            BỎ SÓT      thiếu giữa, câu cuối tròn       (lỗi model)
            ẢO GIÁC LẶP THỪA, sinh lại cùng đoạn        (lỗi model, nguy hiểm
                                                         nhất vì văn bản bịa
                                                         vẫn đọc trôi chảy)

        Chỉ đếm dòng đủ dài: dòng ngắn ("1.", "A", số trang, ô bảng) lặp lại
        là chuyện bình thường trong tài liệu thật, không phải ảo giác.
        """
        lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 25]
        if len(lines) < 4:
            return 0.0
        return 1.0 - len(set(lines)) / len(lines)

    def _looks_truncated(self, text: str) -> bool:
        """Đoán xem văn bản có bị cắt vì hết ngân sách token không.

        VÌ SAO PHẢI BẮT CHO ĐƯỢC: một trang bị cắt vẫn cho ra văn bản đọc
        trôi chảy, chỉ thiếu phần đuôi. Nó lặng lẽ làm CER xấu đi và kéo tỉ lệ
        định danh xuống — rồi ta đổ oan cho chất lượng model.

        Ca thật đã gặp: `vi_academicpaper_17.jpg` (trang tài liệu tham khảo)
        dừng giữa câu ở "J Sci Food Agric", mất 12/67 định danh. Cả BA cấu
        hình model đều cho đúng 0,821 — con số giống hệt nhau qua ba model
        khác nhau chính là dấu hiệu lỗi nằm ở phép đo, không ở model.

        Bản đầu dùng ngưỡng `len(text) > n_predict * 2.5` và bỏ lọt ca này: tỉ
        lệ thật là 2,61 ký tự/token, nằm ngay trên ngưỡng. Đoán một con số sát
        mép là vô dụng — nên giờ kiểm THÊM dấu hiệu trực tiếp: văn bản kết
        thúc giữa chừng.
        """
        # Dấu hiệu CHẮC CHẮN: đã dùng gần hết ngân sách token.
        near_ceiling = len(text) >= self.n_predict * self._CHARS_PER_TOKEN * 0.92
        if near_ceiling:
            return True

        # Dấu hiệu PHỤ: kết thúc giữa chừng. Chỉ xét khi đã dùng quá nửa ngân
        # sách — nếu không thì model đã dừng vì hết nội dung, và kết thúc lạ
        # chỉ là nội dung lạ.
        #
        # BÁO ĐỘNG GIẢ ĐÃ GẶP: trang `..._screen_...` là ảnh chụp MÀN HÌNH,
        # model đọc đúng cả thanh tìm kiếm trình duyệt nên văn bản kết thúc
        # bằng "Q 搜索". Quy tắc "không phải dấu câu ⇒ bị cắt" gạt nhầm trang
        # đó khỏi phép đo — mất dữ liệu vì một luật quá thô.
        if len(text) < self.n_predict * self._CHARS_PER_TOKEN * 0.5:
            return False

        tail = text.rstrip()
        if not tail:
            return False

        # Dấu kết thúc hợp lệ: dấu câu, hoặc SỐ đứng một mình ở dòng cuối
        # (số trang). Chữ cái/chữ Hán ở cuối thì phải xét tiếp — nó vừa có
        # thể là câu bị cắt, vừa có thể là nhãn giao diện trong ảnh chụp
        # màn hình.
        if tail[-1] in ".!?:;)]}\"'\u2026\u201d\u2019":
            return False

        last_line = tail.splitlines()[-1].strip()
        if last_line.isdigit():          # số trang đứng riêng
            return False

        # Dòng cuối ngắn ⇒ nhãn, tiêu đề, phần tử giao diện — không phải câu
        # văn bị chặt ngang. Câu bị cắt giữa chừng thì dòng cuối luôn dài.
        # (Ca thật: ảnh chụp màn hình kết thúc bằng "Q 搜索" — 5 ký tự.)
        return len(last_line) > 40
