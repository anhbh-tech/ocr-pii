"""Dựng gold set từ corpus thật — Task 8.

QUY TRÌNH VÀ LÝ DO CỦA NÓ
─────────────────────────
Ground truth phải do NGƯỜI gõ. Nhưng gõ từ con số không cho 21 ảnh là việc
nhiều giờ, nên script này tạo **bản nháp bằng Apple Vision** để người sửa —
sửa nhanh hơn gõ mới nhiều lần, và Vision đạt CER 0,312 trên MDPBench nên bản
nháp đủ tốt để làm điểm xuất phát.

VÌ SAO DÙNG APPLE VISION MÀ KHÔNG DÙNG TRỢ LÝ AI ĐỌC ẢNH
────────────────────────────────────────────────────────
Ràng buộc số 1: **dữ liệu khách không rời máy**.

Apple Vision chạy hoàn toàn trên máy — ảnh không đi đâu cả. Một trợ lý AI chạy
trên máy chủ đám mây thì ngược lại: muốn nó "gõ hộ" thì phải gửi ảnh lên, và
với ảnh căn cước công dân hay biên lai ngân hàng thì đó là rò rỉ PII thật,
bất kể thư mục có quyền 700 hay không. Quyền 700 bảo vệ ổ đĩa, không bảo vệ
được đường truyền.

Nên: **máy đọc nháp, người sửa.** Không có bước nào ảnh rời máy.

BẢN NHÁP KHÔNG PHẢI GROUND TRUTH
────────────────────────────────
Tệp nháp ghi trong `data/gold/draft/`, ground truth thật ở `data/gold/truth/`.
Hai thư mục tách biệt có chủ ý: nếu để chung, một ngày nào đó ta sẽ chấm điểm
Vision bằng chính đầu ra của Vision và ra kết quả hoàn hảo giả.

`scripts/check_gold_set.py` từ chối mọi tệp truth còn y hệt bản nháp.

CA QUAN TRỌNG NHẤT: ẢNH KHÔNG CÓ CHỮ
────────────────────────────────────
Nhiều ảnh trong kho là ảnh SẢN PHẨM — không có chữ nào. Tesseract vẫn sinh ra
724 ký tự rác từ chúng ("aot ! ON ee PS `"). Ground truth đúng của những ảnh
đó là **chuỗi rỗng**, và đó là phép thử gắt nhất cho một engine: nó có biết im
lặng khi không có gì để đọc không.

Loại lỗi này khác hẳn "đọc sai" — nó là **bịa chữ từ nhiễu**, và không chỉ số
nào trong bộ đo hiện tại bắt được nếu ground truth không có ảnh trắng.

Chạy:
    uv run python scripts/build_gold_set.py --dry-run    # xem trước, không chép
    uv run python scripts/build_gold_set.py
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "data" / "gold"
IMAGES, DRAFT, TRUTH = GOLD / "images", GOLD / "draft", GOLD / "truth"

#: Kho tài liệu thật. Lấy từ biến môi trường để không cắm cứng đường dẫn máy
#: này — bài học `refiny_engine`: đường dẫn cắm cứng làm test skip im lặng
#: hàng tháng trời.
CORPUS = Path(os.environ.get(
    "OCR_LAB_CORPUS", Path.home() / ".private" / "refiny_data"))

#: Hai hồ sơ mất trắng phần ảnh — 13/13 và 6/6 tệp ra rác. Đây là lý do dự án
#: này tồn tại, nên gold set phải phủ đúng chúng. Tên thư mục hồ sơ là tên
#: khách, nên danh sách nằm ngoài cây git:
#: `{"ho_so_muc_tieu": ["<số>. US. <NHÃN>", ...]}` (chuỗi con của đường dẫn).
GOLD_CONFIG = Path(os.environ.get(
    "OCR_LAB_GOLD_CONFIG", Path.home() / ".private" / "so" / "gold_set.json"))


def target_matters(config: Path = GOLD_CONFIG) -> list[str]:
    if not config.is_file():
        return []
    return json.loads(config.read_text(encoding="utf-8"))["ho_so_muc_tieu"]


TARGET_MATTERS = target_matters()

#: Nhãn loại tài liệu, suy từ tên tệp. Dùng để báo cáo theo nhóm — ảnh sản
#: phẩm và giấy tờ tuỳ thân hỏng theo cách khác nhau và cần kết luận khác nhau.
_KIND_HINTS = [
    ("cccd", "giấy tờ tuỳ thân"),
    ("payment receipt", "biên lai"),
    ("acc info", "ảnh màn hình tài khoản"),
    ("product", "ảnh sản phẩm"),
    ("evidence", "bằng chứng sử dụng"),
]


def _kind(name: str) -> str:
    low = name.lower()
    for hint, label in _KIND_HINTS:
        if hint in low:
            return label
    return "khác"


def _find_images() -> list[Path]:
    if not CORPUS.exists():
        sys.exit(f"không thấy kho: {CORPUS}\n"
                 f"đặt biến OCR_LAB_CORPUS nếu kho ở chỗ khác")
    out = []
    for p in CORPUS.rglob("*"):
        if p.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        if any(m in str(p) for m in TARGET_MATTERS):
            out.append(p)
    return sorted(out)


def _vision_draft(image_dir: Path) -> dict[str, str]:
    """Chạy Apple Vision trên thư mục ảnh, trả {tên tệp: văn bản}.

    Trên máy không phải macOS, hoặc chưa biên dịch, trả rỗng — người sẽ gõ từ
    đầu. KHÔNG im lặng bỏ qua: in rõ lý do.
    """
    binary = ROOT / "swift" / "vision_ocr"
    if not binary.exists():
        print(f"  chưa có {binary.name} — biên dịch bằng:\n"
              f"    cd swift && swiftc -O main.swift -o vision_ocr\n"
              f"  (bỏ qua bản nháp, sẽ phải gõ từ đầu)", file=sys.stderr)
        return {}

    r = subprocess.run([str(binary), str(image_dir)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  Vision lỗi: {r.stderr[-300:]}", file=sys.stderr)
        return {}
    return {x["page"]: x["text"] for x in json.loads(r.stdout)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="chỉ liệt kê, không chép gì")
    args = ap.parse_args()

    if not TARGET_MATTERS:
        sys.exit(f"không thấy danh sách hồ sơ mục tiêu: {GOLD_CONFIG}\n"
                 f"đặt biến OCR_LAB_GOLD_CONFIG nếu tệp ở chỗ khác")
    images = _find_images()
    if not images:
        sys.exit(f"không tìm thấy ảnh nào của {TARGET_MATTERS} trong {CORPUS}")

    print(f"Tìm thấy {len(images)} ảnh trong 2 hồ sơ mất trắng:\n")
    by_kind: dict[str, int] = {}
    for p in images:
        k = _kind(p.name)
        by_kind[k] = by_kind.get(k, 0) + 1
    for k, n in sorted(by_kind.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<26} {n:>3}")

    if args.dry_run:
        print("\n--dry-run: không chép gì.")
        for p in images:
            print(f"  [{_kind(p.name):<22}] {p.name}")
        return 0

    # ── chép ảnh, giữ quyền 700 ─────────────────────────────────────────
    for d in (IMAGES, DRAFT, TRUTH):
        d.mkdir(parents=True, exist_ok=True)
        d.chmod(0o700)

    manifest = []
    for p in images:
        # Tên phẳng, giữ mã hồ sơ để truy ngược được.
        matter = next((m for m in TARGET_MATTERS if m in str(p)), "?")
        code = matter.split(".")[0].strip().replace(" ", "")
        flat = f"{code}__{p.name}".replace(" ", "_")
        dst = IMAGES / flat
        if not dst.exists():
            shutil.copy2(p, dst)
            dst.chmod(0o600)
        manifest.append({"gold_name": flat, "kind": _kind(p.name),
                         "matter": matter,
                         # Chỉ lưu đường dẫn TƯƠNG ĐỐI trong kho — đường dẫn
                         # tuyệt đối vừa lộ cấu trúc máy vừa vô dụng khi
                         # chuyển máy.
                         "source": str(p.relative_to(CORPUS))})

    print(f"\nChép {len(manifest)} ảnh → {IMAGES} (quyền 700)")

    # ── bản nháp bằng Vision, chạy trên máy ─────────────────────────────
    print("\nTạo bản nháp bằng Apple Vision (chạy TRÊN MÁY, ảnh không rời máy)…")
    drafts = _vision_draft(IMAGES)

    empty = 0
    for item in manifest:
        name = item["gold_name"]
        text = drafts.get(name, "")
        stem = Path(name).stem
        (DRAFT / f"{stem}.txt").write_text(text, encoding="utf-8")
        (DRAFT / f"{stem}.txt").chmod(0o600)
        item["draft_chars"] = len(text)
        if len(text.strip()) < 10:
            empty += 1

        # Tạo tệp truth RỖNG để người điền. Không chép bản nháp sang: nếu chép,
        # tệp chưa ai sửa vẫn trông như đã gõ xong, và ta sẽ chấm Vision bằng
        # chính đầu ra của Vision.
        t = TRUTH / f"{stem}.txt"
        if not t.exists():
            t.write_text("", encoding="utf-8")
            t.chmod(0o600)

    (GOLD / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (GOLD / "manifest.json").chmod(0o600)

    print(f"  {len(drafts)} bản nháp → {DRAFT}")
    print(f"  {empty}/{len(manifest)} ảnh Vision đọc ra gần như KHÔNG CÓ CHỮ")
    print(f"     → nhiều khả năng là ảnh sản phẩm; ground truth của chúng là")
    print(f"       CHUỖI RỖNG, và đó là phép thử gắt nhất: engine có biết im")
    print(f"       lặng khi không có gì để đọc không (tesseract bịa 724 ký tự")
    print(f"       rác từ một ảnh như vậy).")

    print(f"""
BƯỚC TIẾP THEO — CẦN NGƯỜI, KHÔNG TỰ ĐỘNG ĐƯỢC

  1. Mở từng ảnh trong {IMAGES}
  2. Đọc bản nháp tương ứng trong {DRAFT}
  3. Gõ bản ĐÚNG vào {TRUTH}/<tên>.txt

  Quy ước gõ:
    * ảnh KHÔNG có chữ  → để tệp RỖNG (đó là đáp án đúng, không phải bỏ sót)
    * chỉ gõ chữ NHÌN THẤY được, không suy đoán chữ bị che
    * giữ nguyên số hiệu, ngày, email, số tài khoản TỪNG KÝ TỰ
    * xuống dòng theo bố cục ảnh

  Kiểm khi xong:  uv run python scripts/check_gold_set.py
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
