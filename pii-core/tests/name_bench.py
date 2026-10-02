"""A synthetic benchmark for person-name detection.

Every name is generated here, at run time, from syllable pools; no document
or value comes from a client. Run it directly for the table:

    uv run python tests/name_bench.py            # after: the current code
    PYTHONPATH=<old src>:tests python tests/name_bench.py   # before

A **mention** is caught when every letter of it lies inside a span the
redaction treated (any action but KEEP). A **negative** is a phrase that must
reach the agent intact: a street or school named after a person, a place, a
heading, an everyday word that starts with a surname syllable. It counts as
a false positive when any letter of it is treated as PERSON.

The pools are split on purpose. Surnames come in three kinds: the common
sixteen, rarer real ones, and invented syllables no lexicon holds. Given
names are reported by whether the detector's own lexicon holds them, so a
recall number cannot hide that it only works on names it already knew.
"""
from __future__ import annotations

import random
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

SEED = 20260923
N_CASES = 80
KEY = "synthetic-test-key-not-a-secret"

SURNAME_COMMON = ("Nguyễn Trần Lê Phạm Hoàng Huỳnh Phan Vũ Võ Đặng Bùi Đỗ Hồ Ngô "
                  "Dương Lý").split()
SURNAME_RARE = "Ung Lã Mẫn Thân Ninh Bạch Đàm Diệp Lục Tiêu Doãn Khúc Hàn Kha".split()
SURNAME_INVENTED = "Thử Mẫu Cấu Giả".split()
MIDDLE_M = "Văn Hữu Đức Quang Minh Công Gia Xuân".split()
MIDDLE_F = "Thị Ngọc Thu Diệu Kim Thanh Bảo".split()
GIVEN_M = ("An Bình Cường Dũng Hải Hiếu Hùng Huy Khang Khiêm Long Nam Phong Quân "
           "Sơn Tài Thắng Toàn Trung Tuấn Vinh Toản Chiến Lộc Nhân Định Mẫu Cấu").split()
GIVEN_F = ("Anh Châu Diễm Giang Hà Hạnh Hằng Hoa Hương Khuê Lan Linh Loan Luyến "
           "Mai Nga Nhàn Nhung Oanh Phương Quỳnh Thảo Thục Trang Uyên Vy Yến Thử").split()
WEST_FIRST = ("John Mary David Sarah Michael Emma Robert Laura Peter Anna "
              "Thaddeus Ottoline Leofric Birgit").split()
WEST_LAST = "Placeholder Example Sample Fixture Testwell Mockford Dummyson".split()

MALE_CUES = ("anh", "ông", "chú", "bác")
FEMALE_CUES = ("chị", "bà", "cô")

STREETS = ("Lê Lợi", "Trần Hưng Đạo", "Nguyễn Huệ", "Nguyễn Trãi", "Lý Thường Kiệt",
           "Hai Bà Trưng", "Võ Văn Tần", "Phan Chu Trinh", "Đinh Tiên Hoàng")
NEGATIVE_TEMPLATES = (
    *(f"Văn phòng nằm trên đường {{{s}}} gần chợ." for s in STREETS),
    *(f"Chúng tôi gặp nhau ở phố {{{s}}} hôm qua." for s in STREETS[:4]),
    *(f"Chi nhánh đặt tại {{{p}}} từ năm ngoái." for p in (
        "Hà Nội", "Thành phố Hồ Chí Minh", "Hà Giang", "Cao Bằng", "Lâm Đồng",
        "Phan Thiết", "Đồng Nai", "Bình Dương", "Thanh Hóa", "Hải Dương",
        "Quảng Ninh", "Hà Lan", "Hoa Kỳ", "Bà Rịa", "Hà Tĩnh", "Long An",
        "Việt Nam", "Tân Bình", "Ninh Bình", "Hàn Quốc")),
    "Học sinh {Trường THPT Nguyễn Du} tham gia cuộc thi.",
    "Kết quả xét nghiệm từ {Bệnh viện Bạch Mai} được đính kèm.",
    "Đơn được gửi tới {Cục Sở hữu trí tuệ} trong tuần.",
    "Vụ việc thuộc thẩm quyền của {Tòa án nhân dân Thành phố Hà Nội}.",
    "Công văn của {Bộ Khoa học và Công nghệ} đã có.",
    "Hội thảo tại {Trung Tâm Hội Nghị Quốc Gia} tuần sau.",
    "Nhà máy đặt ở {Khu Công Nghiệp Tân Bình}.",
    "Giảng viên {Đại Học Quốc Gia Hà Nội} được mời.",
    "Nghỉ lễ dịp {Ngày Quốc Khánh}.", "Tra cứu {Hệ Thống Văn Bản Pháp Luật}.",
    "Họp tại {chợ Bà Chiểu} lúc chín giờ.",
    "{Hồ sơ} gồm ba bản chính.", "{Lý do} nộp đơn đã nêu ở trên.",
    "{Phạm vi} bảo hộ không đổi.", "{Đào tạo} nhân viên là nghĩa vụ của bên B.",
    "{Tôn trọng} quyền của chủ sở hữu.", "{Cao cấp} là phân khúc của sản phẩm.",
    "{Lương cơ bản} không thuộc phạm vi hợp đồng.", "{Dương lịch} được dùng trong văn bản.",
    "Hai bên thống nhất {văn bản} này.", "Giá {thị trường} biến động mạnh.",
    "Cần {minh bạch} về chi phí.", "Bảo đảm {an toàn} thông tin.",
    "Mọi việc vẫn {bình thường}.", "Thủ tục {hải quan} mất hai ngày.",
    "Đề xuất {phương án} xử lý.", "Bên B cam kết {trung thực}.",
    "Tin đồn {lan truyền} nhanh.", "Quyết định {thu hồi} văn bằng.",
    "mức {lương thị trường} tăng.", "đây là {hoàng gia anh} xưa.",
    "sản phẩm đạt {tiêu chuẩn} quốc tế.", "hai bên {đàm phán} lại giá.",
    "{QUYẾT ĐỊNH}", "{GIẤY ỦY QUYỀN}", "{BIÊN BẢN BÀN GIAO}",
    "{THÔNG BÁO KẾT QUẢ THẨM ĐỊNH}", "{PHỤ LỤC HỢP ĐỒNG}", "{TIÊU CHUẨN KỸ THUẬT}",
    "{CHẾ ĐỘ BẢO HÀNH}", "{QUAN HỆ HỢP ĐỒNG}",
    "Theo {Luật Sở hữu trí tuệ} hiện hành.", "Áp dụng {Bộ luật Dân sự} năm 2015.",
    "Tên nhãn hiệu: {KIM LONG}", "Tên nhãn hiệu: {HOA SEN VÀNG}",
    "Tên nhãn hiệu: {Minh Anh}",
    "The {United States Patent and Trademark Office} issued it.",
    "We received an {Office Action} last week.", "{Dear Sir or Madam},",
    "Priority is claimed under the {Paris Convention}.",
    "It was filed through the {Madrid Protocol}.", "{Best regards},",
    "Hạn chót là cuối {Tháng Mười}.",
    "Tài liệu viết bằng {tiếng Anh} và tiếng Việt.",
    "Thương hiệu {Minh Long} bán gốm sứ.", "{Thu Bồn} là tên một dòng sông.",
    "Bản dịch {tiếng Anh Mỹ} đính kèm.", "Hãng bay của {Anh Quốc} đã xác nhận.",
)


# The held-out suite. Written after the detector was frozen and never tuned
# against: rarer real surnames the lexicon lacks (Vi, Phí, Kha, Mạch, Quản,
# Nhan and Phó are left out of it on purpose), given and Western names it
# lacks, and negatives of the same kinds but none of the same phrases.
HOLDOUT = dict(
    common=SURNAME_COMMON,
    rare="Khiếu Lỗ Bành Lạc Thang Chung Lều Đậu Vi Phí Kha Mạch Quản Nhan Phó".split(),
    invented="Thí Khảo Nghiệm Phỏng".split(),
    middle_m="Văn Hữu Đình Sỹ Khắc Viết Trọng Tùng Duy Bá".split(),
    middle_f="Thị Ngọc Bích Ánh Diễm Mộng Tường Hải".split(),
    given_m=("Toản Quyết Khuyến Trác Nhượng Sĩ Lạng Mừng Chương Diễn Hoạch Thiêm "
             "Khởi Bổng Tụng Luyện Khang Phong Tuấn Hùng").split(),
    given_f=("Luyến Thục Khuê Nhạn Đoan Thoa Hiên Mơ Lụa Nhài Gấm Thắm Hoa Lan "
             "Yến Trinh").split(),
    west_first=("Thaddeus Ottoline Leofric Birgit Ingrid Casimir Wilhelmina Rupert "
                "Anneliese Bartholomew Ignatius Seraphina").split(),
    west_last="Fakeworth Trialson Mockley Exemplar Draftwood".split(),
    negatives=(
        "Văn phòng mới ở đường {Nguyễn Thị Minh Khai} quận 3.",
        "Xe đi theo đường {Điện Biên Phủ} rồi rẽ phải.",
        "Học sinh trường {Lê Văn Tám} đạt giải nhất.",
        "Qua cầu {Chương Dương} là tới kho.", "Hẹn ở {Công viên Lê Thị Riêng}.",
        "Chuyến bay hạ cánh ở {Sân bay Tân Sơn Nhất}.", "Tham quan {Bến Nhà Rồng}.",
        "Trụ sở ở quận {Phú Nhuận}.", "Chi nhánh ở phường {Bến Nghé}.",
        "Nhà máy ở tỉnh {Kiên Giang}.", "Kho hàng ở huyện {Củ Chi}.",
        "Chụp ảnh trước {Nhà thờ Đức Bà}.", "Cửa hàng gần chợ {Bến Thành}.",
        "Đề nghị {lưu ý thêm} điều khoản này.", "Bên B giữ {hồ sơ gốc} của đơn.",
        "Cần xác định {phạm vi bảo hộ} rõ ràng.", "Khách phàn nàn về {thái độ phục vụ}.",
        "Chế độ {lương hưu trí} theo luật.", "Báo cáo {triệu chứng lâm sàng} kèm theo.",
        "Dự báo {tăng trưởng kinh tế} năm tới.", "Nhập khẩu {cao su thiên nhiên}.",
        "Chương trình {đào tạo nghề} miễn phí.", "Cần nêu {lý do chính đáng} trong đơn.",
        "Ảnh chụp lúc {hoàng hôn buông} xuống.", "Giữ {đoàn kết nội bộ} là ưu tiên.",
        "Sửa {trần nhà cao} ở tầng hai.", "Tài liệu {vũ trụ học} bằng tiếng Việt.",
        "Khu {đỗ xe tạm} ở cổng sau.", "Kết quả {dương tính giả} đã được loại.",
        "{Hợp Đồng Dịch Vụ Pháp Lý}", "{Thông Tin Liên Hệ}", "{Phương Án Kinh Doanh}",
        "{Quy Trình Thẩm Định}", "{Lương Thưởng Cuối Năm}", "Dạo quanh {Hồ Tây}.",
        "Cuộc thi {Vũ Điệu Thanh Xuân} đã kết thúc.", "{Đào Tạo Nội Bộ}",
        "{PHẠM VI CÔNG VIỆC}", "{LƯU Ý QUAN TRỌNG}", "{HOÀNG GIA}",
        "Du lịch {Lễ Hội Chùa Hương}.", "Ảnh chụp ở {Cao Nguyên Đá Đồng Văn}.",
        "Nghỉ {Tết Nguyên Đán} một tuần.", "Mua sữa {Mộc Châu} cho văn phòng.",
        "Nước mắm {Phú Quốc} được bảo hộ chỉ dẫn địa lý.", "Loại gạo {Tám Thơm}.",
        "Trà {Thái Nguyên} làm quà.", "Nhãn hiệu {Hồng Hà} nổi tiếng.",
        "Đặt mua bút bi {Thiên Long}.",
        "A {Grace Period} applies to the fee.", "Our {Madison Avenue} office replied.",
        "The ship docked at {Victoria Harbour}.", "The {Austin Office} replied.",
        "Appeal to the {Georgia Court of Appeals}.", "Water from the {Jordan River}.",
        "Lunch at {Chelsea Market}.", "{Kind Regards},", "{Sincerely Yours},",
        "Filed with the {Trademark Trial and Appeal Board}.",
        "Goods follow the {Nice Classification}.", "Filed under the {Hague Agreement}.",
    ),
)
DEV = dict(common=SURNAME_COMMON, rare=SURNAME_RARE, invented=SURNAME_INVENTED,
           middle_m=MIDDLE_M, middle_f=MIDDLE_F, given_m=GIVEN_M, given_f=GIVEN_F,
           west_first=WEST_FIRST, west_last=WEST_LAST, negatives=NEGATIVE_TEMPLATES)
SUITES = {"dev": (SEED, DEV), "holdout": (SEED + 1, HOLDOUT)}

def fold(s: str) -> str:
    s = s.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


@dataclass
class Person:
    surname: str
    middle: list[str]
    given: list[str]
    female: bool
    western: bool = False
    surname_kind: str = "common"

    @property
    def full(self) -> str:
        if self.western:
            return f"{self.given[0]} {self.surname}"
        return " ".join([self.surname, *self.middle, *self.given])

    @property
    def call(self) -> str:
        """How a colleague addresses them: the given name (last syllable)."""
        return self.surname if self.western else self.given[-1]


@dataclass
class Doc:
    kind: str
    parts: list[str] = field(default_factory=list)
    mentions: list[tuple[int, int, str, Person]] = field(default_factory=list)
    negatives: list[tuple[int, int, str]] = field(default_factory=list)
    _len: int = 0

    def add(self, s: str) -> None:
        self.parts.append(s)
        self._len += len(s)

    def mention(self, before: str, name: str, after: str, form: str, p: Person) -> None:
        self.add(before)
        self.mentions.append((self._len, self._len + len(name), form, p))
        self.add(name)
        self.add(after)

    def negative(self, template: str) -> None:
        pre, rest = template.split("{", 1)
        phrase, post = rest.split("}", 1)
        self.add(pre)
        self.negatives.append((self._len, self._len + len(phrase), phrase))
        self.add(phrase)
        self.add(post + "\n")

    @property
    def text(self) -> str:
        return "".join(self.parts)


def _person(rng: random.Random, P: dict, western: bool = False) -> Person:
    if western:
        return Person(rng.choice(P["west_last"]), [], [rng.choice(P["west_first"])],
                      False, True, "western")
    kind = rng.choices(("common", "rare", "invented"), (6, 3, 1))[0]
    female = rng.random() < 0.5
    middle = [rng.choice(P["middle_f"] if female else P["middle_m"])]
    given = [rng.choice(P["given_f"] if female else P["given_m"])]
    if female and rng.random() < 0.25:
        given.insert(0, rng.choice(("Thu", "Ngọc", "Minh", "Thanh")))
    return Person(rng.choice(P[kind]), middle, given, female, False, kind)


def make_case(rng: random.Random, i: int, P: dict = DEV) -> list[Doc]:
    people = [_person(rng, P), _person(rng, P)]
    west = _person(rng, P, western=True)
    a, b = people

    form = Doc("form")
    form.add("HỢP ĐỒNG DỊCH VỤ PHÁP LÝ\n")
    form.mention("Họ và tên: ", a.full, "\n", "label", a)
    form.add("Ngày sinh: 12/04/1985\n")
    form.mention("Người liên hệ: ", b.full, "\n", "label", b)
    form.mention("Applicant name: ", west.full, "\n", "label", west)

    letter = Doc("letter")
    negs = rng.sample(P["negatives"], 5)
    cue_a = rng.choice(FEMALE_CUES if a.female else MALE_CUES)
    cue_b = rng.choice(FEMALE_CUES if b.female else MALE_CUES)
    hon = "Bà" if a.female else "Ông"
    letter.mention(f"Kính gửi {hon} ", a.full, ",\n", "honorific", a)
    letter.negative(negs[0])
    letter.mention("Hợp đồng do ", b.full, " ký ngày 05/03/2024.\n", "bare_title", b)
    letter.negative(negs[1])
    letter.mention("Theo đề nghị của Giám đốc ", a.full, ", chúng tôi gửi lại hồ sơ.\n",
                   "role_cue", a)
    letter.mention(f"Bản sao đã gửi cho {cue_b} ", b.call, " qua bưu điện.\n",
                   "given_after_cue", b)
    letter.negative(negs[2])
    letter.mention("", west.full, " confirmed the instructions by phone.\n",
                   "western_bare", west)
    title = rng.choice(("Mr", "Ms", "Dr"))
    letter.mention(f"We will copy {title} ", west.surname, " on the reply.\n",
                   "western_title_surname", west)
    letter.add("ĐẠI DIỆN BÊN A\n(ký, ghi rõ họ tên)\n\n")
    letter.mention("", a.full.upper(), "\n", "caps_signature", a)

    chat = Doc("chat")
    chat.mention("tin nhắn: tôi là ", b.full.lower(), ", xin xác nhận lại lịch hẹn.\n",
                 "lower_accented", b)
    chat.negative(negs[3])
    chat.mention("Cam on, ", fold(a.full), " se gui lai ban scan.\n",
                 "unaccented_title", a)
    chat.mention("ho ten: ", fold(b.full).lower(), "\n", "unaccented_lower_labelled", b)
    chat.mention("gọi lại cho ", fold(a.full).lower(), " trước thứ sáu.\n",
                 "unaccented_lower", a)
    chat.negative(negs[4])
    chat.mention(f"{cue_a.capitalize()} ", a.call, " nhắn là đã nhận được.\n",
                 "given_after_cue", a)
    return [form, letter, chat]


def make_controls(rng: random.Random, n: int, P: dict = DEV) -> list[Doc]:
    """Documents with no person in them at all: every block is a false block."""
    out = []
    for _ in range(n):
        d = Doc("control")
        for t in rng.sample(P["negatives"], 6):
            d.negative(t)
        out.append(d)
    return out


def build(suite: str = "dev", n_cases: int = N_CASES) -> tuple[list[list[Doc]], list[Doc]]:
    seed, P = SUITES[suite]
    rng = random.Random(seed)
    return [make_case(rng, i, P) for i in range(n_cases)], make_controls(rng, n_cases, P)


# -- scoring -------------------------------------------------------------------

def _covered(spans: list[tuple[int, int]], s: int, e: int, text: str) -> str:
    letters = [k for k in range(s, e) if text[k].isalpha()]
    inside = sum(1 for k in letters if any(a <= k < b for a, b in spans))
    return "caught" if inside == len(letters) else "partial" if inside else "missed"


def _treated(result, person_only: bool = False) -> list[tuple[int, int]]:
    return [(f.start, f.end) for f in result.fields if f.action != "KEEP"
            and (not person_only or f.category == "PERSON")]


def _is_name_residue(result) -> bool:
    return any(str(r.get("matched_by", "")).startswith("residue:name")
               for r in result.residue)


def evaluate(mode: str, cases, controls, policy) -> dict:
    import pii_core
    from pii_core import redact_document

    by_form: dict[str, Counter] = defaultdict(Counter)
    by_kind: dict[str, Counter] = defaultdict(Counter)
    lexicon, west = _lexicon()
    fp = Counter()
    blocks = Counter()

    def results_for(docs: list[Doc], group: str):
        if mode == "doc":
            return [redact_document(d.text, policy, group=group) for d in docs]
        if mode == "case-sequential":
            out, vault = [], None
            for d in docs:
                r = redact_document(d.text, policy, group=group, vault=vault)
                vault = r.vault
                out.append(r)
            return out
        if mode in ("case", "case-unlabelled"):
            return pii_core.redact_case([d.text for d in docs], policy, group=group)
        raise ValueError(mode)

    for i, docs in enumerate(cases):
        if mode == "case-unlabelled":          # no form: no name is ever labelled
            docs = docs[1:]
        for d, r in zip(docs, results_for(docs, f"BENCH-{i}")):
            spans = _treated(r)
            leaked = False
            for s, e, form, p in d.mentions:
                verdict = _covered(spans, s, e, d.text)
                by_form[form][verdict] += 1
                kind = p.surname_kind
                if p.western:
                    kind += "/first-in-lexicon" if p.given[0].casefold() in west \
                        else "/first-held-out"
                else:
                    kind += "/given-in-lexicon" if all(
                        g in lexicon for g in p.given) else "/given-held-out"
                by_kind[kind][verdict] += 1
                leaked |= verdict != "caught"
            pspans = _treated(r, person_only=True)
            for s, e, _ in d.negatives:
                fp["negatives"] += 1
                fp["person_fp"] += _covered(pspans, s, e, d.text) != "missed"
                fp["any_fp"] += _covered(spans, s, e, d.text) != "missed"
            key = "leaky" if leaked else "clean"
            blocks[key] += 1
            blocks[f"{key}_name_flag"] += _is_name_residue(r)
            blocks[f"{key}_blocked"] += not r.summary["ok"]
    for j, d in enumerate(controls):
        r = redact_document(d.text, policy, group=f"CTRL-{j}")
        pspans = _treated(r, person_only=True)
        spans = _treated(r)
        for s, e, _ in d.negatives:
            fp["negatives"] += 1
            fp["person_fp"] += _covered(pspans, s, e, d.text) != "missed"
            fp["any_fp"] += _covered(spans, s, e, d.text) != "missed"
        blocks["control"] += 1
        blocks["control_blocked"] += not r.summary["ok"]
        blocks["control_name_flag"] += _is_name_residue(r)
    return {"by_form": by_form, "by_kind": by_kind, "fp": fp, "blocks": blocks}


def _lexicon():
    try:
        from pii_core.names import GIVEN, WEST_GIVEN
    except ImportError:                      # the code before the name layers
        return frozenset(), frozenset()
    return GIVEN, WEST_GIVEN


def _rate(c: Counter) -> str:
    n = sum(c.values())
    return f"{c['caught'] / n:6.1%} ({c['caught']}/{n}, partial {c['partial']})" if n else "-"


def report(result: dict) -> str:
    lines = []
    total = Counter()
    for form, c in sorted(result["by_form"].items()):
        lines.append(f"  {form:28s} {_rate(c)}")
        total.update(c)
    lines.append(f"  {'ALL MENTIONS':28s} {_rate(total)}")
    lines.append("  by surname / given:")
    for kind, c in sorted(result["by_kind"].items()):
        lines.append(f"    {kind:34s} {_rate(c)}")
    fp, b = result["fp"], result["blocks"]
    lines.append(f"  negatives treated as PERSON: {fp['person_fp']}/{fp['negatives']}"
                 f"  (any treatment: {fp['any_fp']})")
    lines.append(f"  leaky docs blocked: {b['leaky_blocked']}/{b['leaky']}"
                 f" (name residue {b['leaky_name_flag']});"
                 f" clean docs blocked: {b['clean_blocked']}/{b['clean']};"
                 f" control docs blocked: {b['control_blocked']}/{b['control']}")
    return "\n".join(lines)


def main(argv: list[str]) -> None:
    import pii_core
    from pii_core import Policy
    policy = Policy(KEY)
    suites = [a for a in argv if a in SUITES] or list(SUITES)
    without = {a[1:] for a in argv if a.startswith("-")}
    if without:                                # ablation: -cues -propagation ...
        from pii_core import names
        names.LAYERS -= without
    modes = [a for a in argv if a not in SUITES and not a.startswith("-")] or \
        ["doc", "case-sequential"] + (["case", "case-unlabelled"]
                                      if hasattr(pii_core, "redact_case") else [])
    for suite in suites:
        cases, controls = build(suite)
        for mode in modes:
            off = f", without {sorted(without)}" if without else ""
            print(f"== {suite} / mode {mode}{off}  (pii_core from {Path(pii_core.__file__).parent})")
            print(report(evaluate(mode, cases, controls, policy)))


if __name__ == "__main__":
    main(sys.argv[1:])
