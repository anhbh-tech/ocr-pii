"""Person names in free text: a lexicon, context cues, and the case's own names.

A Vietnamese name is hard to find by shape alone: its syllables are ordinary
words (``Bình``, ``Hà``, ``Minh``), streets and provinces are named after
people, and OCR and chat text drop the accents and the capitals. So the
detection is layered, and ``tests/name_bench.py`` measures each layer:

1. **lexicon**: a name led by a surname (the common ones and rarer ones), a
   ``Văn``/``Thị`` middle name in any casing, and an unknown first syllable
   followed by a middle and a given name from the lexicon.
2. **cues**: honorifics (always on), the kinship words Vietnamese addresses
   people with (``anh Hùng``, ``chị Lan``), a role (``Giám đốc ...``), a
   self-introduction (``tôi là ...``), a salutation, and Western given names.
3. **propagation**: a name found once with confidence (under a label, after
   an honorific, three syllables led by a surname) is looked for again in the
   whole case, in any casing and without accents, and its given name is looked
   for after a cue. Each variant is mapped back to that name, so every mention
   gets the same token.
4. **residue**: a broader name shape, checked on the redacted output. It does
   not redact. It stops the document for a human to look at.

What no layer catches: a name whose surname the lexicon lacks, with no
label, cue or ``Văn``/``Thị`` anywhere in the case; a Western name whose
first name the lexicon lacks, with no title; a bare given name with no cue.
And headings led by a surname syllable (``PHẠM VI CÔNG VIỆC``) are still
taken for names. ``tests/name_bench.py holdout`` measures both.

Every full name in this module's docstrings and comments (``Nguyễn Văn Mẫu``,
``TRẦN THỊ THỬ``, ``Thử Mẫu``) is SYNTHETIC: an illustrative example built
from placeholder words (Mẫu, Thử), not a real person.
"""
from __future__ import annotations

import re
import unicodedata
from bisect import bisect_left
from functools import lru_cache
from typing import Iterable, Iterator, Sequence

__all__ = ["LAYERS", "SURNAMES", "GIVEN", "MIDDLE", "WEST_GIVEN", "key",
           "COMMON", "common_led", "surname_led", "middle_led", "lexicon_led",
           "pair_led", "cue_led", "western", "CaseNames", "residue_names",
           "HONORIFIC"]

#: The benchmark switches layers off to measure each one. Production code
#: never changes this.
LAYERS: set[str] = {"lexicon", "cues", "propagation", "residue"}

_WORD = re.compile(r"[^\W\d_]+")
_GAP = (" ", " ")


@lru_cache(maxsize=1 << 16)
def key(word: str) -> str:
    """Accent- and case-folded: ``Đặng`` and ``DANG`` share ``dang``."""
    s = unicodedata.normalize("NFD", word.casefold())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d")


def _plain(word: str) -> bool:
    return key(word) == word.casefold()


class _Lexicon:
    """Accented words are compared accented and unaccented ones folded. So
    ``Hà`` never matches ``Ha``, but OCR's ``Ha`` still matches ``Hà``."""

    __slots__ = ("accented", "folded")

    def __init__(self, words: str) -> None:
        ws = words.split()
        self.accented = frozenset(w.casefold() for w in ws)
        self.folded = frozenset(key(w) for w in ws)

    def __contains__(self, word: str) -> bool:
        w = word.casefold()
        return key(w) in self.folded if _plain(w) else w in self.accented


def _keys(words: Iterable[str]) -> frozenset[str]:
    return frozenset(" ".join(key(w) for w in p.split()) for p in words)


# -- the lexicon ---------------------------------------------------------------

# pii-lab's surname list (scan.VN_SURNAMES), accented and folded, plus common
# surnames it lacked. Only the accented form is listed where the folded form
# is an everyday English or Vietnamese word ("Ha", "To", "Mai", "Cao").
_BASE_SURNAMES = frozenset(s.casefold() for s in (
    "Nguyễn Nguyen Trần Tran Lê Le Phạm Pham Hoàng Hoang Huỳnh Huynh Phan "
    "Vũ Vu Võ Vo Đặng Dang Bùi Bui Đỗ Do Hồ Ho Ngô Ngo Dương Duong Lý Ly "
    "Đinh Dinh Trịnh Trinh "
    "Hà Mai Tô Trương Truong Lưu Luu Lâm Đào Dao Đoàn Doan Cao Kiều Kieu Tạ "
    "Thái Lương Luong Vương Vuong Triệu Trieu Phùng Phung Châu Quách Quach "
    "Tăng Mạc Mac Tôn Ton Khổng Khong Âu Viên Lại Lai La Chu Nông Hứa Hua").split())

# Rarer surnames, accented only. Left out on purpose because they lead
# everyday phrases in headings: Phó (Phó Giám đốc), Phí (PHÍ DỊCH VỤ), Vi
# (VI PHẠM), Mạch (MẠCH ĐIỆN), Trình (TRÌNH TỰ), Cổ (CỔ PHẦN), Quản (QUẢN
# LÝ), Quan (QUAN HỆ), Từ (Từ ngày), Đường, Mã, Đồng, Hoa, Sơn, Văn, and
# Kha and Nhan, whose unaccented forms are "khả" and "nhãn".
_RARE_SURNAMES = frozenset(s.casefold() for s in (
    "Ung Giang Kim Lục Mẫn Thân Ninh Lã Bạch Đàm Diệp Tiêu Hàn Doãn Khúc "
    "Nghiêm Khương Giáp Lò Tống Thạch Bế Cù Sầm Tào Thiều Uông Nhâm Ôn Đới "
    "Hầu Lường Mông Chế").split())


def surnames() -> frozenset[str]:
    return _BASE_SURNAMES | _RARE_SURNAMES if "lexicon" in LAYERS else _BASE_SURNAMES


SURNAMES = _BASE_SURNAMES | _RARE_SURNAMES
SURNAME_KEYS = frozenset(key(s) for s in SURNAMES)

MIDDLE = _Lexicon(
    "Văn Thị Hữu Đức Quang Minh Công Gia Xuân Ngọc Thu Diệu Kim Thanh Bảo "
    "Đình Quốc Trọng Thành Duy Anh Hoàng Mạnh Tuấn Việt Nhật Khánh Hải Hồng "
    "Phương Thúy Mỹ Như Bích Cẩm Tuyết Hoài Thùy Trung Tiến Đăng Chí Huy Mai "
    "Tường Phúc Bá Khắc Hà Kiều Lệ Thế Nguyên Viết Thiện Tấn Tất Đắc Quý Ánh "
    "Bội Khải Nam Hạnh Vân Tú Lan Hương Linh Hiếu Trí Tâm Hoa")
GIVEN = _Lexicon(
    "An Anh Ánh Bách Bảo Bích Bình Cảnh Cẩm Châu Chi Chiến Chính Công Cúc "
    "Cường Đại Đan Đạt Diễm Diệp Diệu Điệp Định Đông Đức Dung Dũng Dương Duy "
    "Duyên Giang Hà Hải Hạnh Hào Hằng Hân Hậu Hiền Hiển Hiếu Hiệp Hòa Hoa "
    "Hoài Hoan Hoàng Hồng Huệ Hùng Hưng Hương Hường Huy Huyền Khang Khanh "
    "Khánh Khải Khiêm Khoa Khôi Kiên Kiệt Kim Lan Lâm Lành Lệ Liên Liễu Linh "
    "Loan Lộc Lợi Long Luân Lực Lương Ly Lý Mai Mạnh Minh My Mỹ Nam Nga Ngân "
    "Nghĩa Ngọc Nguyên Nhã Nhàn Nhân Nhật Nhi Nhung Như Oanh Phát Phi Phong "
    "Phú Phúc Phụng Phương Phượng Quang Quân Quế Quốc Quý Quyên Quỳnh Sang "
    "Sinh Sơn Tài Tâm Tân Thạch Thái Thắm Thắng Thanh Thành Thảo Thịnh Thơ "
    "Thông Thu Thuận Thủy Thúy Thùy Thư Thương Tiến Tiên Toàn Trang Trâm Trí "
    "Trinh Trọng Trung Tú Tuấn Tùng Tuyết Tường Uyên Vân Việt Vinh Vũ Vy Xuân "
    "Yên Yến Tuệ Đạo Hạ Tín Thiện Thọ Tấn Phước Giao")

# Common Western given names. Left out: the ones that are also words, places
# or months (Mark, Will, Grace, Paris, Victoria, Jordan, May), and the ones
# whose letters are an unaccented Vietnamese word (Don "đơn", Dan "dân").
WEST_GIVEN = frozenset(n.casefold() for n in (
    "James John Robert Michael William David Richard Joseph Thomas Charles "
    "Christopher Daniel Matthew Anthony Donald Steven Paul Andrew Joshua "
    "Kenneth Kevin Brian George Timothy Ronald Edward Jason Jeffrey Ryan Jacob "
    "Gary Nicholas Eric Jonathan Stephen Larry Justin Scott Brandon Benjamin "
    "Samuel Gregory Alexander Patrick Raymond Jack Dennis Jerry Tyler Aaron "
    "Jose Adam Nathan Henry Douglas Zachary Peter Kyle Noah Ethan Jeremy Walter "
    "Christian Keith Roger Terry Sean Gerald Carl Harold Dylan Arthur Lawrence "
    "Jesse Bryan Bruce Gabriel Joe Logan Albert Alan Eugene Russell Vincent "
    "Philip Bradley Mary Patricia Jennifer Linda Elizabeth Barbara Susan "
    "Jessica Sarah Karen Lisa Nancy Betty Sandra Margaret Ashley Kimberly "
    "Emily Donna Michelle Carol Amanda Melissa Deborah Stephanie Dorothy "
    "Rebecca Sharon Laura Cynthia Amy Kathleen Angela Shirley Brenda Emma Anna "
    "Pamela Nicole Samantha Katherine Christine Helen Debra Rachel Carolyn "
    "Janet Maria Catherine Heather Diane Olivia Julie Joyce Ruth Lauren Kelly "
    "Christina Joan Evelyn Judith Andrea Hannah Megan Cheryl Jacqueline Martha "
    "Teresa Gloria Sara Janice Ann Kathryn Abigail Sophia Frances Jean Alice "
    "Judy Isabella Julia Amber Denise Danielle Marilyn Beverly Charlotte "
    "Natalie Theresa Diana Brittany Doris Alexis Marie Hans Klaus Pierre "
    "François Marco Luca Giovanni Carlos Juan Luis Miguel Pedro Hiroshi "
    "Takashi Kenji Akira").split())

# Provinces (before and after the 2025 merger), large cities and districts,
# and the countries a case names. Places, not people: "Hà Lan", "Bình Dương".
PLACES = _keys((
    "An Giang", "Bà Rịa", "Vũng Tàu", "Bắc Giang", "Bắc Kạn", "Bạc Liêu",
    "Bắc Ninh", "Bến Tre", "Bình Định", "Bình Dương", "Bình Phước",
    "Bình Thuận", "Cà Mau", "Cần Thơ", "Cao Bằng", "Đà Nẵng", "Đắk Lắk",
    "Đắk Nông", "Điện Biên", "Đồng Nai", "Đồng Tháp", "Gia Lai", "Hà Giang",
    "Hà Nam", "Hà Nội", "Hà Tĩnh", "Hải Dương", "Hải Phòng", "Hậu Giang",
    "Hòa Bình", "Hưng Yên", "Khánh Hòa", "Kiên Giang", "Kon Tum", "Lai Châu",
    "Lâm Đồng", "Lạng Sơn", "Lào Cai", "Long An", "Nam Định", "Nghệ An",
    "Ninh Bình", "Ninh Thuận", "Phú Thọ", "Phú Yên", "Quảng Bình",
    "Quảng Nam", "Quảng Ngãi", "Quảng Ninh", "Quảng Trị", "Sóc Trăng",
    "Sơn La", "Tây Ninh", "Thái Bình", "Thái Nguyên", "Thanh Hóa",
    "Thừa Thiên Huế", "Tiền Giang", "Hồ Chí Minh", "Trà Vinh", "Tuyên Quang",
    "Vĩnh Long", "Vĩnh Phúc", "Yên Bái", "Sài Gòn", "Nha Trang", "Đà Lạt",
    "Phan Thiết", "Buôn Ma Thuột", "Hạ Long", "Phú Quốc", "Côn Đảo",
    "Hoàng Sa", "Trường Sa", "Cô Tô", "Thủ Đức", "Tân Bình", "Bình Thạnh",
    "Gò Vấp", "Phú Nhuận", "Hoàn Kiếm", "Ba Đình", "Đống Đa", "Cầu Giấy",
    "Hai Bà Trưng", "Hoàng Mai", "Long Biên", "Tây Hồ", "Thanh Xuân",
    "Hà Đông", "Từ Liêm", "Biên Hòa", "Thuận An", "Dĩ An", "Mỹ Tho",
    "Long Xuyên", "Rạch Giá", "Quy Nhơn", "Việt Nam", "Hà Lan", "Hoa Kỳ",
    "Anh Quốc", "Nhật Bản", "Hàn Quốc", "Trung Quốc", "Thái Lan", "Ấn Độ",
    "Đài Loan", "Hồng Kông", "Triều Tiên", "Tân Tây Lan", "Đông Nam Á",
    "Châu Á", "Châu Âu", "Châu Mỹ", "Châu Phi", "Châu Úc", "Liên Minh Châu Âu",
    "Nam Phi", "Nam Mỹ", "Trung Đông", "Đông Dương"))

# Runs that start with a surname and are not names.
NOT_NAMES = _keys((
    "hồ sơ", "lý do", "lý lịch", "lý thuyết", "dương lịch", "lê chân",
    "hồ tây", "hồ gươm", "mai dịch", "cao lãnh", "hoàng kiếm", "trần đề",
    "lý sơn", "vũ tàu", "lương sơn", "đô lương", "hà tiên", "chu lai",
    "mặc định", "tăng cường", "tăng trưởng", "hứa hẹn", "phụng sự", "cao cấp",
    "cao học", "cao đẳng", "trần thuật", "trần tình", "vô hạn", "vô hiệu",
    "vô điều kiện", "vô danh", "lệ phí", "tôn trọng", "tồn tại", "không thể",
    "phan rang", "hứa", "ung thư", "ứng dụng", "ứng viên", "ứng xử",
    "ứng phó", "ứng trước", "kim loại", "kim ngạch", "lục địa", "lực lượng",
    "thân gửi", "thân thiện", "thân nhân", "thân chủ", "đàm phán",
    "đàm thoại", "tiêu chuẩn", "tiêu chí", "tiêu dùng", "tiêu thụ",
    "tiêu đề", "tiêu biểu", "tiêu điểm", "hạn chế", "hạn mức", "tống đạt",
    "hầu hết", "chế độ", "chế tài", "chế tạo", "chế biến", "giảng viên",
    "giảng dạy", "quốc khánh", "quốc gia", "quốc tế", "minh bạch",
    "đông nam", "an toàn", "an ninh", "tân tiến", "lâm thời", "đào tạo",
    "đoàn kết", "trương mục", "lưu ý"))

# A word before the surname that makes the run a street, a place or an
# institution named after a person: "đường Lê Lợi" is an address.
_PLACE_BEFORE = frozenset(w.casefold() for w in (
    "đường phố quận huyện phường xã tỉnh tp tp. thị trấn trường cầu chợ hẻm "
    "ngõ ngách lộ khu bến cảng st street road district ward duong pho huyen "
    "phuong hem thpt thcs đại học viện chùa đền sông núi đảo kênh rạch lăng "
    "tượng đình miếu phụ").split())
_PLACE_BEFORE_BASE = frozenset(w.casefold() for w in (
    "đường phố quận huyện phường xã tỉnh tp tp. thị trấn trường cầu chợ hẻm "
    "ngõ ngách lộ khu bến cảng st street road district ward duong pho huyen "
    "phuong hem thpt thcs đại học").split())

# The form captions a table cell's flattened ``<br>`` leaves on the name's
# own line: ``Full name: <name> Nationality: <country>``.
CAPTIONS = frozenset(w.casefold() for w in (
    "nationality citizenship gender sex position occupation profession address "
    "tel phone mobile fax passport "
    # and the Vietnamese ones' first words (chức vụ, giới tính, dân tộc,
    # nghề nghiệp, quê quán, nơi sinh), none of them a name syllable.
    "chức giới dân nghề quê nơi").split())
# Words that end a name run, compared with accents kept.
NAME_STOP = CAPTIONS | frozenset(w.casefold() for w in (
    "và của là với cho tại theo về ông bà số ngày tháng địa chỉ giám đốc luật "
    "sư đơn quốc tịch điện thoại email sinh "
    "the of and to not it is a an in on for with by at from whom may be this "
    "that no as or we you your our dear re subject").split())

# Words that cannot be the unknown first syllable of a name: institutions,
# document words, prepositions. They lead headings, not people.
_LEAD_STOP = _Lexicon(
    "sư ty tnhh phần hạn viện trường học bộ sở cục tổng phòng ban hội tòa án "
    "ngân hàng chi nhánh tâm trung khu xã phường quận huyện tỉnh phố thành "
    "đường cầu chợ sông núi đảo biển theo của cho với và tại từ về gửi kính "
    "thân chào cảm ơn xin nhờ là được bởi do cùng người ông bà anh chị em cô "
    "chú bác luật giám đốc chủ tịch nhãn hiệu sản phẩm dịch vụ hợp đồng điều "
    "khoản mục số ngày tháng năm quý công văn đại hệ thống kế toán bên đơn "
    "giấy bản quyết định thông báo tờ khai lệ phí quỹ nhà máy xưởng cửa "
    "siêu thị khách sạn hãng tập đoàn liên minh ủy nhân dân quốc chính phủ "
    "vụ việc tiếng nước mã")

# Vietnamese common words that are never a name syllable: the document nouns
# a line opens with and the function words. Capitalised at the start of a
# sentence, after a label or after a role, "Đơn" is still the application,
# not a person. Accented forms only, compared accented: ``Don`` is a name.
COMMON = frozenset(w.casefold() for w in (
    "Đơn Tờ Giấy Bản Phiếu Hợp Chứng Nhãn Hạn Mốc Bước Lần Mục Khoản Điều "
    "Nhóm Phụ Trạng Kết Yêu Nội Việc Tiền Người Chủ Bên Các Những Mọi Mỗi "
    "Không Chưa Hiện Đã Đang Sẽ Cần Còn Kèm Gồm Được Bị Có Cả Trước Ngoài "
    "Đến Nếu Vì Nhưng Hoặc Đây Đó Này").split())


def common_led(value: str) -> bool:
    """``Đơn đã nộp``: a value that opens with a common word and has no other
    capitalised word is a sentence, not a name."""
    ws = _WORD.findall(value)
    return bool(ws) and ws[0].casefold() in COMMON \
        and not any(_case(w) in ("title", "caps") for w in ws[1:])


_ORG_WORDS = _Lexicon(
    "tnhh ltd limited inc llc corp corporation jsc co company gmbh plc llp "
    "group holdings bank")
_ORG_PAIRS = _keys(("công ty", "cổ phần", "ngân hàng", "tập đoàn"))


def _has_org(words: Sequence[str]) -> bool:
    """A company marker among ``words``. The Vietnamese ones are pairs: alone,
    Công, Đoàn and Hàng are names."""
    return any(w in _ORG_WORDS for w in words) or any(
        f"{key(x)} {key(y)}" in _ORG_PAIRS for x, y in zip(words, words[1:]))


# Văn/Thị/Vấn inside an everyday compound, not a middle name.
_MID_PREV_NOT = _keys((
    "siêu thị", "đô thị", "thành thị", "hiển thị", "chỉ thị", "yết thị",
    "công văn", "luận văn", "ngữ văn", "nhân văn", "thiên văn", "thủy văn",
    "điện văn", "tản văn", "tạp văn", "cáo thị",
    # "dịch vụ tư vấn" read as "<họ> Vấn <tên>" and blocked whole documents.
    "tư vấn", "cố vấn", "tham vấn", "thẩm vấn", "phỏng vấn", "chất vấn"))
_MID_NEXT_NOT = _keys((
    "thị xã", "thị trấn", "thị trường", "thị thực", "thị giác", "thị phần",
    "thị hiếu", "thị uy", "thị sát", "thị chính", "văn bản", "văn phòng",
    "văn hóa", "văn kiện", "văn học", "văn thư", "văn nghệ", "văn minh",
    "văn bằng", "văn phạm", "văn hiến", "văn tự", "vấn đề", "vận hành",
    "vận chuyển", "vận đơn", "vận dụng", "vận động", "vận tải", "vận tốc",
    "thi hành", "thi công", "thi tuyển", "thi đua", "thí sinh", "thí điểm",
    "thí nghiệm", "thí dụ", "vạn năng"))
_STRONG_MIDDLE = frozenset(("văn", "thị"))
# A surname that is the second half of an everyday compound: "dịch vụ pháp
# lý" is legal services, not "<họ> Vụ" or "<họ> Lý". Compared folded, so the
# unaccented "VU PHAP LY" of a foreign form is the same compound.
_SURNAME_COMPOUND = _keys((
    "dịch vụ", "nhiệm vụ", "nghĩa vụ", "phục vụ", "chức vụ", "nghiệp vụ",
    "công vụ", "sự vụ", "quản lý", "xử lý", "pháp lý", "đại lý", "hợp lý",
    "tâm lý", "địa lý", "trợ lý", "thụ lý", "vi phạm", "tập đoàn", "đồng hồ",
    "nâng cao", "tiền lương", "trạng thái"))
# A word inside a capitalised run that makes it a thing, not a person: a
# place named after one, as an English rendering writes it ("Nguyen Du
# Ward"), or a currency whose country reads as a surname ("Thai Baht").
_THING_AFTER = frozenset(w.casefold() for w in (
    "ward district street st road rd avenue ave lane ln boulevard blvd "
    "commune province city town village hamlet bridge park square "
    "baht dollar dollars euro euros yuan renminbi ringgit rupiah rupee rupees "
    "peso pesos pound pounds sterling franc francs krone kroner krona kronor "
    "riel kyat rouble ruble shekel dirham riyal dinar").split())

# A single line break may part the honorific from the name, as in a
# signature block ("Bà\nThử Mẫu", a synthetic name); a blank line may not.
HONORIFIC = _HONORIFIC = re.compile(
    r"(?<![\w])(?:Ông|ông|ÔNG|Bà|bà|BÀ|Mr\.?|Mrs\.?|Ms\.?|Miss|Dr\.?|"
    r"Luật sư|luật sư|LUẬT SƯ|LS\.)(?:[ \t]+|[ \t]*\r?\n[ \t]*)")
_BA_PLACES = frozenset(w.casefold() for w in (
    "rịa chiểu đen triệu huyện điểm hom quẹo nà chúa trưng").split())
# How Vietnamese addresses a person: "anh Hùng", "chị Lan", "Cô Mai".
_KIN = re.compile(
    r"(?<![\w])(?:anh|chị|em|cô|chú|bác|cháu|bạn|dì|cậu|thím|mợ|"
    r"Anh|Chị|Em|Cô|Chú|Bác|Cháu|Bạn|Dì|Cậu)[ \t]+")
_KIN_NOT = frozenset(("quốc", "văn", "ngữ", "mỹ"))
_KIN_NOT_BEFORE = frozenset(("tiếng", "nước", "người", "bằng", "tieng", "nuoc"))
_SALUTE = re.compile(
    r"(?<![\w])(?:Dear|Hi|Hello|Chào|chào|Kính gửi|kính gửi|KÍNH GỬI|"
    r"Thân gửi|thân gửi)[ \t]*,?[ \t]+")
_ROLE = re.compile(
    r"(?<![\w])(?:tổng giám đốc|phó giám đốc|giám đốc|phó chủ tịch|chủ tịch|"
    r"kế toán trưởng|trưởng phòng|trưởng ban|thư ký|người đại diện(?: theo "
    r"pháp luật)?|người ký|người nhận|tác giả|chủ đơn|thẩm phán|kiểm sát viên|"
    r"chấp hành viên|công chứng viên|thừa phát lại|điều tra viên|hội thẩm|"
    r"managing director|director|ceo|cfo|chairman|chairwoman|president|"
    r"signed by|attn\.?|attention|inventor|examiner)[ \t]*[:：]?[ \t]+",
    re.IGNORECASE)
_INTRO = re.compile(
    r"(?<![\w])(?:tên tôi là|tôi tên là|tôi là|tên là|em là|mình là|"
    r"ten toi la|toi ten la|toi la|ten la|em la|minh la)[ \t]+", re.IGNORECASE)
EN_NOT = frozenset(w.casefold() for w in (
    "Sir Sirs Madam Madame Colleague Colleagues Counsel All Team Client "
    "Customer Partner Partners Members Member Friends Board Committee "
    "Examiner Officer Registrar Director Manager Applicant Applicants Owner "
    "Reader Reviewer Users User Everyone There You We I The A An This That "
    "Office Action Convention Protocol Street Road Avenue Lane University "
    "College Hospital School Institute Foundation Company Group Holdings "
    "Limited Ltd Inc LLC Corp Corporation Bank Trust Center Centre Court Act "
    "Agreement Treaty Law Regulation Rules Code And Or Of For Regards Wishes "
    "Sincerely Thanks "
    # The events a docket prints after "PETITION TO DIRECTOR".
    "Received Granted Filed Denied Instituted Terminated Approved Issued "
    "Mailed Accepted Refused Withdrawn Abandoned Published Registered "
    "Petition Notice").split())


# -- word runs -----------------------------------------------------------------

# A Western surname with a capital inside it.
_WEST_PREFIXED = re.compile(r"(?:Mc|Mac|De|Di|Da|Du|La|Le|Van|Von|Fitz)[A-Z][a-z]+")


@lru_cache(maxsize=1 << 16)
def _case(word: str) -> str | None:
    if len(word) > 1 and word.isupper():
        return "caps"
    if word[0].isupper() and (len(word) == 1 or word[1:].islower()):
        return "title"
    if _WEST_PREFIXED.fullmatch(word):
        return "title"                     # McDonald, DeVries
    if word.islower():
        return "lower"
    return None


class _Piece:
    """A word cut out of a longer one, with the face of a match."""

    __slots__ = ("_s", "_e", "_w")

    def __init__(self, s: int, e: int, w: str) -> None:
        self._s, self._e, self._w = s, e, w

    def start(self) -> int:
        return self._s

    def end(self) -> int:
        return self._e

    def group(self) -> str:
        return self._w


def _syllable(w: str) -> bool:
    return w.casefold() in surnames() or w in GIVEN or w in MIDDLE


def _glued(word: str) -> list[int]:
    """Where ``word`` is two words OCR glued: ``LanGiám``, ``AnhFirst`` (a
    name, then the next field's role or label). A cut only where the left part
    is a name syllable, and never in ``McDonald`` or ``LeBlanc``."""
    if _WEST_PREFIXED.fullmatch(word):
        return []
    cuts = [i for i in range(1, len(word) - 1)
            if word[i - 1].islower() and word[i].isupper() and word[i + 1].islower()]
    out, prev = [], 0
    for i in cuts:
        nxt = next((j for j in cuts if j > i), len(word))
        left, right = word[prev:i], word[i:nxt]
        if _syllable(left):
            out.append(i)
            prev = i
    return out


def _words(text: str) -> list:
    out: list = []
    for m in _WORD.finditer(text):
        w = m.group()
        cuts = _glued(w) if not w.islower() and not w.isupper() and len(w) > 3 else []
        if not cuts:
            out.append(m)
            continue
        edges = [0, *cuts, len(w)]
        out.extend(_Piece(m.start() + a, m.start() + b, w[a:b])
                   for a, b in zip(edges, edges[1:]))
    return out


def _joined(text: str, a: re.Match[str], b: re.Match[str]) -> bool:
    return text[a.end():b.start()] in _GAP


def _name_run(text: str, words: list[re.Match[str]], i: int, casing: str,
              limit: int) -> int:
    """How many words after ``words[i]`` continue a name. Single spaces only."""
    taken, j = 0, i
    while taken < limit and j + 1 < len(words):
        nxt = words[j + 1]
        if not _joined(text, words[j], nxt):
            break
        w = nxt.group()
        if _case(w) != casing and not (casing == "caps" and len(w) == 1):
            break
        if w.casefold() in NAME_STOP:
            break
        taken += 1
        j += 1
    return taken


def _nonname_prefix(folded: list[str]) -> int:
    """Words at the start of ``folded`` that are a place or an everyday
    phrase, not a name. ``0`` when there are none."""
    stop = NOT_NAMES | PLACES if "lexicon" in LAYERS else NOT_NAMES
    for n in range(min(len(folded), 4), 0, -1):
        if " ".join(folded[:n]) in stop:
            return n
    return 0



def _after_place(text: str, words: list[re.Match[str]], i: int) -> bool:
    if i == 0:
        return False
    before = words[i - 1].group().casefold()
    gap = text[words[i - 1].end():words[i].start()]
    places = _PLACE_BEFORE if "lexicon" in LAYERS else _PLACE_BEFORE_BASE
    return before in places and gap.strip(" .") == ""


def _surname(word: str, loose: bool = False) -> bool:
    w = word.casefold()
    if w in surnames():
        return True
    return loose and _plain(w) and key(w) in SURNAME_KEYS


# -- layer 1: the lexicon --------------------------------------------------------

def surname_led(text: str) -> Iterator[tuple[int, int]]:
    """``Nguyễn Văn Mẫu``, ``TRẦN THỊ THỬ``: a surname and up to three more
    words in the same casing. (Synthetic examples, not real people.)"""
    words = _words(text)
    skip = -1
    for i, m in enumerate(words):
        if i <= skip:
            continue
        w = m.group()
        casing = _case(w)
        if casing not in ("title", "caps") or not _surname(w):
            continue
        if i > 0 and _joined(text, words[i - 1], m) \
                and f"{key(words[i - 1].group())} {key(w)}" in _SURNAME_COMPOUND:
            continue
        run = _name_run(text, words, i, casing, 3)
        for j in range(1, run + 1):
            if f"{key(words[i + j - 1].group())} {key(words[i + j].group())}" \
                    in _SURNAME_COMPOUND:
                run = max(j - 2, 0)
                break
        if run == 0:
            continue
        # The thing may stand on the next line: "Nguyen Du\nWard …".
        after = words[i + run + 1] if i + run + 1 < len(words) else None
        wrapped = after is not None and text[words[i + run].end():after.start()] == "\n" \
            and after.group().casefold() in _THING_AFTER
        if wrapped or any(x.group().casefold() in _THING_AFTER
                          for x in words[i + 1:i + run + 1]):
            skip = i + run
            continue
        if _after_place(text, words, i):
            if "lexicon" in LAYERS:
                skip = i + run       # "đường Phan Chu Trinh": Chu is no surname
            continue
        folded = [key(x.group()) for x in words[i:i + run + 1]]
        n = _nonname_prefix(folded)
        if n:
            if "lexicon" in LAYERS:
                skip = i + n - 1
            continue
        yield m.start(), words[i + run].end()


def middle_led(text: str) -> Iterator[tuple[int, int]]:
    """``X Văn Y``/``X Thị Y`` in any casing, the middle name no other word
    order produces: ``Giả Thị Giang``, ``le thi lan``, ``NGUYEN VAN HUNG``."""
    if "lexicon" not in LAYERS:
        return
    words = _words(text)
    for i in range(1, len(words) - 1):
        mid = words[i].group()
        if key(mid) not in ("van", "thi"):
            continue
        if not _plain(mid) and mid.casefold() not in _STRONG_MIDDLE:
            continue
        prev, nxt = words[i - 1], words[i + 1]
        if not (_joined(text, prev, words[i]) and _joined(text, words[i], nxt)):
            continue
        casing = _case(mid)
        if casing is None or {_case(prev.group()), _case(nxt.group())} != {casing}:
            continue
        pair_prev = f"{key(prev.group())} {key(mid)}"
        pair_next = f"{key(mid)} {key(nxt.group())}"
        if pair_prev in _MID_PREV_NOT or pair_next in _MID_NEXT_NOT:
            continue
        if nxt.group().casefold() in NAME_STOP or _after_place(text, words, i - 1):
            continue
        if casing == "lower":
            if not _surname(prev.group(), loose=True):
                continue
        elif prev.group() in _LEAD_STOP or prev.group().casefold() in NAME_STOP:
            continue
        end = i + 1
        if end + 1 < len(words) and _joined(text, words[end], words[end + 1]) \
                and _case(words[end + 1].group()) == casing \
                and words[end + 1].group() in GIVEN \
                and words[end + 1].group().casefold() not in NAME_STOP:
            end += 1
        folded = [key(x.group()) for x in words[i - 1:end + 1]]
        if _nonname_prefix(folded):
            continue
        yield prev.start(), words[end].end()


def _runs(text: str, words: list[re.Match[str]]) -> Iterator[tuple[int, int, str]]:
    """Maximal runs of words in one casing, joined by single spaces:
    ``(first index, last index, casing)``."""
    i = 0
    while i < len(words):
        casing = _case(words[i].group())
        j = i
        while j + 1 < len(words) and _joined(text, words[j], words[j + 1]) \
                and _case(words[j + 1].group()) == casing:
            j += 1
        if casing is not None:
            yield i, j, casing
        i = j + 1


def lexicon_led(text: str) -> Iterator[tuple[int, int]]:
    """An unknown first syllable, then a middle name and a given name from
    the lexicon: ``Cấu Minh Bình``, ``LUC THANH QUYNH``. The surrounding run
    may be led only by words that cannot be names, so a heading is safe."""
    if "lexicon" not in LAYERS:
        return
    words = _words(text)
    for a, b, casing in _runs(text, words):
        if casing not in ("title", "caps") or b - a < 2:
            continue
        run = [w.group() for w in words[a:b + 1]]
        for j in range(len(run) - 2):
            tail = run[j + 1:]
            if not 2 <= len(tail) <= 3:
                continue
            if run[j] in _LEAD_STOP or run[j].casefold() in NAME_STOP:
                continue
            if tail[0] not in MIDDLE or tail[-1] not in GIVEN \
                    or not all(t in MIDDLE or t in GIVEN for t in tail):
                continue
            if not all(w in _LEAD_STOP for w in run[:j]):
                break
            if _after_place(text, words, a + j):
                break
            if _nonname_prefix([key(w) for w in run[j:]]):
                break
            yield words[a + j].start(), words[b].end()
            break


# Two name syllables that make an everyday word or an institution's name
# ("Tài Chính", "Công An"): capitalised in a heading, still not a person.
_COMMON_PAIRS = _keys((
    "hạnh phúc", "thành công", "thắng lợi", "vinh quang", "tài chính",
    "tài nguyên", "công an", "công thương", "công lý", "giao thông",
    "hải quan", "hiệp định", "trung thành", "trung thu", "an khang",
    "phát tài", "tài lộc", "phúc lộc"))
# The word before a pair that makes it a mark, a shop or a company.
_BRAND_BEFORE = frozenset(w.casefold() for w in (
    "hiệu mark brand trademark ty tnhh jsc hãng phẩm hàng tiệm quán sạn").split())


def pair_led(text: str) -> Iterator[tuple[int, int]]:
    """``Thu Hà``, ``Khánh Linh``: two accented, capitalised name syllables
    standing alone, with no surname and no cue. The run may be led only by
    words that cannot be names, so a longer heading is safe."""
    if "lexicon" not in LAYERS:
        return
    words = _words(text)
    for a, b, casing in _runs(text, words):
        if casing != "title" or b == a:
            continue
        i = b - 1
        lead = [w.group() for w in words[a:i]]
        if not all((w in _LEAD_STOP or w.casefold() in NAME_STOP)
                   and not (_surname(w, loose=True) or w in MIDDLE or w in GIVEN)
                   for w in lead):
            continue
        x, y = words[i].group(), words[b].group()
        fx, fy = x.casefold(), y.casefold()
        # Accented text spells a plain name plainly: "Hải Quan" is customs.
        if _plain(fx) and _plain(fy):
            continue
        if fx not in MIDDLE.accented and fx not in GIVEN.accented \
                or fy not in GIVEN.accented:
            continue
        # A kinship word stops a name from starting (`anh Hùng`), not from
        # ending: `Khánh Anh`.
        if x in _LEAD_STOP or (y in _LEAD_STOP and not _KIN.match(y + " ")) \
                or fx in COMMON or fy in COMMON:
            continue
        pair = [key(x), key(y)]
        if _nonname_prefix(pair) or " ".join(pair) in _COMMON_PAIRS \
                or _compound([x, y]) or _after_place(text, words, i):
            continue
        if i > 0 and words[i - 1].group().casefold() in _BRAND_BEFORE \
                and text[words[i - 1].end():words[i].start()].strip(" :\"“") == "":
            continue
        if b + 1 < len(words) and words[b + 1].group() in _ORG_WORDS:
            continue
        yield words[i].start(), words[b].end()


# -- layer 2: cues ---------------------------------------------------------------

def _after(text: str, words: list[re.Match[str]], starts: list[int], pos: int,
           limit: int, casings=("title", "caps")) -> tuple[int, int] | None:
    k = bisect_left(starts, pos)
    if k >= len(words) or words[k].start() != pos:
        return None
    first = words[k].group()
    casing = _case(first)
    if casing not in casings or first.casefold() in NAME_STOP \
            or first.casefold() in COMMON:
        return None
    run = _name_run(text, words, k, casing, limit)
    return k, k + run


def _name_below(names: list[str]) -> bool:
    """The line under an honorific holds a name, not the next line of prose
    (``bà\\nHôm nay``) or a form's next label (``Ông/Bà\\nHọ và tên``)."""
    if names[0] in _LEAD_STOP or (len(names) == 1 and names[0] not in GIVEN):
        return False
    return not _nonname_prefix([key(w) for w in names])


def _abbreviation(names: list[str]) -> bool:
    """``chủ đơn NH``: two capitals alone are an abbreviation, unless they
    are a name syllable (``AN``, ``LÊ``)."""
    w = names[0]
    return len(names) == 1 and _case(w) == "caps" and len(w) <= 2 \
        and not (_surname(w, loose=True) or w in MIDDLE or w in GIVEN)


def cue_led(text: str) -> Iterator[tuple[int, int]]:
    """A name after an honorific, a kinship word, a role, a salutation or a
    self-introduction."""
    words = _words(text)
    starts = [w.start() for w in words]
    for h in _HONORIFIC.finditer(text):
        got = _after(text, words, starts, h.end(), 3)
        if got is None:
            continue
        k, e = got
        if h.group().strip().casefold() == "bà" and words[k].group().casefold() in _BA_PLACES:
            continue
        # "Luật sư Hoa Kỳ" is a lawyer of that country, not a name.
        if key(h.group().strip()).startswith(("luat su", "ls")) and "lexicon" in LAYERS:
            folded = [key(w.group()) for w in words[k:e + 1]]
            if _nonname_prefix(folded) == len(folded):
                continue
        if "\n" in h.group() and not _name_below([w.group() for w in words[k:e + 1]]):
            continue
        yield words[k].start(), words[e].end()
    if "cues" not in LAYERS:
        return
    for c in _KIN.finditer(text):
        got = _after(text, words, starts, c.end(), 2)
        if got is None:
            continue
        k, e = got
        first = words[k].group()
        if first.casefold() in _KIN_NOT or first in _LEAD_STOP:
            continue
        before = text[:c.start()].rstrip().rsplit(None, 1)
        if before and before[-1].casefold() in _KIN_NOT_BEFORE:
            continue
        cue = key(c.group().strip())
        folded = [key(w.group()) for w in words[k:e + 1]]
        if _nonname_prefix(folded) or _nonname_prefix([cue, *folded]):
            continue
        yield words[k].start(), words[e].end()
    for c in _SALUTE.finditer(text):
        got = _after(text, words, starts, c.end(), 2)
        if got is None:
            continue
        k, e = got
        first = words[k].group()
        if first in _LEAD_STOP or first.casefold() in EN_NOT \
                or _KIN.match(first + " ") or _HONORIFIC.match(first + " "):
            continue
        if _nonname_prefix([key(w.group()) for w in words[k:e + 1]]):
            continue
        yield words[k].start(), words[e].end()
    for c in _ROLE.finditer(text):
        got = _after(text, words, starts, c.end(), 3)
        if got is None:
            continue
        k, e = got
        names = [w.group() for w in words[k:e + 1]]
        if _HONORIFIC.match(text, words[k].start()):
            continue                       # "Signed by: Mr. …": the honorific leads
        if names[0] in _LEAD_STOP or _has_org(names) \
                or names[0].casefold() in EN_NOT or _abbreviation(names):
            continue
        if _nonname_prefix([key(w) for w in names]):
            continue
        yield words[k].start(), words[e].end()
    for c in _INTRO.finditer(text):
        got = _after(text, words, starts, c.end(), 3, ("title", "caps", "lower"))
        if got is None:
            continue
        k, e = got
        names = [w.group() for w in words[k:e + 1]]
        if len(names) < 2 or not _surname(names[0], loose=True):
            continue
        if not all(w in MIDDLE or w in GIVEN for w in names[1:]):
            continue
        yield words[k].start(), words[e].end()


def western(text: str) -> Iterator[tuple[int, int]]:
    """``Mary Placeholder``: a Western given name and one or two capitalised
    words that are not an institution."""
    if "cues" not in LAYERS:
        return
    words = _words(text)
    for a, b, casing in _runs(text, words):
        if casing != "title" or b == a:
            continue
        cut = next((k for k in range(a + 1, b + 1)
                    if words[k].group().casefold() in CAPTIONS), None)
        if cut is not None:
            b = cut - 1
        run = [w.group() for w in words[a:b + 1]]
        j = next((j for j, w in enumerate(run) if w.casefold() in WEST_GIVEN), None)
        if j is None or not all(w.casefold() in EN_NOT or _SALUTE.match(w + " ")
                                or _HONORIFIC.match(w + " ") for w in run[:j]):
            continue
        rest = run[j + 1:]
        if not 1 <= len(rest) <= 2 or any(w.casefold() in EN_NOT for w in rest):
            continue
        after = text[words[b].end():words[b].end() + 16].split()
        if after and after[0].strip(",.;:").casefold() in EN_NOT:
            continue
        yield words[a + j].start(), words[b].end()


# -- layer 3: the case's own names -----------------------------------------------

_CUES = frozenset(w.casefold() for w in (
    "anh chị em cô chú bác cháu bạn dì cậu ông bà mr mrs ms miss dr dear hi "
    "hello chào sư đốc tịch").split())
_PLAIN_CUES = frozenset("anh ong chi mr mrs ms dr dear hi hello".split())


def _is_cue(word: str) -> bool:
    w = word.casefold()
    return w in _PLAIN_CUES if _plain(w) else w in _CUES


_TONES = frozenset("\u0300\u0301\u0303\u0309\u0323")


def _toned(word: str) -> tuple[str, str]:
    """A syllable's letters and its tone, apart: ``Hòa`` and ``Hoà`` are one
    syllable, whichever vowel the tone mark sits on."""
    d = unicodedata.normalize("NFD", word.casefold())
    return (unicodedata.normalize("NFC", "".join(c for c in d if c not in _TONES)),
            "".join(c for c in d if c in _TONES))


def _vietnamese(words: list[str]) -> bool:
    return (_surname(words[0], loose=True) or any(not _plain(w) for w in words)
            or any(key(w) in ("van", "thi") for w in words[1:-1]))


class CaseNames:
    """The names a case has already shown with confidence, and every shape
    they reappear in.

    * the full name, in any casing, with or without accents;
    * surname + given name (``Nguyễn Hùng``), when capitalised;
    * the given name, or the last two syllables, right after a cue (``anh
      hùng``, ``chị Thu Hà``); for a Western name the first name or the
      surname.

    Each hit carries the canonical name, so a variant wears its token. A
    variant two names share (two people called Hùng) gets no canonical and
    keeps a token of its own.

    ``guesses`` are names no detector was sure of (the values a vault holds,
    whatever found them). They are found again only in a name's shape: in
    one casing, and not in accented lower case, which is prose ("phạm vi",
    scope, after a heading "PHẠM VI" was taken for a name). And for every
    name, an accented word is its syllable only with that syllable's
    accents: "anh vẫn" (he still) is no "anh Vân".
    """

    def __init__(self, names: Iterable[str] = (), guesses: Iterable[str] = ()) -> None:
        groups: dict[tuple[str, ...], set[str]] = {}
        sure: set[tuple[str, ...]] = set()
        for raw, guess in [*((n, False) for n in names), *((g, True) for g in guesses)]:
            words = _WORD.findall(raw)
            if not 2 <= len(words) <= 5 or any(ch.isdigit() for ch in raw) \
                    or _has_org(words):
                continue
            k = tuple(key(w) for w in words)
            if _nonname_prefix(list(k)) == len(k) \
                    or any(f"{x} {y}" in _SURNAME_COMPOUND for x, y in zip(k, k[1:])) \
                    or any(w.casefold() in _THING_AFTER for w in words[1:]):
                continue
            groups.setdefault(k, set()).add(" ".join(raw.split()))
            if not guess:
                sure.add(k)
        self.full: dict[str, list[tuple[tuple[str, ...], str]]] = {}
        self.short: dict[tuple[str, ...], set[str]] = {}
        self.pair: dict[tuple[str, str], set[str]] = {}
        self._canonical: dict[tuple[str, ...], str] = {}
        self._guess = set(groups) - sure
        # The accented spellings each syllable was seen with, tone marks
        # wherever the font put them.
        self._tones: dict[str, set[tuple[str, str]]] = {}
        for forms in groups.values():
            for f in forms:
                for w in _WORD.findall(f):
                    if not _plain(w):
                        self._tones.setdefault(key(w), set()).add(_toned(w))
        for k, forms in groups.items():
            canon = max(forms, key=lambda f: (not _plain(f), f[:1].isupper()
                                              and not f.isupper(), f))
            self._canonical[k] = canon
            self.full.setdefault(k[0], []).append((k, canon))
            if _vietnamese(canon.split()):
                shorts = [k[-1:]] + ([k[-2:]] if len(k) >= 3 else [])
                if len(k) >= 3:
                    self.pair.setdefault((k[0], k[-1]), set()).add(canon)
            else:
                shorts = [k[:1], k[-1:]]
            for s in shorts:
                self.short.setdefault(s, set()).add(canon)
        for seqs in self.full.values():
            seqs.sort(key=lambda t: -len(t[0]))

    def __bool__(self) -> bool:
        return bool(self._canonical)

    def canonical(self, value: str) -> str:
        """The canonical form of a value that IS one of the names, else ``""``."""
        k = tuple(key(w) for w in _WORD.findall(value))
        return self._canonical.get(k, "")

    def find(self, text: str) -> list[tuple[int, int, str]]:
        """``(start, end, canonical)`` for every reappearance, left to right,
        never overlapping."""
        words = _words(text)
        keys = [key(w.group()) for w in words]
        out: list[tuple[int, int, str]] = []
        i = 0
        while i < len(words):
            got = self._match(text, words, keys, i)
            if got is None:
                i += 1
                continue
            n, canon = got
            # "đường Nguyễn Du", "Nguyen Du Ward": the street named after a
            # person, as the detectors read it too.
            after = words[i + n] if i + n < len(words) else None
            if _after_place(text, words, i) or (
                    after is not None and after.group().casefold() in _THING_AFTER
                    and text[words[i + n - 1].end():after.start()].strip() == ""):
                i += n
                continue
            out.append((words[i].start(), words[i + n - 1].end(), canon))
            i += n
        return out

    def _joined(self, text: str, words, i: int, n: int) -> bool:
        # "Mau T. Placeholder": an initial keeps its full stop.
        return all(self._gap(text[words[j].end():words[j + 1].start()], words[j].group())
                   for j in range(i, i + n - 1))

    @staticmethod
    def _gap(gap: str, before: str) -> bool:
        if len(before) == 1 and gap.startswith("."):
            gap = gap[1:]
        return gap.strip() == "" and len(gap) <= 3

    def _accents_agree(self, ws: Sequence[str], sure: bool) -> bool:
        """An accented word matches a syllable seen with those accents; an
        unaccented one matches any. A sure name seen only unaccented takes
        any accents; a guess, none."""
        for w in ws:
            if _plain(w):
                continue
            seen = self._tones.get(key(w))
            if seen is None:
                if not sure:
                    return False
            elif _toned(w) not in seen:
                return False
        return True

    def _shaped(self, ws: Sequence[str]) -> bool:
        """A guess found again: one casing, and no accented lower case."""
        casings = {_case(w) for w in ws}
        return len(casings) == 1 and (casings != {"lower"} or all(_plain(w) for w in ws))

    def _match(self, text, words, keys, i) -> tuple[int, str] | None:
        for seq, canon in self.full.get(keys[i], ()):
            n = len(seq)
            if tuple(keys[i:i + n]) == seq and self._joined(text, words, i, n):
                ws = [w.group() for w in words[i:i + n]]
                sure = seq not in self._guess
                if not self._accents_agree(ws, sure) or not (sure or self._shaped(ws)):
                    continue
                return n, canon
        if i + 1 < len(words) and (keys[i], keys[i + 1]) in self.pair \
                and self._joined(text, words, i, 2) \
                and _case(words[i].group()) in ("title", "caps") \
                and _case(words[i + 1].group()) == _case(words[i].group()):
            names = self.pair[(keys[i], keys[i + 1])]
            return 2, next(iter(names)) if len(names) == 1 else ""
        if i > 0 and _is_cue(words[i - 1].group()) \
                and text[words[i - 1].end():words[i].start()].strip(" .") == "":
            for n in (2, 1):
                if i + n > len(words):
                    continue
                names = self.short.get(tuple(keys[i:i + n]))
                if names and self._joined(text, words, i, n) and self._accents_agree(
                        [w.group() for w in words[i:i + n]],
                        any(self._sure(c) for c in names)):
                    return n, next(iter(names)) if len(names) == 1 else ""
        return None

    def _sure(self, canon: str) -> bool:
        return tuple(key(w) for w in _WORD.findall(canon)) not in self._guess


# -- layer 4: residue --------------------------------------------------------------

def residue_names(text: str) -> Iterator[tuple[int, int]]:
    """Name-shaped runs in text that is about to leave: broader than what the
    redaction dares to treat, because a hit here stops the document for a
    human instead of changing it.

    * a capitalised run of two to four words led by any surname, accents or
      not (``Ha Van``, ``Mai Anh Tuan``);
    * a capitalised run of three or four words that are all name syllables;
    * a lowercase run of three or four words, a surname and then name
      syllables (``phan bao hoa``).
    """
    words = _words(text)
    for a, b, casing in _runs(text, words):
        run = [w.group() for w in words[a:b + 1]]
        folded = [key(w) for w in run]
        if casing in ("title", "caps"):
            if not 2 <= len(run) <= 4 or _after_place(text, words, a):
                continue
            if any(w.casefold() in NAME_STOP or w in _LEAD_STOP
                   or w.casefold() in _THING_AFTER for w in run[1:]):
                continue
            led = _surname(run[0], loose=True)
            lexical = len(run) >= 3 and all(w in MIDDLE or w in GIVEN for w in run)
        elif casing == "lower":
            if not 3 <= len(run) <= 4:
                # A longer lowercase run is a sentence; look at its windows.
                for j in range(a, b - 1):
                    w3 = [x.group() for x in words[j:j + 3]]
                    if _surname(w3[0], loose=True) \
                            and all(x in MIDDLE or x in GIVEN for x in w3[1:]) \
                            and not _nonname_prefix([key(x) for x in w3]) \
                            and not _compound(w3):
                        yield words[j].start(), words[j + 2].end()
                continue
            led = _surname(run[0], loose=True) and all(
                w in MIDDLE or w in GIVEN for w in run[1:])
            lexical = False
            if _compound(run):
                continue
        else:
            continue
        if not (led or lexical) or _nonname_prefix(folded):
            continue
        yield words[a].start(), words[b].end()


def _compound(run: list[str]) -> bool:
    ks = [key(w) for w in run]
    return any(f"{x} {y}" in _MID_NEXT_NOT or f"{x} {y}" in _MID_PREV_NOT
               for x, y in zip(ks, ks[1:]))
