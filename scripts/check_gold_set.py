"""Kiểm gold set trước khi dùng nó làm căn cứ đo.

MỘT GOLD SET SAI THÌ TỆ HƠN KHÔNG CÓ GOLD SET
─────────────────────────────────────────────
Nó vẫn cho ra bảng điểm, vẫn xếp hạng được engine, chỉ là xếp nhầm — và cái
nhầm đó không tự lộ ra. Bốn thứ script này canh:

1. **Tệp truth còn y hệt bản nháp.** Nếu ai đó chép bản nháp sang thư mục
   truth cho nhanh, ta sẽ chấm điểm Apple Vision bằng chính đầu ra của Apple
   Vision và ra kết quả hoàn hảo giả. Đây là lý do `build_gold_set.py` tạo tệp
   truth RỖNG thay vì chép sẵn bản nháp vào.

2. **Quyền tệp.** Đây là tài liệu thật của khách: căn cước công dân, biên lai
   ngân hàng. Quyền 755 nghĩa là mọi tài khoản trên máy đọc được.

3. **Lọt vào git.** Một lần commit nhầm là dữ liệu nằm vĩnh viễn trong lịch
   sử; xoá ở commit sau không gỡ được.

4. **Tệp rỗng: cố ý hay bỏ quên?** Ảnh sản phẩm không có chữ thì ground truth
   ĐÚNG là chuỗi rỗng. Nhưng tệp chưa ai đụng tới cũng rỗng. Hai thứ trông
   giống hệt nhau, nên phải đánh dấu tường minh — xem `_EMPTY_MARKER`.

Chạy:
    uv run python scripts/check_gold_set.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "data" / "gold"
IMAGES, DRAFT, TRUTH = GOLD / "images", GOLD / "draft", GOLD / "truth"

#: Đánh dấu "ảnh này thật sự không có chữ, tôi đã xem và xác nhận".
#:
#: Cần một dấu hiệu tường minh vì tệp rỗng có hai nghĩa trái ngược: "đáp án là
#: chuỗi rỗng" và "chưa ai gõ". Không phân biệt được thì ta sẽ tính những tệp
#: chưa làm vào bảng điểm, và mọi engine đều được 100% trên chúng.
_EMPTY_MARKER = "# KHÔNG CÓ CHỮ"


def main() -> int:
    if not GOLD.exists():
        sys.exit(f"chưa có gold set — chạy: uv run python "
                 f"scripts/build_gold_set.py")

    manifest = json.loads((GOLD / "manifest.json").read_text("utf-8"))
    problems: list[str] = []

    # ── 1. quyền ────────────────────────────────────────────────────────
    for d in (GOLD, IMAGES, DRAFT, TRUTH):
        mode = d.stat().st_mode & 0o777
        if mode != 0o700:
            problems.append(f"{d.relative_to(ROOT)} có quyền {oct(mode)}, "
                            f"phải 0o700 — đây là tài liệu thật của khách")

    # ── 2. git phải chặn ────────────────────────────────────────────────
    r = subprocess.run(["git", "check-ignore", "-q", "data/gold/images/x.jpg"],
                       cwd=ROOT, capture_output=True)
    if r.returncode != 0:
        problems.append("git KHÔNG chặn data/gold/ — dữ liệu khách có thể lọt "
                        "vào lịch sử git")

    # ── 3. đối chiếu bản nháp ───────────────────────────────────────────
    done = empty_confirmed = todo = copied = 0
    by_kind: dict[str, list[int]] = {}

    for item in manifest:
        stem = Path(item["gold_name"]).stem
        t_path, d_path = TRUTH / f"{stem}.txt", DRAFT / f"{stem}.txt"
        if not t_path.exists():
            problems.append(f"thiếu tệp truth: {stem}.txt")
            continue

        truth = t_path.read_text(encoding="utf-8")
        draft = d_path.read_text(encoding="utf-8") if d_path.exists() else ""

        stripped = truth.strip()
        if stripped.startswith(_EMPTY_MARKER):
            empty_confirmed += 1
            state = "rỗng (đã xác nhận)"
        elif not stripped:
            todo += 1
            state = "CHƯA GÕ"
        elif draft.strip() and stripped == draft.strip():
            copied += 1
            problems.append(
                f"{stem}: truth y hệt bản nháp Vision — nếu là do chép sang "
                f"thì mọi phép đo sau sẽ chấm Vision bằng chính Vision")
            state = "y hệt nháp"
        else:
            done += 1
            state = "đã gõ"

        by_kind.setdefault(item["kind"], []).append(1 if state == "đã gõ" else 0)

    # ── báo cáo ─────────────────────────────────────────────────────────
    total = len(manifest)
    print(f"Gold set: {total} ảnh\n")
    print(f"  đã gõ                {done:>3}")
    print(f"  rỗng (đã xác nhận)   {empty_confirmed:>3}")
    print(f"  CHƯA GÕ              {todo:>3}")
    if copied:
        print(f"  y hệt bản nháp       {copied:>3}  ← phải sửa")

    print(f"\n{'loại tài liệu':<26}{'xong':>6}{'/ tổng':>8}")
    for kind, flags in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        print(f"{kind:<26}{sum(flags):>6}{len(flags):>8}")

    if todo:
        print(f"\nCòn {todo} tệp chưa gõ. Xem danh sách:")
        for item in manifest:
            stem = Path(item["gold_name"]).stem
            t = (TRUTH / f"{stem}.txt")
            if t.exists() and not t.read_text(encoding="utf-8").strip():
                draft_len = len((DRAFT / f"{stem}.txt").read_text("utf-8")
                                if (DRAFT / f"{stem}.txt").exists() else "")
                hint = (f"nháp {draft_len} kt" if draft_len
                        else "nháp RỖNG — có thể đáp án đúng là rỗng")
                print(f"    [{item['kind']:<22}] {stem}  ({hint})")
        print(f"\n  Ảnh không có chữ: ghi dòng `{_EMPTY_MARKER}` vào tệp truth")
        print(f"  thay vì để trống — để phân biệt với tệp chưa làm.")

    if problems:
        print(f"\n{'=' * 70}\nVẤN ĐỀ ({len(problems)}):")
        for p in problems:
            print(f"  ✗ {p}")
        return 1

    if todo:
        print(f"\nChưa dùng được làm căn cứ đo: còn {todo} tệp chưa gõ.")
        return 2

    print(f"\n✓ Gold set dùng được: {done} tệp có chữ + {empty_confirmed} tệp "
          f"rỗng đã xác nhận")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
