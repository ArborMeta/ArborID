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


def model_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "model"


class Api:
    """Called from the page as window.pywebview.api.<name>(...) (runs off the UI thread)."""

    def __init__(self) -> None:
        self._identifier = None

    def _engine(self):
        if self._identifier is None:
            from atlas_identify import Identifier
            self._identifier = Identifier(model_dir())
        return self._identifier

    def photo_info(self, data_url):
        """GPS, date and a small preview of one photo (the preview also fixes HEIC/rotation)."""
        import base64
        import io
        from atlas_identify import decode_data_url
        img, lat, lon, taken = decode_data_url(data_url)
        img.thumbnail((240, 240))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=80)
        thumb = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        return {"lat": lat, "lon": lon, "taken": taken, "thumb": thumb}

    def identify(self, data_urls, lat=None, lon=None, state=None):
        try:
            from atlas_identify import decode_data_url
            engine = self._engine()
            if not engine.available():
                return {"error": "The identification model isn't included in this build."}
            images = [decode_data_url(u)[0] for u in data_urls]
            return engine.identify(images, lat=lat, lon=lon, state=state)
        except Exception as e:  # shown in the Identify window
            return {"error": f"Identification failed: {e}"}


def selftest(photo: str, out: str) -> None:
    """Build check:  "AusTree Atlas.exe" --selftest photo.jpg result.json  (no window)."""
    import base64
    import json
    import time
    try:
        url = "data:image/jpeg;base64," + base64.b64encode(Path(photo).read_bytes()).decode()
        info = Api().photo_info(url)
        t0 = time.time()
        res = Api().identify([url], info["lat"], info["lon"])
        res["seconds"] = round(time.time() - t0, 2)
        res["gps"] = [info["lat"], info["lon"]]
    except Exception as e:
        res = {"error": repr(e)}
    Path(out).write_text(json.dumps(res, indent=1), encoding="utf-8")


def main() -> None:
    if len(sys.argv) == 4 and sys.argv[1] == "--selftest":
        selftest(sys.argv[2], sys.argv[3])
        return
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
        js_api=Api(),
    )
    webview.start(private_mode=False, storage_path=str(data_dir()))


if __name__ == "__main__":
    main()
