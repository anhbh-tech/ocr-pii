#!/usr/bin/env python3
"""Sổ vai ảnh: gán vai cho 100 tấm ảnh trong kho, chép mô tả thị giác đã có.

ADE Pro đã đọc 100 tấm ảnh và 68 tấm đã mang sẵn một khối `<figure><description>`
mô tả nội dung nhìn thấy. Chưa có mô tả nào được chép vào sổ, nên tầng trên
phải mở lại ảnh mới biết trong ảnh có gì. Script này KHÔNG gọi ADE và KHÔNG
gọi model thị giác — nó chỉ đọc lại `~/.private/ade_out` (0 credit).

    uv run python scripts/so_vai_anh.py

Ba việc:

1. **Vai lấy từ ĐƯỜNG DẪN.** Bảng luật `LUAT_VAI` dưới đây khớp theo thứ tự,
   luật đầu tiên trúng thì thắng. Không đổi tên tệp, không suy vai từ nội
   dung ảnh — thư mục hồ sơ đã nói vai rồi. Mã luật được ghi vào sổ để người
   sau soát lại được từng dòng.
2. **Chép mô tả.** Mỗi `<description>` chép nguyên văn vào `hinh[].mo_ta`, và
   bản ghép của cả tài liệu nằm ở `mo_ta_thi_giac`.
3. **Tách chrome khỏi bằng chứng.** Khối figure nào chỉ mô tả thanh công cụ
   Zalo (bảng "Photos/Videos", ô ảnh rỗng, icon máy ảnh / kính lúp) thì đặt
   `giao_dien: true` và loại khỏi `bo_bang_chung`.

Sổ ra `~/.private/so/vai_anh.json` quyền 700 — nó dẫn chiếu hồ sơ khách hàng
nên KHÔNG được nằm trong cây dự án. Sổ chỉ mang mô tả thị giác, không mang
toàn văn OCR, vì toàn văn có số căn cước và số tài khoản.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

NGUON = Path.home() / ".private" / "ade_out"
DICH = Path.home() / ".private" / "so" / "vai_anh.json"

ANH = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif", ".bmp", ".tif", ".tiff"}

# parse_pro2 > parse_pro > parse: bản Pro mới nhất là bản duy nhất có figure.
TEP_META = ("meta_pro2.json", "meta_pro.json", "meta.json")
TEP_PARSE = ("parse_pro2.json", "parse_pro.json", "parse.json")

VAI_EN = {
    "mau_vat": "specimen",
    "bang_chung": "evidence",
    "anh_hoi_thoai": "conversation screenshot",
    "anh_giao_dien": "interface screenshot",
}

# --------------------------------------------------------------------------
# Bảng luật: (mã, vai, phạm vi, mẫu, giải thích).
#
# phạm vi `thu_muc` khớp vào từng đoạn thư mục, `ten` khớp vào tên tệp,
# `duong_dan` khớp vào cả đường dẫn. Khớp không phân biệt hoa thường, sau khi
# đã chuẩn hoá NFC (kho trộn NFC với NFD, xem `de_xuat_sua`).
#
# Thứ tự QUAN TRỌNG: mẫu vật đứng trước, vì `mau nhan 3.jpg` nằm chung thư mục
# `1. Tra cuu` với ảnh chụp Zalo báo khách.
# --------------------------------------------------------------------------
LUAT_VAI: list[tuple[str, str, str, str, str]] = [
    ("R01", "mau_vat", "ten", r"specimen",
     "tên tệp nói thẳng đây là mẫu vật nộp đơn"),
    ("R02", "mau_vat", "ten", r"mau nhan",
     "mẫu nhãn dùng để tra cứu / nộp đơn"),
    ("R03", "mau_vat", "thu_muc", r"^đky bản quyền$",
     "bản tác phẩm nộp kèm đơn đăng ký bản quyền"),
    ("R04", "mau_vat", "thu_muc", r"^3\. certification$",
     "tác phẩm in trên giấy chứng nhận"),
    ("R05", "mau_vat", "thu_muc", r"^sp\d+$",
     "bộ mẫu vật nộp kèm bản trả lời Office Action"),
    ("R06", "mau_vat", "duong_dan", r"2\. đăng ký bản quyền tại hoa kỳ/[^/]+/0\.\s*info/",
     "hồ sơ bản quyền: ảnh ở '0. Info' chính là tác phẩm"),

    ("R07", "anh_hoi_thoai", "thu_muc", r"^4\. internal discussion$",
     "ảnh chụp nhóm chat nội bộ"),
    ("R08", "anh_hoi_thoai", "thu_muc", r"^(1\. tra cuu|3\. tra cuu lan 2)$",
     "ảnh chụp tin nhắn báo kết quả tra cứu cho khách"),
    ("R09", "anh_hoi_thoai", "thu_muc", r"^1\. doc from client$",
     "ảnh khách gửi trong khung chat"),
    ("R10", "anh_hoi_thoai", "duong_dan", r"5\. result/[^/]*confirmation",
     "ảnh chụp lời xác nhận của khách trong chat"),

    ("R11", "bang_chung", "thu_muc", r"^bang chung su dung nhan hieu$",
     "bằng chứng sử dụng nhãn hiệu"),
    ("R12", "bang_chung", "thu_muc", r"^evidence of use$",
     "bằng chứng sử dụng nhãn hiệu"),
    ("R13", "bang_chung", "thu_muc", r"^product pictures",
     "ảnh sản phẩm khách gửi"),
    ("R14", "bang_chung", "thu_muc", r"^selected ",
     "ảnh sản phẩm đã chọn để nộp Amazon Brand Registry"),
    ("R15", "bang_chung", "ten", r"cccd",
     "ảnh giấy tờ tuỳ thân kèm hồ sơ"),
    ("R16", "bang_chung", "ten", r"court case notification",
     "thông báo vụ kiện"),
    ("R17", "bang_chung", "thu_muc", r"^accounting$",
     "chứng từ thanh toán"),

    ("R18", "anh_giao_dien", "thu_muc", r"^3\. appeal lan 2$",
     "ảnh chụp màn hình cổng Amazon Brand Registry"),
    ("R19", "anh_giao_dien", "thu_muc", r"^5\. result$",
     "ảnh chụp màn hình hộp thư / cổng dịch vụ"),
    ("R20", "anh_giao_dien", "ten", r"(?<![0-9a-z])amz(?![0-9a-z])",
     "ảnh chụp màn hình tài khoản Amazon Seller Central"),

    ("R21", "bang_chung", "ten", r"payment|receipt|reccepit|thanh toan|comm?ission",
     "chứng từ thanh toán nằm ngoài thư mục Accounting"),
]

LUAT_DU = ("R99", "bang_chung", "chưa có luật đường dẫn nào trúng — cần người soát")

# --------------------------------------------------------------------------
# Chrome của khung chat: mô tả thị giác chỉ nói về giao diện, không nói về
# vật chứng. Cắt khỏi bộ bằng chứng, nhưng vẫn giữ nguyên văn trong sổ.
# --------------------------------------------------------------------------
CHROME_CHAC = (
    r"photos\s*/\s*videos",           # bảng media bên phải cửa sổ Zalo
    r"ui element or placeholder",     # ô ảnh chưa tải
    r"placeholder panel",
)
CHROME_ICON = (
    r"\bmagnifying glass\b",
    r"\bcamera icon\b",
    r"\badd[- ]people icon\b",
    r"\bsearch icon\b",
    r"\blayout (?:split view )?icon\b",
    r"\btoolbar\b",
)
NGUONG_ICON = 400   # mô tả dài hơn thế thì icon chỉ là chi tiết phụ

# Dấu hiệu khung chat trong toàn văn — chỉ dùng để ĐỐI CHIẾU với bảng luật,
# không dùng để gán vai.
HDR_CHAT = re.compile(r"\d+\s*(?:thành viên|thanh vien|members)", re.I)
CHROME_CHAT = (
    re.compile(r"add[ _]people|add[ _]user|ADD_PEOPLE|👥|👤\+", re.I),
    re.compile(r"video[ _]camera|VIDEO_CAMERA|📹", re.I),
    re.compile(r"magnifying glass|search[ _]icon|SEARCH_ICON|🔍", re.I),
    re.compile(r"layout[ _](?:split|icon|view)|side-by-side view|LAYOUT_ICON|◧|🔲", re.I),
)

# Tệp có thể mang định danh trực tiếp trong ảnh. Sổ không chép toàn văn, nhưng
# đánh dấu để tầng sau biết chỗ nào phải che.
NHAY_CAM = re.compile(r"cccd|căn cước|can cuoc|passport|payment|receipt|thanh toan|invoice", re.I)

RX_FIGURE = re.compile(r"<figure([^>]*)>(.*?)</figure>", re.S)
RX_DESC = re.compile(r"<description>(.*?)</description>", re.S)
RX_LOAI = re.compile(r'type="([^"]+)"')


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def gon(s: str) -> str:
    return " ".join(s.split())


def _doc_json(thu_muc: Path, ten: tuple[str, ...]) -> dict | None:
    for t in ten:
        f = thu_muc / t
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
    return None


def gan_vai(duong_dan: str) -> tuple[str, str, str]:
    """Trả về (mã luật, vai, giải thích). Chỉ nhìn đường dẫn."""
    p = nfc(duong_dan).lower()
    doan = p.split("/")
    thu_muc, ten = doan[:-1], doan[-1]
    for ma, vai, pham_vi, mau, vi_sao in LUAT_VAI:
        if pham_vi == "ten":
            trung = re.search(mau, ten)
        elif pham_vi == "thu_muc":
            trung = any(re.search(mau, d) for d in thu_muc)
        else:
            trung = re.search(mau, p)
        if trung:
            return ma, vai, vi_sao
    return LUAT_DU[0], LUAT_DU[1], LUAT_DU[2]


def la_chrome(mo_ta: str) -> bool:
    t = mo_ta.lower()
    if any(re.search(m, t) for m in CHROME_CHAC):
        return True
    return len(t) < NGUONG_ICON and any(re.search(m, t) for m in CHROME_ICON)


def boc_hinh(markdown: str) -> list[dict]:
    """Bóc từng khối <figure> kèm mô tả. Chép nguyên văn, không sửa chữ."""
    hinh = []
    for i, m in enumerate(RX_FIGURE.finditer(markdown)):
        than = m.group(2)
        loai = RX_LOAI.search(m.group(1))
        mo_ta = [gon(d) for d in RX_DESC.findall(than)]
        # ADE Pro thỉnh thoảng để một câu dẫn ngoài <description>; giữ luôn,
        # vì cắt đi là mất chữ mà model đã trả tiền để sinh ra.
        ngoai = gon(RX_DESC.sub(" ", than))
        if not mo_ta and ngoai:
            mo_ta = [ngoai]
            ngoai = ""
        cau = " ".join(mo_ta)
        hinh.append({
            "so": i,
            "loai": loai.group(1) if loai else None,
            "dan": ngoai or None,
            "mo_ta": cau or None,
            "giao_dien": bool(cau) and la_chrome(f"{ngoai} {cau}"),
        })
    return hinh


def dau_hieu_chat(markdown: str) -> bool:
    """Đối chiếu độc lập: toàn văn có khung nhóm chat không."""
    if HDR_CHAT.search(markdown):
        return True
    return sum(1 for r in CHROME_CHAT if r.search(markdown)) >= 2


def quet() -> dict:
    tai_lieu: list[dict] = []
    de_xuat: list[dict] = []
    tron_chuan_hoa = 0

    for d in sorted(os.listdir(NGUON)):
        thu_muc = NGUON / d
        if not thu_muc.is_dir():
            continue
        meta = _doc_json(thu_muc, TEP_META)
        if not meta:
            de_xuat.append({"loai": "thieu_meta", "id": d,
                            "ghi_chu": "thư mục ade_out không có tệp meta nào"})
            continue
        nguon_tep = meta.get("source", "")
        if Path(nguon_tep).suffix.lower() not in ANH:
            continue

        parse = _doc_json(thu_muc, TEP_PARSE) or {}
        markdown = parse.get("markdown", "")

        if nguon_tep != nfc(nguon_tep):
            tron_chuan_hoa += 1
        duong_dan = nfc(nguon_tep)
        doan = duong_dan.split("/")

        ma, vai, vi_sao = gan_vai(duong_dan)
        hinh = boc_hinh(markdown)
        so_the_desc = markdown.count("<description>")
        mo_ta_tat = [h["mo_ta"] for h in hinh if h["mo_ta"]]
        bang_chung = [h["mo_ta"] for h in hinh if h["mo_ta"] and not h["giao_dien"]]

        if ma == LUAT_DU[0]:
            de_xuat.append({
                "loai": "khong_co_luat", "id": d, "duong_dan": duong_dan,
                "vai_tam": vai,
                "ghi_chu": "không luật đường dẫn nào trúng; sổ để tạm ở bằng chứng, "
                           "cần thêm một luật vào LUAT_VAI",
            })

        chat = dau_hieu_chat(markdown)
        if chat and vai != "anh_hoi_thoai":
            de_xuat.append({
                "loai": "vai_lech_dau_hieu", "id": d, "duong_dan": duong_dan,
                "vai_theo_duong_dan": vai, "luat": ma,
                "ghi_chu": "toàn văn có khung nhóm chat nhưng đường dẫn không nói "
                           "hội thoại — người soát quyết định, script không tự đổi",
            })

        tai_lieu.append({
            "id": d,
            "duong_dan": duong_dan,
            "muc": "/".join(doan[:2]) if len(doan) > 2 else None,
            "ho_so": doan[2].strip() if len(doan) > 3 else None,
            "ten_tep": doan[-1],
            "vai": vai,
            "vai_en": VAI_EN[vai],
            "luat": ma,
            "luat_vi_sao": vi_sao,
            "model": meta.get("model"),
            "so_hinh": len(hinh),
            "so_mo_ta": len(mo_ta_tat),
            "so_the_description": so_the_desc,
            "so_mo_ta_giao_dien": sum(1 for h in hinh if h["giao_dien"]),
            "mo_ta_thi_giac": " ".join(mo_ta_tat) or None,
            "mo_ta_bang_chung": " ".join(bang_chung) or None,
            "trong_bo_bang_chung": bool(bang_chung),
            "dau_hieu_hoi_thoai": chat,
            "nhay_cam": bool(NHAY_CAM.search(duong_dan)),
            "hinh": hinh,
        })

    if tron_chuan_hoa:
        de_xuat.append({
            "loai": "chuan_hoa_unicode", "so_tep": tron_chuan_hoa,
            "ghi_chu": "trường `source` trong ade_out trộn NFC với NFD nên cùng một "
                       "thư mục hồ sơ đếm ra hai khoá khác nhau; sổ này chuẩn hoá NFC "
                       "khi gom nhóm, kho gốc giữ nguyên",
        })

    return {"tai_lieu": tai_lieu, "de_xuat_sua": de_xuat}


def gom_ho_so(tai_lieu: list[dict]) -> list[dict]:
    """Gom theo hồ sơ, để câu hỏi 'tác phẩm này là cái gì' trả lời được ngay
    từ sổ, không phải mở lại ảnh."""
    theo: dict[str, dict] = {}
    for t in tai_lieu:
        k = t["ho_so"] or "(không rõ)"
        o = theo.setdefault(k, {
            "ho_so": k, "muc": t["muc"], "so_anh": 0,
            "vai": {}, "mo_ta_bang_chung": [],
        })
        o["so_anh"] += 1
        o["vai"][t["vai"]] = o["vai"].get(t["vai"], 0) + 1
        if t["mo_ta_bang_chung"]:
            o["mo_ta_bang_chung"].append({
                "ten_tep": t["ten_tep"], "vai": t["vai"],
                "mo_ta": t["mo_ta_bang_chung"],
            })
    return sorted(theo.values(), key=lambda o: o["ho_so"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ra", type=Path, default=DICH, help=f"sổ ra (mặc định {DICH})")
    ap.add_argument("--im", action="store_true", help="không in tóm tắt")
    args = ap.parse_args()

    if not NGUON.is_dir():
        raise SystemExit(f"không thấy kho {NGUON}")

    kq = quet()
    tai_lieu = kq["tai_lieu"]

    dem_vai: dict[str, int] = {}
    for t in tai_lieu:
        dem_vai[t["vai"]] = dem_vai.get(t["vai"], 0) + 1

    so = {
        "tao_luc": datetime.now(timezone.utc).isoformat(),
        "nguon": str(NGUON),
        "credit_da_tieu": 0,
        "ghi_chu": "Sổ đọc lại kết quả ADE Pro đã có sẵn. Không gọi ADE, không gọi "
                   "model thị giác. Sổ chỉ mang mô tả thị giác, KHÔNG mang toàn văn "
                   "OCR — toàn văn có số căn cước và số tài khoản.",
        "tong": {
            "anh": len(tai_lieu),
            "co_mo_ta": sum(1 for t in tai_lieu if t["so_mo_ta"]),
            "so_mo_ta": sum(t["so_mo_ta"] for t in tai_lieu),
            # 84 khối nằm trong thẻ <description>; khối thứ 85 là một <figure>
            # ADE Pro trả về không kèm thẻ, chữ vẫn là chữ model đã sinh.
            "so_the_description": sum(t["so_the_description"] for t in tai_lieu),
            "co_the_description": sum(1 for t in tai_lieu if t["so_the_description"]),
            "so_mo_ta_giao_dien": sum(t["so_mo_ta_giao_dien"] for t in tai_lieu),
            "trong_bo_bang_chung": sum(1 for t in tai_lieu if t["trong_bo_bang_chung"]),
            "anh_hoi_thoai_theo_dau_hieu": sum(1 for t in tai_lieu if t["dau_hieu_hoi_thoai"]),
            "vai": dem_vai,
        },
        "luat_vai": [{"ma": m, "vai": v, "vai_en": VAI_EN[v], "pham_vi": p,
                      "mau": x, "vi_sao": s} for m, v, p, x, s in LUAT_VAI]
                    + [{"ma": LUAT_DU[0], "vai": LUAT_DU[1], "vai_en": VAI_EN[LUAT_DU[1]],
                        "pham_vi": "du", "mau": None, "vi_sao": LUAT_DU[2]}],
        "ho_so": gom_ho_so(tai_lieu),
        "tai_lieu": tai_lieu,
        "de_xuat_sua": kq["de_xuat_sua"],
    }

    ra: Path = args.ra
    ra.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(ra.parent, 0o700)
    ra.write_text(json.dumps(so, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(ra, 0o600)

    if not args.im:
        t = so["tong"]
        print(f"{ra}: {t['anh']} ảnh, {t['co_mo_ta']} tấm có mô tả "
              f"({t['so_mo_ta']} khối, {t['so_mo_ta_giao_dien']} khối là chrome), "
              f"{t['trong_bo_bang_chung']} tấm vào bộ bằng chứng")
        for v, n in sorted(dem_vai.items(), key=lambda kv: -kv[1]):
            print(f"  {v:<15} {n:>3}  ({VAI_EN[v]})")
        if so["de_xuat_sua"]:
            print(f"  đề xuất sửa: {len(so['de_xuat_sua'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
