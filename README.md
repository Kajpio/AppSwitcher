# AppSwitcher

A lightweight macOS menu bar utility that maps `Option + Letter` (`⌥A`–`⌥Z`) global shortcuts to show, focus, launch, or hide specific apps. Runs using Apple-signed `/usr/bin/python3` with zero external dependencies.

## Behavior

- **App not running**: Launches and focuses it.
- **App hidden, minimized, or in background**: Shows, focuses, and reopens/unminimizes a window if needed.
- **App already frontmost**: Hides it.

## Install & Run

```bash
cd AppSwitcher
./run-python.sh --settings
```

Start automatically in the background at every login:

```bash
./install-launchagent.sh
```

Remove login startup:

```bash
./uninstall-launchagent.sh
```

## Configuration & Permissions

- **Menu bar icon (`⌥`)**: Click to toggle apps, pause shortcuts, or open **Configure Shortcuts…**.
- **Config file**: Saved to `~/Library/Application Support/AppSwitcher/bindings.json`.
- **Accessibility (optional)**: Granting Accessibility permission to Python in **System Settings → Privacy & Security → Accessibility** lets AppSwitcher unminimize Dock-minimized windows directly.

## License

[MIT](LICENSE)
