import ctypes
import os
import signal
import sys

from app_ui import AppUIController
from binding_store import BindingStore
from objc_bridge import NSInteger, cls, create_autorelease_pool, drain_autorelease_pool, msg

NSApplicationActivationPolicyAccessory = 1


def _pid_file_path() -> str:
    app_support = os.path.expanduser("~/Library/Application Support/AppSwitcher")
    return os.path.join(app_support, "appswitcher.pid")


def _signal_existing_instance() -> bool:
    pid_path = _pid_file_path()
    if not os.path.isfile(pid_path):
        return False
    try:
        with open(pid_path, "r", encoding="utf-8") as f:
            pid = int(f.read().strip())
        if pid <= 0 or pid == os.getpid():
            return False
        os.kill(pid, signal.SIGUSR1)
        return True
    except OSError:
        return False


def _write_pid_file() -> None:
    pid_path = _pid_file_path()
    os.makedirs(os.path.dirname(pid_path), exist_ok=True)
    with open(pid_path, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))


def _remove_pid_file() -> None:
    pid_path = _pid_file_path()
    try:
        if os.path.isfile(pid_path):
            with open(pid_path, "r", encoding="utf-8") as f:
                pid = int(f.read().strip())
            if pid == os.getpid():
                os.remove(pid_path)
    except Exception:
        pass


def main() -> None:
    if _signal_existing_instance():
        return

    open_settings = "--settings" in sys.argv[1:]
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    _write_pid_file()

    pool = create_autorelease_pool()

    nsapp = msg(cls("NSApplication"), "sharedApplication")
    msg(nsapp, "setActivationPolicy:", None, (NSInteger,), NSApplicationActivationPolicyAccessory)

    store = BindingStore()
    controller = AppUIController(store, open_settings_on_launch=open_settings)
    msg(nsapp, "setDelegate:", None, (ctypes.c_void_p,), controller.dispatcher)

    signal.signal(signal.SIGUSR1, lambda _sig, _frame: controller.request_open_settings_from_signal())

    drain_autorelease_pool(pool)
    try:
        msg(nsapp, "run", None)
    finally:
        _remove_pid_file()


if __name__ == "__main__":
    main()
