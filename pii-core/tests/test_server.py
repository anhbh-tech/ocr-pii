"""The loopback HTTP interface, on an ephemeral 127.0.0.1 port."""
from __future__ import annotations

import http.client
import json
import threading

import pytest

from pii_core.server import check_host, make_server


@pytest.mark.parametrize("host", ["0.0.0.0", "", "::", "192.168.1.10", "10.0.0.1",
                                  "example.test", "8.8.8.8"])
def test_refuses_non_loopback(host, policy):
    with pytest.raises(ValueError):
        check_host(host)
    with pytest.raises(ValueError):
        make_server(policy, host=host, port=0)


@pytest.mark.parametrize("host, bound", [("127.0.0.1", "127.0.0.1"),
                                         ("localhost", "127.0.0.1"),
                                         ("::1", "::1"), ("127.0.0.2", "127.0.0.2")])
def test_accepts_loopback(host, bound):
    assert check_host(host) == bound


@pytest.fixture
def server(policy):
    lines: list[str] = []
    srv = make_server(policy, "127.0.0.1", 0, max_body=64 * 1024, log=lines.append)
    thread = threading.Thread(target=srv.serve_forever, args=(0.02,), daemon=True)
    thread.start()
    srv.log_lines = lines
    yield srv
    srv.shutdown()
    srv.server_close()


def call(server, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    data = None if body is None else json.dumps(body).encode()
    hdrs = {"Content-Type": "application/json"} if body is not None else {}
    hdrs.update(headers or {})
    conn.request(method, path, body=data, headers=hdrs)
    resp = conn.getresponse()
    payload = json.loads(resp.read() or b"null")
    conn.close()
    return resp.status, payload


def test_health_and_decisions(server):
    assert call(server, "GET", "/health")[1]["ok"] is True
    status, payload = call(server, "GET", "/v1/decisions")
    assert status == 200
    assert {d["category"]: d["action"] for d in payload["decisions"]}["MRZ"] == "REMOVE"


def test_field(server):
    status, r = call(server, "POST", "/v1/field",
                     {"label": "Họ và tên", "value": "Nguyễn Văn Mẫu", "group": "C"})
    assert status == 200 and r["action"] == "PSEUDONYMISE"
    assert r["vault"]["tokens"][r["after"]]["value"] == "Nguyễn Văn Mẫu"


def test_fields(server):
    status, r = call(server, "POST", "/v1/fields", {"fields": [
        {"label": "Họ và tên", "value": "Nguyễn Văn Mẫu"},
        {"label": "Số CCCD", "value": "001099000001"},
        {"label": "Số đơn", "value": "4-2024-12345"}]})
    assert status == 200
    assert [f["action"] for f in r["fields"]] == ["PSEUDONYMISE", "ANONYMISE",
                                                  "PSEUDONYMISE"]
    assert len(r["vault"]["tokens"]) == 2


def test_document_then_restore(server, case_text, register):
    status, r = call(server, "POST", "/v1/document", {"text": case_text, "group": "C"})
    assert status == 200 and r["summary"]["ok"]
    for value in register["must_not_survive"]:
        assert value not in r["text"]
    status, back = call(server, "POST", "/v1/restore",
                        {"text": r["text"], "vault": r["vault"]})
    assert status == 200
    assert back["text"] == case_text.replace("001099000001", "[NATIONAL_ID]") \
        .replace("05/03/1990", "[BIRTH_DATE]")


def test_document_takes_the_matters_own_facts(server):
    text = "Chào @Mongvan Quach, hồ sơ đã nộp.\n"
    status, r = call(server, "POST", "/v1/document",
                     {"text": text, "group": "C",
                      "vars": {"Tên KH": "Thị Mộng Vân Quách"}})
    assert status == 200 and r["summary"]["ok"]
    assert "Mongvan" not in r["text"] and "[PERSON-" in r["text"]
    # and without them the joined, unaccented mention is not found
    _, plain = call(server, "POST", "/v1/document", {"text": text, "group": "C"})
    assert "Mongvan Quach" in plain["text"]


def test_document_continues_a_vault(server):
    _, first = call(server, "POST", "/v1/document",
                    {"text": "Họ và tên: Nguyễn Văn Mẫu\n", "group": "C"})
    _, second = call(server, "POST", "/v1/document",
                     {"text": "Email: mau.nguyen@example.test\n", "group": "C",
                      "vault": first["vault"]})
    assert len(second["vault"]["tokens"]) == 2
    status, _ = call(server, "POST", "/v1/document",
                     {"text": "x", "group": "OTHER", "vault": first["vault"]})
    assert status == 409


def test_case_carries_context_across_documents(server):
    # A mark under a label in the second document is sought in the first:
    # one call gives an HTTP caller what redact_case gives the library.
    docs = ["Ý kiến: Hư Cấu trùng với nhãn đã đăng ký.\n",
            "Tên nhãn hiệu: HƯ CẤU\nNgày nộp đơn: 05/03/2024\n"]
    status, r = call(server, "POST", "/v1/case",
                     {"texts": docs, "group": "C", "sources": ["y-kien.pdf", None]})
    assert status == 200 and r["summary"]["ok"]
    assert r["summary"]["documents"] == 2 and len(r["documents"]) == 2
    first, second = r["documents"]
    assert "Hư Cấu" not in first["text"] and "05/03/2024" not in second["text"]
    assert "vault" not in first and first["source"] == "[SOURCE_FILE]"
    marks = [t for t, row in r["vault"]["tokens"].items() if row["category"] == "MARK"]
    assert len(marks) == 1 and marks[0] in first["text"] and marks[0] in second["text"]
    # fields index each document's own input, as /v1/document's do
    for doc, text in zip(r["documents"], docs):
        for f in doc["fields"]:
            assert text[f["start"]:f["end"]]
    _, back = call(server, "POST", "/v1/restore",
                   {"text": first["text"] + second["text"], "vault": r["vault"]})
    # one token restores one form: the mark as the case first wrote it
    assert back["text"] == docs[0] + docs[1].replace("HƯ CẤU", "Hư Cấu")


def test_case_takes_vars_and_continues_a_vault(server):
    _, lead = call(server, "POST", "/v1/case",
                   {"texts": ["Họ và tên: Nguyễn Văn Mẫu\n"], "group": "C"})
    status, r = call(server, "POST", "/v1/case",
                     {"texts": ["Chào @Mongvan Quach.\n", "Ông Nguyễn Văn Mẫu đã ký.\n"],
                      "group": "C", "vault": lead["vault"],
                      "vars": {"Tên KH": "Thị Mộng Vân Quách"}})
    assert status == 200
    assert "Mongvan" not in r["documents"][0]["text"]
    assert set(lead["vault"]["tokens"]) <= set(r["vault"]["tokens"])
    assert len(r["vault"]["tokens"]) == 2
    status, _ = call(server, "POST", "/v1/case",
                     {"texts": ["x"], "group": "OTHER", "vault": lead["vault"]})
    assert status == 409


def test_an_empty_case_returns_its_vault(server):
    status, r = call(server, "POST", "/v1/case", {"texts": [], "group": "C"})
    assert status == 200 and r["documents"] == [] and r["summary"]["ok"]
    assert r["vault"]["group"] == "C" and r["vault"]["tokens"] == {}
    status, _ = call(server, "POST", "/v1/case",
                     {"texts": [], "group": "OTHER", "vault": r["vault"]})
    assert status == 409


@pytest.mark.parametrize("method, path, body, headers, status", [
    ("POST", "/v1/case", {"group": "C"}, None, 400),
    ("POST", "/v1/case", {"texts": "one text"}, None, 400),
    ("POST", "/v1/case", {"texts": ["a", 3]}, None, 400),
    ("POST", "/v1/case", {"texts": ["a", "b"], "sources": ["a.pdf"]}, None, 400),
    ("POST", "/v1/case", {"texts": ["a"], "vars": ["no-equals-sign"]}, None, 400),
    ("GET", "/v1/case", None, None, 405),
    ("GET", "/nope", None, None, 404),
    ("GET", "/v1/field", None, None, 405),
    ("POST", "/v1/field", {"label": "x"}, None, 400),
    ("POST", "/v1/field", {"label": "x", "value": 3}, None, 400),
    ("POST", "/v1/document", {"text": "x", "vars": ["no-equals-sign"]}, None, 400),
    ("POST", "/v1/field", {"label": "x", "value": "y"}, {"Content-Type": "text/plain"}, 415),
    ("POST", "/v1/field", {"label": "x", "value": "y"}, {"Host": "evil.example.test"}, 403),
    ("POST", "/v1/document", {"text": "x" * 70000}, None, 413),
    ("POST", "/v1/restore", {"text": "x", "vault": {"version": 99}}, None, 400),
])
def test_bad_requests(server, method, path, body, headers, status):
    assert call(server, method, path, body, headers)[0] == status


def test_logs_carry_no_body(server):
    call(server, "POST", "/v1/field", {"label": "Họ và tên", "value": "Nguyễn Văn Mẫu"})
    assert server.log_lines == ["POST /v1/field 200"]
