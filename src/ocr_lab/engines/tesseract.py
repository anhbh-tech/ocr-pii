"""Engine tesseract — đường cơ sở, và là engine duy nhất chắc chắn chạy trên NAS.

VAI TRÒ TRONG DỰ ÁN
───────────────────
Tesseract không phải lựa chọn tốt nhất về chất lượng: trên kho thật nó chỉ đạt
tỉ lệ dấu 0,080 (ảnh) / 0,102 (PDF) so với 0,217 của tiếng Việt thật — mất hơn
nửa số dấu. Nhưng nó là engine DUY NHẤT hiện chạy được trên đích triển khai,
nên mọi engine khác phải so với nó, và nó là đường lui nếu không engine nào
đạt cổng kiểm.

BA TẦNG GỌI, THEO ĐÚNG THỨ TỰ NHANH DẦN
───────────────────────────────────────
`tesserocr` → `pytesseract` → gọi nhị phân trực tiếp.

Khác biệt không nhỏ: `pytesseract` sinh một tiến trình tesseract mới **và nạp
lại traineddata** ở MỖI lần gọi. `tesserocr` nối thẳng vào API C++, nạp model
một lần cho cả tiến trình. Đo trên một hồ sơ thật: **nhanh gấp 1,98 lần, đầu
ra giống nhau từng byte.**

Vẫn giữ đủ ba tầng vì tầng dưới cùng không cần cài gì thêm ngoài nhị phân
tesseract — quan trọng khi dựng trên NAS.

`--oem 1` (chỉ LSTM): bản mặc định `--oem 3` có thể chạy thêm engine cũ, chậm
hơn mà không chính xác hơn trên traineddata hiện đại.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .base import EngineUnavailable, OcrEngine, OcrResult

__all__ = ["TesseractEngine"]

#: PSM 6 = "một khối chữ đồng nhất" — đúng với phần lớn trang tài liệu.
_DEFAULT_PSM = 6


class TesseractEngine(OcrEngine):
    """Tesseract 5.x với traineddata `vie+eng`.

    Mặc định `vie+eng` chứ không phải `vie` riêng: tài liệu trong kho hay trộn
    tên riêng, thuật ngữ và địa chỉ tiếng Anh. Thứ tự có ý nghĩa — tesseract ưu
    tiên ngôn ngữ đứng trước.
    """

    name = "tesseract"
    deployable_on_cpu_nas = True     # ← engine duy nhất hiện đạt điều kiện này

    def __init__(self, lang: str = "vie+eng", psm: int = _DEFAULT_PSM) -> None:
        super().__init__()
        self.lang = lang
        self.psm = psm
        self._api = None          # tesserocr, nếu có
        self._backend = "?"

    def _load(self) -> None:
        # Tầng 1: tesserocr — nạp model một lần cho cả tiến trình.
        try:
            import tesserocr

            self._api = tesserocr.PyTessBaseAPI(
                lang=self.lang, oem=tesserocr.OEM.LSTM_ONLY)
            self._api.SetPageSegMode(self.psm)
            self._backend = "tesserocr"
            return
        except Exception:
            pass

        # Tầng 2: pytesseract — vẫn tiện, nhưng nạp lại model mỗi lần gọi.
        try:
            import pytesseract

            pytesseract.get_tesseract_version()
            self._backend = "pytesseract"
            return
        except Exception:
            pass

        # Tầng 3: gọi thẳng nhị phân. Không cần cài gói Python nào.
        if shutil.which("tesseract") is None:
            raise EngineUnavailable(
                "không tìm thấy tesseract — cài bằng `brew install tesseract "
                "tesseract-lang` hoặc `apt install tesseract-ocr "
                "tesseract-ocr-vie`")
        self._backend = "binary"
        self._check_languages()

    def _check_languages(self) -> None:
        """Kiểm traineddata có đủ không, NGAY LÚC NẠP.

        Thiếu `vie` thì tesseract vẫn chạy và vẫn ra chữ — bằng model tiếng
        Anh. Kết quả là một bảng điểm trông hợp lệ nhưng đo sai ngôn ngữ. Phải
        chết ngay ở đây thay vì cho ra số sai.
        """
        r = subprocess.run(["tesseract", "--list-langs"],
                           capture_output=True, text=True)
        have = {ln.strip() for ln in r.stdout.splitlines()[1:] if ln.strip()}
        missing = [x for x in self.lang.split("+") if x not in have]
        if missing:
            raise EngineUnavailable(
                f"thiếu traineddata {missing} (đang có {len(have)} ngôn ngữ). "
                f"Không có `vie` thì tesseract vẫn chạy bằng model tiếng Anh "
                f"và cho ra số liệu sai — dừng ở đây thay vì đo sai.")

    def _read(self, image_path: Path) -> OcrResult:
        if self._backend == "tesserocr":
            self._api.SetImageFile(str(image_path))
            text = self._api.GetUTF8Text()
            # MeanTextConf trả thang 0–100; đổi về 0–1 cho thống nhất.
            conf = self._api.MeanTextConf() / 100.0
            return OcrResult(text.strip(), self.name, 0.0,
                             confidence=conf if conf >= 0 else None)

        if self._backend == "pytesseract":
            import pytesseract
            from PIL import Image

            text = pytesseract.image_to_string(
                Image.open(image_path), lang=self.lang,
                config=f"--oem 1 --psm {self.psm}")
            return OcrResult(text.strip(), self.name, 0.0)

        return self._read_via_binary(image_path)

    def _read_via_binary(self, image_path: Path) -> OcrResult:
        """Gọi nhị phân tesseract, ghi ra tệp tạm.

        `OMP_THREAD_LIMIT=1`: luồng OpenMP bên trong tesseract xung đột với
        việc chạy song song nhiều trang ở tầng trên. Để mặc định thì chạy song
        song không nhanh hơn, có khi còn chậm đi. Một trang lẻ cũng gần như
        không thiệt gì.
        """
        with tempfile.TemporaryDirectory() as tmp:
            stem = Path(tmp) / "out"
            env = {**os.environ, "OMP_THREAD_LIMIT": "1"}
            r = subprocess.run(
                ["tesseract", str(image_path), str(stem),
                 "-l", self.lang, "--oem", "1", "--psm", str(self.psm)],
                capture_output=True, text=True, env=env)

            txt = stem.with_suffix(".txt")
            if r.returncode != 0 or not txt.exists():
                return OcrResult(
                    "", self.name, 0.0,
                    warnings=[f"tesseract lỗi (mã {r.returncode}): "
                              f"{r.stderr.strip()[:200]}"])

            return OcrResult(txt.read_text(encoding="utf-8").strip(),
                             self.name, 0.0)

    def __del__(self) -> None:
        if self._api is not None:
            try:
                self._api.End()
            except Exception:
                pass
