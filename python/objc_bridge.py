import ctypes
import ctypes.util
from typing import Any, Callable, Dict, Tuple

objc = ctypes.CDLL(ctypes.util.find_library("objc"))
cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
appkit = ctypes.CDLL(ctypes.util.find_library("AppKit"))
foundation = ctypes.CDLL(ctypes.util.find_library("Foundation"))
cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
appserv = ctypes.CDLL(ctypes.util.find_library("ApplicationServices"))
carbon = ctypes.CDLL(ctypes.util.find_library("Carbon"))

CGFloat = ctypes.c_double
NSUInteger = ctypes.c_uint64
NSInteger = ctypes.c_int64


class NSPoint(ctypes.Structure):
    _fields_ = [("x", CGFloat), ("y", CGFloat)]


class NSSize(ctypes.Structure):
    _fields_ = [("width", CGFloat), ("height", CGFloat)]


class NSRect(ctypes.Structure):
    _fields_ = [("origin", NSPoint), ("size", NSSize)]


def make_rect(x: float, y: float, w: float, h: float) -> NSRect:
    return NSRect(NSPoint(x, y), NSSize(w, h))


# Objective-C runtime signatures
objc.objc_getClass.restype = ctypes.c_void_p
objc.objc_getClass.argtypes = [ctypes.c_char_p]

objc.sel_registerName.restype = ctypes.c_void_p
objc.sel_registerName.argtypes = [ctypes.c_char_p]

objc.objc_allocateClassPair.restype = ctypes.c_void_p
objc.objc_allocateClassPair.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]

objc.objc_registerClassPair.restype = None
objc.objc_registerClassPair.argtypes = [ctypes.c_void_p]

objc.class_addMethod.restype = ctypes.c_bool
objc.class_addMethod.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p]

# CoreFoundation signatures
cf.CFRelease.restype = None
cf.CFRelease.argtypes = [ctypes.c_void_p]

cf.CFRetain.restype = ctypes.c_void_p
cf.CFRetain.argtypes = [ctypes.c_void_p]

cf.CFArrayGetCount.restype = ctypes.c_long
cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]

cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]

cf.CFDictionaryGetValue.restype = ctypes.c_void_p
cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

cf.CFBooleanGetValue.restype = ctypes.c_bool
cf.CFBooleanGetValue.argtypes = [ctypes.c_void_p]

cf.CFGetTypeID.restype = ctypes.c_ulong
cf.CFGetTypeID.argtypes = [ctypes.c_void_p]

cf.CFBooleanGetTypeID.restype = ctypes.c_ulong
cf.CFBooleanGetTypeID.argtypes = []

cf.CFNumberGetTypeID.restype = ctypes.c_ulong
cf.CFNumberGetTypeID.argtypes = []

cf.CFNumberGetValue.restype = ctypes.c_bool
cf.CFNumberGetValue.argtypes = [ctypes.c_void_p, ctypes.c_int32, ctypes.c_void_p]

cf.CFDataGetLength.restype = ctypes.c_long
cf.CFDataGetLength.argtypes = [ctypes.c_void_p]

cf.CFDataGetBytePtr.restype = ctypes.c_void_p
cf.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]

cf.CFStringCreateWithCString.restype = ctypes.c_void_p
cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]

cf.CFStringGetCString.restype = ctypes.c_bool
cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]

kCFStringEncodingUTF8 = 0x08000100
kCFNumberSInt32Type = 3
kCFNumberFloat64Type = 6
kCFBooleanTrue = ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue")
kCFBooleanFalse = ctypes.c_void_p.in_dll(cf, "kCFBooleanFalse")

_SEL_CACHE: Dict[str, int] = {}
_CLS_CACHE: Dict[str, int] = {}
_MSG_CACHE: Dict[Tuple[Any, Tuple[Any, ...]], Any] = {}
_CALLBACK_KEEPALIVE: list = []


def cls(name: str) -> int:
    c = _CLS_CACHE.get(name)
    if c is None:
        c = objc.objc_getClass(name.encode("utf-8"))
        _CLS_CACHE[name] = c
    return c


def sel(name: str) -> int:
    s = _SEL_CACHE.get(name)
    if s is None:
        s = objc.sel_registerName(name.encode("utf-8"))
        _SEL_CACHE[name] = s
    return s


def msg(obj: int, selector: str, restype: Any = ctypes.c_void_p, argtypes: Tuple[Any, ...] = (), *args: Any) -> Any:
    if not obj:
        return None
    key = (restype, argtypes)
    fn = _MSG_CACHE.get(key)
    if fn is None:
        fn = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)(
            ("objc_msgSend", objc)
        )
        _MSG_CACHE[key] = fn
    return fn(obj, sel(selector), *args)


def nsstr(text: str) -> int:
    return msg(cls("NSString"), "stringWithUTF8String:", ctypes.c_void_p, (ctypes.c_char_p,), text.encode("utf-8"))


def from_nsstr(ns_obj: int) -> str:
    if not ns_obj:
        return ""
    raw = msg(ns_obj, "UTF8String", ctypes.c_char_p)
    return raw.decode("utf-8", errors="replace") if raw else ""


def cfstr(text: str) -> int:
    return cf.CFStringCreateWithCString(None, text.encode("utf-8"), kCFStringEncodingUTF8)


def from_cfstr(cf_obj: int) -> str:
    if not cf_obj:
        return ""
    buf = ctypes.create_string_buffer(2048)
    if cf.CFStringGetCString(cf_obj, buf, 2048, kCFStringEncodingUTF8):
        return buf.value.decode("utf-8", errors="replace")
    return ""


def nsurl_from_path(path: str) -> int:
    return msg(cls("NSURL"), "fileURLWithPath:", ctypes.c_void_p, (ctypes.c_void_p,), nsstr(path))


def alloc_init(class_name: str) -> int:
    obj = msg(cls(class_name), "alloc")
    return msg(obj, "init")


def create_autorelease_pool() -> int:
    return alloc_init("NSAutoreleasePool")


def drain_autorelease_pool(pool: int) -> None:
    if pool:
        msg(pool, "drain", None)


def create_objc_class(name: str, superclass: str, methods: Dict[str, Tuple[Any, bytes, Callable]]) -> int:
    existing = objc.objc_getClass(name.encode("utf-8"))
    if existing:
        return existing
    new_cls = objc.objc_allocateClassPair(cls(superclass), name.encode("utf-8"), 0)
    for selector_name, (fn_type, encoding, py_func) in methods.items():
        c_cb = fn_type(py_func)
        _CALLBACK_KEEPALIVE.append(c_cb)
        objc.class_addMethod(new_cls, sel(selector_name), ctypes.cast(c_cb, ctypes.c_void_p), encoding)
    objc.objc_registerClassPair(new_cls)
    _CLS_CACHE[name] = new_cls
    return new_cls
