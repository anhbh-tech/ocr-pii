"""One root key, independent HKDF subkeys per job, and none for anonymisation.

Ported from pii-lab (`src/pii_lab/keyring.py`). The HKDF ``info`` labels are
kept byte-identical to pii-lab's, so the same root key gives the same token
for the same value in both projects — a pii-lab table cell and a pii-core
document field about the same person link up.

* The root does no work itself; each job derives its own subkey, so a leaked
  token subkey does not reverse date shifts and vice versa.
* Anonymisation takes no key. If a key can reverse it, it is pseudonymisation.
* Tokens are 5 bytes (10 hex digits): at 2,331 secrets (pii-lab's live vault)
  the chance of ANY collision is ~0.0003%; at 3 bytes it is ~15%.
"""
from __future__ import annotations

import hashlib
import hmac
import math
from dataclasses import dataclass

__all__ = ["Keyring", "TOKEN_BYTES", "PURPOSES", "collision_probability",
           "hkdf", "flatten"]


TOKEN_BYTES = 5

#: Frozen strings: changing one changes every value derived under it.
PURPOSES: dict[str, bytes] = {
    "token": b"pii-lab/v1/token-digest",
    "lookup": b"pii-lab/v1/lookup-hash",
    "encrypt": b"pii-lab/v1/value-encryption",
    "dateshift": b"pii-lab/v1/date-shift",
}


def hkdf(root: bytes, info: bytes, length: int = 32, salt: bytes = b"") -> bytes:
    """HKDF-SHA256 (RFC 5869)."""
    if length > 255 * 32:
        raise ValueError("HKDF cannot expand beyond 255 hash lengths")
    prk = hmac.digest(salt or bytes(32), root, hashlib.sha256)
    out, block, counter = b"", b"", 1
    while len(out) < length:
        block = hmac.digest(prk, block + info + bytes([counter]), hashlib.sha256)
        out += block
        counter += 1
    return out[:length]


def collision_probability(secrets: int, digest_bytes: int = TOKEN_BYTES) -> float:
    """Birthday bound: chance that ANY two of `secrets` values share a token."""
    if secrets < 2:
        return 0.0
    space = 2 ** (8 * digest_bytes)
    return 1.0 - math.exp(-(secrets * (secrets - 1)) / (2 * space))


def flatten(value: str) -> str:
    """The form a token is computed over: whitespace collapsed, case folded.

    ``NGUYỄN VĂN MẪU`` on a letterhead and ``Nguyễn Văn Mẫu`` in the body are
    the same person (a synthetic example) and must wear the same token.
    """
    return " ".join(value.split()).lower()


@dataclass(frozen=True, slots=True)
class Keyring:
    root: bytes

    @classmethod
    def from_text(cls, text: str) -> "Keyring":
        if not text:
            raise ValueError(
                "a root key is required: unkeyed hashes of a small, guessable "
                "value set — Vietnamese names, phone numbers — are reversible "
                "by dictionary attack")
        return cls(text.encode("utf-8"))

    def subkey(self, purpose: str) -> bytes:
        if purpose not in PURPOSES:
            raise KeyError(
                f"no subkey for {purpose!r}; known: {sorted(PURPOSES)}. "
                "Anonymisation deliberately has none.")
        return hkdf(self.root, PURPOSES[purpose])

    def token_digest(self, category: str, value: str) -> str:
        """The hex inside a token. The category is part of the input, so one
        string as a PERSON and as an ORG does not collapse to one token."""
        mac = hmac.digest(self.subkey("token"),
                          f"{category}|{flatten(value)}".encode(), hashlib.sha256)
        return mac.hex()[:TOKEN_BYTES * 2]
