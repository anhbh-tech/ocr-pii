"""Hậu xử lý văn bản OCR bằng model sửa lỗi seq2seq.

CẢNH BÁO TRƯỚC KHI DÙNG: ĐÂY LÀ MODEL SINH CHỮ
──────────────────────────────────────────────
Nó không "sửa" theo nghĩa thay thế có kiểm soát — nó SINH LẠI câu. Nên nó có
thể viết lại số hiệu văn bản, email, ngày tháng. Một model cùng loại (mBART)
từng đạt 86% ở chỉ số `identifier_preservation` và bị LOẠI khỏi dự án này, dù
nó làm tăng tỉ lệ dấu.

protonX tuyên bố "Correction ≠ rewriting, no hallucination". **Tuyên bố không
phải bằng chứng.** Cổng 99% giữ nguyên.

GIỚI HẠN TÁC GIẢ TỰ NÊU — ĐỌC KỸ TRƯỚC KHI KỲ VỌNG
──────────────────────────────────────────────────
* *"Cannot restore missing semantic content"* — chữ nào OCR không đọc ra thì
  model này KHÔNG dựng lại được. Nó chỉ sửa chữ đã có mà sai.
* *"Max sequence length: 256 tokens total (128 cho đầu vào, 128 cho đầu ra)"*
  — chú ý: **128 token đầu vào**, không phải 160 như ghi trong kế hoạch gốc.
* Tác giả cảnh báo ảo giác trên câu dài, nên chunk phải NGẮN.

Hệ quả trực tiếp: model này chỉ giúp được ở loại lỗi "chữ đúng nhưng sai dấu /
sai chính tả". Nó không cứu được trang mà OCR đọc trượt hẳn.

KẾT QUẢ ĐO: MODEL KẸT GIỮA HAI CỰC — KHÔNG DÙNG TRONG PIPELINE NÀY
─────────────────────────────────────────────────────────────────
Trên câu TỰ SOẠN thì nó xuất sắc:

    CER 0,163 → 0,000 · dấu 0,009 → 0,225 · định danh 100% · 0 lần lui

Nhưng trên ĐẦU RA OCR THẬT thì không:

    engine        dấu trước   CER trước → sau     định danh    lui
    tesseract       0,127     0,846 → 0,820  (−3%)  61,4% → 61,4%  88 đoạn
    paddleocr-vl    0,178     0,308 → 0,313  (+2%)  96,2% → 96,2%  29 đoạn

Lý do nằm ở chỗ nó bị kẹt giữa hai cực:

  * OCR TỆ (tesseract, mất >80% ký tự): dấu chỉ còn 0,127, nhưng chữ đã mất
    thì model không dựng lại được — chính tác giả nêu "cannot restore missing
    semantic content". Chỉ cứu được 3% CER.

  * OCR TỐT (VLM): dấu đã đạt 0,178, gần mốc tiếng Việt thật 0,217. protonX
    sinh ra ĐỂ phục hồi dấu, nên khi dấu gần đủ rồi thì nó không còn việc gì
    để làm ngoài gây nhiễu — CER TĂNG 2%.

Trên VLM chỉ 15/136 đoạn (11%) thực sự được sửa và giữ lại; 29 đoạn bị lớp
bảo vệ chặn vì làm hỏng định danh.

BÀI HỌC VỀ CÁCH ĐO: 11 câu tự soạn ban đầu cho kết quả hoàn hảo vì chúng vô
thức được viết giống dữ liệu huấn luyện của model — văn phong hành chính, lỗi
kiểu "mất dấu đều". Đầu ra OCR thật hỏng theo cách khác hẳn: chữ dính nhau, ký
tự lạ, mất nguyên đoạn. **Đừng kết luận về một model sửa lỗi dựa trên ca thử
do chính mình viết ra.**

GIỮ LẠI MODULE NÀY ĐỂ LÀM GÌ: cơ chế che định danh + kiểm-rồi-lui là thứ dùng
lại được cho bất kỳ model sinh chữ nào đặt sau OCR. Và nếu sau này có engine
nhanh mà mất dấu (chưa có), đây là chỗ để cắm vào.

GIẤY PHÉP: v1.3-NC — PHI THƯƠNG MẠI
───────────────────────────────────
§2.3 cho phép dùng nội bộ trong doanh nghiệp và nghiên cứu. §2.2 CẤM bán, cấp
phép lại, cung cấp API có phí, nhúng vào phần mềm có phí, hoặc kiếm tiền trực
tiếp/gián tiếp — những việc đó cần giấy phép thương mại riêng của ProtonX.

Đo đạc và dùng nội bộ thì hợp lệ. Nếu kết quả đủ tốt để đưa vào sản phẩm bán
cho khách thì phải xin giấy phép trước.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Chunk", "chunk_text", "PostCorrector", "CorrectionResult",
           "mask_identifiers", "unmask_identifiers"]

#: Trần đầu vào của model là 128 token. Đặt ngân sách từ thấp hơn hẳn vì
#: tokenizer tiếng Việt sinh nhiều token hơn số từ (dấu tách thành token
#: riêng). Đo thật trên ViT5: ~1,6 token/từ, nên 70 từ ≈ 112 token.
_MAX_WORDS_PER_CHUNK = 70

#: MẶC ĐỊNH TOÀN DỰ ÁN — model teacher 904 MB (v1.3.1), KHÔNG phải nano.
#:
#: Nano 171 MB (4 lớp, d_model 512) từng được dùng nhầm và cho kết quả tệ
#: hơn hẳn khi đo cạnh nhau trên cùng 23 chunk CCCD:
#:
#:                        nano 171MB   teacher 904MB
#:     sửa thanh điệu          3            4
#:     đổi chữ bậy            10            5
#:
#: Teacher sửa đúng `Nới tam` → `Nơi tạm` mà không cần bất kỳ danh sách nhãn
#: biểu mẫu nào, và không bịa `Sex:` → `SexV:` hay `zen` → `trên` như nano.
#: 12 lớp / d_model 768 / ROUGE-L 98,44.
DEFAULT_MODEL_DIR = "models/protonx-legal-tc"

#: Trần token MỖI LẦN gọi model.
#:
#: README của model ghi "256 tokens total (128 cho input, 128 cho output)".
#: Notebook chính thức chia theo TỪ (12 từ/khối), nhưng đo trên bản chép ADE
#: của kho này thì tỉ lệ token/từ là **trung vị 2,0 · p95 13,0 · tệ nhất
#: 28,0** — chữ hỏng OCR vỡ thành rất nhiều token. 12 từ do đó có thể thành
#: 156 token (p95) hoặc 336 (tệ nhất), vượt trần và bị cắt cụt IM LẶNG.
#:
#: Nên trần đặt theo token đo thật, và đặt ở 96 chứ không phải 128: chừa
#: biên an toàn cho câu mà token cuối cùng đội lên bất ngờ.
DEFAULT_MAX_INPUT_TOKENS = 96

#: Notebook dùng `num_beams=4` cho đường chia khối dài (`decode_a_text`) và
#: 10 cho ví dụ câu ngắn. Chọn 4: khối đã nhỏ nên beam rộng không bù nổi chi
#: phí — beam tăng tuyến tính thời gian, mà đây là CPU.
DEFAULT_NUM_BEAMS = 4

#: Điểm cắt ưu tiên giảm dần: hết câu → hết dòng → hết cụm.
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


# ── che định danh ───────────────────────────────────────────────────────────
#
# VÌ SAO CHE: model là model sinh chữ, và nó đọc `thongtinchinhphu@chinhphu.vn`
# như tiếng Việt không dấu rồi "sửa" thành "thống tin chính phủ" — mất luôn
# ký tự `@`. Đo thật: 9/9 ca KHÔNG có email đạt định danh 100%, cả 2 ca có
# email đều vỡ. Thiệt hại tập trung đúng một chỗ, nên bịt được.
#
# CHỌN DẠNG MÃ CHE BẰNG ĐO, KHÔNG ĐOÁN. Thử 7 dạng, xem dạng nào sống sót:
#
#     [EMAIL]        SỐNG
#     XKQZ0          SỐNG
#     <extra_id_0>   CHẾT → "nhằm"     (token đặc biệt của T5 bị model dịch)
#     §0§            CHẾT → "0"
#     @@0@@          CHẾT → "0"
#     {{0}}          CHẾT → "0"
#     \x01           CHẾT → biến mất
#
# `<extra_id_0>` là dạng trông "đúng chuẩn T5" nhất và lại là dạng hỏng —
# đúng kiểu giả định phải đo.
_MASK_RE = re.compile(r"\[ID(\d+)\]")

#: Loại định danh cần che. KHÔNG che số trần và ngày tháng: model sửa chúng
#: đúng (đo được 100% trên ca số tiền, mã hồ sơ, số hiệu), và che tất cả sẽ
#: cắt vụn câu làm model mất ngữ cảnh.
#:
#: Che ĐÚNG thứ model làm hỏng: email, và chuỗi có ký tự `@` hoặc URL.
_FRAGILE_RE = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.-]+"              # email
    r"|https?://\S+|www\.\S+"                 # URL
)


def mask_identifiers(text: str) -> tuple[str, list[str]]:
    """Thay định danh dễ vỡ bằng mã che, trả (văn bản đã che, danh sách gốc).

    Chỉ che email và URL — đo thật cho thấy model xử lý đúng số hiệu văn bản,
    ngày, số tiền, mã hồ sơ (100% trên 9 ca). Che thừa làm câu vụn và model
    mất ngữ cảnh, tức đánh mất chính giá trị của nó.
    """
    saved: list[str] = []

    def _swap(m: re.Match) -> str:
        saved.append(m.group(0))
        return f"[ID{len(saved) - 1}]"

    return _FRAGILE_RE.sub(_swap, text), saved


def unmask_identifiers(text: str, saved: list[str]) -> str:
    """Đặt lại định danh gốc vào chỗ mã che.

    Mã che bị model xoá hoặc đổi số thì phần tương ứng KHÔNG được khôi phục —
    `PostCorrector.correct_chunk` phát hiện điều đó bằng cách kiểm lại và trả
    về nguyên bản thay vì trả một câu thiếu email.
    """
    def _restore(m: re.Match) -> str:
        idx = int(m.group(1))
        return saved[idx] if idx < len(saved) else m.group(0)

    return _MASK_RE.sub(_restore, text)


@dataclass(frozen=True)
class Chunk:
    """Một đoạn đưa vào model, kèm vị trí để ghép lại đúng chỗ."""

    text: str
    start: int      #: chỉ số ký tự trong văn bản gốc
    end: int

    @property
    def words(self) -> int:
        return len(self.text.split())


def chunk_text(text: str, max_words: int = _MAX_WORDS_PER_CHUNK) -> list[Chunk]:
    """Chia văn bản thành đoạn đủ ngắn cho model, cắt ở chỗ tự nhiên.

    VÌ SAO KHÔNG CẮT THEO SỐ TỪ CỐ ĐỊNH: cắt giữa câu làm model mất ngữ cảnh
    và đúng lúc đó nó bắt đầu bịa. Tác giả cảnh báo ảo giác trên câu dài;
    kinh nghiệm ngược lại cũng đúng — câu bị chặt đầu chặt đuôi cũng sinh ảo
    giác.

    Thứ tự cắt: hết câu → hết dòng → cuối cùng mới cắt cứng theo số từ.

    Giữ `start`/`end` để ghép lại đúng vị trí, và để so từng đoạn trước/sau —
    cần cho việc tìm xem model làm hỏng định danh ở đâu.
    """
    if not text.strip():
        return []

    chunks: list[Chunk] = []
    # Tách theo dòng trước: dòng trong tài liệu hành chính thường là một ý.
    for line_match in re.finditer(r"[^\n]+", text):
        line = line_match.group(0)
        base = line_match.start()

        if len(line.split()) <= max_words:
            chunks.append(Chunk(line, base, base + len(line)))
            continue

        # Dòng quá dài: tách theo câu, rồi gộp câu lại cho vừa ngân sách.
        pieces = _SENTENCE_END.split(line)
        buf: list[str] = []
        buf_start = 0
        cursor = 0

        for piece in pieces:
            idx = line.find(piece, cursor)
            cursor = idx + len(piece)
            if not buf:
                buf_start = idx

            if len(" ".join(buf + [piece]).split()) > max_words and buf:
                joined = " ".join(buf)
                chunks.append(Chunk(joined, base + buf_start,
                                    base + buf_start + len(joined)))
                buf, buf_start = [piece], idx
            else:
                buf.append(piece)

            # Một câu đơn lẻ vẫn quá dài ⇒ cắt cứng theo từ. Không còn cách
            # nào tự nhiên hơn, nhưng vẫn phải cắt vì model có trần cứng.
            while len(" ".join(buf).split()) > max_words:
                words = " ".join(buf).split()
                head = " ".join(words[:max_words])
                chunks.append(Chunk(head, base + buf_start,
                                    base + buf_start + len(head)))
                rest = " ".join(words[max_words:])
                buf_start += len(head) + 1
                buf = [rest] if rest else []

        if buf:
            joined = " ".join(buf)
            chunks.append(Chunk(joined, base + buf_start,
                                base + buf_start + len(joined)))

    return chunks


def _strip_marks(s: str) -> str:
    import unicodedata as ud

    s = s.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in ud.normalize("NFD", s)
                   if not ud.combining(c)).lower()


def _same_ignoring_diacritics(before: list[str], after: list[str]) -> bool:
    """Hai danh sách định danh có giống nhau khi bỏ qua dấu không.

    Dùng để phân biệt hai việc mà bộ đo thô gộp làm một:

        `56/2026/ND-CP` → `56/2026/NĐ-CP`   SỬA ĐÚNG, phải chấp nhận
        `info@congty.vn` → `infocongty.vn`  LÀM HỎNG, phải lui

    Không có phép phân biệt này thì cổng chặn phạt cả việc model làm đúng, và
    ta sẽ loại nhầm một model tốt. Đo thật: 2/4 ca "hỏng" ban đầu thực ra là
    model sửa đúng chữ Đ.
    """
    return sorted(_strip_marks(x) for x in before) == \
        sorted(_strip_marks(x) for x in after)


@dataclass
class CorrectionResult:
    """Kết quả sửa, kèm ĐỦ THÔNG TIN ĐỂ TRUY VẾT.

    Không chỉ trả văn bản: phải biết model đã đổi những gì, vì cổng kiểm định
    danh cần chỉ ra chính xác đoạn nào làm mất số hiệu.
    """

    text: str
    original: str
    chunks_total: int
    chunks_changed: int
    elapsed_ms: float
    #: Các đoạn mà model làm THAY ĐỔI định danh — thứ nguy hiểm nhất.
    identifier_damage: list[tuple[str, str]] = field(default_factory=list)

    @property
    def is_safe(self) -> bool:
        """Không đoạn nào làm hỏng định danh."""
        return not self.identifier_damage


class PostCorrector:
    """Bao quanh model sửa lỗi seq2seq của protonX.

    Nạp model một lần cho cả tiến trình (như engine OCR), và bấm giờ ở ngoài
    để so được với chi phí của engine.
    """

    def __init__(self, model_dir: str | Path = DEFAULT_MODEL_DIR, *,
                 max_words: int = _MAX_WORDS_PER_CHUNK,
                 max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS,
                 num_beams: int = DEFAULT_NUM_BEAMS,
                 device: str = "cpu") -> None:
        self.model_dir = Path(model_dir)
        self.max_words = max_words
        #: Trần token cho MỘT lần gọi model. Chia nhỏ theo con số này, không
        #: theo số từ — xem `split_by_tokens` để biết vì sao.
        self.max_input_tokens = max_input_tokens
        #: Tác giả dùng `num_beams=10` trong ví dụ. Beam rộng thì bớt ảo giác
        #: nhưng chậm hơn tuyến tính — đo cả hai khi chọn.
        self.num_beams = num_beams
        #: Mặc định CPU: đích triển khai là NAS không có GPU, nên số đo trên
        #: MPS chỉ để gỡ lỗi.
        self.device = device
        self._tok = None
        self._model = None
        #: Số câu phải chia nhỏ vì vượt trần token. Theo dõi để biết trần
        #: đang đặt có hợp với dữ liệu thật không.
        self._splits = 0
        #: Số đoạn phải trả về nguyên bản vì model làm hỏng định danh. Đây là
        #: chỉ số vận hành quan trọng: nó bằng 0 nghĩa là model an toàn trên
        #: tập này, nó lớn nghĩa là model đang bị chặn liên tục và phần "sửa"
        #: hầu như không có tác dụng.
        self._fallbacks = 0

    def ensure_ready(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        self._tok = self._load_tokenizer()
        self._model = AutoModelForSeq2SeqLM.from_pretrained(
            str(self.model_dir),
            # float32 dứt khoát: bfloat16 trên CPU ARM chậm hơn 540 lần vì
            # không có kernel — bài học đã đo trong dự án này.
            dtype=torch.float32)
        self._model.to(self.device)
        self._model.eval()

    def _load_tokenizer(self):
        """Nạp tokenizer, vòng qua một chỗ không tương thích của model này.

        `tokenizer_config.json` khai `tokenizer_class: T5TokenizerFast`, nhưng
        `tokenizer.json` thực tế là **BPE**, không phải Unigram (định dạng mà
        T5 mặc định dùng). transformers 5.x tin vào phần khai báo nên cố dựng
        Unigram từ vocab kiểu dict và chết với

            TypeError: 'dict' object is not an instance of 'Sequence'
                       while processing 'vocab'

        `PreTrainedTokenizerFast` đọc thẳng `tokenizer.json` và tự nhận đúng
        loại, nên bỏ qua được phần khai báo sai. Giữ nguyên các token đặc biệt
        lấy từ config để `generate()` biết chỗ dừng.
        """
        from transformers import AutoTokenizer, PreTrainedTokenizerFast

        try:
            return AutoTokenizer.from_pretrained(str(self.model_dir))
        except (TypeError, ValueError) as exc:
            tok_file = self.model_dir / "tokenizer.json"
            if not tok_file.exists():
                raise
            import json

            cfg = {}
            cfg_file = self.model_dir / "tokenizer_config.json"
            if cfg_file.exists():
                cfg = json.loads(cfg_file.read_text(encoding="utf-8"))

            self._tokenizer_fallback_reason = str(exc)
            return PreTrainedTokenizerFast(
                tokenizer_file=str(tok_file),
                eos_token=cfg.get("eos_token", "</s>"),
                unk_token=cfg.get("unk_token", "<unk>"),
                pad_token=cfg.get("pad_token", "<pad>"),
                model_max_length=cfg.get("model_max_length", 128))

    def _generate_one(self, text: str) -> str:
        """Sinh cho MỘT khối đã chắc chắn nằm dưới trần token."""
        import torch

        self.ensure_ready()
        inputs = self._tok(text, return_tensors="pt", truncation=True,
                           max_length=self.max_input_tokens).to(self.device)
        with torch.no_grad():
            out = self._model.generate(
                **inputs, num_beams=self.num_beams,
                max_new_tokens=self.max_input_tokens * 2,
                length_penalty=1.0, early_stopping=True,
                pad_token_id=self._tok.pad_token_id,
                eos_token_id=self._tok.eos_token_id)
        return self._tok.decode(out[0], skip_special_tokens=True)

    def split_by_tokens(self, text: str) -> list[str]:
        """Chia câu thành các khối nằm dưới trần token, cắt ở RANH GIỚI TỪ.

        VÌ SAO CHIA THEO TOKEN CHỨ KHÔNG THEO TỪ
        ────────────────────────────────────────
        Notebook của ProtonX chia 12 từ một khối. Trên văn bản sạch thì vừa,
        nhưng đo trên chính bản chép ADE của kho này:

            token/từ   trung vị 2,0   ·   p95 13,0   ·   tệ nhất 28,0

        Chữ hỏng OCR (`Sęo`, `thė`, `ZA0310`) vỡ thành rất nhiều token, nên
        12 từ có thể thành **156 token ở p95 và 336 ở ca tệ nhất** — vượt
        trần 128. Khi đó `truncation=True` cắt cụt IM LẶNG: model trả về một
        câu ngắn hơn, trông vẫn hợp lệ, và phần chữ bị mất không có dấu hiệu
        gì. Đây là kiểu hỏng nguy hiểm nhất trong cả pipeline này.

        Chia theo token đo thật thì trần là trần thật, không phụ thuộc văn
        bản sạch hay bẩn.

        Cắt ở ranh giới TỪ (không cắt giữa từ): cắt giữa từ thì model nhận
        một mẩu chữ cụt và sẽ "sửa" nó thành từ khác hẳn.
        """
        self.ensure_ready()
        words = text.split()
        if not words:
            return []

        out: list[str] = []
        cur: list[str] = []
        for w in words:
            trial = cur + [w]
            n = len(self._tok(" ".join(trial)).input_ids)
            if n > self.max_input_tokens and cur:
                out.append(" ".join(cur))
                cur = [w]
            else:
                cur = trial
        if cur:
            out.append(" ".join(cur))
        return out

    def _generate(self, text: str) -> str:
        """Sinh cho cả câu, tự chia nhỏ khi vượt trần.

        Ghép lại bằng dấu cách theo đúng cách notebook làm — khối được cắt ở
        ranh giới từ nên ghép lại không mất chữ nào.
        """
        blocks = self.split_by_tokens(text)
        if len(blocks) <= 1:
            return self._generate_one(text)
        self._splits += 1
        return " ".join(self._generate_one(b) for b in blocks)

    def correct_chunk(self, text: str) -> str:
        """Sửa một đoạn, với hai lớp bảo vệ định danh.

        LỚP 1 — CHE: email và URL được thay bằng `[IDn]` trước khi đưa vào
        model. Model đọc `thongtinchinhphu@chinhphu.vn` như tiếng Việt không
        dấu và "sửa" thành "thống tin chính phủ", mất luôn ký tự `@`.

        LỚP 2 — KIỂM RỒI LUI: sau khi khôi phục, so lại định danh. Nếu vẫn
        khác, TRẢ VỀ NGUYÊN BẢN chưa sửa.

        Vì sao cần lớp 2 dù đã có lớp 1: che chỉ xử lý được loại hỏng ta ĐÃ
        BIẾT. Lớp 2 chặn cả loại chưa biết. Cái giá của nó là mất phần sửa
        dấu trên đúng đoạn đó — rẻ hơn nhiều so với làm vỡ một số hiệu, vì
        đường lược danh tính phía sau phụ thuộc vào định danh, không phụ
        thuộc vào dấu.

        Nguyên tắc: **không bao giờ tin model, luôn kiểm lại.** "Correction ≠
        rewriting" là tuyên bố của nhà phát hành, không phải bảo đảm.
        """
        from ocr_lab.metrics import identifiers

        masked, saved = mask_identifiers(text)
        fixed = unmask_identifiers(self._generate(masked), saved)

        before, after = identifiers(text), identifiers(fixed)
        if sorted(before) != sorted(after):
            # Cho phép MỘT ngoại lệ có kiểm soát: model phục hồi dấu TRONG
            # định danh là việc đúng (`56/2026/ND-CP` → `56/2026/NĐ-CP`).
            # Nhận diện bằng cách so sau khi gỡ dấu — nếu khung xương giống
            # nhau thì chỉ là dấu được thêm, không phải chữ bị đổi.
            if _same_ignoring_diacritics(before, after):
                return fixed
            self._fallbacks += 1
            return text
        return fixed

    def correct(self, text: str) -> CorrectionResult:
        """Sửa cả văn bản, theo từng đoạn, và ghi lại thiệt hại định danh.

        Ghép lại bằng cách nối các đoạn đã sửa theo thứ tự — không dùng vị trí
        ký tự để chèn, vì độ dài đoạn thay đổi sau khi sửa.
        """
        import time

        from ocr_lab.metrics import identifiers

        self.ensure_ready()
        chunks = chunk_text(text, self.max_words)
        t0 = time.perf_counter()

        out_parts: list[str] = []
        changed = 0
        damage: list[tuple[str, str]] = []

        for ch in chunks:
            fixed = self.correct_chunk(ch.text)
            out_parts.append(fixed)
            if fixed.strip() != ch.text.strip():
                changed += 1
            # So định danh NGAY Ở MỨC ĐOẠN: ở mức toàn trang, một định danh bị
            # đổi có thể trùng khớp tình cờ với định danh khác và ta không
            # thấy. Ở mức đoạn thì chỉ ra được đúng câu gây hỏng.
            before, after = identifiers(ch.text), identifiers(fixed)
            if sorted(before) != sorted(after):
                damage.append((ch.text, fixed))

        elapsed = (time.perf_counter() - t0) * 1000
        return CorrectionResult("\n".join(out_parts), text, len(chunks),
                                changed, elapsed, damage)
