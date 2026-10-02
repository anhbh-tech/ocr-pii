#!/usr/bin/env python3
"""Chạy agent kiểm hình thức & rút số hiệu trên các tài liệu CHỐT CỔNG của một hồ sơ.

    uv run python scripts/agent_hinh_thuc.py --diem-cong "<thư mục hồ sơ>"   # liệt kê, không gọi model
    uv run python scripts/agent_hinh_thuc.py --doc-id ID [--doc-id ID ...]  # ước lượng, không gọi model
    uv run python scripts/agent_hinh_thuc.py --doc-id ID ... --goi          # gọi model thật
    uv run python scripts/agent_hinh_thuc.py --doc-id ID ... --kiem-lai     # kiểm lại câu đã lưu, 0 đồng

Lõi (lời nhắc, gọi model, kiểm dòng trích) ở `src/ocr_lab/agent_hinh_thuc.py`.
Script này nạp bốn đầu vào, đối chiếu kết quả với sổ, ghi sổ và ghi ngược:

  vào   mục bắt buộc   `anh_xa_ten_goi.json` (bảng ánh xạ, không phải BPMN)
        nội dung ADE   `ade_out/<id>/parse_pro2|parse_pro|parse.json`
        tên tệp        đường dẫn trong hồ sơ — PHỎNG ĐOÁN, đi sau nội dung
        sổ số hiệu     `so_hieu.json`, chỉ các dòng có mặt trong tài liệu
                       cộng số công khai của ta (không gửi số nhạy cảm thừa)
  ra    `~/.private/so/agent_hinh_thuc.json` (0600), gộp theo doc_id

CHỈ Ở CHỖ QUYẾT ĐỊNH CỔNG
─────────────────────────
Không có chế độ quét cả kho. Tài liệu phải nêu từng `--doc-id`, tối đa
`TRAN_MOI_LUOT`; `--diem-cong` gợi ý các tệp đang giữ một ô sản phẩm của bảng
ánh xạ trong hồ sơ. Mở rộng ra cả kho là quyết định của chủ kho, sau khi đã
thấy chi phí thật mỗi tài liệu — sửa hằng đó chính là quyết định ấy.

GHI NGƯỢC VÀO BẢNG ÁNH XẠ
─────────────────────────
Agent nhận ra tài liệu đáp ứng mục M của khoá K, bảng ánh xạ chưa gắn tệp đó
vào (K, M), và lõi tên tệp (`so_anh_xa.chuan_hoa`) chưa là cách gọi nào của K
mà luật so từ cũng không bắc được cầu: đó là cách gọi MỚI. Nó được ghi vào
`anh_xa_phan_doan.json` (nguồn để `so_anh_xa.py` dựng lại sổ) và vào thẳng
`anh_xa_ten_goi.json`, kèm tệp nguồn và dòng trích. Chỉ ghi khi mục đáp ứng
ĐỦ (`co`), hình thức không `khong_dat` và độ chắc không "thấp" — tên tệp chỉ
là phỏng đoán, ghi bản một phần/sai hình thức thì lõi tên tệp tự làm xanh ô
cổng ở mọi hồ sơ; các ca ấy chuyển người. Bảng ánh xạ nói tệp giữ ô mà agent không thấy thì cũng chuyển
người, không xoá gì. `do_luong` của bảng ánh xạ chỉ đúng lại khi dựng lại.

Script không in số hiệu, tên tệp hay trích ra màn hình — chỉ doc_id và số đếm.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import so_anh_xa  # noqa: E402
import so_so_hieu  # noqa: E402
from ocr_lab import agent_hinh_thuc as ag  # noqa: E402
from ocr_lab.ade_store import doc_id_for  # noqa: E402

SO_DIR = Path.home() / ".private" / "so"
ADE_OUT = Path.home() / ".private" / "ade_out"
SO_ANH_XA = SO_DIR / "anh_xa_ten_goi.json"
PHAN_DOAN = SO_DIR / "anh_xa_phan_doan.json"
SO_HIEU = SO_DIR / "so_hieu.json"
DANH_TINH = SO_DIR / "danh_tinh.json"
RA = SO_DIR / "agent_hinh_thuc.json"

#: Trần tài liệu mỗi lượt. Một hồ sơ có vài tài liệu chốt cổng (báo cáo q4:
#: 5 trên 23); trần này chặn một vòng lặp lỡ tay chạy cả kho.
TRAN_MOI_LUOT = 8

#: Chỉ để ƯỚC LƯỢNG trước khi gọi (giá niêm yết Sonnet 5 mà CLI báo: $2/M
#: token vào, $10/M ra). Chi phí THẬT lấy từ `total_cost_usd` của từng lượt.
GIA_UOC_VAO, GIA_UOC_RA, TOKEN_RA_UOC = 2.0 / 1e6, 10.0 / 1e6, 2500


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _doc(p: Path) -> dict | None:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _ghi_rieng(p: Path, du_lieu) -> None:
    """Ghi nguyên tử, quyền 0600: sổ dẫn chiếu hồ sơ khách hàng."""
    p.parent.mkdir(parents=True, exist_ok=True)
    tam = p.with_name(p.name + ".tmp")
    tam.write_text(json.dumps(du_lieu, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(tam, 0o600)
    os.replace(tam, p)


# ── Nạp ──────────────────────────────────────────────────────────────────

def nap_tai_lieu(ade_out: Path, doc_id: str) -> dict | None:
    """Bản parse tốt nhất của một tài liệu: pro2 > pro > chuẩn (như sổ số hiệu)."""
    d = ade_out / doc_id
    for ten_meta, ten_parse, engine in so_so_hieu.BIEN_THE:
        meta, parse = _doc(d / ten_meta), _doc(d / ten_parse)
        if meta and parse:
            return {"doc_id": doc_id, "nguon": nfc(meta.get("source", "")), "engine": engine,
                    "markdown": parse.get("markdown") or ""}
    return None


def phan_duong_dan(rel: str) -> dict:
    """`Phòng/<nhóm>/<hồ sơ>/<…>/<tệp>` → nhóm, thư mục hồ sơ, phần trong hồ sơ."""
    doan = nfc(rel).split("/")
    thu_muc = doan[2] if len(doan) > 3 else ""
    return {
        "nhom": doan[1].strip() if len(doan) > 1 else "",
        "thu_muc_ho_so": thu_muc,
        "trong_ho_so": "/".join(doan[3:]) if len(doan) > 3 else doan[-1],
        "nhan_hieu": so_anh_xa.doan_nhan_hieu(thu_muc),
        "ma_so": (re.match(r"\s*(\d+)", thu_muc) or [None, ""])[1],
    }


def buoc_ung_vien(so_ax: dict, so_do: str | None) -> list[dict]:
    """Các bước có mục bắt buộc của đúng sơ đồ điều chỉnh hồ sơ, từ bảng ánh xạ."""
    ra = []
    for khoa, v in so_ax.get("anh_xa", {}).items():
        for hd in v.get("hoat_dong", []):
            if hd.get("so_do") == so_do:
                ra.append({"hoat_dong": hd["id"], "ten": hd["ten"], "khoa": khoa,
                           "muc": [{k: m.get(k) for k in ("ten", "nguyen_van", "trang_thai_bat_buoc", "ghi_chu")}
                                   for m in v.get("muc_bat_buoc", [])]})
    return ra


def o_dang_giu(so_ax: dict, rel: str) -> set[tuple[str, str]]:
    """(khoá, mục) mà bảng ánh xạ đang gắn tệp này vào."""
    rel = nfc(rel)
    return {(khoa, t["cho_muc"])
            for khoa, v in so_ax.get("anh_xa", {}).items()
            for t in v.get("ten_goi_chap_nhan", [])
            if rel in {nfc(n) for n in t.get("nguon", [])}}


def diem_cong(so_ax: dict, ho_so: str) -> dict[str, list[tuple[str, str, str]]]:
    """doc_id → [(hoạt động, khoá, mục)] của mọi tệp trong hồ sơ đang giữ một ô."""
    ra: dict[str, list] = {}
    for khoa, v in so_ax.get("anh_xa", {}).items():
        hd = v["hoat_dong"][0]["id"] if v.get("hoat_dong") else None
        for t in v.get("ten_goi_chap_nhan", []):
            for n in t.get("nguon", []):
                if phan_duong_dan(n)["thu_muc_ho_so"].strip() == ho_so.strip():
                    o = (hd, khoa, t["cho_muc"])
                    lst = ra.setdefault(doc_id_for(nfc(n)), [])
                    if o not in lst:
                        lst.append(o)
    return ra


def so_lien_quan(so_hieu: list[dict], ho_so: list[str], dong: dict[int, str]) -> list[dict]:
    """Dòng sổ số hiệu của hồ sơ mà tài liệu này cần để biết số nào là của ta.

    Chỉ số có mặt trong nội dung, cộng số công khai của ta (số đơn, văn bằng).
    Số nhạy cảm không có trong tài liệu thì không gửi đi.
    """
    chu = ag._chu_so(" ".join(dong.values()))
    ra = []
    for g in so_hieu:
        if g.get("ho_so") not in ho_so:
            continue
        co_mat = g["chuan"] != so_so_hieu.CHUA_CAP_SO and ag._chu_so(g["chuan"]) in chu
        if co_mat or (g["bang"] == so_so_hieu.CONG_KHAI and g["chu_so_huu"] == "ta"):
            ra.append({"loai": g["loai"], "gia_tri": g["gia_tri"], "chu_so_huu": g["chu_so_huu"],
                       "chuan": g["chuan"], "bang": g["bang"]})
    return ra


# ── Đối chiếu sau khi agent trả lời ───────────────────────────────────────

def doi_chieu_so(so_agent: list[dict], so_so: list[dict]) -> list[dict]:
    """Mỗi số agent rút ra: khớp sổ, lệch chủ với sổ, hay sổ chưa có."""
    ra = []
    for s in so_agent:
        if s["gia_tri"] == so_so_hieu.CHUA_CAP_SO:
            # Sổ không giữ dòng "chưa cấp số" để so; nói "mới" là sai.
            ra.append({**s, "so_voi_so": {"trang_thai": "chua_cap_so"}})
            continue
        chuan = so_so_hieu.chuan_gia_tri(s.get("loai", ""), s["gia_tri"])
        trung = [g for g in so_so if g["chuan"] == chuan or ag._chu_so(g["chuan"]) == ag._chu_so(s["gia_tri"])]
        if not trung:
            tt = {"trang_thai": "moi"}
        elif any(g["chu_so_huu"] == s["chu_so_huu"] for g in trung):
            tt = {"trang_thai": "khop"}
        else:
            tt = {"trang_thai": "lech_chu", "chu_trong_so": sorted({g["chu_so_huu"] for g in trung})}
        if trung and all(g["loai"] != s.get("loai") for g in trung):
            tt["loai_trong_so"] = sorted({g["loai"] for g in trung})
        ra.append({**s, "so_voi_so": tt})
    return ra


def doi_chieu_anh_xa(kq: dict, giu: set[tuple[str, str]]) -> dict:
    """Agent nói tài liệu đáp ứng (khoá, mục) nào; bảng ánh xạ đang gắn nó vào đâu."""
    khoa = (kq.get("buoc") or {}).get("khoa")
    agent = {(khoa, m["muc"]) for m in kq.get("muc_bat_buoc", []) if khoa and m["dap_ung"] != "thieu"}
    return {
        "anh_xa_giu": sorted(giu),
        "agent_nhan": sorted(agent),
        "chi_agent": sorted(agent - giu),
        "chi_anh_xa": sorted(giu - agent),
        "trang_thai": "khop" if agent == giu else ("agent_moi" if giu <= agent else "lech"),
    }


def cach_goi_moi(kq: dict, rel: str, so_ax: dict, doi: dict) -> tuple[list[dict], list[dict]]:
    """(cách gọi mới cần ghi ngược, các ô agent thấy mà không cần ghi — kèm lý do)."""
    if kq.get("do_chac") == "thap":
        return [], [{"o": o, "ly_do": "độ chắc thấp — chuyển người"} for o in doi["chi_agent"]]
    pd = phan_duong_dan(rel)
    loi, _tt = so_anh_xa.chuan_hoa(Path(rel).name, pd["nhan_hieu"], pd["ma_so"])
    theo_muc = {m["muc"]: m for m in kq.get("muc_bat_buoc", [])}
    hinh_thuc = (kq.get("hinh_thuc") or {}).get("muc")
    moi, bo_qua = [], []
    for khoa, muc in doi["chi_agent"]:
        v = so_ax["anh_xa"][khoa]
        if theo_muc[muc]["dap_ung"] != "co":
            bo_qua.append({"o": [khoa, muc], "ly_do": "mục chỉ đáp ứng một phần — tên tệp chưa đủ làm cách gọi"})
        elif hinh_thuc == "khong_dat":
            bo_qua.append({"o": [khoa, muc], "ly_do": "hình thức không đạt — tên tệp chưa đủ làm cách gọi"})
        elif not loi:
            bo_qua.append({"o": [khoa, muc], "ly_do": "tên tệp không còn lõi nào sau chuẩn hoá"})
        elif any(t["ten"] == loi and t.get("cho_muc") == muc for t in v.get("ten_goi_chap_nhan", [])):
            bo_qua.append({"o": [khoa, muc], "ly_do": "cách gọi đã có, chỉ thiếu nguồn — dựng lại sổ"})
        elif so_anh_xa.khop(muc, loi):
            bo_qua.append({"o": [khoa, muc], "ly_do": "luật so từ đã bắc cầu — dựng lại sổ"})
        else:
            m = theo_muc[muc]
            moi.append({
                "khoa": khoa, "ten": loi, "cho_muc": muc, "nguon": nfc(rel), "phuong_phap": "agent",
                "ly_do": f"agent_hinh_thuc: {m.get('ly_do') or ''} — dòng {m['dong']}: «{m['trich']}»",
            })
    return moi, bo_qua


def ghi_nguoc(moi: list[dict], so_anh_xa_tep: Path, phan_doan_tep: Path) -> int:
    """Ghi cách gọi mới vào bảng ánh xạ và vào nguồn dựng lại của nó. Lặp lại không nhân đôi."""
    if not moi:
        return 0
    so_ax = _doc(so_anh_xa_tep)
    pd = _doc(phan_doan_tep) or {"anh_xa_phan_doan": [], "ung_vien_loai": []}
    them = 0
    for c in moi:
        v = so_ax["anh_xa"][c["khoa"]]
        ds = v.setdefault("ten_goi_chap_nhan", [])
        cu = next((t for t in ds if t["ten"] == c["ten"] and t["cho_muc"] == c["cho_muc"]), None)
        if cu is None:
            ds.append({"ten": c["ten"], "cho_muc": c["cho_muc"], "phuong_phap": "agent",
                       "nguon": [c["nguon"]], "ly_do": c["ly_do"]})
            them += 1
        elif c["nguon"] not in cu["nguon"]:
            cu["nguon"].append(c["nguon"])
        if c["nguon"] not in v.setdefault("nguon", []):
            v["nguon"].append(c["nguon"])
        dong = {k: c[k] for k in ("khoa", "ten", "nguon", "ly_do", "cho_muc", "phuong_phap")}
        if not any(all(x.get(k) == dong[k] for k in ("khoa", "ten", "nguon", "cho_muc"))
                   for x in pd["anh_xa_phan_doan"]):
            pd["anh_xa_phan_doan"].append(dong)
    _ghi_rieng(so_anh_xa_tep, so_ax)
    _ghi_rieng(phan_doan_tep, pd)
    return them


# ── Một tài liệu ─────────────────────────────────────────────────────────

def dung_dau_vao(tl: dict, dt_tep: dict | None, so_ax: dict, so_hieu: list[dict]) -> tuple[dict, dict]:
    """(đầu vào cho lõi, ngữ cảnh để đối chiếu sau)."""
    pd = phan_duong_dan(tl["nguon"])
    so_do = so_anh_xa.QUY_TRINH.get(pd["nhom"])
    ho_so = [h["ho_so"] for h in (dt_tep or {}).get("ho_so", [])]
    h0 = (dt_tep or {}).get("ho_so") or [{}]
    dong = ag.dong_noi_dung(tl["markdown"])
    so_so = so_lien_quan(so_hieu, ho_so, dong)
    dau_vao = {
        "buoc_ung_vien": buoc_ung_vien(so_ax, so_do),
        "dong": dong,
        "ho_so": {"ma": h0[0].get("ma"), "nhan": h0[0].get("nhan")},
        "so_hieu": [{k: g[k] for k in ("loai", "gia_tri", "chu_so_huu")} for g in so_so],
        "loai_so": sorted(so_so_hieu.BANG_CUA_LOAI),
        "ten_tep": pd["trong_ho_so"],
    }
    return dau_vao, {"ho_so": ho_so, "so_do": so_do, "so_so": so_so,
                     "xung_dot": (dt_tep or {}).get("xung_dot"), "co_danh_tinh": dt_tep is not None}


def bam_loi_nhac() -> str:
    """Bản ghi mang băm lời nhắc hệ thống: sổ gộp nhiều lượt, lời nhắc đổi giữa chừng."""
    return hashlib.sha256(ag.HE_THONG.encode()).hexdigest()[:16]


def uoc_luong(dau_vao: dict) -> dict:
    he, nd = ag.dung_loi_nhac(dau_vao)
    # ~3 ký tự/token cho văn bản Việt–Anh trộn; chỉ để báo trước khi gọi.
    vao = (len(he) + len(nd)) // 3 + 574
    return {"token_vao_uoc": vao, "usd_uoc": round(vao * GIA_UOC_VAO + TOKEN_RA_UOC * GIA_UOC_RA, 4)}


def xu_ly(tl: dict, dt_tep: dict | None, so_ax: dict, so_hieu: list[dict], goi) -> dict:
    """Chạy agent trên một tài liệu và đối chiếu với bảng ánh xạ, sổ số hiệu."""
    dau_vao, nc = dung_dau_vao(tl, dt_tep, so_ax, so_hieu)
    ban_ghi = {"doc_id": tl["doc_id"], "duong_dan": tl["nguon"], "engine": tl["engine"],
               "ho_so": nc["ho_so"], "so_do": nc["so_do"], "loi_nhac_bam": bam_loi_nhac(),
               "chay_luc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    if not nc["ho_so"]:
        # Không biết hồ sơ thì không biết "nhãn của ta": chủ sở hữu mọi số sẽ đoán.
        ly = "tệp chờ người xác nhận hồ sơ (hàng chờ xung đột)" if nc["xung_dot"] else "tệp không thuộc hồ sơ nào trong sổ danh tính"
        return {**ban_ghi, "cho_nguoi": True, "ly_do_cho_nguoi": [ly], "khong_goi_model": True}
    if not dau_vao["buoc_ung_vien"]:
        return {**ban_ghi, "cho_nguoi": True, "khong_goi_model": True,
                "ly_do_cho_nguoi": ["bảng ánh xạ không có bước nào cho sơ đồ của hồ sơ"]}
    kq = ag.chay(dau_vao, goi, so_so_hieu.BANG_CUA_LOAI)
    ban_ghi.update(kq)
    if "loi" in kq:
        ban_ghi["ly_do_cho_nguoi"] = [kq["loi"]]
        return ban_ghi
    kq["so_hieu"] = ban_ghi["so_hieu"] = doi_chieu_so(kq["so_hieu"], nc["so_so"])
    doi = doi_chieu_anh_xa(kq, o_dang_giu(so_ax, tl["nguon"]))
    moi, bo_qua = cach_goi_moi(kq, tl["nguon"], so_ax, doi)
    ban_ghi.update(doi_chieu_anh_xa=doi, cach_goi_moi=moi, o_khong_ghi=bo_qua)
    ly = []
    if kq["do_chac"] == "thap":
        ly.append("độ chắc thấp")
    if doi["chi_anh_xa"]:
        ly.append("bảng ánh xạ gắn tệp vào ô mà agent không thấy tài liệu đáp ứng")
    if any(s["so_voi_so"]["trang_thai"] == "lech_chu" for s in kq["so_hieu"]):
        ly.append("chủ sở hữu số lệch với sổ số hiệu")
    ban_ghi["cho_nguoi"], ban_ghi["ly_do_cho_nguoi"] = bool(ly), ly
    return ban_ghi


class GoiLai:
    """Trả lại câu trả lời đã lưu, kèm chi phí của lượt gọi đã sinh ra nó.

    Đổi luật kiểm thì không phải trả tiền gọi lại. Lời nhắc đã đổi thì câu trả
    lời cũ không còn là câu trả lời cho lời nhắc này: từ chối, phải gọi thật.
    """

    def __init__(self, ban_ghi: dict | None, doc_id: str) -> None:
        if not ban_ghi or not isinstance(ban_ghi.get("tra_loi_tho"), dict):
            raise SystemExit(f"{doc_id}: sổ không có câu trả lời đã lưu để kiểm lại")
        if ban_ghi.get("loi_nhac_bam") != bam_loi_nhac():
            raise SystemExit(f"{doc_id}: lời nhắc đã đổi từ lượt gọi trước — phải --goi lại")
        self.ban_ghi, self.chay_luc = ban_ghi, ban_ghi.get("chay_luc")

    def __call__(self, _he_thong: str, _nguoi_dung: str) -> ag.PhanHoi:
        cp = self.ban_ghi.get("chi_phi") or {}
        return ag.PhanHoi(json.dumps(self.ban_ghi["tra_loi_tho"], ensure_ascii=False),
                          cp.get("model") or "", usd=cp.get("usd"), token=cp.get("token") or {},
                          thoi_gian_ms=cp.get("thoi_gian_ms"))


def tong_chi_phi(tai_lieu: dict[str, dict]) -> dict:
    usd = [t["chi_phi"]["usd"] for t in tai_lieu.values()
           if t.get("chi_phi") and t["chi_phi"].get("usd") is not None]
    tk = [t["chi_phi"]["token"] for t in tai_lieu.values() if t.get("chi_phi")]
    return {
        "so_luot_goi": len(usd),
        "usd_tong": round(sum(usd), 6),
        "usd_moi_tai_lieu": ({"thap_nhat": min(usd), "cao_nhat": max(usd),
                              "trung_binh": round(sum(usd) / len(usd), 6)} if usd else None),
        "token": {k: sum(x.get(k, 0) for x in tk) for k in
                  ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--doc-id", action="append", default=[], help="tài liệu chốt cổng (lặp được)")
    ap.add_argument("--diem-cong", metavar="THU_MUC_HO_SO",
                    help="liệt kê tệp đang giữ ô sản phẩm của hồ sơ, không gọi model")
    ap.add_argument("--goi", action="store_true", help="gọi model thật (mặc định chỉ ước lượng)")
    ap.add_argument("--kiem-lai", action="store_true",
                    help="kiểm lại câu trả lời đã lưu bằng luật kiểm hiện tại, không gọi model")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--effort", default=None)
    ap.add_argument("--ade-out", type=Path, default=ADE_OUT)
    ap.add_argument("--so-anh-xa", type=Path, default=SO_ANH_XA)
    ap.add_argument("--phan-doan", type=Path, default=PHAN_DOAN)
    ap.add_argument("--so-hieu", type=Path, default=SO_HIEU)
    ap.add_argument("--danh-tinh", type=Path, default=DANH_TINH)
    ap.add_argument("--ra", type=Path, default=RA)
    a = ap.parse_args(argv)

    so_ax = _doc(a.so_anh_xa)
    if so_ax is None:
        raise SystemExit(f"không thấy bảng ánh xạ {a.so_anh_xa}")
    if a.diem_cong:
        for d, o in sorted(diem_cong(so_ax, a.diem_cong).items()):
            print(d, " · ".join(f"{hd} «{m}»" for hd, _k, m in o))
        print("(tệp chốt cổng mà bảng ánh xạ không có ô — như biên nhận nộp đơn — phải nêu tay)")
        return 0
    ids = list(dict.fromkeys(a.doc_id))
    if not ids:
        raise SystemExit("nêu từng --doc-id: agent chỉ chạy ở chỗ quyết định cổng")
    if len(ids) > TRAN_MOI_LUOT:
        raise SystemExit(f"{len(ids)} tài liệu > trần {TRAN_MOI_LUOT} mỗi lượt — mở rộng là quyết định của chủ kho")

    so_hieu = (_doc(a.so_hieu) or {}).get("so_hieu", [])
    danh_tinh = so_so_hieu.nap_danh_tinh(a.danh_tinh) if a.danh_tinh.exists() else {}
    tai_lieu = []
    for d in ids:
        tl = nap_tai_lieu(a.ade_out, d)
        if tl is None:
            raise SystemExit(f"{d}: không có bản parse ADE")
        tai_lieu.append(tl)

    if not (a.goi or a.kiem_lai):
        tong = 0.0
        for tl in tai_lieu:
            dau_vao, _ = dung_dau_vao(tl, danh_tinh.get(tl["nguon"]), so_ax, so_hieu)
            u = uoc_luong(dau_vao)
            tong += u["usd_uoc"]
            print(f"{tl['doc_id']}  {tl['engine']:<5} {len(dau_vao['dong']):>4} dòng  "
                  f"~{u['token_vao_uoc']} token vào  ~${u['usd_uoc']:.4f}")
        print(f"ước lượng {len(tai_lieu)} tài liệu ≈ ${tong:.4f} — thêm --goi để chạy thật")
        return 0

    so = _doc(a.ra) or {"phien_ban": 1, "tai_lieu": {}, "ghi_nguoc_anh_xa": []}
    # Kiểm lại: dựng mọi GoiLai TRƯỚC vòng lặp, để một tài liệu thiếu câu trả lời
    # không bỏ dở lượt giữa chừng sau khi đã ghi ngược bảng ánh xạ.
    lai = {tl["doc_id"]: GoiLai(so["tai_lieu"].get(tl["doc_id"]), tl["doc_id"])
           for tl in tai_lieu} if a.kiem_lai else {}
    goi = None if a.kiem_lai else ag.ClaudeCli(a.model, effort=a.effort)
    for tl in tai_lieu:
        g = lai.get(tl["doc_id"]) or goi
        bg = xu_ly(tl, danh_tinh.get(tl["nguon"]), so_ax, so_hieu, g)
        if a.kiem_lai:
            bg["kiem_lai_luc"], bg["chay_luc"] = bg["chay_luc"], g.chay_luc
        so["tai_lieu"][tl["doc_id"]] = bg
        n = ghi_nguoc(bg.get("cach_goi_moi") or [], a.so_anh_xa, a.phan_doan)
        if bg.get("cach_goi_moi"):
            so["ghi_nguoc_anh_xa"].append({"doc_id": tl["doc_id"], "luc": bg["chay_luc"],
                                           "so_cach_goi": len(bg["cach_goi_moi"]), "moi_that": n})
            so_ax = _doc(a.so_anh_xa)
        cp = bg.get("chi_phi") or {}
        print(f"{tl['doc_id']}  {bg.get('do_chac', '-'):<4} "
              f"{'chờ người' if bg.get('cho_nguoi') else 'tự ghi':<9} "
              f"bỏ {len(bg.get('bi_bo', []))}  ghi ngược {len(bg.get('cach_goi_moi') or [])}  "
              f"${cp.get('usd') or 0:.4f}  {cp.get('token', {}).get('input_tokens', 0)}→"
              f"{cp.get('token', {}).get('output_tokens', 0)} token")
    so.update({
        "cap_nhat_luc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "loi_nhac_bam": bam_loi_nhac(),
        "giu_du_lieu_tren_may": ag.GIU_DU_LIEU_TREN_MAY,
        "nguon": {"ade_out": str(a.ade_out), "so_anh_xa": str(a.so_anh_xa), "so_hieu": str(a.so_hieu),
                  "danh_tinh": str(a.danh_tinh)},
        "chi_phi": tong_chi_phi(so["tai_lieu"]),
        "cho_nguoi": sorted(d for d, t in so["tai_lieu"].items() if t.get("cho_nguoi")),
    })
    _ghi_rieng(a.ra, so)
    c = so["chi_phi"]
    print(f"tổng {c['so_luot_goi']} lượt gọi ${c['usd_tong']:.4f} → {a.ra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
