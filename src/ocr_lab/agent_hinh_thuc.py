"""Agent kiểm hình thức & rút số hiệu — chỉ chạy ở chỗ quyết định cổng.

VÌ SAO PHẢI LÀ AGENT
────────────────────
Ba kiểu lệch giữa tên tệp và nội dung không có luật cứng nào giải được:

  A  tên đạt, hình thức không đạt — sản phẩm bàn giao là ảnh chụp đoạn chat;
     hoặc trạng thái thật nằm ở một dòng ("Số: <Chưa cấp số>"), không ở nhãn
     `(draft)` trên tên.
  B  tên khác chuỗi chuẩn nhưng nghĩa đúng — phiếu thông tin khách đã ký thay
     cho "email phê duyệt".
  C  nhiều số hiệu trong một tài liệu, khác chủ — tài liệu tra cứu PHẢI chứa
     số của người khác; việc là phân giải số nào của hồ sơ ta.

Phải đọc và hiểu. Nhưng không cần đọc nhiều: luật rẻ (`so_anh_xa`,
`so_hinh_thuc`, `so_so_hieu`) lọc trước, agent chỉ đọc vài tài liệu chốt cổng
của một hồ sơ. `scripts/agent_hinh_thuc.py` chọn tài liệu, ghi sổ và ghi
ngược cách gọi mới vào bảng ánh xạ; mô-đun này chỉ dựng lời nhắc, gọi model
và kiểm từng khẳng định.

BỐN RÀNG BUỘC
─────────────
1. Nói gì cũng phải chỉ ra được dòng. Mỗi khẳng định mang `dong` (số dòng
   của nội dung ADE) và `trich` (chép nguyên văn từ chính các dòng đó).
   `kiem_chung` bỏ mọi khẳng định mà trích không nằm trong dòng đã chỉ, số
   hiệu không nằm trong trích, hay ngày không đọc lại được từ trích. Bị bỏ
   thì không vào sổ — "sổ phải ghi kèm nguồn" thành thứ máy kiểm được.
2. Tên tệp là PHỎNG ĐOÁN. Nó vào lời nhắc SAU nội dung, dưới nhãn phỏng
   đoán, và không có số dòng nên không trích được. Nếu không, agent chép lại
   đúng cái lỗi ta đang muốn bắt.
3. Danh sách mục bắt buộc lấy từ bảng ánh xạ (`anh_xa_ten_goi.json`), không
   từ BPMN viết lại. Bước không có trong danh sách thì là "không nhận ra",
   không đoán.
4. Có mức giữa: "Đủ nội dung – sai hình thức" là kết luận hay gặp nhất của
   kho này; ép chọn đạt/không đạt là ép nói dối một chiều.

DỮ LIỆU RỜI MÁY
───────────────
`ClaudeCli` gửi nội dung ADE (đã rời máy một lần, khi ADE đọc) tới Anthropic.
Hằng `GIU_DU_LIEU_TREN_MAY = False` để bên gọi in cờ đó cạnh mọi con số, như
engine OpenAI. Trần số tài liệu mỗi lượt đặt cứng ở script, không ở đây.
"""
from __future__ import annotations

import copy
import html
import json
import re
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass, field
from typing import Callable

LOAI_TAI_LIEU = (
    "bao_cao", "anh_chup_chat", "email", "bien_nhan_co_quan", "ban_in_tra_cuu",
    "bieu_mau", "hop_dong", "hoa_don", "giay_to_tuy_than", "khac",
)
# Cùng khoá với `so_hinh_thuc.MUC`: hai sổ phải đọc chung được một mức.
MUC_HINH_THUC = ("dat", "du_noi_dung_sai_hinh_thuc", "khong_dat")
CHU_SO_HUU = ("ta", "doi_chung", "doi_tac", "chua_ro")
NHAN_NGAY = ("ky", "nop", "cap", "hieu_luc", "het_han", "lap_van_ban", "su_dung_dau", "khac")
DAP_UNG = ("co", "mot_phan", "thieu")
TEN_TEP = ("khop", "lech", "khong_du_can_cu")
DO_CHAC = ("cao", "vua", "thap")
CHUA_CAP_SO = "<Chưa cấp số>"

#: Nội dung dài hơn thì từ chối, không cắt: cắt bớt tài liệu gửi agent mà
#: không báo là lỗi đã gặp (email quyết định bị bỏ, node bị chặn sai).
TRAN_KY_TU = 200_000

GIU_DU_LIEU_TREN_MAY = False

# Chỉ gỡ thẻ HTML thật; "<Chưa cấp số>" trên hoá đơn nháp phải sống sót.
_THE_HTML = re.compile(
    r"</?(?:table|thead|tbody|tr|td|th|br|b|i|u|p|div|span|a|img|sup|sub|ul|ol|li|h\d)\b[^>]*>",
    re.I,
)
_NEO = re.compile(r"<a id=[^>]*></a>|<!--.*?-->")


def _bo_dau(s: str) -> str:
    # `đ` không tách được bằng NFD: phải thay trước (AGENTS.md).
    s = s.replace("Đ", "D").replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def dong_noi_dung(markdown: str) -> dict[int, str]:
    """Số dòng → chữ của dòng, đánh số theo `markdown.split("\\n")`.

    Cùng cách đánh số với `so_so_hieu.trich_dong`, nên "dòng 12" của agent và
    của sổ số hiệu chỉ cùng một chỗ. Ô bảng thành ` | `; dòng rỗng sau khi gỡ
    neo thì bỏ, số dòng giữ nguyên. Thực thể HTML (`&#x27;`) giải SAU khi gỡ
    thẻ: model trích `'`, không trích `&#x27;`.
    """
    ra = {}
    for i, tho in enumerate(markdown.split("\n"), 1):
        s = html.unescape(_THE_HTML.sub(" | ", _NEO.sub("", tho))).replace("**", "")
        s = re.sub(r"(?:\s*\|\s*)+", " | ", s)
        s = re.sub(r"\s+", " ", s).strip(" |")
        if s:
            ra[i] = unicodedata.normalize("NFC", s)
    return ra


# ── Lời nhắc ─────────────────────────────────────────────────────────────

HE_THONG = """Bạn là agent kiểm HÌNH THỨC và rút SỐ HIỆU cho MỘT tài liệu trong hồ sơ \
của một hãng luật sở hữu trí tuệ, tại đúng chỗ cổng tiến độ phải quyết định. \
Bạn đọc nội dung, không đọc tên tệp để kết luận.

ĐẦU VÀO
1. BƯỚC CÓ MỤC BẮT BUỘC — lấy từ bảng ánh xạ. Đây là danh sách bước DUY NHẤT \
được chọn. Mỗi bước: mã hoạt động, tên, khoá (chuỗi chuẩn nguyên văn) và các mục bắt buộc.
2. NỘI DUNG — bản đọc ADE, mỗi dòng dạng `L<số>| <chữ>`. Chỉ các dòng này là nguồn.
3. HỒ SƠ — mã và nhãn hiệu của hồ sơ, cùng sổ số hiệu hiện có (số nào đã biết là của ai).
4. PHỎNG ĐOÁN TỪ TÊN TỆP — tên tệp và thư mục do người lưu đặt, CÓ THỂ SAI. \
Không phải nguồn, không có số dòng, không được trích.

LUẬT
- Mọi khẳng định mang "dong" (danh sách số dòng L) và "trich" (chép NGUYÊN VĂN, \
liền một đoạn, ≤ 200 ký tự, từ chính các dòng đó). Trích vắt qua nhiều dòng thì \
"dong" liệt kê ĐỦ mọi dòng ấy. Không chỉ ra được dòng thì KHÔNG ghi — máy sẽ kiểm \
và bỏ mọi trích không khớp.
- Quyết loại tài liệu và bước từ NỘI DUNG trước, rồi mới so với phỏng đoán tên tệp: \
"khop" (nội dung xác nhận), "lech" (nội dung nói khác — nêu dòng), "khong_du_can_cu". \
Ngày `_ddmmyy` trên tên tệp là ngày người lưu/nhận tệp, không phải ngày của văn bản: \
khác ngày một mình không làm tên tệp "lech".
- Bước: chỉ chọn trong danh sách. Không bước nào hợp → "hoat_dong": null \
("không nhận ra"), nói vì sao. Không đoán bừa.
- Hình thức, ba mức, xét theo mục bắt buộc của bước (không nhận ra bước thì xét \
theo loại thật của tài liệu):
  "dat" — đúng loại văn bản, đủ nội dung, ở trạng thái mục đòi (đã ký, đã phát hành...).
  "du_noi_dung_sai_hinh_thuc" — nội dung cần có đều có, nhưng vật mang sai \
(ảnh chụp đoạn chat thay cho báo cáo, định dạng khác mẫu). Mức này hay gặp nhất; đừng ép.
  "khong_dat" — thiếu nội dung cốt lõi, hoặc chưa có hiệu lực (nháp, chưa cấp số, \
chưa ký nơi mục đòi ký), hoặc sai tài liệu. Trích dòng chứng minh chỗ thiếu \
(ví dụ trường bỏ trống).
- Mục bắt buộc: với bước đã nhận, xét TỪNG mục: "co" / "mot_phan" / "thieu". \
"thieu" cũng phải trích: dòng lộ chỗ trống, hoặc dòng cho thấy tài liệu là thứ khác.
- Số hiệu: mọi số định danh (số đơn, văn bằng, hoá đơn, hợp đồng, mã số thuế, \
tài khoản, điện thoại, giấy tờ tuỳ thân, mã theo dõi...), "loai" lấy trong LOẠI SỐ. \
Không tính số tiền, mã bưu chính, số trang. Chủ sở hữu:
  "ta" — khách hàng hoặc hãng của CHÍNH hồ sơ này;
  "doi_chung" — chủ nhãn bị tra cứu, bị trích dẫn làm đối chứng;
  "doi_tac" — đại diện nước ngoài, nhà cung cấp, cơ quan;
  "chua_ro" — không đủ căn cứ.
  Số USPTO thuộc chủ của trường "Mark" CÙNG bản ghi: Mark trùng nhãn hồ sơ thì là của ta, \
khác thì là đối chứng. Tài liệu tra cứu chứa số của người khác là ĐÚNG mục đích của nó. \
Sổ số hiệu cho biết số nào đã biết là của ta; nội dung nói khác sổ thì ghi rõ trong "ly_do". \
"gia_tri" chép đúng như trong dòng; số chưa cấp thì ghi "<Chưa cấp số>".
- Ngày: mọi ngày có nghĩa pháp lý hay nghiệp vụ, "nhan" lấy trong NHÃN NGÀY, \
"gia_tri" dạng YYYY-MM-DD. Văn bản Hoa Kỳ viết MM/DD/YYYY. `hh:mm`/`hh.mm` trong \
ảnh chat là đồng hồ giao diện, không phải ngày. Thiếu năm thì không bịa năm — bỏ.
- Độ chắc chắn "cao" / "vua" / "thap". "thap" thì chuyển người kiểm, không tự ghi sổ.

CHỈ trả MỘT đối tượng JSON, không lời dẫn, đúng khuôn:
{"loai_tai_lieu": {"gia_tri": "<LOẠI TÀI LIỆU>", "mo_ta": "...", "dong": [1], "trich": "..."},
 "buoc": {"hoat_dong": "<mã>|null", "khoa": "<khoá>|null", "ly_do": "...", "dong": [1], "trich": "..."},
 "ten_tep": {"ket_luan": "khop|lech|khong_du_can_cu", "ly_do": "...", "dong": [1], "trich": "..."},
 "hinh_thuc": {"muc": "dat|du_noi_dung_sai_hinh_thuc|khong_dat", "ly_do": "...", "dong": [1], "trich": "..."},
 "muc_bat_buoc": [{"muc": "<tên mục>", "dap_ung": "co|mot_phan|thieu", "ly_do": "...", "dong": [1], "trich": "..."}],
 "so_hieu": [{"loai": "<LOẠI SỐ>", "gia_tri": "...", "chu_so_huu": "ta|doi_chung|doi_tac|chua_ro", "ly_do": "...", "dong": [1], "trich": "..."}],
 "ngay": [{"nhan": "<NHÃN NGÀY>", "gia_tri": "YYYY-MM-DD", "ly_do": "...", "dong": [1], "trich": "..."}],
 "do_chac": "cao|vua|thap", "ly_do_do_chac": "..."}
"ly_do" viết tiếng Việt, ngắn."""


def dung_loi_nhac(dau_vao: dict) -> tuple[str, str]:
    """(hệ thống, người dùng). `dau_vao`:

        buoc_ung_vien  [{hoat_dong, ten, khoa, muc: [{ten, nguyen_van, trang_thai_bat_buoc, ghi_chu}]}]
        dong           {số dòng: chữ} — từ `dong_noi_dung`
        ho_so          {ma, nhan}
        so_hieu        [{loai, gia_tri, chu_so_huu}] — sổ số hiệu của hồ sơ
        loai_so        danh sách loại số của sổ số hiệu
        ten_tep        đường dẫn trong hồ sơ (phỏng đoán)
    """
    buoc = []
    for b in dau_vao["buoc_ung_vien"]:
        muc = "; ".join(
            f"«{m['ten']}» (chuẩn ghi: {m['nguyen_van']}"
            + (f"; trạng thái bắt buộc: {', '.join(m['trang_thai_bat_buoc'])}" if m.get("trang_thai_bat_buoc") else "")
            + (f"; ghi chú: {', '.join(m['ghi_chu'])}" if m.get("ghi_chu") else "") + ")"
            for m in b["muc"])
        buoc.append(f"- {b['hoat_dong']} · {b['ten']}\n  khoá: {b['khoa']}\n  mục: {muc}")
    so = "\n".join(f"- {s['loai']} {s['gia_tri']} → {s['chu_so_huu']}" for s in dau_vao["so_hieu"]) or "- (trống)"
    noi_dung = "\n".join(f"L{i}| {t}" for i, t in sorted(dau_vao["dong"].items()))
    hs = dau_vao["ho_so"]
    nguoi_dung = (
        "# BƯỚC CÓ MỤC BẮT BUỘC (bảng ánh xạ)\n" + ("\n".join(buoc) or "- (không có)") + "\n\n"
        f"# LOẠI TÀI LIỆU\n{', '.join(LOAI_TAI_LIEU)}\n"
        f"# LOẠI SỐ\n{', '.join(dau_vao['loai_so'])}\n"
        f"# NHÃN NGÀY\n{', '.join(NHAN_NGAY)}\n\n"
        f"# HỒ SƠ\nmã: {hs.get('ma') or '?'} · nhãn hiệu: {hs.get('nhan') or '?'}\n"
        f"sổ số hiệu hiện có:\n{so}\n\n"
        f"# NỘI DUNG\n{noi_dung}\n\n"
        "# PHỎNG ĐOÁN TỪ TÊN TỆP (chưa kiểm — không phải nguồn, không trích)\n"
        f"{dau_vao['ten_tep']}\n"
    )
    return HE_THONG, nguoi_dung


# ── Gọi model ────────────────────────────────────────────────────────────

@dataclass
class PhanHoi:
    van_ban: str
    model: str
    usd: float | None = None
    token: dict = field(default_factory=dict)
    thoi_gian_ms: int | None = None


Goi = Callable[[str, str], PhanHoi]


class LoiGoi(RuntimeError):
    """Model không trả lời được. Thông điệp không mang nội dung tài liệu."""


class ClaudeCli:
    """Gọi `claude -p` một lượt, không công cụ, không MCP, không CLAUDE.md.

    Chạy trong một thư mục trống để không nạp CLAUDE.md và cài đặt của dự
    án; `--setting-sources project` bỏ cài đặt người dùng (hook, plugin). Đo
    trên lời nhắc tổng hợp: phần cố định của một lượt ≈ 574 token vào. Chi phí
    lấy từ `total_cost_usd` mà CLI tự báo, không ước lượng.
    """

    def __init__(self, model: str = "sonnet", *, effort: str | None = None,
                 lenh: str = "claude", het_gio_s: int = 600) -> None:
        self.model, self.effort, self.lenh, self.het_gio_s = model, effort, lenh, het_gio_s

    def __call__(self, he_thong: str, nguoi_dung: str) -> PhanHoi:
        lenh = [self.lenh, "-p", "--output-format", "json", "--model", self.model,
                "--system-prompt", he_thong, "--tools", "", "--strict-mcp-config",
                "--no-session-persistence", "--setting-sources", "project"]
        if self.effort:
            lenh += ["--effort", self.effort]
        cwd = tempfile.mkdtemp(prefix="agent-hinh-thuc-")
        try:
            kq = subprocess.run(lenh, input=nguoi_dung, capture_output=True, text=True,
                                cwd=cwd, timeout=self.het_gio_s)
        except subprocess.TimeoutExpired as e:
            raise LoiGoi(f"claude -p quá {self.het_gio_s}s") from e
        finally:
            shutil.rmtree(cwd, ignore_errors=True)
        if kq.returncode != 0:
            raise LoiGoi(f"claude -p thoát mã {kq.returncode}")
        try:
            d = json.loads(kq.stdout)
        except json.JSONDecodeError as e:
            raise LoiGoi("claude -p không trả JSON") from e
        if d.get("is_error"):
            raise LoiGoi(f"claude -p báo lỗi: {d.get('subtype')} {d.get('api_error_status')}")
        u = d.get("usage") or {}
        model = next(iter(d.get("modelUsage") or {}), self.model)
        return PhanHoi(
            van_ban=d.get("result") or "",
            model=model,
            usd=d.get("total_cost_usd"),
            token={k: u.get(k, 0) for k in ("input_tokens", "output_tokens",
                                            "cache_creation_input_tokens", "cache_read_input_tokens")},
            thoi_gian_ms=d.get("duration_ms"),
        )


def doc_json(van_ban: str) -> dict:
    """Đối tượng JSON đầu tiên trong câu trả lời; chịu được rào ```json."""
    s = van_ban.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", s, re.S)
    if m:
        s = m.group(1)
    dau, cuoi = s.find("{"), s.rfind("}")
    if dau < 0 or cuoi <= dau:
        raise ValueError("không có đối tượng JSON")
    return json.loads(s[dau:cuoi + 1])


# ── Kiểm từng khẳng định ─────────────────────────────────────────────────

def _chuan_trich(s: str) -> str:
    # Bỏ hẳn khoảng trắng, không chỉ gộp: trích vắt hai dòng model hay nối
    # liền ("…RetrievalSTATUS…"), còn dòng thì nối bằng dấu cách.
    s = unicodedata.normalize("NFC", s).replace("**", "").replace("|", " ")
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return re.sub(r"\s+", "", s).casefold()


def _chu_so(s: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", _bo_dau(s).upper())


def _co_trong(trich: str, dong: dict[int, str], so) -> bool:
    """Trích nằm trong các dòng nối theo thứ tự dòng, hoặc theo thứ tự model liệt kê."""
    t = _chuan_trich(trich)
    return any(t in _chuan_trich(" ".join(dong[x] for x in thu_tu)) for thu_tu in (sorted(so), so))


def kiem_trich(kd: dict, dong: dict[int, str]) -> str | None:
    """None nếu trích nằm trong các dòng đã chỉ; ngược lại là lý do bỏ.

    Trích có thật nhưng lệch một dòng (model chỉ dòng 357 cho trích vắt 356–357)
    thì máy neo lại vào đoạn dòng liền nhỏ nhất chứa nó, trong phạm vi ±1 dòng
    quanh các dòng đã chỉ, và giữ số model nói ở `dong_goc`. Trích vẫn được đọc
    lại nguyên văn, nên bảo đảm "có dòng làm bằng" không đổi.
    """
    so = kd.get("dong")
    if not isinstance(so, list) or not so or not all(isinstance(x, int) for x in so):
        return "không chỉ ra dòng"
    thieu = [x for x in so if x not in dong]
    if thieu:
        return f"dòng không có trong nội dung: {thieu}"
    trich = kd.get("trich")
    if not isinstance(trich, str) or not trich.strip():
        return "không có trích"
    if _co_trong(trich, dong, so):
        return None
    quanh = [x for x in sorted(dong) if min(so) - 1 <= x <= max(so) + 1]
    for dai in range(1, len(quanh) + 1):
        for i in range(len(quanh) - dai + 1):
            if _co_trong(trich, dong, quanh[i:i + dai]):
                kd["dong_goc"], kd["dong"] = so, quanh[i:i + dai]
                return None
    return "trích không nằm trong các dòng đã chỉ"


_THANG_EN = {}
for _i, _ten in enumerate(["january", "february", "march", "april", "may", "june", "july",
                           "august", "september", "october", "november", "december"], 1):
    _THANG_EN[_ten] = _THANG_EN[_ten[:3]] = _i
_THANG_EN["sept"] = 9
_RX_THANG_EN = re.compile(r"\b(" + "|".join(sorted(_THANG_EN, key=len, reverse=True)) + r")\b")


def ngay_doc_lai_duoc(iso: str, trich: str) -> bool:
    """Năm, tháng, ngày của `iso` đều đọc lại được từ trích.

    Không phân tích mọi kiểu viết ngày; chỉ chặn ngày bịa: năm (4 hoặc 2 chữ
    số; có năm 4 chữ số trong trích thì phải là nó), ngày (số) và tháng (số, tên tiếng Anh, hoặc `tháng M`) phải có mặt.
    Tên tháng phải đứng thành từ: "Mark" không phải tháng Ba. Không bắt được
    đảo ngày/tháng (`8/10` đọc hai chiều đều qua) — đó là việc của lời nhắc.
    """
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not m:
        return False
    nam, thang, ngay = m.group(1), int(m.group(2)), int(m.group(3))
    t = _bo_dau(trich).lower()
    for c in re.findall(r"(?<!\d)(\d{6}|\d{8})(?!\d)", t):     # ddmmyy / ddmmyyyy dính liền
        if int(c[:2]) == ngay and int(c[2:4]) == thang and c[4:] in (nam, nam[2:]):
            return True
    so = [int(x) for x in re.findall(r"\d+", t)]
    nam_du = re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", t)
    if nam not in nam_du if nam_du else int(nam[2:]) not in so:
        return False
    thang_chu = {_THANG_EN[x] for x in _RX_THANG_EN.findall(t)}
    thang_chu |= {int(x) for x in re.findall(r"thang\s*(\d{1,2})", t)}
    if thang in thang_chu:
        return ngay in so
    return thang in so and ngay in so


def _bo(bi_bo: list, truong: str, kd, ly_do: str) -> None:
    bi_bo.append({"truong": truong, "khang_dinh": kd, "ly_do": ly_do})


def kiem_chung(kq: dict, dong: dict[int, str], buoc_ung_vien: list[dict],
               bang_cua_loai: dict[str, str]) -> dict:
    """Giữ khẳng định có dòng làm bằng, bỏ phần còn lại và nói vì sao.

    Trả bản ghi đã kiểm: mọi trường theo khuôn lời nhắc, cộng `muc_con_thieu`,
    `muc_khong_xet`, `bi_bo`. `bang` / `cong_khai` của số hiệu đọc từ loại số
    qua `bang_cua_loai` của sổ số hiệu — việc đó luật cứng làm được, không để
    model quyết.
    """
    bi_bo: list[dict] = []
    ra: dict = {}

    def mot(truong: str, khoa_gt: str, mien: tuple, can_trich=lambda v: True):
        kd = kq.get(truong)
        if not isinstance(kd, dict):
            _bo(bi_bo, truong, kd, "thiếu trường")
            return None
        v = kd.get(khoa_gt)
        if v not in mien:
            _bo(bi_bo, truong, kd, f"giá trị ngoài miền: {v!r}")
            return None
        if can_trich(v):
            ly = kiem_trich(kd, dong)
            if ly:
                _bo(bi_bo, truong, kd, ly)
                return None
        return kd

    ra["loai_tai_lieu"] = mot("loai_tai_lieu", "gia_tri", LOAI_TAI_LIEU)
    ra["ten_tep"] = mot("ten_tep", "ket_luan", TEN_TEP, lambda v: v != "khong_du_can_cu")
    ra["hinh_thuc"] = mot("hinh_thuc", "muc", MUC_HINH_THUC)

    theo_id = {b["hoat_dong"]: b for b in buoc_ung_vien}
    buoc = kq.get("buoc") if isinstance(kq.get("buoc"), dict) else {}
    hd = buoc.get("hoat_dong")
    ung = None
    if hd in (None, "", "null"):
        ra["buoc"] = {"hoat_dong": None, "khoa": None, "ly_do": buoc.get("ly_do") or "không nhận ra"}
    elif hd not in theo_id:
        _bo(bi_bo, "buoc", buoc, f"bước {hd!r} không có trong bảng ánh xạ")
        ra["buoc"] = {"hoat_dong": None, "khoa": None, "ly_do": "không nhận ra (bước đề xuất bị bỏ)"}
    elif kiem_trich(buoc, dong):
        _bo(bi_bo, "buoc", buoc, kiem_trich(buoc, dong))
        ra["buoc"] = {"hoat_dong": None, "khoa": None, "ly_do": "không nhận ra (bước đề xuất bị bỏ)"}
    else:
        ung = theo_id[hd]
        ra["buoc"] = {**buoc, "khoa": ung["khoa"]}

    ra["muc_bat_buoc"] = []
    ten_muc = [m["ten"] for m in ung["muc"]] if ung else []
    for kd in kq.get("muc_bat_buoc") or []:
        if not ung:
            _bo(bi_bo, "muc_bat_buoc", kd, "không có bước được nhận")
        elif not isinstance(kd, dict) or kd.get("muc") not in ten_muc:
            _bo(bi_bo, "muc_bat_buoc", kd, "mục không thuộc bước đã nhận")
        elif kd.get("dap_ung") not in DAP_UNG:
            _bo(bi_bo, "muc_bat_buoc", kd, f"giá trị ngoài miền: {kd.get('dap_ung')!r}")
        elif (ly := kiem_trich(kd, dong)):
            _bo(bi_bo, "muc_bat_buoc", kd, ly)
        elif any(x["muc"] == kd["muc"] for x in ra["muc_bat_buoc"]):
            _bo(bi_bo, "muc_bat_buoc", kd, "mục nói hai lần")
        else:
            ra["muc_bat_buoc"].append(kd)
    xet = {x["muc"] for x in ra["muc_bat_buoc"]}
    ra["muc_con_thieu"] = [x["muc"] for x in ra["muc_bat_buoc"] if x["dap_ung"] == "thieu"]
    ra["muc_khong_xet"] = [m for m in ten_muc if m not in xet]

    ra["so_hieu"] = []
    for kd in kq.get("so_hieu") or []:
        if not isinstance(kd, dict) or not isinstance(kd.get("gia_tri"), str) or not kd["gia_tri"].strip():
            _bo(bi_bo, "so_hieu", kd, "không có giá trị")
            continue
        if kd.get("chu_so_huu") not in CHU_SO_HUU:
            _bo(bi_bo, "so_hieu", kd, f"chủ ngoài miền: {kd.get('chu_so_huu')!r}")
            continue
        if (ly := kiem_trich(kd, dong)):
            _bo(bi_bo, "so_hieu", kd, ly)
            continue
        gt = kd["gia_tri"].strip()
        if gt != CHUA_CAP_SO and (not _chu_so(gt) or _chu_so(gt) not in _chu_so(kd["trich"])):
            _bo(bi_bo, "so_hieu", kd, "số không nằm trong trích")
            continue
        if gt == CHUA_CAP_SO and CHUA_CAP_SO.casefold() not in kd["trich"].casefold():
            _bo(bi_bo, "so_hieu", kd, "số không nằm trong trích")
            continue
        # Loại lạ: cấm như bảng nhạy cảm cho tới khi người xếp (luật sổ số hiệu).
        bang = bang_cua_loai.get(kd.get("loai"), "chua_xep")
        ra["so_hieu"].append({**kd, "gia_tri": gt, "bang": bang, "cong_khai": bang == "cong_khai"})

    ra["ngay"] = []
    for kd in kq.get("ngay") or []:
        if not isinstance(kd, dict) or kd.get("nhan") not in NHAN_NGAY:
            _bo(bi_bo, "ngay", kd, "nhãn ngày ngoài miền")
        elif (ly := kiem_trich(kd, dong)):
            _bo(bi_bo, "ngay", kd, ly)
        elif not ngay_doc_lai_duoc(kd.get("gia_tri"), kd["trich"]):
            _bo(bi_bo, "ngay", kd, "ngày không đọc lại được từ trích")
        else:
            ra["ngay"].append(kd)

    do_chac = kq.get("do_chac") if kq.get("do_chac") in DO_CHAC else "thap"
    ly_do_chac = kq.get("ly_do_do_chac") or ""
    mat_cot_loi = [t for t in ("loai_tai_lieu", "hinh_thuc") if ra[t] is None]
    if any(b["truong"] == "buoc" for b in bi_bo):
        mat_cot_loi.append("buoc")
    if mat_cot_loi:
        do_chac = "thap"
        ly_do_chac = f"khẳng định cốt lõi bị bỏ: {', '.join(mat_cot_loi)}. " + ly_do_chac
    elif bi_bo and do_chac == "cao":
        do_chac = "vua"
        ly_do_chac = f"{len(bi_bo)} khẳng định bị bỏ. " + ly_do_chac
    ra["do_chac"], ra["ly_do_do_chac"] = do_chac, ly_do_chac.strip()
    ra["bi_bo"] = bi_bo
    return ra


def chay(dau_vao: dict, goi: Goi, bang_cua_loai: dict[str, str]) -> dict:
    """Một tài liệu: dựng lời nhắc, gọi model một lần, kiểm, trả bản ghi."""
    tong = sum(len(t) for t in dau_vao["dong"].values())
    if tong > TRAN_KY_TU:
        return {"loi": f"nội dung {tong} ký tự vượt trần {TRAN_KY_TU} — không cắt, chuyển người",
                "cho_nguoi": True}
    he_thong, nguoi_dung = dung_loi_nhac(dau_vao)
    try:
        ph = goi(he_thong, nguoi_dung)
    except LoiGoi as e:
        return {"loi": str(e), "cho_nguoi": True}
    chi_phi = {"model": ph.model, "usd": ph.usd, "token": ph.token, "thoi_gian_ms": ph.thoi_gian_ms,
               "ky_tu_loi_nhac": len(he_thong) + len(nguoi_dung)}
    try:
        tho = doc_json(ph.van_ban)
    except ValueError as e:
        return {"loi": f"câu trả lời không đọc được: {e}", "cho_nguoi": True,
                "chi_phi": chi_phi, "tra_loi_tho": ph.van_ban}
    kq = kiem_chung(copy.deepcopy(tho), dau_vao["dong"], dau_vao["buoc_ung_vien"], bang_cua_loai)
    kq["chi_phi"] = chi_phi
    kq["tra_loi_tho"] = tho
    kq["cho_nguoi"] = kq["do_chac"] == "thap"
    return kq
