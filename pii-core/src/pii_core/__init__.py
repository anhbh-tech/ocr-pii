"""pii-core: classify every field of a case document as keep / pseudonymise /
anonymise / remove, and redact it, before it reaches jev ai or an agent.

    from pii_core import Policy, redact_document, restore

    policy = Policy(key)                                  # key from the firm
    policy.field("Họ và tên", "Nguyễn Văn Mẫu")           # one field
    result = redact_document(text, policy, group="CASE")  # one document
    restore(answer, result.vault)                         # back again

``Nguyễn Văn Mẫu`` is a synthetic example name, not a real person.
"""
__version__ = "0.1.0"

from .casevars import CaseVar, parse_vars  # noqa: E402
from .decide import Action, Decision, decisions  # noqa: E402
from .document import (DocumentResult, FieldRecord, Vault, VaultError,  # noqa: E402
                       redact_case, redact_document, restore)
from .extract import Hit, extract  # noqa: E402
from .parties import Party, Roster  # noqa: E402
from .policy import FieldResult, Policy  # noqa: E402

__all__ = ["__version__", "Action", "CaseVar", "Decision", "decisions",
           "parse_vars", "DocumentResult",
           "FieldRecord", "Vault", "VaultError", "redact_case", "redact_document", "restore",
           "Hit", "extract", "Party", "Roster", "FieldResult", "Policy"]
