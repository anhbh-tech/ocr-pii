"""The label map: which category a field's own label DECLARES.

Ported from pii-lab (`src/pii_lab/labels.py`). The idea is pii-lab's and it is
the strongest one in either project: do not ask "does this string look like a
name?", ask "what does the label say this field is?". A value under
``Họ và tên`` IS a name; nothing is being detected.

Matching is against the WHOLE normalised label (``fullmatch``), accented and
accent-folded, and past-tense docket phrases (``Email Correspondence Entered``)
are rejected, because the cell beside them holds a date.

Deviations from pii-lab, each listed in ``docs/RECONCILIATION.md``:

* A MARK rule runs first. pii-lab's generic ``... name`` rule sends
  ``Trademark name`` to PERSON; a mark is not a person, but looked up on the
  register it names its applicant, so it gets its own category.
* :data:`NOT_PII_LABELS` then exempts products, services and domains.
* URL runs before ADDRESS, so ``Địa chỉ web`` reaches URL rather than being
  swallowed by ``địa chỉ ...``.
* More Vietnamese form labels (``Ông/Bà``, ``Nơi thường trú``, ``Số ĐKKD``,
  ``Căn cước công dân số``, ``Số tài khoản`` ...) — the free-text extractor
  meets these on every case document, and pii-lab's table corpus did not.
"""
from __future__ import annotations

import re
import unicodedata

__all__ = ["normalise", "fold", "category_for_label", "declares_not_pii",
           "is_heading", "EVENT_PHRASE", "LABEL_RULES", "NOT_PII_LABELS",
           "declares_nothing", "NOTHING_LABELS",
           "HEADINGS"]


_TAG = re.compile(r"<[^>]*>")
_ENTITY = re.compile(r"&(?:#x?[0-9a-fA-F]+|[a-z]+);")
_TOKEN = re.compile(r"\[[A-Z_]+-[0-9a-f]+\]")


def normalise(raw: str) -> str:
    """A label's comparable form: markup out, ``*`` and ``:`` off, case folded."""
    text = _TAG.sub(" ", raw)
    text = _ENTITY.sub(" ", text)
    text = _TOKEN.sub(" ", text)
    text = unicodedata.normalize("NFC", text)
    text = text.strip().strip("*").strip()
    text = text.rstrip(":").strip()
    text = text.strip("-•·*#> \t").strip()
    # "(Last name)", "[Full name]": a caption in brackets is the caption.
    while len(text) > 2 and (text[0], text[-1]) in (("(", ")"), ("[", "]")):
        text = text[1:-1].strip()
    return " ".join(text.split()).lower()


def fold(text: str) -> str:
    """Accent-folded form — OCR drops Vietnamese diacritics routinely."""
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFC", stripped).replace("đ", "d").replace("Đ", "D")


# Docket events, not field labels (pii-lab). Past tense is the tell.
EVENT_PHRASE = re.compile(
    r"\b(?:"
    r"e-?mailed|entered|received|written|issued|mailed|sent|filed|"
    r"cancelled|abandoned|approved|assigned|published|revoked|withdrawn|"
    r"amended|refused|suspended|completed|generated|printed|uploaded"
    r")\b"
)


def _both(*alternatives: str) -> re.Pattern[str]:
    """Full-match pattern over the alternatives. Used with ``fullmatch`` only."""
    return re.compile("|".join(alternatives), re.IGNORECASE)


#: Labels that contain a PII word but declare something that is not PII.
#: Checked before :data:`LABEL_RULES`; a match means "declares nothing".
NOT_PII_LABELS = _both(
    r"product(?: name)?", r"domain(?: name)?", r"ten (?:san pham|dich vu|mien)",
)

#: Captions that name a PII word and declare nothing: ``Type of Mark:`` is
#: followed by ``TRADEMARK``, not a mark. Their value is left to the other
#: detectors, unlike a :data:`NOT_PII_LABELS` value. ``Description of Mark``
#: is not one: a design mark's description identifies it as its name does.
NOTHING_LABELS = _both(
    r"(?:type|kind) of (?:the )?mark", r"mark (?:type|drawing (?:type|code))",
)

#: Section headings of the register's renderings (TSDR, the IP Việt Nam
#: forms). A line holding one opens the next section: it is never the value of
#: an empty label above it.
HEADINGS = _both(
    r"goods(?: (?:and|&) services)?", r"services",
    r"(?:danh muc )?(?:hang hoa|san pham)(?:,? (?:va )?dich vu)?",
)


# (category, pattern, why). First match wins, so specific rules come first.
LABEL_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("MARK",
     _both(
         r"(?:trade ?|service |word |figurative )?mark(?: name| text)?",
         r"brand(?: name)?", r"(?:ten |mau )?nhan hieu(?: .*)?",
     ),
     "Before PERSON, so 'Trademark name' is a mark. On the register a mark "
     "names its applicant (Luật Luật sư Điều 25)."),
    ("SOURCE_FILE",
     _both(r"(?:[\w'/]+ )*file name", r"ten (?:tep|file)"),
     "A filename routinely embeds the client's code and name."),
    ("ORG",
     _both(
         r"law firm", r"company(?: name)?", r"organi[sz]ation(?: name)?",
         r"firm(?: name)?", r"ten (?:cong ty|doanh nghiep|to chuc)",
         r"cong ty", r"doanh nghiep", r"bank name", r"entity(?: name)?",
         r"ten (?:giao dich|viet tat)(?: .*)?", r"don vi",
     ),
     "The client organisation: the duty of confidence reaches it."),
    ("PERSON",
     _both(
         r"(?:[\w'/]+ ){0,3}name",
         r"(?:correspondence|signatory'?s?|owner|applicant|attorney|contact|"
         r"author|inventor|representative|examiner|witness|chu don|chu so huu"
         r"|tac gia|nguoi (?:\w+ ?){0,2})[ /]*(?:name|ho va ten|ten)",
         r"ho(?: va)? ten(?:.*)?", r"ten",
         r"ten (?:nguoi|tac gia|chu (?:don|so huu))",
         r"chu don|chu so huu|nguoi nop don|nguoi dai dien|tac gia",
         r"applicant|owner|attorney of record|signatory|correspondent",
         r"(?:(?:legal|authori[sz]ed) )?representative",
         r"ong ?/ ?ba|ong \(ba\)|ong|ba|mr|mrs|ms",
         r"(?:nguoi )?dai dien(?: theo phap luat| theo uy quyen| boi)?",
         r"nguoi (?:lien he|lien lac|ky|uy quyen|duoc uy quyen|nhan)",
         r"(?:nguyen don|bi don|nguoi khieu nai|nguoi yeu cau)",
     ),
     "Labels that name a person or the role a person fills."),
    ("EMAIL",
     _both(
         r"(?:\w+ )*e-?mail(?: address(?:es)?)?",
         r"e-?mail lien he", r"dia chi e-?mail", r"thu dien tu",
         r"(?:primary|courtesy copy|correspondent)[\w /]*e-?mail[\w ]*",
     ),
     "Whole-label match only."),
    ("PHONE",
     _both(
         r"(?:\w+ )*(?:telephone|phone|fax|mobile|tel)(?: number| no)?",
         r"so dien thoai(?: lien he| di dong)?", r"dien thoai(?: .*)?",
         r"fax(?: number)?", r"s?dt(?: di dong| lien he)?", r"di dong",
         r"hotline",
     ),
     ""),
    ("URL",
     _both(r"url", r"web ?site", r"link", r"dia chi web(?:site)?", r"trang web"),
     "Runs before ADDRESS so 'Địa chỉ web' is not an address."),
    ("ADDRESS",
     _both(
         r"(?:\w+ )*address(?: (?:line )?\d)?",
         r"address (?:line \d|information)",
         r"(?:mailing|domicile|street|postal|correspondence)[\w ]*address[\w ]*",
         r"dia chi(?: .*)?",
         r"noi (?:cu tru|thuong tru|tam tru|o(?: hien (?:tai|nay))?|sinh)",
         r"cho o(?: hien (?:tai|nay))?", r"ho khau(?: thuong tru)?",
         r"que quan", r"tru so(?: chinh)?",
         r"city|state/territory|state or territory|zip/postal code|"
         r"postal code|zip code|country",
     ),
     "Address COMPONENTS are included: a form splits one address over "
     "Address Line 1 / City / State / Zip."),
    ("NATIONAL_ID",
     _both(
         r"(?:cccd|cmnd|cmt)(?:[ /].*)?",
         r"so (?:cccd|cmnd|cmt|dinh danh(?: ca nhan)?|the can cuoc|ho chieu)",
         r"(?:the )?can cuoc(?: cong dan)?(?: so)?",
         r"chung minh (?:nhan dan|thu)(?: so)?", r"ho chieu(?: so)?",
         r"(?:national )?id(?:entity)? (?:card )?(?:number|no)",
         r"passport(?: number| no)?",
     ),
     ""),
    ("TAX_CODE",
     _both(
         r"mst", r"ma so thue(?: .*)?", r"tax (?:code|id|identification number)",
         r"(?:so )?dkkd", r"ma so doanh nghiep", r"so dang ky kinh doanh",
         r"giay (?:chung nhan )?dang ky (?:kinh doanh|doanh nghiep)(?: so)?",
         r"business registration(?: number| no)?",
     ),
     "ĐKKD is folded into TAX_CODE, as ocr-lab's own title does."),
    ("APP_SERIAL",
     _both(
         r"(?:u\.?s\.? )?serial number", r"application (?:number|no|serial)",
         r"so don(?: dang ky)?", r"proceeding number",
     ),
     "Public, but it names the client; tokenised, looked up after de-tokenising."),
    ("REG_NUMBER",
     _both(
         r"registration number", r"reg\.? no\.?",
         r"so (?:dang ky|van bang|giay chung nhan)",
     ),
     ""),
    ("NICE_CLASS",
     _both(
         r"(?:international|u\.?s\.?) class(?:\(es\)|es)?",
         r"class(?:\(es\)|es)?", r"nhom(?: san pham| dich vu)?", r"phan nhom",
     ),
     ""),
    ("MATTER_REF",
     _both(
         r"(?:docket|our|your|client)[\w .]*ref(?:erence)?(?: number| no)?",
         r"(?:docket or reference|reference) number", r"ma ho so", r"so ho so",
         r"docket(?: number| no\.?| #)?",
     ),
     ""),
    ("INVOICE_NO",
     _both(r"invoice(?: number| no)?", r"so hoa don", r"hoa don(?: so)?",
           r"ma tra cuu(?: hoa don)?", r"ma (?:cqt|co quan thue)"),
     "The e-invoice lookup code is a bearer key to the buyer and the amount; "
     "the tax office's code (mã CQT) identifies the same invoice."),
    ("OTHER_ID",
     _both(r"so tai khoan(?: .*)?", r"stk", r"(?:bank )?account (?:number|no)",
           r"(?:beneficiary|bank) account(?: number| no)?",
           r"iban|swift(?: code)?",
           r"(?:aba |bank |wire )?routing(?: transit)?(?: number| no\.?| #)?"
           r"(?: \([^)]*\))?",
           r"so dinh tuyen(?: ngan hang)?", r"sort code",
           r"so the(?: ngan hang| tin dung| ghi no)?",
           r"the (?:ngan hang|tin dung|ghi no)", r"card number"),
     "An identifier no specific category receives. A routing / ABA / sort "
     "code names the bank, not the person, but it stands beside the account "
     "number and is read with it; Nghị định 13 Điều 2.4(h) covers the pair."),
    ("MONEY",
     _both(
         r"(?:total|amount|fee|cost|price|subtotal|sum)(?: .*)?",
         r"thanh tien|thanh toan|tong (?:cong|tien)|so tien(?: .*)?|phi(?: .*)?|"
         r"le phi(?: .*)?|thue vat.*|tham khao \(usd\)|don gia|gia",
         r"[\w ]*\(usd\)|[\w ]*\(vnd\)",
         r"(?:so tien )?(?:viet )?bang chu",
     ),
     ""),
    ("BIRTH_DATE",
     _both(
         r"(?:ngay,? )?(?:thang,? )?nam sinh(?:[ /].*)?", r"ngay sinh(?:[ /].*)?",
         r"sinh ngay|sinh nam|ngay thang nam sinh(?:[ /].*)?",
         r"(?:date|place and date) of birth(?:[ /].*)?", r"birth ?date", r"d\.?o\.?b\.?",
     ),
     "Runs before DATE: split out on the firm's 2026-09-28 ruling (P1), "
     "ANONYMISE where a procedural date is tokenised."),
    ("DATE",
     _both(
         r"date(?: of .*| .*)?", r"(?:\w+ )*date", r"ngay(?: .*)?",
         r"(?:filing|issue|expiry|renewal|due) date",
     ),
     "A procedural date: filing, notice, deadline, signature."),
)


def declares_not_pii(raw: str) -> bool:
    """True when the label names something public on purpose — a product, a
    service, a domain. Its value is the thing the agent must read, so the
    heuristic detectors leave it alone (exact detectors still run)."""
    label = normalise(raw)
    return bool(label) and bool(NOT_PII_LABELS.fullmatch(label)
                                or NOT_PII_LABELS.fullmatch(fold(label)))


def declares_nothing(raw: str) -> bool:
    """True when the label is a caption of :data:`NOTHING_LABELS`."""
    label = normalise(raw)
    return bool(label) and bool(NOTHING_LABELS.fullmatch(label))


def is_heading(raw: str) -> bool:
    """True when the text is a form's section heading (:data:`HEADINGS`)."""
    label = normalise(raw)
    return bool(label) and bool(HEADINGS.fullmatch(label)
                                or HEADINGS.fullmatch(fold(label)))


def category_for_label(raw: str) -> str | None:
    """Which category this label DECLARES, or None if it declares nothing.

    None is the common and correct answer: ``Description``, ``Status``,
    ``Kính gửi`` declare nothing.
    """
    label = normalise(raw)
    if not label:
        return None
    if EVENT_PHRASE.search(label):
        return None
    folded = fold(label)
    if NOT_PII_LABELS.fullmatch(label) or NOT_PII_LABELS.fullmatch(folded):
        return None
    for code, pattern, _why in LABEL_RULES:
        if pattern.fullmatch(label) or pattern.fullmatch(folded):
            return code
    return None
