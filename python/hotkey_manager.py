import ctypes
from typing import Callable, Dict, List, Optional

from key_mapper import keycode_for_letter
from objc_bridge import carbon

HOTKEY_SIGNATURE = 0x41505357  # 'APSW'
K_EVENT_CLASS_KEYBOARD = 0x6B657962  # 'keyb'
K_EVENT_HOTKEY_PRESSED = 5
K_EVENT_PARAM_DIRECT_OBJECT = 0x2D2D2D2D  # '----'
TYPE_EVENT_HOTKEY_ID = 0x686B6964  # 'hkid'
OPTION_KEY_MASK = 1 << 11
EVENT_NOT_HANDLED_ERR = -9874
PARAM_ERR = -50


class EventTypeSpec(ctypes.Structure):
    _fields_ = [
        ("eventClass", ctypes.c_uint32),
        ("eventKind", ctypes.c_uint32),
    ]


class EventHotKeyID(ctypes.Structure):
    _fields_ = [
        ("signature", ctypes.c_uint32),
        ("id", ctypes.c_uint32),
    ]


EVENT_HANDLER_UPP = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
)

carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
carbon.GetApplicationEventTarget.argtypes = []

carbon.InstallEventHandler.restype = ctypes.c_int32
carbon.InstallEventHandler.argtypes = [
    ctypes.c_void_p,
    EVENT_HANDLER_UPP,
    ctypes.c_uint32,
    ctypes.POINTER(EventTypeSpec),
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_void_p),
]

carbon.RemoveEventHandler.restype = ctypes.c_int32
carbon.RemoveEventHandler.argtypes = [ctypes.c_void_p]

carbon.GetEventParameter.restype = ctypes.c_int32
carbon.GetEventParameter.argtypes = [
    ctypes.c_void_p,
    ctypes.c_uint32,
    ctypes.c_uint32,
    ctypes.c_void_p,
    ctypes.c_uint32,
    ctypes.c_void_p,
    ctypes.c_void_p,
]

carbon.RegisterEventHotKey.restype = ctypes.c_int32
carbon.RegisterEventHotKey.argtypes = [
    ctypes.c_uint32,
    ctypes.c_uint32,
    EventHotKeyID,
    ctypes.c_void_p,
    ctypes.c_uint32,
    ctypes.POINTER(ctypes.c_void_p),
]

carbon.UnregisterEventHotKey.restype = ctypes.c_int32
carbon.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]


class HotKeyManager:
    def __init__(self, on_trigger: Callable[[dict], None]) -> None:
        self._on_trigger = on_trigger
        self._handler_ref = ctypes.c_void_p()
        self._registered_refs: Dict[int, ctypes.c_void_p] = {}
        self._id_to_binding: Dict[int, dict] = {}
        self._next_id = 1
        self.failed_bindings: Dict[str, int] = {}
        self._is_paused = False
        self._bindings: List[dict] = []

        self._handler_cb = EVENT_HANDLER_UPP(self._handle_event)
        self._install_handler()

    def _install_handler(self) -> None:
        spec = EventTypeSpec(K_EVENT_CLASS_KEYBOARD, K_EVENT_HOTKEY_PRESSED)
        carbon.InstallEventHandler(
            carbon.GetApplicationEventTarget(),
            self._handler_cb,
            1,
            ctypes.byref(spec),
            None,
            ctypes.byref(self._handler_ref),
        )

    def _handle_event(self, _next_handler: int, event_ref: int, _user_data: int) -> int:
        if not event_ref:
            return EVENT_NOT_HANDLED_ERR
        hk_id = EventHotKeyID()
        status = carbon.GetEventParameter(
            event_ref,
            K_EVENT_PARAM_DIRECT_OBJECT,
            TYPE_EVENT_HOTKEY_ID,
            None,
            ctypes.sizeof(EventHotKeyID),
            None,
            ctypes.byref(hk_id),
        )
        if status != 0 or hk_id.signature != HOTKEY_SIGNATURE:
            return EVENT_NOT_HANDLED_ERR

        if not self._is_paused:
            binding = self._id_to_binding.get(hk_id.id)
            if binding is not None:
                self._on_trigger(binding)
        return 0

    def update(self, bindings: List[dict], is_paused: bool) -> Dict[str, int]:
        self._bindings = list(bindings)
        self._is_paused = is_paused
        return self.reregister_all()

    def reregister_all(self) -> Dict[str, int]:
        self.unregister_all()
        self.failed_bindings.clear()

        if self._is_paused:
            return self.failed_bindings

        target = carbon.GetApplicationEventTarget()
        for binding in self._bindings:
            if not binding.get("isEnabled", True):
                continue

            key_code = keycode_for_letter(binding.get("letter", ""))
            if key_code is None:
                self.failed_bindings[binding["id"]] = PARAM_ERR
                continue

            numeric_id = self._next_id
            self._next_id = (self._next_id + 1) & 0xFFFFFFFF
            if self._next_id == 0:
                self._next_id = 1

            hk_id = EventHotKeyID(HOTKEY_SIGNATURE, numeric_id)
            ref = ctypes.c_void_p()
            status = carbon.RegisterEventHotKey(
                key_code,
                OPTION_KEY_MASK,
                hk_id,
                target,
                0,
                ctypes.byref(ref),
            )
            if status == 0 and ref.value:
                self._registered_refs[numeric_id] = ref
                self._id_to_binding[numeric_id] = binding
            else:
                self.failed_bindings[binding["id"]] = status

        return self.failed_bindings

    def unregister_all(self) -> None:
        for ref in self._registered_refs.values():
            carbon.UnregisterEventHotKey(ref)
        self._registered_refs.clear()
        self._id_to_binding.clear()

    def shutdown(self) -> None:
        self.unregister_all()
        if self._handler_ref.value:
            carbon.RemoveEventHandler(self._handler_ref)
            self._handler_ref = ctypes.c_void_p()
