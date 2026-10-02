"""`POST /api/classify` — cho bên gọi ngoài (jev ai) hỏi "tài liệu này đi đường nào".

    uv run python scripts/serve_classify.py            # http://127.0.0.1:8812
    make classify-api

Hai cách gửi tài liệu:

    # tải nội dung lên — tệp KHÔNG bị ghi ra đĩa, chỉ phân loại trong bộ nhớ
    curl --data-binary @hop_dong.pdf -H 'Content-Type: application/octet-stream' \\
         'http://127.0.0.1:8812/api/classify?filename=hop_dong.pdf'

    # trỏ tới tệp cục bộ trên máy chạy server — đường dẫn tuyệt đối
    curl -H 'Content-Type: application/json' -d '{"path": "/abs/hop_dong.pdf"}' \\
         http://127.0.0.1:8812/api/classify

Khuôn trả về: `docs/classify-api.md` (kèm kiểu TypeScript), JSON Schema tại
`GET /api/classify/schema`.

VÌ SAO LÀ SERVER RIÊNG, KHÔNG GẮN VÀO `serve_review.py`
───────────────────────────────────────────────────────
`serve_review.py` có `--tailnet` để mở cho điện thoại trong tailnet. Endpoint
này nhận ĐƯỜNG DẪN TUYỆT ĐỐI bất kỳ trên máy — gắn vào đó thì bật `--tailnet`
một cái là thiết bị khác đọc được tín hiệu của mọi tệp trên đĩa. Ở đây host
bị GHI CỨNG `127.0.0.1`, không có cờ nào đổi được.

HAI LỚP CHẶN TRÌNH DUYỆT
────────────────────────
Một trang web lạ mở trong trình duyệt của chính máy này vẫn gửi được request
tới 127.0.0.1. Nên:

- `TrustedHostMiddleware` chỉ nhận `Host: 127.0.0.1` / `localhost` — chặn DNS
  rebinding (tên miền lạ trỏ về 127.0.0.1).
- Chế độ đường dẫn CHỈ nhận `Content-Type: application/json`, mà kiểu đó buộc
  trình duyệt hỏi CORS trước; server không bật CORS nên trang lạ bị chặn ngay
  từ bước hỏi. Không có CORS thì trang lạ cũng không đọc được kết quả.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fastapi import FastAPI, HTTPException, Query, Request         # noqa: E402
from fastapi.concurrency import run_in_threadpool                   # noqa: E402
from fastapi.responses import FileResponse, JSONResponse            # noqa: E402
from pydantic import BaseModel, ConfigDict, ValidationError         # noqa: E402
from starlette.middleware.trustedhost import TrustedHostMiddleware  # noqa: E402

from ocr_lab.classify_api import classify_bytes, classify_path      # noqa: E402

SCHEMA = ROOT / "docs" / "classify-api.schema.json"

#: Trần kích thước một tệp. Hồ sơ scan dày nhất trong kho cỡ vài chục MB;
#: 200 MB là mép rộng mà vẫn không để một request nuốt hết RAM.
MAX_BYTES = 200 * 1024 * 1024

app = FastAPI(title="ocr-lab · phân loại tài liệu")
app.add_middleware(TrustedHostMiddleware,
                   allowed_hosts=["127.0.0.1", "localhost"])


class TheoDuongDan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str


def _qua_lon(n: int) -> HTTPException:
    return HTTPException(413, f"tệp {n} byte, vượt trần {MAX_BYTES} byte")


@app.post("/api/classify")
async def classify(request: Request,
                   filename: str = Query("", max_length=1024)) -> JSONResponse:
    loai = request.headers.get("content-type", "").split(";")[0].strip().lower()

    if loai == "application/json":
        try:
            yc = TheoDuongDan.model_validate_json(await request.body())
        except ValidationError as exc:
            raise HTTPException(422, f"cần đúng {{\"path\": \"/đường/dẫn/tuyệt/đối\"}}: "
                                     f"{exc.errors()[0]['msg']}") from None
        p = Path(yc.path)
        if not p.is_absolute():
            raise HTTPException(400, "path phải là đường dẫn tuyệt đối")
        if not p.exists():
            raise HTTPException(404, "không có tệp này")
        if not p.is_file():
            raise HTTPException(400, "path không phải một tệp")
        if p.stat().st_size > MAX_BYTES:
            raise _qua_lon(p.stat().st_size)
        return JSONResponse(await run_in_threadpool(classify_path, p))

    if loai == "multipart/form-data":
        raise HTTPException(415, "không nhận multipart/form-data (FormData): "
                                 "gửi thẳng byte của tệp làm thân request, "
                                 "Content-Type: application/octet-stream, "
                                 "tên tệp ở ?filename=")

    # Còn lại: thân request CHÍNH LÀ nội dung tệp. Đọc từng khúc để cắt ngay
    # khi vượt trần, không đợi nạp hết mới biết.
    khai = request.headers.get("content-length", "")
    if khai.isdigit() and int(khai) > MAX_BYTES:
        raise _qua_lon(int(khai))
    khuc: list[bytes] = []
    n = 0
    async for k in request.stream():
        n += len(k)
        if n > MAX_BYTES:
            raise _qua_lon(n)
        khuc.append(k)
    return JSONResponse(await run_in_threadpool(classify_bytes, b"".join(khuc),
                                                filename))


@app.get("/api/classify/schema")
def schema() -> FileResponse:
    return FileResponse(SCHEMA, media_type="application/schema+json")


def main() -> None:
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8812)
    args = ap.parse_args()
    print(f"http://127.0.0.1:{args.port}/api/classify")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
