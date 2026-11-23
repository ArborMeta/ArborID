"""AusTree Atlas desktop launcher.

Opens the bundled web app (app/index.html) in a native window using the
Edge WebView2 engine that ships with Windows 10/11.
"""
import os
import sys
from pathlib import Path

import webview

APP_NAME = "AusTree Atlas"


def resource_dir() -> Path:
    # When frozen by PyInstaller, bundled files live in sys._MEIPASS.
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "app"


def data_dir() -> Path:
    # Persistent browser profile so localStorage (custom specimens, theme,
    # photo cache) survives between launches.
    root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AusTreeAtlas"
    root.mkdir(parents=True, exist_ok=True)
    return root


def main() -> None:
    index = resource_dir() / "index.html"

    # Let the "Download specimen sheet" and "Export CSV" buttons save files.
    webview.settings["ALLOW_DOWNLOADS"] = True
    # Atlas of Living Australia links open in the normal web browser.
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True

    webview.create_window(
        APP_NAME,
        url=index.as_uri(),  # file:// keeps a stable origin for localStorage
        width=1400,
        height=900,
        min_size=(900, 600),
    )
    webview.start(private_mode=False, storage_path=str(data_dir()))


if __name__ == "__main__":
    main()
