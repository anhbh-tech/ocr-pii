#!/usr/bin/env python3
"""Chạy TOÀN KHO theo lô, chọn engine rẻ nhất phù hợp từng loại tệp.

QUY TẮC ĐỊNH TUYẾN — người dùng đặt, ghi lại ở đây để không ai đổi nhầm
──────────────────────────────────────────────────────────────────────
    PDF scan, ảnh rời       → ADE Pro     (0,9 cr/trang)
    PDF digital, docx, xlsx → ADE Verity  (0,3 cr/trang)

Lý do đằng sau: tệp scan và ảnh KHÔNG có lớp chữ nào, nên chất lượng đọc
quyết định toàn bộ giá trị — đáng trả giá cao. Tệp digital đã có lớp chữ
hoàn hảo; Verity chỉ cần dựng cấu trúc và đọc phần ảnh chèn vào.

VÌ SAO VẪN GỬI TỆP DIGITAL CHO ADE
──────────────────────────────────
Có thể đọc digital bằng `extract.py` miễn phí. Nhưng Verity trả về thêm
hai thứ mà bản đọc thẳng không có: cấu trúc ngữ nghĩa (đâu là bảng, đâu là
chữ ký) và mô tả nội dung ảnh chèn vào. Đó chính là phần "description" mà
người dùng chỉ ra là đắt giá.

AN TOÀN CHI PHÍ
───────────────
Ba lớp, và lớp nào cũng phải vượt qua:
  * dự toán in ra trước, mặc định KHÔNG chạy;
  * `--tran-credits` chặn cứng, vượt là dừng;
  * tệp đã có kết quả của đúng engine đó thì bỏ qua, không gọi lại.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ocr_lab.ade_store import doc_id_for, render_pages, save_result  # noqa: E402
from ocr_lab.classify import classify_pdf  # noqa: E402
from ocr_lab.engines import load_dotenv  # noqa: E402

NGUON = Path.home() / ".private" / "refiny_data"
KHO = Path.home() / ".private" / "ade_out"

#: Giá mỗi trang, tính bằng credits. 1 credit = $0,01.
GIA = {"verity": 0.3, "pro": 0.9}

#: Tên model ADE. Lấy từ script đã chạy được, KHÔNG đoán — một tên sai trả
#: 422 cho cả mẻ (đã mất một lượt vì `dpt-2-latest` bịa ra).
MODEL = {"verity": "dpt-3-verity-20260804-preview", "pro": "dpt-3-pro"}

#: Đuôi tệp ADE nhận trực tiếp.
ANH = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}
OFFICE = {".docx", ".xlsx"}


@dataclass
class Viec:
    """Một tệp cần chạy, đã biết loại và engine."""

    path: Path
    rel: str
    section: str          # pdf_digital | pdf_scan | anh | docx | xlsx
    case: str             # thư mục hồ sơ chứa nó
    engine: str           # verity | pro
    so_trang: int

    @property
    def credits(self) -> float:
        return self.so_trang * GIA[self.engine]


def _case_cua(rel: str) -> str:
    """Tên hồ sơ (case) chứa tệp này.

    Cấu trúc kho: `Phòng IP/<nhóm nghiệp vụ>/<case>/<thư mục con>/tệp`.
    Lấy đúng cấp thứ ba; tệp nông hơn thì lấy cấp sâu nhất có được, chứ
    không bỏ qua — một tệp không thuộc case nào vẫn phải xuất hiện trong
    báo cáo, nếu không nó biến mất im lặng.
    """
    phan = Path(rel).parts
    return phan[2] if len(phan) >= 4 else (phan[-2] if len(phan) >= 2 else "(gốc)")


def phan_loai(f: Path) -> tuple[str, int] | None:
    """Trả về (section, số trang). None nghĩa là không xử lý được."""
    suf = f.suffix.lower()
    if suf in ANH:
        return "anh", 1
    if suf == ".docx":
        return "docx", 1
    if suf == ".xlsx":
        # ADE từ chối xlsx: 422 "Unsupported format: application/zip".
        # Đã kiểm bằng tệp tự dựng, không phải suy đoán từ tệp hỏng.
        # Vẫn xếp section để báo cáo đầy đủ; phần định tuyến bỏ qua nó.
        return "xlsx", 1
    if suf != ".pdf":
        return None
    try:
        kq = classify_pdf(f)
    except Exception:       # noqa: BLE001 — PDF hỏng không dừng cả mẻ
        return None
    if not kq.pages:
        return None
    n_scan = sum(1 for p in kq.pages if p.needs_ocr)
    n_dig = len(kq.pages) - n_scan
    # Đa số trang quyết định. Một PDF trộn lẫn thì trang scan đắt hơn, nên
    # hoà nhau xếp về scan — thà trả thừa còn hơn đọc hụt phần scan.
    return ("pdf_scan" if n_scan >= n_dig else "pdf_digital"), len(kq.pages)


def _da_co(rel: str, engine: str) -> bool:
    tep = "parse_pro.json" if engine == "pro" else "parse.json"
    return (KHO / doc_id_for(rel) / tep).is_file()


def liet_ke(bo_qua_da_chay: bool = True) -> list[Viec]:
    ra: list[Viec] = []
    for f in sorted(NGUON.rglob("*")):
        if not f.is_file() or f.name.startswith("."):
            continue
        # Tệp khoá tạm của Word/Excel: `~$<tên gốc>.docx`, khoảng 160 byte,
        # do phần mềm tạo khi ai đó ĐANG mở tài liệu và thường sót lại sau
        # khi máy tắt đột ngột. Nó không có nội dung — gửi lên ADE chỉ tốn
        # tiền để nhận về lỗi, và làm mọi báo cáo treo ở "còn 1 tệp chưa
        # chạy" mãi mãi.
        if f.name.startswith("~$"):
            continue
        pl = phan_loai(f)
        if not pl:
            continue
        section, so_trang = pl
        # QUY TẮC ĐỊNH TUYẾN — xem docstring đầu tệp.
        if section == "xlsx":
            continue        # ADE không nhận — đọc bằng extract.py, miễn phí
        engine = "pro" if section in {"pdf_scan", "anh"} else "verity"
        rel = str(f.relative_to(NGUON))
        if bo_qua_da_chay and _da_co(rel, engine):
            continue
        ra.append(Viec(f, rel, section, _case_cua(rel), engine, so_trang))
    return ra


def in_du_toan(viec: list[Viec]) -> float:
    theo_sec: dict[str, list[Viec]] = {}
    for v in viec:
        theo_sec.setdefault(v.section, []).append(v)

    print(f"\n{'section':<14} {'engine':<8} {'tệp':>5} {'trang':>6} "
          f"{'credits':>9} {'USD':>8}")
    print("-" * 56)
    tong = 0.0
    for sec in sorted(theo_sec):
        vs = theo_sec[sec]
        cr = sum(v.credits for v in vs)
        tong += cr
        print(f"{sec:<14} {vs[0].engine:<8} {len(vs):>5} "
              f"{sum(v.so_trang for v in vs):>6} {cr:>9.1f} {cr / 100:>8.2f}")
    print("-" * 56)
    print(f"{'TỔNG':<29} {sum(v.so_trang for v in viec):>6} "
          f"{tong:>9.1f} {tong / 100:>8.2f}")

    cases = Counter(v.case for v in viec)
    print(f"\n{len(cases)} hồ sơ · 8 hồ sơ nhiều việc nhất:")
    for c, n in cases.most_common(8):
        cr = sum(v.credits for v in viec if v.case == c)
        print(f"  {n:>3} tệp · {cr / 100:>6.2f} USD · {c[:52]}")
    return tong


def _goi_co_thu_lai(engine, path: Path, lan_toi_da: int = 5):
    """Gọi ADE, lùi dần khi bị 429.

    Phân biệt hai loại lỗi mà lần chạy đầu gộp làm một:

      * 429 rate_limit  — tệp KHÔNG có vấn đề gì, chỉ là ta gửi quá nhanh.
        Bỏ qua nó là vứt một tệp hợp lệ. Đợi rồi gửi lại.
      * 422 validation   — định dạng ADE không nhận (xlsx). Thử lại bao
        nhiêu lần cũng vô ích, hỏng ngay để khỏi tốn thời gian.

    Lùi dần theo cấp số nhân: 5s, 10s, 20s, 40s. Hàng đợi bên kia cần thời
    gian thoát tải, gửi lại ngay chỉ làm nó tệ thêm.
    """
    cho = 5.0
    for lan in range(lan_toi_da):
        try:
            return engine.parse_document(path)
        except Exception as e:      # noqa: BLE001
            ten = type(e).__name__
            if "RateLimit" not in ten and "429" not in str(e):
                raise
            if lan == lan_toi_da - 1:
                raise
            print(f"      429 — đợi {cho:.0f}s rồi thử lại "
                  f"(lần {lan + 2}/{lan_toi_da})")
            time.sleep(cho)
            cho *= 2
    raise RuntimeError("không tới được")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tran-credits", type=float, default=150.0,
                    help="vượt trần là DỪNG, không chạy gì")
    ap.add_argument("--chay", action="store_true",
                    help="BẮT BUỘC để thực sự gọi API — mặc định chỉ dự toán")
    ap.add_argument("--section", default="",
                    help="chỉ chạy một section (pdf_digital, pdf_scan, anh, docx, xlsx)")
    ap.add_argument("--ra", type=Path,
                    default=Path("reports/batch_toan_kho.json"))
    a = ap.parse_args()

    print("đang phân loại toàn kho…")
    viec = liet_ke()
    if a.section:
        viec = [v for v in viec if v.section == a.section]
    if not viec:
        print("không còn việc nào — mọi tệp đã chạy engine tương ứng.")
        return 0

    tong = in_du_toan(viec)

    if tong > a.tran_credits:
        print(f"\n⛔ {tong:.1f} credits VƯỢT TRẦN {a.tran_credits} — dừng.")
        print("   Tăng --tran-credits nếu thực sự muốn, hoặc chạy từng "
              "--section một.")
        return 1
    if not a.chay:
        print("\nCHƯA GỬI GÌ CẢ. Thêm --chay để chạy thật.")
        return 0

    print("\n⚠ HỒ SƠ KHÁCH HÀNG THẬT đang được gửi tới LandingAI.\n")
    load_dotenv()
    from ocr_lab.engines.ade import AdeEngine

    eng = {k: AdeEngine(model=MODEL[k], service_tier="standard")
           for k in ("verity", "pro")}

    xong, loi, cr_that = 0, 0, 0.0
    bao: list[dict] = []
    t0 = time.perf_counter()

    for i, v in enumerate(viec, start=1):
        try:
            kq = _goi_co_thu_lai(eng[v.engine], v.path)
            cr = (kq.get("metadata", {}).get("billing", {})
                  .get("total_credits", v.credits))
            cr_that += cr

            did = doc_id_for(v.rel)
            d = KHO / did
            pages_dir = d / "pages"
            if not (pages_dir.is_dir() and any(pages_dir.glob("p*.*"))):
                try:
                    render_pages(v.path, pages_dir)
                except Exception:   # noqa: BLE001 — docx/xlsx không render được
                    pass
            imgs = sorted(pages_dir.glob("p*.*")) if pages_dir.is_dir() else []
            save_result(KHO, did, kq,
                        source=v.rel, model=MODEL[v.engine], credits=cr,
                        pages=[{"page": n + 1} for n in range(max(1, len(imgs)))],
                        variant="pro" if v.engine == "pro" else "")
            xong += 1
            bao.append({"rel": v.rel, "section": v.section, "case": v.case,
                        "engine": v.engine, "credits": cr,
                        "ky_tu": len(kq.get("markdown", ""))})
            print(f"  [{i}/{len(viec)}] {v.section:<12} {cr:>4.1f}cr "
                  f"{len(kq.get('markdown', '')):>6} ký tự  {v.path.name[:40]}")
        except Exception as e:      # noqa: BLE001 — một tệp lỗi không dừng cả mẻ
            loi += 1
            print(f"  [{i}/{len(viec)}] LỖI {type(e).__name__}: "
                  f"{str(e)[:80]}  {v.path.name[:34]}")

        if cr_that > a.tran_credits:
            print(f"\n⛔ đã tiêu {cr_that:.1f} credits, chạm trần — DỪNG.")
            break

    print(f"\n{xong} xong · {loi} lỗi · {cr_that:.1f} credits "
          f"(${cr_that / 100:.2f}) · {time.perf_counter() - t0:.0f}s")
    a.ra.parent.mkdir(parents=True, exist_ok=True)
    a.ra.write_text(json.dumps(
        {"xong": xong, "loi": loi, "credits": cr_that, "tep": bao},
        ensure_ascii=False, indent=2), "utf-8")
    print(f"→ {a.ra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
