"""Find candidate PII fields in the extracted text of a case document.

This is the step the survey found missing from both projects: pii-lab decides
what to do with a *labelled table cell*, ocr-lab regex-scans *free text*, and
neither turns an OCR'd case document into a list of fields. Three sources of
candidates, in order of how much they are trusted:

1. **Labels** (tier ``label``). ``Họ và tên: ...``, ``| Địa chỉ | ... |``,
   ``<td>Email</td><td>...</td>``. The label map (:mod:`pii_core.labels`)
   says what the value IS; nothing is guessed about the value itself.
2. **Exact patterns** (tier ``exact``). Shapes with a checkable structure:
   e-mail, CCCD, MRZ, phone, tax code, money with a currency, dates, the
   firm's matter references, application serials, and the public shapes kept
   on purpose (URL, quốc hiệu).
3. **Heuristics** (tier ``heuristic``). Person names (:mod:`pii_core.names`:
   lexicon, cues, and a second pass that looks again for every name the
   document, or the case, already showed), organisations after ``Công ty`` /
   before ``Ltd``, street addresses, administrative-unit chains. These are
   the guesses.

Resolution (:func:`resolve`) — the part that decides safety:

* Sensitive exact hits are chosen first, by ocr-lab's rule: earliest start,
  then longest, then the detector's priority.
* A labelled value keeps its label's category, but exact hits inside it are
  **carved out** and keep their own treatment. ``Họ tên: X CCCD 0010...``
  must not put the CCCD under a reversible PERSON token: CCCD is ANONYMISE
  and a vault row would make it recoverable.
* KEEP hits (public shapes, labels that declare a public category, labels
  that declare a product or a domain) never suppress a sensitive exact hit.
  They only shield their span from the heuristics.
* Heuristic hits fill what is left, split around anything already taken, so
  a guessed address that runs into a phone number still covers both.
"""
from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, replace
from typing import Callable, Iterable, Iterator

from .categories import BY_CODE, Harm
from .dates import find_dates
from .labels import category_for_label, declares_not_pii, declares_nothing, fold, is_heading
from . import names
from .casevars import CASE_VAR_PRIORITY, CaseVar, find_vars
from .parties import Roster
from .policy import TOKEN

__all__ = ["Hit", "extract", "detect", "resolve", "labelled_fields",
           "pattern_hits", "roster_hits", "case_var_hits", "person_seeds",
           "mark_seeds", "mark_hits", "DETECTORS"]


# -- character classes ---------------------------------------------------------

_L = "a-zàáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ"
_U = "A-ZÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬĐÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴ"
_CAPWORD = rf"(?:\d+[A-Za-z]?(?:/\d+[A-Za-z]?)*|[{_U}][{_L}{_U}]*)"

_TRIM = " \t\r\n\xa0,.;:-–—()[]{}*_|/\\\"'`"


@dataclass(frozen=True, slots=True)
class Hit:
    """One candidate field. Offsets are into the text that was scanned."""

    start: int
    end: int
    category: str | None
    detector: str
    tier: str                    # "label" | "exact" | "heuristic"
    priority: int = 0
    label: str = ""
    label_start: int = -1
    label_end: int = -1
    #: For a name found again in the case: the form it was first found in,
    #: so every mention wears one token. Never written to the audit.
    canonical: str = ""

    @property
    def length(self) -> int:
        return self.end - self.start


def _keeps(category: str | None) -> bool:
    """Public by construction: L = 0 makes risk 0 whatever R measures."""
    if category is None:
        return True
    cat = BY_CODE.get(category)
    return cat is not None and cat.leak_harm is Harm.NONE


# -- exact detectors -----------------------------------------------------------

_AMOUNT = r"\d{1,3}(?:[.,   ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d+)?"
_CURRENCY_AFTER = r"(?:đồng|Đồng|ĐỒNG|VNĐ|VND|vnđ|vnd|đ|USD|usd|EUR|€|\$|₫)"
_CURRENCY_BEFORE = r"(?:US\s?\$|USD|VNĐ|VND|EUR|€|\$|₫)"
_SCALE = r"(?:triệu|tỷ|nghìn|ngàn|million|billion)"
# An amount spelled out ("mười hai triệu năm trăm nghìn đồng"), as contracts
# repeat it after the figure. Needs a scale word, so "năm hai đồng" is not one;
# "đồng" starting a compound ("đồng nghiệp", "đồng thời") is not currency.
_NUM_WORD = (r"(?:một|mốt|hai|ba|bốn|tư|năm|lăm|nhăm|sáu|bảy|bẩy|tám|chín|"
             r"mười|mươi|chục|trăm|nghìn|ngàn|triệu|tỷ|tỉ|linh|lẻ|không)")
_MONEY_WORDS = re.compile(
    rf"(?<![\w])(?:{_NUM_WORD}[ \t,]+){{2,}}đồng(?:[ \t]+chẵn)?(?![\w])"
    r"(?![ \t]+(?:nghiệp|ý|thời|hồ|bào|chí|hương|bằng|loạt|đều|phạm|minh|"
    r"sở hữu|tác giả|sáng lập)\b)", re.IGNORECASE)
_MONEY_SCALE_WORD = re.compile(r"\b(?:mười|mươi|trăm|nghìn|ngàn|triệu|tỷ|tỉ)\b",
                               re.IGNORECASE)


def _find_money_words(text: str) -> Iterator[tuple[int, int]]:
    for m in _MONEY_WORDS.finditer(text):
        if _MONEY_SCALE_WORD.search(m.group()):
            yield m.span()

_ADMIN = (r"(?:Phường|phường|PHƯỜNG|Xã|xã|XÃ|Thị trấn|thị trấn|THỊ TRẤN|"
          r"Quận|quận|QUẬN|Huyện|huyện|HUYỆN|Thị xã|thị xã|THỊ XÃ|"
          r"Thành phố|thành phố|THÀNH PHỐ|TP\.?|Tp\.?|Tỉnh|tỉnh|TỈNH|"
          r"Khu phố|khu phố|KP\.?|P\.|Q\.|Ward|District|Province|"
          # Unaccented, as a foreign form or a keyboard without Telex writes
          # it. Bare "Xa" stays out: it is a word of its own.
          r"Phuong|phuong|PHUONG|Quan|quan|QUAN|Huyen|huyen|HUYEN|"
          r"Thi tran|thi tran|Thi xa|thi xa|Thanh pho|thanh pho|THANH PHO|"
          r"Tinh|tinh|TINH)")
_ADMIN_SEG = rf"{_ADMIN}\s*{_CAPWORD}(?:[ \t]+{_CAPWORD}){{0,4}}"
_STREET_KW = (r"(?:đường|Đường|ĐƯỜNG|phố|Phố|PHỐ|ngõ|Ngõ|NGÕ|ngách|Ngách|"
              r"hẻm|Hẻm|HẺM|kiệt|Kiệt|tổ|Tổ|khu|Khu|thôn|Thôn|ấp|Ấp|xóm|Xóm|"
              r"lô|Lô|đại lộ|Đại lộ|Duong|duong|DUONG|Pho|pho|PHO|Hem|hem|HEM|"
              r"Ngo|ngo|NGO|Ngach|ngach|NGACH)")
_STREET_PART = rf"{_STREET_KW}[ \t]+{_CAPWORD}(?:[ \t]+{_CAPWORD}){{0,5}}"
_HOUSE = r"(?:(?:Số|số|SỐ|So|No\.?)[ \t]*)?\d+[A-Za-z]?(?:[/-]\d+[A-Za-z]?)*"

#: The cities that close an address with no keyword in front of them.
_VN_CITY = (r"(?:Hà Nội|HÀ NỘI|Ha Noi|HA NOI|Hanoi|HANOI|Hồ Chí Minh|HỒ CHÍ MINH|"
            r"Ho Chi Minh(?: City)?|HO CHI MINH(?: CITY)?|Đà Nẵng|Da Nang|"
            r"Hải Phòng|Hai Phong|Cần Thơ|Can Tho)")
_VN_COUNTRY = r"(?:Việt Nam|Vietnam|VIỆT NAM|Viet Nam|VIET NAM|VIETNAM|VN)"

_VN_ADDRESS = re.compile(
    rf"(?<![\w/]){_HOUSE}[ \t]*,?[ \t]*"
    rf"(?:(?P<kw>{_STREET_PART})(?:[ \t]*,?[ \t]*{_STREET_PART})*"
    rf"|{_CAPWORD}(?:[ \t]+{_CAPWORD}){{0,5}})"
    rf"(?P<adm>(?:[ \t]*[,-][ \t]*(?:{_STREET_PART}|{_ADMIN_SEG}))*)"
    rf"(?:[ \t]*,[ \t]*{_VN_CITY})?"
    rf"(?:[ \t]*,[ \t]*{_VN_COUNTRY})?"
    # The postcode that closes a foreign form's rendering of it.
    r"(?:[ \t]*,?[ \t]*\d{5,6}(?![\w]))?")
_US_SUFFIX = (r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|"
              r"Ln|Way|Court|Ct|Place|Pl|Parkway|Pkwy|Highway|Hwy|Circle|Cir|"
              r"Terrace|Ter|Trail|Trl|Square|Sq|Plaza|Plz)")
_US_DIRECTION = r"(?:N|S|E|W|NE|NW|SE|SW|North|South|East|West)"
_US_UNIT = (r"(?:,?[ \t]*(?:\r?\n[ \t]*)?"
            r"(?i:Suite|Ste|Apt|Unit|Floor|Fl|Room|Rm|#)\.?[ \t]*\d[\w-]*)")
_US_ADDRESS = re.compile(
    # A number, an optional direction, one to four words (capitalised, in
    # capitals, or an ordinal: ``8th``), the suffix in any case of its own.
    # A line may break between the words: ``53 Mau\nThu Street``.
    rf"(?<![\w])\d{{1,6}}[ \t]+(?:{_US_DIRECTION}\.?[ \t]+)?"
    rf"(?:(?:\d+(?:st|nd|rd|th)|[A-Z][A-Za-z'-]*\.?)(?:[ \t]+|[ \t]*\r?\n[ \t]*)){{1,4}}"
    rf"(?:{_US_SUFFIX}|(?i:{_US_SUFFIX}))\.?(?![\w])"
    rf"(?:[ \t]+{_US_DIRECTION}(?![\w]))?{_US_UNIT}?"
    rf"(?:,[ \t]*[A-Z][a-z]+(?:[ \t][A-Z][a-z]+)*,?[ \t]*[A-Z]{{2}}[ \t]+\d{{5}}(?:-\d{{4}})?)?"
    # Lower case, as a person types it: the abbreviation's period shows it.
    rf"|(?<![\w])\d{{3,6}}[ \t]+(?:[a-z]+[ \t]+){{1,3}}"
    r"(?:ct|st|ave|rd|dr|ln|blvd|pl|cir|ter|pkwy)\.(?=\s|$)"
    # A post-office box.
    r"|(?<![\w])(?:P\.?[ \t]?O\.?|Post Office)[ \t]*(?:Box|BOX)[ \t]*#?[ \t]*\d{1,7}(?![\w])")
#: The state codes, so ``Word, XX 00000`` is a city line and not prose.
_US_STATES = (r"(?:A[KLRZ]|C[AOT]|D[CE]|FL|GA|HI|I[ADLN]|K[SY]|LA|M[ADEINOST]|"
              r"N[CDEHJMVY]|O[HKR]|PA|PR|RI|S[CD]|T[NX]|UT|V[AT]|W[AIVY])")
_US_COUNTRY = r"(?:UNITED STATES(?: OF AMERICA)?|United States(?: of America)?|USA|U\.S\.A\.)"
_US_CITY = r"[A-Z][A-Za-z.'-]*(?:[ \t]+[A-Z][A-Za-z.'-]*){0,3}"
#: ``City, STATE UNITED STATES 00000``, as the register prints an owner, or
#: ``City, ST 00000``. The ZIP+4 may have lost its hyphen.
_US_CITY_LINE = re.compile(
    rf"(?<![\w]){_US_CITY},[ \t]+(?:[A-Z][A-Za-z]+[ \t]+){{1,3}}?{_US_COUNTRY}"
    r"[ \t]+\d{5}(?:-?\d{4})?(?![\w-])"
    rf"|(?<![\w]){_US_CITY},[ \t]+{_US_STATES}[ \t]+\d{{5}}(?:-?\d{{4}})?(?![\w-])"
    rf"(?:[ \t]+{_US_COUNTRY})?")
#: ``City, Province CANADA A9A 9A9`` or ``City UNITED KINGDOM AA9A 9AA``:
#: an owner abroad, as the register prints one. The postcode names a street.
_FOREIGN_POSTCODE = (
    r"(?:(?:CANADA|Canada)[ \t]+[A-Z]\d[A-Z][ \t]?\d[A-Z]\d"
    r"|(?:UNITED KINGDOM|United Kingdom|UK)[ \t]+[A-Z]{1,2}\d[A-Z\d]?[ \t]?\d[A-Z]{2})")
_FOREIGN_CITY_LINE = re.compile(
    rf"(?<![\w]){_US_CITY},?[ \t]+(?:[A-Z][A-Za-z]+[ \t]+){{0,3}}?{_FOREIGN_POSTCODE}(?![\w])")
_GEO = re.compile(
    rf"(?<![\w]){_ADMIN_SEG}(?:[ \t]*[,-][ \t]*{_ADMIN_SEG})+"
    rf"(?:[ \t]*,[ \t]*(?:Việt Nam|Vietnam|VIỆT NAM))?")


def _rx(pattern: str, flags: int = 0) -> Callable[[str], Iterator[tuple[int, int]]]:
    compiled = re.compile(pattern, flags)
    has_value = "v" in compiled.groupindex

    def find(text: str) -> Iterator[tuple[int, int]]:
        for m in compiled.finditer(text):
            yield m.span("v") if has_value else m.span()
    return find


def _rx_any(*finders: Callable[[str], Iterator[tuple[int, int]]]):
    def find(text: str) -> Iterator[tuple[int, int]]:
        for f in finders:
            yield from f(text)
    return find


def _find_dates(text: str) -> Iterator[tuple[int, int]]:
    for hit in find_dates(text):
        yield hit.start, hit.end


def _find_urls(text: str) -> Iterator[tuple[int, int]]:
    for m in re.finditer(r"(?:https?://|www\.)[^\s<>\"')\]|]+", text):
        s, e = m.span()
        while e > s and text[e - 1] in ".,;:!?":
            e -= 1
        yield s, e


def _find_vn_address(text: str) -> Iterator[tuple[int, int]]:
    for m in _VN_ADDRESS.finditer(text):
        if m.group("kw") or m.group("adm"):
            yield m.span()


# -- numbers that are not what the digit sieve takes them for ------------------
#
# Every shape here was a document the 2026-09-24 dry run refused to release:
# ``document.RESIDUE_DIGITS`` saw nine digits nothing had treated and stopped
# the file. The answer is to recognise the number, not to loosen the sieve.

#: The NANP freephone area codes. Reserved for services, never issued to a
#: person, so the number names an organisation and stays readable (HOTLINE).
_TOLL_FREE = r"8(?:00|33|44|55|66|77|88)"

_HOTLINE = _rx_any(
    _rx(rf"(?<![\w.+-])(?:\+?1[ .-]?)?{_TOLL_FREE}[ .-]\d{{3}}[ .-]\d{{4}}(?![\d-])"),
    _rx(rf"(?<![\w.+-])(?:\+?1[ .-]?)?\({_TOLL_FREE}\)[ .-]?\d{{3}}[ .-]?\d{{4}}"
        r"(?!\d)"),
    # Việt Nam: 1900/1800 service numbers, four to six digits after the prefix.
    _rx(r"(?<![\w.+-])1[ .-]?(?:900|800)[ .-]?\d{3,4}(?:[ .-]?\d{1,2})?(?![\d-])"))

#: ``STAMP:USPTO/...-<ip>-<timestamp>-<serial>-<uuid>-CARD-<txid>``: a registry
#: e-seal. It is one value even when the line wraps on one of its hyphens.
_STAMP_RX = re.compile(
    r"(?<![\w])(?:STAMP|E-?SEAL|E-?SIGN|SEAL|DẤU ĐIỆN TỬ|Dấu điện tử)"
    r"[ \t]*[:：][ \t]*"
    r"(?P<v>[^\W_][\w./:]*(?:-[ \t]*(?:\r?\n[ \t]*)?[\w./:]+)*)")

_TXN_RX = re.compile(
    r"(?<![\w])(?:CARD|TXN|TRACE|RRN|Auth(?:orization)?[ \t]code|"
    r"Transaction[ \t](?:ID|No\.?|Number)|[Mm]ã giao dịch|MÃ GIAO DỊCH|"
    r"[Ss]ố giao dịch|SỐ GIAO DỊCH)[ \t]*[:#=-][ \t]*"
    r"(?P<v>[A-Za-z0-9][A-Za-z0-9-]{7,})(?![\w-])")


def _find_machine_traces(text: str) -> Iterator[tuple[int, int]]:
    for rx in (_STAMP_RX, _TXN_RX):
        for m in rx.finditer(text):
            s, e = m.span("v")
            if e - s >= 8 and any(ch.isdigit() for ch in text[s:e]):
                yield s, e


#: A bare run of digits with no separator at all. Long enough that it is not a
#: phone (10-11 with the leading 0) and not a ten-digit tax code.
_BARE_DIGITS = re.compile(r"(?<![\w.,\-/])\d{11,19}(?![\w.,\-/])")
#: Words that put a bank on the page. A bare digit run under one of them is an
#: account number even when the row lost its ``Số tài khoản`` label to the
#: table extraction.
_BANK_CUE = re.compile(
    r"(?<![\w])(?:ngân hàng|ngan hang|nh tmcp|tmcp|[^\W\d_]*bank|stk|"
    r"số tài khoản|so tai khoan|tài khoản|tai khoan|chủ tài khoản|"
    r"chuyển khoản|chuyen khoan|thanh toán|thanh toan|beneficiary|"
    r"account|swift|iban)(?![\w])", re.IGNORECASE)
#: How far back the cue may stand. Two short lines, not a page.
_BANK_WINDOW = 200


def _find_bank_accounts(text: str) -> Iterator[tuple[int, int]]:
    cues = [m.end() for m in _BANK_CUE.finditer(text)]
    if not cues:
        return
    for m in _BARE_DIGITS.finditer(text):
        i = bisect_right(cues, m.start())
        if i and m.start() - cues[i - 1] <= _BANK_WINDOW:
            yield m.span()


#: Dot-grouped digits that are not ONE well-formed amount: two cells of a fee
#: table with the wall between them lost. ``1.234.567.890`` is left alone.
# A comma may stand in front: ``Gói1,1234.567.890`` is a table that lost its
# wall. A US thousands group cannot be mistaken for one, because what follows
# a comma there is three digits and ``_ONE_AMOUNT`` then owns the whole run.
_DOTTED = re.compile(r"(?<![\w.])\d+(?:\.\d{3,})+(?![\d,])")
_ONE_AMOUNT = re.compile(r"\d{1,3}(?:\.\d{3})+")
_GROUP3 = re.compile(r"\.(\d{3})(?!\d)")


def _find_glued_amounts(text: str) -> Iterator[tuple[int, int]]:
    for m in _DOTTED.finditer(text):
        run = m.group()
        if _ONE_AMOUNT.fullmatch(run):
            continue
        # Two intact thousands groups: evidence that these were amounts, not a
        # version string or a dotted identifier.
        if len(_GROUP3.findall(run)) >= 2 \
                and sum(ch.isdigit() for ch in run) >= 10:
            yield m.span()


#: A register number after its cue, prose or form: ``văn bằng bảo hộ số``,
#: ``registration number is``, ``Reg. No.``, and the register's two-column
#: renderings that wrap the label round its value (``International
#: Registration`` / number / ``Number:``). Six to eight digits, or the
#: certificate's ``N,NNN,NNN``.
_REG_NO = r"(?P<v>\d{1,2},\d{3},\d{3}|\d{6,8})(?!\d|[.,]\d)"
_CUE_GAP = r"[ \t]*[:：#]?(?:[ \t]*\r?\n){0,2}[ \t]*[:：]?[ \t]*"
_REG_RX = re.compile(
    r"(?<![\w])(?:văn bằng(?:[ \t]+bảo hộ)?|van bang(?:[ \t]+bao ho)?|"
    r"giấy chứng nhận đăng ký nhãn hiệu|GCN(?:ĐKNH)?|"
    r"registrations?|reg\.?|ownership of U\.?S\.?|(?-i:RN))"
    r"(?:[ \t]+(?:số|so|number|no\.?|nos?\.?|#|is|của|of))*" + _CUE_GAP + _REG_NO,
    re.IGNORECASE)
#: A lawyer's bar number, under a label an e-filing form may wrap over two
#: lines (``*Bar membership or registration\nnumber\n9900001``).
_BAR_WORD = r"(?:membership|registration|number|no\.?)"
_BAR_RX = re.compile(
    rf"(?<![\w])bar[ \t]+{_BAR_WORD}(?:(?:[ \t]+|[ \t]*\r?\n[ \t]*)(?:or[ \t]+)?{_BAR_WORD})*"
    + _CUE_GAP + r"(?P<v>[A-Z]{0,2}\d{4,9})(?![\w])", re.IGNORECASE)
#: An e-invoice prints its own number under a bare ``Số:`` a few lines below
#: its heading (``HÓA ĐƠN GIÁ TRỊ GIA TĂNG``); "Số" alone is too common a word
#: to be trusted anywhere else.
_INVOICE_RX = re.compile(
    r"(?<![\w])h(?:óa|oá|oa)[ \t]+đơn[^\n]*\n(?:[^\n]*\n){0,5}?[ \t]*(?:số|so)"
    + _CUE_GAP + r"(?P<v>\d{1,8})(?![\w/])", re.IGNORECASE)
#: A foreign or international application's number: every office has its own
#: shape, so only the cue says what it is.
_APP_RX = re.compile(
    r"(?<![\w])(?:foreign|international|priority)[ \t]+application"
    r"(?:[ \t]+(?:number|no\.?|serial))?" + _CUE_GAP
    + r"(?P<v>\d{6,12})(?!\d|[.,]\d)", re.IGNORECASE)


def _find_cued(rx: re.Pattern[str]) -> Callable[[str], Iterator[tuple[int, int]]]:
    def find(text: str) -> Iterator[tuple[int, int]]:
        for m in rx.finditer(text):
            yield m.span("v")
    return find


#: An ABA routing number carries a checksum: 3·(d1+d4+d7) + 7·(d2+d5+d8) +
#: (d3+d6+d9) ≡ 0 (mod 10). Nine digits that pass it under a bank's words are
#: one, whatever became of the ``ROUTING #`` label.
_NINE = re.compile(r"(?<![\w.,\-/])\d{9}(?![\w.,\-/])")
_ROUTING_CUE = re.compile(r"(?<![\w])(?:routing|aba|wire|fedwire)(?![\w])",
                          re.IGNORECASE)


def _aba_ok(digits: str) -> bool:
    d = [int(ch) for ch in digits]
    return (3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7])
            + d[2] + d[5] + d[8]) % 10 == 0


def _find_routing(text: str) -> Iterator[tuple[int, int]]:
    cues = sorted(m.end() for rx in (_BANK_CUE, _ROUTING_CUE)
                  for m in rx.finditer(text))
    if not cues:
        return
    for m in _NINE.finditer(text):
        i = bisect_right(cues, m.start())
        if i and m.start() - cues[i - 1] <= _BANK_WINDOW and _aba_ok(m.group()):
            yield m.span()


#: SWIFT MT103 party fields (``50K:``, ``59:``, ``57A:`` ...): the account
#: stands on the field's first line after a slash, or on the line under it,
#: which a printed message heads with the field's name
#: (``59: Beneficiary Customer``).
_SWIFT_ACCOUNT = re.compile(
    r"(?m)^[ \t]*:?(?:50[AFK]?|59[AF]?|5[2-7][A-D])[ \t]*:[ \t]*"
    r"(?:[^\n:/]{0,60}\r?\n[ \t]*)?"
    r"/(?P<v>[A-Z]{0,4}\d[\d ]{4,32}\d)(?![\w])")
#: A payment network's acknowledgement reference (``LocalSwiftAcks-NNNN-NNNNN``).
_SWIFT_ACK = re.compile(r"(?<![\w-])[A-Za-z]*Swift[A-Za-z]*(?:-\d{3,}){2,}(?![\w-])")
#: One digit repeated: OCR filler, no identifier. Treated, so the digit sieve
#: has nothing left to stop the document for.
_FILLER = re.compile(r"(?<![\w.,])(\d)(?:[ .-]?\1){8,}(?![\w.,])")


#: Words that put money on the page. A grouped amount near one is money even
#: when the table cell that named its currency was lost.
_MONEY_CUE = re.compile(
    r"(?<![\w])(?:phí|lệ phí|phi|le phi|số tiền|so tien|thành tiền|thanh tien|"
    r"tổng cộng|tong cong|tổng tiền|đơn giá|don gia|thanh toán|thanh toan|"
    r"fees?|amount|total|subtotal|price|cost|charges?|invoice|"
    r"usd|vnd|vnđ|đồng|dong|eur)(?![\w])", re.IGNORECASE)
_MONEY_WINDOW = 300
_GROUPED = re.compile(
    r"(?<![\w.,])(?:\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?(?![\w,]|\.\d)"
    r"|\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?(?![\w.]|,\d)"
    r"|\d+\.\d+(?![\w.,]))")


def _find_bare_amounts(text: str) -> Iterator[tuple[int, int]]:
    cues = [m.end() for m in _MONEY_CUE.finditer(text)]
    if not cues:
        return
    for m in _GROUPED.finditer(text):
        run = m.group()
        if "," not in run and run.count(".") == 1 and not _ONE_AMOUNT.fullmatch(run) \
                and sum(ch.isdigit() for ch in run) < 5:
            continue                  # 3.14, 10.5: a float too short for money
        i = bisect_right(cues, m.start())
        if i and m.start() - cues[i - 1] <= _MONEY_WINDOW:
            yield m.span()


#: A table with a total row (``Cộng bank |``, ``Tổng |``, ``Total |``) is a
#: fee table: every long number in its cells is money, the rows above the
#: total as much as the total itself.
_TOTAL_ROW = re.compile(
    r"(?im)^[ \t]*\|?[ \t]*(?:cộng|tổng|total|subtotal)(?![\w])[^|\n]{0,24}\|")
_PIPE_BLOCK = re.compile(r"(?m)(?:^[^\n|]*\|[^\n]*(?:\n|\Z))+")
_CELL = re.compile(r"[^|\n]+")
_CELL_NUMBER = re.compile(r"\d[\d.,]*\d")


def _find_fee_table_cells(text: str) -> Iterator[tuple[int, int]]:
    for block in _PIPE_BLOCK.finditer(text):
        if not _TOTAL_ROW.search(block.group()):
            continue
        for cell in _CELL.finditer(text, block.start(), block.end()):
            s, e = _trim(text, *cell.span())
            if _CELL_NUMBER.fullmatch(text, s, e) \
                    and sum(ch.isdigit() for ch in text[s:e]) >= 5:
                yield s, e


#: A mark named in prose: ``Nhãn hiệu “…”``, ``the mark "…"``. The quotes
#: say where it ends; the cue says it is a mark. Bare "mark" is a verb, so it
#: needs a determiner or its capital.
_MARK_CUE = re.compile(
    r"(?<![\w])(?:[Nn]hãn hiệu|NHÃN HIỆU|[Nn]han hieu|NHAN HIEU|"
    r"[Tt]rademarks?|TRADEMARKS?|[Ss]ervice [Mm]arks?|"
    r"(?:[Tt]he|[Tt]his|[Tt]hat|[Oo]ur|[Yy]our|[Tt]heir|[Ii]ts|word|device|"
    r"cited|prior|opposed|applied-for|same) marks?|Marks?)(?![\w])")
_QUOTED = re.compile(
    r"[ \t]*(?:(?:số|là|named|called|is)[ \t]+)?"
    r"[“\"«‘](?P<v>[^”\"»’“«\n]{1,40})[”\"»’]")
_QUOTED_MORE = re.compile(r"[ \t]*(?:,|/|và|and|or|hoặc)")
_QUOTED_MAX_WORDS = 6


def _find_quoted_marks(text: str) -> Iterator[tuple[int, int]]:
    for cue in _MARK_CUE.finditer(text):
        pos = cue.end()
        while (m := _QUOTED.match(text, pos)) is not None:
            s, e = _trim(text, *m.span("v"))
            value = text[s:e]
            if not value or value[0].islower() \
                    or len(value.split()) > _QUOTED_MAX_WORDS:
                break
            yield s, e
            more = _QUOTED_MORE.match(text, m.end())
            if more is None:
                break
            pos = more.end()


# -- heuristic detectors -------------------------------------------------------

_ORG_CUE = re.compile(
    r"(?<![\w])(?:Công ty|Công Ty|CÔNG TY|công ty|Cty\.?|CTY\.?|Cong ty|CONG TY|CTTNHH|CTCP|"
    r"Văn phòng [Ll]uật(?: sư)?|VĂN PHÒNG LUẬT(?: SƯ)?|VPLS|Doanh nghiệp tư nhân|"
    r"DOANH NGHIỆP TƯ NHÂN|DNTN|Tập đoàn|TẬP ĐOÀN|Hợp tác xã|HỢP TÁC XÃ|HTX|"
    r"Ngân hàng|Ngân Hàng|NGÂN HÀNG)"
    r"(?=[ \t])")
_ORG_FORM = frozenset(w.casefold() for w in (
    "tnhh cổ phần cp mtv một thành viên trách nhiệm hữu hạn hợp danh luật tư "
    "vấn đầu thương mại sản xuất dịch vụ xây dựng và co phan trach nhiem huu "
    "han mot thanh vien luat tu van dau thuong mai san xuat dich vu xay dung "
    "va hop danh sư tmcp "
    # "Công ty Luật Sở hữu trí tuệ" is the kind of firm, not its name.
    "sở hữu trí tuệ").split())
# The legal forms, in the casings a name is printed in: ``Example Co., Ltd``,
# ``EXAMPLE COMPANY LIMITED``, ``Example - Law Firm``.
_EN_FORM = (
    r"Co\.,?[ \t]*Ltd\.?|CO\.,?[ \t]*LTD\.?|Company Limited|COMPANY LIMITED|"
    r"Limited|LIMITED|Ltd\.?|LTD\.?|LLC|L\.L\.C\.|Inc\.?|INC\.?|Corp\.?|CORP\.?|"
    r"Corporation|CORPORATION|JSC|J\.S\.C\.|PLLC|LLP|GmbH|GMBH|S\.A\.|B\.V\.|"
    r"Pte\.?[ \t]*Ltd\.?|PTE\.?[ \t]*LTD\.?|Pty\.?[ \t]*Ltd\.?|PTY\.?[ \t]*LTD\.?|PLC|"
    r"Sdn\.?[ \t]*Bhd\.?|SDN\.?[ \t]*BHD\.?|Bhd\.?|BHD\.?|Berhad|BERHAD|"
    r"S\.r\.l\.?|S\.R\.L\.?|Srl|SRL|"
    r"Law Firm|LAW FIRM|Law Offices?|LAW OFFICES?")
_EN_ORG = re.compile(
    r"(?<![\w&])(?:(?:[A-Z][\w&'.-]*|&)"
    r"(?:[ \t]+(?:[A-Z][\w&'.-]*|&|\([A-Z]{1,3}\)|of|and|for)){0,6})"
    rf"(?:,?[ \t]+|[ \t]+[-–—][ \t]+)(?:{_EN_FORM})(?![\w])")
_EN_LEAD = frozenset("the dear to from between and by with for re see at in on of".split())
_NEXT_TOKEN = re.compile(r"[ \t]+([^\s]+)")
# The legal form ended its line and the name is on the next one:
# ``CÔNG TY TNHH THƯƠNG MẠI\nMẪU THỬ`` (a synthetic name).
_NEXT_LINE_TOKEN = re.compile(r"[ \t]*\n[ \t]*([^\s]+)")


_NEXT_LINE = re.compile(r"[ \t]*\n([^\n]*)")
# Words that open the line under a letterhead, not the rest of its name.
_HEADING_LEAD = frozenset("cộng độc biên đề thông quyết báo danh bảng kính trụ địa "
                          "mã số điện tel fax email website".split())
# The trades a Vietnamese company name spells out, written in lower case in
# running text: "Công ty TNHH Thương mại dịch vụ vận tải và Công nghệ <name>".
# They carry the walk on; like a legal form they name no one.
_ORG_TRADE = frozenset(
    "quảng cáo du lịch vận tải xuất nhập khẩu công nghệ truyền thông thời trang "
    "giáo dục thực phẩm kỹ thuật giải pháp phát triển thiết bị bất động sản "
    "tổng hợp".split())


def _caps_line(line: str, most: int) -> bool:
    """A short line of capitals that could be (part of) a company's name: no
    digit, colon, caption, heading or person's name."""
    words = line.split()
    if not 1 <= len(words) <= most or ":" in line \
            or any(ch.islower() or ch.isdigit() for ch in line):
        return False
    first = words[0].casefold()
    if first in names.COMMON or first in _HEADING_LEAD or category_for_label(line) \
            or declares_not_pii(line) or is_heading(line):
        return False
    # The signatory under the seal is a person, not the rest of the firm.
    return not any(a == 0 for a, _ in names.surname_led(line))


def _name_goes_on(text: str, pos: int) -> bool:
    """The line after ``pos`` carries on a company name printed in capitals."""
    m = _NEXT_LINE.match(text, pos)
    return m is not None and _caps_line(m.group(1).strip(), 6)


def _title_goes_on(text: str, pos: int) -> bool:
    """``Công ty TNHH`` ends its line and the name opens the next one."""
    m = _NEXT_LINE.match(text, pos)
    if m is None:
        return False
    words = m.group(1).split()
    return bool(words) and words[0][0].isupper() and ":" not in m.group(1) \
        and words[0].casefold() not in names.COMMON \
        and words[0].casefold() not in _HEADING_LEAD


# ocr-lab marks a seal it could not read whole; the line under the marker is
# what it could: "[STAMPED]\nMAU THU TRADING".
_STAMP_LINE = re.compile(
    r"^[ \t]*(?:\[[A-Z_ ]+\][ \t]*)*\[(?:STAMP|STAMPED|SEAL|SEALED)\][ \t]*"
    r"(?:\[[A-Z_ ]+\][ \t]*)*\n[ \t]*([^\n]*[^\s])", re.MULTILINE)
_STAMP_WORD = re.compile(r"[^\W\d_]+(?:[-'’&][^\W\d_]+)*[.,]?")
# A public body's seal ("TM. ỦY BAN …", "SỞ KẾ HOẠCH VÀ ĐẦU TƯ") names no client.
_PUBLIC_LEAD = frozenset("tm t/m ủy uỷ ubnd sở bộ cục tòa toà viện".split())


def _find_stamp_orgs(text: str) -> Iterator[tuple[int, int]]:
    """The company name a seal reads, cut short: two words or more of
    capitals under a stamp marker, with no legal form left to find it by."""
    for m in _STAMP_LINE.finditer(text):
        line = m.group(1)
        words = line.split()
        if len(words) >= 2 and all(_STAMP_WORD.fullmatch(w) for w in words) \
                and words[0].rstrip(".").casefold() not in _PUBLIC_LEAD \
                and not any(w.casefold() in names.COMMON for w in words) \
                and not _ORG_CUE.match(line) and _caps_line(line, 8):
            yield m.start(1), m.end(1)


def _find_orgs(text: str) -> Iterator[tuple[int, int]]:
    for m in _ORG_CUE.finditer(text):
        end, pos, named, seen, prev = m.end(), m.end(), [], [], ""
        caps = m.group().isupper()
        wrapped, wraps = False, 0
        # Two companies side by side (a signature table read as one line):
        # the line under them may finish either name, so neither takes it.
        line_start = text.rfind("\n", 0, m.start()) + 1
        second = _ORG_CUE.search(text, line_start, m.start()) is not None
        for _ in range(16):
            t = _NEXT_TOKEN.match(text, pos)
            # "CÔNG TY TNHH\nMẪU THỬ", "… VẬN\nTẢI HƯ CẤU": a name in
            # capitals wraps in a letterhead or a bank transfer.
            if t is None and wraps < 2 and (
                    (caps and ((not named and not wrapped)
                               or (not second and _name_goes_on(text, pos))))
                    or (not caps and not named and not wrapped
                        and _title_goes_on(text, pos))):
                t = _NEXT_LINE_TOKEN.match(text, pos)
                if t is not None:
                    wrapped, wraps = True, wraps + 1
            if t is None:
                break
            if wrapped and caps and not t.group(1).isupper():
                break
            if _ORG_CUE.match(text, t.start(1)):
                break                  # the next company starts here
            raw = t.group(1)
            token = raw.rstrip(",.;:)")
            if not token:
                break
            key = token.casefold()
            if key in names.COMMON and prev in ("và", "va", "&"):
                break                  # "… Mẫu Thử và Bên B": the prose goes on
            prev = key
            if key in _ORG_FORM:
                pass
            elif key in _ORG_TRADE:
                seen.append(token)
                if named:
                    end = t.start(1) + len(token)
            elif token[0].isupper() or token[0].isdigit() or token == "&":
                named.append(token)
                seen.append(token)
                end = t.start(1) + len(token)
            else:
                break
            pos = t.end()
            if token != raw:
                break
        # "Công ty Luật Sở hữu trí tuệ Hoa Kỳ": a kind of firm in a country.
        # A company may be named after a district or a region.
        if named and not _COUNTRY.fullmatch(" ".join(seen)):
            yield m.start(), end
    for m in _EN_ORG.finditer(text):
        s, e = m.span()
        words = text[s:e].split()
        # "Name EXAMPLE CO., LTD": a caption with no colon leads the row.
        while len(words) > 1 and (words[0].casefold() in _EN_LEAD
                                  or category_for_label(words[0]) is not None):
            s = text.index(words[1], s + len(words[0]))
            words = words[1:]
        # "CORRESPONDENCE RECEIVED IN LAW OFFICE": a docket event, no firm.
        head = _EN_TAIL.split(text[s:e])[0].split()
        if head and head[-1].casefold() in _EN_LEAD:
            continue
        yield s, e


_COUNTRY = re.compile(rf"{_VN_COUNTRY}|{_US_COUNTRY}|{_VN_CITY}|Hoa Kỳ|HOA KỲ|Mỹ|MỸ",
                      re.IGNORECASE)


def _place(value: str) -> bool:
    folded = " ".join(names.key(w) for w in value.split())
    return folded in names.PLACES or bool(_COUNTRY.fullmatch(value))


_EN_TAIL = re.compile(rf"(?:,?[ \t]+|[ \t]+[-–—][ \t]+)(?:{_EN_FORM})\.?$")
_PAREN_TOKEN = re.compile(r"\([^()\s]*\)")
_CORE_TRIM = " \t,.;:-–—&"


def org_core(value: str) -> str:
    """The name inside an organisation's full form, the part prose repeats
    alone: ``Example`` of ``Example - Law Firm``, ``Mẫu Thử`` of ``Công ty
    TNHH Mẫu Thử`` (synthetic names). ``""`` when there is none."""
    v = " ".join(value.split())
    m = _ORG_CUE.match(v)
    if m is not None:
        words = v[m.end():].split()
        while words and words[0].casefold() in _ORG_FORM:
            words.pop(0)
    else:
        tail = _EN_TAIL.search(v)
        if tail is None:
            return ""
        words = v[:tail.start()].split()
        while len(words) > 1 and words[0].casefold() in _EN_LEAD:
            words.pop(0)
    words = [w for w in words if not _PAREN_TOKEN.fullmatch(w)]
    # "… HƯ CẤU Q": the stamp's next letter, read onto the name.
    while len(words) > 1 and len(words[-1].strip(_CORE_TRIM)) == 1:
        words.pop()
    return " ".join(words).strip(_CORE_TRIM)


def _place_cut(core: str) -> str:
    """The core without the place it ends on: ``hư cấu`` of ``hư cấu hoàn
    kiếm``. Only for joining two writings both seen; a company named after
    a place keeps the place in the core it is sought by."""
    words = core.split()
    for k in range(1, len(words)):
        if _place(" ".join(words[k:])):
            return " ".join(words[:k])
    return core


def org_seeds(text: str, hits: Iterable[Hit]) -> list[str]:
    """The organisations found by a legal form or under a label."""
    return [text[h.start:h.end] for h in hits if h.category == "ORG"
            and (h.tier == "label" or h.detector == "org")]


#: The words a company's name is made of that name no one company alone:
#: ``TRADING`` of a name whose first half the line before holds.
_ORG_GENERIC = frozenset(w.casefold() for w in (
    "trading service services international group holdings industries industry "
    "enterprise enterprises technologies technology products solutions systems "
    "global asia pacific partners associates consulting investment investments "
    "development management media marketing logistics import export commercial "
    "general united national american vietnam viet china capital ventures "
    "brothers sons").split())


def _names_no_one(core: str) -> bool:
    """A core that is a label, a heading, a place, too short to be a name, or
    a single word any company's name may hold: an accented one is a
    Vietnamese syllable (``Quảng``), an everyday word or a name's."""
    words = core.split()
    letters = sum(ch.isalpha() for ch in core)
    if not words or letters < (4 if len(words) == 1 else 3):
        return True
    if len(words) == 1 and (not names.key(core) == core.casefold()
                            or core.casefold() in _ORG_GENERIC
                            or core.casefold() in names.EN_NOT):
        return True
    if category_for_label(core) is not None or declares_not_pii(core) or is_heading(core):
        return True
    folded = " ".join(names.key(w) for w in words)
    return folded in names.NOT_NAMES or _place(core)


def org_forms(orgs: Iterable[str]) -> dict[str, str]:
    """Each organisation's name without its legal form, folded, to its
    longest full form: the one whose token every writing of it wears."""
    full: dict[str, str] = {}
    for org in orgs:
        org = " ".join(org.split())
        core = org_core(org)
        if core and not _names_no_one(core) and len(org) > len(full.get(core.casefold(), "")):
            full[core.casefold()] = org
    # "HƯ CẤU HOÀN KIẾM" on the seal beside "HƯ CẤU": the district, not
    # another firm.
    for k in list(full):
        cut = _place_cut(k)
        if cut != k and cut in full:
            full[k] = full[cut]
    return full


def org_hits(text: str, orgs: Iterable[str]) -> list[Hit]:
    """Every whole-word occurrence of a known organisation's name without its
    legal form, in any casing that starts with a capital, wearing the full
    form's token: ``Example`` after ``Example - Law Firm``. A lower-case use
    is a common word."""
    full = org_forms(orgs)
    if not full:
        return []
    cores = sorted({org_core(v) for v in full.values()}, key=len, reverse=True)
    alts = "|".join(re.escape(c).replace(r"\ ", r"\s+") for c in cores)
    rx = re.compile(rf"(?<![\w&])(?:{alts})(?![\w])", re.IGNORECASE)
    out = []
    for m in rx.finditer(text):
        if not m.group()[0].isupper():
            continue
        org = full[" ".join(m.group().split()).casefold()]
        out.append(Hit(m.start(), m.end(), "ORG", "org-case", "heuristic", 16, canonical=org))
    return out


@dataclass(frozen=True, slots=True)
class Detector:
    name: str
    category: str
    tier: str
    priority: int
    find: Callable[[str], Iterable[tuple[int, int]]]


_MAIL_HEADER = re.compile(
    r"^[ \t>*#-]*(?:From|To|Cc|CC|Bcc|BCC|Reply-To|Sender|Từ|Đến|Người gửi|Người nhận)"
    r"[ \t]*:", re.MULTILINE)
_MAIL_ADDRESS = re.compile(r"[ \t]*[<(][ \t]*[\w.+-]+@[\w-]+(?:\.[\w-]+)+[ \t]*[>)]")
_MAIL_NAME_WORD = re.compile(r"[^\W\d_]\.|[^\W\d_][^\W\d_'’-]*")


def _find_mail_names(text: str) -> Iterator[tuple[int, int]]:
    """``To: J. Mau Placeholder <mau@example.com>``: the name a mail header
    gives its address. Each recipient on the header line, never an
    organisation."""
    for h in _MAIL_HEADER.finditer(text):
        line_end = text.find("\n", h.end())
        line_end = len(text) if line_end < 0 else line_end
        cursor = h.end()
        for a in _MAIL_ADDRESS.finditer(text, h.end(), line_end):
            s, e = cursor, a.start()
            cursor = a.end()
            while s < e and text[s] in " \t,;\"'":
                s += 1
            while e > s and text[e - 1] in " \t\"'":
                e -= 1
            words = list(_MAIL_NAME_WORD.finditer(text, s, e))
            if not 2 <= len(words) <= 5 or words[0].start() != s or words[-1].end() != e:
                continue
            if any(text[w.end():n.start()].strip() for w, n in zip(words, words[1:])):
                continue
            if not all(w.group()[0].isupper() for w in words):
                continue
            if any(o[0] == s for o in _find_orgs(text[s:e])) or _place(text[s:e]):
                continue
            yield s, e


DETECTORS: tuple[Detector, ...] = (
    Detector("mrz", "MRZ", "exact", 100, _rx(
        r"IDVNM[A-Z0-9<]{10,}"
        r"|(?<![A-Z0-9<])(?=[A-Z0-9<]{30,44}(?![A-Z0-9<]))(?:[A-Z0-9]*<){3}[A-Z0-9<]*")),
    Detector("email", "EMAIL", "exact", 90, _rx(
        r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    Detector("national-id-cue", "NATIONAL_ID", "exact", 85, _rx(
        r"(?:CCCD/CMND|CMND/CCCD|CMND|CMT|CCCD|Hộ chiếu|hộ chiếu|HỘ CHIẾU|"
        r"Passport|passport|PASSPORT|Căn cước|căn cước|CĂN CƯỚC)"
        r"(?:[ \t]+(?:công dân|CÔNG DÂN|số|SỐ|No\.?|number))*[ \t]*[:：#]?[ \t]*"
        r"(?P<v>[A-Z]?\d{7,12})(?!\d)")),
    Detector("cccd", "NATIONAL_ID", "exact", 80, _rx(
        # pii-lab's shape (a province code 001-096 leads), plus 3-digit groups.
        r"(?<![\d.,])0(?:0[1-9]|[1-8]\d|9[0-6])(?:\d{9}|(?:[ .]\d{3}){3})(?!\d)")),
    Detector("account-cue", "OTHER_ID", "exact", 75, _rx(
        r"(?:STK|Số TK|số TK|Số tài khoản|số tài khoản|SỐ TÀI KHOẢN|A/C|"
        r"Account No\.?|Account number|IBAN|ABA|[Rr]outing (?:number|no\.?|"
        r"transit number)|ROUTING NUMBER|[Ss]ort code)"
        # ``Số tài khoản: | 1234``: the wall of a table cell, not the value.
        r"[ \t]*[:：]?[ \t]*\|?[ \t]*(?P<v>\d[\d .-]{4,}\d)")),
    Detector("tax-cue", "TAX_CODE", "exact", 72, _rx(
        # ocr-lab's `dkkd` stamp, widened to the MST cues; value only.
        r"(?:MST|Mã số thuế|mã số thuế|MÃ SỐ THUẾ|MSDN|Mã số doanh nghiệp|"
        r"mã số doanh nghiệp|Tax ID|Tax code|S\.?Đ\.?K\.?D|ĐKKD|GCNĐKDN|"
        r"GCNĐKKD|[Ss]ố đăng ký kinh doanh)\.?(?:[ \t]+số)?[ \t]*[:：]?[ \t]*"
        r"(?P<v>\d{8,13}(?:-\d{3})?)(?!\d)")),
    Detector("hotline", "HOTLINE", "exact", 71, _HOTLINE),
    Detector("phone", "PHONE", "exact", 70, _rx_any(
        _rx(r"(?<![\w.+])(?:\(\+84\)|\+84(?:[ ]?\(0\))?|0)[ .-]?(?:\d[ .-]?){8,9}\d"
            r"(?!\d|[.,]\d)"),
        _rx(r"(?<![\w.+])\(0\d{1,3}\)[ .-]?(?:\d[ .-]?){6,7}\d(?!\d|[.,]\d)"),
        # The freephone area codes are HOTLINE's; a KEEP shape must not be
        # taken by a PSEUDONYMISE detector standing on the same span.
        _rx(rf"(?<![\w.+])(?:\+1[ .-]?)?\((?!{_TOLL_FREE}\))\d{{3}}\)"
            r"[ .-]?\d{3}[ .-]\d{4}(?!\d)"),
        _rx(rf"(?<![\w.+(])\+1[ .-]?(?!{_TOLL_FREE}[ .-])\d{{3}}[ .-]\d{{3}}"
            r"[ .-]\d{4}(?!\d)"))),
    Detector("machine-trace", "MACHINE_TRACE", "exact", 66, _find_machine_traces),
    Detector("bank-account", "OTHER_ID", "exact", 68, _find_bank_accounts),
    Detector("routing", "OTHER_ID", "exact", 67, _find_routing),
    Detector("swift-account", "OTHER_ID", "exact", 67, _find_cued(_SWIFT_ACCOUNT)),
    Detector("swift-ack", "MACHINE_TRACE", "exact", 66, _rx(_SWIFT_ACK.pattern)),
    Detector("tax-code", "TAX_CODE", "exact", 60, _rx(
        r"(?<![\d-])\d{10}(?:-\d{3})?(?![\d-])")),
    Detector("money-glued", "MONEY", "exact", 56, _find_glued_amounts),
    Detector("money-bare", "MONEY", "exact", 54, _find_bare_amounts),
    Detector("money-table", "MONEY", "exact", 54, _find_fee_table_cells),
    Detector("money", "MONEY", "exact", 55, _rx_any(
        _rx(rf"(?<![\w.,])(?:{_AMOUNT})[ \t]*(?:{_SCALE}[ \t]*)?{_CURRENCY_AFTER}(?![\w])"),
        _rx(rf"(?<![\w]){_CURRENCY_BEFORE}[ \t]?(?:{_AMOUNT})(?:[ \t]*{_SCALE})?"),
        _find_money_words)),
    Detector("date", "DATE", "exact", 50, _find_dates),
    Detector("matter-ref", "MATTER_REF", "exact", 45, _rx(
        # ocr-lab's `ho_so` shape.
        r"\b(?:NH|BQ|TV)\d{2,4}(?:[-.]\d{1,4})?(?:\.[A-Z]{2})?\b")),
    Detector("url", "URL", "exact", 40, _find_urls),
    Detector("app-serial", "APP_SERIAL", "exact", 35, _rx_any(
        # ocr-lab `don`, USPTO. A comma or a period next to it ends a
        # sentence; only one that carries on a number (`0.81234567`,
        # `81234567,5`) makes it a decimal.
        _rx(r"(?<![\d-])(?<!\d[.,])[789]\d{7}(?![\d-]|[.,]\d)"),
        _rx(r"(?<![\d-])[1-4]-\d{4}-\d{5}(?![\d-])"),       # IP Vietnam
        # The certificate's ``SER. NO. 99-000,001``.
        _rx(r"(?<![\d-])[789]\d-\d{3},\d{3}(?!\d|,\d)"))),
    Detector("reg-number", "REG_NUMBER", "exact", 36, _find_cued(_REG_RX)),
    Detector("app-cue", "APP_SERIAL", "exact", 36, _find_cued(_APP_RX)),
    Detector("bar-number", "OTHER_ID", "exact", 36, _find_cued(_BAR_RX)),
    Detector("invoice-no", "INVOICE_NO", "exact", 36, _find_cued(_INVOICE_RX)),
    Detector("filler", "OTHER_ID", "exact", 34, _rx(_FILLER.pattern)),
    Detector("mark-quoted", "MARK", "exact", 33, _find_quoted_marks),
    Detector("boilerplate", "BOILERPLATE", "exact", 30, _rx(
        r"C[ỘO]NG H[ÒO][AÀ] X[ÃA] H[ỘO]I CH[ỦU] NGH[ĨI]A VI[ỆE]T NAM"
        r"|Đ[ộo]c l[ậa]p\s*[-–]\s*T[ựu] do\s*[-–]\s*H[ạa]nh ph[úu]c",
        re.IGNORECASE)),
    Detector("address", "ADDRESS", "heuristic", 20,
             _rx_any(_find_vn_address, _rx(_US_ADDRESS.pattern),
                     _rx(_US_CITY_LINE.pattern), _rx(_FOREIGN_CITY_LINE.pattern))),
    Detector("org", "ORG", "heuristic", 18, _find_orgs),
    Detector("org-stamp", "ORG", "heuristic", 17, _find_stamp_orgs),
    Detector("person", "PERSON", "heuristic", 15, names.surname_led),
    Detector("person-cue", "PERSON", "heuristic", 15, names.cue_led),
    Detector("person-mail", "PERSON", "heuristic", 15, _find_mail_names),
    Detector("person-middle", "PERSON", "heuristic", 14, names.middle_led),
    Detector("person-west", "PERSON", "heuristic", 13, names.western),
    Detector("person-lexicon", "PERSON", "heuristic", 12, names.lexicon_led),
    Detector("person-pair", "PERSON", "heuristic", 11, names.pair_led),
    Detector("geo", "GEO", "heuristic", 10, _rx(_GEO.pattern)),
)


def pattern_hits(text: str) -> list[Hit]:
    """Every raw detector hit. Overlapping; :func:`resolve` sorts them out."""
    hits: list[Hit] = []
    for d in DETECTORS:
        for s, e in d.find(text):
            s, e = _trim(text, s, e)
            if d.category == "PERSON":
                e = _past_initial(text, s, e)
            if e > s:
                hits.append(Hit(s, e, d.category, d.name, d.tier, d.priority))
    return hits


# -- labelled fields -----------------------------------------------------------

_COLON = re.compile(r"[:：]")
# Ends a value on its line: tab, pipe, semicolon, an HTML tag.
_HARD = re.compile(r"\t|\||;|<\/?[A-Za-z][^>]*>")
# ``Số tài khoản: |  1234``. The wall right after the colon is the edge of the
# label's own cell, so the value stands in the next one and the line has not
# ended. One empty cell may sit between them; a third wall is a different row.
_CELL_BREAK = re.compile(r"(?:[ \t]*[|\t]){1,2}[ \t]*")
_WORDS = re.compile(r"\S+")
# ``Mẫu ThửFirst Name:`` (a synthetic name): OCR glued a label to the value before it. A capital
# after a small letter inside one word is where the label starts, and so is
# one after a token's closing bracket (``[PERSON-…]Last Name:``).
_GLUE = re.compile(rf"(?<=[{_L}\]])(?=[{_U}][{_L}])")
# A dot after a middle initial or a title is inside the name, when a
# capitalised word or two then close it: "Mauricio Q. Placeholder".
_NAME_CLOSE = rf"[{_U}][\w'-]*(?:[ \t]+[{_U}][\w'-]*){{0,2}}(?=[ \t]*(?:[,;(]|\.?[ \t]*$))"
_INNER_DOT = (rf"(?:(?<=[\s(][{_U}])|(?<=\bMr)|(?<=\bMrs)|(?<=\bMs)|(?<=\bDr))\.[ \t]"
              rf"(?={_NAME_CLOSE})")
_PAST_INITIAL = re.compile(rf"(?m)\.[ \t]+{_NAME_CLOSE}")
_TERMINATORS: dict[str, re.Pattern[str]] = {
    "PERSON": re.compile(
        rf"(?m),|\(|\s[-–—]\s|(?!{_INNER_DOT})\.\s|\s+(?=(?:sinh|sn|năm sinh|quốc tịch|chức vụ|"
        r"giới tính|là|và|cùng|theo|với|tại|đã|sẽ|trú|nơi|ngày|cmnd|cccd|số|"
        r"mã|địa chỉ|điện thoại|email|dob|born|nationality|citizenship|gender|"
        r"position|occupation|passport|address|phone|mobile|tel|fax)\b)", re.IGNORECASE),
    "ORG": re.compile(r",\s"),
}
_COMPACT = re.compile(rf",\s|\s\(|\s[-–—]\s|\s+(?=[{_L}]{{2,}}\b)")
_COMPACT_CATEGORIES = frozenset((
    "EMAIL", "PHONE", "NATIONAL_ID", "TAX_CODE", "OTHER_ID", "MATTER_REF",
    "INVOICE_NO", "APP_SERIAL", "REG_NUMBER", "NICE_CLASS", "URL", "DATE",
    "BIRTH_DATE"))
_DATE_KINDS = frozenset(("DATE", "BIRTH_DATE"))
_MD_ROW = re.compile(r"^[ \t]*\|.*\|[ \t]*$", re.MULTILINE)
_MD_RULE = re.compile(r"^\s*:?-{3,}:?\s*$")
_TABLE = re.compile(r"<table\b[^>]*>(.*?)</table>", re.IGNORECASE | re.DOTALL)
_TR = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_TD = re.compile(r"<(t[dh])\b[^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"<[^>]*>")


def _past_initial(text: str, s: int, e: int) -> int:
    """A name the name layers cut at its middle initial's dot ("John T" of
    "John T. Placeholder") runs on to the words that close it."""
    if e - s >= 3 and text[e - 1].isupper() and text[e - 2] == " ":
        m = _PAST_INITIAL.match(text, e)
        if m:
            return m.end()
    return e


def _trim(text: str, s: int, e: int) -> tuple[int, int]:
    while s < e and text[s] in _TRIM:
        s += 1
    while e > s and text[e - 1] in _TRIM:
        e -= 1
    # Keep a bracket the value itself needs: "(028) 3900 0001" must not be
    # left as "(" + token.
    span = text[s:e]
    if span.count(")") > span.count("(") and s > 0 and text[s - 1] == "(":
        s -= 1
    elif span.count("(") > span.count(")") and e < len(text) and text[e] == ")":
        e += 1
    return s, e


def _upper_start(word: str) -> bool:
    core = word.lstrip("*_#>-•·([")
    return bool(core) and core[0].isupper()


def _valid_colon(line: str, i: int) -> bool:
    before = line[i - 1] if i > 0 else ""
    after = line[i + 1] if i + 1 < len(line) else ""
    if before.isdigit() and after.isdigit():
        return False                       # 10:30, 1:2
    if after == "/" and before.isalpha():
        return False                       # http://
    return True


@dataclass(slots=True)
class _Boundary:
    label_start: int
    colon: int
    category: str | None
    not_pii: bool
    label: str
    #: The label ends the value of one before it on its line.
    after_value: bool = False


#: The words that make ``Name`` a part of a person's name: ``Last Name:``
#: after a value on its line is one caption, not ``Last`` and ``Name:``.
_NAME_PART = frozenset("first last middle given family full maiden legal".split())


def _words(line: str, a: int, b: int) -> list[tuple[int, str, bool]]:
    """(start, word, glued) for the words of ``line[a:b]``, a word split
    where :data:`_GLUE` finds a label glued to it."""
    out = []
    for m in _WORDS.finditer(line, a, b):
        cuts = [m.start(), *(g.start() for g in _GLUE.finditer(line, m.start(), m.end())
                             if g.start() > m.start()), m.end()]
        for i, (x, y) in enumerate(zip(cuts, cuts[1:])):
            out.append((x, line[x:y], i > 0))
    return out


def _boundaries(text: str, ls: int, le: int) -> list[_Boundary]:
    """Every ``Label:`` on one line, in order. Offsets are absolute."""
    line = text[ls:le]
    hard_ends = [m.end() for m in _HARD.finditer(line)]
    found: list[_Boundary] = []
    for cm in _COLON.finditer(line):
        c = cm.start()
        if not _valid_colon(line, c):
            continue
        seg = max([h for h in hard_ends if h <= c], default=0)
        prev = found[-1].colon - ls + 1 if found else 0
        window_start = max(seg, prev)
        open_value = bool(found) and prev > seg
        comma = line.rfind(",", window_start, c)
        if comma >= 0:
            window_start = comma + 1
        words = _words(line, window_start, c)[-6:]
        if not words:
            continue
        chosen: tuple[int, str | None, bool] | None = None
        ks = range(1, len(words) + 1)
        # A label glued to the value before it starts where the glue is.
        order = [k for k in ks if words[-k][2]]
        order += ks if open_value else reversed(ks)
        for k in order:
            start = words[-k][0]
            raw = line[start:c]
            if len(raw) > 60:
                continue
            if open_value and not _upper_start(words[-k][1]):
                continue
            # "Họ (Last name):" is a caption; "... of Party B (Applicant):" is prose.
            lead = line[window_start:start]
            if raw[:1] in "([" and category_for_label(lead) is None \
                    and any(w.lstrip("*_#>-•·([")[:1].islower() for w in lead.split()):
                continue
            if declares_nothing(raw):
                chosen = (start, None, False)
                break
            cat = category_for_label(raw)
            if cat is not None:
                if open_value:
                    while k < len(words) and _upper_start(words[-k - 1][1]) \
                            and words[-k - 1][1].casefold() in _NAME_PART \
                            and category_for_label(line[words[-k - 1][0]:c]) is not None:
                        k += 1
                    start = words[-k][0]
                chosen = (start, cat, False)
                break
            if declares_not_pii(raw):
                chosen = (start, None, True)
                break
        if chosen is None:
            # An unrecognised label still ends the value before it.
            for k in range(1, min(4, len(words)) + 1):
                if _upper_start(words[-k][1]):
                    chosen = (words[-k][0], None, False)
                    break
        if chosen is None:
            continue
        start, cat, not_pii = chosen
        found.append(_Boundary(ls + start, ls + c, cat, not_pii,
                               line[start:c].strip(), open_value))
    return found


def _value_end(text: str, category: str | None, s: int, e: int) -> int:
    rule = _TERMINATORS.get(category or "")
    if rule is None and category in _COMPACT_CATEGORIES:
        rule = _COMPACT
    if rule is not None:
        m = rule.search(text, s, e)
        if m is not None and m.start() > s:
            e = m.start()
    return e


# A price, or the MONEY token the second look finds in its place.
_PRICE = re.compile(rf"(?:{_CURRENCY_BEFORE})[ \t]?\d|(?:{_AMOUNT})[ \t]?{_CURRENCY_AFTER}(?!\w)"
                    r"|\[?MONEY-[0-9a-f]+\]|\[?SỐ TIỀN\]")


def _org_value(text: str, category: str | None, s: int, e: int) -> tuple[str | None, int]:
    """(category, end) for a person's or company's label whose value opens
    with a company: ``Applicant: Example Co., Ltd`` is an ORG, the whole of
    it, though a PERSON value would end at the comma. ``(category, -1)`` for
    any other value."""
    if category not in ("PERSON", "ORG"):
        return category, -1
    s, e = _trim(text, s, e)
    for a, b in _find_orgs(text[s:e]):
        if a == 0:
            return "ORG", s + b
    return category, -1


def _line_fields(text: str, captions: list[tuple[int, int]] | None = None) -> Iterator[Hit]:
    """The labelled values of every line. ``captions`` collects the declared
    labels that end the value before them on their line: ``Country`` in
    ``Full name: <name> Country: <country>`` is a caption, not the name's
    last word."""
    lines, pos = [], 0
    for raw in text.split("\n"):
        lines.append((pos, pos + len(raw)))
        pos += len(raw) + 1
    for idx, (ls, le) in enumerate(lines):
        found = _boundaries(text, ls, le)
        led = _colon_led(text, lines, idx)
        if led is not None:
            end = found[0].label_start if found else le
            cat, org_end = _org_value(text, led[2], led[3], end)
            s, e = _trim(text, led[3], org_end if org_end > 0 else _value_end(
                text, cat, led[3], end))
            if e > s:
                yield Hit(s, e, cat, "label", "label", 0,
                          text[led[0]:led[1]], led[0], led[1])
        if not found:
            bare = _bare_label(text, ls, le)
            if bare is not None:
                s, e = _next_line_value(text, lines, idx, bare[2])
                if e > s:
                    yield Hit(s, e, bare[2], "label", "label", 0,
                              text[bare[0]:bare[1]], bare[0], bare[1])
            continue
        for n, b in enumerate(found):
            if b.category is None and not b.not_pii:
                continue
            if captions is not None and b.after_value:
                captions.append((b.label_start, b.colon))
            vs = b.colon + 1
            ve = found[n + 1].label_start if n + 1 < len(found) else le
            cell = _CELL_BREAK.match(text, vs, ve)
            if cell is not None and cell.end() < ve:
                vs = cell.end()
            hard = _HARD.search(text, vs, ve)
            if hard is not None:
                ve = hard.start()
            cat, org_end = _org_value(text, b.category, vs, ve)
            s, e = _trim(text, vs, org_end if org_end > 0 else _value_end(text, cat, vs, ve))
            if cat == "MARK" and _PRICE.match(text, s, e):
                continue          # "Tra cứu nhãn hiệu chữ: $500 …" prices a search
            if e <= s and not text[vs:le].strip(" \t*_"):
                s, e = _next_line_value(text, lines, idx, cat)
            if e <= s or (cat in _DATE_KINDS and not _datelike(text[s:e])):
                continue
            yield Hit(s, e, cat,
                      "label:not-pii" if b.not_pii else "label", "label", 0,
                      b.label, b.label_start, b.colon)


_LEAD_COLON = re.compile(r"[ \t]*[:：][ \t]*")
_ABOVE_MAX_WORDS = 6


def _colon_led(text: str, lines: list[tuple[int, int]],
               idx: int) -> tuple[int, int, str, int] | None:
    """``: value`` under a line that is wholly a label, as a two-column
    rendering sets them: (label start, label end, category, value start)."""
    ls, le = lines[idx]
    m = _LEAD_COLON.match(text, ls, le)
    if m is None or idx == 0:
        return None
    s, e = _trim(text, *lines[idx - 1])
    raw = text[s:e]
    if not raw or len(raw.split()) > _ABOVE_MAX_WORDS or _COLON.search(raw):
        return None
    cat = category_for_label(raw)
    return None if cat is None else (s, e, cat, m.end())


def _next_line_value(text: str, lines: list[tuple[int, int]], idx: int,
                     category: str | None) -> tuple[int, int]:
    """``Địa chỉ:`` alone on its line: the value is the next non-empty line,
    unless that line is the next label or heading, or no value of the kind."""
    for ls, le in lines[idx + 1:idx + 4]:
        if not text[ls:le].strip():
            continue
        if _MD_ROW.fullmatch(text, ls, le) or _boundaries(text, ls, le) \
                or _bare_label(text, ls, le, any_kind=True) is not None:
            return 0, 0
        s, e = _trim(text, ls, le)
        s, e = _trim(text, s, _value_end(text, category, s, e))
        return (s, e) if _plausible(text[s:e], category) else (0, 0)
    return 0, 0


#: The categories whose value is a number of some kind: a line with no digit
#: in it is not one.
_DIGIT_KINDS = frozenset((
    "PHONE", "TAX_CODE", "NATIONAL_ID", "APP_SERIAL", "REG_NUMBER", "OTHER_ID",
    "INVOICE_NO"))
_MONTH = re.compile(
    r"(?<![\w])(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?(?![\w])"
    r"|(?<![\w])tháng(?![\w])", re.IGNORECASE)
_YEAR = re.compile(r"(?:19|20)\d\d")
_NUM_WORD_RX = re.compile(rf"(?<![\w]){_NUM_WORD}(?![\w])", re.IGNORECASE)


def _datelike(value: str) -> bool:
    return any(ch.isdigit() for ch in value) or bool(_MONTH.search(value))


def _plausible(value: str, category: str | None) -> bool:
    """Could ``value``, found on the line under its label, be one? The label
    stood alone, so nothing on its own line says where its value is."""
    if not value or category_for_label(value) is not None \
            or declares_not_pii(value) or is_heading(value):
        return False
    digit = any(ch.isdigit() for ch in value)
    if category in _DATE_KINDS:
        return _datelike(value)
    if category in _DIGIT_KINDS:
        return digit
    if category == "EMAIL":
        return "@" in value
    if category == "MONEY":
        return (digit or bool(_NUM_WORD_RX.search(value))) \
            and not _YEAR.fullmatch(value)
    if category == "PERSON":
        return _upper_start(value)
    return True


#: What a form label standing alone on its line, with no colon, may declare
#: (``Zip/postal code`` over ``00000``, as the e-filing renderings print it).
#: Dates, classes, marks and money have shapes of their own; a single-word
#: PERSON label (``Tên``, ``Ông``) is too common a word to trust bare.
_BARE_CATEGORIES = frozenset((
    "ADDRESS", "EMAIL", "PHONE", "TAX_CODE", "NATIONAL_ID", "APP_SERIAL",
    "REG_NUMBER", "MATTER_REF", "INVOICE_NO", "OTHER_ID", "PERSON"))
_BARE_MAX_WORDS = 4
_BARE_MAX_CHARS = 40


def _bare_label(text: str, ls: int, le: int,
                any_kind: bool = False) -> tuple[int, int, str] | None:
    """A whole line that is a form label with no colon: (start, end, category).

    ``any_kind`` answers for any category, for the question "is this line a
    label, so not the value of the one above it"."""
    s, e = _trim(text, ls, le)
    raw = text[s:e]
    words = raw.split()
    if not raw or len(words) > _BARE_MAX_WORDS or len(raw) > _BARE_MAX_CHARS \
            or _COLON.search(raw) or raw[-1] in ".!?":
        return None
    cat = category_for_label(raw)
    if cat is None:
        return (s, e, "") if any_kind and declares_not_pii(raw) else None
    if any_kind:
        return s, e, cat
    if cat not in _BARE_CATEGORIES or (cat == "PERSON" and len(words) < 2):
        return None
    return s, e, cat


@dataclass(frozen=True, slots=True)
class _Cell:
    start: int
    end: int
    text: str


def _pair_or_header(rows: list[list[_Cell]]) -> Iterator[tuple[_Cell, _Cell]]:
    """(label cell, value cell) pairs for one table.

    Two columns whose first row is not all labels: key/value rows. An even
    number of columns whose first cells mostly declare categories: repeated
    key/value pairs across the row. Anything else: the first row is a header.
    """
    rows = [r for r in rows if r]
    if len(rows) == 0:
        return
    ncols = max(len(r) for r in rows)
    header = rows[0]
    header_declares = [category_for_label(c.text) is not None for c in header]
    row_labels = sum(1 for r in rows if category_for_label(r[0].text) is not None)
    if (ncols == 2 and not all(header_declares)) or (
            ncols % 2 == 0 and ncols > 2 and row_labels * 2 >= len(rows)):
        for r in rows:
            for i in range(0, len(r) - 1, 2):
                yield r[i], r[i + 1]
        return
    for r in rows[1:]:
        for i, cell in enumerate(r):
            if i < len(header):
                yield header[i], cell


def _table_hits(pairs: Iterable[tuple[_Cell, _Cell]], detector: str) -> Iterator[Hit]:
    for label, value in pairs:
        if value.end <= value.start:
            continue
        cat = category_for_label(label.text)
        not_pii = cat is None and declares_not_pii(label.text)
        if cat is None and not not_pii:
            continue
        cat = _org_value(value.text, cat, 0, len(value.text))[0]
        yield Hit(value.start, value.end, cat,
                  f"{detector}:not-pii" if not_pii else detector, "label", 0,
                  label.text.strip(), label.start, label.end)


def _markdown_tables(text: str) -> Iterator[Hit]:
    block: list[list[_Cell]] = []
    last_end = -2
    for m in _MD_ROW.finditer(text):
        if m.start() != last_end + 1 and block:
            yield from _table_hits(_pair_or_header(block), "table")
            block = []
        last_end = m.end()
        line = m.group()
        pipes = [i for i, ch in enumerate(line) if ch == "|"]
        cells: list[_Cell] = []
        for a, b in zip(pipes, pipes[1:]):
            s, e = _trim(text, m.start() + a + 1, m.start() + b)
            cells.append(_Cell(s, e, text[s:e]))
        if cells and all(_MD_RULE.fullmatch(c.text) or not c.text for c in cells):
            continue
        block.append(cells)
    if block:
        yield from _table_hits(_pair_or_header(block), "table")


def _html_tables(text: str) -> Iterator[Hit]:
    for t in _TABLE.finditer(text):
        rows: list[list[_Cell]] = []
        for tr in _TR.finditer(text, t.start(1), t.end(1)):
            cells = []
            for td in _TD.finditer(text, tr.start(1), tr.end(1)):
                s, e = td.span(2)
                while s < e and text[s].isspace():
                    s += 1
                while e > s and text[e - 1].isspace():
                    e -= 1
                inner = _TAGS.sub(" ", text[s:e])
                cells.append(_Cell(s, e if inner.strip() else s, inner))
            rows.append(cells)
        yield from _table_hits(_pair_or_header(rows), "table")


def labelled_fields(text: str,
                    captions: list[tuple[int, int]] | None = None) -> list[Hit]:
    """Every value whose label declares its category (or declares a mark).
    ``captions`` collects the labels that end a value on their line."""
    table = list(_html_tables(text)) + list(_markdown_tables(text))
    spans = _Spans()
    out: list[Hit] = []
    for h in sorted(table, key=lambda h: h.start):
        if not spans.overlaps(h.start, h.end):
            spans.add(h.start, h.end)
            out.append(h)
    for h in _line_fields(text, captions):
        if not spans.overlaps(h.start, h.end):
            spans.add(h.start, h.end)
            out.append(h)
    # "Chủ đơn:\nĐơn đã nộp": a sentence under a person's label is no name.
    # The text stays open to every other detector.
    out = [_without_honorific(text, h) for h in out if h.category != "PERSON"
           or not names.common_led(text[h.start:h.end])]
    return sorted(out, key=lambda h: h.start)


def _without_honorific(text: str, h: Hit) -> Hit:
    """``Bà Trần Thị Mẫu`` (a synthetic name) under a label: the name without the ``Bà``, so it
    wears the token the name wears everywhere else."""
    if h.category != "PERSON":
        return h
    m = names.HONORIFIC.match(text, h.start, h.end)
    if m is None or not text[m.end():h.end].strip():
        return h
    return replace(h, start=m.end())


# -- resolution ----------------------------------------------------------------

class _Spans:
    """Sorted, non-overlapping half-open intervals."""

    def __init__(self) -> None:
        self.starts: list[int] = []
        self.ends: list[int] = []

    def overlaps(self, s: int, e: int) -> bool:
        i = bisect_right(self.starts, s) - 1
        if i >= 0 and self.ends[i] > s:
            return True
        j = i + 1
        return j < len(self.starts) and self.starts[j] < e

    def add(self, s: int, e: int) -> None:
        i = bisect_left(self.starts, s)
        self.starts.insert(i, s)
        self.ends.insert(i, e)

    def gaps(self, s: int, e: int) -> list[tuple[int, int]]:
        out, cursor = [], s
        i = max(bisect_right(self.starts, s) - 1, 0)
        while i < len(self.starts) and self.starts[i] < e:
            if self.ends[i] > cursor:
                if self.starts[i] > cursor:
                    out.append((cursor, self.starts[i]))
                cursor = max(cursor, self.ends[i])
            i += 1
        if cursor < e:
            out.append((cursor, e))
        return out


def _order(h: Hit) -> tuple[int, int, int]:
    return (h.start, -h.length, -h.priority)


#: The words of a legal form. What is left of a value once the name in it is
#: taken, if it holds only these, names no one: ``Công ty TNHH [ORG-…]``.
_LEGAL_FORM = frozenset(fold(w).casefold() for w in (
    "công ty tnhh cổ phần cp mtv một thành viên trách nhiệm hữu hạn hợp danh "
    "co company limited ltd llc l.l.c inc corp corporation jsc j.s.c pllc llp "
    "gmbh s.a b.v the and & of liability law firm office offices sdn bhd "
    "berhad s.r.l srl").split())
_FORM_WORD = re.compile(r"[^\s,;()]+")


def _form_only(value: str) -> bool:
    words = [fold(w.strip(".") or w).casefold() for w in _FORM_WORD.findall(value)]
    return bool(words) and all(w in _LEGAL_FORM for w in words)


def _fragments(text: str, h: Hit, blocked: _Spans) -> Iterator[Hit]:
    gaps = list(blocked.gaps(h.start, h.end))
    # The number a digit kind's label declared was taken on its own; the
    # words left beside it ("… 0100. If you have questions") are no number.
    split = h.category in _DIGIT_KINDS and gaps != [(h.start, h.end)]
    for a, b in gaps:
        a, b = _trim(text, a, b)
        if b > a and any(ch.isalnum() for ch in text[a:b]) \
                and not _form_only(text[a:b]) \
                and not (split and not any(ch.isdigit() for ch in text[a:b])):
            yield replace(h, start=a, end=b)


def resolve(text: str, labelled: list[Hit], patterns: list[Hit],
            keeps: Callable[[str | None], bool] = _keeps,
            pinned: Iterable[Hit] = (),
            captions: Iterable[tuple[int, int]] = ()) -> list[Hit]:
    """Non-overlapping hits, sensitive and kept, sorted by position.

    ``pinned`` hits (the public roster) are kept and outrank everything: a
    roster name inside a labelled value or under a phone-shaped pattern is
    still the public name.

    ``captions`` are labels that ended the value before them: no guess may
    take one, or a name run on into ``Country:`` leaves ``Country`` behind
    as a person.

    A token already in the text (``Người nhận: [PERSON-…]``, written there by
    a caller or an earlier pass) is no value: nothing may treat it again, or
    it comes back wrapped in a second token.
    """
    taken = _Spans()            # spans that will be treated
    blocked = _Spans()          # taken + pinned + shielded-by-KEEP + tokens
    chosen: list[Hit] = []

    for m in TOKEN.finditer(text):
        blocked.add(*m.span())

    for h in sorted(pinned, key=_order):
        if not blocked.overlaps(h.start, h.end):
            blocked.add(h.start, h.end)
            chosen.append(h)

    exact = sorted((h for h in patterns if h.tier == "exact"), key=_order)
    for h in exact:
        if not keeps(h.category) and not blocked.overlaps(h.start, h.end):
            taken.add(h.start, h.end)
            blocked.add(h.start, h.end)
            chosen.append(h)

    for h in labelled:
        if keeps(h.category):
            continue
        for frag in _fragments(text, h, blocked):
            taken.add(frag.start, frag.end)
            blocked.add(frag.start, frag.end)
            chosen.append(frag)

    for cs, ce in captions:
        for a, b in blocked.gaps(cs, ce):
            blocked.add(a, b)

    shields = [h for h in labelled if keeps(h.category)]
    shields += [h for h in exact if keeps(h.category)]
    for h in sorted(shields, key=_order):
        pieces = blocked.gaps(h.start, h.end)
        for a, b in pieces:
            blocked.add(a, b)
        if h.category is not None and not taken.overlaps(h.start, h.end) \
                and pieces == [(h.start, h.end)]:
            chosen.append(h)       # reported as deliberately kept

    for h in sorted((p for p in patterns if p.tier == "heuristic"), key=_order):
        if keeps(h.category):
            continue
        for frag in _fragments(text, h, blocked):
            taken.add(frag.start, frag.end)
            blocked.add(frag.start, frag.end)
            chosen.append(frag)

    return _birth_dates(text, sorted(chosen, key=lambda h: h.start), labelled)


#: What stands right before a date of birth in running text, folded:
#: ``sinh ngày``, ``Ngày sinh:``, ``born on``, ``DOB``. ``phát sinh``
#: (to arise) is no birth.
_BIRTH_CUE = re.compile(
    r"(?:(?<!phat )(?<!\w)sinh(?: ngay| nam)?|ngay,? (?:thang,? )?(?:nam )?sinh"
    r"|nam sinh|date of birth|birth ?date|(?<!\w)dob|(?<!\w)d\.o\.b\.?"
    r"|(?<!\w)born(?: on)?)[\s:：/.-]*$", re.IGNORECASE)
_BIRTH_WINDOW = 24


def _birth_dates(text: str, hits: list[Hit], labelled: list[Hit]) -> list[Hit]:
    """A date under a birth label, or right after a birth cue, is a
    BIRTH_DATE. The exact detector found the date; the label or the cue says
    whose it is. Every other date is a procedural DATE."""
    births = [(h.start, h.end) for h in labelled if h.category == "BIRTH_DATE"]
    out = []
    for h in hits:
        if h.category == "DATE" and (
                any(a < h.end and h.start < b for a, b in births)
                or _BIRTH_CUE.search(
                    fold(text[max(0, h.start - _BIRTH_WINDOW):h.start]))):
            h = replace(h, category="BIRTH_DATE")
        out.append(h)
    return out


def roster_hits(text: str, roster: Roster | None) -> list[Hit]:
    if roster is None:
        return []
    return [Hit(s, e, party.category, "roster", "exact", 110)
            for s, e, party in roster.find(text)]


def case_var_hits(text: str, case_vars: Iterable[CaseVar]) -> list[Hit]:
    """The matter's own facts, in whatever shape the text wrote them.

    ``canonical`` is the value the caller gave, so the joined, unaccented and
    mistyped mentions all wear the token of the one the caller knows.
    """
    return [Hit(s, e, var.category, "case-var", "exact", CASE_VAR_PRIORITY,
                canonical=var.value)
            for s, e, var in find_vars(text, case_vars)]


def extract(text: str, keeps: Callable[[str | None], bool] = _keeps,
            roster: Roster | None = None, names_seen: Iterable[str] = (),
            marks_seen: Iterable[str] = (), refs_seen: Iterable[str] = (),
            case_vars: Iterable[CaseVar] = (), orgs_seen: Iterable[str] = (),
            names_guessed: Iterable[str] = ()) -> list[Hit]:
    """Labels, tables and patterns over a whole document, resolved.

    ``names_seen`` are person names the case has already shown with
    confidence (the other documents'). They and the confident names of this
    document are looked for again in every shape; ``names_guessed`` (the
    vault's) only in a name's (:class:`names.CaseNames`).
    ``marks_seen`` and this document's labelled marks are looked for again
    as written, in capitals and in title case (:func:`mark_hits`);
    ``refs_seen`` and this document's labelled matter codes in any case
    (:func:`ref_hits`); ``orgs_seen`` and this document's organisations by
    their name without the legal form (:func:`org_hits`). ``case_vars`` are
    the matter's own facts, matched in folded form (:mod:`casevars`)."""
    captions: list[tuple[int, int]] = []
    labelled = labelled_fields(text, captions)
    patterns = pattern_hits(text) + case_var_hits(text, case_vars)
    pinned = roster_hits(text, roster)
    hits = resolve(text, labelled, patterns, keeps, pinned, captions)
    again = mark_hits(text, [*marks_seen, *mark_seeds(text, hits)])
    again += ref_hits(text, [*refs_seen, *ref_seeds(text, hits)])
    orgs = [*orgs_seen, *org_seeds(text, hits)]
    again += org_hits(text, orgs)
    case = None
    if "propagation" in names.LAYERS:
        case = names.CaseNames([*names_seen, *person_seeds(text, hits)], names_guessed)
        again += [Hit(s, _past_initial(text, s, e), "PERSON", "person-case", "heuristic",
                      16, canonical=c) for s, e, c in case.find(text)] if case else []
    if not again:
        return hits
    hits = resolve(text, labelled, patterns + again, keeps, pinned, captions)
    forms = org_forms(orgs)
    out = []
    for h in hits:
        if h.category == "PERSON" and not h.canonical and case:
            canon = case.canonical(text[h.start:h.end])
            if canon:
                h = replace(h, canonical=canon)
        elif h.category == "ORG" and not h.canonical and forms:
            # "EXAMPLE LAW FIRM" and "Example - Law Firm": one firm, one token.
            canon = forms.get(org_core(text[h.start:h.end]).casefold())
            if canon:
                h = replace(h, canonical=canon)
        out.append(h)
    return out


_SEED_DETECTORS = frozenset(("person-cue", "person-mail", "person-middle", "person-west"))


def person_seeds(text: str, hits: Iterable[Hit]) -> list[str]:
    """The PERSON values found with confidence: under a label, after a cue,
    with a Văn/Thị middle name, or three syllables led by a surname. These are
    worth looking for again; a two-word guess is not."""
    out = []
    for h in hits:
        if h.category != "PERSON":
            continue
        value = text[h.start:h.end]
        n = len(value.split())
        if n < 2:
            continue
        if h.tier == "label" or h.detector in _SEED_DETECTORS \
                or (h.detector == "person" and n >= 3):
            out.append(value)
    return out


def mark_seeds(text: str, hits: Iterable[Hit]) -> list[str]:
    """The mark names a label declared. Prose repeats them without one."""
    return [text[h.start:h.end] for h in hits
            if h.category == "MARK"
            and (h.tier == "label" or h.detector == "mark-quoted")]


def mark_hits(text: str, marks: Iterable[str]) -> list[Hit]:
    """Every whole-word occurrence of a known mark, as written, in capitals or
    in title case. Case-sensitive otherwise: a mark that is also a common word
    must not take every lower-case use of it."""
    forms: set[str] = set()
    for mark in marks:
        mark = " ".join(mark.split())
        # A label or heading taken for a mark (an older vault may hold one)
        # would take that word from every document.
        if category_for_label(mark) is not None or declares_not_pii(mark) \
                or is_heading(mark):
            continue
        if sum(ch.isalnum() for ch in mark) >= 2:
            forms |= {mark, mark.upper(), mark.title()}
    if not forms:
        return []
    alts = "|".join(re.escape(f).replace(r"\ ", r"\s+")
                    for f in sorted(forms, key=len, reverse=True))
    rx = re.compile(rf"(?<!\w)(?:{alts})(?!\w)")
    return [Hit(m.start(), m.end(), "MARK", "mark-case", "heuristic", 17)
            for m in rx.finditer(text)]


def ref_seeds(text: str, hits: Iterable[Hit]) -> list[str]:
    """The matter codes a label declared. Prose repeats them without one, and
    a code in a shape of its own no pattern knows."""
    return [text[h.start:h.end] for h in hits
            if h.category == "MATTER_REF" and h.tier == "label"]


def ref_hits(text: str, refs: Iterable[str]) -> list[Hit]:
    """Every whole-word occurrence of a known matter code, in any case: a code
    is no common word, and its token is over the case-folded value anyway."""
    forms = {" ".join(r.split()) for r in refs}
    forms = {f for f in forms if sum(ch.isalnum() for ch in f) >= 3}
    if not forms:
        return []
    alts = "|".join(re.escape(f).replace(r"\ ", r"\s+")
                    for f in sorted(forms, key=len, reverse=True))
    rx = re.compile(rf"(?<!\w)(?:{alts})(?!\w)", re.IGNORECASE)
    return [Hit(m.start(), m.end(), "MATTER_REF", "ref-case", "heuristic", 17)
            for m in rx.finditer(text)]


def detect(text: str, keeps: Callable[[str | None], bool] = _keeps,
           roster: Roster | None = None) -> list[Hit]:
    """Patterns only — for one value whose label declared nothing."""
    return resolve(text, [], pattern_hits(text), keeps, roster_hits(text, roster))
