"""The register: one row per category of information, with L and its basis.

Ported from pii-lab (`src/pii_lab/categories.py`, branch fm/pii-decision-lab),
which is the source of truth for this package. The rules carried over intact:

* ``leak_harm`` (L) is a lookup into a **cited instrument**, never a score by
  feel. Disagreeing means reading the article in ``leak_harm_basis``.
* ``need`` (N) and ``action`` are **not stored here**. N is derived from the
  measured evidence in ``data/evidence.json`` and the action from
  ``risk = R x L`` then N, in :mod:`pii_core.decide`.
* ``identifies_a_person`` is structural; R is a frequency. They are different
  claims, which is why L — not R — zeroes the risk of a public value.

Four categories are new relative to pii-lab: ``BOILERPLATE``, adopted from
ocr-lab's ``quoc_hieu`` row; ``MARK``, the firm's 2026-09-23 decision that a
mark name leads to its applicant; and ``HOTLINE`` and ``MACHINE_TRACE``, the
two kinds of number the 2026-09-24 dry run found blocking the gate — a
published switchboard that must stay readable, and an e-seal or transaction
code that must not. See ``docs/RECONCILIATION.md``.

The firm's rulings of 2026-09-28 (the pipeline report, §2.3 and §6) add more:
``BIRTH_DATE`` split out of ``DATE``; ``AGENCY`` beside ``PARTY``, both now
tokenised; and the six things that stand only on a page image (portrait,
signature, fingerprint, QR code, figurative mark, logo), whose rows carry
``image=True``. pii-core never finds those itself; the caller that masks a
page image (ocr-lab) reads their action from the same table.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

__all__ = ["Harm", "BasisKind", "Category", "CATEGORIES", "BY_CODE", "category"]


class Harm(IntEnum):
    """L — harm if leaked. Coarse on purpose; every step names its authority."""

    NONE = 0
    """Already public, or published by a register."""
    INTERNAL = 1
    """The firm's own operational trace. Embarrassing to lose, not reportable."""
    PERSONAL = 2
    """Personal data, or information a lawyer is bound to keep about a client."""
    SENSITIVE = 3
    """Sensitive personal data, or a value the firm declared commercially
    sensitive in its own right."""


class BasisKind(IntEnum):
    """Where an L score comes from. ``PROPOSED`` means no instrument speaks and
    the firm has not ruled; such rows still decide, but are marked."""

    DECREE = 0
    STATUTE = 1
    FIRM_STATED = 2
    PUBLIC_RECORD = 3
    PROPOSED = 4


# NOT LEGAL ADVICE. These are pii-lab's proposed classifications; the firm
# confirms or overrules them, one cited article at a time.
ND13 = "Nghị định 13/2023/NĐ-CP"
LLS = "Luật Luật sư 2006 (sđ. 2012)"

_ND13_BASIC = f"{ND13} Điều 2.3 — dữ liệu cá nhân cơ bản"
_LLS_SECRET = f"{LLS} Điều 25 — bí mật thông tin khách hàng"
_ND13_BIRTH = f"{ND13} Điều 2.3(b) — ngày, tháng, năm sinh, chết hoặc mất tích"
_ND13_PLACE = (f"{ND13} Điều 2.3(d) — nơi sinh, nơi thường trú, nơi ở, quê quán, "
               "địa chỉ liên hệ")
_ND13_ACCOUNT = (f"{ND13} Điều 2.4(h) — thông tin tài khoản của khách hàng tổ chức "
                 "tín dụng")
_ND13_IMAGE = f"{ND13} Điều 2.3(e) — hình ảnh của cá nhân"
_ND13_BIOMETRIC = (f"{ND13} Điều 2.4(đ) — thuộc tính vật lý, đặc điểm sinh học "
                   "riêng của cá nhân")
#: The firm's rulings on the pipeline report, 2026-09-28.
_RULED = "văn phòng chốt 2026-09-28 (báo cáo pipeline OCR → PII → kho, §2.3, §6)"


@dataclass(frozen=True, slots=True)
class Category:
    code: str
    title: str
    identifies_a_person: bool
    leak_harm: Harm
    leak_harm_basis: str
    basis_kind: BasisKind
    note: str = ""
    #: Stands only on a page image; no text detector ever produces it.
    image: bool = False

    @property
    def settled(self) -> bool:
        """False when L is a proposal rather than an authority's reading."""
        return self.basis_kind is not BasisKind.PROPOSED


CATEGORIES: tuple[Category, ...] = (
    # ---- directly identifying people -------------------------------------
    Category("PERSON", "Tên người", True,
             Harm.PERSONAL, _ND13_BASIC, BasisKind.DECREE,
             "Điều 2.3 gọi tên thẳng 'họ, chữ đệm và tên khai sinh'; tên khách "
             f"hàng còn được phủ bởi {_LLS_SECRET}."),
    Category("ADDRESS", "Địa chỉ bưu chính", True,
             Harm.PERSONAL, _ND13_BASIC, BasisKind.DECREE,
             "Điều 2.3: nơi thường trú, tạm trú, nơi ở hiện tại, địa chỉ liên hệ."),
    Category("EMAIL", "Địa chỉ email", True,
             Harm.PERSONAL, _ND13_BASIC, BasisKind.DECREE,
             "Dữ liệu liên hệ; thường có dạng ho.ten@... nên mang theo cả tên."),
    Category("PHONE", "Số điện thoại", True,
             Harm.PERSONAL, _ND13_BASIC, BasisKind.DECREE,
             "'số điện thoại', được gọi tên ở Điều 2.3."),
    Category("NATIONAL_ID", "Số căn cước công dân (CCCD/CMND)", True,
             Harm.SENSITIVE, _ND13_BASIC, BasisKind.DECREE,
             "Nghị định xếp vào cơ bản (L = 2); pii-lab nâng lên 3 công khai vì "
             "một số CCCD tự nó tái định danh trên toàn dân số và không cấp lại "
             "được."),
    Category("MRZ", "Vùng máy đọc của hộ chiếu / CCCD (MRZ)", True,
             Harm.SENSITIVE, _ND13_BASIC, BasisKind.DECREE,
             "Lấy từ ocr-lab. Cả trang nhân thân (họ tên, số hộ chiếu, ngày sinh) "
             "nén trong hai dòng: đều là dữ liệu cơ bản của Điều 2.3, nâng lên 3 "
             "như NATIONAL_ID. Không có nhu cầu nghiệp vụ nào đọc nó, nên REMOVE."),
    Category("TAX_CODE", "Mã số thuế / số ĐKKD", True,
             Harm.PERSONAL, _ND13_BASIC, BasisKind.DECREE,
             "Điều 2.3 nêu mã số thuế của CÁ NHÂN. Gộp cả số ĐKKD (ocr-lab tách "
             "riêng dòng 'dkkd'; ở đây là cùng một hạng mục)."),

    # ---- identifying an organisation -------------------------------------
    Category("ORG", "Tên tổ chức (phía khách hàng)", True,
             Harm.PERSONAL, _LLS_SECRET, BasisKind.STATUTE,
             "Nghị định không với tới pháp nhân; nghĩa vụ bảo mật của luật sư thì "
             "có. Đối tác/đối lập đã công khai thuộc PARTY, theo roster."),

    # ---- on a public record already --------------------------------------
    Category("PARTY", "Đối phương: đương sự, luật sư phía đối lập", True,
             Harm.PERSONAL, _LLS_SECRET, BasisKind.STATUTE,
             "Chỉ qua roster (danh sách do văn phòng cung cấp), không bao giờ "
             "theo suy đoán. Tên đối phương có trên hồ sơ công khai, nhưng việc "
             "văn phòng đại diện ai chống ai là thông tin về vụ việc, và đối "
             f"phương có thể là một cá nhân. Trước khi {_RULED} (P2), hàng này "
             "là L = 0 và KEEP."),
    Category("AGENCY", "Cơ quan: Cục SHTT, USPTO, toà án, công chức ký thay",
             True, Harm.INTERNAL, _LLS_SECRET, BasisKind.STATUTE,
             "Chỉ qua roster. Danh tính cơ quan là công khai; điều không công "
             "khai là hồ sơ này đang nằm ở cơ quan nào: cơ quan cộng ngày nộp "
             "và nhãn hiệu là tra ra đơn, tức ra khách (như APP_SERIAL). "
             f"{_RULED} (P2): bí danh hoá cả cơ quan lẫn đối phương. Token vẫn "
             "cho biết hai văn bản đến từ CÙNG một cơ quan; bước nào cần biết "
             "là cơ quan nào thì chạy trong vùng tin cậy, sau khi giải token."),
    Category("FIRM", "Danh tính của chính văn phòng", True,
             Harm.NONE, "danh tính do chính văn phòng công bố",
             BasisKind.PUBLIC_RECORD),
    Category("HOTLINE", "Tổng đài đã công bố", False,
             Harm.NONE, "số tổng đài do chính cơ quan hoặc doanh nghiệp công bố",
             BasisKind.PUBLIC_RECORD,
             f"{ND13} Điều 2.3 nói 'số điện thoại' của CÁ NHÂN. Đầu số tổng "
             "đài (1900/1800 ở Việt Nam, các đầu số miễn cước 800/833/844/855/"
             "866/877/888 ở Hoa Kỳ) được cấp cho một tổ chức và in trên chính "
             "trang của tổ chức đó; che nó đi thì luật sư không gọi được ai. "
             "Chỉ nhận qua đầu số dành riêng, không bao giờ theo suy đoán — "
             "một số di động vẫn là PHONE."),

    # ---- the firm's own commercial position ------------------------------
    Category("MONEY", "Số tiền", False,
             Harm.SENSITIVE, "văn phòng tự xác định (bảng phí mang cả basecost "
             "lẫn margin), ghi trong neo_legal_swift pseudonymise.py",
             BasisKind.FIRM_STATED),

    # ---- operational trace of the firm -----------------------------------
    Category("MATTER_REF", "Số hiệu hồ sơ nội bộ", False,
             Harm.INTERNAL, "định danh vận hành; không điều khoản nào chạm tới",
             BasisKind.PROPOSED,
             "Vô nghĩa với người ngoài, nhưng là khoá nối giữa các tài liệu. Tiền "
             "tố của mã lộ loại việc và nơi nộp, không lộ khách hàng."),
    Category("MACHINE_TRACE", "Dấu vết máy (mã đóng dấu điện tử, mã giao dịch)",
             False, Harm.INTERNAL,
             "dấu vết vận hành của hệ thống; không điều khoản nào chạm tới",
             BasisKind.PROPOSED,
             "Mã e-seal của đăng bạ mang theo địa chỉ IP và mốc thời gian nộp "
             "đơn; mã giao dịch thẻ trỏ về một lần thanh toán. Không phép đo "
             "nào cần đọc lại chúng, nên không mua khả năng hoàn nguyên: thay "
             "bằng nhãn lớp. Trước 2026-09-24 chúng rơi vào lưới rà số của "
             "document.RESIDUE_DIGITS và chặn cả tài liệu."),
    Category("SOURCE_FILE", "Tên tệp gốc", True,
             Harm.PERSONAL, _LLS_SECRET, BasisKind.STATUTE,
             "Tên tệp thường nhúng mã và tên khách hàng."),

    # ---- published register data -----------------------------------------
    Category("APP_SERIAL", "Số đơn / số serial", False,
             Harm.INTERNAL, _LLS_SECRET, BasisKind.STATUTE,
             "Đăng bạ công bố số đơn, nhưng tra số đơn là ra chủ đơn, tức là "
             "khách hàng. Quan hệ luật sư – khách hàng ở giai đoạn trước khi nộp "
             "và nội dung tư vấn thì không công khai (văn phòng quyết định "
             "2026-09-23). Token giữ liên kết giữa các tài liệu; tra đăng bạ thì "
             "giải token tại chỗ."),
    Category("REG_NUMBER", "Số đăng bạ", False,
             Harm.INTERNAL, _LLS_SECRET, BasisKind.STATUTE,
             "Như APP_SERIAL: số văn bằng công khai nhưng chỉ ra chủ văn bằng."),
    Category("MARK", "Tên nhãn hiệu", False,
             Harm.INTERNAL, _LLS_SECRET, BasisKind.STATUTE,
             "Như APP_SERIAL: tra tên nhãn hiệu trên đăng bạ là ra chủ đơn. Token "
             "giữ một nhãn hiệu là một giá trị trong cả hồ sơ; đổi lại agent "
             "không so được chữ của hai nhãn."),
    Category("NICE_CLASS", "Phân nhóm Nice", False,
             Harm.NONE, "chuẩn phân loại đã công bố", BasisKind.PUBLIC_RECORD),

    # ---- everything else ---------------------------------------------------
    Category("DATE", "Ngày thủ tục (nộp, ra thông báo, hạn, ký)", False,
             Harm.INTERNAL, _LLS_SECRET, BasisKind.STATUTE,
             "Ngày nộp cộng đăng bạ công khai là tìm ra đơn, tức ra người nộp, "
             "như APP_SERIAL. Ngày sinh đã tách sang BIRTH_DATE, nên L không "
             f"còn lấy theo ngày sinh. {_RULED} (P1): bí danh hoá bằng TOKEN, "
             "không dịch ngày: một độ dịch chung của cả hồ sơ lộ ra ngay khi "
             "biết một cặp ngày thật. Token không mang khoảng cách; tính hạn "
             "và suy giai đoạn chạy trên ngày thật trong vùng tin cậy."),
    Category("BIRTH_DATE", "Ngày sinh", True,
             Harm.PERSONAL, _ND13_BIRTH, BasisKind.DECREE,
             f"Tách khỏi DATE theo {_RULED} (P1). Không chặng nào cần lấy lại "
             "nó (báo cáo §2.3 hàng 15): ai cần thì đọc bản gốc. Nhận qua nhãn "
             "(Ngày sinh, Sinh ngày, Date of birth) hoặc lời dẫn đứng ngay "
             "trước một ngày (sinh ngày …, born on …)."),
    Category("URL", "Địa chỉ web", False,
             Harm.NONE, "tài nguyên web đã công bố", BasisKind.PUBLIC_RECORD),
    Category("INVOICE_NO", "Số hoá đơn", False,
             Harm.INTERNAL, "định danh vận hành", BasisKind.PROPOSED,
             "Số thứ tự hoá đơn tự nó không chỉ ra khách hàng. Mã tra cứu hoá đơn "
             "điện tử thì khác: ai có nó cũng xem được người mua và số tiền."),
    Category("GEO", "Tên địa danh", False,
             Harm.PERSONAL, _ND13_PLACE, BasisKind.DECREE,
             "Một thành phần của địa chỉ; gắn với một người thì là nơi sinh, quê "
             "quán hay nơi ở. Cấp tỉnh là đủ cho việc chọn nơi nộp."),
    Category("OTHER_ID", "Số tài khoản / định danh khác", False,
             Harm.SENSITIVE, _ND13_ACCOUNT, BasisKind.DECREE,
             "Nhãn nhận nó là số tài khoản, STK, IBAN, SWIFT. SWIFT là mã ngân "
             "hàng, không phải của người; hạng mục lấy L của số tài khoản."),

    # ---- adopted from ocr-lab ----------------------------------------------
    Category("BOILERPLATE", "Quốc hiệu, tiêu ngữ", False,
             Harm.NONE, "văn bản khuôn mẫu có trên mọi văn bản hành chính",
             BasisKind.PUBLIC_RECORD,
             "Dòng 'quoc_hieu' của ocr-lab. Không chỉ về ai; giấu đi chỉ làm "
             "văn bản khó đọc."),

    # ---- only on a page image (báo cáo §2.3 hàng 21, 29–31) ----------------
    # On an image every action but KEEP is one masked box; REMOVE also says
    # no copy of the pixels is kept anywhere, the vault included.
    Category("FACE_PHOTO", "Ảnh chân dung", True,
             Harm.SENSITIVE, _ND13_IMAGE, BasisKind.DECREE,
             "Nghị định xếp vào cơ bản (L = 2); nâng lên 3 như NATIONAL_ID vì "
             "một khuôn mặt là dữ liệu sinh trắc (Điều 2.4(đ)) và không cấp lại "
             f"được. Không chặng nào đọc nó. Hàng 29, {_RULED}.", image=True),
    Category("SIGNATURE", "Chữ ký tay", True,
             Harm.SENSITIVE, f"{_RULED}: một chữ ký tay đủ để giả mạo văn bản",
             BasisKind.FIRM_STATED,
             "Không điều khoản nào gọi tên chữ ký; văn phòng tự xác định L = 3 "
             "(báo cáo §2.3 hàng 30). Ai đã ký thì đọc ở dòng chữ in bên dưới.",
             image=True),
    Category("FINGERPRINT", "Vân tay", True,
             Harm.SENSITIVE, _ND13_BIOMETRIC, BasisKind.DECREE,
             f"Sinh trắc học; ở mặt sau CCCD. Hàng 30, {_RULED}.", image=True),
    Category("SCAN_CODE", "Mã QR / mã vạch trên giấy tờ tuỳ thân", True,
             Harm.SENSITIVE, _ND13_BASIC, BasisKind.DECREE,
             "Mã QR trên CCCD mã hoá số định danh, họ tên, ngày sinh và nơi "
             "thường trú: cả trang nhân thân, nên nâng lên 3 như MRZ. "
             f"Hàng 31, {_RULED}.", image=True),
    Category("MARK_IMAGE", "Mẫu nhãn hiệu dạng hình", False,
             Harm.SENSITIVE, f"{_RULED} (P4): che mẫu nhãn dạng hình trên mọi "
             "bản che", BasisKind.FIRM_STATED,
             "Như MARK: tra hình trên đăng bạ là ra chủ đơn (Luật Luật sư Điều "
             "25). Khác MARK ở chỗ một hình không token hoá được, nên không có "
             "liên kết nào để mua; bản gốc ở lại máy và so hình chỉ chạy tại "
             "máy. Văn phòng tự xác định L = 3 để hình không rời máy dưới dạng "
             "nào.", image=True),
    Category("LOGO", "Logo", False,
             Harm.SENSITIVE, f"{_RULED} (P4): che logo trên mọi bản che",
             BasisKind.FIRM_STATED,
             "Logo của khách chỉ thẳng ra khách; logo của cơ quan chỉ ra hồ sơ "
             "đang ở đâu (như AGENCY). Trên ảnh không phân biệt được hai loại "
             "khi chưa biết vai, nên che cả hai.", image=True),
)

BY_CODE: dict[str, Category] = {c.code: c for c in CATEGORIES}


def category(code: str) -> Category:
    """Look one up, loudly. A typo must not silently vanish."""
    try:
        return BY_CODE[code]
    except KeyError:
        raise KeyError(
            f"unknown category {code!r}; known: {', '.join(sorted(BY_CODE))}"
        ) from None
