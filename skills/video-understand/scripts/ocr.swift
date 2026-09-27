import AppKit
import Vision

// One JSON line per image: {"path": ..., "chars": N, "text": "..."}.
// Built once by text_check.py and cached; stdlib Python cannot reach Vision.
for path in CommandLine.arguments.dropFirst() {
    var chars = 0
    var lines: [String] = []
    if let img = NSImage(contentsOfFile: path),
       let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) {
        let req = VNRecognizeTextRequest()
        req.recognitionLevel = .accurate
        // Vision wants full codes (th-TH, not th). Unknown codes are dropped
        // silently, which is how Thai subtitles once came back as nothing.
        let langs = ProcessInfo.processInfo.environment["OCR_LANGS"]?
            .split(separator: ",").map(String.init) ?? ["zh-Hans", "en-US"]
        req.recognitionLanguages = langs
        req.usesLanguageCorrection = false
        req.minimumTextHeight = 0.015
        try? VNImageRequestHandler(cgImage: cg).perform([req])
        for obs in req.results ?? [] {
            if let top = obs.topCandidates(1).first, top.confidence >= 0.3 {
                chars += top.string.count
                lines.append(top.string)
            }
        }
    }
    let row: [String: Any] = ["path": path, "chars": chars, "text": lines.joined(separator: " | ")]
    if let data = try? JSONSerialization.data(withJSONObject: row),
       let s = String(data: data, encoding: .utf8) {
        print(s)
    }
}
