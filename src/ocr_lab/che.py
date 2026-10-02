"""Che thông tin nhạy cảm thẳng lên ảnh trang, dùng box của ADE Pro.

HỌC TỪ ĐÂU
──────────
Đường ống lấy từ HideMyData (mkbula/HideMyData, macOS): văn bản của trang →
tìm vùng nhạy cảm theo vị trí ký tự → đổi vị trí ký tự sang khung trên trang
→ tô đen → dựng lại TỆP MỚI từ ảnh đã tô, nên chữ gốc và lớp text biến mất
chứ không chỉ bị phủ. Họ dùng Apple Vision để có box từng ký tự; ta KHÔNG OCR
lại: `parse_pro.json` đã có sẵn box theo dòng (`atomic_grounding`, `range` là
chỉ số codepoint vào `markdown`) và box theo ô bảng.

Ba chỗ ta khác họ, và vì sao:

1. **Box theo dòng chứ không theo ký tự.** ADE Pro không cho box từng chữ,
   nên vị trí trong dòng đo theo mực trên ảnh trang (`_hop_muc`); không đo
   được mới nội suy theo bề rộng chữ rồi nới thêm. Chấp nhận che rộng hơn
   chứ không hẹp hơn.
2. **Cái gì phải che, và che ở đâu trong chữ, do pii-core quyết.** Cả văn bản
   sạch của tài liệu (`lam_sach(markdown)`) đi qua pii-core một lần, có ngữ
   cảnh cả tài liệu (và cả hồ sơ, khi gọi thư viện `redact_case`); mọi field
   có hành động ≠ KEEP được đổi về vị trí markdown rồi về box. Tệp này không
   có bảng quyết định, bộ dò hay ghi đè riêng: cùng một giá trị thì ảnh, văn
   bản đã che và kho nhận cùng một quyết định.
3. **Ô đen in `replacement` của pii-core** (token hoặc nhãn lớp), không in mã
   hạng mục: ảnh che nối được với văn bản đã che và kho, cùng một mã.

Hình (ảnh người, chữ ký, QR, vân tay, mẫu nhãn dạng hình, logo) không phải
chữ nên pii-core không thấy; ta nhận ra chúng từ cấu trúc ADE và hỏi pii-core
hành động của hạng mục (vắng mặt trong bảng thì REMOVE, như `Policy.action_for`).
Con dấu và chữ ký là phần tử `attestation` của ADE (STAMP / SIGNATURE), cũng
che cả phần tử; field nằm trọn trong nó không cần ô riêng.

Ô che KHÔNG chồng nhau (`_giai_chong`): phần chung thuộc hành động nghiêm hơn
(REMOVE › ANONYMISE › PSEUDONYMISE › KEEP), ô kia bị cắt — KEEP không mở được
ô che, và hai token không in đè lên nhau. Trang scan lệch (`Khung`) thì xoay
thẳng ảnh, đo và cắt trong khung thẳng, rồi trả ô về trang gốc thành tứ giác
nghiêng theo dòng (`Vung.tu_giac`).

Không bản ghi nào ở đây chứa chữ gốc: `che.json` chỉ có trang, box, hạng mục
và token.
"""
from __future__ import annotations

import html
import json
import math
import os
import re
import sys
import unicodedata
from bisect import bisect_left
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

__all__ = ["PiiCoreThieu", "PiiCore", "PiiCoreHttp", "PiiCoreThuVien", "Truong",
           "KetQua", "Dong", "Vung", "Khung", "nap_pii_core", "van_ban", "dong_cua",
           "tim_vung", "nung", "chung_minh", "che_tai_lieu", "che_ho_so",
           "DEFAULT_OUT", "PII_CORE_URL", "PII_CORE_SRC"]

#: Kết quả che. Cùng vùng tin cậy với `~/.private/ade_out`: tệp che rồi vẫn
#: mang bố cục và phần chữ không nhạy cảm của hồ sơ thật.
DEFAULT_OUT = Path.home() / ".private" / "che"

#: `pii-core serve` nghe ở đây (loopback). Token do khoá của tiến trình đó
#: sinh: phải là cùng khoá với lần che văn bản vào kho thì ảnh mới cùng mã.
PII_CORE_URL = "http://127.0.0.1:8813"

#: Mã pii-core đi cùng repo (`pii-core/`). Dùng khi không đặt `PII_CORE_SRC`.
PII_CORE_SRC = Path(__file__).resolve().parents[2] / "pii-core" / "src"


class PiiCoreThieu(RuntimeError):
    """Không hỏi được pii-core — không có quyết định thì không che gì cả."""


# ── nguồn quyết định: pii-core ───────────────────────────────────────────

@dataclass(frozen=True)
class Truong:
    """Một field pii-core trả về. Vị trí là codepoint trong chữ ĐÃ GỬI; không
    mang giá trị gốc, chỉ thứ thay vào (`replacement`)."""
    start: int
    end: int
    category: str | None
    action: str
    replacement: str
    matched_by: str = ""

    @classmethod
    def tu_dict(cls, f: dict[str, Any]) -> Truong:
        return cls(int(f["start"]), int(f["end"]), f.get("category"), str(f["action"]),
                   str(f.get("replacement") or ""), str(f.get("matched_by") or ""))


class PiiCore:
    """Bảng hành động của pii-core + cách hỏi nó các field của từng tài liệu."""

    def __init__(self, bang: dict[str, str], nguon: str):
        self.bang = bang
        self.nguon = nguon

    def hanh_dong(self, category: str) -> str:
        # Như `Policy.action_for`: hạng mục vắng mặt trong bảng là lỗi của dự
        # án, không phải giấy phép công bố — đóng ở REMOVE.
        return self.bang.get(category, "REMOVE")

    def quyet(self, texts: list[str], group: str = "") -> list[list[Truong]]:
        """Field của từng văn bản, cùng thứ tự. `group` là hồ sơ."""
        raise NotImplementedError


class PiiCoreHttp(PiiCore):
    """`pii-core serve` qua HTTP. `/v1/document` không có ngữ cảnh hồ sơ: mỗi
    tài liệu một lần gọi, tên thấy ở tài liệu này không được tìm lại ở tài
    liệu kia. Cần ngữ cảnh hồ sơ thì dùng `PiiCoreThuVien` (`redact_case`)."""

    def __init__(self, url: str = PII_CORE_URL, timeout: float = 120.0):
        self.url = url.rstrip("/")
        self.timeout = timeout
        rows = self._goi("GET", "/v1/decisions").get("decisions") or []
        super().__init__({r["category"]: r["action"] for r in rows}, f"pii-core {self.url}")

    def _goi(self, method: str, path: str, body: dict | None = None) -> dict:
        import urllib.error
        import urllib.request
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.url + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Thân lỗi của pii-core chỉ có thông báo, không có chữ đã gửi.
            raise PiiCoreThieu(f"pii-core {path}: HTTP {exc.code}") from None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise PiiCoreThieu(f"không gọi được pii-core ở {self.url}: {exc}") from None

    def quyet(self, texts: list[str], group: str = "") -> list[list[Truong]]:
        return [[Truong.tu_dict(f) for f in
                 self._goi("POST", "/v1/document", {"text": t, "group": group}).get("fields") or []]
                for t in texts]


class PiiCoreThuVien(PiiCore):
    """Thư viện pii-core trong tiến trình này: `redact_case` cho cả hồ sơ, nên
    tên, nhãn, mã tìm thấy ở một tài liệu được tìm lại ở mọi tài liệu kia."""

    def __init__(self, policy: Any):
        import pii_core
        self._policy = policy
        super().__init__({c: d.action.name for c, d in policy.decisions.items()},
                         f"pii-core {Path(pii_core.__file__).parent}")

    def quyet(self, texts: list[str], group: str = "") -> list[list[Truong]]:
        from pii_core import redact_case
        return [[Truong.tu_dict(f.as_dict()) for f in r.fields]
                for r in redact_case(list(texts), self._policy, group=group)]


def them_duong_pii_core() -> None:
    """Đưa `$PII_CORE_SRC` (vắng thì bản trong repo, `PII_CORE_SRC`) lên
    `sys.path` để `import pii_core` tìm được."""
    src = os.environ.get("PII_CORE_SRC") or str(PII_CORE_SRC)
    if (Path(src) / "pii_core" / "__init__.py").is_file() and src not in sys.path:
        sys.path.insert(0, src)


def _thu_vien() -> PiiCoreThuVien | None:
    """Thư viện pii-core nếu import được (từ `$PII_CORE_SRC`, vắng thì từ
    `pii-core/src` trong repo) VÀ có khoá (`PII_CORE_KEY` /
    `PII_CORE_KEY_FILE`); không thì None."""
    them_duong_pii_core()
    try:
        from pii_core import Policy, Roster
        from pii_core.cli import load_key
    except ImportError:
        return None
    try:
        key = load_key()
    except Exception:                          # noqa: BLE001 — không khoá thì không dùng
        return None
    return PiiCoreThuVien(Policy(key, roster=Roster.load())) if key else None


def nap_pii_core(url: str | None = None) -> PiiCore:
    """`url` / `PII_CORE_URL` → HTTP; không thì thư viện (nếu có cả mã và
    khoá); không thì `pii-core serve` ở cổng mặc định."""
    url = url or os.environ.get("PII_CORE_URL")
    if url:
        return PiiCoreHttp(url)
    lib = _thu_vien()
    if lib is not None:
        return lib
    try:
        return PiiCoreHttp(PII_CORE_URL)
    except PiiCoreThieu as exc:
        raise PiiCoreThieu(
            f"{exc}. Chạy `make pii-core-serve`, hoặc đặt PII_CORE_URL, hoặc "
            "đặt PII_CORE_KEY (thư viện pii-core/src trong repo)") from None


# ── dòng: đơn vị có box ──────────────────────────────────────────────────

@dataclass(frozen=True)
class Dong:
    """Một đoạn chữ có box: một dòng `atomic_grounding` hoặc một ô bảng."""
    page: int            # đánh số từ 1, như `pages/p{n}.jpg`
    start: int           # codepoint trong `markdown`
    end: int
    box: dict[str, float]
    kieu: str            # type của phần tử ADE
    bang: int = -1       # chỉ số bảng (ô bảng), -1 nếu không phải ô
    row: int | None = None
    col: int | None = None


def _trang(g: dict) -> int:
    # `grounding.page` của ADE Pro đếm từ 1, cùng gốc với `pages/p{n}.jpg`
    # (đo: 547/547 bản parse có min = 1, max = page_count). Lệch một ở đây
    # đẩy mọi khung sang trang sau — xem chặn trong `che_tai_lieu`.
    return int(g["page"])


def dong_cua(parse: dict, khung: dict[int, Khung] | None = None) -> list[Dong]:
    """Duỗi cây `structure` thành các dòng có box, theo thứ tự đọc.

    Có `khung` (trang → khung thẳng của trang nghiêng) thì box của dòng ở
    trang đó là box trong khung thẳng (`Khung.dong`), không phải box ADE."""
    out: list[Dong] = []
    so_bang = 0

    def walk(x: Any, bang: int) -> None:
        nonlocal so_bang
        if not isinstance(x, dict):
            return
        t = x.get("type")
        if t == "table":
            bang = so_bang
            so_bang += 1
        g = x.get("grounding")
        atoms = x.get("atomic_grounding")
        if t == "table_cell" and g and g.get("box"):
            r = g["range"]
            out.append(Dong(_trang(g), r["start"], r["end"], g["box"], t,
                            bang, x.get("row"), x.get("col")))
        elif atoms:
            for a in atoms:
                r = a["range"]
                out.append(Dong(_trang(a), r["start"], r["end"], a["box"], t))
        elif t == "scan_code" and g and g.get("box"):
            r = g["range"]
            out.append(Dong(_trang(g), r["start"], r["end"], g["box"], t))
        for c in x.get("children") or []:
            walk(c, bang)

    walk(parse.get("structure") or {}, -1)
    if khung:
        out = [replace(d, box=khung[d.page].dong(d.box)) if d.page in khung else d
               for d in out]
    return out


# ── trang nghiêng: khung thẳng ───────────────────────────────────────────
#
# Bản scan đặt lệch vài độ thì dòng chữ là một đường xiên, còn box dòng của
# ADE là HỘP BAO thẳng của đường xiên ấy (đo trên C4: trang lệch 0,55–1,35°,
# box dòng dài cao 37–47 px trong khi nét chữ suy ra chỉ 27–30 px). Ô che
# thẳng trên hộp bao đó ăn vào góc dòng trên/dưới, còn ô khít theo mực thì
# phải cao bằng cả độ trôi của từ. Bản scan là một phép xoay cứng, nên ta ước
# MỘT góc cho cả trang, xoay ảnh trang về thẳng, đặt mọi box vào khung thẳng,
# đo mực ở đấy như trang thẳng — rồi xoay bốn góc ô che về trang gốc.

#: Góc nhỏ hơn thế (độ), hoặc trôi dưới `_TROI_MIN` px trên dòng dài trung
#: vị, thì coi trang là thẳng: không xoay gì, box y như trước.
_GOC_MIN = 0.2
_TROI_MIN = 2.0


@dataclass(frozen=True)
class Khung:
    """Khung thẳng của một trang: ảnh gốc W×H xoay `goc` độ quanh tâm về
    thẳng, vào một khung W2×H2 đủ rộng để không mất góc nào."""
    goc: float           # độ; dương = dòng chữ đi xuống về phía phải
    W: int
    H: int
    W2: int
    H2: int
    #: Độ dày trung vị (px) của một dòng chữ trong khung thẳng — dùng khi box
    #: ADE không phải hộp bao của dòng xiên (xem `dong`).
    day: float = 0.0
    #: Box dòng ADE (xmin, ymin, xmax, ymax) mà box nắn thẳng để rơi mực
    #: (`_mat_muc`): dòng đó lấy hộp bao trọn box ADE (`bao`), không nắn.
    ca: frozenset[tuple[float, float, float, float]] = frozenset()

    @classmethod
    def tao(cls, goc: float, W: int, H: int, day: float = 0.0) -> Khung:
        c, s = abs(math.cos(math.radians(goc))), abs(math.sin(math.radians(goc)))
        return cls(goc, W, H, math.ceil(W * c + H * s), math.ceil(W * s + H * c), day)

    def _cs(self) -> tuple[float, float]:
        t = math.radians(self.goc)
        return math.cos(t), math.sin(t)

    def toi(self, x: float, y: float) -> tuple[float, float]:
        """Điểm ảnh gốc → điểm ảnh khung thẳng."""
        c, s = self._cs()
        dx, dy = x - self.W / 2, y - self.H / 2
        return c * dx + s * dy + self.W2 / 2, -s * dx + c * dy + self.H2 / 2

    def ve(self, x: float, y: float) -> tuple[float, float]:
        """Điểm ảnh khung thẳng → điểm ảnh gốc."""
        c, s = self._cs()
        dx, dy = x - self.W2 / 2, y - self.H2 / 2
        return c * dx - s * dy + self.W / 2, s * dx + c * dy + self.H / 2

    def xoay(self, g: Any) -> Any:
        """Ảnh xám gốc (mảng) → ảnh xám khung thẳng, nền ngoài trang là trắng."""
        import numpy as np
        from PIL import Image
        c, s = self._cs()
        # AFFINE nhận phép NGƯỢC: điểm (x', y') của ảnh ra lấy từ `ve(x', y')`.
        hs = (c, -s, -c * self.W2 / 2 + s * self.H2 / 2 + self.W / 2,
              s, c, -s * self.W2 / 2 - c * self.H2 / 2 + self.H / 2)
        return np.asarray(Image.fromarray(g).transform(
            (self.W2, self.H2), Image.AFFINE, hs, resample=Image.BICUBIC, fillcolor=255))

    def _chuan(self, x0: float, y0: float, x1: float, y1: float) -> dict[str, float]:
        k = lambda v, n: min(1.0, max(0.0, v / n))  # noqa: E731
        return {"xmin": k(x0, self.W2), "ymin": k(y0, self.H2),
                "xmax": k(x1, self.W2), "ymax": k(y1, self.H2)}

    def _goc4(self, b: dict[str, float], W: float, H: float) -> list[tuple[float, float]]:
        return [(b["xmin"] * W, b["ymin"] * H), (b["xmax"] * W, b["ymin"] * H),
                (b["xmax"] * W, b["ymax"] * H), (b["xmin"] * W, b["ymax"] * H)]

    def bao(self, b: dict[str, float]) -> dict[str, float]:
        """Box ADE (trang gốc) → hộp thẳng BAO TRỌN nó trong khung thẳng. Cho
        cả phần tử (hình, con dấu, QR): ô che xoay về gốc phủ hết box ADE."""
        ps = [self.toi(x, y) for x, y in self._goc4(b, self.W, self.H)]
        return self._chuan(min(p[0] for p in ps), min(p[1] for p in ps),
                           max(p[0] for p in ps), max(p[1] for p in ps))

    def dong(self, b: dict[str, float]) -> dict[str, float]:
        """Box dòng ADE (hộp bao thẳng của một dòng xiên) → box của chính dòng
        đó trong khung thẳng. Hộp bao w×h của hình chữ nhật L×T xoay θ có
        w = L·cosθ + T·sinθ, h = L·sinθ + T·cosθ; giải ra L, T. T suy ra
        mỏng hơn nửa dòng thường của trang thì box ADE không phải hộp bao:
        lấy độ dày dòng thường (`day`). Nới thêm 20% để dấu tách rời chữ vẫn
        nằm trong box (xem `_hop_muc`): T giải từ hai đầu dòng, mũ của Ệ giữa
        dòng cao hơn thế (DejaVu: 5% lộ mũ, cần ≥ 13%)."""
        if _khoa(b) in self.ca:
            return self.bao(b)
        x0, y0 = b["xmin"] * self.W, b["ymin"] * self.H
        x1, y1 = b["xmax"] * self.W, b["ymax"] * self.H
        w, h = x1 - x0, y1 - y0
        c, s = abs(math.cos(math.radians(self.goc))), abs(math.sin(math.radians(self.goc)))
        m = c * c - s * s
        L = max((w * c - h * s) / m, 0.6 * w)
        T = (h * c - w * s) / m
        if T < 0.5 * self.day:
            T = min(self.day, h)
        T = max(T, 1.0)
        nx, ny = 1.0, max(1.0, 0.2 * T)
        cx, cy = self.toi((x0 + x1) / 2, (y0 + y1) / 2)
        return self._chuan(cx - L / 2 - nx, cy - T / 2 - ny, cx + L / 2 + nx, cy + T / 2 + ny)

    def ve_hop(self, b: dict[str, float]) -> tuple[dict[str, float], tuple[tuple[float, float], ...]]:
        """Box khung thẳng → (hộp bao trên trang gốc, bốn góc trên trang gốc:
        trên-trái, trên-phải, dưới-phải, dưới-trái), chuẩn hoá [0, 1]."""
        k = lambda v: float(min(1.0, max(0.0, v)))  # noqa: E731
        ps = tuple((k(x / self.W), k(y / self.H)) for x, y in
                   (self.ve(x, y) for x, y in self._goc4(b, self.W2, self.H2)))
        return ({"xmin": min(p[0] for p in ps), "ymin": min(p[1] for p in ps),
                 "xmax": max(p[0] for p in ps), "ymax": max(p[1] for p in ps)}, ps)


#: Phần tử không mang dòng chữ theo hướng trang: không dùng để ước góc.
_KHONG_UOC_GOC = ("attestation", "figure", "logo", "scan_code", "table_cell")
#: Phần tử che cả box: không cần nắn, không kiểm mực rơi.
_CA_PHAN_TU = ("attestation", "figure", "logo", "scan_code")


def _khoa(b: dict[str, float]) -> tuple[float, float, float, float]:
    return b["xmin"], b["ymin"], b["xmax"], b["ymax"]


def _mat_muc(g: Any, k: Khung, hop: list[dict[str, float]]
             ) -> frozenset[tuple[float, float, float, float]] | None:
    """Box nắn thẳng có giữ được mực của box ADE không. Mực trong box ADE mà
    nằm ngoài MỌI box nắn là mực không dòng nào che được nữa. Trả các box
    ADE rơi quá 0,5% mực của nó (dòng đó sẽ không nắn), hoặc None khi hơn
    một phần tư số dòng rơi quá 2% — góc sai hay box ADE không phải hộp bao
    của dòng xiên: bỏ khung, để trang thẳng như cũ. Đo trên C4: 33 trang
    lệch đúng góc rơi tối đa 3,3% ở một dòng; 2 trang ước sai góc rơi quá
    2% ở 4–5 trên 9 dòng."""
    import numpy as np
    from PIL import Image, ImageDraw
    from .ade_store import box_to_pixels
    H, W = g.shape
    muc = g < _nguong_muc(g)
    mn = Image.new("L", (W, H), 0)
    dr = ImageDraw.Draw(mn)
    for b in hop:
        _, q = k.ve_hop(k.dong(b))
        dr.polygon([(x * W, y * H) for x, y in q], fill=255)
    phu = np.asarray(mn) > 0
    roi: set[tuple[float, float, float, float]] = set()
    do = nhieu = 0
    for b in hop:
        x0, y0, x1, y1 = box_to_pixels(b, width=W, height=H)
        m = muc[y0:y1, x0:x1]
        tong = int(m.sum())
        if tong < 20:
            continue
        do += 1
        ti = int((m & ~phu[y0:y1, x0:x1]).sum()) / tong
        if ti > 0.005:
            roi.add(_khoa(b))
        nhieu += ti > 0.02
    return None if 4 * nhieu > do else frozenset(roi)


def _nguong_muc(g: Any) -> int:
    """Ngưỡng mực của một vùng xám: như `_cum_dong` — nền là màu sáng phổ
    biến nhất, mực tối hơn nền ít nhất max(40, nền/4)."""
    import numpy as np
    hist = np.bincount(g.ravel() // 8, minlength=32)
    hist[:15] = 0
    nen = int(hist.argmax()) * 8 + 4
    return nen - max(40, nen // 4)


def _goc_trang(g: Any, hop: list[tuple[int, int, int, int]]) -> tuple[float, float]:
    """(góc nghiêng theo độ, độ dày dòng trung vị theo px) của trang, đo trên
    mực trong các box dòng chữ DÀI.

    Chiếu mực theo từng góc trong ±5°: đúng góc thì mỗi dòng dồn vào ít hàng
    nhất, tổng bình phương cao nhất. Chỉ tính mực trong box dòng chữ, không
    tính hình hay bảng. Trả (0, 0) khi không đủ dòng để tin, góc quá nhỏ,
    hoặc box ADE không phải hộp bao của dòng xiên (xoay theo nó sẽ cắt chữ)."""
    import numpy as np
    dai = [(x0, y0, x1, y1) for x0, y0, x1, y1 in hop
           if y1 - y0 >= 4 and x1 - x0 >= 4 * (y1 - y0)]
    if len(dai) < 3:
        return 0.0, 0.0
    nguong = _nguong_muc(g)
    ys_, xs_ = [], []
    for x0, y0, x1, y1 in dai:
        yy, xx = np.nonzero(g[y0:y1, x0:x1] < nguong)
        ys_.append(yy + y0)
        xs_.append(xx + x0)
    ys, xs = np.concatenate(ys_).astype(float), np.concatenate(xs_).astype(float)
    if ys.size < 200:
        return 0.0, 0.0
    if ys.size > 100_000:
        k = np.linspace(0, ys.size - 1, 100_000).astype(int)
        ys, xs = ys[k], xs[k]

    def diem(a: float) -> float:
        v = np.round(ys - xs * math.tan(math.radians(a))).astype(np.int64)
        return float((np.bincount(v - v.min()).astype(float) ** 2).sum())
    tho = max(np.arange(-5.0, 5.001, 0.25), key=diem)
    goc = round(float(max(np.arange(tho - 0.25, tho + 0.2501, 0.05), key=diem)), 2)
    rong = sorted(x1 - x0 for x0, _, x1, _ in dai)[len(dai) // 2]
    if abs(goc) < _GOC_MIN or rong * math.tan(math.radians(abs(goc))) < _TROI_MIN:
        return 0.0, 0.0
    c, s = math.cos(math.radians(abs(goc))), math.sin(math.radians(abs(goc)))
    T = [(((y1 - y0) * c - (x1 - x0) * s) / (c * c - s * s), y1 - y0) for x0, y0, x1, y1 in dai]
    if 3 * sum(t > 0.3 * h for t, h in T) < 2 * len(T):
        return 0.0, 0.0
    return goc, sorted(t for t, _ in T)[len(T) // 2]


# ── chữ sạch, kèm bản đồ vị trí về chữ gốc ───────────────────────────────

#: Chỉ thẻ thật: `<tom@x.com>`, `<https://…>` trong thư là chữ, bỏ đi thì
#: email mất và nội suy cả dòng lệch.
_MARKUP = re.compile(r"</?[a-zA-Z][a-zA-Z0-9]*(?:\s[^<>]*)?/?>|<!--.*?-->"
                     r"|&(?:#x?[0-9a-fA-F]+|[a-zA-Z]+);|\*\*")


def lam_sach(raw: str) -> tuple[str, list[int]]:
    """Bỏ thẻ HTML và `**`, giải entity; trả chữ sạch và vị trí gốc từng ký tự.

    Cùng ý với `OCRNormalizer` của HideMyData: mẫu chạy trên chữ sạch, còn
    box nội suy theo chữ gốc — nên phải giữ đường về.
    """
    chu: list[str] = []
    map_: list[int] = []
    i = 0
    for m in _MARKUP.finditer(raw):
        for k in range(i, m.start()):
            chu.append(raw[k]); map_.append(k)
        tok = m.group(0)
        if tok.startswith("&"):
            for c in html.unescape(tok):
                chu.append(c); map_.append(m.start())
        elif tok.startswith("<") and chu and not chu[-1].isspace():
            # Thẻ giữa hai từ ngăn cách chúng; bỏ thẻ mà không chèn cách
            # thì "Tên</td><td>Nguyễn" dính thành một từ.
            chu.append(" "); map_.append(m.start())
        i = m.end()
    for k in range(i, len(raw)):
        chu.append(raw[k]); map_.append(k)
    return "".join(chu), map_


# ── hình: ADE thay bằng mô tả, hoặc là phần tử hình riêng ─────────────────

#: Chỗ ADE Pro thay HÌNH bằng một dòng mô tả trong ngoặc vuông, box của dòng
#: là box của hình: che cả box. Hành động theo bảng pii-core (vắng thì REMOVE).
_HINH: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("FACE_PHOTO", re.compile(
        r"\[\s*(?:profile[ _]?(?:picture|photo|image)|(?:user|holder|card[ _]?holder)[ _]photo|avatar|portrait|headshot"
        r"|(?:photo|picture|image)[ _]of[ _](?:a[ _])?(?:man|woman|person|people|face|child|boy|girl)"
        r"|face[ _]photo|id[ _]photo|ảnh[ _](?:đại[ _]diện|chân[ _]dung|thẻ))[^\]]*\]", re.IGNORECASE)),
    ("SIGNATURE", re.compile(
        r"\[\s*(?:(?:handwritten|illegible|hand[ _]drawn)[ _])?signature[^\]]*\]"
        r"|\[\s*chữ[ _]ký[^\]]*\]", re.IGNORECASE)),
    ("SCAN_CODE", re.compile(r"\[\s*(?:qr|bar)[ _]?code[^\]]*\]", re.IGNORECASE)),
    ("FINGERPRINT", re.compile(r"\[\s*(?:[a-z_ ]*[ _])?fingerprint[^\]]*\]|\[\s*vân[ _]tay[^\]]*\]",
                               re.IGNORECASE)),
)

#: Phần tử hình riêng của ADE. Mẫu nhãn dạng hình và logo chỉ ra khách qua sổ
#: đăng bạ như tên nhãn dạng chữ: che cả phần tử (MARK_IMAGE) trên mọi bản
#: che; so hình chỉ chạy tại máy, trên bản gốc.
_PHAN_TU_HINH = ("figure", "logo")

#: Phần tử `attestation` của ADE: con dấu, dấu nổi, chữ ký (kèm dấu) — đo trên
#: kho: 569 phần tử ở 188 tài liệu. Con dấu in tên tổ chức, và cả con dấu lẫn
#: chữ ký đủ để giả văn bản: che cả phần tử như hình. ADE tả chữ ký bằng
#: "[Signed…]"/"[E-signed…]", con dấu bằng "[Stamped…]"/"[Sealed…]" hay chữ
#: OCR của dấu. pii-core chưa có hạng mục con dấu: STAMP vắng trong bảng nên
#: đóng ở REMOVE, như mọi hạng mục vắng (`PiiCore.hanh_dong`).
_CHUNG_THUC = "attestation"
_KY = re.compile(r"\s*\[\s*(?:(?:e-?)?sign|chữ[ _]ký)", re.IGNORECASE)


@dataclass(frozen=True)
class Vung:
    page: int
    #: Hộp bao thẳng trên trang gốc, [0, 1]. Có `tu_giac` thì ô che là tứ
    #: giác đó (trang nghiêng), còn `box` chỉ là hộp bao của nó.
    box: dict[str, float]
    code: str
    action: str
    luat: str            # "pii_core" | "ma_quet" | "hinh" | "hinh_ade" | "chung_thuc"
    #: Box lấy từ đâu: "muc" = đo mực trên ảnh trang (khít), "noi_suy" =
    #: đoán theo bề rộng chữ (nới 1 ký tự bù sai số), "dong" = cả box ADE.
    dinh_vi: str = "dong"
    #: Chữ in lên ô đen: `replacement` của pii-core (token, nhãn lớp).
    thay: str = ""
    #: Bốn góc ô che trên trang gốc (trên-trái, trên-phải, dưới-phải,
    #: dưới-trái), [0, 1] — chỉ khi trang nghiêng; None thì ô che là `box`.
    tu_giac: tuple[tuple[float, float], ...] | None = None
    #: Mảnh này mang nhãn của vùng. Một vùng bị vùng nghiêm hơn cắt thành
    #: nhiều mảnh thì chỉ mảnh lớn nhất in token (`_giai_chong`).
    nhan: bool = True


def _rong(c: str) -> float:
    """Bề rộng tương đối của một ký tự trong font có chân/không chân thường gặp.

    Chia đều theo số ký tự thì một dòng nhiều chữ hoa phía trước làm mọi ô
    phía sau lệch sang trái — đo trên thư tín thật: đuôi tên còn lộ 2 chữ.
    """
    if c.isspace() or c in ".,:;'|!()[]\"`":
        return 0.33
    if c in "iljtfrI":
        return 0.4
    if c in "mwMW":
        return 1.45
    if c.isupper():
        return 1.25
    return 1.0


def _hop_con(line: Dong, chu: str, s: int, e: int) -> dict[str, float]:
    """Box của đoạn [s, e) của chữ SẠCH `chu` trong dòng, nội suy theo bề rộng.

    Nội suy trên chữ sạch chứ không trên markdown thô: `**`, thẻ HTML không
    hiện trên trang, đếm chúng là đẩy box lệch. Đoạn nới ra tới biên từ rồi
    thêm một ký tự mỗi bên: che thừa nửa chữ bên cạnh rẻ hơn lộ đuôi tên.
    """
    while s > 0 and chu[s - 1].isalnum():
        s -= 1
    while e < len(chu) and chu[e].isalnum():
        e += 1
    dau = len(chu) - len(chu.lstrip())
    cuoi = len(chu.rstrip())
    w_ = [_rong(c) for c in chu[dau:cuoi]] or [1.0]
    tong = sum(w_)
    tich = [0.0]
    for x in w_:
        tich.append(tich[-1] + x)
    s, e = min(max(s - dau, 0), len(w_)), min(max(e - dau, 0), len(w_))
    b = line.box
    w = b["xmax"] - b["xmin"]
    char = w / max(len(w_), 1)
    x0 = b["xmin"] + w * tich[s] / tong - char
    x1 = b["xmin"] + w * tich[e] / tong + char
    h = b["ymax"] - b["ymin"]
    return {"xmin": max(0.0, x0), "ymin": max(0.0, b["ymin"] - 0.1 * h),
            "xmax": min(1.0, x1), "ymax": min(1.0, b["ymax"] + 0.1 * h)}


# ── đo mực: box khít theo chữ thật trên ảnh trang ─────────────────────────
#
# Nội suy theo số ký tự phải nới rộng để bù sai số, và nới thì ô che nuốt cả
# chữ bên cạnh — không dùng được khi thứ cần che chỉ là một con số giữa câu.
# Ảnh trang thì có sẵn: trong box DÒNG của ADE, cột nào có mực là cột có chữ,
# khe trắng rộng là khoảng cách giữa hai từ. Khớp các cụm mực đó với các từ
# của chữ là biết từng từ nằm ở điểm ảnh nào.

class AnhTrang:
    """Ảnh trang xám, nạp lười và giữ lại cho mọi dòng của cùng trang.

    Trang có trong `khung` (đã `dat_khung`) thì `lay` trả ảnh ĐÃ XOAY THẲNG:
    box của dòng trang đó cũng ở khung thẳng, nên mọi phép đo mực bên dưới
    chạy y như trên trang thẳng."""

    def __init__(self, trang: dict[int, Path] | None):
        self._p = trang or {}
        self._g: dict[int, Any] = {}
        self._c: dict[int, Any] = {}
        self.khung: dict[int, Khung] = {}

    def goc(self, n: int) -> Any:
        """Ảnh gốc, chưa xoay."""
        if n not in self._g:
            import numpy as np
            from PIL import Image
            f = self._p.get(n)
            self._g[n] = np.asarray(Image.open(f).convert("L")) if f else None
        return self._g[n]

    def lay(self, n: int) -> Any:
        if n not in self._c:
            g = self.goc(n)
            self._c[n] = self.khung[n].xoay(g) if g is not None and n in self.khung else g
        return self._c[n]

    def dat_khung(self, dongs: list[Dong]) -> dict[int, Khung]:
        """Ước góc từng trang từ box dòng chữ (trang gốc) và mực; trang lệch
        đủ để đáng kể thì có khung thẳng."""
        from .ade_store import box_to_pixels
        for n in sorted(self._p):
            g = self.goc(n)
            if g is None:
                continue
            H, W = g.shape
            hop = [box_to_pixels(d.box, width=W, height=H) for d in dongs
                   if d.page == n and d.bang < 0 and d.kieu not in _KHONG_UOC_GOC]
            goc, day = _goc_trang(g, hop)
            if not goc:
                continue
            k = Khung.tao(goc, W, H, day)
            roi = _mat_muc(g, k, [d.box for d in dongs
                                  if d.page == n and d.kieu not in _CA_PHAN_TU])
            if roi is None:
                continue
            self.khung[n] = replace(k, ca=roi)
            self._c.pop(n, None)
        return self.khung


def _cum_muc(cot: Any, khe: int) -> list[tuple[int, int]]:
    """Các cụm cột có mực [a, b), tách ở chỗ có >= `khe` cột trắng liền nhau."""
    import numpy as np
    xs = np.flatnonzero(cot)
    if not xs.size:
        return []
    out, a, b = [], int(xs[0]), int(xs[0])
    for x in xs[1:]:
        x = int(x)
        if x - b - 1 >= khe:
            out.append((a, b + 1))
            a = x
        b = x
    out.append((a, b + 1))
    return out


def _khop_tu(ww: list[float], seg: list[tuple[int, int]]) -> list[tuple[float, float]] | None:
    r = _khop_tu_gia(ww, seg)
    return r[1] if r else None


def _khop_tu_gia(ww: list[float], seg: list[tuple[int, int]]
                 ) -> tuple[float, list[tuple[float, float]]] | None:
    """Gán mỗi từ (trọng số bề rộng `ww`) một khoảng điểm ảnh từ các cụm mực.

    Quy hoạch động đơn điệu: một từ ăn 1–4 cụm (chữ có khe bên trong, như
    "L A W"), hoặc 2–4 từ chung một cụm (khe quá hẹp nên không tách được) —
    khi đó chia cụm theo trọng số. Giá = lệch tỉ lệ bề rộng. Lệch quá thì
    trả None: khớp sai một từ là che trúng từ bên cạnh và để lộ từ cần che.
    """
    n, m = len(ww), len(seg)
    if not n or not m:
        return None
    tw = sum(ww) or 1.0
    sw = [b - a for a, b in seg]
    ts = sum(sw) or 1
    pw = [w / tw for w in ww]
    ps = [w / ts for w in sw]
    INF = float("inf")
    dp = [[INF] * (m + 1) for _ in range(n + 1)]
    bk: list[list[tuple[int, int] | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            if dp[i][j] == INF:
                continue
            for k in range(1, 5):              # 1 từ ↔ k cụm
                if i + 1 <= n and j + k <= m:
                    c = dp[i][j] + abs(pw[i] - sum(ps[j:j + k])) + 0.01 * (k - 1)
                    if c < dp[i + 1][j + k]:
                        dp[i + 1][j + k], bk[i + 1][j + k] = c, (1, k)
            for k in range(2, 5):              # k từ ↔ 1 cụm
                if i + k <= n and j + 1 <= m:
                    c = dp[i][j] + abs(sum(pw[i:i + k]) - ps[j]) + 0.01 * (k - 1)
                    if c < dp[i + k][j + 1]:
                        dp[i + k][j + 1], bk[i + k][j + 1] = c, (k, 1)
    if dp[n][m] == INF or dp[n][m] > 0.15:
        return None
    out: list[tuple[float, float]] = [(0.0, 0.0)] * n
    i, j = n, m
    while i or j:
        a, b = bk[i][j]  # type: ignore[misc]
        if a == 1:
            out[i - 1] = (seg[j - b][0], seg[j - 1][1])
        else:
            x0, x1 = seg[j - 1]
            ws = ww[i - a:i]
            t, acc = sum(ws) or 1.0, 0.0
            for q, w in enumerate(ws):
                out[i - a + q] = (x0 + (x1 - x0) * acc / t, x0 + (x1 - x0) * (acc + w) / t)
                acc += w
        i, j = i - a, j - b
    return dp[n][m], out


def _cum_dong(line: Dong, anh: AnhTrang) -> tuple[Any, int, list[tuple[int, int]], int] | None:
    """Đo mực trong box dòng: (mặt nạ mực của box, màu nền, cụm cột, cao box)."""
    import numpy as np
    from .ade_store import box_to_pixels
    g = anh.lay(line.page)
    if g is None:
        return None
    H, W = g.shape
    lx0, ly0, lx1, ly1 = box_to_pixels(line.box, width=W, height=H)
    if lx1 - lx0 < 4 or ly1 - ly0 < 4:
        return None
    o = g[ly0:ly1, lx0:lx1].astype(np.int16)
    # Màu nền = màu PHỔ BIẾN nhất trong box, không phải màu sáng nhất: ngày
    # trong ảnh chat nằm trên "viên" xám giữa nền trắng, lấy màu sáng làm nền
    # thì cả viên xám thành mực và ô che phủ nguyên viên (thấy trên ảnh chat).
    # Chỉ xét màu sáng (≥ 120): chữ đậm, to có thể chiếm quá nửa box.
    hist = np.bincount(o.ravel() // 8, minlength=32)
    hist[:15] = 0
    if hist.sum() < 0.2 * o.size:
        return None                            # chữ sáng trên nền tối: không đo
    nen = int(hist.argmax()) * 8 + 4
    muc = o < nen - max(40, nen // 4)
    h = ly1 - ly0
    # Gạch chân, đường kẻ ô: một vệt mực liền dài hơn 3 lần cao dòng thì không
    # phải chữ. Để lại thì mọi cột có mực, cả dòng thành một cụm, không khớp được.
    # Vệt phải mảnh (≤ 20% cao box): khối mực đặc là chữ đậm/ô tô sẵn.
    ke = []
    for y in np.flatnonzero(muc.sum(axis=1) > 3 * h):
        r = np.diff(np.concatenate(([0], muc[y].view(np.int8), [0])))
        if (np.flatnonzero(r == -1) - np.flatnonzero(r == 1)).max() > 3 * h:
            ke.append(y)
    nhom: list[list[int]] = []
    for y in ke:
        if nhom and y == nhom[-1][-1] + 1:
            nhom[-1].append(int(y))
        else:
            nhom.append([int(y)])
    for n_ in nhom:
        if len(n_) <= max(2, 0.2 * h):
            muc[n_] = False
    if h >= 40:                                # ô nhiều dòng: bỏ cả kẻ dọc
        muc[:, muc.sum(axis=0) >= 0.9 * h] = False
    cot = muc.sum(axis=0) >= 2                 # 1 điểm lẻ là bụi scan
    return muc, nen, _cum_muc(cot, khe=max(2, round(0.2 * h))), h


def _do_dong(line: Dong, chu: str, anh: AnhTrang) -> tuple[float, float] | None:
    """Chữ `chu` khớp mực trong box dòng tới đâu: (giá khớp từ, tỉ lệ rộng/cao).

    Tỉ lệ = bề rộng mực / (bề rộng chữ ước theo `_rong` × chiều cao mực). Trên
    một tài liệu nó gần như hằng; box gán nhầm chữ của dòng khác lệch hẳn."""
    import numpy as np
    c = _cum_dong(line, anh)
    t = chu.strip()
    if c is None or not t:
        return None
    muc, _, seg, _ = c
    tu = re.findall(r"\S+", t)
    r = _khop_tu_gia([sum(_rong(x) for x in w) or 1.0 for w in tu], seg)
    hang = np.flatnonzero(muc.sum(axis=1) >= 1)
    if r is None or not hang.size:
        return None
    cao = int(hang[-1] - hang[0] + 1)
    return r[0], (seg[-1][1] - seg[0][0]) / (sum(_rong(x) for x in t) * cao)


def _hop_muc(line: Dong, chu: str, s: int, e: int, anh: AnhTrang) -> dict[str, float] | None:
    """Box khít của đoạn [s, e) theo mực trên ảnh trang; None nếu không đo được."""
    import numpy as np
    from .ade_store import box_to_pixels
    c = _cum_dong(line, anh)
    if c is None:
        return None
    g = anh.lay(line.page)
    H, W = g.shape
    lx0, ly0, lx1, ly1 = box_to_pixels(line.box, width=W, height=H)
    _, nen, seg, h = c
    tu = [(mm.start(), mm.end()) for mm in re.finditer(r"\S+", chu)]
    ww = [sum(_rong(c) for c in chu[a:b]) or 1.0 for a, b in tu]
    x_tu = _khop_tu(ww, seg)
    if x_tu is None:
        return None

    def x_tai(p: int, cuoi: bool) -> float | None:
        for (a, b), (xa, xb) in zip(tu, x_tu):
            if a <= p < b or (cuoi and a < p <= b):
                dw = sum(_rong(c) for c in chu[a:b]) or 1.0
                return xa + (xb - xa) * sum(_rong(c) for c in chu[a:p]) / dw
        return None

    # Đầu đoạn rơi vào khoảng trắng thì bắt đầu ở từ kế tiếp.
    while s < e and chu[s].isspace():
        s += 1
    while e > s and chu[e - 1].isspace():
        e -= 1
    x0, x1 = x_tai(s, False), x_tai(e, True)
    if x0 is None or x1 is None or x1 <= x0:
        return None
    a, b = int(np.floor(x0)), int(np.ceil(x1))
    # Chiều dọc: hàng có mực trong đúng các cột đó. Box ADE đôi khi cắt mất
    # chân chữ (g, y, p): mực chạm mép thì dò tiếp ra ngoài, tối đa 20% dòng
    # (30% thì ăn sang dấu của dòng dưới khi hai dòng sát nhau, như CCCD).
    y0, y1 = ly0, ly1
    lim = max(2, round(0.2 * h))
    band = g[max(0, ly0 - lim):min(H, ly1 + lim), lx0 + a:lx0 + b].astype(np.int16)
    # Hàng chỉ lấm tấm vài điểm là hoa văn nền (CCCD), không phải chân chữ.
    hang = (band < nen - max(40, nen // 4)).sum(axis=1) >= max(1, round(0.04 * (b - a)))
    goc = ly0 - max(0, ly0 - lim)
    trong = np.flatnonzero(hang[goc:goc + h])
    if trong.size:
        y0, y1 = ly0 + int(trong[0]), ly0 + int(trong[-1]) + 1
        k = goc + int(trong[0]) - 1
        while k >= 0 and hang[k]:
            y0 -= 1; k -= 1
        k = goc + int(trong[-1]) + 1
        while k < len(hang) and hang[k]:
            y1 += 1; k += 1
        # Dấu tách rời chữ (mũ của Ô/Ệ, sắc của ố, chấm dưới) là hàng mực thưa
        # dưới ngưỡng trên: còn mực nào trong box dòng ADE thì phủ tới đó,
        # không quá mép box nên không lấn sang dòng bên cạnh.
        thua = np.flatnonzero((band[goc:goc + h] < nen - max(40, nen // 4)).any(axis=1))
        if thua.size:
            y0 = min(y0, ly0 + int(thua[0]))
            y1 = max(y1, ly0 + int(thua[-1]) + 1)
    return {"xmin": max(0.0, (lx0 + a) / W), "ymin": max(0.0, y0 / H),
            "xmax": min(1.0, (lx0 + b) / W), "ymax": min(1.0, y1 / H)}


def _tach_hang(line: Dong, chu: str, anh: AnhTrang) -> list[tuple[Dong, str, int, int]] | None:
    """Box ô bảng / đoạn chữ ngắt nhiều dòng trên trang: tách theo dải hàng có
    mực, chia từ cho từng dải theo bề rộng mực. Trả (dòng con, chữ con, lo, hi)
    — chữ con giữ nguyên vị trí, từ ngoài dải thay bằng khoảng trắng — hoặc
    None nếu box chỉ có một dòng chữ. Không tách thì cả ô nhiều dòng bị coi
    là một dòng và ô che trượt khỏi chữ."""
    import numpy as np
    from dataclasses import replace
    from .ade_store import box_to_pixels
    c = _cum_dong(line, anh)
    if c is None:
        return None
    muc, _, _, h = c
    # Giữa hai dòng chữ còn lấm tấm chân chữ và dấu thanh: khe là hàng mực
    # dưới 10% hàng đậm.
    tong = muc.sum(axis=1)
    if not tong.any():
        return None
    hang = np.flatnonzero(tong >= max(2.0, 0.1 * float(np.percentile(tong[tong > 0], 90))))
    if hang.size < 2:
        return None
    dai: list[list[int]] = [[int(hang[0]), int(hang[0]) + 1]]
    for y in hang[1:]:
        if int(y) - dai[-1][1] >= 2:
            dai.append([int(y), int(y) + 1])
        else:
            dai[-1][1] = int(y) + 1
    cao = max(b - a for a, b in dai)
    # Dải mỏng (dấu thanh tách khỏi thân chữ, gạch chân) nhập vào dải gần nhất.
    while len(dai) > 1:
        k = min(range(len(dai)), key=lambda q: dai[q][1] - dai[q][0])
        if dai[k][1] - dai[k][0] >= 0.45 * cao:
            break
        tren = dai[k][0] - dai[k - 1][1] if k > 0 else 1 << 30
        duoi = dai[k + 1][0] - dai[k][1] if k + 1 < len(dai) else 1 << 30
        j = k - 1 if tren <= duoi else k + 1
        a, b = min(dai[j][0], dai[k][0]), max(dai[j][1], dai[k][1])
        dai[min(j, k)] = [a, b]
        del dai[max(j, k)]
    if len(dai) < 2 or h < 1.6 * max(b - a for a, b in dai):
        return None
    tu = [(mm.start(), mm.end()) for mm in re.finditer(r"\S+", chu)]
    if len(tu) < len(dai):
        return None
    ww = [sum(_rong(x) for x in chu[a:b]) or 1.0 for a, b in tu]
    rong, segs = [], []
    for a, b in dai:
        seg = _cum_muc(muc[a:b].sum(axis=0) >= 2, khe=max(2, round(0.2 * (b - a))))
        segs.append(seg)
        rong.append(sum(y - x for x, y in seg) or 1)
    tich_w = [0.0]
    for w in ww:
        tich_w.append(tich_w[-1] + w)
    cat, j = [0], 0
    for k in range(1, len(dai)):
        muc_tieu = tich_w[-1] * sum(rong[:k]) / sum(rong)
        lo, hi = j + 1, len(tu) - (len(dai) - k)
        j = min(range(lo, hi + 1), key=lambda q: abs(tich_w[q] - muc_tieu))
        cat.append(j)
    cat.append(len(tu))

    def gia(k: int) -> float:
        r = _khop_tu_gia(ww[cat[k]:cat[k + 1]], segs[k]) if cat[k] < cat[k + 1] else None
        return r[0] if r else 1.0
    # Chia theo bề rộng lệch được một hai từ ở chỗ ngắt dòng: dời từng điểm
    # cắt tới chỗ hai dải kề nhau khớp mực tốt nhất.
    for k in range(1, len(dai)):
        goc = cat[k]
        tot, chon = gia(k - 1) + gia(k), goc
        for q in range(max(cat[k - 1] + 1, goc - 3), min(cat[k + 1] - 1, goc + 3) + 1):
            cat[k] = q
            g_ = gia(k - 1) + gia(k)
            if g_ < tot - 1e-9:
                tot, chon = g_, q
        cat[k] = chon
    g = anh.lay(line.page)
    H, W = g.shape
    _, ly0, _, ly1 = box_to_pixels(line.box, width=W, height=H)
    out = []
    for k, (a, b) in enumerate(dai):
        lo, hi = tu[cat[k]][0], tu[cat[k + 1] - 1][1]
        con = "".join(x if lo <= q < hi else " " for q, x in enumerate(chu))
        box = dict(line.box)
        box["ymin"] = max(line.box["ymin"], (ly0 + a - 1) / H)
        box["ymax"] = min(line.box["ymax"], (ly0 + b + 1) / H)
        out.append((replace(line, box=box), con, lo, hi))
    return out


def _gap(t: str) -> str:
    """Bỏ dấu, thường hoá, GIỮ nguyên độ dài (từng ký tự một → một ký tự)."""
    return "".join(unicodedata.normalize("NFD", c.replace("Đ", "D").replace("đ", "d"))[:1].lower()
                   for c in t)


def _iou(a: dict[str, float], b: dict[str, float]) -> float:
    w = min(a["xmax"], b["xmax"]) - max(a["xmin"], b["xmin"])
    h = min(a["ymax"], b["ymax"]) - max(a["ymin"], b["ymin"])
    if w <= 0 or h <= 0:
        return 0.0
    dt = lambda x: (x["xmax"] - x["xmin"]) * (x["ymax"] - x["ymin"])  # noqa: E731
    return w * h / (dt(a) + dt(b) - w * h)


def _tim_tu(chu_lon: str, nho: str) -> list[int]:
    """Mọi vị trí `nho` nằm trong `chu_lon` trọn từ (hai đầu không dính chữ)."""
    out, k = [], chu_lon.find(nho)
    while k >= 0:
        e = k + len(nho)
        if (k == 0 or not chu_lon[k - 1].isalnum()) and (e == len(chu_lon) or not chu_lon[e].isalnum()):
            out.append(k)
        k = chu_lon.find(nho, k + 1)
    return out


#: Một mảnh sửa box: đoạn [lo, hi) của chữ pro nằm ở dòng thường `dong`, vị
#: trí trong chữ thường = vị trí pro + `lech`.
@dataclass(frozen=True)
class _Manh:
    dong: Dong
    chu: str
    lech: int
    lo: int
    hi: int


def _dat_lai(dongs: list[Dong], chus: list[str], phu: dict | None,
             anh: AnhTrang) -> dict[int, list[_Manh]]:
    """Dòng nào của bản pro nên lấy box từ bản ADE thường (`parse.json`).

    ADE Pro có khi gán chữ lệch một box trong cả một khối (CCCD: "Nam" nằm
    trên box của "Quốc tịch…", mọi dòng dưới trượt theo) — che đúng box nó
    nói thì lọt chữ thật. Bản thường của cùng tệp thường đặt đúng. Với mỗi dòng
    pro, tìm dòng thường chứa nó hoặc là một khúc của nó (so bỏ dấu: bản
    thường hay hỏng dấu) ở chỗ KHÁC, rồi để mực phân xử: chỉ đổi khi box pro
    KHÔNG khớp (điểm > 0.4) mà box thường khớp (≤ 0.35). Điểm = giá khớp từ
    với cụm mực + |log| độ lệch tỉ lệ rộng/cao so với trung vị tài liệu.
    Chữ trùng ở hai chỗ (quê quán = nơi thường trú) thì lấy cả hai."""
    import math
    if not phu or not anh._p:
        return {}
    pmd = phu.get("markdown") or ""
    pd = [d for d in dong_cua(phu, anh.khung) if d.bang < 0]
    pchu = [lam_sach(pmd[d.start:d.end])[0] for d in pd]
    do = {i: _do_dong(d, chus[i], anh) for i, d in enumerate(dongs)
          if d.bang < 0 and len(chus[i].strip()) >= 3}
    tl = sorted(v[1] for v in do.values() if v and v[0] <= 0.08)
    if len(tl) < 3:
        return {}
    giua = tl[len(tl) // 2]

    def diem(v: tuple[float, float] | None) -> float:
        return math.inf if v is None or v[1] <= 0 else v[0] + abs(math.log(v[1] / giua))

    pdiem: dict[int, float] = {}
    out: dict[int, list[_Manh]] = {}
    for i, v in do.items():
        lp = len(chus[i]) - len(chus[i].lstrip())
        f = _gap(chus[i].strip())
        rieng = diem(v)
        if rieng <= 0.4:
            continue                           # box pro đã khớp mực: giữ
        manh: list[_Manh] = []
        for j, pdj in enumerate(pd):
            if pdj.page != dongs[i].page or _iou(pdj.box, dongs[i].box) > 0.5:
                continue
            ls = len(pchu[j]) - len(pchu[j].lstrip())
            g = _gap(pchu[j].strip())
            if len(g) < 3:
                continue
            cho = ([(ls + o - lp, lp, lp + len(f)) for o in _tim_tu(g, f)]
                   if 2 * len(f) >= len(g) else [])
            if len(g) >= 8 and len(g) < len(f) and 10 * len(g) >= 3 * len(f):
                cho += [(ls - lp - q, lp + q, lp + q + len(g)) for q in _tim_tu(f, g)]
            if not cho:
                continue
            if j not in pdiem:
                pdiem[j] = diem(_do_dong(pdj, pchu[j], anh))
            if pdiem[j] <= 0.35:
                manh += [_Manh(pdj, pchu[j], lech, lo, hi) for lech, lo, hi in cho]
        # Chữ lặp ở nhiều hơn hai chỗ (tiêu đề, chân trang) thì không biết
        # chỗ nào: để nguyên như không có bản thường.
        if manh and len({(m.lo, m.hi) for m in manh}) * 2 >= len(manh):
            out[i] = manh
    return out

def van_ban(parse: dict) -> str:
    """Chữ gửi pii-core: markdown của cả tài liệu, đã `lam_sach`. Vị trí field
    đổi về markdown bằng chính bản đồ của `lam_sach` (xem `tim_vung`)."""
    return lam_sach(parse.get("markdown") or "")[0]


def _hinh_ade(parse: dict) -> list[tuple[int, dict[str, float], str, str]]:
    """(trang, box, hạng mục, luật) của mọi phần tử che cả box của ADE:
    `figure`/`logo` (MARK_IMAGE, "hinh_ade") và `attestation` (SIGNATURE
    hoặc STAMP theo lời tả của ADE, "chung_thuc")."""
    md = parse.get("markdown") or ""
    out: list[tuple[int, dict[str, float], str, str]] = []

    def walk(x: Any) -> None:
        if not isinstance(x, dict):
            return
        g = x.get("grounding")
        t = x.get("type")
        if g and g.get("box"):
            if t in _PHAN_TU_HINH:
                out.append((_trang(g), g["box"], "MARK_IMAGE", "hinh_ade"))
            elif t == _CHUNG_THUC:
                r = g.get("range") or {}
                ta = lam_sach(md[r.get("start", 0):r.get("end", 0)])[0]
                out.append((_trang(g), g["box"], "SIGNATURE" if _KY.match(ta) else "STAMP",
                            "chung_thuc"))
        for c in x.get("children") or []:
            walk(c)

    walk(parse.get("structure") or {})
    return out


def _trong(a: dict[str, float], b: dict[str, float], lo: float = 0.005) -> bool:
    """Box `a` nằm trọn trong box `b` (nới `lo`)."""
    return (a["xmin"] >= b["xmin"] - lo and a["ymin"] >= b["ymin"] - lo
            and a["xmax"] <= b["xmax"] + lo and a["ymax"] <= b["ymax"] + lo)


# ── vùng chồng nhau: vùng nghiêm hơn thắng ───────────────────────────────
#
# Hai field kề nhau trên một dòng (ORG rồi GEO, email rồi số máy) có box nới
# hay đo mực chạm vào nhau; con dấu đè lên dòng chữ. Vẽ nguyên cả hai thì ô
# tô hai lần, nhãn in đè nhau, và trên lớp soát một ô KEEP nằm trên ô che
# trông như chữ đó được giữ. Đo trên C4 trước khi sửa: 388 cặp box chồng
# nhau ở 71/115 tài liệu.

#: Thứ tự nghiêm của `Action` pii-core. Hành động lạ đóng ở mức cao nhất.
_HANG = {"KEEP": 0, "PSEUDONYMISE": 1, "ANONYMISE": 2, "REMOVE": 3}
_EPS = 1e-9


def _dien_tich(b: dict[str, float]) -> float:
    return max(0.0, b["xmax"] - b["xmin"]) * max(0.0, b["ymax"] - b["ymin"])


def _tru(p: dict[str, float], a: dict[str, float]) -> list[dict[str, float]]:
    """p − a: các hộp thẳng không chồng nhau phủ ĐÚNG phần của p nằm ngoài a.
    Chia theo dải dọc trước hay dải ngang trước — lấy cách có mảnh lớn nhất
    lớn hơn (field kề nhau trên một dòng thì dải dọc: một mảnh gần nguyên)."""
    x0, y0 = max(p["xmin"], a["xmin"]), max(p["ymin"], a["ymin"])
    x1, y1 = min(p["xmax"], a["xmax"]), min(p["ymax"], a["ymax"])
    if x1 - x0 <= _EPS or y1 - y0 <= _EPS:
        return [p]
    h = lambda a0, b0, a1, b1: {"xmin": a0, "ymin": b0, "xmax": a1, "ymax": b1}  # noqa: E731
    doc = [h(p["xmin"], p["ymin"], x0, p["ymax"]), h(x1, p["ymin"], p["xmax"], p["ymax"]),
           h(x0, p["ymin"], x1, y0), h(x0, y1, x1, p["ymax"])]
    ngang = [h(p["xmin"], p["ymin"], p["xmax"], y0), h(p["xmin"], y1, p["xmax"], p["ymax"]),
             h(p["xmin"], y0, x0, y1), h(x1, y0, p["xmax"], y1)]
    cach = [[b for b in c if b["xmax"] - b["xmin"] > _EPS and b["ymax"] - b["ymin"] > _EPS]
            for c in (doc, ngang)]
    return max(cach, key=lambda c: (max(map(_dien_tich, c), default=0.0), -len(c)))


def _gop(vung: list[Vung]) -> list[Vung]:
    """Gộp các box CÙNG một thứ (cùng hạng mục, hành động, token) chồng nhau
    trên cùng một dòng — box pro và box thường của một field, hai lần đo của
    một chữ — thành hộp bao chung: rộng hơn cả hai nên không lộ gì."""
    out = list(vung)
    doi = True
    while doi:
        doi = False
        for i in range(len(out)):
            for j in range(i + 1, len(out)):
                a, b = out[i], out[j]
                if (a.page, a.code, a.action, a.thay, a.luat) != (b.page, b.code, b.action, b.thay, b.luat):
                    continue
                w = min(a.box["xmax"], b.box["xmax"]) - max(a.box["xmin"], b.box["xmin"])
                h = min(a.box["ymax"], b.box["ymax"]) - max(a.box["ymin"], b.box["ymin"])
                thap = min(a.box["ymax"] - a.box["ymin"], b.box["ymax"] - b.box["ymin"])
                if w <= _EPS or h < 0.5 * thap:
                    continue
                out[i] = replace(a, box={"xmin": min(a.box["xmin"], b.box["xmin"]),
                                         "ymin": min(a.box["ymin"], b.box["ymin"]),
                                         "xmax": max(a.box["xmax"], b.box["xmax"]),
                                         "ymax": max(a.box["ymax"], b.box["ymax"])})
                del out[j]
                doi = True
                break
            if doi:
                break
    return out


def _giai_chong(vung: list[Vung]) -> list[Vung]:
    """Không còn hai vùng nào chồng nhau. Vùng nghiêm hơn (REMOVE > ANONYMISE >
    PSEUDONYMISE > KEEP) giữ nguyên; vùng kém hơn bị cắt bỏ phần nằm dưới nó,
    nằm trọn dưới nó thì bỏ hẳn. Ngang hạng thì box lớn hơn thắng, rồi theo
    vị trí — tất định. Chỉ trừ đi phần ĐÃ CÓ vùng che phủ, nên hợp của mọi
    vùng che không đổi: field nào có ô che trước thì vẫn có. KEEP xếp cuối,
    nên không bao giờ cắt vào ô che, và các ô che giống hệt khi có hay không
    có KEEP (`giu`). Mảnh lớn nhất của mỗi vùng mang nhãn. Thứ tự ra giữ
    thứ tự vào."""
    vs = _gop(vung)
    xep = sorted(range(len(vs)), key=lambda i: (
        vs[i].page, -_HANG.get(vs[i].action, 3), -_dien_tich(vs[i].box),
        vs[i].box["ymin"], vs[i].box["xmin"], vs[i].code, vs[i].thay))
    da: dict[int, list[dict[str, float]]] = {}
    ra: dict[int, list[Vung]] = {}
    for i in xep:
        v = vs[i]
        manh = [v.box]
        for a in da.get(v.page, []):
            manh = [q for m in manh for q in _tru(m, a)]
            if not manh:
                break
        if not manh:
            continue
        lon = max(manh, key=_dien_tich)
        ra[i] = [replace(v, box=m, nhan=v.nhan and m is lon) for m in manh]
        da.setdefault(v.page, []).extend(manh)
    return [m for i in sorted(ra) for m in ra[i]]


@dataclass
class KetQua:
    """Vùng che của một tài liệu, và field nào không đặt được vào đâu."""
    vung: list[Vung]
    #: Field ≠ KEEP pii-core trả về, và bao nhiêu trong đó không có vùng nào.
    truong: int = 0
    khong_dinh_vi: int = 0
    #: Số FIELD (không phải box: một field hai dòng là hai box) theo hành
    #: động, và theo hạng mục → hành động. Có KEEP khi gọi với `giu`.
    dem: dict[str, int] = field(default_factory=dict)
    dem_hang_muc: dict[str, dict[str, int]] = field(default_factory=dict)


def tim_vung(parse: dict, nguon: PiiCore, trang: dict[int, Path] | None = None,
             phu: dict | None = None, *, group: str = "",
             truong: list[Truong] | None = None, giu: bool = False) -> KetQua:
    """Vùng cần che. Có `trang` (ảnh p{n}.jpg) thì box đo theo mực, khít.
    `phu` là bản ADE thường cùng tệp, dùng để sửa box pro bị gán lệch.
    `truong`: field pii-core của `van_ban(parse)` đã hỏi sẵn (cả hồ sơ một
    lần, `che_ho_so`); vắng thì hỏi `nguon` cho riêng tài liệu này.
    `giu`: trả cả field KEEP (để SOÁT trên web, không bao giờ để tô) — chữ
    thay của chúng là chữ gốc nên `thay` để trống; không tính vào đếm.
    Vùng trả về không chồng nhau (`_giai_chong`); trang nghiêng thì vùng mang
    `tu_giac` theo góc dòng chữ."""
    anh = AnhTrang(trang)
    md = parse.get("markdown") or ""
    # Trang nghiêng: mọi box từ đây xuống là box trong khung thẳng của trang
    # (`Khung`), ô che xoay về trang gốc ở cuối. `ade` giữ box ADE gốc: hình
    # và con dấu che cả box ADE, nên lấy hộp BAO nó (`Khung.bao`).
    ade = dong_cua(parse)
    khung = anh.dat_khung(ade)
    dongs = dong_cua(parse, khung) if khung else ade

    def bao(page: int, box: dict[str, float]) -> dict[str, float]:
        return khung[page].bao(box) if page in khung else box
    sach = [lam_sach(md[d.start:d.end]) for d in dongs]
    chus = [c for c, _ in sach]
    # Vị trí markdown của từng ký tự sạch trong dòng: không giảm, nên tìm
    # nhị phân được.
    goc = [[d.start + k for k in m] for d, (_, m) in zip(dongs, sach)]
    thay = _dat_lai(dongs, chus, phu, anh)
    # Box pro chỉ được bỏ khi bản thường đặt một chữ KHÁC lên đúng chỗ đó —
    # bằng chứng box ấy của dòng khác. Không thế thì che cả hai: chữ lặp ở
    # chỗ khác có thể là một lần xuất hiện khác, còn lần này vẫn nằm ở box pro.
    # (CCCD: box pro của địa chỉ nằm trên ngày hết hạn ADE bỏ sót — vẫn che.)
    chiem: list[tuple[dict[str, float], str]] = []
    if thay and phu:
        pmd = phu.get("markdown") or ""
        chiem = [(d.box, _gap(t)) for d in dong_cua(phu, khung) if d.bang < 0
                 for t in [lam_sach(pmd[d.start:d.end])[0].strip()] if t]

    def cua_dong_khac(d: Dong, chu: str) -> bool:
        f = _gap(chu.strip())
        return any(_iou(d.box, b) > 0.5 and f not in g and g not in f for b, g in chiem)

    def dinh(i: int, d: Dong, chu: str, s: int, e: int, ca: bool = False
             ) -> list[tuple[int, dict[str, float], str]]:
        """Các (trang, box, dinh_vi) phủ đoạn [s, e) của dòng i. `ca`: cả dòng,
        đo không được thì lấy cả box thay vì nội suy."""
        if i in thay:
            ra = []
            for m in thay[i]:
                a, b = max(s, m.lo), min(e, m.hi)
                if a < b:
                    bb = _hop_muc(m.dong, m.chu, a + m.lech, b + m.lech, anh)
                    ra.append((m.dong.page, bb or (m.dong.box if ca else
                               _hop_con(m.dong, m.chu, a + m.lech, b + m.lech)),
                               "muc" if bb else ("dong" if ca else "noi_suy")))
            if ra:
                if not cua_dong_khac(d, chu):
                    bb = _hop_muc(d, chu, s, e, anh)
                    ra.append((d.page, bb or (d.box if ca else _hop_con(d, chu, s, e)),
                               "muc" if bb else ("dong" if ca else "noi_suy")))
                return list({(p, tuple(b.values())): (p, b, v) for p, b, v in ra}.values())
        hang = _tach_hang(d, chu, anh) if anh is not None else None
        if hang:
            ra = []
            for con, cc, lo, hi in hang:
                a, b = max(s, lo), min(e, hi)
                if a < b:
                    bb = _hop_muc(con, cc, a, b, anh)
                    ra.append((d.page, bb or (con.box if ca else _hop_con(con, cc, a, b)),
                               "muc" if bb else ("dong" if ca else "noi_suy")))
            if ra:
                return ra
        bb = _hop_muc(d, chu, s, e, anh)
        return [(d.page, bb or (d.box if ca else _hop_con(d, chu, s, e)),
                 "muc" if bb else ("dong" if ca else "noi_suy"))]

    out: list[Vung] = []

    def hinh(page: int, box: dict[str, float], code: str, luat: str) -> bool:
        """Vùng che cả box cho một hình; False nếu pii-core bảo giữ."""
        hd = nguon.hanh_dong(code)
        if hd == "KEEP":
            return False
        out.append(Vung(page, box, code, hd, luat, thay=f"[{code}]"))
        return True

    # Mẫu nhãn dạng hình, logo, ảnh, con dấu, chữ ký: che cả phần tử trên mọi
    # bản che.
    phu_kin: list[tuple[int, dict[str, float]]] = []
    for p, b, code, luat in _hinh_ade(parse):
        if hinh(p, bao(p, b), code, luat):
            phu_kin.append((p, bao(p, b)))
    # Dòng đã nằm dưới một ô đen cả box: field trong nó có vùng rồi.
    kin: set[int] = set()
    for i, d in enumerate(dongs):
        if d.kieu == "scan_code":
            # Mã QR trên CCCD mã hoá cả số định danh, họ tên, ngày sinh.
            if hinh(d.page, bao(d.page, ade[i].box), "SCAN_CODE", "ma_quet"):
                kin.add(i)
            continue
        code = next((c for c, pat in _HINH if pat.fullmatch(chus[i].strip())), None)
        if (code and hinh(d.page, bao(d.page, ade[i].box), code, "hinh")) or \
                any(p == d.page and _trong(d.box, b) for p, b in phu_kin):
            kin.add(i)

    if truong is None:
        truong = nguon.quyet([van_ban(parse)], group)[0]
    _, ban_do = lam_sach(md)
    so = khong = 0
    dem: dict[str, int] = {}
    dem_hm: dict[str, dict[str, int]] = {}
    for f in sorted(truong, key=lambda t: (t.start, t.end)):
        giu_lai = f.action == "KEEP"
        if (giu_lai and not giu) or not (0 <= f.start < f.end <= len(ban_do)):
            continue
        so += not giu_lai
        cat = f.category or "UNKNOWN"
        dem[f.action] = dem.get(f.action, 0) + 1
        dem_hm.setdefault(cat, {})[f.action] = dem_hm.setdefault(cat, {}).get(f.action, 0) + 1
        ra, rb = ban_do[f.start], ban_do[f.end - 1] + 1      # [ra, rb) trong markdown
        co = False
        for i, d in enumerate(dongs):
            if d.end <= ra or d.start >= rb:
                continue
            s, e = bisect_left(goc[i], ra), bisect_left(goc[i], rb)
            if s >= e or not chus[i][s:e].strip():
                continue
            co = True
            if i in kin:
                continue
            ca = chus[i][s:e].strip() == chus[i].strip()
            tk = "" if giu_lai else f.replacement or f"[{cat}]"
            for pg, box, dv in dinh(i, d, chus[i], s, e, ca=ca):
                out.append(Vung(pg, box, cat, f.action, "pii_core", dv, thay=tk))
        if not co and not giu_lai:
            khong += 1
    # Nhiều dòng pro có thể cùng dời về một box thường: bỏ vùng trùng.
    vung = _giai_chong(list({(v.page, v.code, tuple(v.box.values())): v for v in out}.values()))

    def ve_goc(v: Vung) -> Vung:
        if v.page not in khung:
            return v
        box, tg = khung[v.page].ve_hop(v.box)
        return replace(v, box=box, tu_giac=tg)
    return KetQua([ve_goc(v) for v in vung], so, khong, dem, dict(sorted(dem_hm.items())))


# ── nung: tô lên ảnh, dựng PDF mới ───────────────────────────────────────

#: Dải nhãn chữ trắng (font mặc định của PIL cao ~11 px, in lệch 1 px). Box
#: khít thường chỉ cao 12–14 px: in nhãn vào đó là chữ trắng tràn xuống lõi,
#: nên chỉ in khi box cao hơn dải nhãn ít nhất 6 px.
_NHAN_CAO = 14


def _pixel(box: dict, w: int, h: int, pad: int = 1) -> tuple[int, int, int, int]:
    from .ade_store import box_to_pixels
    x0, y0, x1, y1 = box_to_pixels(box, width=w, height=h)
    return max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)


Diem = tuple[float, float]


def _truc(q: tuple[Diem, ...]) -> tuple[Diem, Diem, float, float]:
    """Trục của tứ giác (trên-trái, trên-phải, dưới-phải, dưới-trái): véc-tơ
    đơn vị dọc mép trên, véc-tơ đơn vị dọc mép trái, rộng, cao."""
    (x0, y0), (x1, y1), _, (x3, y3) = q
    rong, cao = math.hypot(x1 - x0, y1 - y0), math.hypot(x3 - x0, y3 - y0)
    return ((x1 - x0) / (rong or 1), (y1 - y0) / (rong or 1)), \
        ((x3 - x0) / (cao or 1), (y3 - y0) / (cao or 1)), rong, cao


def _trong_khung(q: tuple[Diem, ...], a0: float, b0: float, a1: float, b1: float) -> tuple[Diem, ...]:
    """Hình chữ nhật [a0, a1] × [b0, b1] theo trục riêng của tứ giác `q`."""
    (u, v, _, _), (x, y) = _truc(q), q[0]
    return tuple((x + u[0] * a + v[0] * b, y + u[1] * a + v[1] * b)
                 for a, b in ((a0, b0), (a1, b0), (a1, b1), (a0, b1)))


def _da_giac(v: Vung, w: int, h: int, pad: int = 1) -> tuple[Diem, ...] | None:
    """Tứ giác ô che theo điểm ảnh, nới `pad` px ra mọi phía như `_pixel`."""
    if not v.tu_giac:
        return None
    q = tuple((x * w, y * h) for x, y in v.tu_giac)
    _, _, rong, cao = _truc(q)
    return _trong_khung(q, -pad, -pad, rong + pad, cao + pad)


def _hop_bao(q: tuple[Diem, ...], w: int, h: int) -> tuple[int, int, int, int]:
    return (max(0, math.floor(min(p[0] for p in q))), max(0, math.floor(min(p[1] for p in q))),
            min(w, math.ceil(max(p[0] for p in q))), min(h, math.ceil(max(p[1] for p in q))))


def nung(trang: dict[int, Path], vung: list[Vung], out_pdf: Path, *,
         ghi_nhan: bool = True) -> dict[int, list[tuple]]:
    """Tô đen từng vùng lên ảnh trang và ghi một PDF CHỈ gồm ảnh.

    Như `saveSecurely` của HideMyData: trang mới dựng từ ảnh, nên không còn
    lớp text, không còn font, không còn metadata của tệp gốc.

    Trả, theo trang, (x0, y0, x1, y1, cao dải nhãn) của từng ô — ô tứ giác
    (trang nghiêng) có thêm phần tử thứ sáu là bốn góc theo điểm ảnh.
    """
    import pymupdf
    from PIL import Image, ImageDraw

    from .ade_store import DISPLAY_DPI

    rects: dict[int, list[tuple]] = {}
    doc = pymupdf.open()
    for n in sorted(trang):
        im = Image.open(trang[n]).convert("RGB")
        dr = ImageDraw.Draw(im)
        cua_trang = []
        for v in vung:
            if v.page == n:
                q = _da_giac(v, im.width, im.height)
                cua_trang.append((v, _pixel(v.box, im.width, im.height) if q is None
                                  else _hop_bao(q, im.width, im.height), q))
        # Tô HẾT rồi mới in nhãn: in nhãn xen kẽ thì chữ trắng của ô này rơi
        # vào lõi ô bên cạnh — đo trên kho: 431 vùng ở 153 tài liệu.
        for _, r, q in cua_trang:
            if q is None:
                dr.rectangle(r, fill=(0, 0, 0))
            else:
                dr.polygon(q, fill=(0, 0, 0))
        ra: list[tuple] = []
        for v, r, q in cua_trang:
            dai = 0
            nhan = _nhan(v)
            if q is None:
                rong, cao = r[2] - r[0], r[3] - r[1]
                band: tuple[int, ...] = (r[0], r[1], r[2], r[1] + _NHAN_CAO)
            else:
                _, _, rong, cao = _truc(q)
                band = _hop_bao(_trong_khung(q, 0, 0, rong, _NHAN_CAO), im.width, im.height)
            if ghi_nhan and v.nhan and cao >= _NHAN_CAO + 6 and dr.textlength(nhan) + 4 <= rong \
                    and not any(_giao(band, o) for _, o, _ in cua_trang if o is not r):
                # In token của pii-core: người đọc biết cái gì đã bị che
                # và tra được nó trong văn bản đã che / kho, cùng một mã.
                if q is None:
                    dr.text((r[0] + 2, r[1] + 1), nhan, fill=(255, 255, 255))
                else:
                    _in_xoay(im, q, nhan)
                dai = _NHAN_CAO
            ra.append((*r, dai) if q is None else (*r, dai, q))
        rects[n] = ra
        buf = _jpeg(im)
        # Ảnh trang render ở DISPLAY_DPI; giữ đúng khổ giấy khi in.
        k = 72 / DISPLAY_DPI
        p = doc.new_page(width=im.width * k, height=im.height * k)
        p.insert_image(p.rect, stream=buf)
    doc.set_metadata({})
    doc.del_xml_metadata()
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_pdf, garbage=4, deflate=True, no_new_id=True)
    doc.close()
    return rects


def _nhan(v: Vung) -> str:
    """Chữ in lên ô: token pii-core; nhãn lớp khi không có, hoặc khi thứ thay
    vào không phải ASCII (font mặc định của PIL không có dấu tiếng Việt)."""
    t = v.thay or f"[{v.code}]"
    return t if t.isascii() else f"[{v.code}]"


def _giao(a: tuple[int, ...], b: tuple[int, ...]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _in_xoay(im: Any, q: tuple[Diem, ...], nhan: str) -> None:
    """In nhãn trắng dọc mép trên của ô tứ giác, nghiêng theo ô: y như
    `dr.text` ở ô thẳng, nhưng trong trục riêng của ô."""
    from PIL import Image, ImageDraw
    (ux, uy), (vx, vy), rong, _ = _truc(q)
    la = Image.new("L", (max(1, math.ceil(rong)), _NHAN_CAO), 0)
    ImageDraw.Draw(la).text((2, 1), nhan, fill=255)
    # PIL xoay ngược chiều kim đồng hồ khi nhìn, trục y ảnh hướng xuống.
    xoay = la.rotate(-math.degrees(math.atan2(uy, ux)), resample=Image.BILINEAR, expand=True)
    # Tâm dải nhãn: xoay giữ tâm, nên đặt tâm ảnh xoay vào đó.
    cx = q[0][0] + ux * la.width / 2 + vx * la.height / 2
    cy = q[0][1] + uy * la.width / 2 + vy * la.height / 2
    im.paste((255, 255, 255), (round(cx - xoay.width / 2), round(cy - xoay.height / 2)), xoay)


def _jpeg(im: Any) -> bytes:
    import io
    b = io.BytesIO()
    im.save(b, "JPEG", quality=90)
    return b.getvalue()


def _sang_nhat_tu_giac(im: Any, q: tuple[Diem, ...]) -> int:
    """Điểm sáng nhất của ảnh xám `im` bên trong tứ giác `q`."""
    import numpy as np
    from PIL import Image, ImageDraw
    x0, y0, x1, y1 = _hop_bao(q, im.width, im.height)
    if x1 > x0 and y1 > y0:
        mn = Image.new("L", (x1 - x0, y1 - y0), 0)
        ImageDraw.Draw(mn).polygon([(x - x0, y - y0) for x, y in q], fill=255)
        trong = np.asarray(mn) > 0
        if trong.any():
            return int(np.asarray(im.crop((x0, y0, x1, y1)))[trong].max())
    # Lõi co về một điểm: kiểm tâm, không bao giờ bỏ qua vùng.
    cx, cy = sum(p[0] for p in q) / 4, sum(p[1] for p in q) / 4
    return int(im.getpixel((min(im.width - 1, max(0, int(cx))), min(im.height - 1, max(0, int(cy))))))


def chung_minh(out_pdf: Path, rects: dict[int, list[tuple]],
               khong_dinh_vi: int = 0) -> list[str]:
    """Đọc lại tệp đã ghi và kể mọi chỗ nó chưa sạch. Rỗng = đạt.

    Kiểm trên TỆP ĐÃ GHI, không trên ảnh trong bộ nhớ: một vùng tô đúng trên
    ảnh vẫn có thể hỏng lúc nén, và một lớp text sót chỉ thấy khi mở lại.
    Kiểm cả độ phủ: field ≠ KEEP nào của pii-core không có vùng
    (`khong_dinh_vi`) thì giá trị đó còn nguyên trên ảnh — không đạt.
    """
    import io
    import pymupdf
    from PIL import Image

    loi: list[str] = []
    if khong_dinh_vi:
        loi.append(f"{khong_dinh_vi} field ≠ KEEP của pii-core không có vùng che")
    with pymupdf.open(out_pdf) as doc:
        meta = {k: v for k, v in (doc.metadata or {}).items()
                if v and k not in ("format", "encryption")}
        if meta:
            loi.append(f"metadata còn: {sorted(meta)}")
        for i, page in enumerate(doc, start=1):
            if page.get_text().strip():
                loi.append(f"trang {i}: còn lớp text")
            imgs = page.get_images(full=True)
            if len(imgs) != 1:
                loi.append(f"trang {i}: {len(imgs)} ảnh, chờ đúng 1")
                continue
            im = Image.open(io.BytesIO(doc.extract_image(imgs[0][0])["image"])).convert("L")
            for r in rects.get(i, []):
                if len(r) > 5:
                    # Ô tứ giác: cùng phép kiểm, trong trục riêng của ô.
                    _, _, rong, cao = _truc(r[5])
                    v = 1 if min(rong, cao) < 12 else 2
                    a0, b0, a1, b1 = v, max(v, r[4]), rong - v, cao - v
                    if a1 <= a0 or b1 <= b0:
                        a0 = a1 = rong / 2
                        b0 = b1 = cao / 2
                    sang = _sang_nhat_tu_giac(im, _trong_khung(r[5], a0, b0, a1, b1))
                    if sang > 80:
                        loi.append(f"trang {i}: vùng {r[:5]} còn điểm sáng {sang}")
                    continue
                # Lõi vùng: bỏ viền 3 px JPEG làm nhoè, và dải nhãn trắng nếu
                # CHÍNH vùng này có in nhãn (phần tử thứ năm của bộ).
                # Box khít có thể chỉ rộng vài điểm ảnh: viền bỏ đi co theo, và
                # không bao giờ bỏ qua vùng — còn tâm thì kiểm tâm.
                v = 1 if min(r[2] - r[0], r[3] - r[1]) < 12 else 2
                x0, y0, x1, y1 = r[0] + v, max(r[1] + v, r[1] + r[4]), r[2] - v, r[3] - v
                if x1 <= x0 or y1 <= y0:
                    cx, cy = (r[0] + r[2]) // 2, (r[1] + r[3]) // 2
                    x0, y0, x1, y1 = cx, cy, cx + 1, cy + 1
                sang = im.crop((x0, y0, x1, y1)).getextrema()[1]
                if sang > 80:
                    loi.append(f"trang {i}: vùng {r} còn điểm sáng {sang}")
    return loi


# ── một tài liệu, đầu cuối ───────────────────────────────────────────────

def _ensure_private(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)
    p.chmod(0o700)


def parse_phu(doc_dir: Path) -> dict | None:
    """Bản ADE thường (`parse.json`) cùng tệp, nếu có — chỉ để sửa box pro."""
    f = doc_dir / "parse.json"
    try:
        return json.loads(f.read_text("utf-8")) if f.is_file() else None
    except ValueError:
        return None


def anh_trang(doc_dir: Path) -> dict[int, Path]:
    d = doc_dir / "pages"
    return {int(p.stem[1:]): p for p in d.glob("p*.jpg")
            if p.stem[1:].isdigit()} if d.is_dir() else {}


def _doc_parse(doc_dir: Path) -> dict | None:
    f = doc_dir / "parse_pro.json"
    return json.loads(f.read_text("utf-8")) if f.is_file() else None


def che_tai_lieu(doc_dir: Path, nguon: PiiCore, out_root: Path = DEFAULT_OUT, *,
                 ghi: bool = True, ghi_nhan: bool = True, group: str = "",
                 truong: list[Truong] | None = None) -> dict[str, Any]:
    """Che một tài liệu trong kho ADE. Trả bản tóm tắt KHÔNG chứa chữ gốc."""
    doc_id = doc_dir.name
    parse = _doc_parse(doc_dir)
    if parse is None:
        return {"doc_id": doc_id, "bo_qua": "không có parse_pro.json"}
    trang = anh_trang(doc_dir)
    kq = tim_vung(parse, nguon, trang, parse_phu(doc_dir), group=group, truong=truong)
    vung = kq.vung
    so_trang = int((parse.get("metadata") or {}).get("page_count") or 0)
    tom: dict[str, Any] = {"doc_id": doc_id, "vung": len(vung),
                           "theo_hang_muc": _dem(vung), "truong": kq.truong,
                           "khong_dinh_vi": kq.khong_dinh_vi}
    if not trang:
        tom["bo_qua"] = "không có ảnh trang (pages/p*.jpg) để tô lên"
        return tom
    if so_trang and len(trang) != so_trang:
        # Tô lên một phần tài liệu rồi gọi là xong là kiểu hỏng khó thấy nhất.
        tom["bo_qua"] = f"có {len(trang)} ảnh trang, parse nói {so_trang} trang"
        return tom
    lac = sorted({v.page for v in vung} - set(trang))
    if lac:
        # Vùng rơi vào trang không có ảnh thì `nung` sẽ bỏ nó im lặng — tệp ra
        # trông sạch mà chữ vẫn còn. Không ghi gì cả.
        tom["bo_qua"] = f"vùng ở trang không có ảnh: {lac}"
        return tom
    if not ghi:
        return tom
    out = out_root / doc_id
    _ensure_private(out_root)
    _ensure_private(out)
    rects = nung(trang, vung, out / "che.pdf", ghi_nhan=ghi_nhan)
    loi = chung_minh(out / "che.pdf", rects, kq.khong_dinh_vi)
    tom["chung_minh"] = loi or "đạt"
    (out / "che.json").write_text(json.dumps({
        "doc_id": doc_id, "pii_core": nguon.nguon, "truong": kq.truong,
        "khong_dinh_vi": kq.khong_dinh_vi,
        "vung": [asdict(v) for v in vung], "chung_minh": loi or "đạt",
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return tom


def che_ho_so(doc_dirs: Iterable[Path], nguon: PiiCore, out_root: Path = DEFAULT_OUT, *,
              group: str = "", **kw: Any) -> list[dict[str, Any]]:
    """Che các tài liệu của MỘT hồ sơ: hỏi pii-core một lần cho cả nhóm, để
    tên/nhãn/mã thấy ở tài liệu này được tìm lại ở tài liệu kia (thư viện:
    `redact_case`; HTTP `/v1/document` thì vẫn từng tài liệu)."""
    dirs = list(doc_dirs)
    parses = {d: _doc_parse(d) for d in dirs}
    co = [d for d in dirs if parses[d] is not None]
    fields = nguon.quyet([van_ban(parses[d]) for d in co], group) if co else []
    theo = dict(zip(co, fields))
    return [che_tai_lieu(d, nguon, out_root, group=group, truong=theo.get(d), **kw)
            for d in dirs]


def _dem(vung: list[Vung]) -> dict[str, int]:
    """Số vùng theo hạng mục; vùng bị cắt thành nhiều mảnh vẫn là một."""
    out: dict[str, int] = {}
    for v in vung:
        if v.nhan:
            out[v.code] = out.get(v.code, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def tai_lieu_trong(store: Path) -> Iterator[Path]:
    for d in sorted(store.iterdir()):
        if (d / "parse_pro.json").is_file():
            yield d
