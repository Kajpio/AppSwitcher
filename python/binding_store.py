import ctypes
import json
import os
import plistlib
import uuid
from typing import Dict, List, Optional

from app_toggler import NSApplicationActivationPolicyRegular, toggle_binding
from hotkey_manager import HotKeyManager
from key_mapper import normalize_letter
from objc_bridge import NSInteger, NSUInteger, cls, from_nsstr, msg, nsstr


def _storage_path() -> str:
    app_support = os.path.expanduser("~/Library/Application Support/AppSwitcher")
    return os.path.join(app_support, "bindings.json")


def _prefs_path() -> str:
    app_support = os.path.expanduser("~/Library/Application Support/AppSwitcher")
    return os.path.join(app_support, "prefs.json")


class BindingStore:
    def __init__(self) -> None:
        self.bindings: List[dict] = self._load_bindings()
        self.is_paused: bool = self._load_paused()
        self.failed_bindings: Dict[str, int] = {}
        self.hotkey_manager = HotKeyManager(on_trigger=self.trigger_binding)
        self.sync_hotkeys()

    def sync_hotkeys(self) -> None:
        self.failed_bindings = self.hotkey_manager.update(self.bindings, self.is_paused)

    def set_paused(self, paused: bool) -> None:
        self.is_paused = bool(paused)
        self._save_paused()
        self.sync_hotkeys()

    def binding_for_letter(self, letter: str) -> Optional[dict]:
        norm = normalize_letter(letter)
        for b in self.bindings:
            if b.get("letter") == norm:
                return b
        return None

    def upsert_binding(
        self,
        letter: str,
        bundle_id: str,
        app_name: str,
        app_path: Optional[str],
        binding_id: Optional[str] = None,
        is_enabled: bool = True,
    ) -> dict:
        norm = normalize_letter(letter)
        bid = binding_id or str(uuid.uuid4())
        entry = {
            "id": bid,
            "letter": norm,
            "bundleIdentifier": bundle_id,
            "appName": app_name,
            "appPath": app_path,
            "isEnabled": is_enabled,
        }
        self.bindings = [
            b for b in self.bindings if b.get("id") != bid and b.get("letter") != norm
        ]
        self.bindings.append(entry)
        self.bindings.sort(key=lambda b: b.get("letter", ""))
        self._save_bindings()
        self.sync_hotkeys()
        return entry

    def set_enabled(self, binding_id: str, enabled: bool) -> None:
        for b in self.bindings:
            if b.get("id") == binding_id:
                b["isEnabled"] = bool(enabled)
                break
        self._save_bindings()
        self.sync_hotkeys()

    def remove_binding(self, binding_id: str) -> None:
        self.bindings = [b for b in self.bindings if b.get("id") != binding_id]
        self._save_bindings()
        self.sync_hotkeys()

    def trigger_binding(self, binding: dict) -> None:
        toggle_binding(binding)

    def is_app_running(self, bundle_id: str) -> bool:
        arr = msg(
            cls("NSRunningApplication"),
            "runningApplicationsWithBundleIdentifier:",
            ctypes.c_void_p,
            (ctypes.c_void_p,),
            nsstr(bundle_id),
        )
        return bool(arr and msg(arr, "count", NSUInteger) > 0)

    def app_candidate_from_path(self, app_path: str) -> Optional[dict]:
        if not app_path.lower().endswith(".app") or not os.path.isdir(app_path):
            return None
        plist_path = os.path.join(app_path, "Contents", "Info.plist")
        if not os.path.isfile(plist_path):
            return None
        try:
            with open(plist_path, "rb") as f:
                info = plistlib.load(f)
        except Exception:
            return None
        bundle_id = info.get("CFBundleIdentifier")
        if not bundle_id:
            return None
        name = (
            info.get("CFBundleDisplayName")
            or info.get("CFBundleName")
            or os.path.splitext(os.path.basename(app_path))[0]
        )
        return {
            "bundleIdentifier": bundle_id,
            "name": name,
            "path": app_path,
            "isRunning": self.is_app_running(bundle_id),
        }

    def discover_apps(self) -> List[dict]:
        by_bundle: Dict[str, dict] = {}

        # Running regular apps
        ws = msg(cls("NSWorkspace"), "sharedWorkspace")
        running_arr = msg(ws, "runningApplications")
        if running_arr:
            count = msg(running_arr, "count", NSUInteger)
            for i in range(count):
                app = msg(running_arr, "objectAtIndex:", ctypes.c_void_p, (NSUInteger,), i)
                if not app:
                    continue
                if msg(app, "activationPolicy", NSInteger) != NSApplicationActivationPolicyRegular:
                    continue
                bid_ns = msg(app, "bundleIdentifier")
                url_ns = msg(app, "bundleURL")
                if not bid_ns or not url_ns:
                    continue
                bid = from_nsstr(bid_ns)
                path = from_nsstr(msg(url_ns, "path"))
                name_ns = msg(app, "localizedName")
                name = from_nsstr(name_ns) or os.path.splitext(os.path.basename(path))[0]
                if bid and path:
                    by_bundle[bid] = {
                        "bundleIdentifier": bid,
                        "name": name,
                        "path": path,
                        "isRunning": True,
                    }

        search_dirs = [
            "/Applications",
            "/System/Applications",
            "/System/Applications/Utilities",
            os.path.expanduser("~/Applications"),
        ]
        for folder in search_dirs:
            if not os.path.isdir(folder):
                continue
            try:
                entries = os.listdir(folder)
            except OSError:
                continue
            for entry in entries:
                if not entry.lower().endswith(".app"):
                    continue
                candidate = self.app_candidate_from_path(os.path.join(folder, entry))
                if candidate and candidate["bundleIdentifier"] not in by_bundle:
                    by_bundle[candidate["bundleIdentifier"]] = candidate

        return sorted(
            by_bundle.values(),
            key=lambda c: (not c["isRunning"], c["name"].lower()),
        )

    def _load_bindings(self) -> List[dict]:
        path = _storage_path()
        if not os.path.isfile(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                data.sort(key=lambda b: b.get("letter", ""))
                return data
        except Exception:
            pass
        return []

    def _save_bindings(self) -> None:
        path = _storage_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.bindings, f, indent=2, sort_keys=True)

    def _load_paused(self) -> bool:
        path = _prefs_path()
        if not os.path.isfile(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return bool(data.get("isPaused", False))
        except Exception:
            return False

    def _save_paused(self) -> None:
        path = _prefs_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"isPaused": self.is_paused}, f, indent=2)
