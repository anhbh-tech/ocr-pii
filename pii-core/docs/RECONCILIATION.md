# Reconciliation: pii-lab × ocr-lab `pii.js`

pii-core has two ancestors, and it copies code from neither:

| | pii-lab (`fm/pii-decision-lab` @ `3102d30`) | ocr-lab `web/src/lib/pii.js` |
|---|---|---|
| R | measured share of values seen in one matter (0–1); worst case R = 1 below 20 distinct values | integer 0–3, hand-read from the same kind of measurement |
| L | looked up from a cited instrument (decree, statute, firm statement, public record), or marked *proposed* | integer 0–3, set by hand |
| N | measured: facts lost, cross-document links, sole anchors, declared searchable | integer 0–3, set by hand |
| outcomes | KEEP / PSEUDONYMISE / ANONYMISE / REMOVE | keep / pseudo / anon |

**pii-lab's decision model is the source of truth** (the brief says so). Every
row below is pii-lab's action, computed by `pii_core.decide` from pii-lab's
frozen evidence (`src/pii_core/data/evidence.json`). ocr-lab contributed
detector shapes, one threshold, and a list of disagreements worth writing
down.

## The rules

| | pii-lab (wins) | pii.js | Why pii-lab's won |
|---|---|---|---|
| KEEP when | risk is NONE, i.e. L = 0 | R × L ≤ 2 (of 9) | ocr-lab would KEEP a value with R = 2 and L = 1 (a date, a matter code) purely because the product is small. pii-lab keeps only what cannot hurt anyone if it leaks. A small product still means *some* harm. |
| PSEUDONYMISE when | N ≥ 2 | risk ≥ 3 and N ≥ 2 | Same threshold. **`REVERSIBLE_NEEDS_N = 2` is ocr-lab's number**: "a reversible copy has to be paid for by more than one signal". pii-lab adopted it. |
| ANONYMISE when | HIGH risk and N > 0, or risk not HIGH and N = 0 | risk ≥ 3 and N ≤ 1 | Where both models apply, they give the same answer. |
| REMOVE | HIGH risk and N = 0 | *(no such outcome)* | When nothing needs a value and a leak is severe, even a `[CATEGORY]` marker says nothing useful. ocr-lab has three buckets, so its MRZ goes to `anon`. |
| inputs | measured, with the measurement in every `why` | typed in | pii-lab's `why` names the evidence, so a disagreement can be argued with numbers. |

## Category by category

`pii.js` score = R × L → outcome. The pii-core row gives pii-lab's R (as a
percentage), L and N.

| pii.js `id` | pii.js R·L·N → outcome | pii-core category | pii-core R · L · N → action | Which won, and why |
|---|---|---|---|---|
| `cccd` | 3·3·1 → **anon** | `NATIONAL_ID` | 80% · 3 · 1 → **ANONYMISE** | Agree. The detector is pii-lab's shape (a province code 001–096 leads), with added 3-digit groups and a cue form (`Số CCCD:`, `Hộ chiếu`). pii.js's bare `\b\d{12}\b` also swallows bank accounts and serials. |
| `mrz` | 3·3·0 → **anon** | `MRZ` | — · 3 · 0 → **REMOVE** | **pii-lab.** At N = 0 there is nothing to anonymise *for*. The detector keeps ocr-lab's `IDVNM…` and adds the generic ICAO line shape. |
| `email` | 3·2·2 → pseudo | `EMAIL` | 90% · 2 · 2 → PSEUDONYMISE | Agree. |
| `phone` | 3·2·2 → pseudo | `PHONE` | 90% · 2 · 2 → PSEUDONYMISE | Agree. pii.js's `(?:\+84\|0)[35789]\d{8}` misses spaced (`0900 000 001`), dotted, landline `(028) …` and US numbers. pii-core's detector covers them. |
| `mst` | 3·2·2 → pseudo | `TAX_CODE` | 71% · 2 · 2 → PSEUDONYMISE | Agree. The bare 10-digit shape is kept (priority 60), behind the cued form (`MST`, `Mã số thuế`, …; priority 72). |
| `dkkd` | 3·2·2 → pseudo | `TAX_CODE` | *(as above)* | Folded in. Since 2015 the business registration number *is* the enterprise tax code, so one category with one token keeps a company joinable across its stamp and its invoice. ocr-lab's stamp cue (`S.Đ.K.D`, `ĐKKD`) is adopted in `tax-cue`. |
| `money` | 3·2·3 → pseudo | `MONEY` | 90% · **3** · 2 → PSEUDONYMISE | Same action, different inputs. **L: pii-lab's 3** over pii.js's 2: the firm stated it, because a fee line carries both cost and margin. **N: pii-lab's measured 2** over pii.js's asserted 3. pii.js's "pseudonymise *by range*" (bucketing) is **not** adopted: a token is exact and reversible, a bucket is neither. |
| `ho_so` | 3·1·3 → pseudo | `MATTER_REF` | 100% · 1 · 2 → PSEUDONYMISE | Agree. The detector is ocr-lab's shape, verbatim (`NH/BQ/TV` + digits). |
| `don` | 3·1·3 → **pseudo** | `APP_SERIAL` | 100% · **1** · 3 → **PSEUDONYMISE** | **pii.js, on the firm's ruling (2026-09-23).** pii-lab gave the number L = 0 because the register publishes it, and kept it. The firm overruled that: looked up, the number names its applicant, and the lawyer–client relationship before filing and the advice given are not public (Luật Luật sư Điều 25). L = 1, N was already 3, so it is tokenised; a lawyer looks it up after de-tokenising locally. The detector takes ocr-lab's USPTO shape `[789]\d{7}` and adds IP Vietnam's `4-2024-12345`. `REG_NUMBER` (granted certificates) follows the same ruling. See *L departures from pii-lab*. |
| `ngay` | 2·2·3 → pseudo | `DATE` + `BIRTH_DATE` | DATE 90% · **1** · 2 → PSEUDONYMISE (a **token**); BIRTH_DATE — · 2 · 0 → **ANONYMISE** | **The firm, 2026-09-28 (P1)**, over both. pii.js and pii-lab shift dates by one keyed offset per case; pii-core did too. Split: a date of birth is anonymised, and a procedural date is tokenised rather than shifted. See *The firm's rulings of 2026-09-28*. pii.js's `\d{1,2}/\d{1,2}/\d{4}` covers one of pii-core's five shapes (`ngày 5 tháng 3 năm 2024`, ISO, dotted/dashed, English month names). |
| `dia_chi` | 2·2·1 → **anon** | `ADDRESS` | 95% · 2 · **2** → **PSEUDONYMISE** | **pii-lab.** N is measured: 262 cross-document links, so N = 2, where pii.js's hand-set N is 1. Anonymising would cut the links between a client's documents that share an address. **Left open:** pii.js's point that a lawyer needs only the province (for venue) is sound. Generalising to province (a `GEO` value, which is ANONYMISE here) is a possible later refinement, not something either model decides today. ocr-lab's rule that a street word must follow the house number (so `số 88123456`, a serial, is not taken for an address) is kept in `_VN_ADDRESS`. |
| `quoc_hieu` | 0·0·1 → keep | `BOILERPLATE` | — · 0 · 0 → KEEP | Agree. `BOILERPLATE` is the one category pii-core adds to pii-lab's 21. pii-lab never needed it, because its table cells never contain the national motto. In free text it has to be recognised so that the name heuristics leave `CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM` alone. |

## Only in pii-lab

pii.js has no row for these; the action is pii-lab's:

| category | action | note |
|---|---|---|
| `PERSON` | PSEUDONYMISE | label-first, plus a surname/honorific heuristic for running text |
| `ORG` | PSEUDONYMISE | legal-form cue (`Công ty TNHH …`) or an English suffix (`… Ltd`) |
| `SOURCE_FILE` | ANONYMISE | the `source` argument of `redact_document`; file names carry client names |
| `GEO` | ANONYMISE | two or more admin segments with no street (`Phường Mẫu, Quận Thử`) |
| `INVOICE_NO`, `OTHER_ID` | PSEUDONYMISE | `OTHER_ID` is found by account cues (`STK`, `Số tài khoản`, `IBAN`); `Mã tra cứu` (an e-invoice lookup code) is an `INVOICE_NO` label |
| `HOTLINE` | KEEP | new in pii-core; a published switchboard (VN 1900/1800, US freephone 800/833/844/855/866/877/888). Recognised by the reserved prefix only, never by guesswork: a mobile number is a `PHONE` |
| `MACHINE_TRACE` | ANONYMISE | new in pii-core; a registry e-seal (`STAMP:…`, which carries an IP address and a filing timestamp) or a card transaction id. L is *proposed*: no instrument reaches it |
| `MARK` | PSEUDONYMISE | new in pii-core; a mark label (`Tên nhãn hiệu`, `Trademark name`, `Brand`), then every later mention of that mark as written, in capitals or in title case, across the case |
| `NICE_CLASS`, `URL` | KEEP | L = 0 |
| `FIRM` | KEEP | roster only, see below |
| `PARTY` | **PSEUDONYMISE** (pii-lab: KEEP) | roster only; the firm's 2026-09-28 ruling (P2) |
| `AGENCY` | PSEUDONYMISE | new in pii-core; roster only; P2 |
| `BIRTH_DATE` | ANONYMISE | new in pii-core; split out of `DATE` (P1) |
| `FACE_PHOTO`, `SIGNATURE`, `FINGERPRINT`, `SCAN_CODE`, `MARK_IMAGE`, `LOGO` | REMOVE | new in pii-core; on a page image only (`image: true`); the pipeline report §2.3 rows 21, 29–31 and P4 |

### The two number kinds the 2026-09-24 dry run forced

A dry run of a case-step agent over nine real steps was refused by the gate on
eight of them. `document.RESIDUE_DIGITS` — the second look that flags any run
of nine or more digits nothing treated — was right every time: nothing *had*
treated them. Four kinds of number were reaching it unrecognised:

| what stood in the document | now | why |
|---|---|---|
| a published agency switchboard | `HOTLINE`, KEEP | Nghị định 13 Điều 2.3 says the phone number *of an individual*. A freephone number is issued to an organisation and printed on its own page; masking it stops the lawyer calling anyone |
| a registry e-seal, a card transaction id | `MACHINE_TRACE`, ANONYMISE | operational traces. No measurement needs to read one back, so no reversibility is bought |
| a bank account / routing number with its label lost to the table extraction | `OTHER_ID`, PSEUDONYMISE | the row's own category; only the recognition was missing (a cue word within 200 characters, or a bank's name) |
| two amounts of a fee table glued together when the cell wall was lost | `MONEY` | one dotted run that is not one well-formed amount |

The sieve was not loosened, and must not be: it is the only thing standing
between an unrecognised identifier and the agent. What changed is upstream
recognition. `APP_SERIAL` and `REG_NUMBER` were already PSEUDONYMISE, so an
application or registration number blocks nothing.

## L departures from pii-lab

pii-lab left five categories' L *proposed*. pii-core settles three of them
against Nghị định 13/2023 and keeps two proposed. Those three change no
action. The firm then overruled pii-lab on the register values (2026-09-23),
and that does change two: `APP_SERIAL` and `REG_NUMBER` go from KEEP to
PSEUDONYMISE. `tests/test_decide.py` holds pii-lab's frozen table and lists
these two as `DEPARTURES`. The firm's rulings of 2026-09-28 add a third,
`PARTY`, re-rank `DATE`, and add the rows from `BIRTH_DATE` down (see *The
firm's rulings of 2026-09-28*).

| category | pii-lab L | pii-core L | basis | risk | N | action |
|---|---|---|---|---|---|---|
| `DATE` | 1 (proposed) | **1** (was 2 until 2026-09-28) | Luật Luật sư Điều 25: a filing date and the register lead to the application | LOW (90% × 1) | 2 | PSEUDONYMISE, **as a token** |
| `BIRTH_DATE` | — (inside `DATE`) | **2** | Điều 2.3(b): date of birth | MEDIUM (R unmeasured, so 100% × 2) | 0 | **ANONYMISE** |
| `GEO` | 1 (proposed) | **2** | Điều 2.3(d): place of birth, residence, hometown | MEDIUM (100% × 2) | 0 | ANONYMISE |
| `OTHER_ID` | 1 (proposed) | **3** | Điều 2.4(h): a credit-institution customer's account | HIGH (100% × 3) | 2 | PSEUDONYMISE |
| `INVOICE_NO` | 1 (proposed) | 1 (proposed) | — | LOW | 3 | PSEUDONYMISE |
| `MATTER_REF` | 1 (proposed) | 1 (proposed) | — | LOW | 2 | PSEUDONYMISE |
| `MRZ` | 3 | 3 | Điều 2.3 basic, raised to 3 as `NATIONAL_ID` is (was cited as 2.4) | HIGH | 0 | REMOVE |
| `APP_SERIAL` | 0 (public record) | **1** | Luật Luật sư Điều 25: client confidence | LOW (100% × 1) | 3 | **PSEUDONYMISE** (was KEEP) |
| `REG_NUMBER` | 0 (public record) | **1** | Luật Luật sư Điều 25 | LOW (100% × 1) | 3 | **PSEUDONYMISE** (was KEEP) |
| `HOTLINE` | — | **0** | public record: an organisation's own published number | NONE | 0 | KEEP |
| `MACHINE_TRACE` | — | 1 (proposed) | — | LOW (R unmeasured, so 100% × 1) | 0 | ANONYMISE |
| `MARK` | — (pii-lab sends `Trademark name` to PERSON) | **1** | Luật Luật sư Điều 25 | LOW (R unmeasured, so 100% × 1) | 2 | PSEUDONYMISE |
| `PARTY` | 0 (public record) | **2** | Luật Luật sư Điều 25: who the firm acts against is information about the matter | MEDIUM (R unmeasured, so 100% × 2) | 2 (declared) | **PSEUDONYMISE** (was KEEP) |
| `AGENCY` | — | **1** | Luật Luật sư Điều 25, as `APP_SERIAL` | LOW (R unmeasured, so 100% × 1) | 2 (declared) | PSEUDONYMISE |
| `FACE_PHOTO` | — | **3** | Điều 2.3(e): a person's image, raised to 3 as `NATIONAL_ID` is | HIGH | 0 | REMOVE |
| `FINGERPRINT` | — | **3** | Điều 2.4(đ): biometric | HIGH | 0 | REMOVE |
| `SCAN_CODE` | — | **3** | Điều 2.3: a CCCD's QR code holds its whole identity page, raised to 3 as `MRZ` is | HIGH | 0 | REMOVE |
| `SIGNATURE` | — | **3** | firm stated, 2026-09-28: a handwritten signature is enough to forge a document | HIGH | 0 | REMOVE |
| `MARK_IMAGE`, `LOGO` | — | **3** | firm stated, 2026-09-28 (P4): masked on every masked copy | HIGH | 0 | REMOVE |

- A category takes the L of its worst member: `OTHER_ID` holds bank account
  numbers as well as SWIFT codes. `DATE` did the same with dates of birth
  until 2026-09-28, when they became `BIRTH_DATE`.
- `OTHER_ID` is pseudonymised only because pii-lab declares it searchable. If
  that declaration is dropped, L 3 makes the action ANONYMISE.
- **The register values.** The register is public, but it is searched by
  number and by mark, and the result is the applicant: the client. The firm
  ruled that the lawyer–client relationship before filing and the content of
  the advice are not public information (Luật Luật sư Điều 25), even though
  the register is. So `APP_SERIAL` and `REG_NUMBER` take L = 1, and a mark's
  name, which pii-lab exempted, is a new category `MARK` with the same L.
  The cost: the agent can no longer read or compare the wording of two marks,
  and a register lookup needs a local de-tokenisation first.
- `MARK` has no measured N, since pii-lab's corpus never classed a mark. It is
  declared searchable in `decide.DECLARED_SEARCHABLE` (one mark must be one
  value across the application, the notices, an opposition, a renewal), which
  gives N = 2 and PSEUDONYMISE. Without that declaration it would be
  ANONYMISE, and every mention would lose its link to the others.
- `MACHINE_TRACE` is the only new *proposed* row. It is ANONYMISE rather than
  PSEUDONYMISE because N = 0: nothing in the case needs an e-seal code back.
  Its L is a guess in the safe direction; an instrument that reaches it (a
  registry's own terms on e-seal data) would settle it.
- `HOTLINE` is the mirror of `MARK`: a value whose *publication by its owner*
  is the whole point. It is recognised only by the reserved service prefixes,
  so the failure mode is a hotline read as a `PHONE` and tokenised — not a
  personal number read as a hotline and kept.
- Product, service and domain names stay exempt: the ruling was about marks.
  A domain name leads to its registrant as a mark leads to its applicant, so
  it is the next candidate for the same ruling.

## The firm's rulings of 2026-09-28

The pipeline report *OCR → PII → kho → truy hồi* (firstmate, 2026-09-28)
found three decision tables alive at once and ocr-lab masking from pii-lab's
frozen one. It put four policy questions to the firm (§6, P1–P4) and proposed
a row for every kind of value in an IP case file (§2.3). The firm ruled on all
four and adopted the proposals. What that changed here, each by its evidence:

| ruling | change | basis | how the action follows |
|---|---|---|---|
| **P1** split dates | `DATE` (procedural: filing, notice, deadline, signature) and a new `BIRTH_DATE` | a date of birth is Nghị định 13 Điều 2.3(b); a filing date is Luật Luật sư Điều 25, as a serial is | `BIRTH_DATE`: L 2, N 0 (no stage reads one back) → ANONYMISE. `DATE`: L 2 → 1 with its worst member gone, N 2 measured → PSEUDONYMISE |
| **P1** tokens, not a shift | a procedural date becomes `[DATE-…]`, computed over its ISO form, so one day is one token however it is written; the vault restores it | the firm: a plain shift is too easy to guess. One offset serves the whole case, so one known pair (a filing receipt beside its masked copy, a public register date) opens every date in it | the action is unchanged; only its treatment (`policy.apply_as`). Tokens carry no interval, so deadlines and stages are computed on real dates in the trusted zone (README, *Dates*) |
| **P2** agencies and opposing parties | `PARTY` L 0 → 2, a new `AGENCY` (L 1), both declared searchable | Luật Luật sư Điều 25: whom the firm acts for and against, and where the file stands, is information about the matter | L > 0 makes the risk non-zero; the declaration (`decide.DECLARED_SEARCHABLE`: retrieval by party or agency, restoring the name to draft a letter) gives N = 2 → PSEUDONYMISE. The roster still decides the category; `FIRM` stays KEEP |
| **P3** GEO | none: ANONYMISE already | Nghị định 13 Điều 2.3(d); N measured 0 | ocr-lab's `_GHI_DE_HANH_DONG = {"GEO": "PSEUDONYMISE"}` override is not adopted |
| **P4** figurative marks and logos | new `MARK_IMAGE`, `LOGO` | firm stated: masked on every masked copy; the original stays on the machine and image comparison runs there | L 3 (firm stated), N 0 → REMOVE |
| §2.3 rows 29–31 | new `FACE_PHOTO`, `SIGNATURE`, `FINGERPRINT`, `SCAN_CODE` | Điều 2.3(e), 2.4(đ), 2.3; a signature is firm stated | L 3, N 0 → REMOVE |

- The six image rows carry `image: true` and have `need` rows of zeros in
  `evidence.json` (`pii_core_rows` says why). No text detector produces them.
  They exist so that the tool that masks a page image — ocr-lab today, whose
  `_HINH` names four of them — reads its action from pii-core's table rather
  than from "an unknown category is masked". On an image every action but KEEP
  is one box; REMOVE adds that no copy of the pixels is kept, the vault
  included.
- `MARK_IMAGE` and `LOGO` are REMOVE rather than ANONYMISE, which on a page
  would draw the same box, because the firm chose REMOVE (P4 A). Their L = 3 is
  the firm's own statement, as `MONEY`'s is; no instrument reaches them.
- `PARTY` is the third departure from pii-lab's frozen actions
  (`DEPARTURES` in `tests/test_decide.py`). The others are rows pii-lab never
  had.
- **What P2 costs.** An agency token still tells the agent that two documents
  came from the same office, but not which office. A step that must know it,
  for instance stage inference that reads "a USPTO office action", runs in the
  trusted zone after restoring, or reads the matter's own records.
- **What P1 costs.** An agent can no longer compare two dates or count the
  days between them. A date written two ways (`02/02/2024`, `ngày 2 tháng 2
  năm 2024`) wears one token and restores as the form the case wrote first.
  A vault written before the ruling still holds its shift and its shifted
  dates; `restore` moves those back, and a case may be continued with it.

## What changed on the way in

- **The roster ships empty.** pii-lab's `parties.py` names real public
  counterparties in source. pii-core holds synthetic data only, so the roster
  is a JSON file supplied at run time (`--roster` / `PII_CORE_ROSTER`). The
  rule is still pii-lab's: the roster is checked on the value first, and its
  category wins over any label. With no roster, every name is treated as a
  client's, which is the safer mistake to make.
- **Roster names are also found inside running text.** A table cell is one
  value, but a paragraph is not. `Roster.find` matches whole roster names
  (accent- and case-folded) anywhere in the text, and those spans outrank
  every other detector.
- **Label map.** pii-lab's rules are kept, with these additions: `Tên` →
  PERSON, `Bằng chữ` / `Số tiền viết bằng chữ` → MONEY, a `MARK` rule ahead
  of PERSON (`Tên nhãn hiệu`, `Trademark name`, `Brand`), and a *not-PII*
  label list (product, service and domain names). A value under a not-PII
  label is kept rather than scanned.
- **Unlabelled values are scanned.** When pii-lab's `Policy.field` finds no
  label, it keeps the value. pii-core runs the pattern detectors on it
  instead, so `Ghi chú: gọi 0900 000 001` does not let a phone number through.
- **Tokens are byte-compatible with pii-lab.** They use the same HKDF info
  labels and the same `CATEGORY|flattened value` input. So with the same root
  key, a pii-lab table cell and a pii-core document field about the same
  person get the same token. The date shift is derived as pii-lab derives it,
  but since 2026-09-28 pii-core only checks legacy vaults against it: a
  `DATE` token (`DATE|<ISO date>`) has no pii-lab counterpart, because
  pii-lab shifts.
