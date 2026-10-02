"""A loopback-only HTTP interface for the node-check chain.

Standard library only. It binds a loopback address or refuses to start:
``0.0.0.0``, ``::``, the empty string and every non-loopback address are
rejected before a socket is opened. On top of that it:

* answers only clients whose peer address is loopback;
* checks the ``Host`` header against the bound address, so a web page that
  DNS-rebinds its own domain to 127.0.0.1 is refused;
* requires ``Content-Type: application/json`` on POST, which a cross-origin
  page cannot send without a CORS preflight this server never approves;
* takes the key from its own process (``PII_CORE_KEY`` / key file), never
  from a request;
* logs method, path and status only — never a body.

Endpoints (all JSON; see README for the call shapes)::

    GET  /health
    GET  /v1/decisions
    POST /v1/field      {label, value, group?}
    POST /v1/fields     {fields: [{label, value}], group?}
    POST /v1/document   {text, group?, source?, vault?, vars?}
    POST /v1/case       {texts: [...], group?, sources?, vault?, vars?}
    POST /v1/restore    {text, vault, unshift_dates?}
"""
from __future__ import annotations

import ipaddress
import json
import socket
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from . import __version__
from .casevars import parse_vars
from .document import Vault, VaultError, redact_case, redact_document, restore
from .parties import ROSTER_ENV
from .policy import Policy

__all__ = ["DEFAULT_HOST", "DEFAULT_PORT", "MAX_BODY", "make_server",
           "check_host", "serve"]


DEFAULT_HOST = "127.0.0.1"
#: pii-lab's local server takes 8812; this sits next to it.
DEFAULT_PORT = 8813
MAX_BODY = 8 * 1024 * 1024


class _BadRequest(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


def check_host(host: str) -> str:
    """The loopback address to bind for ``host``, or ValueError.

    ``localhost`` is pinned to 127.0.0.1 rather than resolved: a hosts file
    can point it anywhere.
    """
    if host == "localhost":
        return "127.0.0.1"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise ValueError(
            f"refusing to bind {host!r}: pii-core serves loopback only "
            "(127.0.0.1, ::1 or localhost)") from None
    if not address.is_loopback:
        raise ValueError(
            f"refusing to bind {host!r}: not a loopback address. The redaction "
            "service sees raw case text and must never listen beyond this "
            "machine.")
    return str(address)


def _require(body: dict[str, Any], key: str, kind: type = str) -> Any:
    if key not in body:
        raise _BadRequest(HTTPStatus.BAD_REQUEST, f"missing field {key!r}")
    if not isinstance(body[key], kind):
        raise _BadRequest(HTTPStatus.BAD_REQUEST,
                          f"field {key!r} must be {kind.__name__}")
    return body[key]


def _optional_str(body: dict[str, Any], key: str, default: str | None) -> str | None:
    value = body.get(key, default)
    if value is not None and not isinstance(value, str):
        raise _BadRequest(HTTPStatus.BAD_REQUEST, f"field {key!r} must be str")
    return value


def _case_vars(data: Any):
    """``vars``: the matter's own facts. ``{"Tên KH": "..."}`` or a list of
    ``{name, value, category?}``. The caller knows them; without them the
    extractor has to find the client's name in the prose unaided."""
    if data is None:
        return ()
    try:
        return parse_vars(data)
    except (TypeError, ValueError) as exc:
        raise _BadRequest(HTTPStatus.BAD_REQUEST, f"bad vars: {exc}") from None


def _vault(data: Any) -> Vault:
    if not isinstance(data, dict):
        raise _BadRequest(HTTPStatus.BAD_REQUEST, "field 'vault' must be an object")
    try:
        return Vault.from_dict(data)
    except (VaultError, TypeError, ValueError, KeyError) as exc:
        raise _BadRequest(HTTPStatus.BAD_REQUEST, f"bad vault: {exc}") from None


def _routes(policy: Policy) -> dict[tuple[str, str], Callable[[dict[str, Any]], Any]]:
    def health(_: dict[str, Any]) -> Any:
        return {"ok": True, "version": __version__, "roster": len(policy.roster),
                "categories": len(policy.decisions)}

    def table(_: dict[str, Any]) -> Any:
        return {"decisions": [d.as_dict() for d in policy.decisions.values()]}

    def one_field(body: dict[str, Any]) -> Any:
        group = _optional_str(body, "group", "") or ""
        result = policy.field(_require(body, "label"), _require(body, "value"), group)
        vault = Vault(group=group)
        vault.add_tokens(result.tokens)
        return {**result.as_dict(), "vault": vault.as_dict()}

    def many_fields(body: dict[str, Any]) -> Any:
        group = _optional_str(body, "group", "") or ""
        rows = _require(body, "fields", list)
        vault = Vault(group=group)
        out = []
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                raise _BadRequest(HTTPStatus.BAD_REQUEST, f"fields[{i}] must be an object")
            result = policy.field(_require(row, "label"), _require(row, "value"), group)
            vault.add_tokens(result.tokens)
            out.append(result.as_dict())
        return {"fields": out, "vault": vault.as_dict()}

    def document(body: dict[str, Any]) -> Any:
        group = _optional_str(body, "group", "") or ""
        vault = _vault(body["vault"]) if body.get("vault") is not None else None
        try:
            result = redact_document(_require(body, "text"), policy, group=group,
                                     vault=vault,
                                     source=_optional_str(body, "source", None),
                                     case_vars=_case_vars(body.get("vars")))
        except VaultError as exc:
            raise _BadRequest(HTTPStatus.CONFLICT, str(exc)) from None
        return result.as_dict(include_vault=True)

    def case(body: dict[str, Any]) -> Any:
        """A case's documents in one call, so an HTTP caller gets what
        :func:`redact_case` gives the library: a name, mark or matter code
        found in any document is sought in all of them, and one vault covers
        the case. Documents come back in the order sent, without the vault;
        the one vault comes once, beside them."""
        group = _optional_str(body, "group", "") or ""
        texts = _require(body, "texts", list)
        if not all(isinstance(t, str) for t in texts):
            raise _BadRequest(HTTPStatus.BAD_REQUEST, "field 'texts' must be a list of str")
        sources = body.get("sources")
        if sources is not None and (
                not isinstance(sources, list) or len(sources) != len(texts)
                or not all(s is None or isinstance(s, str) for s in sources)):
            raise _BadRequest(HTTPStatus.BAD_REQUEST,
                              "field 'sources' must be a list of str or null, "
                              "one per text")
        vault = _vault(body["vault"]) if body.get("vault") is not None else None
        if vault is not None and vault.group != group:
            raise _BadRequest(HTTPStatus.CONFLICT,
                              "the vault passed in belongs to a different group")
        try:
            results = redact_case(texts, policy, group=group, sources=sources,
                                  vault=vault, case_vars=_case_vars(body.get("vars")))
        except VaultError as exc:
            raise _BadRequest(HTTPStatus.CONFLICT, str(exc)) from None
        final = results[-1].vault if results else (vault or Vault(group=group))
        documents = [r.as_dict(include_vault=False) for r in results]
        return {"documents": documents, "vault": final.as_dict(),
                "summary": {"documents": len(documents),
                            "fields": sum(d["summary"]["fields"] for d in documents),
                            "residue": sum(d["summary"]["residue"] for d in documents),
                            "tokens": len(final.tokens),
                            "ok": all(d["summary"]["ok"] for d in documents)}}

    def undo(body: dict[str, Any]) -> Any:
        unshift = body.get("unshift_dates", True)
        if not isinstance(unshift, bool):
            raise _BadRequest(HTTPStatus.BAD_REQUEST, "field 'unshift_dates' must be bool")
        return {"text": restore(_require(body, "text"), _vault(body.get("vault")),
                                unshift_dates=unshift)}

    return {("GET", "/health"): health, ("GET", "/v1/decisions"): table,
            ("POST", "/v1/field"): one_field, ("POST", "/v1/fields"): many_fields,
            ("POST", "/v1/document"): document, ("POST", "/v1/case"): case,
            ("POST", "/v1/restore"): undo}


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _Server6(_Server):
    address_family = socket.AF_INET6


def make_server(policy: Policy, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                max_body: int = MAX_BODY, log: Callable[[str], None] | None = None
                ) -> ThreadingHTTPServer:
    """A bound, not yet serving, loopback server. ``port=0`` picks a free one."""
    bind = check_host(host)
    routes = _routes(policy)
    emit = log if log is not None else (lambda line: print(line, file=sys.stderr))

    class Handler(BaseHTTPRequestHandler):
        server_version = f"pii-core/{__version__}"
        sys_version = ""

        def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
            status = code.value if isinstance(code, HTTPStatus) else code
            emit(f"{self.command} {self.path.split('?', 1)[0]} {status}")

        def log_message(self, format: str, *args: Any) -> None:
            pass                     # the default would echo request lines

        def _send(self, status: HTTPStatus, payload: Any) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _allowed_hosts(self) -> set[str]:
            port = self.server.server_address[1]
            names = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
            if port == 80:
                names |= {"127.0.0.1", "localhost", "[::1]"}
            return names

        def _body(self) -> dict[str, Any]:
            ctype = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if ctype != "application/json":
                raise _BadRequest(HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                                  "Content-Type must be application/json")
            length = self.headers.get("Content-Length")
            if length is None or not length.isdigit():
                raise _BadRequest(HTTPStatus.LENGTH_REQUIRED, "Content-Length required")
            if int(length) > max_body:
                raise _BadRequest(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                                  f"body over {max_body} bytes")
            try:
                body = json.loads(self.rfile.read(int(length)).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise _BadRequest(HTTPStatus.BAD_REQUEST, "body is not JSON") from None
            if not isinstance(body, dict):
                raise _BadRequest(HTTPStatus.BAD_REQUEST, "body must be a JSON object")
            return body

        def _handle(self) -> None:
            try:
                peer = ipaddress.ip_address(self.client_address[0])
                if not peer.is_loopback:
                    raise _BadRequest(HTTPStatus.FORBIDDEN, "loopback clients only")
                if self.headers.get("Host", "") not in self._allowed_hosts():
                    raise _BadRequest(HTTPStatus.FORBIDDEN, "unexpected Host header")
                path = self.path.split("?", 1)[0]
                handler = routes.get((self.command, path))
                if handler is None:
                    known = {p for _, p in routes}
                    status = (HTTPStatus.METHOD_NOT_ALLOWED if path in known
                              else HTTPStatus.NOT_FOUND)
                    raise _BadRequest(status, f"no {self.command} {path}")
                body = self._body() if self.command == "POST" else {}
                self._send(HTTPStatus.OK, handler(body))
            except _BadRequest as exc:
                self._send(exc.status, {"error": str(exc)})
            except Exception as exc:   # never echo the input back in an error
                emit(f"{self.command} {self.path.split('?', 1)[0]} failed: "
                     f"{type(exc).__name__}")
                self._send(HTTPStatus.INTERNAL_SERVER_ERROR,
                           {"error": f"internal error ({type(exc).__name__})"})

        do_GET = _handle
        do_POST = _handle

    cls = _Server6 if ":" in bind else _Server
    return cls((bind, port), Handler)


def serve(policy: Policy, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    server = make_server(policy, host, port)
    address, bound = server.server_address[:2]
    print(f"pii-core {__version__} listening on http://{address}:{bound} "
          f"(loopback only; roster {len(policy.roster)})", file=sys.stderr)
    if not len(policy.roster):
        print("pii-core: WARNING no roster loaded: every name is treated as a "
              f"client's, the firm's own staff included. Set ${ROSTER_ENV} or "
              "--roster before real use.", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
