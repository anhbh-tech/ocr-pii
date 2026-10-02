"""Web đối chiếu kết quả ADE với trang gốc.

VÌ SAO KHÔNG BAO GIỜ NGHE 0.0.0.0
─────────────────────────────────
Server này phục vụ ảnh CCCD và bản chép của chúng. `host="0.0.0.0"` là mở kho
hồ sơ khách hàng ra cho cả mạng LAN — quán cà phê, văn phòng chung, mạng
khách sạn. Script TỪ CHỐI giá trị đó, không phải cảnh báo rồi vẫn chạy.

BA MỨC PHƠI BÀY, CHỌN ĐÚNG MỘT
──────────────────────────────
    127.0.0.1        chỉ máy này                      ← mặc định
    100.x.y.z        chỉ thiết bị trong tailnet       ← `--tailnet`
    0.0.0.0          cả LAN + bất kỳ ai cùng mạng     ← BỊ CHẶN

`--tailnet` tự tìm địa chỉ Tailscale của máy và nghe ĐÚNG địa chỉ đó. Khác
biệt với 0.0.0.0 là thật, không phải hình thức: gói tin tới cổng này phải đi
qua đường hầm WireGuard đã xác thực bằng khoá thiết bị, nên máy lạ cùng Wi-Fi
không chạm tới được. Mạng LAN không nhìn thấy cổng.

VÌ SAO `doc_id` PHẢI KHỚP REGEX
───────────────────────────────
`doc_id` đến từ URL, và `store / doc_id` với `doc_id = "../.."` đọc được cả
đĩa. Băm SHA-1 rút gọn luôn là 16 ký tự hex, nên ràng đúng khuôn đó vừa chặt
vừa không loại nhầm dữ liệu hợp lệ.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fastapi import FastAPI, HTTPException, Query                  # noqa: E402
from fastapi.responses import (                                     # noqa: E402
    FileResponse, HTMLResponse, Response, StreamingResponse,
)
from pydantic import BaseModel                                      # noqa: E402

from ocr_lab.ade_store import (                                     # noqa: E402
    DEFAULT_STORE, box_to_pixels, doc_id_for,
)

WEB = ROOT / "web"
STORE = DEFAULT_STORE

#: Thư mục hồ sơ GỐC trên đĩa. File manager duyệt cái này, không duyệt kho —
#: kho chỉ chứa tài liệu ĐÃ chạy, mà điểm của file manager là thấy được cả
#: những tệp chưa chạy bao giờ.
SOURCE_ROOT = Path.home() / ".private" / "refiny_data"

#: Đuôi tệp đọc được TRỰC TIẾP bằng engine OCR.
_OCR_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp",
                 ".bmp", ".gif", ".heic", ".heif"}

#: Tệp Office: KHÔNG đọc thẳng được, nhưng chứa ảnh nhúng bên trong.
#:
#: Đo trên kho này: 148 docx + 22 xlsx. PyMuPDF mở được và trả lớp text đúng,
#: nhưng `page.get_images()` trả về 0 trên MỌI trang — ảnh nhúng nằm trong
#: `word/media/` của kho ZIP và không bao giờ vào danh sách tài nguyên trang.
#: Một khảo sát trước đây trên corpus thật: 147 docx báo 0 ảnh nhưng thực
#: chứa 262 ảnh, 106 trong số đó có chữ, gồm cả ảnh chụp CCCD.
#:
#: Nên chúng hiện trong danh sách kèm nhãn riêng, không im lặng biến mất.
_OFFICE_SUFFIXES = {".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt"}

#: Mọi đuôi còn lại vẫn HIỆN trong danh sách. Ẩn tệp đi thì người dùng không
#: biết hồ sơ có gì, và không phân biệt được "không có tệp" với "có nhưng
#: công cụ không đọc được".

#: Băm SHA-1 rút gọn: đúng 16 ký tự hex, không hơn không kém.
_DOC_ID = re.compile(r"^[0-9a-f]{16}$")

#: Công cụ đang phát triển: mã đổi liên tục, và một bản JS cũ trong cache
#: gây lỗi "trang trắng" mà người dùng không có cách nào tự chẩn đoán —
#: server thì đúng, tệp trên đĩa thì đúng, chỉ trình duyệt giữ bản cũ.
_NO_CACHE = {"Cache-Control": "no-store, must-revalidate", "Pragma": "no-cache"}


app = FastAPI(title="ocr-lab · đối chiếu ADE")


def _doc_dir(doc_id: str) -> Path:
    """Thư mục của một tài liệu, sau khi đã kiểm khuôn `doc_id`."""
    if not _DOC_ID.match(doc_id):
        # 404 chứ không phải 400: không tiết lộ rằng khuôn id là thứ bị từ chối.
        raise HTTPException(404, "không có tài liệu này")
    d = STORE / doc_id
    # Đủ điều kiện khi có BẤT KỲ engine nào đã chạy, không riêng ADE Verity.
    # Đòi `parse.json` thì tài liệu chạy bằng Vision (cục bộ, miễn phí) mở ra
    # 404 — mà đó chính là đường chạy mặc định của file manager.
    if not any((d / f).is_file()
               for f in ("parse.json", "parse_pro.json", "vision.json")):
        raise HTTPException(404, "không có tài liệu này")
    return d


#: Thứ tự hiện section. Không xếp theo bảng chữ cái mà theo MỨC RỦI RO đọc
#: sai: tệp scan phải OCR nên sai nhiều nhất, xếp đầu để người soát gặp
#: trước; tệp digital có sẵn lớp chữ nên gần như không sai, xếp cuối.
_THU_TU_SECTION = ["pdf_scan", "anh", "pdf_digital", "docx", "xlsx", "khac"]

_NHAN_SECTION = {
    "pdf_scan": "PDF scan",
    "anh": "Ảnh rời",
    "pdf_digital": "PDF digital",
    "docx": "Word (docx)",
    "xlsx": "Excel (xlsx)",
    "khac": "Khác",
}


def _section_cua(sub: Path, src: Path, meta: dict) -> str:
    """Loại tài liệu, đọc từ kho chứ không phân loại lại.

    Phân loại lại mỗi lần gọi API nghĩa là mở và đếm chữ trong hàng trăm PDF
    cho MỖI lần tải trang — cây hồ sơ sẽ mất vài giây để hiện. Lô chạy đã
    xác định loại rồi, nên chỉ cần ghi nhớ.

    Với tài liệu chạy trước khi có trường này, suy ra từ hai dấu hiệu rẻ:
    đuôi tệp, và engine đã dùng (Pro dành cho scan/ảnh, Verity cho digital).
    Suy sai một vài tài liệu cũ chấp nhận được — chúng hiện sai nhóm chứ
    không biến mất, và chạy lại là đúng.
    """
    if meta.get("section"):
        return str(meta["section"])

    suf = src.suffix.lower()
    if suf in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}:
        return "anh"
    if suf == ".docx":
        return "docx"
    if suf == ".xlsx":
        return "xlsx"
    if suf != ".pdf":
        return "khac"
    # `parse_pro.json` có mặt nghĩa là lô đã định tuyến tệp này sang Pro, và
    # quy tắc định tuyến chỉ gửi scan/ảnh cho Pro.
    return "pdf_scan" if (sub / "parse_pro.json").is_file() else "pdf_digital"


@app.get("/api/tree")
def tree() -> dict:
    """Cây hồ sơ → tài liệu, dựng từ `source` của từng mục trong kho.

    Nhóm theo hai cấp thư mục đầu của đường dẫn gốc: đó là cách hồ sơ được tổ
    chức thật (`Phòng IP/1. Đăng ký bảo hộ.../901.US. ZORBLAX...`).
    """
    if not STORE.exists():
        return {"store": str(STORE), "matters": []}

    matters: dict[str, list[dict]] = {}
    for sub in sorted(STORE.iterdir()):
        # Siêu dữ liệu nằm ở một trong ba chỗ, tuỳ engine đã chạy:
        #   meta.json      — ADE Verity (và xlsx đọc cục bộ)
        #   meta_pro.json  — ADE Pro, chạy cho pdf_scan và ảnh rời
        #   vision.json    — Apple Vision, chạy cục bộ
        # Lọc theo `meta.json` thôi thì 137 tài liệu chạy bằng Pro — tức TOÀN
        # BỘ pdf_scan và ảnh rời — không bao giờ hiện trong cây: người dùng
        # trả tiền chạy xong rồi không tìm thấy chúng ở đâu.
        meta_f = sub / "meta.json"
        pro_f = sub / "meta_pro.json"
        vis_f = sub / "vision.json"
        if meta_f.is_file():
            meta = json.loads(meta_f.read_text("utf-8"))
        elif pro_f.is_file():
            meta = json.loads(pro_f.read_text("utf-8"))
        elif vis_f.is_file():
            v = json.loads(vis_f.read_text("utf-8"))
            meta = {"source": v.get("source", ""), "model": v.get("engine", ""),
                    "credits": 0.0,
                    "pages": [{"page": pg.get("page"), "width": pg.get("width"),
                               "height": pg.get("height")}
                              for pg in v.get("pages", [])]}
        else:
            continue
        src = Path(meta.get("source", ""))
        # Tên hồ sơ = thư mục cấp 3 nếu có (…/Phòng IP/1. Đăng ký…/901.US…),
        # ngược lại lùi về cấp gần nhất còn tồn tại.
        parts = src.parts
        matter = parts[2] if len(parts) > 3 else (parts[0] if parts else "(khác)")
        matters.setdefault(matter, []).append({
            "doc_id": sub.name,
            "name": src.name,
            "source": str(src),
            "section": _section_cua(sub, src, meta),
            "pages": len(meta.get("pages") or []),
            "credits": meta.get("credits"),
            "model": meta.get("model"),
            "parsed_at": meta.get("parsed_at"),
        })

    # Gom theo SECTION trước, HỒ SƠ sau. Người dùng hỏi "tệp scan nào chưa
    # đạt" nhiều hơn hỏi "hồ sơ 901 có gì", nên loại tài liệu phải là trục
    # ngoài cùng; trong mỗi loại mới chia tiếp theo hồ sơ.
    sections: dict[str, dict[str, list[dict]]] = {}
    for ten_hs, docs in matters.items():
        for d in docs:
            sections.setdefault(d["section"], {}).setdefault(ten_hs, []).append(d)

    return {
        "store": str(STORE),
        # Giữ nguyên `matters` để màn hình cũ không gãy khi web chưa nạp lại.
        "matters": [{"name": k, "docs": sorted(v, key=lambda d: d["name"])}
                    for k, v in sorted(matters.items())],
        "sections": [
            {
                "key": k,
                "label": _NHAN_SECTION.get(k, k),
                "n_docs": sum(len(v) for v in hs.values()),
                "matters": [{"name": n, "docs": sorted(v, key=lambda d: d["name"])}
                            for n, v in sorted(hs.items())],
            }
            for k in _THU_TU_SECTION if k in sections
            for hs in [sections[k]]
        ],
    }


@app.get("/api/browse")
def browse(path: str = Query("", max_length=400)) -> dict:
    """Duyệt thư mục hồ sơ THẬT trên đĩa, kèm trạng thái OCR của từng tệp.

    Khác `/api/tree` ở điểm quyết định: cây kia dựng từ KHO nên chỉ thấy tài
    liệu đã chạy. Người dùng cần thấy cả tệp chưa chạy — đó là lý do có màn
    hình này.

    `path` là đường dẫn TƯƠNG ĐỐI so với `SOURCE_ROOT`. Mọi đường dẫn được
    resolve rồi kiểm phải nằm trong gốc: `..%2F..%2Fetc` mà lọt là đọc được
    cả đĩa.
    """
    target = (SOURCE_ROOT / path).resolve() if path else SOURCE_ROOT
    try:
        target.relative_to(SOURCE_ROOT.resolve())
    except ValueError:
        raise HTTPException(404, "không có thư mục này")
    if not target.is_dir():
        raise HTTPException(404, "không có thư mục này")

    dirs, files = [], []
    for p in sorted(target.iterdir()):
        if p.name.startswith("."):
            continue
        rel = str(p.relative_to(SOURCE_ROOT))
        if p.is_dir():
            # Đếm nông (chỉ cấp 1) — đếm sâu trên thư mục 300 tệp làm treo
            # mỗi lần mở một cấp, và con số đó cũng không ai dùng.
            dirs.append({"name": p.name, "path": rel,
                         "n": sum(1 for _ in p.iterdir())})
            continue

        suf = p.suffix.lower()
        can_ocr = suf in _OCR_SUFFIXES
        kind = ("ocr" if can_ocr else
                "office" if suf in _OFFICE_SUFFIXES else "other")
        # Cùng phép băm mà pipeline dùng, trên cùng dạng chuỗi tương đối —
        # lệch một chút là file manager báo "chưa chạy" cho tệp đã chạy.
        did = doc_id_for(rel) if can_ocr else ""
        d = STORE / did if did else None
        files.append({
            "name": p.name, "path": rel, "size": p.stat().st_size,
            "can_ocr": can_ocr, "kind": kind, "doc_id": did,
            # Engine nào đã chạy cho tệp này. Hiện thẳng trạng thái thay vì
            # chỉ "đã/chưa": người dùng cần biết còn thiếu engine nào.
            "verity": bool(d and (d / "parse.json").is_file()),
            "pro": bool(d and (d / "parse_pro.json").is_file()),
            "vision": bool(d and (d / "vision.json").is_file()),
        })

    parent = str(Path(path).parent) if path and Path(path).parent != Path(".") else ""
    return {"path": path, "parent": parent, "at_root": not path,
            "dirs": dirs, "files": files}


@app.get("/api/preview")
def preview(path: str = Query(..., max_length=400)) -> dict:
    """Xem trước một tệp KHÔNG phải ảnh: docx, xlsx, txt, md, html.

    Tách khỏi `/api/run` vì đây không phải OCR: không gọi engine, không
    tốn tiền, không ghi gì vào kho. Chỉ đọc và dựng HTML để xem.
    """
    from ocr_lab.preview import xem_truoc

    f = (SOURCE_ROOT / path).resolve()
    try:
        f.relative_to(SOURCE_ROOT.resolve())
    except ValueError:
        raise HTTPException(404, "không có tệp này")
    if not f.is_file():
        raise HTTPException(404, "không có tệp này")
    return xem_truoc(f)


@app.get("/api/peek")
def peek(path: str = Query(..., max_length=400)) -> dict:
    """Nhìn nhanh vào một tệp: vài dòng đầu + số trang. KHÔNG dựng cả tệp.

    Khác `/api/extract` ở chi phí: extract đọc toàn bộ (một PDF 34 trang mất
    vài giây), còn cái này chỉ chạm trang đầu. Nó chạy mỗi khi người dùng
    di chuyển lựa chọn trong danh sách, nên phải rẻ — nếu không việc duyệt
    tệp sẽ giật.
    """
    f = (SOURCE_ROOT / path).resolve()
    try:
        f.relative_to(SOURCE_ROOT.resolve())
    except ValueError:
        raise HTTPException(404, "không có tệp này")
    if not f.is_file():
        raise HTTPException(404, "không có tệp này")

    suf = f.suffix.lower()
    out = {"name": f.name, "size": f.stat().st_size, "suffix": suf,
           "so_trang": 1, "text": "", "co_anh": False, "can_ocr": False}

    if suf == ".pdf":
        import pymupdf
        with pymupdf.open(f) as doc:
            out["so_trang"] = doc.page_count
            if doc.page_count:
                # Chỉ trang đầu: đủ để nhận ra tệp, và không phải đợi.
                out["text"] = doc[0].get_text().strip()[:600]
        out["co_anh"] = True
        # Không có chữ ở trang đầu ⇒ gần như chắc chắn là bản scan.
        out["can_ocr"] = len(out["text"]) < 60
    elif suf in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp",
                 ".tif", ".tiff", ".heic", ".heif"}:
        out["co_anh"] = True
        out["can_ocr"] = True
    else:
        try:
            from ocr_lab.extract import trich_xuat
            kq = trich_xuat(f)
            out["text"] = kq["markdown"][:600]
            out["so_trang"] = kq["meta"].get("so_trang", 1)
        except Exception:   # noqa: BLE001 — xem trước hỏng không được chặn việc duyệt
            out["text"] = ""
    return out


@app.get("/api/peek/thumb")
def peek_thumb(path: str = Query(..., max_length=400)) -> Response:
    """Ảnh thu nhỏ trang đầu — dựng tại chỗ, KHÔNG ghi vào kho.

    Không dùng `render_pages`: hàm đó dựng ảnh 200 DPI cho MỌI trang và lưu
    lại, tức là xem trước một tệp 34 trang sẽ tạo 34 tệp ảnh trong kho cho
    một thao tác mà người dùng có thể chỉ lướt qua.
    """
    f = (SOURCE_ROOT / path).resolve()
    try:
        f.relative_to(SOURCE_ROOT.resolve())
    except ValueError:
        raise HTTPException(404, "không có tệp này")
    if not f.is_file():
        raise HTTPException(404, "không có tệp này")

    suf = f.suffix.lower()
    try:
        if suf == ".pdf":
            import pymupdf
            with pymupdf.open(f) as doc:
                if not doc.page_count:
                    raise HTTPException(404, "PDF rỗng")
                # 72 DPI: vừa đủ cho khung ~200px, dựng trong vài chục ms.
                pix = doc[0].get_pixmap(dpi=72)
                return Response(pix.tobytes("jpeg", jpg_quality=75),
                                media_type="image/jpeg", headers=_NO_CACHE)
        from PIL import Image
        im = Image.open(f)
        im.thumbnail((480, 480))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=75)
        return Response(buf.getvalue(), media_type="image/jpeg",
                        headers=_NO_CACHE)
    except HTTPException:
        raise
    except Exception as e:      # noqa: BLE001
        raise HTTPException(415, f"không dựng được ảnh: {type(e).__name__}")


@app.get("/api/batch/preview")
def batch_preview(path: str = Query("", max_length=400),
                  engine: str = Query("vision", max_length=16),
                  de_quy: bool = Query(True)) -> dict:
    """Đếm việc và TIỀN trước khi chạy hàng loạt — không gọi engine nào.

    Bắt buộc phải có bước này. Chạy cả thư mục bằng ADE Pro là con số hàng
    chục đô la, và người dùng không có cách nào lấy lại sau khi bấm. Đưa ra
    con số TRƯỚC, rồi mới hỏi.

    Không đếm tệp đã chạy engine đó: chúng sẽ bị bỏ qua lúc chạy, nên tính
    vào dự toán là nói quá cả thời gian lẫn tiền.
    """
    target = (SOURCE_ROOT / path).resolve() if path else SOURCE_ROOT
    try:
        target.relative_to(SOURCE_ROOT.resolve())
    except ValueError:
        raise HTTPException(404, "không có thư mục này")

    viec = _liet_ke_viec(target, engine, de_quy)
    tong_trang = sum(v["so_trang"] for v in viec)
    gia = {"vision": 0.0, "verity": 0.003, "pro": 0.009}[engine]
    return {
        "so_tep": len(viec),
        "so_trang": tong_trang,
        "chi_phi_usd": round(tong_trang * gia, 3),
        "mien_phi": gia == 0.0,
        # Hiện vài tên đầu để người dùng đối chiếu nhanh là đúng chỗ không.
        "vi_du": [v["name"] for v in viec[:8]],
    }


#: Trần giải nén: tổng dung lượng và số tệp. Một kho zip nhỏ có thể bung ra
#: hàng GB ("zip bomb") và làm đầy đĩa trước khi ai kịp nhận ra.
ZIP_MAX_BYTES = 2 * 1024 ** 3
ZIP_MAX_FILES = 5000


def _giai_nen_zip(z: Path) -> Path:
    """Giải nén vào thư mục cạnh tệp zip, trả về thư mục đó.

    Giải nén NGAY TRONG cây hồ sơ chứ không vào /tmp: mọi thứ khác
    (`doc_id`, đường dẫn tương đối, kiểm chặn thoát thư mục) đều tính theo
    `SOURCE_ROOT`. Một thư mục ngoài cây sẽ không có `doc_id` ổn định và
    kết quả OCR sẽ mất liên kết ngay lần chạy sau.

    Ba lớp chặn, thiếu lớp nào cũng nguy hiểm:
      * tên tệp chứa `..` hoặc đường dẫn tuyệt đối ⇒ ghi ra ngoài thư mục
        đích (Zip Slip);
      * tổng dung lượng giải nén ⇒ zip bomb làm đầy đĩa;
      * số tệp ⇒ hàng trăm nghìn tệp rỗng làm treo phần duyệt thư mục.
    """
    import zipfile

    dich = z.with_suffix("")
    if dich.exists() and any(dich.iterdir()):
        return dich                      # đã giải nén lần trước
    dich.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(z) as zf:
        muc = zf.infolist()
        if len(muc) > ZIP_MAX_FILES:
            raise HTTPException(400, f"zip có {len(muc)} tệp, quá {ZIP_MAX_FILES}")
        tong = sum(m.file_size for m in muc)
        if tong > ZIP_MAX_BYTES:
            raise HTTPException(400, f"zip bung ra {tong / 1024**3:.1f} GB, quá lớn")

        for m in muc:
            if m.is_dir():
                continue
            # Chỉ giữ TÊN tệp và các cấp thư mục hợp lệ; loại mọi thành phần
            # `..`, ổ đĩa, và dấu gạch đầu — đó là toàn bộ cách Zip Slip hoạt động.
            phan = [c for c in Path(m.filename).parts
                    if c not in ("..", "/", "\\") and ":" not in c]
            if not phan:
                continue
            ra = dich.joinpath(*phan)
            try:
                ra.resolve().relative_to(dich.resolve())
            except ValueError:
                continue                 # vẫn thoát ra được ⇒ bỏ qua tệp này
            ra.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(m) as src_f, ra.open("wb") as out_f:
                shutil.copyfileobj(src_f, out_f, 1024 * 64)
    return dich


def _so_trang_nhanh(f: Path) -> int:
    """Đếm trang KHÔNG dựng ảnh — chỉ để dự toán.

    Dựng ảnh cho cả thư mục chỉ để đếm thì mất hàng phút, và người dùng
    đang chờ một con số trước khi quyết định.
    """
    if f.suffix.lower() != ".pdf":
        return 1
    try:
        import pymupdf
        with pymupdf.open(f) as doc:
            return doc.page_count
    except Exception:       # noqa: BLE001 — tệp hỏng vẫn phải đếm là 1
        return 1


def _liet_ke_viec(target: Path, engine: str, de_quy: bool) -> list[dict]:
    """Các tệp CẦN chạy engine này, bỏ qua tệp đã có kết quả."""
    da_co = {"vision": "vision.json", "pro": "parse_pro.json",
             "verity": "parse.json"}[engine]

    if target.is_file() and target.suffix.lower() == ".zip":
        target = _giai_nen_zip(target)

    nguon = target.rglob("*") if de_quy else target.iterdir()
    viec = []
    for f in sorted(nguon):
        if not f.is_file() or f.name.startswith("."):
            continue
        if f.suffix.lower() not in _OCR_SUFFIXES:
            continue
        rel = str(f.relative_to(SOURCE_ROOT))
        if (STORE / doc_id_for(rel) / da_co).is_file():
            continue
        viec.append({"path": rel, "name": f.name,
                     "so_trang": _so_trang_nhanh(f)})
    return viec


@app.get("/api/batch/run")
def batch_run(path: str = Query("", max_length=400),
              engine: str = Query("vision", max_length=16),
              de_quy: bool = Query(True)) -> StreamingResponse:
    """Chạy cả thư mục, một tệp một, có tiến độ thật.

    TUẦN TỰ chứ không song song. Ba lý do, lý do nào cũng đủ:
      * ADE tính tiền theo trang — chạy song song mà lỗi giữa chừng thì
        không biết đã trả tiền cho những gì;
      * Apple Vision đã dùng hết lõi cho mỗi trang, chạy song song chỉ làm
        chúng tranh nhau;
      * tiến độ tuần tự nói đúng sự thật; tiến độ song song là một con số
        trung bình không ứng với việc nào cả.

    Một tệp lỗi KHÔNG dừng cả lượt: báo lỗi tệp đó rồi đi tiếp. Dừng hẳn
    nghĩa là một tệp hỏng chặn mất 200 tệp lành.
    """
    target = (SOURCE_ROOT / path).resolve() if path else SOURCE_ROOT
    try:
        target.relative_to(SOURCE_ROOT.resolve())
    except ValueError:
        raise HTTPException(404, "không có thư mục này")
    if engine not in ("vision", "verity", "pro"):
        raise HTTPException(400, "engine không hợp lệ")
    if target.is_file() and target.suffix.lower() == ".zip":
        target = _giai_nen_zip(target)

    def sse(ev: str, **data) -> str:
        return f"event: {ev}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def stream():
        import time
        viec = _liet_ke_viec(target, engine, de_quy)
        t0 = time.perf_counter()
        yield sse("batch_start", so_tep=len(viec),
                  so_trang=sum(v["so_trang"] for v in viec))

        xong, loi = 0, 0
        for i, v in enumerate(viec, start=1):
            yield sse("file_start", i=i, n=len(viec), name=v["name"],
                      pct=round((i - 1) / max(1, len(viec)) * 100))
            try:
                # Dùng lại ĐÚNG đường chạy của một tệp: cùng phép chặn trùng,
                # cùng cách lưu, cùng variant. Viết đường thứ hai ở đây là
                # cách chắc chắn để hai đường lệch nhau sau vài lần sửa.
                for _ in _chay_mot_tep(SOURCE_ROOT / v["path"], v["path"], engine):
                    pass
                xong += 1
            except Exception as e:      # noqa: BLE001 — một tệp hỏng không được dừng cả lượt
                loi += 1
                yield sse("file_error", name=v["name"], msg=str(e)[:200])

        yield sse("batch_done", xong=xong, loi=loi,
                  seconds=round(time.perf_counter() - t0, 2))

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers=_NO_CACHE)


@app.get("/api/extract")
def extract_local(path: str = Query(..., max_length=400)) -> dict:
    """Trích xuất CÓ NEO VỊ TRÍ, cục bộ, miễn phí — engine thứ tư.

    Khác `/api/preview` ở chỗ quyết định: preview dựng HTML để NGƯỜI đọc,
    còn cái này trả về đúng khuôn ADE (`markdown` + `structure` + `grounding`)
    để dùng lại toàn bộ khung đối chiếu — tab Markdown/JSON, danh sách chunk,
    tô sáng theo `range`.

    Không ghi vào kho: đây là đọc thẳng từ tệp gốc, chạy lại lúc nào cũng ra
    kết quả ấy. Ghi vào kho sẽ làm nhoè ranh giới giữa "đã chạy engine" và
    "đọc được sẵn".
    """
    from ocr_lab.extract import trich_xuat

    f = (SOURCE_ROOT / path).resolve()
    try:
        f.relative_to(SOURCE_ROOT.resolve())
    except ValueError:
        raise HTTPException(404, "không có tệp này")
    if not f.is_file():
        raise HTTPException(404, "không có tệp này")
    try:
        kq = trich_xuat(f)
    except ValueError as e:
        raise HTTPException(415, str(e))
    kq["meta"]["source"] = path
    kq["meta"]["name"] = f.name
    return kq


@app.get("/api/raw")
def raw_file(path: str = Query(..., max_length=400)) -> FileResponse:
    """Trả về TỆP GỐC để trình duyệt tự dựng (PDF qua pdf.js, ảnh trực tiếp).

    Cần vì trình xem phía web phóng to/thu nhỏ trên chính tệp gốc, không
    phải trên ảnh trang đã render sẵn trong kho — kho chỉ có tệp đã chạy OCR.
    """
    f = (SOURCE_ROOT / path).resolve()
    try:
        f.relative_to(SOURCE_ROOT.resolve())
    except ValueError:
        raise HTTPException(404, "không có tệp này")
    if not f.is_file():
        raise HTTPException(404, "không có tệp này")
    return FileResponse(f, headers=_NO_CACHE)


def _sse(ev: str, **data) -> str:
    return f"event: {ev}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _chay_mot_tep(src: Path, rel_path: str, engine: str):
    """Chạy MỘT tệp, sinh ra từng sự kiện SSE.

    Là hàm module chứ không phải hàm lồng trong `/api/run`, vì cả chạy một
    tệp lẫn chạy hàng loạt phải đi qua ĐÚNG đường này — cùng phép chặn
    trùng, cùng cách lưu, cùng variant. Hai đường song song sẽ lệch nhau
    sau vài lần sửa, và cái lệch đó tốn tiền thật.
    """
    import time
    # Đường dẫn tương đối phải tính từ SOURCE_ROOT CHƯA resolve.
    # `doc_id` là băm của chuỗi này, và `resolve()` bung symlink của
    # `.private` thành đường thật ⇒ chuỗi khác ⇒ băm khác ⇒ tạo một thư
    # mục tài liệu THỨ HAI cho cùng một tệp, kho im lặng nhân đôi.
    rel = rel_path
    did = doc_id_for(rel)
    d = STORE / did
    t0 = time.perf_counter()

    # Đã có kết quả của đúng engine này ⇒ KHÔNG gọi lại.
    #
    # ADE tính tiền mỗi lần gọi, nên một cú bấm nhầm trên tệp đã chạy là
    # mất tiền lần hai để lấy về thứ đang nằm sẵn trên đĩa. Chặn ở SERVER
    # chứ không chỉ ở giao diện: giao diện có thể lỡ nhịp (danh sách chưa
    # kịp nạp lại), còn tệp trên đĩa thì không nói dối.
    _da_co = {"vision": "vision.json", "pro": "parse_pro.json",
              "verity": "parse.json"}[engine]
    if (d / _da_co).is_file():
        yield _sse("done", doc_id=did, seconds=0.0, da_co=True)
        return
    try:
        yield _sse("start", doc_id=did, name=src.name, engine=engine)

        # Ảnh trang: dùng lại nếu đã render, vì cả ba engine phải đọc
        # CÙNG một ảnh — render lại bằng tham số khác thì chênh lệch
        # giữa các engine lẫn cả chênh lệch do ảnh.
        pages_dir = d / "pages"
        if not (pages_dir.is_dir() and any(pages_dir.glob("p*.*"))):
            yield _sse("step", msg="dựng ảnh trang", pct=10)
            from ocr_lab.ade_store import render_pages
            render_pages(src, pages_dir)

        imgs = sorted(
            [q for q in pages_dir.glob("p*.*")
             if q.suffix.lower() in (".png", ".jpg", ".jpeg")],
            key=lambda q: int("".join(c for c in q.stem if c.isdigit()) or 0))

        if engine == "vision":
            sys.path.insert(0, str(Path.home() / "ocr-lab-gpu" / "src"))
            from ocr_gpu.engines.vision import VisionEngine
            eng = VisionEngine()
            out = []
            for i, im in enumerate(imgs, 1):
                yield _sse("step", msg=f"đọc trang {i}/{len(imgs)}",
                          pct=10 + int(80 * i / max(len(imgs), 1)))
                pg = eng.read_page(im)
                out.append({
                    "page": i, "width": pg.width, "height": pg.height,
                    "text": pg.text,
                    "lines": [{"text": s.text, "confidence": s.confidence,
                               "bbox_topleft": s.bbox_topleft}
                              for s in pg.lines],
                })
            d.mkdir(parents=True, exist_ok=True)
            f = d / "vision.json"
            f.write_text(json.dumps(
                {"engine": "apple-vision", "doc_id": did, "source": rel,
                 "seconds": round(time.perf_counter() - t0, 2),
                 "pages": out}, ensure_ascii=False, indent=2),
                encoding="utf-8")
            f.chmod(0o600)

            # Ghi `meta.json` nếu chưa có: cây hồ sơ và mọi thứ dựng từ
            # nó đều đọc tệp này. Thiếu nó thì tài liệu chạy xong nằm
            # trong kho mà không nơi nào hiện ra.
            #
            # KHÔNG ghi đè khi đã có: `meta.json` của ADE mang `credits`
            # và `model` đã trả tiền để có.
            mf = d / "meta.json"
            if not mf.is_file():
                mf.write_text(json.dumps({
                    "source": rel, "model": "apple-vision", "credits": 0.0,
                    "pages": [{"page": pg["page"], "width": pg["width"],
                               "height": pg["height"]} for pg in out],
                    "parsed_at": datetime.now(timezone.utc).isoformat(),
                }, ensure_ascii=False, indent=2), encoding="utf-8")
                mf.chmod(0o600)
        else:
            model = "dpt-3-pro" if engine == "pro" else "dpt-3-verity"
            yield _sse("step", msg=f"gửi tới LandingAI ({model})", pct=30)
            from ocr_lab.ade_store import save_result
            from ocr_lab.engines import load_dotenv
            from ocr_lab.engines.ade import AdeEngine
            load_dotenv()
            data = AdeEngine(model=model).parse_document(src)
            yield _sse("step", msg="lưu kết quả", pct=90)
            meta_api = data.get("metadata") or {}
            cr = ((meta_api.get("billing") or {}).get("total_credits")) or 0.0
            save_result(STORE, did, data, source=rel, model=model,
                        credits=cr,
                        pages=[{"page": i + 1} for i in range(len(imgs))],
                        variant="pro" if engine == "pro" else "")

        yield _sse("done", doc_id=did,
                  seconds=round(time.perf_counter() - t0, 2))
    except Exception as exc:
        # Lỗi phải tới được trình duyệt: thanh tiến trình đứng im mãi
        # là thứ khó chẩn đoán nhất với người dùng.
        yield _sse("error", msg=f"{type(exc).__name__}: {str(exc)[:160]}")



@app.get("/api/run")
def run_ocr(path: str = Query(..., max_length=400),
            engine: str = Query("vision")) -> StreamingResponse:
    """Chạy OCR cho MỘT tệp, đẩy tiến độ về trình duyệt theo thời gian thực.

    VÌ SAO SERVER-SENT EVENTS
    ─────────────────────────
    OCR một hợp đồng 8 trang mất vài giây tới vài chục giây. Một request
    thường sẽ im lặng suốt thời gian đó rồi trả kết quả — và người dùng
    không phân biệt được "đang chạy" với "đã treo", nên họ bấm lại, và lần
    bấm thứ hai tốn thêm tiền thật nếu là ADE.

    SSE đẩy từng bước (`render 3/8`, `gọi engine`, `xong`) nên thanh tiến
    trình phản ánh việc THẬT chứ không phải hoạt hình chạy cho có.

    VÌ SAO MẶC ĐỊNH LÀ VISION
    ─────────────────────────
    Vision chạy cục bộ và miễn phí. Bấm nhầm vào một tệp thì không mất gì.
    ADE phải chọn có ý thức, và mỗi lần chọn là tiền thật.
    """
    src = (SOURCE_ROOT / path).resolve()
    try:
        src.relative_to(SOURCE_ROOT.resolve())
    except ValueError:
        raise HTTPException(404, "không có tệp này")
    if not src.is_file():
        raise HTTPException(404, "không có tệp này")
    if engine not in ("vision", "verity", "pro"):
        raise HTTPException(400, "engine không hợp lệ")

    rel = str((SOURCE_ROOT / path).relative_to(SOURCE_ROOT))
    return StreamingResponse(_chay_mot_tep(src, rel, engine),
                             media_type="text/event-stream", headers=_NO_CACHE)


@app.get("/api/doc/{doc_id}")
def doc(doc_id: str) -> dict:
    d = _doc_dir(doc_id)
    # Pro lưu dưới tên riêng (`parse_pro.json`/`meta_pro.json`) để chạy Pro
    # không đè lên kết quả Verity của cùng tài liệu. Đọc cứng tên không hậu
    # tố thì mọi pdf_scan và ảnh rời — tức tất cả những gì chạy bằng Pro —
    # mở ra lỗi 500.
    pf = d / "parse.json"
    if not pf.is_file() and (d / "parse_pro.json").is_file():
        pf = d / "parse_pro.json"
    mf = d / "meta.json"
    if not mf.is_file() and (d / "meta_pro.json").is_file():
        mf = d / "meta_pro.json"
    out = {
        "doc_id": doc_id,
        "meta": json.loads(mf.read_text("utf-8")) if mf.is_file() else {},
        # `parse` rỗng khi tài liệu mới chỉ chạy Vision. Đọc cứng tệp này thì
        # mở tài liệu chạy cục bộ ra lỗi 500 — mà đó là đường mặc định của
        # file manager, nên gần như mọi tài liệu mới đều dính.
        "parse": (json.loads(pf.read_text("utf-8")) if pf.is_file()
                  else {"markdown": "", "structure": None}),
    }
    # docx/xlsx KHÔNG có ảnh trang: chúng không phải tài liệu phân trang,
    # `render_pages` không dựng được gì, nên khung trái đứng trống và
    # `/page/1` trả 404. Một tài liệu mở ra trắng trơn trông y hệt tài liệu
    # hỏng — người dùng không có cách nào phân biệt.
    #
    # Thay ảnh trang bằng HTML dựng từ CHÍNH tệp gốc. Dựng tại chỗ chứ
    # không lưu: bản dựng là dẫn xuất thuần tuý từ tệp gốc, lưu thêm một
    # bản chỉ nhân đôi hồ sơ khách hàng trên đĩa.
    src_rel = (out["meta"] or {}).get("source") or ""
    if src_rel and Path(src_rel).suffix.lower() in {".docx", ".xlsx"}:
        goc = SOURCE_ROOT / src_rel
        if goc.is_file():
            from ocr_lab.preview import xem_truoc
            out["preview"] = xem_truoc(goc)

    verdicts = d / "verdicts.json"
    if verdicts.is_file():
        out["verdicts"] = json.loads(verdicts.read_text("utf-8"))

    # Bản sửa chính tả, nếu đã chạy `make correct-write`.
    #
    # Gửi kèm luôn thay vì để web gọi thêm một lượt: nó luôn được dùng cùng
    # `parse`, và tách ra chỉ thêm một trạng thái "đã tải parse chưa tải
    # corrected" mà giao diện phải xử lý.
    #
    # `parse.json` KHÔNG bị đụng tới — bản sửa nằm ở tệp riêng vì mọi
    # `grounding.range` neo vào `markdown` bằng offset ký tự.
    corrected = d / "corrected.json"
    if corrected.is_file():
        out["corrected"] = json.loads(corrected.read_text("utf-8"))

    # Bản chép của các engine khác, gửi kèm để đổi engine không phải tải
    # lại — đổi qua đổi lại chính là cách so sánh, nên nó phải tức thì.
    vision = d / "vision.json"
    if vision.is_file():
        out["vision"] = json.loads(vision.read_text("utf-8"))

    # Chữ đọc được từ ảnh NHÚNG trong trang digital. Giữ riêng, không trộn
    # vào `markdown`: lớp text là chữ đọc thẳng từ PDF (chắc chắn đúng), còn
    # đây là OCR đoán (có thể sai) — trộn thì người soát mất khả năng phân
    # biệt hai mức tin cậy đó.
    imt = d / "image_text.json"
    if imt.is_file():
        out["image_text"] = json.loads(imt.read_text("utf-8"))

    pro = d / "parse_pro.json"
    if pro.is_file():
        out["parse_pro"] = json.loads(pro.read_text("utf-8"))
        meta_pro = d / "meta_pro.json"
        if meta_pro.is_file():
            out["meta_pro"] = json.loads(meta_pro.read_text("utf-8"))
    return out


#: Nguồn quyết định pii-core, nạp một lần (HTTP: đọc bảng hành động một lần).
_NGUON: list = []


def _nguon():
    from ocr_lab.che import PiiCoreThieu, nap_pii_core
    if not _NGUON:
        try:
            _NGUON.append(nap_pii_core())
        except PiiCoreThieu as e:
            # 503 chứ không trả danh sách rỗng: "không có gì phải che" và
            # "không biết phải che gì" trông giống hệt nhau trên màn hình.
            raise HTTPException(503, str(e))
    return _NGUON[0]


def _pdf_pii_core(doc_id: str) -> bool:
    """Có `che.pdf` do pii-core quyết — bản cũ theo bảng pii-lab không tính."""
    from ocr_lab import che
    out = che.DEFAULT_OUT / doc_id
    if not (out / "che.pdf").is_file() or not (out / "che.json").is_file():
        return False
    return "pii_core" in json.loads((out / "che.json").read_text("utf-8"))


@app.get("/api/doc/{doc_id}/che")
def che_vung(doc_id: str) -> dict:
    """Các vùng pii-core bảo che, kèm box ADE Pro và token — KHÔNG kèm chữ gốc.

    Web vẽ chúng lên ảnh trang y như `make che` sẽ nung, để người soát thấy
    trước cái gì bị che và cái gì lọt, rồi mới tải PDF.
    """
    from dataclasses import asdict
    from ocr_lab import che
    d = _doc_dir(doc_id)
    f = d / "parse_pro.json"
    if not f.is_file():
        return {"vung": [], "dem": {}, "ly_do": "chưa có parse ADE Pro — box che lấy từ đó"}
    nguon = _nguon()
    try:
        kq = che.tim_vung(json.loads(f.read_text("utf-8")), nguon, che.anh_trang(d),
                          che.parse_phu(d))
    except che.PiiCoreThieu as e:
        raise HTTPException(503, str(e))
    co_anh = (d / "pages" / "p1.jpg").is_file()
    return {"vung": [asdict(v) for v in kq.vung], "dem": che._dem(kq.vung),
            "pii_core": nguon.nguon, "truong": kq.truong, "khong_dinh_vi": kq.khong_dinh_vi,
            "co_pdf": _pdf_pii_core(doc_id),
            "ly_do": None if co_anh else "không có ảnh trang (docx?) — chưa che được"}


@app.get("/api/doc/{doc_id}/truong")
def truong_vung(doc_id: str) -> dict:
    """MỌI field pii-core thấy trong tài liệu, kể cả KEEP, kèm box và hành động
    — để soát trên trang cái gì bị bí danh hoá / ẩn danh hoá / giữ. Không kèm
    chữ gốc: field KEEP không mang chữ thay (chữ thay của nó là chữ gốc)."""
    from dataclasses import asdict
    from ocr_lab import che
    d = _doc_dir(doc_id)
    f = d / "parse_pro.json"
    if not f.is_file():
        return {"vung": [], "dem": {}, "theo_hang_muc": {},
                "ly_do": "chưa có parse ADE Pro — box lấy từ đó"}
    nguon = _nguon()
    try:
        kq = che.tim_vung(json.loads(f.read_text("utf-8")), nguon, che.anh_trang(d),
                          che.parse_phu(d), giu=True)
    except che.PiiCoreThieu as e:
        raise HTTPException(503, str(e))
    return {"vung": [asdict(v) for v in kq.vung], "dem": kq.dem,
            "theo_hang_muc": kq.dem_hang_muc,
            "pii_core": nguon.nguon, "truong": kq.truong, "khong_dinh_vi": kq.khong_dinh_vi,
            "ly_do": None if (d / "pages" / "p1.jpg").is_file()
            else "không có ảnh trang (docx?) — không vẽ được box"}


@app.get("/api/doc/{doc_id}/che.pdf")
def che_pdf(doc_id: str, lam_moi: bool = False) -> FileResponse:
    """PDF đã che. Chưa có, không do pii-core quyết (hoặc `lam_moi`) thì dựng
    ngay, như `make che`.

    Chỉ trả tệp khi phép chứng minh ĐẠT: một PDF che hỏng mà vẫn tải về được
    là thứ sẽ bị gửi đi.
    """
    from ocr_lab import che
    d = _doc_dir(doc_id)
    out = che.DEFAULT_OUT / doc_id / "che.pdf"
    ket = che.DEFAULT_OUT / doc_id / "che.json"
    if lam_moi or not _pdf_pii_core(doc_id):
        try:
            tom = che.che_tai_lieu(d, _nguon(), che.DEFAULT_OUT)
        except che.PiiCoreThieu as e:
            raise HTTPException(503, str(e))
        if tom.get("bo_qua"):
            raise HTTPException(409, tom["bo_qua"])
    if json.loads(ket.read_text("utf-8")).get("chung_minh") != "đạt":
        raise HTTPException(500, "phép chứng minh không đạt — không phát tệp")
    return FileResponse(out, media_type="application/pdf",
                        filename=f"{doc_id}-che.pdf", headers=_NO_CACHE)


@app.get("/api/doc/{doc_id}/page/{n}")
def page_image(doc_id: str, n: int) -> FileResponse:
    d = _doc_dir(doc_id)
    img = d / "pages" / f"p{n}.jpg"
    if not img.is_file():
        raise HTTPException(404, f"không có trang {n}")
    return FileResponse(img, media_type="image/jpeg")


@app.get("/api/doc/{doc_id}/crop")
def crop(doc_id: str, page: int = 1,
         xmin: float = Query(...), ymin: float = Query(...),
         xmax: float = Query(...), ymax: float = Query(...)) -> Response:
    """Cắt một vùng từ ảnh trang — dùng cho hình, chữ ký, con dấu.

    Toạ độ đi qua ĐÚNG `box_to_pixels` như phía web, nên một phép biến đổi sai
    sẽ sai nhất quán ở cả hai nơi thay vì lệch nhau âm thầm. Tham số đến từ
    URL nên việc kiểm biên ở đây là bắt buộc, không phải phòng xa.
    """
    from PIL import Image

    d = _doc_dir(doc_id)
    img_f = d / "pages" / f"p{page}.jpg"
    if not img_f.is_file():
        raise HTTPException(404, f"không có trang {page}")

    im = Image.open(img_f)
    try:
        box = box_to_pixels({"xmin": xmin, "ymin": ymin,
                             "xmax": xmax, "ymax": ymax},
                            width=im.width, height=im.height)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    # Vùng rộng 0 px làm `crop` trả về ảnh rỗng và trình duyệt hiện ô vỡ. Nới
    # tối thiểu 1 px để một phần tử mảnh (đường kẻ, gạch chân) vẫn nhìn thấy.
    x0, y0, x1, y1 = box
    x1 = max(x1, x0 + 1)
    y1 = max(y1, y0 + 1)

    buf = io.BytesIO()
    im.crop((x0, y0, x1, y1)).save(buf, "JPEG", quality=90)
    return Response(buf.getvalue(), media_type="image/jpeg")


class Verdict(BaseModel):
    chunk_id: str
    verdict: str          # "good" | "bad"
    corrected: str = ""


@app.post("/api/doc/{doc_id}/verdict")
def put_verdict(doc_id: str, v: Verdict) -> dict:
    """Ghi nhận đúng/sai của người soát, kèm bản sửa.

    Ghi vào tệp RIÊNG, không trộn vào `parse.json`: bản chép của model và bản
    sửa của người là hai thứ khác nhau. Trộn lại thì một lần chạy pipeline sau
    sẽ ghi đè mất công người gõ — và công đó đắt hơn tiền API nhiều lần.
    """
    if v.verdict not in ("good", "bad"):
        raise HTTPException(400, "verdict phải là 'good' hoặc 'bad'")

    d = _doc_dir(doc_id)
    f = d / "verdicts.json"
    data = json.loads(f.read_text("utf-8")) if f.is_file() else {}

    data[v.chunk_id] = {
        "verdict": v.verdict,
        "corrected": v.corrected,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    f.chmod(0o600)
    return {"ok": True, "count": len(data)}


#: Thư mục do Vite dựng ra. Có thì phục vụ nó; không thì quay về tệp nguồn.
#:
#: Hai chế độ này tồn tại vì hai tình huống khác nhau:
#:   * `npm run build` rồi chạy server Python  → dùng dist/, một cổng duy nhất
#:   * `npm run dev` + server Python           → Vite (5173) chuyển tiếp /api
#:
#: Quay về tệp nguồn khi chưa dựng là có chủ đích: người vừa clone kho về
#: chạy `serve_review.py` phải thấy trang chạy được, không phải thấy 404 rồi
#: đi tìm xem còn thiếu bước nào.
DIST = WEB / "dist"

_MIME = {
    ".js": "application/javascript", ".mjs": "application/javascript",
    ".css": "text/css", ".map": "application/json",
    ".woff2": "font/woff2", ".svg": "image/svg+xml",
}


@app.get("/api/version")
def version() -> dict:
    """Dấu vân tay của bản web đang phục vụ.

    VÌ SAO CẦN: `Cache-Control: no-store` chỉ áp cho lần TẢI SAU. Một tab đã
    mở từ trước giữ nguyên HTML và JS trong bộ nhớ, và người dùng không có
    cách nào biết mình đang nhìn bản cũ — họ báo "tính năng không có" trong
    khi nó đã chạy trên đĩa. Đã xảy ra thật hai lần.

    Web hỏi endpoint này mỗi 30 giây; lệch thì tự tải lại.
    """
    f = (DIST if (DIST / "index.html").is_file() else WEB) / "index.html"
    js = DIST / "assets" / "app.js"
    dau = hashlib.sha256(
        f.read_bytes() + (js.read_bytes() if js.is_file() else b"")
    ).hexdigest()[:12]
    # `goc` để web dựng ĐƯỜNG DẪN TUYỆT ĐỐI trên thanh tài liệu. Mọi API khác
    # chỉ trả đường dẫn tương đối so với SOURCE_ROOT (đúng, vì đó là biên bảo
    # mật), nhưng người dùng cần biết tệp nằm ở đâu trên máy để mở bằng công
    # cụ khác — nói "0. Info/CCCD.pdf" thì họ vẫn phải đi tìm.
    return {"van_tay": dau, "goc": str(SOURCE_ROOT)}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    f = (DIST if (DIST / "index.html").is_file() else WEB) / "index.html"
    return HTMLResponse(f.read_text("utf-8"), headers=_NO_CACHE)


@app.get("/assets/{ten:path}")
def asset(ten: str) -> Response:
    """Tài nguyên Vite dựng ra.

    `ten` đi thẳng vào đường dẫn nên phải chặn thoát thư mục: `../../etc`
    mà lọt là đọc được cả đĩa.
    """
    f = (DIST / "assets" / ten).resolve()
    try:
        f.relative_to((DIST / "assets").resolve())
    except ValueError:
        raise HTTPException(404, "không có tệp này")
    if not f.is_file():
        raise HTTPException(404, "không có tệp này")
    return Response(f.read_bytes(),
                    media_type=_MIME.get(f.suffix, "application/octet-stream"),
                    headers=_NO_CACHE)


@app.get("/app.js")
def appjs() -> Response:
    return Response((WEB / "app.js").read_text("utf-8"),
                    media_type="application/javascript", headers=_NO_CACHE)


@app.get("/style.css")
def css() -> Response:
    return Response((WEB / "style.css").read_text("utf-8"),
                    media_type="text/css", headers=_NO_CACHE)


@app.get("/src/{ten:path}")
def src_file(ten: str) -> Response:
    """Tệp nguồn — CHỈ dùng khi chưa chạy `npm run build`.

    Trình duyệt tự phân giải `import` giữa các module, nên chế độ này chạy
    được mà không cần công cụ dựng. pdf.js sẽ không hoạt động (nó nằm trong
    node_modules) nhưng phần còn lại thì có.
    """
    f = (WEB / "src" / ten).resolve()
    try:
        f.relative_to((WEB / "src").resolve())
    except ValueError:
        raise HTTPException(404, "không có tệp này")
    if not f.is_file():
        raise HTTPException(404, "không có tệp này")
    return Response(f.read_bytes(),
                    media_type=_MIME.get(f.suffix, "text/plain"),
                    headers=_NO_CACHE)


def _tailnet_ip() -> str | None:
    """Địa chỉ Tailscale của máy này, hoặc None nếu chưa vào tailnet.

    HỎI CARD MẠNG TRƯỚC, CLI CHỈ LÀ ĐƯỜNG LÙI.
    Ngược với trực giác, nhưng `tailscale ip -4` KHÔNG chạy được dưới launchd:
    bản Mac App Store phải nói chuyện với tiến trình GUI qua sandbox, mà agent
    launchd không ở trong phiên đồ hoạ nên luôn nhận:

        The Tailscale GUI failed to start: … (Tailscale.CLIError error 3.)

    Tệ hơn, câu đó in ra STDOUT kèm mã thoát 0. Bản đầu lấy nguyên nó làm
    hostname; uvicorn đem đi phân giải DNS và chết với `UnicodeError: label
    empty or too long` — một lỗi cách xa nguyên nhân thật.

    `ifconfig` không cần GUI, không cần biến môi trường, chạy được với `env -i`.
    Địa chỉ Tailscale luôn nằm trong 100.64.0.0/10 (dải CGNAT mà Tailscale
    dùng riêng), nên nhận ra nó không cần đoán tên card `utun` nào.
    """
    import ipaddress
    import re as _re
    import shutil
    import subprocess

    CGNAT = ipaddress.ip_network("100.64.0.0/10")

    def _hop_le(s: str) -> str | None:
        try:
            ip = ipaddress.IPv4Address(s.strip())
        except ValueError:
            return None
        return str(ip) if ip in CGNAT else None

    # 1. Card mạng — nguồn duy nhất chạy được dưới launchd.
    try:
        out = subprocess.run(["/sbin/ifconfig"], capture_output=True,
                             text=True, timeout=5)
        for m in _re.finditer(r"\binet (\d+\.\d+\.\d+\.\d+)", out.stdout):
            if ip := _hop_le(m.group(1)):
                return ip
    except (OSError, subprocess.SubprocessError):
        pass

    # 2. CLI — chỉ dùng khi chạy tay trong terminal.
    exe = (shutil.which("tailscale")
           or "/Applications/Tailscale.app/Contents/MacOS/Tailscale")
    if not Path(exe).exists():
        return None
    try:
        out = subprocess.run([exe, "ip", "-4"], capture_output=True,
                             text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    for dong in out.stdout.splitlines():
        if ip := _hop_le(dong):
            return ip
    return None


if __name__ == "__main__":
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tailnet", action="store_true",
                    help="nghe trên địa chỉ Tailscale để máy khác trong "
                         "tailnet xem được (KHÔNG mở ra LAN)")
    ap.add_argument("--port", type=int, default=8811)
    args = ap.parse_args()

    host = "127.0.0.1"
    if args.tailnet:
        # CHỜ TAILSCALE, KHÔNG CHẾT NGAY.
        # Dưới launchd lúc đăng nhập, agent chạy TRƯỚC khi Tailscale GUI kịp
        # dựng, nên lần hỏi đầu luôn trượt. Thoát ngay thì KeepAlive dựng lại
        # sau 30s và thường vẫn trượt — thành vòng lặp chết-dựng ghi đầy log.
        # Chờ tại chỗ rẻ hơn và im lặng hơn.
        for lan in range(30):          # 30 × 2s = tối đa 60s
            host = _tailnet_ip() or ""
            if host:
                break
            if lan == 0:
                print("Chờ Tailscale sẵn sàng…", file=sys.stderr)
            time.sleep(2)
        if not host:
            print("Không tìm thấy địa chỉ Tailscale sau 60s.", file=sys.stderr)
            print("Kiểm tra: tailscale status", file=sys.stderr)
            raise SystemExit(1)

    print(f"Kho : {STORE}")
    print(f"Mở  : http://{host}:{args.port}")
    if args.tailnet:
        print("\n⚠ Đang phục vụ trên tailnet — chỉ thiết bị đã đăng nhập")
        print("  cùng tài khoản Tailscale mới vào được. Mạng LAN KHÔNG thấy")
        print("  cổng này. Kho chứa hồ sơ khách hàng: tắt server khi xong.")
    else:
        print("\n⚠ Chỉ nghe trên loopback — kho này chứa hồ sơ khách hàng.")
        print("  Cần xem từ máy khác: thêm --tailnet")

    uvicorn.run(app, host=host, port=args.port, log_level="warning")
