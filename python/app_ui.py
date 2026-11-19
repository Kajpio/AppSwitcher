import ctypes
import os
from typing import Callable, Dict, List, Optional

from app_toggler import is_accessibility_trusted, open_accessibility_settings
from binding_store import BindingStore
from key_mapper import ALL_LETTERS, letter_for_keycode
from objc_bridge import (
    NSInteger,
    NSRect,
    NSSize,
    NSUInteger,
    cf,
    cls,
    create_objc_class,
    from_nsstr,
    make_rect,
    msg,
    nsstr,
    nsurl_from_path,
    sel,
)

NSEventModifierFlagOption = 1 << 19
NSEventModifierFlagCommand = 1 << 20
NSWindowStyleMaskTitled = 1 << 0
NSWindowStyleMaskClosable = 1 << 1
NSWindowStyleMaskMiniaturizable = 1 << 2
NSWindowStyleMaskResizable = 1 << 3
NSBackingStoreBuffered = 2
NSViewWidthSizable = 1 << 1
NSViewHeightSizable = 1 << 4
NSViewMinXMargin = 1 << 0
NSViewMinYMargin = 1 << 3
NSViewMaxYMargin = 1 << 5
NSControlStateValueOn = 1
NSControlStateValueOff = 0
NSBezelStyleRounded = 1
NSModalResponseOK = 1

_TAG_CALLBACKS: Dict[int, Callable[[], None]] = {}
_NEXT_TAG = 100
_ACTIVE_CONTROLLER = None


def _register_callback(cb: Callable[[], None]) -> int:
    global _NEXT_TAG
    tag = _NEXT_TAG
    _NEXT_TAG += 1
    _TAG_CALLBACKS[tag] = cb
    return tag


def _attach_action(control: int, target: int, cb: Callable[[], None]) -> None:
    tag = _register_callback(cb)
    msg(control, "setTag:", None, (NSInteger,), tag)
    msg(control, "setTarget:", None, (ctypes.c_void_p,), target)
    msg(control, "setAction:", None, (ctypes.c_void_p,), sel("handleAction:"))


def _make_label(text: str, rect: NSRect, font_size: float = 13.0, bold: bool = False, secondary: bool = False) -> int:
    lbl = msg(cls("NSTextField"), "labelWithString:", ctypes.c_void_p, (ctypes.c_void_p,), nsstr(text))
    msg(lbl, "setFrame:", None, (NSRect,), rect)
    if bold:
        font = msg(cls("NSFont"), "boldSystemFontOfSize:", ctypes.c_void_p, (ctypes.c_double,), font_size)
    else:
        font = msg(cls("NSFont"), "systemFontOfSize:", ctypes.c_void_p, (ctypes.c_double,), font_size)
    if font:
        msg(lbl, "setFont:", None, (ctypes.c_void_p,), font)
    if secondary:
        color = msg(cls("NSColor"), "secondaryLabelColor")
        if color:
            msg(lbl, "setTextColor:", None, (ctypes.c_void_p,), color)
    return lbl


def _make_button(title: str, rect: NSRect, target: int, cb: Callable[[], None], default: bool = False) -> int:
    btn = msg(
        cls("NSButton"),
        "buttonWithTitle:target:action:",
        ctypes.c_void_p,
        (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p),
        nsstr(title),
        target,
        sel("handleAction:"),
    )
    tag = _register_callback(cb)
    msg(btn, "setTag:", None, (NSInteger,), tag)
    msg(btn, "setFrame:", None, (NSRect,), rect)
    msg(btn, "setBezelStyle:", None, (NSUInteger,), NSBezelStyleRounded)
    if default:
        msg(btn, "setKeyEquivalent:", None, (ctypes.c_void_p,), nsstr("\r"))
    return btn


def _make_checkbox(title: str, rect: NSRect, checked: bool, target: int, cb: Callable[[], None]) -> int:
    btn = msg(
        cls("NSButton"),
        "checkboxWithTitle:target:action:",
        ctypes.c_void_p,
        (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p),
        nsstr(title),
        target,
        sel("handleAction:"),
    )
    tag = _register_callback(cb)
    msg(btn, "setTag:", None, (NSInteger,), tag)
    msg(btn, "setFrame:", None, (NSRect,), rect)
    msg(btn, "setState:", None, (NSInteger,), NSControlStateValueOn if checked else NSControlStateValueOff)
    return btn


def _app_icon(bundle_id: str, app_path: Optional[str], size: float) -> Optional[int]:
    ws = msg(cls("NSWorkspace"), "sharedWorkspace")
    path = app_path if (app_path and os.path.exists(app_path)) else None
    if not path:
        url = msg(ws, "URLForApplicationWithBundleIdentifier:", ctypes.c_void_p, (ctypes.c_void_p,), nsstr(bundle_id))
        if url:
            path = from_nsstr(msg(url, "path"))
    if not path:
        return None
    img = msg(ws, "iconForFile:", ctypes.c_void_p, (ctypes.c_void_p,), nsstr(path))
    if img:
        msg(img, "setSize:", None, (NSSize,), NSSize(size, size))
    return img


def _init_objc_classes() -> None:
    def on_action(_self: int, _cmd: int, sender: int) -> None:
        if not sender:
            return
        tag = msg(sender, "tag", NSInteger)
        cb = _TAG_CALLBACKS.get(tag)
        if cb:
            cb()

    def on_menu_needs_update(_self: int, _cmd: int, menu: int) -> None:
        if _ACTIVE_CONTROLLER is not None:
            _ACTIVE_CONTROLLER.rebuild_menu(menu)

    def on_window_will_close(_self: int, _cmd: int, notification: int) -> None:
        if _ACTIVE_CONTROLLER is not None:
            win = msg(notification, "object")
            _ACTIVE_CONTROLLER.on_window_closed(win)

    def on_did_finish_launching(_self: int, _cmd: int, _notification: int) -> None:
        if _ACTIVE_CONTROLLER is not None:
            _ACTIVE_CONTROLLER.on_app_launched()

    def on_open_settings_main(_self: int, _cmd: int, _obj: int) -> None:
        if _ACTIVE_CONTROLLER is not None:
            _ACTIVE_CONTROLLER.open_settings_window()

    create_objc_class(
        "PyAppSwitcherDispatcher",
        "NSObject",
        {
            "handleAction:": (ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p), b"v@:@", on_action),
            "menuNeedsUpdate:": (ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p), b"v@:@", on_menu_needs_update),
            "windowWillClose:": (ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p), b"v@:@", on_window_will_close),
            "applicationDidFinishLaunching:": (ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p), b"v@:@", on_did_finish_launching),
            "openSettingsOnMain:": (ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p), b"v@:@", on_open_settings_main),
        },
    )

    def on_is_flipped(_self: int, _cmd: int) -> bool:
        return True

    create_objc_class(
        "PyAppSwitcherFlippedView",
        "NSView",
        {
            "isFlipped": (ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p), b"B@:", on_is_flipped),
        },
    )

    def on_accepts_first(_self: int, _cmd: int) -> bool:
        return True

    def on_key_down(_self: int, _cmd: int, event: int) -> None:
        if _ACTIVE_CONTROLLER is not None and event:
            key_code = msg(event, "keyCode", ctypes.c_uint16)
            _ACTIVE_CONTROLLER.handle_recorded_keycode(int(key_code))

    create_objc_class(
        "PyAppSwitcherKeyCaptureView",
        "NSView",
        {
            "acceptsFirstResponder": (ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p), b"B@:", on_accepts_first),
            "keyDown:": (ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p), b"v@:@", on_key_down),
        },
    )


class AppUIController:
    def __init__(self, store: BindingStore, open_settings_on_launch: bool = False) -> None:
        global _ACTIVE_CONTROLLER
        _ACTIVE_CONTROLLER = self
        self.store = store
        self.open_settings_on_launch = open_settings_on_launch
        _init_objc_classes()

        self.dispatcher = msg(msg(cls("PyAppSwitcherDispatcher"), "alloc"), "init")
        self.settings_window: Optional[int] = None
        self.editor_window: Optional[int] = None
        self.editing_binding: Optional[dict] = None
        self.is_recording_key = False
        self.was_paused_before_record = False
        self.editor_letter_popup: Optional[int] = None
        self.editor_app_popup: Optional[int] = None
        self.editor_record_btn: Optional[int] = None
        self.editor_capture_view: Optional[int] = None
        self.editor_conflict_label: Optional[int] = None
        self.editor_apps: List[dict] = []

        self._setup_status_item()

    def on_app_launched(self) -> None:
        if self.open_settings_on_launch or not self.store.bindings:
            self.open_settings_window()

    def request_open_settings_from_signal(self) -> None:
        msg(
            self.dispatcher,
            "performSelectorOnMainThread:withObject:waitUntilDone:",
            None,
            (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool),
            sel("openSettingsOnMain:"),
            None,
            False,
        )

    def _setup_status_item(self) -> None:
        sb = msg(cls("NSStatusBar"), "systemStatusBar")
        self.status_item = msg(sb, "statusItemWithLength:", ctypes.c_void_p, (ctypes.c_double,), -1.0)
        if self.status_item:
            cf.CFRetain(self.status_item)
        self._update_status_button()

        menu = msg(msg(cls("NSMenu"), "alloc"), "init")
        msg(menu, "setDelegate:", None, (ctypes.c_void_p,), self.dispatcher)
        msg(self.status_item, "setMenu:", None, (ctypes.c_void_p,), menu)

    def _update_status_button(self) -> None:
        btn = msg(self.status_item, "button")
        if not btn:
            return
        sym = "macwindow.badge.plus" if self.store.is_paused else "macwindow.on.rectangle"
        img = msg(
            cls("NSImage"),
            "imageWithSystemSymbolName:accessibilityDescription:",
            ctypes.c_void_p,
            (ctypes.c_void_p, ctypes.c_void_p),
            nsstr(sym),
            nsstr("AppSwitcher"),
        )
        if not img:
            img = msg(
                cls("NSImage"),
                "imageWithSystemSymbolName:accessibilityDescription:",
                ctypes.c_void_p,
                (ctypes.c_void_p, ctypes.c_void_p),
                nsstr("rectangle.stack"),
                nsstr("AppSwitcher"),
            )
        if img:
            msg(img, "setTemplate:", None, (ctypes.c_bool,), True)
            msg(btn, "setImage:", None, (ctypes.c_void_p,), img)
            msg(btn, "setImagePosition:", None, (NSUInteger,), 2)  # NSImageLeft
        msg(btn, "setTitle:", None, (ctypes.c_void_p,), nsstr(" ⌥"))
        msg(btn, "setAppearsDisabled:", None, (ctypes.c_bool,), self.store.is_paused)
        msg(btn, "setToolTip:", None, (ctypes.c_void_p,), nsstr("AppSwitcher (Paused)" if self.store.is_paused else "AppSwitcher"))

    def rebuild_menu(self, menu: int) -> None:
        msg(menu, "removeAllItems", None)

        if self.store.is_paused:
            paused_item = msg(
                msg(cls("NSMenuItem"), "alloc"),
                "initWithTitle:action:keyEquivalent:",
                ctypes.c_void_p,
                (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p),
                nsstr("Shortcuts Paused"),
                None,
                nsstr(""),
            )
            msg(paused_item, "setEnabled:", None, (ctypes.c_bool,), False)
            msg(menu, "addItem:", None, (ctypes.c_void_p,), paused_item)

        if not self.store.bindings:
            empty_item = msg(
                msg(cls("NSMenuItem"), "alloc"),
                "initWithTitle:action:keyEquivalent:",
                ctypes.c_void_p,
                (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p),
                nsstr("No shortcuts configured"),
                None,
                nsstr(""),
            )
            msg(empty_item, "setEnabled:", None, (ctypes.c_bool,), False)
            msg(menu, "addItem:", None, (ctypes.c_void_p,), empty_item)
        else:
            for b in self.store.bindings:
                title = b["appName"] if b.get("isEnabled", True) else f"{b['appName']} (Disabled)"
                item = msg(
                    msg(cls("NSMenuItem"), "alloc"),
                    "initWithTitle:action:keyEquivalent:",
                    ctypes.c_void_p,
                    (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p),
                    nsstr(title),
                    sel("handleAction:"),
                    nsstr(b["letter"].lower()),
                )
                msg(item, "setKeyEquivalentModifierMask:", None, (NSUInteger,), NSEventModifierFlagOption)
                binding_copy = dict(b)
                _attach_action(item, self.dispatcher, lambda bc=binding_copy: self.store.trigger_binding(bc))
                icon = _app_icon(b["bundleIdentifier"], b.get("appPath"), 16.0)
                if icon:
                    msg(item, "setImage:", None, (ctypes.c_void_p,), icon)
                msg(menu, "addItem:", None, (ctypes.c_void_p,), item)

        msg(menu, "addItem:", None, (ctypes.c_void_p,), msg(cls("NSMenuItem"), "separatorItem"))

        pause_title = "Resume All Shortcuts" if self.store.is_paused else "Pause All Shortcuts"
        pause_item = msg(
            msg(cls("NSMenuItem"), "alloc"),
            "initWithTitle:action:keyEquivalent:",
            ctypes.c_void_p,
            (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p),
            nsstr(pause_title),
            sel("handleAction:"),
            nsstr(""),
        )
        _attach_action(pause_item, self.dispatcher, self.toggle_paused)
        msg(menu, "addItem:", None, (ctypes.c_void_p,), pause_item)

        cfg_item = msg(
            msg(cls("NSMenuItem"), "alloc"),
            "initWithTitle:action:keyEquivalent:",
            ctypes.c_void_p,
            (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p),
            nsstr("Configure Shortcuts…"),
            sel("handleAction:"),
            nsstr(","),
        )
        _attach_action(cfg_item, self.dispatcher, self.open_settings_window)
        msg(menu, "addItem:", None, (ctypes.c_void_p,), cfg_item)

        msg(menu, "addItem:", None, (ctypes.c_void_p,), msg(cls("NSMenuItem"), "separatorItem"))

        quit_item = msg(
            msg(cls("NSMenuItem"), "alloc"),
            "initWithTitle:action:keyEquivalent:",
            ctypes.c_void_p,
            (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p),
            nsstr("Quit AppSwitcher"),
            sel("handleAction:"),
            nsstr("q"),
        )
        _attach_action(quit_item, self.dispatcher, self.quit_app)
        msg(menu, "addItem:", None, (ctypes.c_void_p,), quit_item)

    def toggle_paused(self) -> None:
        self.store.set_paused(not self.store.is_paused)
        self._update_status_button()
        if self.settings_window:
            self._populate_settings_window()

    def quit_app(self) -> None:
        self.store.hotkey_manager.shutdown()
        nsapp = msg(cls("NSApplication"), "sharedApplication")
        msg(nsapp, "terminate:", None, (ctypes.c_void_p,), None)

    def open_settings_window(self) -> None:
        if not self.settings_window:
            style = (
                NSWindowStyleMaskTitled
                | NSWindowStyleMaskClosable
                | NSWindowStyleMaskMiniaturizable
            )
            win = msg(
                msg(cls("NSWindow"), "alloc"),
                "initWithContentRect:styleMask:backing:defer:",
                ctypes.c_void_p,
                (NSRect, NSUInteger, NSUInteger, ctypes.c_bool),
                make_rect(0, 0, 640, 500),
                style,
                NSBackingStoreBuffered,
                False,
            )
            msg(win, "setTitle:", None, (ctypes.c_void_p,), nsstr("AppSwitcher"))
            msg(win, "setReleasedWhenClosed:", None, (ctypes.c_bool,), False)
            msg(win, "center", None)
            self.settings_window = win

        self._populate_settings_window()

        nsapp = msg(cls("NSApplication"), "sharedApplication")
        msg(nsapp, "activateIgnoringOtherApps:", None, (ctypes.c_bool,), True)
        msg(self.settings_window, "makeKeyAndOrderFront:", None, (ctypes.c_void_p,), None)
        msg(self.settings_window, "orderFrontRegardless", None)

    def _populate_settings_window(self) -> None:
        if not self.settings_window:
            return
        content = msg(msg(cls("PyAppSwitcherFlippedView"), "alloc"), "initWithFrame:", ctypes.c_void_p, (NSRect,), make_rect(0, 0, 640, 500))

        # Header
        msg(content, "addSubview:", None, (ctypes.c_void_p,), _make_label("Option + Letter App Shortcuts", make_rect(20, 16, 340, 22), 15.0, bold=True))
        msg(content, "addSubview:", None, (ctypes.c_void_p,), _make_label("Show, focus, launch, or hide configured apps from anywhere.", make_rect(20, 38, 360, 18), 12.0, secondary=True))

        pause_cb = _make_checkbox("Active", make_rect(410, 22, 80, 24), not self.store.is_paused, self.dispatcher, self.toggle_paused)
        msg(content, "addSubview:", None, (ctypes.c_void_p,), pause_cb)

        add_btn = _make_button("+ Add Shortcut", make_rect(495, 18, 128, 30), self.dispatcher, lambda: self.open_editor(None), default=True)
        msg(content, "addSubview:", None, (ctypes.c_void_p,), add_btn)

        y_top = 68
        if not is_accessibility_trusted():
            banner = msg(msg(cls("NSBox"), "alloc"), "initWithFrame:", ctypes.c_void_p, (NSRect,), make_rect(20, y_top, 600, 44))
            msg(banner, "setTitlePosition:", None, (NSUInteger,), 0)
            msg(banner, "addSubview:", None, (ctypes.c_void_p,), _make_label("Optional: Grant Accessibility to unminimize Dock-minimized windows.", make_rect(10, 12, 405, 18), 11.5))
            msg(banner, "addSubview:", None, (ctypes.c_void_p,), _make_button("Grant Access", make_rect(420, 7, 102, 28), self.dispatcher, self._grant_ax))
            msg(banner, "addSubview:", None, (ctypes.c_void_p,), _make_button("Refresh", make_rect(526, 7, 66, 28), self.dispatcher, self._populate_settings_window))
            msg(content, "addSubview:", None, (ctypes.c_void_p,), banner)
            y_top += 54

        list_height = 456 - y_top
        scroll = msg(msg(cls("NSScrollView"), "alloc"), "initWithFrame:", ctypes.c_void_p, (NSRect,), make_rect(20, y_top, 600, list_height))
        msg(scroll, "setHasVerticalScroller:", None, (ctypes.c_bool,), True)
        msg(scroll, "setBorderType:", None, (NSUInteger,), 2)  # NSBezelBorder

        row_h = 46
        doc_h = max(list_height - 4, len(self.store.bindings) * row_h + 12)
        doc_view = msg(msg(cls("PyAppSwitcherFlippedView"), "alloc"), "initWithFrame:", ctypes.c_void_p, (NSRect,), make_rect(0, 0, 582, doc_h))

        if not self.store.bindings:
            msg(doc_view, "addSubview:", None, (ctypes.c_void_p,), _make_label("No shortcuts configured yet. Click '+ Add Shortcut' to start.", make_rect(115, 120, 360, 22), 13.0, secondary=True))
        else:
            for idx, b in enumerate(self.store.bindings):
                ry = 6 + idx * row_h
                row = msg(msg(cls("PyAppSwitcherFlippedView"), "alloc"), "initWithFrame:", ctypes.c_void_p, (NSRect,), make_rect(6, ry, 570, row_h - 4))

                msg(row, "addSubview:", None, (ctypes.c_void_p,), _make_label(f"⌥{b['letter']}", make_rect(8, 10, 42, 22), 14.0, bold=True))

                icon = _app_icon(b["bundleIdentifier"], b.get("appPath"), 24.0)
                if icon:
                    iv = msg(msg(cls("NSImageView"), "alloc"), "initWithFrame:", ctypes.c_void_p, (NSRect,), make_rect(54, 9, 24, 24))
                    msg(iv, "setImage:", None, (ctypes.c_void_p,), icon)
                    msg(row, "addSubview:", None, (ctypes.c_void_p,), iv)

                running = self.store.is_app_running(b["bundleIdentifier"])
                conflict = self.store.failed_bindings.get(b["id"])
                title = f"{b['appName']}  • Running" if running else b["appName"]
                if conflict is not None:
                    title += f"  (Conflict: {conflict})"

                msg(row, "addSubview:", None, (ctypes.c_void_p,), _make_label(title, make_rect(86, 4, 245, 18), 13.0, bold=True))
                msg(row, "addSubview:", None, (ctypes.c_void_p,), _make_label(b["bundleIdentifier"], make_rect(86, 22, 245, 16), 11.0, secondary=True))

                bid = b["id"]
                enabled = b.get("isEnabled", True)
                b_copy = dict(b)

                cb = _make_checkbox("", make_rect(338, 9, 24, 24), enabled, self.dispatcher, lambda i=bid, e=enabled: self._toggle_binding_enabled(i, not e))
                msg(row, "addSubview:", None, (ctypes.c_void_p,), cb)
                msg(row, "addSubview:", None, (ctypes.c_void_p,), _make_button("Test", make_rect(368, 7, 56, 28), self.dispatcher, lambda bc=b_copy: self.store.trigger_binding(bc)))
                msg(row, "addSubview:", None, (ctypes.c_void_p,), _make_button("Edit", make_rect(428, 7, 56, 28), self.dispatcher, lambda bc=b_copy: self.open_editor(bc)))
                msg(row, "addSubview:", None, (ctypes.c_void_p,), _make_button("Delete", make_rect(488, 7, 74, 28), self.dispatcher, lambda i=bid: self._delete_binding(i)))

                msg(doc_view, "addSubview:", None, (ctypes.c_void_p,), row)

        msg(scroll, "setDocumentView:", None, (ctypes.c_void_p,), doc_view)
        msg(content, "addSubview:", None, (ctypes.c_void_p,), scroll)

        msg(content, "addSubview:", None, (ctypes.c_void_p,), _make_label("Bound ⌥+Letter keys override Option special characters (like å) while active.", make_rect(20, 468, 600, 18), 11.5, secondary=True))

        msg(self.settings_window, "setContentView:", None, (ctypes.c_void_p,), content)

    def _grant_ax(self) -> None:
        is_accessibility_trusted(prompt=True)
        open_accessibility_settings()

    def _toggle_binding_enabled(self, binding_id: str, new_state: bool) -> None:
        self.store.set_enabled(binding_id, new_state)
        self._populate_settings_window()

    def _delete_binding(self, binding_id: str) -> None:
        self.store.remove_binding(binding_id)
        self._populate_settings_window()

    def open_editor(self, existing: Optional[dict]) -> None:
        self.editing_binding = existing
        self.editor_apps = self.store.discover_apps()
        if existing:
            exists_in_list = any(a["bundleIdentifier"] == existing["bundleIdentifier"] for a in self.editor_apps)
            if not exists_in_list:
                self.editor_apps.insert(0, {
                    "bundleIdentifier": existing["bundleIdentifier"],
                    "name": existing["appName"],
                    "path": existing.get("appPath") or "",
                    "isRunning": self.store.is_app_running(existing["bundleIdentifier"]),
                })

        if self.editor_window:
            msg(self.editor_window, "close", None)

        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
        win = msg(
            msg(cls("NSWindow"), "alloc"),
            "initWithContentRect:styleMask:backing:defer:",
            ctypes.c_void_p,
            (NSRect, NSUInteger, NSUInteger, ctypes.c_bool),
            make_rect(0, 0, 480, 230),
            style,
            NSBackingStoreBuffered,
            False,
        )
        msg(win, "setTitle:", None, (ctypes.c_void_p,), nsstr("Edit Shortcut" if existing else "Add Shortcut"))
        msg(win, "setDelegate:", None, (ctypes.c_void_p,), self.dispatcher)
        msg(win, "setReleasedWhenClosed:", None, (ctypes.c_bool,), False)
        msg(win, "center", None)
        self.editor_window = win

        content = msg(msg(cls("PyAppSwitcherFlippedView"), "alloc"), "initWithFrame:", ctypes.c_void_p, (NSRect,), make_rect(0, 0, 480, 230))

        # Hidden 1x1 key capture responder
        cap = msg(msg(cls("PyAppSwitcherKeyCaptureView"), "alloc"), "initWithFrame:", ctypes.c_void_p, (NSRect,), make_rect(0, 0, 1, 1))
        msg(content, "addSubview:", None, (ctypes.c_void_p,), cap)
        self.editor_capture_view = cap

        msg(content, "addSubview:", None, (ctypes.c_void_p,), _make_label("1. Option + Letter:", make_rect(20, 24, 140, 20), 13.0, bold=True))

        letter_popup = msg(msg(cls("NSPopUpButton"), "alloc"), "initWithFrame:pullsDown:", ctypes.c_void_p, (NSRect, ctypes.c_bool), make_rect(165, 20, 165, 26), False)
        _attach_action(letter_popup, self.dispatcher, self._update_conflict_label)
        default_letter = existing["letter"] if existing else next((l for l in ALL_LETTERS if not self.store.binding_for_letter(l)), "A")
        default_idx = 0
        for idx, letter in enumerate(ALL_LETTERS):
            other = self.store.binding_for_letter(letter)
            if other and (not existing or other["id"] != existing["id"]):
                item_title = f"⌥{letter} — {other['appName']}"
            else:
                item_title = f"⌥{letter}"
            msg(letter_popup, "addItemWithTitle:", None, (ctypes.c_void_p,), nsstr(item_title))
            if letter == default_letter:
                default_idx = idx
        msg(letter_popup, "selectItemAtIndex:", None, (NSInteger,), default_idx)
        msg(content, "addSubview:", None, (ctypes.c_void_p,), letter_popup)
        self.editor_letter_popup = letter_popup

        rec_btn = _make_button("Record Key", make_rect(340, 19, 120, 28), self.dispatcher, self._toggle_key_recording)
        msg(content, "addSubview:", None, (ctypes.c_void_p,), rec_btn)
        self.editor_record_btn = rec_btn

        msg(content, "addSubview:", None, (ctypes.c_void_p,), _make_label("2. Target App:", make_rect(20, 74, 140, 20), 13.0, bold=True))

        app_popup = msg(msg(cls("NSPopUpButton"), "alloc"), "initWithFrame:pullsDown:", ctypes.c_void_p, (NSRect, ctypes.c_bool), make_rect(165, 70, 210, 26), False)
        self.editor_app_popup = app_popup
        self._populate_app_popup(selected_bundle_id=existing["bundleIdentifier"] if existing else None)
        msg(content, "addSubview:", None, (ctypes.c_void_p,), app_popup)

        browse_btn = _make_button("Browse…", make_rect(382, 69, 78, 28), self.dispatcher, self._browse_app)
        msg(content, "addSubview:", None, (ctypes.c_void_p,), browse_btn)

        conflict_lbl = _make_label("", make_rect(20, 120, 440, 20), 12.0, secondary=True)
        msg(content, "addSubview:", None, (ctypes.c_void_p,), conflict_lbl)
        self.editor_conflict_label = conflict_lbl
        self._update_conflict_label()

        msg(content, "addSubview:", None, (ctypes.c_void_p,), _make_button("Cancel", make_rect(270, 178, 90, 30), self.dispatcher, self._close_editor))
        msg(content, "addSubview:", None, (ctypes.c_void_p,), _make_button("Save" if existing else "Add Shortcut", make_rect(368, 178, 96, 30), self.dispatcher, self._save_editor, default=True))

        msg(win, "setContentView:", None, (ctypes.c_void_p,), content)
        nsapp = msg(cls("NSApplication"), "sharedApplication")
        msg(nsapp, "activateIgnoringOtherApps:", None, (ctypes.c_bool,), True)
        msg(win, "makeKeyAndOrderFront:", None, (ctypes.c_void_p,), None)

    def _populate_app_popup(self, selected_bundle_id: Optional[str] = None) -> None:
        if not self.editor_app_popup:
            return
        msg(self.editor_app_popup, "removeAllItems", None)
        selected_idx = 0
        for idx, app in enumerate(self.editor_apps):
            label = f"{app['name']} (Running)" if app.get("isRunning") else app["name"]
            msg(self.editor_app_popup, "addItemWithTitle:", None, (ctypes.c_void_p,), nsstr(label))
            if selected_bundle_id and app["bundleIdentifier"] == selected_bundle_id:
                selected_idx = idx
        if self.editor_apps:
            msg(self.editor_app_popup, "selectItemAtIndex:", None, (NSInteger,), selected_idx)

    def _selected_editor_letter(self) -> str:
        if not self.editor_letter_popup:
            return "A"
        idx = msg(self.editor_letter_popup, "indexOfSelectedItem", NSInteger)
        if 0 <= idx < len(ALL_LETTERS):
            return ALL_LETTERS[idx]
        return "A"

    def _update_conflict_label(self) -> None:
        if not self.editor_conflict_label:
            return
        letter = self._selected_editor_letter()
        other = self.store.binding_for_letter(letter)
        if other and (not self.editing_binding or other["id"] != self.editing_binding["id"]):
            text = f"Note: Saving will replace existing ⌥{letter} → {other['appName']}."
        else:
            text = "Shortcut triggers with Option + Letter from any app."
        msg(self.editor_conflict_label, "setStringValue:", None, (ctypes.c_void_p,), nsstr(text))

    def _toggle_key_recording(self) -> None:
        if self.is_recording_key:
            self._stop_key_recording()
        else:
            self._start_key_recording()

    def _start_key_recording(self) -> None:
        if not self.editor_window or not self.editor_capture_view:
            return
        self.was_paused_before_record = self.store.is_paused
        self.store.set_paused(True)
        self.is_recording_key = True
        if self.editor_record_btn:
            msg(self.editor_record_btn, "setTitle:", None, (ctypes.c_void_p,), nsstr("Press Key…"))
        msg(self.editor_window, "makeFirstResponder:", ctypes.c_bool, (ctypes.c_void_p,), self.editor_capture_view)

    def _stop_key_recording(self) -> None:
        if not self.is_recording_key:
            return
        self.is_recording_key = False
        if self.editor_record_btn:
            msg(self.editor_record_btn, "setTitle:", None, (ctypes.c_void_p,), nsstr("Record Key"))
        self.store.set_paused(self.was_paused_before_record)

    def handle_recorded_keycode(self, key_code: int) -> None:
        if not self.is_recording_key:
            return
        if key_code == 53:  # Escape
            self._stop_key_recording()
            return
        letter = letter_for_keycode(key_code)
        if letter and self.editor_letter_popup:
            idx = ALL_LETTERS.index(letter)
            msg(self.editor_letter_popup, "selectItemAtIndex:", None, (NSInteger,), idx)
            self._update_conflict_label()
            self._stop_key_recording()

    def _browse_app(self) -> None:
        self._stop_key_recording()
        panel = msg(cls("NSOpenPanel"), "openPanel")
        msg(panel, "setTitle:", None, (ctypes.c_void_p,), nsstr("Select Application"))
        msg(panel, "setAllowsMultipleSelection:", None, (ctypes.c_bool,), False)
        msg(panel, "setCanChooseDirectories:", None, (ctypes.c_bool,), False)
        msg(panel, "setDirectoryURL:", None, (ctypes.c_void_p,), nsurl_from_path("/Applications"))
        # Allow .app bundles
        arr = msg(cls("NSArray"), "arrayWithObject:", ctypes.c_void_p, (ctypes.c_void_p,), nsstr("app"))
        msg(panel, "setAllowedFileTypes:", None, (ctypes.c_void_p,), arr)

        if msg(panel, "runModal", NSInteger) == NSModalResponseOK:
            url = msg(panel, "URL")
            if url:
                path = from_nsstr(msg(url, "path"))
                cand = self.store.app_candidate_from_path(path)
                if cand:
                    self.editor_apps = [a for a in self.editor_apps if a["bundleIdentifier"] != cand["bundleIdentifier"]]
                    self.editor_apps.insert(0, cand)
                    self._populate_app_popup(selected_bundle_id=cand["bundleIdentifier"])

    def _save_editor(self) -> None:
        self._stop_key_recording()
        if not self.editor_app_popup or not self.editor_apps:
            return
        app_idx = msg(self.editor_app_popup, "indexOfSelectedItem", NSInteger)
        if not (0 <= app_idx < len(self.editor_apps)):
            return
        app = self.editor_apps[app_idx]
        letter = self._selected_editor_letter()

        self.store.upsert_binding(
            letter=letter,
            bundle_id=app["bundleIdentifier"],
            app_name=app["name"],
            app_path=app.get("path"),
            binding_id=self.editing_binding["id"] if self.editing_binding else None,
            is_enabled=self.editing_binding.get("isEnabled", True) if self.editing_binding else True,
        )
        self._close_editor()
        self._populate_settings_window()

    def _close_editor(self) -> None:
        self._stop_key_recording()
        if self.editor_window:
            msg(self.editor_window, "close", None)

    def on_window_closed(self, win: int) -> None:
        if win and self.editor_window and win == self.editor_window:
            self._stop_key_recording()
