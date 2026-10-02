"""Engine gọi LandingAI ADE v2.

VÌ SAO DÙNG JOBS ROUTE CHỨ KHÔNG PHẢI `parse.run()`
───────────────────────────────────────────────────
`client.parse.run()` là lối gọi đồng bộ, và gateway LUÔN tính nó ở tier
priority — gấp đôi giá. Tier `standard` chỉ đạt được qua jobs route:

    job = client.parse.jobs.create(..., service_tier="standard")
    result = client.parse.jobs.wait(job.job_id)

Trên toàn kho 433 trang cần OCR, khác biệt là $1,30 so với $2,60. Số tiền nhỏ,
nhưng cái bẫy thì không: không có gì trong lời gọi sync báo cho ta biết đang
trả giá gấp đôi. Playground cũng luôn chạy priority, nên con số credit thấy ở
đó không phải con số sẽ trả khi chạy qua API.

Thêm một bẫy nữa cùng họ: ở route sync, `service_tier` KHÔNG phải tham số của
`parse.run` mà nằm trong `options`. Truyền nhầm chỗ thì im lặng bị tính
priority. Trên jobs route nó mới là kwarg thật.

VÌ SAO `dpt-3-verity`
─────────────────────
Tài liệu SDK nói model này ground ở mức TỪ và kèm `confidence` cho từng từ,
còn `dpt-3-pro` ground theo dòng và không có confidence.

ĐO THẬT TRÊN BẢN `dpt-3-verity-20260804-preview` (14/09/2026) THÌ KHÔNG PHẢI:

    45/45 segment `atomic_grounding` có `confidence = None`
    độ hạt là theo DÒNG, không phải theo từ

Nên lý do ban đầu để chọn Verity — "biết model không chắc ở chữ nào" — hiện
KHÔNG thành hiện thực. Vẫn giữ Verity, nhưng vì lý do khác và đã kiểm chứng:
nó rẻ nhất (0,3 credits/trang so với 0,9 của Pro ở cùng tier standard), và
trên CCCD thật nó tách đúng 3 phần tử (2 mặt thẻ + 1 con dấu).

Đây là bản `-preview`; confidence có thể xuất hiện ở bản ổn định. Mã phía web
vì vậy vẫn xử lý `confidence` khi có, nhưng KHÔNG được coi nó là điều đương
nhiên — thiếu nó là trạng thái bình thường hôm nay.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, cast

from .base import EngineUnavailable, OcrEngine, OcrResult

__all__ = ["AdeEngine"]

#: Tier hợp lệ. Ràng ở đây vì đây là thứ quyết định giá gấp đôi — một lỗi gõ
#: ("Standard") mà lọt xuống API sẽ bị bỏ qua và im lặng tính giá priority.
_TIERS = ("standard", "priority")


class AdeEngine(OcrEngine):
    """Parse tài liệu qua ADE v2, trả về markdown + cây `structure` có toạ độ."""

    name = "ade"

    # NAS chỉ cần mạng là gọi được — ràng buộc phần cứng không phải vấn đề.
    deployable_on_cpu_nas = True

    # Nhưng tài liệu rời khỏi máy. Giống engine OpenAI, khác mọi engine cục bộ.
    keeps_data_on_device = False

    def __init__(self, *, model: str = "dpt-3-verity",
                 service_tier: str = "standard",
                 api_key: str | None = None,
                 timeout_s: int = 600) -> None:
        super().__init__()
        if service_tier not in _TIERS:
            raise ValueError(
                f"service_tier phải là một trong {_TIERS}, nhận {service_tier!r}")
        self.model = model
        self.service_tier = service_tier
        self.timeout_s = timeout_s
        self._api_key = api_key
        self._client = None
        #: Cộng dồn credits qua các lần gọi — đọc từ `billing.total_credits` mà
        #: API trả về, KHÔNG tự tính lại. Công thức có làm tròn lên và có thể
        #: đổi; con số của nhà cung cấp mới là con số phải trả.
        self.credits_used = 0.0

    def _load(self) -> None:
        key = self._api_key or os.environ.get("VISION_AGENT_API_KEY", "")
        if not key.strip():
            raise EngineUnavailable(
                "thiếu VISION_AGENT_API_KEY — điền vào ~/ocr-lab/.env")

        from landingai_ade import LandingAIADE

        self._api_key = key.strip()
        self._client = LandingAIADE(apikey=self._api_key)

    def parse_document(self, path: Path) -> dict:
        """Parse một tài liệu, trả về dict NGUYÊN VĂN của V2ParseResponse.

        Trả dict thô chứ không phải đối tượng SDK: kho trên đĩa phải sống lâu
        hơn phiên bản thư viện. Một bản nâng cấp SDK đổi tên trường không được
        làm hỏng kết quả đã trả tiền để có.
        """
        self.ensure_ready()
        assert self._client is not None

        with open(path, "rb") as fh:
            job = self._client.v2.parse_jobs.create(
                document=fh,
                model=self.model,
                service_tier=cast(Literal["standard", "priority"],
                                  self.service_tier),
            )

        # `raise_on_failure=True`: mặc định là False, nghĩa là job hỏng vẫn trả
        # về bình thường và chỉ khác nhau ở trường `status`. Im lặng như thế sẽ
        # ghi vào kho một `parse.json` rỗng trông y như tài liệu không có chữ.
        job = self._client.v2.parse_jobs.wait(
            job.job_id, timeout=self.timeout_s, raise_on_failure=True)

        if job.result is None:
            raise RuntimeError(
                f"job {job.job_id} kết thúc ở trạng thái {job.status} nhưng "
                f"không có kết quả"
                + (f": {job.error.message}" if job.error else ""))

        # `wait()` trả về `Job`, không phải `V2ParseResponse` — kết quả parse
        # nằm trong `job.result`. SDK khai kiểu nó là `object` vì cùng một lớp
        # `Job` phục vụ cả parse lẫn extract.
        raw = job.result
        data: dict[str, Any] = (
            raw if isinstance(raw, dict)
            else cast(Any, raw).model_dump(mode="json"))

        # Metadata thường nằm trong result; nó CHỈ nổi lên cấp job khi có
        # `output_save_url`. Đọc cả hai chỗ, nếu không thì credits im lặng
        # thành 0 và ta tưởng lượt chạy miễn phí.
        meta = data.get("metadata") or job.metadata or {}
        billing = meta.get("billing") or {}

        self.credits_used += billing.get("total_credits") or 0.0

        # Đối chiếu tier: xin standard mà bị tính priority là đã trả gấp đôi
        # trong im lặng. Đây đúng là cái bẫy mô tả ở đầu tệp, nên phải bắt tại
        # chỗ chứ không để nó chỉ hiện ra ở hoá đơn cuối tháng.
        got_tier = billing.get("service_tier")
        if got_tier and got_tier != self.service_tier:
            raise RuntimeError(
                f"xin tier {self.service_tier!r} nhưng API tính {got_tier!r} "
                f"— đang trả giá khác giá dự tính")

        return data

    def _read(self, image_path: Path) -> OcrResult:
        """Đọc một ảnh — để khớp interface `OcrEngine` và dùng chung bảng điểm
        với tesseract / llama.cpp / OpenAI."""
        data = self.parse_document(image_path)
        md = data.get("markdown") or ""

        warnings = []
        failed = (data.get("metadata") or {}).get("failed_pages") or []
        if failed:
            # Trả về HTTP 206: parse một phần. Trang hỏng phải lộ ra, nếu không
            # bản chép thiếu nguyên một trang mà bảng điểm vẫn xanh.
            warnings.append(f"ADE KHÔNG đọc được trang: {failed}")
        if not md.strip():
            warnings.append("ADE không trả về chữ nào")

        return OcrResult(md, self.name, 0.0, warnings=warnings)
