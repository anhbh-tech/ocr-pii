# pii-core

pii-core runs on a case document before its text reaches jev ai or an agent.
It decides, field by field, whether the value is **kept**, **pseudonymised**
(a reversible token, dates included), **anonymised** (`[CATEGORY]`,
irreversible) or **removed**. Each field carries its reason.

It was built fresh and depends on neither ancestor:

- **pii-lab** supplies the decision model (R × L risk against measured need N),
  its frozen evidence, the keyring and the policy order;
- **ocr-lab `pii.js`** supplies several detector shapes.

Where the two disagree, [docs/RECONCILIATION.md](docs/RECONCILIATION.md)
says which value won and why.

It uses the standard library only and needs Python ≥ 3.11.

```sh
uv run --extra dev pytest          # or: pip install -e '.[dev]' && pytest
```

## The two entry points

```python
from pii_core import Policy, Roster, redact_document, restore

policy = Policy(key, roster=Roster.load("roster.json"))   # key: the firm's secret

# Field level: (label, value) -> action + reason
r = policy.field("Họ và tên", "Nguyễn Văn Mẫu", group="CASE-042")
r.action    # 'PSEUDONYMISE'
r.after     # '[PERSON-3488c45033]'
r.reason    # 'nhãn “Họ và tên” khai báo PERSON. rủi ro MEDIUM (R 84% × L 2), và N = 2: …'

# Document level: extracted text -> redacted text + vault
result = redact_document(ocr_text, policy, group="CASE-042", source="scan-01.pdf")
result.text      # what the agent may read
result.fields    # audit: category, action, reason, span, label; NO original values
result.residue   # untreated PII found by a second look at the output; [] = ok
result.vault     # token -> original; the CALLER keeps it

restore(agent_answer, result.vault)   # tokens back
```

`redact_document` takes the place of pii-lab's missing first step: it finds
the candidate fields in free text. It works in three tiers:

1. **Labels.** `Label: value` lines (several on one line, or the value on the
   next line), markdown tables and HTML tables. The label decides the
   category.
2. **Exact patterns.** CCCD/passport, MRZ, e-mail, phone, published
   switchboard, tax code, account / routing number, machine trace (a registry
   e-seal, a card transaction id), money, dates, matter refs, application
   serials, URLs, the national motto. A mark under a label is then looked for again in the prose. A pattern inside a labelled value keeps its own treatment:
   `MST 0312345678` inside a representative's line is still a TAX_CODE.
3. **Heuristics** for running text: person names (a surname and name
   lexicon that also matches lowercase and unaccented text, kinship, role and
   self-introduction cues, Western given names), legal-form organisation
   names, street addresses and admin areas. A name found once with confidence
   is then looked for again in every shape, across the document and, through
   `redact_case` or a carried vault, across the case; every shape gets the
   one token.

**Case variables** — the facts of the matter the caller already knows: the
client's name, the matter code, the mark. Pass them and every mention is
replaced whatever shape it arrived in, because the match is on a folded form
(accents stripped, case folded, separators dropped) over whole words, with
one typo tolerated for a letters-only value:

```python
from pii_core import parse_vars
result = redact_document(text, policy, group="CASE-042", case_vars=parse_vars(
    {"Tên KH": "Thị Mộng Vân Quách", "Nhãn hiệu": "MAUMAUOI"}))
```

`Thi Mong Van Quach`, `@Mongvan Quach` and a mark mistyped by one letter are then
the same value, and every mention wears the one token. A code is never
fuzzed: one digit apart, two matter codes are two matters. The category comes
from the variable's name (`Tên KH` → PERSON), else from the value's own
shape.

**Roster names** are found in any tier, and the roster says whose they are.
The firm's own names (`FIRM`) are kept. Opposing parties (`PARTY`) and
agencies (`AGENCY`: Cục SHTT, USPTO, a court) are tokenised under their
roster name, so every alias wears one token. L = 0 values such as URLs and
boilerplate are kept and shield their spans from the heuristics. Application
serials, registration numbers and mark names are public on the register but
are tokenised: looked up, they name the client (Luật Luật sư Điều 25;
docs/RECONCILIATION.md).

**Dates.** A date of birth (`BIRTH_DATE`, found by its label or by a cue such
as `sinh ngày`) is anonymised. Every other date is a procedural date (`DATE`)
and is tokenised: `[DATE-…]`, one token per calendar day however it is
written, restored from the vault. Dates are not shifted any more. A shift
shared by the whole case falls to one known pair of real dates.

> **Deadlines and stages run on real dates, inside the trusted zone.** A
> `[DATE-…]` token carries no interval: the agent cannot tell which of two
> dates came first, nor count the days between them. So a deadline, a
> response window or a stage inferred from the gap between a filing and a
> notice has to be computed before masking (from the original text or the
> matter's own records), or after `restore` puts the real dates back, on
> the firm's side of the gate. Never ask the agent to do date arithmetic on
> masked text.

`group` is the case. A vault belongs to one case. Pass `vault=` to continue
it across that case's documents, or send them together (`redact_case`,
`POST /v1/case`).

## Calling it from the node-check chain (bpmn_editor)

The chain goes OCR → **pii-core** → agent → **pii-core** → wherever the
answer goes. Run the service beside the bpmn_editor server, which also binds
loopback. pii-lab's server uses 8812; pii-core uses 8813.

```sh
export PII_CORE_KEY_FILE=~/.config/pii-core/key     # or PII_CORE_KEY=...
export PII_CORE_ROSTER=~/.config/pii-core/roster.json
pii-core serve                                     # http://127.0.0.1:8813
```

**1. Before the agent**, send the OCR text:

```http
POST /v1/document
Content-Type: application/json

{"text": "<OCR output>", "group": "<case id>", "source": "<file name>",
 "vars": {"Tên KH": "…", "Mã hồ sơ": "…", "Nhãn hiệu": "…"},
 "vault": <the case's vault so far, or omit>}
```

```jsonc
{
  "text": "Họ và tên: [PERSON-3488c45033] …",   // → the agent, and nothing else
  "summary": {"fields": 24, "by_action": {"KEEP": 3, "PSEUDONYMISE": 20,
              "ANONYMISE": 1}, "residue": 0, "ok": true, …},
  "fields": [{"category": "PERSON", "action": "PSEUDONYMISE",
              "reason": "…", "start": 101, "end": 115,
              "replacement": "[PERSON-3488c45033]", "matched_by": "label",
              "label": "Họ và tên", "provisional": false}, …],
  "residue": [],                              // non-empty → do not forward
  "source": "[SOURCE_FILE]",
  "vault": {"version": 1, "group": "…", "date_shift_days": 0,
            "tokens": {"[PERSON-3488c45033]": {"category": "PERSON",
                                                "value": "…"}},
            "dates": {}}                        // keep it; never to the agent
}
```

The node check should:

- **forward only `text`**;
- **block when `summary.ok` is false**, i.e. `residue` is non-empty. That
  means something PII-shaped survived, such as a long digit run no detector
  claimed;
- **store `vault` against the case**, on the caller's side. It is the only
  copy that can reverse the tokens.

**2. After the agent**, reverse its answer:

```http
POST /v1/restore
{"text": "<agent answer>", "vault": <the case's vault>, "unshift_dates": true}
→ {"text": "<answer with originals back>"}
```

Tokens are replaced by their originals, procedural dates included. A date
the agent wrote out itself is left alone. `[NATIONAL_ID]`- and
`[BIRTH_DATE]`-style markers stay: they are irreversible by design. A vault
written before 2026-09-28 still carries a date shift (`date_shift_days` ≠ 0,
`dates` non-empty); with it, the shifted dates come back exactly and any
other date is moved back by the case's offset, as before.

**A whole case in one call.** `POST /v1/case` does for an HTTP caller what
`redact_case` does for the library: a name, a mark or a matter code found in
any document is sought in all of them, the earlier ones included, and one
vault covers the case.

```http
POST /v1/case
{"texts": ["<doc 1>", "<doc 2>", …], "group": "<case id>",
 "sources": ["<file 1>", null, …],          // optional, one per text
 "vars": {…}, "vault": <the case's vault so far, or omit>}
```

```jsonc
{
  "documents": [{"text": "…", "summary": {…}, "fields": [...],
                 "residue": [], "source": "[SOURCE_FILE]"}, …],  // in order, no vault
  "vault": {…},                                  // one, for the whole case
  "summary": {"documents": 2, "fields": 41, "residue": 0, "tokens": 17, "ok": true}
}
```

Each document's `fields` index that document's own input, exactly as
`/v1/document`'s do. Block the case when `summary.ok` is false, and forward
only the documents' `text`.

**Other endpoints:**

| method | path | body | returns |
|---|---|---|---|
| GET | `/health` | | `{ok, version, roster, categories}` |
| GET | `/v1/decisions` | | the decision table with every input and `why` |
| POST | `/v1/field` | `{label, value, group?}` | the field result, plus `vault` holding its tokens |
| POST | `/v1/fields` | `{fields: [{label, value}], group?}` | `{fields: [...], vault}` |
| POST | `/v1/case` | `{texts: [...], group?, sources?, vars?, vault?}` | `{documents: [...], vault, summary}` |

Errors are `{"error": "..."}` with 400 (bad input), 403 (not a loopback peer,
or a foreign `Host`), 404, 405, 409 (vault from another case), 411, 413
(body over 8 MiB) or 415 (not `application/json`).

**CLI**, for a chain that shells out instead:

```sh
pii-core document scan.txt --group CASE-042 --source scan-01.pdf \
    --vars-file case-vars.json \
    --vault-in case.vault.json --vault-out case.vault.json --strict > safe.txt
pii-core restore answer.txt --vault case.vault.json > answer.restored.txt
pii-core field "Số CCCD" "001099000001"
pii-core decisions
```

`--var "Tên KH=…"` (repeatable) and `--vars-file` (JSON, or `NAME=VALUE`
lines) carry the matter's own facts; prefer the file, so no client name
stands in a shell history.

`document` writes the redacted text to stdout. With `--json` it writes the
full result *without* the vault. The vault only ever goes to `--vault-out`,
mode 0600. `--strict` exits 3 when residue is found. Configuration errors
exit 2.

## Guarantees and limits

- **Loopback only.** `serve` refuses `0.0.0.0`, `::`, the empty string and
  every non-loopback address before opening a socket. `localhost` is pinned
  to 127.0.0.1. Requests are refused unless the peer is loopback, the `Host`
  header is the bound address and a POST is `application/json`, which a
  cross-origin page cannot send without a preflight. Logs carry method, path
  and status, never a body.
- **The key never travels.** It is read from `PII_CORE_KEY`,
  `PII_CORE_KEY_FILE` or `--key-file`, and there is no default. The same key
  must be used to redact and to restore a case. The same key as pii-lab gives
  pii-lab's tokens (pii-lab still shifts dates; pii-core tokenises them).
- **The vault holds only pseudonymised originals.** Anonymised and removed
  values are written nowhere. `*.vault.json` is git-ignored.
- **The roster is supplied at run time.** It is a JSON list of
  `{name, category: FIRM|PARTY|AGENCY, why, aliases}`, given as `--roster FILE` or
  `PII_CORE_ROSTER=FILE`. Keep it outside this repository — it holds real
  names — e.g. `~/.private/pii-core/roster.json`, mode 0600:

  ```sh
  install -m 700 -d ~/.private/pii-core
  cat > ~/.private/pii-core/roster.json <<'JSON'
  [{"name": "<internal lawyer>", "category": "FIRM", "why": "our own staff"},
   {"name": "<opposing party>", "category": "PARTY", "why": "the other side"},
   {"name": "<agency>", "category": "AGENCY", "why": "examining office"}]
  JSON
  chmod 600 ~/.private/pii-core/roster.json
  export PII_CORE_ROSTER=~/.private/pii-core/roster.json
  ```

  **Load the internal staff roster before real use.** With no roster every
  name is treated as a client's — the safe direction, but it tokenises the
  firm's own lawyers out of their own memos. `serve` warns when the roster is
  empty and `/health` reports its size.
- **Heuristics miss things.** `uv run python tests/name_bench.py` measures
  them on invented names. On the held-out set, 87.8% of mentions are caught
  one document at a time and 100% across a case where each person is labelled
  once. The misses are names whose surname or Western first name the lexicon
  lacks, with no label or cue anywhere in the case. Headings led by a surname
  syllable are still taken for names: 102 of 880 held-out negatives.
  The residue check flags digit runs and name-shaped runs, and a flag stops
  the document. Treat `summary.ok` as necessary, not sufficient.
- **Provisional categories** are those whose L no instrument settles
  (INVOICE_NO, MATTER_REF). Their results carry `provisional: true`, and
  their reason says so. BIRTH_DATE, GEO and OTHER_ID are settled against
  Nghị định 13, DATE against Luật Luật sư Điều 25 (docs/RECONCILIATION.md,
  *L departures from pii-lab*).
- **Image categories.** `FACE_PHOTO`, `SIGNATURE`, `FINGERPRINT`,
  `SCAN_CODE`, `MARK_IMAGE` (a figurative mark) and `LOGO` stand only on a
  page image. pii-core never finds them in text; they are in the table
  (`image: true` in `/v1/decisions`) so that whoever masks the page image
  reads its action from the same source. All six are REMOVE: masked on every
  masked copy, with no copy kept.
- **Synthetic data only.** Every fixture is invented (tests/fixtures/README.md).
  `tests/test_synthetic_only.py` fails if a tracked file holds an e-mail,
  phone or 12-digit ID outside the reserved invented shapes.
