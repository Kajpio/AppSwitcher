import ctypes
from typing import Dict, Optional

from objc_bridge import carbon, cf

# ANSI fallback virtual key codes (from HIToolbox/Events.h)
ANSI_FALLBACK_MAP: Dict[str, int] = {
    "A": 0x00,
    "B": 0x0B,
    "C": 0x08,
    "D": 0x02,
    "E": 0x0E,
    "F": 0x03,
    "G": 0x05,
    "H": 0x04,
    "I": 0x22,
    "J": 0x26,
    "K": 0x28,
    "L": 0x25,
    "M": 0x2E,
    "N": 0x2D,
    "O": 0x1F,
    "P": 0x23,
    "Q": 0x0C,
    "R": 0x0F,
    "S": 0x01,
    "T": 0x11,
    "U": 0x20,
    "V": 0x09,
    "W": 0x0D,
    "X": 0x07,
    "Y": 0x10,
    "Z": 0x06,
}

ALL_LETTERS = [chr(code) for code in range(ord("A"), ord("Z") + 1)]

# Carbon / TIS / UCKeyTranslate signatures
carbon.TISCopyCurrentKeyboardLayoutInputSource.restype = ctypes.c_void_p
carbon.TISCopyCurrentKeyboardLayoutInputSource.argtypes = []

carbon.TISGetInputSourceProperty.restype = ctypes.c_void_p
carbon.TISGetInputSourceProperty.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

carbon.LMGetKbdType.restype = ctypes.c_uint8
carbon.LMGetKbdType.argtypes = []

carbon.UCKeyTranslate.restype = ctypes.c_int32
carbon.UCKeyTranslate.argtypes = [
    ctypes.c_void_p,
    ctypes.c_uint16,
    ctypes.c_uint16,
    ctypes.c_uint32,
    ctypes.c_uint32,
    ctypes.c_uint32,
    ctypes.POINTER(ctypes.c_uint32),
    ctypes.c_ulong,
    ctypes.POINTER(ctypes.c_ulong),
    ctypes.POINTER(ctypes.c_uint16),
]

kTISPropertyUnicodeKeyLayoutData = ctypes.c_void_p.in_dll(carbon, "kTISPropertyUnicodeKeyLayoutData")
kUCKeyActionDisplay = 3
kUCKeyTranslateNoDeadKeysBit = 1 << 0


def normalize_letter(raw: str) -> str:
    for ch in raw.upper():
        if "A" <= ch <= "Z":
            return ch
    return ""


def _translate_keycode(key_code: int) -> Optional[str]:
    input_source = carbon.TISCopyCurrentKeyboardLayoutInputSource()
    if not input_source:
        return None
    try:
        layout_data = carbon.TISGetInputSourceProperty(input_source, kTISPropertyUnicodeKeyLayoutData)
        if not layout_data:
            return None
        layout_ptr = cf.CFDataGetBytePtr(layout_data)
        if not layout_ptr:
            return None

        dead_key_state = ctypes.c_uint32(0)
        actual_len = ctypes.c_ulong(0)
        chars = (ctypes.c_uint16 * 4)()

        status = carbon.UCKeyTranslate(
            layout_ptr,
            ctypes.c_uint16(key_code),
            kUCKeyActionDisplay,
            0,
            ctypes.c_uint32(carbon.LMGetKbdType()),
            kUCKeyTranslateNoDeadKeysBit,
            ctypes.byref(dead_key_state),
            4,
            ctypes.byref(actual_len),
            chars,
        )
        if status != 0 or actual_len.value == 0:
            return None
        return "".join(chr(chars[i]) for i in range(actual_len.value))
    finally:
        cf.CFRelease(input_source)


def _current_layout_map() -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    for code in range(128):
        text = _translate_keycode(code)
        if not text:
            continue
        letter = normalize_letter(text)
        if letter and letter not in mapping:
            mapping[letter] = code
    return mapping


def keycode_for_letter(letter: str) -> Optional[int]:
    norm = normalize_letter(letter)
    if not norm:
        return None
    layout_map = _current_layout_map()
    if norm in layout_map:
        return layout_map[norm]
    return ANSI_FALLBACK_MAP.get(norm)


def letter_for_keycode(key_code: int) -> Optional[str]:
    text = _translate_keycode(key_code)
    if text:
        norm = normalize_letter(text)
        if norm:
            return norm
    for letter, code in ANSI_FALLBACK_MAP.items():
        if code == key_code:
            return letter
    return None
