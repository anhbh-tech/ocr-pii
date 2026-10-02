"""Đo SenOCR-Vi trên M4: tốc độ, bộ nhớ, chất lượng dấu tiếng Việt.

VÌ SAO SCRIPT NÀY TỒN TẠI
─────────────────────────
Không benchmark công khai nào trả lời được câu hỏi của ta:

  * SenOCR-Vi công bố điểm chất lượng nhưng **không công bố** pages/sec,
    VRAM, hay độ trễ — README của họ nói thẳng điều đó.
  * E-ARMOR (arXiv 2509.03615) đo độ trễ, nhưng trên **CPU biên thuần** và
    trộn 54 ngôn ngữ, không tách tiếng Việt. Máy này có MPS.

Nên con số duy nhất đáng tin là con số đo trên chính máy này, chính ảnh này.

NGƯỠNG BỎ CUỘC: >30 giây/trang thì không dùng được cho 566 tệp của kho.
"""

from __future__ import annotations

import argparse
import json
import resource
import statistics as st
import time
import unicodedata as ud
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "SenOCR-Vi"

#: Tỉ lệ ký tự có dấu của tiếng Việt thật, đo trên ground truth MDPBench.
#: Dùng làm mốc: kết quả OCR thấp hơn nhiều nghĩa là đã mất dấu.
VIETNAMESE_ACCENT_SHARE = 0.217


def accent_share(text: str) -> float:
    """Tỉ lệ chữ cái mang dấu tổ hợp (NFD).

    Đây là thước đo thay thế cho "OCR có đọc được tiếng Việt không". Dấu thanh
    và dấu nguyên âm là thứ engine đa ngôn ngữ hay bỏ đầu tiên, và cũng là thứ
    mang thông tin định danh mà pipeline PII phụ thuộc vào.
    """
    alpha = [c for c in text if c.isalpha()]
    if not alpha:
        return 0.0
    marked = sum(1 for c in alpha
                 if any(ud.combining(m) for m in ud.normalize("NFD", c)))
    return marked / len(alpha)


def peak_rss_gb() -> float:
    """RSS đỉnh của tiến trình, tính bằng GB.

    macOS trả `ru_maxrss` theo BYTE (Linux theo kilobyte) — nhầm đơn vị ở đây
    cho ra con số lệch 1024 lần và kết luận sai hoàn toàn về việc model có vừa
    bộ nhớ hay không.
    """
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 ** 3)


def load_model(device: str, dtype_name: str):
    """Nạp model với kiểu số chỉ định.

    FP32 trên máy 16 GB là ca tệ nhất: checkpoint 3,85 GB nở ra ~4 GB trong
    RAM, cộng bộ đệm suy luận thì tràn sang swap. Đo thật trên máy này: swap
    chạm 10,5/11 GB, một ảnh chưa xong sau 16 phút.

    Trọng số gốc lưu ở **bfloat16** — nạp FP32 là tự nhân đôi bộ nhớ để đổi
    lấy độ chính xác mà mô hình vốn không có. README của SenOCR-Vi nói bản
    benchmark phục vụ ở FP32 và khuyến cáo kiểm chứng riêng cho precision
    thấp hơn; đó chính là việc script này làm.
    """
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor

    dtypes = {"float32": torch.float32,
              "bfloat16": torch.bfloat16,
              "float16": torch.float16}
    model = (AutoModelForImageTextToText
             .from_pretrained(MODEL_DIR, dtype=dtypes[dtype_name],
                              low_cpu_mem_usage=True)
             .to(device).eval())
    processor = AutoProcessor.from_pretrained(MODEL_DIR)
    return model, processor


def read_page(model, processor, image, device: str, max_new_tokens: int) -> str:
    import torch

    messages = [{"role": "user", "content": [
        {"type": "image", "image": image},
        {"type": "text", "text": "OCR:"},
    ]}]
    inputs = processor.apply_chat_template(
        messages, add_generation_prompt=True, tokenize=True,
        return_dict=True, return_tensors="pt").to(device)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=max_new_tokens,
                             do_sample=False)
    return processor.decode(out[0][inputs["input_ids"].shape[-1]:-1],
                            skip_special_tokens=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="mps", choices=["mps", "cpu"])
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--max-new-tokens", type=int, default=512)
    ap.add_argument("--dtype", default="bfloat16",
                    choices=["bfloat16", "float16", "float32"])
    ap.add_argument("--out", default="reports/senocr_probe.json")
    args = ap.parse_args()

    from PIL import Image

    # Ảnh thật từ kho — đúng nhóm đang hỏng (ảnh chụp, không phải PDF).
    corpus = Path.home() / ".private/refiny_data"
    images = sorted(p for p in corpus.rglob("*")
                    if p.suffix.lower() in {".jpg", ".jpeg", ".png"})[:args.limit]
    if not images:
        raise SystemExit("không tìm thấy ảnh nào trong kho")

    print(f"  thiết bị: {args.device} · dtype {args.dtype} · {len(images)} ảnh thật")
    t0 = time.time()
    model, processor = load_model(args.device, args.dtype)
    load_s = time.time() - t0
    print(f"  nạp model: {load_s:.1f}s · RSS {peak_rss_gb():.2f} GB\n")

    rows = []
    for p in images:
        img = Image.open(p).convert("RGB")
        t1 = time.time()
        try:
            text = read_page(model, processor, img, args.device,
                             args.max_new_tokens)
            err = ""
        except Exception as exc:                      # noqa: BLE001
            text, err = "", f"{type(exc).__name__}: {exc}"
        el = time.time() - t1
        rows.append({"file": p.name, "seconds": round(el, 2),
                     "chars": len(text.strip()),
                     "accent_share": round(accent_share(text), 3),
                     "error": err, "sample": text.strip()[:160]})
        flag = "LỖI" if err else ""
        print(f"  {p.name[:40]:<40} {el:>6.1f}s {len(text.strip()):>6} ký tự "
              f"dấu {accent_share(text):.3f} {flag}")
        if err:
            print(f"      {err[:110]}")

    ok = [r for r in rows if not r["error"]]
    summary = {
        "device": args.device,
        "dtype": args.dtype,
        "load_seconds": round(load_s, 1),
        "peak_rss_gb": round(peak_rss_gb(), 2),
        "pages": len(rows),
        "failed": len(rows) - len(ok),
        "median_seconds": round(st.median([r["seconds"] for r in ok]), 2) if ok else None,
        "mean_accent_share": round(st.mean([r["accent_share"] for r in ok]), 3) if ok else None,
        "vietnamese_reference_accent": VIETNAMESE_ACCENT_SHARE,
    }
    print(f"\n  === TỔNG KẾT ===")
    for k, v in summary.items():
        print(f"    {k:<28} {v}")

    if summary["median_seconds"]:
        verdict = ("DÙNG ĐƯỢC" if summary["median_seconds"] <= 30
                   else "QUÁ CHẬM — vượt ngưỡng bỏ cuộc 30s/trang")
        print(f"\n    phán quyết: {verdict}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "rows": rows},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"    đã lưu: {out}")


if __name__ == "__main__":
    main()
