// Đo Apple Vision OCR trên ảnh tiếng Việt — bản CLI tối giản.
//
// VÌ SAO VIẾT LẠI THAY VÌ BUILD APP CỦA HỌ: máy này chỉ có Command Line
// Tools, không có Xcode đầy đủ, nên không build được `.xcodeproj`. Nhưng phần
// ta cần đo chỉ là `RecognizeTextRequest` — vài chục dòng. Build cả app GUI
// để đo OCR là đi đường vòng.
//
// Giữ nguyên cấu hình của HideMyData để so được:
//     recognitionLevel = .accurate
//     usesLanguageCorrection = true
//     automaticallyDetectsLanguage = true
//
// Điểm đáng ngờ nhất nằm ở dòng thứ ba: họ KHÔNG khai ngôn ngữ. Với tiếng
// Việt, nếu Vision không có model tiếng Việt thì nó sẽ đọc bằng model tiếng
// Anh — vẫn ra chữ Latin, chỉ là mất sạch dấu. Ra chữ mà sai thì tệ hơn báo
// lỗi, vì không ai biết.

import CoreGraphics
import Foundation
import ImageIO
import Vision

// ── liệt kê ngôn ngữ Vision hỗ trợ ──────────────────────────────────────────
func listLanguages() {
    let request = RecognizeTextRequest()
    // `Locale.Language` không có `.identifier`; mã BCP-47 nằm ở
    // `maximalIdentifier` (hoặc ghép từ languageCode + region).
    let langs = request.supportedRecognitionLanguages.map {
        $0.maximalIdentifier
    }
    print("Vision hỗ trợ \(langs.count) ngôn ngữ:")
    print(langs.sorted().joined(separator: " "))

    let vietnamese = langs.filter { $0.hasPrefix("vi") }
    print("")
    if vietnamese.isEmpty {
        print("KHÔNG CÓ TIẾNG VIỆT.")
        print("Hệ quả: Vision sẽ đọc bằng model ngôn ngữ khác — vẫn ra chữ")
        print("Latin nhưng mất dấu, và không có cảnh báo nào.")
    } else {
        print("CÓ tiếng Việt: \(vietnamese.joined(separator: ", "))")
    }
}

// ── đọc một ảnh ─────────────────────────────────────────────────────────────
func loadImage(_ path: String) -> CGImage? {
    guard let src = CGImageSourceCreateWithURL(
        URL(fileURLWithPath: path) as CFURL, nil) else { return nil }
    return CGImageSourceCreateImageAtIndex(src, 0, nil)
}

func recognize(_ image: CGImage, languages: [String]) async throws
    -> (text: String, seconds: Double) {
    var request = RecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    if languages.isEmpty {
        request.automaticallyDetectsLanguage = true
    } else {
        request.automaticallyDetectsLanguage = false
        request.recognitionLanguages = languages.map { Locale.Language(identifier: $0) }
    }

    let t0 = Date()
    let observations = try await request.perform(on: image)
    let elapsed = Date().timeIntervalSince(t0)

    // Ghép theo thứ tự Vision trả về (trên xuống dưới, trái sang phải).
    let lines = observations.compactMap { $0.topCandidates(1).first?.string }
    return (lines.joined(separator: "\n"), elapsed)
}

// ── điểm vào ────────────────────────────────────────────────────────────────
let args = CommandLine.arguments

if args.count < 2 || args[1] == "--languages" {
    listLanguages()
    exit(0)
}

// Cách dùng: vision_ocr <thư mục ảnh> [--lang vi-VN,en-US] [--limit N]
let imageDir = args[1]
var languages: [String] = []
var limit = Int.max

var i = 2
while i < args.count {
    switch args[i] {
    case "--lang":
        if i + 1 < args.count {
            languages = args[i + 1].split(separator: ",").map(String.init)
            i += 1
        }
    case "--limit":
        if i + 1 < args.count { limit = Int(args[i + 1]) ?? Int.max; i += 1 }
    default: break
    }
    i += 1
}

let fm = FileManager.default
let files = ((try? fm.contentsOfDirectory(atPath: imageDir)) ?? [])
    .filter { $0.hasSuffix(".jpg") || $0.hasSuffix(".png") }
    .sorted()
    .prefix(limit)

var results: [[String: Any]] = []
for name in files {
    let path = (imageDir as NSString).appendingPathComponent(name)
    guard let image = loadImage(path) else {
        FileHandle.standardError.write("không đọc được \(name)\n".data(using: .utf8)!)
        continue
    }
    do {
        let (text, secs) = try await recognize(image, languages: languages)
        results.append(["page": name, "text": text,
                        "seconds": (secs * 100).rounded() / 100])
        FileHandle.standardError.write(
            "\(name) \(String(format: "%.2f", secs))s \(text.count) kt\n"
                .data(using: .utf8)!)
    } catch {
        FileHandle.standardError.write("lỗi \(name): \(error)\n".data(using: .utf8)!)
    }
}

let json = try JSONSerialization.data(withJSONObject: results,
                                      options: [.prettyPrinted, .withoutEscapingSlashes])
FileHandle.standardOutput.write(json)
