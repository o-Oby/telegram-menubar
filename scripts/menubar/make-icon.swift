import AppKit
import Foundation

let destination = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)
for size in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let pixels = size * scale
        let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        let context = NSGraphicsContext(bitmapImageRep: bitmap)!
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = context
        let edge = CGFloat(pixels)
        let inset = edge * 0.06
        NSColor(calibratedRed: 0.30, green: 0.17, blue: 0.53, alpha: 1).setFill()
        NSBezierPath(roundedRect: NSRect(x: inset, y: inset, width: edge - 2 * inset, height: edge - 2 * inset), xRadius: edge * 0.21, yRadius: edge * 0.21).fill()
        NSColor.white.setFill()
        NSBezierPath(rect: NSRect(x: edge * 0.24, y: edge * 0.66, width: edge * 0.52, height: edge * 0.115)).fill()
        NSBezierPath(rect: NSRect(x: edge * 0.44, y: edge * 0.23, width: edge * 0.12, height: edge * 0.51)).fill()
        NSColor(calibratedRed: 0.70, green: 0.93, blue: 0.74, alpha: 1).setFill()
        NSBezierPath(ovalIn: NSRect(x: edge * 0.69, y: edge * 0.20, width: edge * 0.12, height: edge * 0.12)).fill()
        NSGraphicsContext.restoreGraphicsState()
        let suffix = scale == 2 ? "@2x" : ""
        let file = destination.appendingPathComponent("icon_\(size)x\(size)\(suffix).png")
        try bitmap.representation(using: .png, properties: [:])!.write(to: file)
    }
}
