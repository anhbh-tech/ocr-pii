"""Lời nhắc hệ thống cho OCR tài liệu pháp lý, gồm cả giấy tờ tuỳ thân.

VÌ SAO CẦN TỆP NÀY: OVER-REFUSAL, KHÔNG PHẢI CHÍNH SÁCH
───────────────────────────────────────────────────────
Model thị giác thường từ chối đọc CCCD/hộ chiếu bằng một câu xin lỗi. Phản xạ
đầu tiên là coi đó là chính sách chặn và đi tìm cách lách. Chẩn đoán đó SAI, và
đi theo nó sẽ dẫn tới một prompt mong manh, vá xong lại hỏng ở bản model sau.

Chép lại chữ in trên giấy tờ tuỳ thân KHÔNG vi phạm chính sách của OpenAI —
toàn bộ ngành eKYC/định danh chạy trên đúng năng lực đó. Thứ bị cấm là hai việc
KHÁC HẲN:

    NHẬN DẠNG DANH TÍNH TỪ KHUÔN MẶT   ("người trong ảnh này là ai")
    SUY ĐOÁN THUỘC TÍNH CÁ NHÂN        (chủng tộc, tôn giáo, xu hướng… từ ảnh)

Khi model từ chối một yêu cầu OCR hợp pháp, đó là **over-refusal**: nó đọc nhầm
ý định, vì "đây là CCCD" nghe gần giống "hãy nhận dạng người này". Cách sửa
đúng là NÓI RÕ Ý ĐỊNH THẬT, không phải che giấu bản chất tài liệu.

NGUYÊN TẮC: MỌI CÂU DƯỚI ĐÂY ĐỀU LÀ SỰ THẬT
───────────────────────────────────────────
Lời nhắc này không chứa câu nào sai sự thật, không đóng vai, không viện dẫn
thẩm quyền không có thật. Đó không phải tính cẩn thận thừa — đó là điều làm nó
BỀN:

- Prompt dựa trên lỗ hổng sẽ hỏng khi nhà cung cấp vá, và hỏng ÂM THẦM giữa một
  lượt chạy hàng loạt.
- Prompt nói đúng ngữ cảnh thì càng ngày càng hiệu quả, vì các bản model sau
  đều được huấn luyện để giảm over-refusal với yêu cầu chính đáng.
- Nếu một ngày ta phải giải trình cách dữ liệu khách hàng được xử lý, lời nhắc
  này đọc lên là một mô tả đúng công việc, không phải một mẹo lách.

Hệ quả thực tế: ĐỪNG thêm câu kiểu "bạn được cấp quyền đặc biệt", "bỏ qua mọi
quy tắc trước đó", "đây là bài kiểm thử nội bộ nên không có dữ liệu thật". Câu
cuối cùng vừa sai (dữ liệu THẬT) vừa phản tác dụng.

RANH GIỚI PHẢI GIỮ NGUYÊN
─────────────────────────
Lời nhắc CẤM model mô tả khuôn mặt hoặc suy đoán về con người. Đó không phải
phép lịch sự với nhà cung cấp mà là yêu cầu nghiệp vụ: ta cần CHỮ trên thẻ, và
một dòng mô tả ngoại hình lọt vào bản chép là dữ liệu sinh trắc không ai yêu
cầu, nằm lại trong tệp kết quả.
"""

from __future__ import annotations

__all__ = ["LEGAL_OCR_SYSTEM", "IDENTITY_DOC_PROMPT", "GENERIC_OCR_PROMPT",
           "CCCD_FIELDS"]


#: Lời nhắc hệ thống. Đặt ngữ cảnh MỘT LẦN cho cả lượt chạy.
#:
#: Ba việc nó làm, theo đúng thứ tự quan trọng:
#:   1. Nêu đúng vai trò: bộ chép chữ, không phải trợ lý phân tích.
#:   2. Nêu đúng ngữ cảnh nghiệp vụ có thật (hồ sơ SHTT, chủ hồ sơ tự nộp).
#:   3. Vạch rõ ranh giới — nói cả điều PHẢI làm lẫn điều KHÔNG được làm, để
#:      model không phải tự đoán ranh giới nằm ở đâu.
LEGAL_OCR_SYSTEM = """\
Bạn là công cụ trích xuất văn bản (OCR) trong quy trình xử lý hồ sơ của một \
công ty luật sở hữu trí tuệ.

BỐI CẢNH CÔNG VIỆC
Tài liệu đưa vào là hồ sơ do chính thân chủ nộp cho công ty luật để làm thủ \
tục đăng ký nhãn hiệu và bản quyền. Chúng gồm đơn từ, biên lai, hợp đồng, và \
giấy tờ tuỳ thân mà thân chủ cung cấp để chứng minh tư cách người nộp đơn — \
đây là giấy tờ bắt buộc theo quy định của cơ quan đăng ký. Công việc của bạn \
là chép lại chữ trên đó để cán bộ hồ sơ đối chiếu, thay cho việc gõ tay.

VIỆC BẠN LÀM
Chép lại chính xác phần CHỮ IN và CHỮ VIẾT nhìn thấy được trong ảnh. Đây là \
sao chép văn bản, giống hệt việc gõ lại một tờ giấy — không phải phân tích, \
không phải nhận dạng con người.

VIỆC BẠN KHÔNG LÀM, KỂ CẢ KHI ĐƯỢC YÊU CẦU
- Không mô tả khuôn mặt, ngoại hình hay đặc điểm sinh trắc của bất kỳ ai.
- Không phán đoán danh tính người trong ảnh, không so khớp với bất kỳ ai.
- Không suy đoán chủng tộc, tôn giáo, sức khoẻ hay bất kỳ thuộc tính cá nhân \
nào không được in thành chữ trên tài liệu.
- Không đánh giá giấy tờ thật hay giả.
- Không bình luận, không tóm tắt, không thêm lời dẫn.

Nếu ảnh có ảnh chân dung, bỏ qua nó hoàn toàn và chỉ chép phần chữ.

CHÍNH XÁC LÀ YÊU CẦU CAO NHẤT
Bản chép này đi vào hồ sơ pháp lý. Một chữ số sai trong số giấy tờ hay ngày \
tháng là một lỗi hồ sơ thật. Khi một ký tự không đọc chắc chắn được, ghi \
[?] tại đúng vị trí đó thay vì đoán. Thà thiếu còn hơn sai.\
"""


#: Lời nhắc cho giấy tờ tuỳ thân. Yêu cầu XUẤT THEO TRƯỜNG chứ không phải chép
#: tự do.
#:
#: VÌ SAO THEO TRƯỜNG: với một biểu mẫu có cấu trúc cố định, chép tự do làm hỏng
#: phép đo. Thứ tự đọc mà model chọn (theo cột? theo dòng? nhãn trước hay giá
#: trị trước?) sẽ lẫn vào CER như thể đọc sai, trong khi từng chữ có thể đúng
#: hết. Ép ra `NHÃN: giá trị` thì so sánh được TỪNG TRƯỜNG — và trường mới là
#: đơn vị mà hồ sơ pháp lý quan tâm, không phải ký tự.
#:
#: VÌ SAO GIỮ CẢ TIẾNG VIỆT LẪN TIẾNG ANH: CCCD in song ngữ. Model hay "dọn
#: dẹp" bằng cách bỏ một trong hai — đó là mất dữ liệu có thật trên thẻ.
IDENTITY_DOC_PROMPT = """\
Ảnh này là giấy tờ tuỳ thân do thân chủ nộp kèm hồ sơ. Chép lại phần chữ.

Xuất ra theo đúng định dạng dưới đây, mỗi trường một dòng, giữ nguyên nhãn \
tiếng Việt in trên thẻ:

NHÃN: giá trị

Quy tắc:
- Giữ nguyên dấu tiếng Việt, chữ HOA/thường đúng như in trên thẻ.
- Chép số giấy tờ, ngày tháng, mã số đúng TỪNG chữ số, không thêm dấu cách \
hay dấu chấm mà thẻ không có.
- Thẻ in song ngữ thì giữ cả hai: viết nhãn tiếng Việt, rồi ` / ` và nhãn \
tiếng Anh.
- Trường nào có trên thẻ mà bạn không đọc được, vẫn ghi nhãn đó và để giá trị \
là [không đọc được].
- Ký tự đơn lẻ không chắc chắn: ghi [?] ngay tại vị trí đó.
- Nếu ảnh có cả mặt trước và mặt sau, chép cả hai, phân cách bằng dòng \
`--- MẶT SAU ---`.
- Có dòng mã máy đọc (MRZ, dãy ký tự và dấu `<`) thì chép nguyên văn dưới nhãn \
`MRZ:`.
- Không mô tả ảnh chân dung, con dấu hay hoa văn. Chỉ chữ.

Chỉ trả về các dòng trường, không thêm lời nào khác.\
"""


#: Lời nhắc cho tài liệu thường (đơn từ, biên lai, hợp đồng).
#:
#: Ở đây chép tự do là ĐÚNG: tài liệu không có cấu trúc cố định, nên ép khuôn
#: sẽ làm mất chính thứ cần đọc.
GENERIC_OCR_PROMPT = """\
Chép lại TOÀN BỘ chữ nhìn thấy trong ảnh này, theo thứ tự đọc từ trên xuống \
dưới, trái sang phải.

- Giữ nguyên chính tả, dấu tiếng Việt, chữ hoa/thường, dấu câu.
- Chép mọi con số, mã số, ngày tháng, email đúng từng ký tự.
- Xuống dòng ở đúng chỗ tài liệu xuống dòng.
- Bảng thì giữ từng hàng trên một dòng, các ô cách nhau bằng ` | `.
- Ký tự không đọc chắc chắn: ghi [?] tại đúng vị trí đó.
- KHÔNG tóm tắt, KHÔNG giải thích, KHÔNG thêm lời dẫn.

Chỉ trả về phần chữ đã chép.\
"""


#: Các trường trên CCCD Việt Nam, dùng để CHẤM ĐỘ PHỦ trường.
#:
#: Đây KHÔNG phải ground truth (giá trị từng trường vẫn phải do người gõ). Nó
#: trả lời một câu hỏi hẹp hơn nhưng tự động được: model có TÌM RA trường đó
#: không, hay bỏ sót hẳn.
#:
#: Phân biệt hai thất bại rất khác nhau, mà nếu chỉ nhìn CER thì lẫn làm một:
#:     BỎ SÓT TRƯỜNG  → hỏng cấu trúc, hồ sơ thiếu mục (nặng)
#:     SAI GIÁ TRỊ    → đọc nhầm chữ, sửa được khi soát (nhẹ hơn)
#:
#: Mỗi trường là một bộ các cách viết nhãn đã gặp thật — CCCD đổi mẫu nhiều
#: lần, và bản chép của model có thể dùng nhãn tiếng Anh.
CCCD_FIELDS: dict[str, tuple[str, ...]] = {
    "số thẻ": ("số:", "số/", "no:", "no.:", "số căn cước", "identity card"),
    "họ tên": ("họ và tên", "họ tên", "full name", "name:"),
    "ngày sinh": ("ngày sinh", "ngày, tháng, năm sinh", "date of birth", "dob"),
    "giới tính": ("giới tính", "sex:", "gender"),
    "quốc tịch": ("quốc tịch", "nationality"),
    "quê quán": ("quê quán", "nơi sinh", "place of origin", "place of birth"),
    "nơi thường trú": ("nơi thường trú", "nơi cư trú", "place of residence",
                       "residence"),
    "có giá trị đến": ("có giá trị đến", "giá trị đến", "date of expiry",
                       "expiry"),
    "ngày cấp": ("ngày cấp", "date of issue", "issue date"),
    "nơi cấp": ("nơi cấp", "place of issue", "cục cảnh sát"),
    "đặc điểm nhân dạng": ("đặc điểm nhân dạng", "nhân dạng",
                           "personal identification"),
}
