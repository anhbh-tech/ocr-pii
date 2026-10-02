/* Nhận diện thông tin nhạy cảm trong văn bản hồ sơ pháp lý.
 *
 * VÌ SAO CÓ TỆP NÀY
 * -----------------
 * Trước khi một đoạn văn bản rời máy — đi nhúng vector, gọi LLM, hay xuất
 * báo cáo — phải biết trong đó có gì đáng giấu. Tệp này KHÔNG tự giấu; nó
 * chỉ chỉ ra chỗ nào là gì, để người soát nhìn thấy trước khi quyết định.
 *
 * HAI CÁCH XỬ LÝ, KHÁC NHAU Ở CHỖ CÓ HOÀN NGUYÊN ĐƯỢC KHÔNG
 * ---------------------------------------------------------
 *   pseudo — BÚT DANH HOÁ. Thay giá trị thật bằng một mã ổn định
 *            ("Nguyễn Văn A" → "NGƯỜI_07"). Cùng một người thì ở đâu
 *            cũng ra cùng một mã, nên vẫn suy luận được quan hệ. Bảng
 *            tra ngược nằm trong `vault` — HOÀN NGUYÊN ĐƯỢC, và vì hoàn
 *            nguyên được nên theo GDPR nó VẪN LÀ dữ liệu cá nhân.
 *
 *   anon   — ẨN DANH HOÁ. Vứt bớt thông tin cho tới khi không lần ngược
 *            được nữa ("số 9 ngách 99/99 Hư Cấu, Mẫu Thử, Hà Nội" →
 *            "Hà Nội"). KHÔNG có bảng tra ngược, không hoàn nguyên được.
 *            Mất mát là thật và vĩnh viễn — đổi lại dữ liệu ra khỏi phạm
 *            vi điều chỉnh của luật bảo vệ dữ liệu cá nhân.
 *
 *   keep   — GIỮ NGUYÊN. Văn bản khuôn mẫu mà hồ sơ nào cũng có, không
 *            chỉ về ai cả.
 *
 * Chọn cái nào không phải tuỳ hứng — xem thang đo trong `SENSITIVITY`.
 */

/* Thang đo, ba trục, mỗi trục 0-3.
 *
 *   R — SỨC TÁI ĐỊNH DANH. Biết giá trị này thì lần ra hồ sơ nào?
 *       ĐO ĐƯỢC, không phải cảm tính: tỉ lệ giá trị chỉ xuất hiện ở đúng
 *       một hồ sơ trong kho. Quốc hiệu có mặt ở mọi hồ sơ → R=0. Mã hồ sơ
 *       92% chỉ thuộc một hồ sơ → R=3.
 *
 *   L — THIỆT HẠI NẾU LỘ. Lộ ra thì hỏng đến đâu? Số căn cước mở đường
 *       cho giả mạo danh tính (L=3); tên công ty đã công bố trên công báo
 *       sở hữu trí tuệ thì nhẹ hơn nhiều (L=1).
 *
 *   N — NHU CẦU NGHIỆP VỤ. Bỏ đi thì luật sư còn làm việc được không?
 *       Ngày nộp đơn mà xoá thì không tính nổi hạn — N=3.
 *
 * QUYẾT ĐỊNH:
 *   rủi ro = R × L
 *   rủi ro ≤ 2           → keep    (không đáng động vào)
 *   rủi ro ≥ 3 và N ≥ 2  → pseudo  (phải giấu, nhưng còn cần dùng)
 *   rủi ro ≥ 3 và N ≤ 1  → anon    (phải giấu, và không cần dùng)
 *
 * Trục N mới là trục quyết định pseudo hay anon — đó là lý do một hệ chỉ
 * nhìn "mức độ nhạy cảm" rồi bôi đen tất cả sẽ phá hỏng hồ sơ: nó giấu cả
 * những thứ luật sư buộc phải đọc mới làm được việc.
 */

export const SENSITIVITY = [
  {
    id: 'cccd',
    ten: 'Số căn cước / CMND',
    re: /\b\d{12}\b/g,
    R: 3, L: 3, N: 1,
    vi_sao: 'Định danh nhà nước, duy nhất tuyệt đối. Lộ ra là mở đường giả '
          + 'mạo danh tính, mở tài khoản, ký hợp đồng thay. Luật sư hầu như '
          + 'không cần đọc con số — chỉ cần biết "có giấy tờ hợp lệ".',
  },
  {
    id: 'mrz',
    ten: 'Dòng máy đọc hộ chiếu (MRZ)',
    re: /IDVNM[A-Z0-9<]{10,}/g,
    R: 3, L: 3, N: 0,
    vi_sao: 'Cả trang nhân thân nén trong một dòng: số, ngày sinh, giới '
          + 'tính, quốc tịch. Không có nhu cầu nghiệp vụ nào cần đến nó.',
  },
  {
    id: 'email',
    ten: 'Địa chỉ thư điện tử',
    re: /[\w.+-]+@[\w-]+\.[\w.]{2,}/g,
    R: 3, L: 2, N: 2,
    vi_sao: 'Đo trong kho: 89% địa chỉ chỉ thuộc đúng một hồ sơ. Vẫn cần '
          + 'giữ quan hệ "ai gửi cho ai" nên bút danh hoá, không xoá.',
  },
  {
    id: 'phone',
    ten: 'Số điện thoại',
    re: /(?:\+84|0)(?:3|5|7|8|9)\d{8}\b/g,
    R: 3, L: 2, N: 2,
    vi_sao: 'Đo trong kho: 90% số chỉ thuộc một hồ sơ. Là đầu mối liên lạc '
          + 'thật nên vẫn phải truy được khi cần gọi.',
  },
  {
    id: 'mst',
    ten: 'Mã số thuế / ĐKKD',
    re: /\b\d{10}(?:-\d{3})?\b/g,
    R: 3, L: 2, N: 2,
    vi_sao: 'Tra một phát ra toàn bộ pháp nhân. Công khai về mặt kỹ thuật, '
          + 'nhưng ghép với hồ sơ tranh chấp thì lộ ai đang kiện ai.',
  },
  {
    id: 'money',
    ten: 'Số tiền',
    re: /\d[\d.,]{4,}\s*(?:đ|VND|VNĐ|USD|\$)/g,
    R: 3, L: 2, N: 3,
    vi_sao: 'Đo trong kho: 100% giá trị chỉ xuất hiện ở một hồ sơ — con số '
          + 'lẻ chính là dấu vân tay. Nhưng luật sư phải đọc được để tư vấn, '
          + 'nên bút danh hoá theo khoảng chứ không xoá.',
  },
  {
    id: 'ho_so',
    ten: 'Mã hồ sơ nội bộ',
    re: /\b(?:NH|BQ|TV)\d{2,4}(?:[-.]\d{1,4})?(?:\.[A-Z]{2})?\b/g,
    R: 3, L: 1, N: 3,
    vi_sao: 'Đo trong kho: 92% mã chỉ thuộc một hồ sơ. Đây là khoá chính '
          + 'của cả hệ thống — xoá đi thì không ghép được tài liệu với hồ '
          + 'sơ nữa. Bắt buộc bút danh hoá, tuyệt đối không ẩn danh.',
  },
  {
    id: 'don',
    ten: 'Số đơn đăng ký (USPTO/IPVN)',
    re: /\b(?:7|8|9)\d{7}\b/g,
    R: 3, L: 1, N: 3,
    vi_sao: 'Đo trong kho: 100% chỉ thuộc một hồ sơ. Nhưng đây là số CÔNG '
          + 'KHAI trên công báo — ai cũng tra được, nên thiệt hại thấp, '
          + 'trong khi bỏ đi thì mất luôn khả năng đối chiếu.',
  },
  {
    id: 'ngay',
    ten: 'Ngày tháng',
    re: /\b\d{1,2}\/\d{1,2}\/\d{4}\b/g,
    R: 2, L: 2, N: 3,
    vi_sao: 'Một ngày đơn lẻ thì yếu, nhưng đo trong kho: 92% giá trị ngày '
          + 'chỉ xuất hiện ở đúng một hồ sơ — chuỗi nộp–phản hồi–gia hạn là '
          + 'dấu vân tay. Dịch cả chuỗi cùng một khoảng ngẫu nhiên theo hồ '
          + 'sơ: khoảng cách giữa các mốc còn nguyên, hạn vẫn tính đúng, mà '
          + 'không lần ra hồ sơ thật. Đó là lý do phải bút danh hoá chứ '
          + 'không xoá — xoá thì mất luôn khả năng tính hạn.',
  },
  {
    id: 'dkkd',
    ten: 'Số đăng ký kinh doanh',
    re: /(?:S\.?Đ\.?K\.?D|ĐKKD)\.?\s*:?\s*\d{8,13}/g,
    R: 3, L: 2, N: 2,
    vi_sao: 'Thấy trên con dấu trong chính tài liệu bàn giao. Tra một phát '
          + 'ra pháp nhân đầy đủ: người đại diện, địa chỉ, ngành nghề.',
  },
  {
    id: 'dia_chi',
    ten: 'Địa chỉ chi tiết',
    re: /(?:số|Số)\s*\d+[A-Za-z]?(?:\/\d+)*\s+(?:ngách|ngõ|đường|phố|tổ|khu)[^,.\n]{0,40}/g,
    R: 2, L: 2, N: 1,
    vi_sao: 'Số nhà chỉ thẳng tới nơi ở. Luật sư chỉ cần đến cấp tỉnh/thành '
          + 'để xác định thẩm quyền toà — nên khái quát hoá, và vì không '
          + 'cần hoàn nguyên nên ẩn danh hẳn. Mẫu bắt buộc phải có từ chỉ '
          + 'đường (ngách/ngõ/phố) đứng sau số, nếu không "số 88123456" — '
          + 'một số đơn đăng ký — sẽ bị nuốt nhầm thành địa chỉ.',
  },
  {
    id: 'quoc_hieu',
    ten: 'Quốc hiệu, tiêu ngữ',
    re: /CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM|Độc lập\s*-\s*Tự do\s*-\s*Hạnh phúc/g,
    R: 0, L: 0, N: 1,
    vi_sao: 'Đo trong kho: xuất hiện ở MỌI hồ sơ, nên không phân biệt được '
          + 'hồ sơ nào với hồ sơ nào. Giấu đi chỉ làm văn bản khó đọc.',
  },
];

/* Suy ra cách xử lý từ ba trục — không ai tự gán tay, để khỏi cãi nhau. */
export function xuLy(f) {
  const ruiRo = f.R * f.L;
  if (ruiRo <= 2) return 'keep';
  return f.N >= 2 ? 'pseudo' : 'anon';
}

export const NHAN = {
  pseudo: { ten: 'bút danh hoá', mo_ta: 'thay bằng mã ổn định, hoàn nguyên được qua vault' },
  anon:   { ten: 'ẩn danh hoá',  mo_ta: 'khái quát hoá, KHÔNG hoàn nguyên được' },
  keep:   { ten: 'giữ nguyên',   mo_ta: 'khuôn mẫu, không chỉ về ai' },
};

/* Tìm mọi vùng nhạy cảm trong một đoạn văn bản THÔ (chưa escape HTML).
 *
 * Trả về mảng {start, end, f} đã sắp xếp và KHÔNG chồng lấn — chồng lấn thì
 * khi dựng HTML sẽ sinh thẻ lồng sai và vỡ trang. Khi hai mẫu cùng khớp một
 * chỗ, giữ mẫu có rủi ro cao hơn (vd '0912345678' vừa giống điện thoại vừa
 * giống mã số thuế 10 số — điện thoại đúng hơn vì có đầu số 09).
 */
export function timPII(text) {
  if (!text) return [];
  const hits = [];
  for (const f of SENSITIVITY) {
    if (xuLy(f) === 'keep') continue;
    f.re.lastIndex = 0;
    let m;
    while ((m = f.re.exec(text)) !== null) {
      if (m[0].length === 0) { f.re.lastIndex++; continue; }
      hits.push({ start: m.index, end: m.index + m[0].length, f });
    }
  }
  hits.sort((a, b) => a.start - b.start
                   || (b.end - b.start) - (a.end - a.start)
                   || (b.f.R * b.f.L) - (a.f.R * a.f.L));
  const out = [];
  let het = -1;
  for (const h of hits) {
    if (h.start >= het) { out.push(h); het = h.end; }
  }
  return out;
}
