/* Cầu nối ra window.
 *
 * Từ khi Vite gộp `app.js` vào một module, mọi hàm và biến trong đó là
 * RIÊNG TƯ. Đó là điều tốt — trước kia chúng nằm hết ở tầm global và bất kỳ
 * script nào cũng ghi đè được. Nhưng vài thứ cần gọi được từ ngoài:
 *
 *   openLocalFile   main.js gọi khi người dùng bấm một tệp trong file manager
 *   veLaiOverlay    gọi sau khi đổi chủ đề — nét vẽ canvas lấy màu tại LÚC
 *                   VẼ từ biến CSS, nên không tự cập nhật khi biến đổi
 *   __state         CHỈ để gỡ lỗi và cho kiểm thử tự động đọc trạng thái
 *
 * Phơi ra có chủ đích và có tên rõ ràng, thay vì bỏ `type="module"` để mọi
 * thứ lại thành global.
 *
 * Tệp này là một module riêng chứ không phải mấy dòng nối vào cuối app.js:
 * nối vào cuối một tệp 1000 dòng bằng lệnh shell là cách chắc chắn để mất
 * nó trong lần sửa sau, và đã mất thật một lần.
 */

// `app.js` tự chạy khi được nạp và gán các hàm này lên `globalThis` ở cuối
// tệp. Ở đây chỉ kiểm tra chúng có mặt, để lỗi hiện ra ngay thay vì lúc
// người dùng bấm.
export function kiemTraCauNoi() {
  const thieu = ['openLocalFile', 'veLaiOverlay']
    .filter((k) => typeof window[k] !== 'function');
  if (thieu.length) {
    console.error(
      `[ocr-lab] app.js không phơi ra: ${thieu.join(', ')} — `
      + 'bấm tệp trong file manager sẽ không có phản hồi.');
  }
  return thieu.length === 0;
}
