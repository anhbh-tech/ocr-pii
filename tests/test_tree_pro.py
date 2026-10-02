"""Tài liệu chạy bằng ADE Pro phải hiện trong cây và mở được.

Pro ghi `parse_pro.json` + `meta_pro.json` (tên riêng để chạy Pro không đè
kết quả Verity của cùng tài liệu). Mọi chỗ đọc cứng `meta.json` sẽ bỏ sót
TOÀN BỘ pdf_scan và ảnh rời — đã trả tiền chạy mà không thấy đâu.
"""
from __future__ import annotations

import json
import importlib.util
import pathlib

import pytest
from fastapi.testclient import TestClient


def _nap_sr():
    """`scripts/` không phải package nên không import theo tên được."""
    p = pathlib.Path(__file__).parent.parent / "scripts" / "serve_review.py"
    spec = importlib.util.spec_from_file_location("sr_pro", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def kho_pro(tmp_path, monkeypatch):
    """Kho có đủ ba kiểu: Verity, Pro, và Pro-không-có-meta-thường."""
    sr = _nap_sr()

    store = tmp_path / "kho"
    store.mkdir()

    # (1) Verity: meta.json + parse.json
    d1 = store / "a1b2c3d4e5f60001"
    d1.mkdir()
    (d1 / "meta.json").write_text(json.dumps({
        "source": "HS1/hop_dong.pdf", "model": "dpt-3-verity",
        "section": "pdf_digital", "credits": 1.0}), "utf-8")
    (d1 / "parse.json").write_text(json.dumps({"markdown": "hợp đồng"}), "utf-8")

    # (2) Pro: CHỈ có meta_pro.json + parse_pro.json
    d2 = store / "a1b2c3d4e5f60002"
    d2.mkdir()
    (d2 / "meta_pro.json").write_text(json.dumps({
        "source": "HS1/scan.pdf", "model": "dpt-3-pro",
        "section": "pdf_scan", "credits": 3.0}), "utf-8")
    (d2 / "parse_pro.json").write_text(
        json.dumps({"markdown": "bản scan"}), "utf-8")

    monkeypatch.setattr(sr, "STORE", store)
    return TestClient(sr.app)


def test_tai_lieu_pro_hien_trong_cay(kho_pro):
    """Bỏ sót Pro nghĩa là mất toàn bộ pdf_scan + ảnh rời khỏi giao diện."""
    r = kho_pro.get("/api/tree")
    assert r.status_code == 200
    d = r.json()
    tong = sum(len(m["docs"]) for s in d["sections"]
               for m in s.get("matters", []))
    assert tong == 2, f"cây phải có cả 2 tài liệu, chỉ thấy {tong}"


def test_pro_vao_dung_section(kho_pro):
    d = kho_pro.get("/api/tree").json()
    theo_key = {s["key"]: sum(len(m["docs"]) for m in s.get("matters", []))
                for s in d["sections"]}
    assert theo_key.get("pdf_scan") == 1, "bản scan phải nằm ở nhóm PDF scan"
    assert theo_key.get("pdf_digital") == 1


def test_mo_tai_lieu_pro_khong_loi_500(kho_pro):
    """`/api/doc` đọc cứng `meta.json` thì mọi tài liệu Pro ném 500."""
    d = kho_pro.get("/api/tree").json()
    doc_id = next(doc["doc_id"] for s in d["sections"]
                  if s["key"] == "pdf_scan"
                  for m in s["matters"] for doc in m["docs"])
    r = kho_pro.get(f"/api/doc/{doc_id}")
    assert r.status_code == 200, f"mở tài liệu Pro lỗi {r.status_code}"
    assert r.json()["parse"]["markdown"] == "bản scan", \
        "phải đọc parse_pro.json, không phải trả về rỗng"
