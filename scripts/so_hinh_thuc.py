#!/usr/bin/env python3
"""Sổ hình thức: bắt ảnh chụp chat đang giữ ô sản phẩm, chấm ba mức.

Tên tệp đúng, đuôi đúng, cổng P2 xanh — vẫn có thể là sản phẩm bàn giao cho
khách chỉ là một tấm ảnh chụp màn hình Telegram. Cổng của `so_anh_xa.py` khớp
TÊN (và bỏ qua đuôi), nên nó không thấy được. Hình thức là trường của SỔ;
BPMN không nói gì về nó, và script này không sửa BPMN.

    uv run python scripts/so_hinh_thuc.py

LUẬT RẺ (không gọi ADE, không gọi model — 0 credit)
────────────────────────────────────────────────────
    chỉ một khung ảnh  ∧  không tiêu đề  ∧  không bảng  ∧  có emoji
        ⇒  ảnh chụp chat

Từng mệnh đề đọc từ đâu:

  một khung ảnh  cấu trúc TỆP GỐC, qua `phan_loai` của `so_ban_sach.py`:
                 tệp ảnh rời, pdf không lớp text, docx chỉ có ảnh nhúng — và
                 đúng MỘT khung (1 trang pdf / 1 ảnh nhúng). ADE Pro không trả
                 được mệnh đề này: nó OCR ảnh chụp thành khối text và không để
                 lại khối figure nào cho trang (xem `ghi_chu` trong sổ).
  không tiêu đề  markdown ADE không có dòng `#`. Pro không có loại khối
                 "title"; tiêu đề chỉ hiện dưới dạng dòng `#`.
  không bảng     markdown ADE không có `<table`.
  có emoji       ít nhất một ký tự hình trong U+1F300–U+1FAFF (xem `RX_EMOJI`).

Tệp gốc chỉ được mở khi ba mệnh đề chữ cùng đúng hoặc có khung chat; còn lại
`cau_truc` = "khong_xet" và `mot_khung_anh` = None (mở mupdf cả kho mất ~5 phút).

Một tín hiệu thứ hai, ĐỘC LẬP với luật: `dau_hieu_chat` của `so_vai_anh.py`
(dòng "N thành viên", hoặc ≥ 2 icon thanh công cụ chat). Nó chỉ để đối chiếu,
KHÔNG đổi mức: hai tín hiệu vênh nhau thì tệp vào `khong_quyet_duoc` — đầu
vào cho agent backlog — và được đo cạnh luật trong `do_chinh_xac`.

BA MỨC (chỉ cắn ở tệp đang giữ một ô sản phẩm của sổ ánh xạ q1)
─────────────────────────────────────────────────────────────
  dat                        không phải ảnh chụp chat, hoặc không giữ ô sản
                             phẩm nào nên cổng không đòi hình thức ở tệp này
  du_noi_dung_sai_hinh_thuc  ảnh chụp chat giữ ô sản phẩm, nhưng nội dung tối
                             thiểu của ô có đủ (`NOI_DUNG_TOI_THIEU`). Cổng
                             GIỮ XANH, gắn cờ `nợ hình thức` lên bảng việc.
  khong_dat                  ảnh chụp chat giữ ô sản phẩm và thiếu nội dung
                             tối thiểu. Ô không được tính; cổng đỏ nếu không
                             còn tệp nào khác đạt ở ô đó.

Mức chỉ do luật rẻ đặt. Ảnh chụp chat giữ ô chưa có luật nội dung thì luật
không kiểm được nội dung: ô đó KHÔNG có mức (`muc` = None, không đếm vào mức
nào, không vào mức giữa hay bảng việc) và chỉ vào `khong_quyet_duoc`. Ô mà
một tệp nguồn khác của q1 chưa có parse ADE thì luật không thấy hết người giữ
ô: bảng việc không gắn cờ, không lật đỏ, ô vào `khong_quyet_duoc`.

Sổ ra `~/.private/so/hinh_thuc.json` quyền 700/600 — nó dẫn chiếu hồ sơ khách
hàng nên KHÔNG nằm trong cây dự án. Nhãn tay để đo độ chính xác đọc từ
`~/.private/so/hinh_thuc_nhan_tay.json` nếu có.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from so_ban_sach import HienVat, _do_docx, phan_loai    # noqa: E402
from so_vai_anh import dau_hieu_chat                     # noqa: E402

NGUON = Path.home() / ".private" / "ade_out"
KHO = Path.home() / ".private" / "refiny_data"
SO_ANH_XA = Path.home() / ".private" / "so" / "anh_xa_ten_goi.json"
NHAN_TAY = Path.home() / ".private" / "so" / "hinh_thuc_nhan_tay.json"
DICH = Path.home() / ".private" / "so" / "hinh_thuc.json"

TEP_META = "meta_pro.json"
# Bản Pro mới nhất trước. Trên 43 tệp có cả hai bản, bốn tín hiệu của luật
# giống hệt nhau giữa parse_pro và parse_pro2.
TEP_PARSE = ("parse_pro2.json", "parse_pro.json")

#: Lô toàn kho chạy ngày này; mọi bản Pro parse TRƯỚC ngày đó là lô 199 tài
#: liệu mà luật được đặt ra để chấm.
NGAY_LO_TOAN_KHO = "2026-09-22"

DUOI_ANH = {".jpg", ".jpeg", ".png", ".heic", ".webp"}

RX_TIEU_DE = re.compile(r"(?m)^#{1,6}\s")
RX_BANG = re.compile(r"<table\b")
# Chỉ lấy khối ký tự hình ở mặt phẳng phụ. Ký hiệu BMP như ★ ✓ ✎ ➡ bị loại:
# ★ có ở 37 tệp của lô 199 và không tệp nào trong đó là ảnh chụp chat — đó là
# ký hiệu chấm sao, dấu tích của văn bản gõ, không phải emoji của khung chat.
RX_EMOJI = re.compile("[\U0001F300-\U0001FAFF]")
RX_NEO = re.compile(r"<a id=[^>]*></a>|<!--.*?-->", re.S)

MUC = ("dat", "du_noi_dung_sai_hinh_thuc", "khong_dat")
MUC_VI = {
    "dat": "Đạt",
    "du_noi_dung_sai_hinh_thuc": "Đủ nội dung – sai hình thức",
    "khong_dat": "Không đạt",
}
# Tệp giữ nhiều ô thì mức của tệp là mức nặng nhất trong các ô.
NANG = {"khong_dat": 2, "du_noi_dung_sai_hinh_thuc": 1, "dat": 0}
CO_NO = "nợ hình thức"


def khong_dau(s: str) -> str:
    """Hạ chữ, bỏ dấu, GIỮ dấu câu và `%`. `đ` phải thay trước khi NFD."""
    s = s.replace("Đ", "D").replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


# --------------------------------------------------------------------------
# Nội dung tối thiểu của một ô sản phẩm, khoá theo `cho_muc` của sổ q1.
# Mỗi yêu cầu: (mã, mô tả, mẫu trên văn bản đã bỏ dấu). Ô nào không có ở đây
# thì luật rẻ không quyết được nội dung — ảnh chụp chat ở ô đó không có mức
# và vào `khong_quyet_duoc`, không tự đoán.
# --------------------------------------------------------------------------
NOI_DUNG_TOI_THIEU: dict[str, list[tuple[str, str, re.Pattern]]] = {
    # N_2_3 "So sánh đối chứng, lập Báo cáo tra cứu".
    "ket qua tra cuu": [
        ("ket_luan", "kết luận khả năng bảo hộ kèm tỉ lệ",
         re.compile(r"kha nang (?:duoc )?(?:bao ho|dang ky)[^.\n%]{0,30}?\d{1,3}(?:[.,]\d+)?\s*%")),
        ("doi_chung", "danh sách đối chứng (số văn bằng / số đơn) hoặc câu nói không có đối chứng",
         re.compile(r"(?:van bang(?: bao ho)?|don dang ky|registration|serial)(?: no\.?| so)?"
                    r"\s*:?\s*(?:\d{6,}|\d-\d{4}-\d{5,})"
                    r"|(?:khong|chua) phat hien[^.\n]{0,30}(?:doi chung|nhan hieu)")),
    ],
}


def _doc_json(f: Path) -> dict | None:
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def tin_hieu(markdown: str) -> dict:
    """Ba mệnh đề đọc từ markdown ADE, cộng tín hiệu khung chat độc lập."""
    emoji = RX_EMOJI.findall(markdown)
    return {
        "so_tieu_de": len(RX_TIEU_DE.findall(markdown)),
        "so_bang": len(RX_BANG.findall(markdown)),
        "so_emoji": len(emoji),
        "emoji": sorted(set(emoji))[:8],
        "khung_chat": dau_hieu_chat(markdown),
    }


def so_khung_anh(duong_dan: Path, cau_truc: str, so_trang: int | None) -> int:
    """Số khung ảnh làm nên tài liệu; 0 nếu tài liệu có lớp chữ thật."""
    if cau_truc != "anh_chup":
        return 0
    duoi = duong_dan.suffix.lower()
    if duoi in DUOI_ANH:
        return 1
    if duoi == ".docx":
        return _do_docx(duong_dan)[0]
    return so_trang or 0


def menh_de(th: dict) -> dict:
    return {
        # None: không mở tệp gốc vì mệnh đề chữ đã trượt.
        "mot_khung_anh": None if th["so_khung_anh"] is None else th["so_khung_anh"] == 1,
        "khong_tieu_de": th["so_tieu_de"] == 0,
        "khong_bang": th["so_bang"] == 0,
        "co_emoji": th["so_emoji"] > 0,
    }


def luat_re(md: dict) -> bool:
    return all(v is True for v in md.values())


def kiem_noi_dung(cho_muc: str, markdown: str) -> dict | None:
    """None nếu ô chưa có luật nội dung; ngược lại liệt kê yêu cầu thiếu."""
    yeu_cau = NOI_DUNG_TOI_THIEU.get(cho_muc)
    if yeu_cau is None:
        return None
    t = khong_dau(markdown)
    thieu = [{"ma": ma, "mo_ta": mo_ta} for ma, mo_ta, rx in yeu_cau if not rx.search(t)]
    return {"du": not thieu, "thieu": thieu}


def cham_o(chat: bool, cho_muc: str, markdown: str) -> tuple[str | None, str, dict | None]:
    """Chấm MỘT ô sản phẩm mà tệp đang giữ. Trả (mức, lý do, kết quả nội dung)."""
    if not chat:
        return "dat", "luật rẻ không bắn — không phải ảnh chụp chat", None
    nd = kiem_noi_dung(cho_muc, markdown)
    if nd is None:
        return None, f"chưa có luật nội dung cho '{cho_muc}'", None
    if nd["du"]:
        return ("du_noi_dung_sai_hinh_thuc",
                f"ảnh chụp chat giữ ô '{cho_muc}'; nội dung tối thiểu có đủ", nd)
    return ("khong_dat",
            f"ảnh chụp chat giữ ô '{cho_muc}'; thiếu: "
            + ", ".join(x["mo_ta"] for x in nd["thieu"]), nd)


def vi_sao_venh(md: dict, khung_chat: bool) -> str:
    if khung_chat:
        chan = [k for k, v in md.items() if not v]
        return "có khung chat nhưng luật không bắn vì trượt: " + ", ".join(chan)
    return "luật bắn (1 khung, không tiêu đề, không bảng, có emoji) nhưng không thấy khung chat"


# ── Nạp sổ q1 và q15 ─────────────────────────────────────────────────────

def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def ho_so_cua(duong_dan: str) -> str | None:
    doan = duong_dan.split("/")
    return doan[2].strip() if len(doan) > 3 else None


def nap_o_san_pham(so_anh_xa: dict) -> tuple[dict[str, list[dict]], dict]:
    """(đường dẫn → các ô nó giữ, (hồ sơ, khoá) → các dòng cổng của q1)."""
    theo_tep: dict[str, list[dict]] = {}
    for khoa, v in so_anh_xa.get("anh_xa", {}).items():
        mau = {m["ten"]: m["nguyen_van"] for m in v.get("muc_bat_buoc", [])}
        hoat_dong = [h["id"] for h in v.get("hoat_dong", [])]
        for t in v.get("ten_goi_chap_nhan", []):
            for n in t.get("nguon", []):
                o = {"khoa": khoa, "cho_muc": t["cho_muc"], "mau_ten": mau.get(t["cho_muc"]),
                     "hoat_dong": hoat_dong, "phuong_phap_ten": t.get("phuong_phap")}
                lst = theo_tep.setdefault(nfc(n), [])
                if o not in lst:
                    lst.append(o)
    cong: dict[tuple[str, str], list[dict]] = {}
    for r in so_anh_xa.get("do_luong", {}).get("chi_tiet", []):
        cong.setdefault((nfc(r["ho_so"]).strip(), r["khoa"]), []).append(r)
    return theo_tep, cong


# ── Quét ─────────────────────────────────────────────────────────────────

def quet(nguon: Path, kho: Path, theo_tep: dict[str, list[dict]]) -> list[dict]:
    out: list[dict] = []
    for d in sorted(os.listdir(nguon)):
        thu_muc = nguon / d
        meta = _doc_json(thu_muc / TEP_META)
        if not meta:
            continue
        parse, tep_parse = None, None
        for t in TEP_PARSE:
            parse = _doc_json(thu_muc / t)
            if parse is not None:
                tep_parse = t
                break
        if parse is None:
            continue
        markdown = RX_NEO.sub("", parse.get("markdown") or "")
        duong_dan = nfc(meta.get("source", ""))
        so_trang = (parse.get("metadata") or {}).get("page_count")

        th = {"so_trang": so_trang, **tin_hieu(markdown)}
        # Mở tệp gốc (mupdf, zip) chỉ khi tín hiệu chữ còn để ngỏ khả năng chat:
        # ba mệnh đề chữ cùng đúng, hoặc có khung chat để đối chiếu vênh.
        tep = kho / meta.get("source", "")
        if not (th["khung_chat"]
                or (th["so_tieu_de"] == 0 and th["so_bang"] == 0 and th["so_emoji"] > 0)):
            cau_truc, ly_do_cau_truc, khung = ("khong_xet",
                                               "tín hiệu chữ đã loại — không mở tệp gốc", None)
        elif tep.exists():
            hv = HienVat(duong_dan, tep)
            phan_loai(hv)
            cau_truc, ly_do_cau_truc = hv.loai, hv.ly_do
            khung = so_khung_anh(tep, cau_truc, so_trang)
        else:
            cau_truc, ly_do_cau_truc, khung = "khong_thay_tep", "tệp gốc không còn trong kho", 0
        th.update(cau_truc=cau_truc, ly_do_cau_truc=ly_do_cau_truc, so_khung_anh=khung)
        md = menh_de(th)
        chat = luat_re(md)
        venh = chat != th["khung_chat"]

        o_list = [dict(o) for o in theo_tep.get(duong_dan, [])]
        for o in o_list:
            o["muc"], o["ly_do"], o["noi_dung"] = cham_o(chat, o["cho_muc"], markdown)
        if o_list:
            co_muc = [o["muc"] for o in o_list if o["muc"] is not None]
            muc = max(co_muc, key=NANG.__getitem__) if co_muc else None
            ly_do = "; ".join(sorted({o["ly_do"] for o in o_list}))
        else:
            muc = "dat"
            ly_do = "không giữ ô sản phẩm nào — cổng không đòi hình thức ở tệp này"

        out.append({
            "id": d,
            "duong_dan": duong_dan,
            "ho_so": ho_so_cua(duong_dan),
            "parse_luc": meta.get("parsed_at"),
            "lo_199": (meta.get("parsed_at") or "") < NGAY_LO_TOAN_KHO,
            "tep_parse": tep_parse,
            "tin_hieu": th,
            "menh_de": md,
            "luat_re": chat,
            "venh": venh,
            "vi_sao_venh": vi_sao_venh(md, th["khung_chat"]) if venh else None,
            "hinh_thuc": "anh_chup_chat" if chat else cau_truc,
            "o_san_pham": o_list,
            "muc": muc,
            "ly_do": ly_do,
        })
    return out


# ── Bảng việc ────────────────────────────────────────────────────────────

def nguon_chua_parse(theo_tep: dict[str, list[dict]],
                     tai_lieu: list[dict]) -> dict[tuple[str, str, str], list[str]]:
    """(hồ sơ, khoá, chỗ mục) → các tệp nguồn q1 của ô đó chưa có parse ADE."""
    da_parse = {t["duong_dan"] for t in tai_lieu}
    out: dict[tuple[str, str, str], list[str]] = {}
    for duong_dan, o_list in theo_tep.items():
        if duong_dan in da_parse:
            continue
        for o in o_list:
            out.setdefault((ho_so_cua(duong_dan), o["khoa"], o["cho_muc"]), []).append(duong_dan)
    return out


def o_chua_dat(tai_lieu: list[dict]) -> dict[tuple[str, str, str], list[tuple[dict, dict]]]:
    """(hồ sơ, khoá, chỗ mục) → (tệp, ô) của các ô không có tệp đã parse nào đạt."""
    o: dict[tuple[str, str, str], list[tuple[dict, dict]]] = {}
    for t in tai_lieu:
        for s in t["o_san_pham"]:
            if s["muc"] is not None:
                o.setdefault((t["ho_so"], s["khoa"], s["cho_muc"]), []).append((t, s))
    return {k: cap for k, cap in o.items() if all(s["muc"] != "dat" for _, s in cap)}


def bang_viec(tai_lieu: list[dict], cong: dict,
              chua_parse: dict | None = None) -> list[dict]:
    """Một dòng cho mỗi cổng q1 mà hình thức làm thay đổi điều bảng việc hiện.

    Mức giữa chỉ gắn cờ khi KHÔNG có tệp nào khác cùng hồ sơ đạt ở cùng ô;
    có bản đạt thì ô đã được trả đúng hình thức, không còn nợ. Ô còn tệp nguồn
    chưa parse thì bỏ qua — tệp đó có thể là bản đạt.
    """
    chua_parse = chua_parse or {}
    dong: list[dict] = []
    for (ho_so, khoa, cho_muc), cap in sorted(o_chua_dat(tai_lieu).items()):
        if (ho_so, khoa, cho_muc) in chua_parse:
            continue
        muc = [s["muc"] for _, s in cap]
        trang_thai = "no_hinh_thuc" if "du_noi_dung_sai_hinh_thuc" in muc else "khong_dat"
        tep = [{"id": t["id"], "duong_dan": t["duong_dan"], "muc": s["muc"]} for t, s in cap]
        for r in cong.get((ho_so, khoa), []) or [{"hoat_dong": None, "sau": None, "so_do": None}]:
            q1 = r.get("sau")
            if trang_thai == "no_hinh_thuc":
                sau, co = q1, ([CO_NO] if q1 == "xanh" else [])
            else:
                sau, co = "do", []
            mau = cap[0][1]["mau_ten"]
            viec = {
                "no_hinh_thuc": f"phát hành lại đúng mẫu `{mau}` cho khách — nội dung đã đủ "
                                "trong ảnh chụp, chỉ còn nợ hình thức",
                "khong_dat": f"lập `{mau}`: ảnh chụp đang giữ ô thiếu nội dung tối thiểu",
            }[trang_thai]
            dong.append({
                "ho_so": ho_so, "hoat_dong": r.get("hoat_dong"), "so_do": r.get("so_do"),
                "khoa": khoa, "cho_muc": cho_muc, "mau_ten": mau,
                "cong_q1": q1, "cong_sau_hinh_thuc": sau, "co": co,
                "trang_thai": trang_thai, "tep": tep, "viec_con_no": viec,
            })
    return dong


# ── Đo bằng nhãn tay ─────────────────────────────────────────────────────

def do_chinh_xac(tai_lieu: list[dict], nhan: dict[str, dict]) -> dict:
    """So hai tín hiệu với nhãn tay `chat: true|false` trên mẫu đã gán."""
    theo_id = {t["id"]: t for t in tai_lieu}
    mau = [(theo_id[i], bool(v["chat"])) for i, v in nhan.items()
           if i in theo_id and v.get("chat") is not None]

    def bang(du_doan) -> dict:
        tp = sum(1 for t, y in mau if du_doan(t) and y)
        fp = sum(1 for t, y in mau if du_doan(t) and not y)
        fn = sum(1 for t, y in mau if not du_doan(t) and y)
        tn = sum(1 for t, y in mau if not du_doan(t) and not y)
        return {
            "dung_duong": tp, "sai_duong": fp, "sot": fn, "dung_am": tn,
            "do_chinh_xac": round(tp / (tp + fp), 3) if tp + fp else None,
            "do_phu": round(tp / (tp + fn), 3) if tp + fn else None,
            "dung_tren_mau": round((tp + tn) / len(mau), 3) if mau else None,
            "sai_duong_id": [t["id"] for t, y in mau if du_doan(t) and not y],
            "sot_id": [t["id"] for t, y in mau if not du_doan(t) and y],
        }

    return {
        "co_mau": len(mau),
        "so_chat_theo_nhan": sum(1 for _, y in mau if y),
        "luat_re": bang(lambda t: t["luat_re"]),
        "khung_chat": bang(lambda t: t["tin_hieu"]["khung_chat"]),
    }


def khong_quyet_duoc(tai_lieu: list[dict], chua_parse: dict | None = None) -> list[dict]:
    """Ca luật rẻ không tự quyết được — đầu vào cho agent backlog."""
    chua_parse = chua_parse or {}
    bo_qua = {k: v for k, v in chua_parse.items() if k in o_chua_dat(tai_lieu)}
    out = []
    for t in tai_lieu:
        ly_do = []
        if t["venh"]:
            ly_do.append(t["vi_sao_venh"])
        for o in t["o_san_pham"]:
            if o["muc"] is None:
                ly_do.append(o["ly_do"])
            k = (t["ho_so"], o["khoa"], o["cho_muc"])
            if k in bo_qua:
                ly_do.append(f"ô '{o['cho_muc']}' còn tệp nguồn chưa có parse ADE: "
                             + ", ".join(p.split("/")[-1] for p in bo_qua[k])
                             + " — không biết ô đã có bản đạt chưa")
        if ly_do:
            out.append({"id": t["id"], "duong_dan": t["duong_dan"], "lo_199": t["lo_199"],
                        "muc": t["muc"], "giu_o_san_pham": bool(t["o_san_pham"]),
                        "ly_do": ly_do})
    return out


def dem(tai_lieu: list[dict]) -> dict:
    m = {k: 0 for k in MUC}
    for t in tai_lieu:
        if t["muc"] is not None:
            m[t["muc"]] += 1
    return {
        "tai_lieu": len(tai_lieu),
        "muc": m,
        "khong_muc": sum(1 for t in tai_lieu if t["muc"] is None),
        "luat_re_ban": sum(1 for t in tai_lieu if t["luat_re"]),
        "khung_chat": sum(1 for t in tai_lieu if t["tin_hieu"]["khung_chat"]),
        "venh": sum(1 for t in tai_lieu if t["venh"]),
        "giu_o_san_pham": sum(1 for t in tai_lieu if t["o_san_pham"]),
    }


def lap_so(nguon: Path = NGUON, kho: Path = KHO, so_anh_xa: Path = SO_ANH_XA,
           nhan_tay: Path = NHAN_TAY) -> dict:
    theo_tep, cong = nap_o_san_pham(_doc_json(so_anh_xa) or {})
    tai_lieu = quet(nguon, kho, theo_tep)
    chua_parse = nguon_chua_parse(theo_tep, tai_lieu)
    nhan = (_doc_json(nhan_tay) or {}).get("nhan", {})

    lo = [t for t in tai_lieu if t["lo_199"]]
    muc_giua = [{"id": t["id"], "duong_dan": t["duong_dan"], "lo_199": t["lo_199"],
                 "o": [(o["hoat_dong"], o["cho_muc"], o["mau_ten"]) for o in t["o_san_pham"]
                       if o["muc"] == "du_noi_dung_sai_hinh_thuc"]}
                for t in tai_lieu if t["muc"] == "du_noi_dung_sai_hinh_thuc"]
    return {
        "tao_luc": datetime.now(timezone.utc).isoformat(),
        "nguon": {"ade_out": str(nguon), "kho": str(kho), "so_anh_xa": str(so_anh_xa)},
        "credit_da_tieu": 0,
        "ghi_chu": "Luật rẻ đọc bản parse ADE Pro đã có và cấu trúc tệp gốc; không gọi "
                   "model. 'Một khung ảnh' phải đọc từ tệp gốc vì ADE Pro OCR ảnh chụp "
                   "thành khối text và không để lại khối figure. Sổ không mang toàn văn "
                   "OCR. Cổng q1 không bị ghi đè: `cong_sau_hinh_thuc` là đề xuất.",
        "luat": {
            "menh_de": ["mot_khung_anh", "khong_tieu_de", "khong_bang", "co_emoji"],
            "emoji": "U+1F300–U+1FAFF",
            "tin_hieu_doi_chieu": "so_vai_anh.dau_hieu_chat",
            "noi_dung_toi_thieu": {k: [{"ma": m, "mo_ta": d} for m, d, _ in v]
                                   for k, v in NOI_DUNG_TOI_THIEU.items()},
            "muc": MUC_VI,
        },
        "tong": {"lo_199": dem(lo), "toan_kho": dem(tai_lieu)},
        "muc_giua": muc_giua,
        "bang_viec": bang_viec(tai_lieu, cong, chua_parse),
        "khong_quyet_duoc": khong_quyet_duoc(tai_lieu, chua_parse),
        "do_chinh_xac": do_chinh_xac(tai_lieu, nhan) if nhan else None,
        "tai_lieu": tai_lieu,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ra", type=Path, default=DICH, help=f"sổ ra (mặc định {DICH})")
    ap.add_argument("--im", action="store_true", help="không in tóm tắt")
    args = ap.parse_args()

    if not NGUON.is_dir():
        raise SystemExit(f"không thấy kho {NGUON}")
    so = lap_so()

    ra: Path = args.ra
    tao_moi = not ra.parent.exists()
    ra.parent.mkdir(parents=True, exist_ok=True)
    if tao_moi or ra.parent.resolve().is_relative_to((Path.home() / ".private").resolve()):
        os.chmod(ra.parent, 0o700)
    ra.write_text(json.dumps(so, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(ra, 0o600)

    if not args.im:
        for pham_vi, t in so["tong"].items():
            m = t["muc"]
            print(f"{pham_vi}: {t['tai_lieu']} tài liệu — "
                  + " · ".join(f"{MUC_VI[k]} {m[k]}" for k in MUC)
                  + f"  (không mức {t['khong_muc']}, luật bắn {t['luat_re_ban']}, khung chat {t['khung_chat']}, "
                    f"vênh {t['venh']})")
        for g in so["muc_giua"]:
            print(f"  mức giữa: {g['id']}  {g['duong_dan'].split('/')[-1]}")
        for b in so["bang_viec"]:
            print(f"  bảng việc: {b['hoat_dong']} {b['cho_muc']} → {b['trang_thai']} "
                  f"cổng {b['cong_q1']}→{b['cong_sau_hinh_thuc']} {b['co']}")
        if so["do_chinh_xac"]:
            d = so["do_chinh_xac"]
            print(f"  nhãn tay: {d['co_mau']} tệp, luật rẻ chính xác "
                  f"{d['luat_re']['do_chinh_xac']} phủ {d['luat_re']['do_phu']}")
        print(f"  không quyết được: {len(so['khong_quyet_duoc'])}  → {ra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
