"""Chồng lớp sửa chính tả protonX lên kết quả ADE.

RÀNG BUỘC QUYẾT ĐỊNH TOÀN BỘ THIẾT KẾ: KHÔNG ĐƯỢC SỬA `markdown` TẠI CHỖ
───────────────────────────────────────────────────────────────────────
Mọi `grounding.range` trong cây `structure` đều trỏ vào chuỗi `markdown` bằng
OFFSET ký tự. Trên một trang CCCD thật đó là 45 span. Sửa chính tả làm đổi độ
dài chuỗi ⇒ mọi offset sau điểm sửa đều lệch ⇒ web vẽ khung sai chỗ, và sai
một cách âm thầm vì khung vẫn trông hợp lý.

Nên bản sửa được ghi vào TỆP RIÊNG `corrected.json`, khoá theo `chunk_id`, và
`parse.json` không bao giờ bị đụng tới. Phía web hiện bản sửa cạnh bản gốc,
không thay thế nó. Đây cũng là quy tắc đã áp cho `verdicts.json` của người
soát — cùng một lý do: dữ liệu nguồn bất biến, mọi lớp phái sinh nằm riêng.

VÌ SAO TIN DỮ LIỆU NÀY LÀ KHÔNG ĐỦ ĐỂ QUYẾT ĐỊNH
────────────────────────────────────────────────
Đo trên 4 tài liệu CCCD đã parse, tỉ lệ dấu **trên riêng những dòng thực sự là
tiếng Việt** (lọc bằng cấu trúc âm tiết, bất biến với mất dấu):

    CCCD 1.jpg      0,202        NH9003 CCCD     0,237
    CCCD.pdf        0,216        CCCD 2.jpg      0,229

Mốc tiếng Việt thật (ground truth MDPBench) là **0,217**. Bốn tài liệu nằm
quanh mốc đó, hai cái còn CAO hơn. Nghĩa là **ADE không mất dấu** — con số
0,144 nhìn thấy khi đo cả bài chỉ là hiệu ứng pha loãng, vì CCCD in song ngữ
Việt–Anh và đầy chữ số.

Mà một model phục hồi dấu đặt lên văn bản đã đủ dấu thì không còn gì để làm,
ngoài việc thêm nhiễu. Đo trước đây trên đầu ra VLM đúng như vậy:

    CER 0,254 → 0,267   (XẤU ĐI 5%)
    CER 0,185 → 0,188   (XẤU ĐI 2%)
    định danh: không đổi ở cả hai

Vì vậy module này được viết để **ĐO TRƯỚC, DÙNG SAU**: `--dry-run` chạy so
sánh trên kho hiện có và in bảng trước/sau, không ghi gì. Chỉ khi bảng đó cho
thấy cải thiện thật mới nên bật ghi.

CỔNG QUYẾT ĐỊNH (không nới cho bất kỳ model nào)
────────────────────────────────────────────────
Giữ lớp sửa CHỈ KHI, đo trên đầu ra engine thật:

    CER giảm rõ rệt   VÀ   định danh giữ ≥ 99%

Một corrector từng đạt 86% định danh và đã bị loại dù cải thiện dấu.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path


__all__ = ["ChunkCorrection", "DocCorrection", "correct_parse",
           "load_corrections", "save_corrections", "should_correct",
           "ACCENT_TARGET", "ACCENT_FLOOR"]

#: Tỉ lệ dấu của tiếng Việt THẬT, đo trên ground truth MDPBench.
ACCENT_TARGET = 0.217

#: Dưới ngưỡng này mới đáng gọi model.
#:
#: 0,60 × mốc: đủ thấp để không đụng vào văn bản vốn đã ổn (4 tài liệu CCCD đo
#: được nằm ở 0,202–0,237, tức là ĐỀU TRÊN ngưỡng và sẽ bị bỏ qua — đúng ý
#: đồ), đủ cao để bắt được trang thật sự mất dấu như đầu ra tesseract (0,080).
ACCENT_FLOOR = ACCENT_TARGET * 0.60


@dataclass
class ChunkCorrection:
    """Bản sửa của MỘT chunk, kèm đủ số liệu để xét có nên nhận hay không."""

    chunk_id: str
    original: str
    corrected: str
    accent_before: float
    accent_after: float
    identifiers_before: list[str]
    identifiers_after: list[str]
    reverted: bool = False
    revert_reason: str = ""

    @property
    def changed(self) -> bool:
        return self.corrected.strip() != self.original.strip()

    @property
    def identifiers_intact(self) -> bool:
        return sorted(self.identifiers_before) == sorted(self.identifiers_after)

    def as_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "original": self.original,
            "corrected": self.corrected,
            "accent_before": round(self.accent_before, 4),
            "accent_after": round(self.accent_after, 4),
            "identifiers_before": self.identifiers_before,
            "identifiers_after": self.identifiers_after,
            "changed": self.changed,
            "reverted": self.reverted,
            "revert_reason": self.revert_reason,
        }


@dataclass
class DocCorrection:
    """Kết quả chồng lớp sửa lên một tài liệu."""

    doc_id: str
    model: str
    chunks: list[ChunkCorrection] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0

    @property
    def n_changed(self) -> int:
        return sum(1 for c in self.chunks if c.changed and not c.reverted)

    @property
    def n_reverted(self) -> int:
        return sum(1 for c in self.chunks if c.reverted)

    @property
    def identifier_preservation(self) -> float:
        """Tỉ lệ định danh sống sót, tính trên TỔNG số định danh.

        Tính theo định danh chứ không theo chunk: một chunk chứa 12 số hiệu mà
        hỏng 1 thì nặng hơn hẳn một chunk chứa 1 số hiệu mà hỏng 1, và cách
        đếm theo chunk gộp hai ca đó làm một.
        """
        total = kept = 0
        for c in self.chunks:
            before = set(c.identifiers_before)
            total += len(before)
            kept += len(before & set(c.identifiers_after))
        return 1.0 if total == 0 else kept / total

    def as_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "model": self.model,
            "n_chunks": len(self.chunks),
            "n_changed": self.n_changed,
            "n_reverted": self.n_reverted,
            "n_skipped": len(self.skipped),
            "identifier_preservation": round(self.identifier_preservation, 4),
            "elapsed_ms": round(self.elapsed_ms, 1),
            "chunks": [c.as_dict() for c in self.chunks],
            "skipped": self.skipped,
        }


def should_correct(text: str, floor: float = ACCENT_FLOOR) -> tuple[bool, str]:
    """Đoạn này có đáng gọi model không? Trả về (có/không, lý do).

    Gate theo MẬT ĐỘ DẤU CỦA CHÍNH ĐOẠN ĐÓ, và chỉ xét trên phần thực sự là
    tiếng Việt. Lý do: mỗi lần gọi model tốn ~0,3 s CPU, và quan trọng hơn —
    đặt một model phục hồi dấu lên văn bản đã đủ dấu thì nó chỉ có thể làm
    hỏng, không thể làm tốt hơn.

    Dòng tiếng Anh trên CCCD song ngữ ("SOCIALIST REPUBLIC OF VIET NAM") có tỉ
    lệ dấu bằng 0 nhưng hoàn toàn đúng. Lọc theo cấu trúc âm tiết trước, nếu
    không thì mọi dòng tiếng Anh đều bị gửi cho model sửa — và model tiếng Việt
    sẽ "sửa" chúng thành thứ gì đó.
    """
    from ocr_lab.language import vietnamese_syllable_share
    from ocr_lab.metrics import accent_share

    lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 8]
    if not lines:
        return False, "quá ngắn"

    vi = [ln for ln in lines if vietnamese_syllable_share(ln) >= 0.45]
    if not vi:
        return False, "không phải tiếng Việt"

    acc = accent_share(" ".join(vi))
    if acc >= floor:
        return False, f"dấu đã đủ ({acc:.3f} ≥ {floor:.3f})"
    return True, f"thiếu dấu ({acc:.3f} < {floor:.3f})"


def _iter_chunks(parse: dict):
    """Duyệt các chunk có `range`, y hệt cách `web/app.js::collectChunks` làm.

    Phải khớp nhau: nếu hai bên duyệt khác nhau thì `chunk_id` trong
    `corrected.json` sẽ không tra được ở giao diện, và bản sửa trở thành dữ
    liệu mồ côi.
    """
    structure = parse.get("structure") or {}

    def walk(node, page):
        g = node.get("grounding") or {}
        pg = g.get("page") or page or 1
        if g.get("box"):
            yield node, g
        for ch in node.get("children") or []:
            yield from walk(ch, pg)

    for page in structure.get("children") or []:
        pg = (page.get("grounding") or {}).get("page") or page.get("page") or 1
        for el in page.get("children") or []:
            yield from walk(el, pg)


def correct_parse(parse: dict, corrector, *, doc_id: str = "",
                  floor: float = ACCENT_FLOOR,
                  force: bool = False) -> DocCorrection:
    """Chồng lớp sửa lên một `parse.json`, KHÔNG đụng vào bản gốc.

    `corrector` là một `PostCorrector` (hoặc bất cứ thứ gì có `.correct_chunk`)
    — tiêm vào thay vì tự dựng, để test chạy được mà không phải nạp model 171
    MB và để đo được với nhiều model khác nhau.

    `force=True` bỏ qua cổng mật độ dấu — chỉ dùng khi đang ĐO xem cổng đặt
    đúng chỗ chưa, không dùng khi chạy thật.
    """
    from ocr_lab.metrics import accent_share, identifiers

    md = parse.get("markdown") or ""
    model_name = getattr(corrector, "model_dir", "")
    out = DocCorrection(doc_id=doc_id, model=str(model_name))
    t0 = time.perf_counter()

    for i, (node, g) in enumerate(_iter_chunks(parse)):
        rng = g.get("range") or {}
        text = md[rng.get("start", 0):rng.get("end", 0)]
        cid = node.get("id") or f"el{i}"

        if not text.strip():
            continue

        if not force:
            ok, why = should_correct(text, floor)
            if not ok:
                out.skipped.append(f"{cid}: {why}")
                continue

        fixed = corrector.correct_chunk(text)

        # TRUNG THỰC TUYỆT ĐỐI VỚI ĐẦU RA MODEL.
        #
        # Ở đây từng có `filter_to_tone_fixes` lọc theo từng từ: nhận bản sửa
        # khi khung xương chữ không đổi, giữ bản gốc khi khác. Nó chặn được
        # `Sęo`→`Sao` và `zen`→`trên`, nhưng đã bị BỎ, vì nó làm hỏng đúng
        # việc mà trang đối chiếu sinh ra để làm:
        #
        #   - Bảng số trở thành "4 sửa / 0 hại" — con số của LỚP LỌC, không
        #     phải của model. Muốn so hai model thì phải đo chính model.
        #   - Lỗi model bị giấu đi, nên không ai biết model tệ ở đâu. Lọc
        #     giỏi che được cả một model tồi.
        #   - Người soát nhìn bản đã lọc và tưởng đó là năng lực model.
        #
        # Quy tắc: kho lưu ĐÚNG cái model trả về. Mọi việc chọn lọc thuộc về
        # bước dùng kết quả về sau, không thuộc bước ghi nhận.
        #
        # `correct_chunk` vẫn giữ hai lớp bảo vệ định danh sẵn có — đó là
        # ràng buộc an toàn dữ liệu khách hàng, không phải sửa lỗi chính tả.

        cc = ChunkCorrection(
            chunk_id=cid,
            original=text,
            corrected=fixed,
            accent_before=accent_share(text),
            accent_after=accent_share(fixed),
            identifiers_before=identifiers(text),
            identifiers_after=identifiers(fixed),
        )

        # `PostCorrector.correct_chunk` đã tự lui về nguyên bản khi làm hỏng
        # định danh. Nhận ra ca đó ở đây để ĐẾM được — tỉ lệ lui cao nghĩa là
        # model đang bị chặn liên tục và phần "sửa" hầu như vô tác dụng, và đó
        # tự nó đã là kết luận.
        if fixed == text and accent_share(text) < floor:
            cc.reverted = True
            cc.revert_reason = "không đổi (có thể đã lui vì hỏng định danh)"

        out.chunks.append(cc)

    out.elapsed_ms = (time.perf_counter() - t0) * 1000
    return out


def save_corrections(store: Path, doc_id: str, result: DocCorrection) -> Path:
    """Ghi vào `corrected.json` — TỆP RIÊNG, không đụng `parse.json`.

    Xem docstring đầu tệp: `parse.json` là dữ liệu nguồn bất biến vì mọi offset
    grounding neo vào nó.
    """
    d = store / doc_id
    d.mkdir(parents=True, exist_ok=True)
    d.chmod(0o700)
    f = d / "corrected.json"
    f.write_text(json.dumps(result.as_dict(), ensure_ascii=False, indent=2),
                 encoding="utf-8")
    f.chmod(0o600)
    return f


def load_corrections(store: Path, doc_id: str) -> dict | None:
    f = store / doc_id / "corrected.json"
    if not f.is_file():
        return None
    return json.loads(f.read_text("utf-8"))
