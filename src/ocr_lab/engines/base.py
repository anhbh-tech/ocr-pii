"""Giao diện chung cho mọi engine OCR.

VÌ SAO CẦN LỚP TRỪU TƯỢNG NÀY
─────────────────────────────
Hai lý do, lý do thứ hai mới là lý do thật:

1. Để so sánh engine trên CÙNG một đầu vào, cùng cách bấm giờ, cùng cách đếm.
   Không có nó thì mỗi engine được đo bằng một đoạn mã riêng và ta đang so
   những con số không so được với nhau.

2. **Để ràng buộc triển khai không thể bị quên.** Đích của dự án là NAS chỉ có
   CPU. Apple Vision nhanh hơn tesseract 9,9 lần và sạch hơn hẳn, nhưng nó chỉ
   chạy trên macOS + Neural Engine — không bao giờ triển khai được. Nửa ngày đo
   đạc đã mất vì phát hiện điều đó muộn.

   Nên `deployable_on_cpu_nas` là một TRƯỜNG BẮT BUỘC của mỗi engine, không
   phải một dòng chú thích. Bảng so sánh phải in nó ra ở mọi báo cáo, để không
   ai đọc bảng rồi chọn nhầm một engine không triển khai được.

VÌ SAO TÊN LÀ `OcrResult` CHỨ KHÔNG PHẢI `PageResult`
────────────────────────────────────────────────────
`classify.PageResult` đã tồn tại và mang nghĩa khác hẳn: nó nói trang này
thuộc LOẠI nào (số hoá sẵn / quét / gần trống). Còn đây là KẾT QUẢ ĐỌC. Hai
thứ đi cạnh nhau trong cùng một đường xử lý, trùng tên là mời gọi nhầm lẫn.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["OcrResult", "OcrEngine", "EngineUnavailable"]


class EngineUnavailable(RuntimeError):
    """Engine không dùng được trên máy này (thiếu nhị phân, thiếu model…).

    Là ngoại lệ riêng chứ không phải `RuntimeError` trần, để bộ so sánh phân
    biệt được "engine này không cài" với "engine này chạy nhưng lỗi". Gộp hai
    thứ lại sẽ dẫn tới `except Exception → skip`, và một engine hỏng sẽ trông
    y hệt một engine chưa cài — đúng kiểu xanh giả mà dự án này đã gặp.
    """


@dataclass(frozen=True)
class OcrResult:
    """Kết quả đọc MỘT ảnh."""

    text: str
    engine: str
    elapsed_ms: float

    #: Thời gian mã hoá ảnh, tách khỏi thời gian sinh chữ. Engine nào không
    #: tách được thì để 0.
    #:
    #: Trường này tồn tại vì một phát hiện đo được: cùng model SenOCR-Vi,
    #: trên PyTorch thì toàn bộ thời gian nằm ở sinh token, còn trên llama.cpp
    #: thì **261/306 giây nằm ở mã hoá ảnh**. Chỉ có tổng thời gian thì không
    #: nhìn ra điều đó, và ta sẽ tối ưu nhầm chỗ.
    encode_ms: float = 0.0

    #: Độ tin cậy do engine tự báo, thang 0–1. `None` khi engine không báo.
    #: KHÔNG tự chế ra số này — độ tin cậy bịa còn tệ hơn không có.
    confidence: float | None = None

    warnings: list[str] = field(default_factory=list)

    @property
    def generate_ms(self) -> float:
        return max(0.0, self.elapsed_ms - self.encode_ms)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


class OcrEngine(ABC):
    """Lớp cơ sở cho mọi engine.

    Dùng lớp trừu tượng thay vì `Protocol` vì ta cần ép buộc khai báo
    `deployable_on_cpu_nas` — `Protocol` chỉ kiểm khi có type checker chạy,
    còn ở đây ta muốn quên là lỗi ngay lúc chạy.
    """

    #: Tên ngắn dùng trong báo cáo và tham số dòng lệnh.
    name: str = "base"

    #: CHẠY ĐƯỢC TRÊN NAS CHỈ CÓ CPU KHÔNG?
    #:
    #: `False` nghĩa là engine này chỉ dùng để đối chiếu khi phát triển, kết
    #: quả của nó KHÔNG được dùng làm căn cứ chọn engine. Apple Vision là ca
    #: điển hình: nhanh và chính xác hơn hẳn, nhưng không triển khai được.
    deployable_on_cpu_nas: bool = False

    #: DỮ LIỆU CÓ Ở LẠI TRONG MÁY KHÔNG?
    #:
    #: Trục ràng buộc THỨ HAI, độc lập với trục phần cứng ở trên — và với hồ
    #: sơ khách hàng thì nó mới là trục quyết định.
    #:
    #: Một engine gọi API đám mây có `deployable_on_cpu_nas = True` (NAS chỉ
    #: cần mạng là gọi được) nhưng `keeps_data_on_device = False`: mỗi trang
    #: quét — CCCD, biên lai, hợp đồng — rời khỏi máy khách hàng. Gộp hai
    #: trục vào một cờ thì engine đám mây trông y hệt engine cục bộ trong
    #: bảng so sánh, và người đọc bảng sẽ chọn nhầm.
    #:
    #: Mặc định `True`: engine chạy cục bộ là trường hợp thường; engine nào
    #: gửi dữ liệu ra ngoài phải TỰ khai báo điều đó.
    keeps_data_on_device: bool = True

    def __init__(self) -> None:
        self._ready = False

    @abstractmethod
    def _load(self) -> None:
        """Nạp model / kiểm công cụ. Thiếu thì ném `EngineUnavailable`."""

    @abstractmethod
    def _read(self, image_path: Path) -> OcrResult:
        """Đọc một ảnh. Không tự bấm giờ — `read_page` lo việc đó."""

    def ensure_ready(self) -> None:
        """Nạp một lần duy nhất.

        Tách khỏi `__init__` vì hai lý do đo lường: thời gian nạp không được
        tính vào thời gian đọc trang đầu tiên, và bộ so sánh phải liệt kê được
        các engine mà không phải nạp model của chúng.
        """
        if not self._ready:
            self._load()
            self._ready = True

    def read_page(self, image_path: str | Path) -> OcrResult:
        """Đọc một ảnh, có bấm giờ.

        Bấm giờ ở đây chứ không ở từng engine con, để mọi engine được đo bằng
        cùng một cái đồng hồ. `perf_counter` chứ không phải `time.time`:
        `time.time` nhảy khi hệ thống chỉnh giờ.
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(path)

        self.ensure_ready()
        t0 = time.perf_counter()
        result = self._read(path)
        elapsed = (time.perf_counter() - t0) * 1000

        # Engine con có thể đã tự điền elapsed_ms; đồng hồ ngoài mới là chuẩn
        # vì nó tính cả phần chi phí mà engine không thấy (khởi động tiến
        # trình con, đọc tệp…) — đó là chi phí thật khi triển khai.
        from dataclasses import replace
        return replace(result, elapsed_ms=elapsed)

    def __repr__(self) -> str:
        flag = "cpu-nas ✓" if self.deployable_on_cpu_nas else "cpu-nas ✗"
        local = "cục bộ" if self.keeps_data_on_device else "GỬI RA NGOÀI"
        return f"<{type(self).__name__} {self.name!r} {flag} {local}>"
