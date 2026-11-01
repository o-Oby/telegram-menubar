import AppKit

struct TestFailure: Error, CustomStringConvertible {
    let description: String
}

func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw TestFailure(description: message) }
}

final class Fixture {
    var fullScreen = false
    var visible = true
    var dock = true
    var failRegular = false
    var failAccessory = false
    var exitRequests = 0
    var events: [String] = []
    var onHide: (() -> Void)?
    lazy var lifecycle = MenuBarWindowLifecycle(operations: .init(
        isFullScreen: { self.fullScreen },
        leaveFullScreen: { self.exitRequests += 1; self.events.append("exit-fullscreen") },
        setDockVisible: { visible in
            self.events.append(visible ? "dock-visible" : "dock-hidden")
            if visible && self.failRegular || !visible && self.failAccessory { return false }
            self.dock = visible
            return true
        },
        hideWindow: {
            self.visible = false
            self.events.append("hide")
            self.onHide?()
        },
        revealWindow: { self.visible = true; self.events.append("reveal") }
    ))

    init(tray: Bool = true) {
        _ = lifecycle.setTrayAvailable(tray)
        events.removeAll()
    }
}

var passed = 0
var failures: [String] = []

func test(_ name: String, _ body: () throws -> Void) {
    do {
        try body()
        passed += 1
        print("PASS: \(name)")
    } catch {
        failures.append("\(name): \(error)")
        print("FAIL: \(name): \(error)")
    }
}

test("close keeps the window alive, hides Dock, and reveal restores Dock before showing") {
    let f = Fixture()
    try expect(f.lifecycle.close(), "working tray must intercept close")
    try expect(f.events == ["hide", "dock-hidden"], "hide must precede Dock removal")
    try expect(!f.visible && !f.dock && f.lifecycle.backgrounded, "closed state")
    f.events.removeAll()
    f.lifecycle.reveal()
    try expect(f.events == ["dock-visible", "reveal"], "Dock must precede window restoration")
    try expect(f.visible && f.dock && !f.lifecycle.backgrounded, "reopened state")
}

test("missing tray preserves the normal close path and Dock") {
    let f = Fixture(tray: false)
    try expect(!f.lifecycle.close(), "no tray must not intercept the native close")
    try expect(f.dock && f.visible && f.events == ["dock-visible"], "native window handling stays available")
}

test("fullscreen close waits for the native exit event and repeated closes do not toggle twice") {
    let f = Fixture()
    f.fullScreen = true
    try expect(f.lifecycle.close(), "close is intercepted")
    try expect(f.lifecycle.close(), "repeated close stays intercepted")
    try expect(f.exitRequests == 1 && f.visible && f.dock, "wait for one native transition")
    f.fullScreen = false
    f.lifecycle.fullScreenExited()
    try expect(!f.visible && !f.dock && !f.lifecycle.pendingClose, "exit completes close")
    let events = f.events
    f.lifecycle.fullScreenExited()
    try expect(f.events == events, "repeated exit must not hide again")
}

test("reopening while fullscreen exits cancels the pending hide") {
    let f = Fixture()
    f.fullScreen = true
    _ = f.lifecycle.close()
    f.lifecycle.reveal()
    f.fullScreen = false
    f.lifecycle.fullScreenExited()
    try expect(f.visible && f.dock && !f.lifecycle.pendingClose, "old close cannot override reopen")
    try expect(!f.events.contains("hide"), "no late hide")
}

test("close during fullscreen entry requests exit after entry finishes") {
    let f = Fixture()
    f.fullScreen = true
    _ = f.lifecycle.close()
    f.lifecycle.fullScreenEntered()
    try expect(f.exitRequests == 2 && f.visible, "native adapter retries after entry completes")
    f.fullScreen = false
    f.lifecycle.fullScreenExited()
    try expect(!f.visible && !f.dock, "close completes after exit")
}

test("close reopen close uses the most recent intent during fullscreen exit") {
    let f = Fixture()
    f.fullScreen = true
    _ = f.lifecycle.close()
    f.lifecycle.reveal()
    _ = f.lifecycle.close()
    try expect(f.exitRequests == 1, "existing transition is reused")
    f.fullScreen = false
    f.lifecycle.fullScreenExited()
    try expect(!f.visible && !f.dock, "latest close wins")
}

test("disabling the tray restores Dock without opening or changing the hidden window") {
    let f = Fixture()
    _ = f.lifecycle.close()
    try expect(f.lifecycle.setTrayAvailable(false), "Dock restoration permits removal")
    try expect(f.dock && !f.visible && !f.lifecycle.trayAvailable, "Dock remains recovery entry point")
}

test("tray disappearance during fullscreen transition cancels the pending hide") {
    let f = Fixture()
    f.fullScreen = true
    _ = f.lifecycle.close()
    _ = f.lifecycle.setTrayAvailable(false)
    f.fullScreen = false
    f.lifecycle.fullScreenExited()
    try expect(f.dock && f.visible && !f.lifecycle.pendingClose, "no inaccessible closed state")
}

test("failed Dock restoration keeps the tray available") {
    let f = Fixture()
    _ = f.lifecycle.close()
    f.failRegular = true
    try expect(!f.lifecycle.setTrayAvailable(false), "tray removal must be refused")
    try expect(f.lifecycle.trayAvailable, "keep a recovery action")
}

test("failed Dock hiding falls back to the regular Dock") {
    let f = Fixture()
    f.failAccessory = true
    _ = f.lifecycle.close()
    try expect(!f.visible && f.dock, "window hides but Dock remains")
    try expect(f.events == ["hide", "dock-hidden", "dock-visible"], "fallback explicitly restores Dock")
}

test("a reveal issued while hiding prevents the old request from hiding Dock") {
    let f = Fixture()
    f.onHide = { f.lifecycle.reveal() }
    _ = f.lifecycle.close()
    try expect(f.visible && f.dock && !f.lifecycle.backgrounded, "newer reveal wins")
    try expect(!f.events.contains("dock-hidden"), "no stale Dock hide")
}

test("normal activation or minimizing cancels a pending close without forcing reveal") {
    let f = Fixture()
    f.fullScreen = true
    _ = f.lifecycle.close()
    f.events.removeAll()
    _ = f.lifecycle.prepareToReveal()
    f.lifecycle.fullScreenExited()
    try expect(f.events == ["dock-visible"], "native hide/minimize/reveal behavior remains the caller's choice")
    try expect(!f.lifecycle.pendingClose, "no delayed close")
}

test("showing a backgrounded window through another route restores Dock") {
    let f = Fixture()
    _ = f.lifecycle.close()
    f.visible = true
    f.lifecycle.windowBecameKey()
    try expect(f.dock && !f.lifecycle.backgrounded, "window visibility requires regular Dock")
}

test("termination cancels fullscreen close and subsequent close is not intercepted") {
    let f = Fixture()
    f.fullScreen = true
    _ = f.lifecycle.close()
    f.lifecycle.beginTermination()
    f.events.removeAll()
    f.lifecycle.fullScreenExited()
    f.lifecycle.reveal()
    _ = f.lifecycle.setTrayAvailable(false)
    try expect(!f.lifecycle.close(), "real quit must reach native close")
    try expect(f.events.isEmpty && f.lifecycle.quitting, "no asynchronous visibility transitions during quit")
}

print("\(passed) tests passed; \(failures.count) failed")
if !failures.isEmpty { exit(1) }
