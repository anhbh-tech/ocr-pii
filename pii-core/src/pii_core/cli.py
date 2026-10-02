"""``pii-core``: the same interface as the server, for a chain that shells out.

::

    pii-core document case.txt --group CASE-042 --vault-out case.vault.json > safe.txt
    pii-core restore answer.txt --vault case.vault.json > answer.restored.txt
    pii-core field "Họ và tên" "Nguyễn Văn Mẫu"
    pii-core decisions
    pii-core serve                      # http://127.0.0.1:8813

``Nguyễn Văn Mẫu`` is a synthetic example name, not a real person.

The key comes from ``--key-file``, else ``$PII_CORE_KEY``, else the file named
by ``$PII_CORE_KEY_FILE``. There is no default key: an unkeyed token of a
Vietnamese name is reversible by dictionary.

Exit status: 0 done; 2 usage or configuration error; 3 ``--strict`` and the
residue check found untreated PII in the output (the output is still written,
so the caller can inspect it — but must not forward it).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .casevars import parse_vars
from .document import Vault, VaultError, redact_document, restore
from .parties import ROSTER_ENV, Roster
from .policy import Policy

__all__ = ["main", "load_key", "KEY_ENV", "KEY_FILE_ENV"]


KEY_ENV = "PII_CORE_KEY"
KEY_FILE_ENV = "PII_CORE_KEY_FILE"


class _ConfigError(Exception):
    pass


def load_key(key_file: str | None = None) -> str:
    if key_file:
        return Path(key_file).read_text(encoding="utf-8").strip()
    if os.environ.get(KEY_ENV):
        return os.environ[KEY_ENV]
    if os.environ.get(KEY_FILE_ENV):
        return Path(os.environ[KEY_FILE_ENV]).read_text(encoding="utf-8").strip()
    raise _ConfigError(
        f"no key: pass --key-file, or set {KEY_ENV} or {KEY_FILE_ENV}. The same "
        "key must be used for a case's redaction and its restore.")


def _policy(args: argparse.Namespace) -> Policy:
    key = load_key(args.key_file)
    if not key:
        raise _ConfigError("the key file is empty")
    return Policy(key, roster=Roster.load(args.roster))


def _read(path: str | None) -> str:
    if path in (None, "-"):
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _dump(payload: Any) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")


def _cmd_field(args: argparse.Namespace) -> int:
    policy = _policy(args)
    result = policy.field(args.label, args.value, args.group)
    if args.vault_out:
        vault = Vault(group=args.group)
        vault.add_tokens(result.tokens)
        vault.save(args.vault_out)
    _dump(result.as_dict())
    return 0


def _vars_file(path: str | None) -> list[Any]:
    """The matter's facts from a file, so they never stand in a command line
    that a shell history would keep: a JSON object, a JSON list of
    ``{name, value, category?}``, or one ``NAME=VALUE`` per line."""
    if not path:
        return []
    raw = _read(path).strip()
    if raw.startswith(("{", "[")):
        data = json.loads(raw)
        if isinstance(data, dict):
            return [{"name": k, "value": v} for k, v in data.items()]
        return list(data)
    return [line for line in raw.splitlines() if line.strip() and "=" in line]


def _cmd_document(args: argparse.Namespace) -> int:
    policy = _policy(args)
    vault = Vault.load(args.vault_in) if args.vault_in else None
    case_vars = parse_vars([*(args.var or ()), *_vars_file(args.vars_file)])
    result = redact_document(_read(args.file), policy, group=args.group,
                             vault=vault, source=args.source,
                             case_vars=case_vars)
    if args.vault_out:
        result.vault.save(args.vault_out)
    elif result.vault.tokens:
        print(f"pii-core: {len(result.vault.tokens)} tokens minted and no "
              "--vault-out: they cannot be restored from this run",
              file=sys.stderr)
    if args.json:
        # The vault never goes to stdout: stdout is what gets forwarded.
        _dump(result.as_dict(include_vault=False))
    else:
        sys.stdout.write(result.text)
        summary = result.summary
        print(f"pii-core: {summary['fields']} fields {summary['by_action']}; "
              f"residue {summary['residue']}", file=sys.stderr)
    for row in result.residue:
        print(f"pii-core: RESIDUE {row['category'] or '?'} via {row['matched_by']} "
              f"at {row['start']}-{row['end']}", file=sys.stderr)
    return 3 if args.strict and result.residue else 0


def _cmd_restore(args: argparse.Namespace) -> int:
    sys.stdout.write(restore(_read(args.file), Vault.load(args.vault),
                             unshift_dates=not args.no_unshift))
    return 0


def _cmd_decisions(args: argparse.Namespace) -> int:
    from .decide import decisions
    rows = [d.as_dict() for d in decisions().values()]
    if args.json:
        _dump(rows)
        return 0
    for row in rows:
        r = "—" if row["r"] is None else f"{row['r']:.0%}"
        flag = "" if row["settled"] else "  (L đề xuất)"
        print(f"{row['category']:<12} {row['action']:<13} R {r:>5}  L {row['harm']}  "
              f"N {row['n']}  risk {row['risk']}{flag}")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve
    serve(_policy(args), args.host, args.port)
    return 0


def _parser() -> argparse.ArgumentParser:
    from .server import DEFAULT_HOST, DEFAULT_PORT

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--key-file", help=f"root key file (else ${KEY_ENV} / ${KEY_FILE_ENV})")
    common.add_argument("--roster", help=f"public-party roster JSON (else ${ROSTER_ENV})")

    parser = argparse.ArgumentParser(prog="pii-core", description=__doc__.split("\n")[0])
    parser.add_argument("--version", action="version", version=f"pii-core {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("field", parents=[common], help="classify one (label, value)")
    p.add_argument("label")
    p.add_argument("value")
    p.add_argument("--group", default="", help="the case; one vault per case")
    p.add_argument("--vault-out", help="write the minted tokens here (0600)")
    p.set_defaults(run=_cmd_field)

    p = sub.add_parser("document", parents=[common], help="redact extracted document text")
    p.add_argument("file", nargs="?", default="-", help="text file, or - for stdin")
    p.add_argument("--group", default="", help="the case; one vault per case")
    p.add_argument("--source", help="the source file name (treated as SOURCE_FILE)")
    p.add_argument("--var", action="append", metavar="NAME=VALUE",
                   help="a fact of this matter (client name, matter code, mark); "
                        "matched accent-free and case-free, one typo tolerated")
    p.add_argument("--vars-file", help="the same, as JSON or NAME=VALUE lines")
    p.add_argument("--vault-in", help="continue this case's vault")
    p.add_argument("--vault-out", help="write the vault here (0600); keep it from the agent")
    p.add_argument("--json", action="store_true",
                   help="print text + audit + residue as JSON (never the vault)")
    p.add_argument("--strict", action="store_true", help="exit 3 when residue is found")
    p.set_defaults(run=_cmd_document)

    p = sub.add_parser("restore", help="put the originals back into agent output")
    p.add_argument("file", nargs="?", default="-")
    p.add_argument("--vault", required=True)
    p.add_argument("--no-unshift", action="store_true",
                   help="with a vault from before 2026-09-28: leave dates alone except the ones it shifted")
    p.set_defaults(run=_cmd_restore)

    p = sub.add_parser("decisions", help="print the decision table")
    p.add_argument("--json", action="store_true")
    p.set_defaults(run=_cmd_decisions)

    p = sub.add_parser("serve", parents=[common], help="loopback HTTP server")
    p.add_argument("--host", default=DEFAULT_HOST, help="loopback only; 0.0.0.0 is refused")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.set_defaults(run=_cmd_serve)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.run(args)
    except (_ConfigError, VaultError, ValueError, OSError) as exc:
        print(f"pii-core: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
