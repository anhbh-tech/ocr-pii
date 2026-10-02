# Gaps the 2026-09-25 replay on real case text found

`redact_case` was run end to end, locally, over the 305 ingested chunks of one
real matter (Vietnamese and English: the engagement, the US filing, the
register pages, the invoices, the SWIFT advice). The real text stayed on the
machine and was deleted afterwards. This file records **shapes and labels
only**, never a value: every example below is invented.

|                                    | before | after |
|------------------------------------|-------:|------:|
| chunks stopped by the residue sieve | 14    | 2     |
| restored field ≠ original          | 62     | 53    |

No field failed to restore. The 53 left are all by design: 51 restore to the canonical spelling of the
same person, organisation, address or e-mail (`Hit.canonical`, one token per
entity), and 2 dates come back in the canonical date format. The 2 stopped
chunks are the garbled-font PDF below, and they are stopped on purpose.

## Fixed in pii-core

Each fix has a synthetic regression test. Lines are those of this branch.

### Names

| Shape (invented example) | Fix | Test |
|---|---|---|
| A middle initial ended the name, so the surname after it leaked: `Họ và tên: Nguyễn Văn A. Bình` → only `Nguyễn Văn A` masked | `_INNER_DOT` in the PERSON terminator, `extract.py:657,662`; `_past_initial` carries a pattern or case-seen hit past `. Surname`, `extract.py:679`, applied at `extract.py:634,1235` | `test_extract.py:564,573` |
| An honorific or role word taken into, or ending, the name after it (`bà`/`ông`/`anh`/`chị`/`Mr.` …) | `_without_honorific`, `extract.py:1056`; the `_ROLE` loop skips an honorific, `names.py:735` | `test_names.py:202` |
| OCR glued a name to the next field's role or English label (`Trần LanFirst Name:`) | `_glued`/`_syllable`/`_Piece`, `names.py:360-400`; `_GLUE`, `extract.py:653` | `test_names.py:170,207`; `test_extract.py:535` |
| A Western surname with an inner capital was cut (`McKay`, `LeBlanc`) | `_WEST_PREFIXED`, `names.py:344` | `test_names.py:175,211` |
| A currency or a thing after a surname-led run taken for a name (`Lê Dollar`, a surname on one line and `Baht` on the next) | `_THING_AFTER`, `names.py:291`, used at `names.py:491,822,916` | `test_names.py:216,190` |
| Phrases led by a surname or cue that name no one (`Luật sư` + a country, compound place names); an old vault holding one would take it from every later document | the `surname_led` compound/place guards, `names.py:283,465`; the `CaseNames` seed guards, `names.py:797`; `residue_names`, `names.py:897` | `test_names.py:190,194` |

### Labels and fields

| Shape | Fix | Test |
|---|---|---|
| A label with nothing after its colon, its value on the next line; or a next line that is another label or a heading | `_next_line_value`, `extract.py:866`; `HEADINGS`/`is_heading`, `labels.py:82,244` | `test_extract.py:266,275` |
| A form label with no colon over its value (`Owner Name` ⏎ value) | `_bare_label`, `extract.py:930` | `test_extract.py:286,296` |
| The register's two-column rendering: the label on one line, `: value` on the next | `_colon_led`, `extract.py:850` | `test_extract.py:464,474` |
| A label glued to the value before it, or to a token's `]` on a page read again | `_boundaries`, `extract.py:740`; `_GLUE`, `extract.py:653` | `test_extract.py:300,535` |
| A spaced dash inside a compact value | `_COMPACT`, `extract.py:667` | `test_extract.py:316` |
| Labels that declared nothing: representative, docket/reference number, `Reg. No.`, e-invoice `mã CQT`, bank account, routing number | `LABEL_RULES`, `labels.py:108-214` | `test_extract.py:312,479` |
| A date label over the register's filler (`Not Found`) masked a non-date, which then could not come back | `_datelike`, `extract.py:894` | `test_extract.py:483` |
| The legal form left once the caller's own name is cut from a label value (`, LLC`) | `_LEGAL_FORM`/`_form_only`, `extract.py:1108,1115` | `test_extract.py:526` |
| Words left beside a labelled number were tokenised as that number | `_fragments` keeps a split digit-kind piece only when it holds a digit, `extract.py:1120-1124` | `test_extract.py:586` |

### Number kinds (each one had stopped a document at the residue sieve)

The sieve (`document.RESIDUE_DIGITS`) was not widened; each kind was taught to
the recogniser.

| Shape | Category | Fix | Test |
|---|---|---|---|
| Trademark register number by its cue, including `RN # 9900001` | REG_NUMBER | `_REG_RX`, `extract.py:323` | `test_extract.py:334,342` |
| Application number in its other shapes | APP_SERIAL | `_APP_RX`, `extract.py:343` | `test_extract.py:350` |
| A routing number whose label was lost (ABA checksum near a bank cue) | OTHER_ID | `_find_routing`, `extract.py:356-377,578` | `test_extract.py:358,362` |
| SWIFT MT103 party account line (`50K:` / `59:` then `/account`) | OTHER_ID | `_SWIFT_ACCOUNT`, `extract.py:385,579` | `test_extract.py:372` |
| SWIFT acknowledgement reference | MACHINE_TRACE | `_SWIFT_ACK`, `extract.py:390,580` | `test_extract.py:376` |
| One digit repeated (OCR filler) | treated | `extract.py:391` | `test_extract.py:399` |
| Amounts with no currency in a fee table that has a total row | MONEY | `_TOTAL_ROW`/`_find_fee_table_cells`, `extract.py:427-434,585` | `test_extract.py:386,395,541,554` |
| A lawyer's bar membership number | OTHER_ID | `_BAR_RX`, `extract.py:332,605` | `test_extract.py:595` |
| The `Số` under an e-invoice heading | INVOICE_NO | `_INVOICE_RX`, `extract.py:338,606` | `test_extract.py:604,608` |

### Addresses and marks

| Shape | Fix | Test |
|---|---|---|
| A VN address unaccented or slashed (`12/3A`) | `_CAPWORD`, `_ADMIN`, `_STREET_KW`, `_VN_CITY`, `_VN_COUNTRY`, `extract.py:59-139` | `test_extract.py:460` |
| A US street line, a US city line, a street wrapped onto the next line | `_US_ADDRESS`, `_US_CITY_LINE`, `extract.py:156,177` | `test_extract.py:414,425,581,448` |
| A city line with a Canadian or British postcode | `_FOREIGN_CITY_LINE`, `extract.py:187`, in the address detector at `extract.py:613` | `test_extract.py:435,439` |
| A mark named only in quotes after a mark cue (`nhãn hiệu “Vidu”`), then sought again in the prose | `_MARK_CUE`/`_QUOTED`/`_find_quoted_marks`, `extract.py:448-460,608`; `mark_seeds`/`mark_hits`, `extract.py:1273,1280` | `test_extract.py:504,508,517,491` |

### Document tier

| Shape | Fix | Test |
|---|---|---|
| A PDF text layer with a broken font map (Cyrillic letters inside Latin words): no detector can read a name in it, so it passed as clean | `RESIDUE_GARBLED`, `document.py:48`, checked in `_residue`, `document.py:226` | `test_document.py:170,178` |

## Mask decisions and restore points relied on (unchanged)

- Actions: `Policy.action_for`, `policy.py:103`, from `data/evidence.json` via
  `decide.decide`, `decide.py:182`. Every category the new detectors emit
  (OTHER_ID, INVOICE_NO, MONEY, MARK, ADDRESS, REG_NUMBER, APP_SERIAL) is
  PSEUDONYMISE; GEO and MACHINE_TRACE are ANONYMISE; HOTLINE and FIRM are
  KEEP. No action changed, so nothing departs from pii-lab.
- Labelled fields: `Policy.field`, `policy.py:117`.
- Masking: `redact_document`, `document.py:239`; later documents seek the
  vault's PERSON, MARK and MATTER_REF values again, `document.py:269-277`;
  `redact_case`, `document.py:329`.
- The gate: `_residue`, `document.py:197`.
- Restore: `restore`, `document.py:360`, over `Vault`, `document.py:57`.

## Left open

**Outside pii-core. Recorded here; this branch does not change them.**

- **tro-ly-lark runs with no roster.** `PII_CORE_ROSTER` is unset in the
  bridge, api and db containers. `compose.yaml` passes no such variable, and
  `scripts/chuan-bi.sh:53` writes it only when the shell already has it. So
  `load_policy` (`tro_ly/pii.py:175`) loads an empty roster
  (`config.py:41`), and the firm's own staff and firm name are tokenised as a
  client's. They are masked, so nothing leaks, but they are treated as client
  data when they are FIRM (KEEP) data.
- **OCR is needed upstream.** One scanned PDF's text layer has a broken font
  map (2 chunks). The new residue kind stops it, correctly. Another page is
  garbled Latin OCR, so its e-mail and phone fragments cannot be read at all.
  Both need an OCR pass in the ingest before pii-core sees the text.

**In pii-core, and left as they are:**

- ~~**An `Owner Name` value that is a company**~~ is ORG since the
  2026-09-29 sweep (below).
- **The firm's own operating licence** (`Số giấy phép hoạt động: …/TP/ĐKHĐ`)
  stays in the text. It identifies the firm, not a client (FIRM is KEEP,
  `categories.py:126`), and it is below the sieve's 9 digits.
- **District and city lines after an ADDRESS token** stay at GEO level
  (ANONYMISE), as the evidence sets.
- **Public exchange rates** in a rate table near `USD` are tokenised as MONEY.
  This is over-treatment, it predates this branch, and it leaks nothing.
- **A toll-free hotline** is HOTLINE (KEEP), as the evidence sets.

# The 2026-09-29 sweep of two US trademark cases

The captain's report (a `Nationality` caption tokenised as PERSON; a
`<Name> - Law Firm` not read as an organisation) led to a sweep of both cases
through the real path (ADE cache → ocr-lab `lam_sach` → pii-core), per
document and per case. Counts and document ids are in the firstmate report
for `pii-m5-nationality-org`, not here.

**Fixed in pii-core** (each with a synthetic test):

- **Captions inside a name.** `lam_sach` flattens a table cell's `<br>` to a
  space, so `Full name: X Nationality: Y` arrives on one line. The name
  detectors ran over the next caption, and the label cut left the caption
  behind as a PERSON fragment. `names.CAPTIONS` now stops a name, the
  caption's own span is blocked in `resolve`, and a `First`/`Last`/`Given`
  word before a caption joins it (`First Name: X Last Name: Y`). A caption in
  brackets (`(Mailing address):`) is a caption unless prose leads it.
- **Organisations without a roster.** A legal form in Title case or capitals
  (`Law Firm`, `CO., LTD`, `COMPANY LIMITED`, `Sdn Bhd`, `S.r.l`, …) or a
  Vietnamese cue (`Văn phòng Luật sư`, `Ngân hàng`) makes an ORG, and a
  company under a person's label (`Applicant:`, `Owner Name:`) is ORG. Its
  name without the legal form is sought again (`org_hits`, detector
  `org-case`), and every writing of it wears one token (`org_forms`),
  including a seal that names the district after the firm.
- **A client's company name left in the clear.** A name in capitals that
  wraps in a letterhead or a bank transfer (`… VẬN⏎TẢI …`), the transfer's
  `CTTNHH`/`CTCP`, a name in sentence case with its trades in lower case
  (`Công ty TNHH⏎Thương mại dịch vụ vận tải và Công nghệ <name>`), and the
  words a seal reads under ocr-lab's `[STAMPED]` marker. The wrap stops at a
  digit, a colon, a caption, a heading, a person's name, and under two
  companies read side by side.
- **Vault names are guesses.** A PERSON value the vault holds is sought again
  only in a name's shape (one casing, never accented lower case) and with the
  accents it was seen with. Before, a vault name that was really a prose
  phrase was sought in every later document.
- **Mark captions that declare nothing** (`Type of Mark:`, `Mark Drawing
  Type:`) and a price under a mark caption (`Tra cứu nhãn hiệu chữ: $500 …`)
  are no MARK. `Description of Mark` stays MARK: a design mark's description
  identifies it.
- **A name a mail header gives its address** (`To: J. Mau Placeholder
  (…@example.com)`), a name with a middle initial sought again whole, and a
  printed timestamp (`Tue Mar 5 09:12:30 ET 2024`) as a DATE.
- A crash: `CaseNames` raised `IndexError` on a text ending with a cue and a
  known given name.

**Left open**: a truncated company name (`… Mau Thu Compan`) in a document
that names the company nowhere else is found only with the case (`POST
/v1/case`) or a case variable. Policy calls (the options are in the
report): whether a
nationality value is PII under Decree 13; `Mỹ` after `Luật sư` read as a
person; public case-law parties and banks tokenised as ORG; the firm itself
tokenised when no roster is loaded. Upstream, `lam_sach` could map a cell's
`<br>` to a newline, which would remove the trigger of the first fault.
