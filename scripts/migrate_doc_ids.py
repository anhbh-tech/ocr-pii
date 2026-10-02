"""Đổi tên thư mục tài liệu sang `doc_id` tính trên đường dẫn đã chuẩn hoá NFC.

VÌ SAO CẦN DI TRÚ
─────────────────
`doc_id_for` trước đây băm thẳng chuỗi đường dẫn. macOS trả tên tệp ở dạng
NFD (`ă` = `a` + U+0306), nên cùng một tệp cho hai id khác nhau tuỳ chuỗi đến
từ `os.listdir` hay từ người gõ. File manager gọi `doc_id_for` trên đường từ
đĩa và báo "chưa chạy" cho tài liệu đã chạy — rồi người dùng trả tiền ADE lần
thứ hai.

Sửa hàm băm thôi thì 36 thư mục hiện có thành mồ côi: kết quả đã trả $0,845
để có vẫn nằm trên đĩa nhưng không ai tìm ra. Script này đổi tên chúng sang
id mới, và ghi luôn `source` dạng NFC vào meta để hai bên khớp hẳn.

AN TOÀN: mặc định chỉ IN ra dự định. Phải `--yes` mới đổi thật.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ocr_lab.ade_store import DEFAULT_STORE, doc_id_for           # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", type=Path, default=DEFAULT_STORE)
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    viec, ok, dung = [], 0, []
    for d in sorted(args.store.iterdir()):
        m = d / "meta.json"
        if not m.is_file():
            continue
        meta = json.loads(m.read_text("utf-8"))
        src = meta.get("source", "")
        src_nfc = unicodedata.normalize("NFC", src)
        moi = doc_id_for(src_nfc)
        if moi == d.name:
            ok += 1
            continue
        if (args.store / moi).exists():
            # Đích đã tồn tại: hai thư mục cho cùng một tài liệu, nghĩa là
            # kho đã bị nhân đôi trước đó. KHÔNG tự gộp — gộp sai thì mất
            # bản tốt, và người chạy cần biết để tự quyết.
            dung.append((d.name, moi))
            continue
        viec.append((d, moi, src_nfc, src != src_nfc))

    print(f"Kho: {args.store}")
    print(f"{ok} thư mục đã đúng · {len(viec)} cần đổi tên · "
          f"{len(dung)} xung đột\n")

    for d, moi, _, nfd in viec[:50]:
        print(f"  {d.name} → {moi}   {'(source NFD)' if nfd else ''}")
    if len(viec) > 50:
        print(f"  … và {len(viec) - 50} thư mục nữa")

    if dung:
        print("\nXUNG ĐỘT — đích đã tồn tại, KHÔNG đụng tới:")
        for a, b in dung:
            print(f"  {a} ↔ {b}")

    if not viec:
        return 0
    if not args.yes:
        print("\nChưa đổi gì. Thêm --yes để thực hiện.")
        return 0

    for d, moi, src_nfc, _ in viec:
        # Ghi `source` dạng NFC TRƯỚC khi đổi tên: nếu đổi tên xong mới ghi
        # mà tiến trình chết giữa chừng thì thư mục mang tên mới nhưng meta
        # vẫn chuỗi cũ — lần chạy sau lại tính ra id khác nữa.
        for tep in ("meta.json", "meta_pro.json"):
            f = d / tep
            if not f.is_file():
                continue
            meta = json.loads(f.read_text("utf-8"))
            meta["source"] = src_nfc
            f.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                         encoding="utf-8")
        d.rename(args.store / moi)

    print(f"\nĐã đổi tên {len(viec)} thư mục.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
