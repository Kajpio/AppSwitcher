import ctypes
import os
from typing import List, Optional, Tuple

from objc_bridge import (
    NSInteger,
    NSUInteger,
    appserv,
    cf,
    cfstr,
    cg,
    cls,
    kCFBooleanFalse,
    kCFBooleanTrue,
    kCFNumberFloat64Type,
    kCFNumberSInt32Type,
    msg,
    nsstr,
    nsurl_from_path,
)

# ApplicationServices / Accessibility signatures
appserv.AXIsProcessTrusted.restype = ctypes.c_bool
appserv.AXIsProcessTrusted.argtypes = []

appserv.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
appserv.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]

appserv.AXUIElementCreateApplication.restype = ctypes.c_void_p
appserv.AXUIElementCreateApplication.argtypes = [ctypes.c_int32]

appserv.AXUIElementCopyAttributeValue.restype = ctypes.c_int32
appserv.AXUIElementCopyAttributeValue.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_void_p),
]

appserv.AXUIElementSetAttributeValue.restype = ctypes.c_int32
appserv.AXUIElementSetAttributeValue.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
]

appserv.AXUIElementPerformAction.restype = ctypes.c_int32
appserv.AXUIElementPerformAction.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

# CoreGraphics window inspection
cg.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]

kCGWindowListOptionAll = 0
kCGNullWindowID = 0
kCGWindowOwnerPID = ctypes.c_void_p.in_dll(cg, "kCGWindowOwnerPID")
kCGWindowLayer = ctypes.c_void_p.in_dll(cg, "kCGWindowLayer")
kCGWindowIsOnscreen = ctypes.c_void_p.in_dll(cg, "kCGWindowIsOnscreen")
kCGWindowBounds = ctypes.c_void_p.in_dll(cg, "kCGWindowBounds")

NSApplicationActivateIgnoringOtherApps = 1 << 1
NSApplicationActivationPolicyRegular = 0


def is_accessibility_trusted(prompt: bool = False) -> bool:
    if not prompt:
        return bool(appserv.AXIsProcessTrusted())
    key = nsstr("AXTrustedCheckOptionPrompt")
    opts = msg(
        cls("NSDictionary"),
        "dictionaryWithObject:forKey:",
        ctypes.c_void_p,
        (ctypes.c_void_p, ctypes.c_void_p),
        kCFBooleanTrue,
        key,
    )
    return bool(appserv.AXIsProcessTrustedWithOptions(opts))


def open_accessibility_settings() -> None:
    url = msg(
        cls("NSURL"),
        "URLWithString:",
        ctypes.c_void_p,
        (ctypes.c_void_p,),
        nsstr("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"),
    )
    if url:
        ws = msg(cls("NSWorkspace"), "sharedWorkspace")
        msg(ws, "openURL:", ctypes.c_bool, (ctypes.c_void_p,), url)


def _find_running_app(bundle_id: str) -> Optional[int]:
    arr = msg(
        cls("NSRunningApplication"),
        "runningApplicationsWithBundleIdentifier:",
        ctypes.c_void_p,
        (ctypes.c_void_p,),
        nsstr(bundle_id),
    )
    if not arr:
        return None
    count = msg(arr, "count", NSUInteger)
    fallback = None
    for i in range(count):
        app = msg(arr, "objectAtIndex:", ctypes.c_void_p, (NSUInteger,), i)
        if not app:
            continue
        if msg(app, "isTerminated", ctypes.c_bool):
            continue
        policy = msg(app, "activationPolicy", NSInteger)
        if policy == NSApplicationActivationPolicyRegular:
            return app
        if fallback is None:
            fallback = app
    return fallback


def _resolve_app_url(binding: dict) -> Optional[int]:
    saved_path = binding.get("appPath")
    if saved_path and os.path.exists(saved_path):
        return nsurl_from_path(saved_path)
    ws = msg(cls("NSWorkspace"), "sharedWorkspace")
    return msg(
        ws,
        "URLForApplicationWithBundleIdentifier:",
        ctypes.c_void_p,
        (ctypes.c_void_p,),
        nsstr(binding["bundleIdentifier"]),
    )


def _open_app_url(app_url: int) -> None:
    ws = msg(cls("NSWorkspace"), "sharedWorkspace")
    cfg = msg(cls("NSWorkspaceOpenConfiguration"), "configuration")
    msg(cfg, "setActivates:", None, (ctypes.c_bool,), True)
    msg(
        ws,
        "openApplicationAtURL:configuration:completionHandler:",
        None,
        (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p),
        app_url,
        cfg,
        None,
    )


def _activate_app(running_app: int) -> None:
    msg(running_app, "activateWithOptions:", ctypes.c_bool, (NSUInteger,), NSApplicationActivateIgnoringOtherApps)


def _reopen_and_activate(running_app: int, binding: dict) -> None:
    app_url = msg(running_app, "bundleURL") or _resolve_app_url(binding)
    if app_url:
        _open_app_url(app_url)
    else:
        _activate_app(running_app)


def _fetch_ax_windows(pid: int) -> List[int]:
    app_elem = appserv.AXUIElementCreateApplication(pid)
    if not app_elem:
        return []
    attr = cfstr("AXWindows")
    val = ctypes.c_void_p()
    windows: List[int] = []
    try:
        err = appserv.AXUIElementCopyAttributeValue(app_elem, attr, ctypes.byref(val))
        if err == 0 and val.value:
            count = cf.CFArrayGetCount(val.value)
            for i in range(count):
                w = cf.CFArrayGetValueAtIndex(val.value, i)
                if w:
                    cf.CFRetain(w)
                    windows.append(w)
            cf.CFRelease(val.value)
    finally:
        cf.CFRelease(attr)
        cf.CFRelease(app_elem)
    return windows


def _is_ax_window_minimized(win_elem: int) -> bool:
    attr = cfstr("AXMinimized")
    val = ctypes.c_void_p()
    try:
        err = appserv.AXUIElementCopyAttributeValue(win_elem, attr, ctypes.byref(val))
        if err == 0 and val.value:
            try:
                if cf.CFGetTypeID(val.value) == cf.CFBooleanGetTypeID():
                    return bool(cf.CFBooleanGetValue(val.value))
            finally:
                cf.CFRelease(val.value)
        return False
    finally:
        cf.CFRelease(attr)


def _unminimize_and_focus(win_elem: int, running_app: int) -> None:
    attr = cfstr("AXMinimized")
    action = cfstr("AXRaise")
    try:
        appserv.AXUIElementSetAttributeValue(win_elem, attr, kCFBooleanFalse)
        _activate_app(running_app)
        appserv.AXUIElementPerformAction(win_elem, action)
    finally:
        cf.CFRelease(attr)
        cf.CFRelease(action)


def _cfnum_int(cf_val: int) -> Optional[int]:
    if not cf_val or cf.CFGetTypeID(cf_val) != cf.CFNumberGetTypeID():
        return None
    out = ctypes.c_int32()
    if cf.CFNumberGetValue(cf_val, kCFNumberSInt32Type, ctypes.byref(out)):
        return int(out.value)
    return None


def _cfnum_float(cf_val: int) -> Optional[float]:
    if not cf_val or cf.CFGetTypeID(cf_val) != cf.CFNumberGetTypeID():
        return None
    out = ctypes.c_double()
    if cf.CFNumberGetValue(cf_val, kCFNumberFloat64Type, ctypes.byref(out)):
        return float(out.value)
    return None


def _inspect_cg_windows(pid: int) -> Tuple[bool, bool]:
    info_list = cg.CGWindowListCopyWindowInfo(kCGWindowListOptionAll, kCGNullWindowID)
    if not info_list:
        return (False, False)

    has_any = False
    has_onscreen = False
    w_key = cfstr("Width")
    h_key = cfstr("Height")
    try:
        count = cf.CFArrayGetCount(info_list)
        for i in range(count):
            d = cf.CFArrayGetValueAtIndex(info_list, i)
            if not d:
                continue
            owner = _cfnum_int(cf.CFDictionaryGetValue(d, kCGWindowOwnerPID))
            if owner != pid:
                continue
            layer = _cfnum_int(cf.CFDictionaryGetValue(d, kCGWindowLayer))
            if layer != 0:
                continue
            bounds = cf.CFDictionaryGetValue(d, kCGWindowBounds)
            if bounds:
                width = _cfnum_float(cf.CFDictionaryGetValue(bounds, w_key)) or 0.0
                height = _cfnum_float(cf.CFDictionaryGetValue(bounds, h_key)) or 0.0
                if width <= 2.0 or height <= 2.0:
                    continue
            has_any = True
            onscreen_ref = cf.CFDictionaryGetValue(d, kCGWindowIsOnscreen)
            if onscreen_ref and cf.CFGetTypeID(onscreen_ref) == cf.CFBooleanGetTypeID():
                if cf.CFBooleanGetValue(onscreen_ref):
                    has_onscreen = True
    finally:
        cf.CFRelease(w_key)
        cf.CFRelease(h_key)
        cf.CFRelease(info_list)
    return (has_any, has_onscreen)


def toggle_binding(binding: dict) -> None:
    running_app = _find_running_app(binding["bundleIdentifier"])
    if not running_app:
        app_url = _resolve_app_url(binding)
        if app_url:
            _open_app_url(app_url)
        else:
            msg(None, "")  # no-op
            from objc_bridge import appkit
            appkit.NSBeep()
        return

    ws = msg(cls("NSWorkspace"), "sharedWorkspace")
    front = msg(ws, "frontmostApplication")
    pid = msg(running_app, "processIdentifier", ctypes.c_int32)
    front_pid = msg(front, "processIdentifier", ctypes.c_int32) if front else -1
    is_frontmost = (pid == front_pid)
    is_hidden = bool(msg(running_app, "isHidden", ctypes.c_bool))

    if is_accessibility_trusted():
        windows = _fetch_ax_windows(pid)
        try:
            non_minimized = [w for w in windows if not _is_ax_window_minimized(w)]
            minimized = [w for w in windows if _is_ax_window_minimized(w)]

            if is_frontmost and not is_hidden:
                if non_minimized:
                    msg(running_app, "hide", ctypes.c_bool)
                elif minimized:
                    _unminimize_and_focus(minimized[0], running_app)
                else:
                    _reopen_and_activate(running_app, binding)
                return

            if is_hidden:
                msg(running_app, "unhide", ctypes.c_bool)

            if non_minimized:
                _activate_app(running_app)
            elif minimized:
                _unminimize_and_focus(minimized[0], running_app)
            else:
                _reopen_and_activate(running_app, binding)
        finally:
            for w in windows:
                cf.CFRelease(w)
    else:
        _has_any, has_onscreen = _inspect_cg_windows(pid)
        if is_frontmost and not is_hidden:
            if has_onscreen:
                msg(running_app, "hide", ctypes.c_bool)
            else:
                _reopen_and_activate(running_app, binding)
            return

        if is_hidden:
            msg(running_app, "unhide", ctypes.c_bool)
            _activate_app(running_app)
            return

        if has_onscreen:
            _activate_app(running_app)
        else:
            _reopen_and_activate(running_app, binding)
