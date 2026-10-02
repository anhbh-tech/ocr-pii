from __future__ import annotations

import json
import stat

import pytest

from pii_core.categories import CATEGORIES
from pii_core.cli import main

from conftest import FIXTURES, KEY


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("PII_CORE_KEY", KEY)
    monkeypatch.delenv("PII_CORE_KEY_FILE", raising=False)
    monkeypatch.delenv("PII_CORE_ROSTER", raising=False)


def test_field(capsys):
    assert main(["field", "Số CCCD", "001099000001"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert (out["action"], out["after"]) == ("ANONYMISE", "[NATIONAL_ID]")


def test_document_and_restore(tmp_path, capsys, register):
    vault = tmp_path / "c.vault.json"
    safe = tmp_path / "safe.txt"
    assert main(["document", str(FIXTURES / "case_synthetic.txt"), "--group", "C",
                 "--vault-out", str(vault)]) == 0
    captured = capsys.readouterr()
    for value in register["must_not_survive"]:
        assert value not in captured.out
    assert stat.S_IMODE(vault.stat().st_mode) == 0o600
    safe.write_text(captured.out, encoding="utf-8")
    assert main(["restore", str(safe), "--vault", str(vault)]) == 0
    back = capsys.readouterr().out
    original = (FIXTURES / "case_synthetic.txt").read_text(encoding="utf-8")
    assert back == original.replace("001099000001", "[NATIONAL_ID]") \
        .replace("05/03/1990", "[BIRTH_DATE]")


def test_document_json_never_prints_the_vault(capsys):
    assert main(["document", str(FIXTURES / "case_synthetic.txt"), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "vault" not in out and out["summary"]["ok"]


def test_var_and_vars_file_carry_the_matters_facts(tmp_path, capsys):
    doc = tmp_path / "d.txt"
    doc.write_text("Chào @Mongvan Quach và MAUMAUOL.\n", encoding="utf-8")
    facts = tmp_path / "vars.json"
    facts.write_text('{"Nhãn hiệu": "MAUMAUOI"}', encoding="utf-8")
    assert main(["document", str(doc), "--group", "C",
                 "--var", "Tên KH=Thị Mộng Vân Quách",
                 "--vars-file", str(facts)]) == 0
    out = capsys.readouterr().out
    assert "Mongvan" not in out and "MAUMAUOL" not in out
    assert "[PERSON-" in out and "[MARK-" in out


def test_strict_fails_on_residue(tmp_path, capsys):
    doc = tmp_path / "d.txt"
    doc.write_text("tham chiếu 9876 5432 1098\n", encoding="utf-8")
    assert main(["document", str(doc), "--strict"]) == 3
    assert "RESIDUE" in capsys.readouterr().err


def test_no_key_is_a_configuration_error(monkeypatch, capsys):
    monkeypatch.delenv("PII_CORE_KEY")
    assert main(["field", "Họ và tên", "Nguyễn Văn Mẫu"]) == 2
    assert "no key" in capsys.readouterr().err


def test_key_file_and_roster(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("PII_CORE_KEY")
    key = tmp_path / "key"
    key.write_text(KEY + "\n", encoding="utf-8")
    assert main(["field", "Họ và tên", "Cong Khai Mau JSC", "--key-file", str(key),
                 "--roster", str(FIXTURES / "roster_synthetic.json")]) == 0
    assert json.loads(capsys.readouterr().out)["matched_by"] == "roster"


def test_serve_refuses_all_interfaces(capsys):
    assert main(["serve", "--host", "0.0.0.0", "--port", "0"]) == 2
    assert "loopback" in capsys.readouterr().err


def test_decisions(capsys):
    assert main(["decisions", "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == len(CATEGORIES)
