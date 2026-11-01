import AppKit

final class MenuBarWindowLifecycle {
    struct Operations {
        var isFullScreen: () -> Bool
        var leaveFullScreen: () -> Void
        var setDockVisible: (Bool) -> Bool
        var hideWindow: () -> Void
        var revealWindow: () -> Void
    }

    private let operations: Operations
    private(set) var trayAvailable = false
    private(set) var backgrounded = false
    private(set) var closingFullScreen = false
    private(set) var pendingClose = false
    private(set) var quitting = false
    private(set) var generation = 0

    init(operations: Operations) {
        self.operations = operations
    }

    @discardableResult
    func setTrayAvailable(_ available: Bool) -> Bool {
        if quitting {
            trayAvailable = available
            return true
        }
        if !available {
            guard operations.setDockVisible(true) else { return false }
            generation += 1
            pendingClose = false
            backgrounded = false
        }
        trayAvailable = available
        return true
    }

    func close() -> Bool {
        guard !quitting else { return false }
        guard trayAvailable else {
            _ = operations.setDockVisible(true)
            return false
        }
        generation += 1
        pendingClose = true
        if operations.isFullScreen() {
            if !closingFullScreen {
                closingFullScreen = true
                operations.leaveFullScreen()
            }
        } else if !closingFullScreen {
            finishClose()
        }
        return true
    }

    func fullScreenEntered() {
        if pendingClose && !quitting {
            closingFullScreen = true
            operations.leaveFullScreen()
        }
    }

    func fullScreenExited() {
        closingFullScreen = false
        if pendingClose { finishClose() }
    }

    @discardableResult
    func prepareToReveal() -> Bool {
        guard !quitting else { return false }
        generation += 1
        pendingClose = false
        backgrounded = false
        return operations.setDockVisible(true)
    }

    func reveal() {
        guard !quitting else { return }
        _ = prepareToReveal()
        operations.revealWindow()
    }

    func windowBecameKey() {
        if backgrounded { _ = prepareToReveal() }
    }

    func beginTermination() {
        generation += 1
        pendingClose = false
        quitting = true
    }

    private func finishClose() {
        guard pendingClose && !quitting else { return }
        pendingClose = false
        backgrounded = true
        operations.hideWindow()
        if trayAvailable && backgrounded && !quitting {
            if !operations.setDockVisible(false) {
                _ = operations.setDockVisible(true)
            }
        }
    }
}

final class MenuBarWindowController {
    private weak var window: NSWindow?
    private weak var statusItem: NSStatusItem?
    private var observations: [NSObjectProtocol] = []
    private var statusVisibility: NSKeyValueObservation?
    private var enteringFullScreen = false
    private(set) var lifecycle: MenuBarWindowLifecycle!

    init(window: NSWindow) {
        self.window = window
        self.lifecycle = MenuBarWindowLifecycle(operations: .init(
            isFullScreen: { [weak self, weak window] in
                (self?.enteringFullScreen ?? false) || (window?.styleMask.contains(.fullScreen) ?? false)
            },
            leaveFullScreen: { [weak self, weak window] in
                if self?.enteringFullScreen == false && window?.styleMask.contains(.fullScreen) == true {
                    window?.toggleFullScreen(nil)
                }
            },
            setDockVisible: { visible in
                let policy: NSApplication.ActivationPolicy = visible ? .regular : .accessory
                return NSApp.activationPolicy() == policy || NSApp.setActivationPolicy(policy)
            },
            hideWindow: { [weak window] in
                window?.orderOut(nil)
                NSApp.hide(nil)
            },
            revealWindow: { [weak window] in
                NSApp.unhide(nil)
                window?.deminiaturize(nil)
                window?.makeKeyAndOrderFront(nil)
                NSApp.activate(ignoringOtherApps: true)
            }
        ))
        observe(NSWindow.willEnterFullScreenNotification, window: window) { controller in
            controller.enteringFullScreen = true
        }
        observe(NSWindow.didEnterFullScreenNotification, window: window) { controller in
            controller.enteringFullScreen = false
            controller.lifecycle.fullScreenEntered()
        }
        observe(NSWindow.didExitFullScreenNotification, window: window) { controller in
            controller.enteringFullScreen = false
            controller.lifecycle.fullScreenExited()
        }
        observe(NSWindow.didBecomeKeyNotification, window: window) { controller in
            controller.lifecycle.windowBecameKey()
        }
        observe(NSWindow.willMiniaturizeNotification, window: window) { controller in
            _ = controller.lifecycle.prepareToReveal()
        }
    }

    func close() -> Bool {
        refreshStatusItem()
        return lifecycle.close()
    }

    func reveal() {
        lifecycle.reveal()
        let generation = lifecycle.generation
        DispatchQueue.main.async { [weak self] in
            guard let self, self.lifecycle.generation == generation,
                  !self.lifecycle.quitting, !self.lifecycle.backgrounded else { return }
            self.window?.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    func prepareToReveal() {
        _ = lifecycle.prepareToReveal()
    }

    func beginTermination() {
        lifecycle.beginTermination()
    }

    @discardableResult
    func setStatusItem(_ item: NSStatusItem?) -> Bool {
        if item == nil && !lifecycle.setTrayAvailable(false) { return false }
        statusVisibility = nil
        statusItem = item
        if let item {
            statusVisibility = item.observe(\.isVisible, options: [.initial, .new]) { [weak self] _, _ in
                self?.refreshStatusItem()
            }
        }
        refreshStatusItem()
        return true
    }

    func refreshStatusItem() {
        let available = statusItem?.isVisible == true && statusItem?.button != nil
            && statusItem?.menu != nil && statusItem?.button?.image != nil
        if !lifecycle.setTrayAvailable(available), let statusItem {
            statusItem.isVisible = true
        }
    }

    private func observe(_ name: NSNotification.Name, window: NSWindow,
                         action: @escaping (MenuBarWindowController) -> Void) {
        observations.append(NotificationCenter.default.addObserver(forName: name, object: window, queue: .main) { [weak self] _ in
            if let self { action(self) }
        })
    }

    deinit {
        for observation in observations {
            NotificationCenter.default.removeObserver(observation)
        }
    }
}
