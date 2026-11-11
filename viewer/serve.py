"""
I3S lokal sunucu - DATA_DIR klasorunu (.env) tarayicida gosterir.
Kullanim: python viewer/serve.py
Sonra http://localhost:8765 adresini acin.
"""
import http.server
import json
import os
import socketserver
import sys
from pathlib import Path
from urllib.parse import urlparse, unquote

REPO_DIR = Path(__file__).resolve().parent.parent
VIEWER_DIR = REPO_DIR / "viewer"

def _load_env():
    env_file = REPO_DIR / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

_load_env()

if not os.environ.get("DATA_DIR"):
    sys.exit("DATA_DIR tanimli degil: .env.example'i .env olarak kopyalayip veri klasorunu yazin")
DATA_DIR = Path(os.environ["DATA_DIR"]).expanduser()
PORT = 8765
PAGES = {"": "viewer.html", "index.html": "viewer.html",
         "viewer.html": "viewer.html", "blocks.html": "blocks.html"}

MIME_MAP = {
    ".json": "application/json",
    ".html": "text/html",
    ".js": "application/javascript",
    ".css": "text/css",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".ktx2": "image/ktx2",
    ".bin": "application/octet-stream",
}


def fix_texture_defs(data):
    """Keep only JPEG texture format in I3S JSON (remove KTX2 since those failed)."""
    if isinstance(data, dict):
        if "textureSetDefinitions" in data:
            for tsd in data["textureSetDefinitions"]:
                tsd["formats"] = [f for f in tsd["formats"] if f.get("format") == "jpg"]
    return data


def _build_block_extents():
    blocks = []
    for d in sorted(DATA_DIR.iterdir()):
        if not d.is_dir() or not d.name.startswith("server"):
            continue
        layer_json = d / "layers" / "0.json"
        extent = None
        if layer_json.is_file():
            try:
                info = json.loads(layer_json.read_bytes())
                ext = info.get("fullExtent") or info.get("store", {}).get("extent")
                if isinstance(ext, dict):
                    extent = {k: ext[k] for k in ("xmin", "ymin", "xmax", "ymax") if k in ext}
                elif isinstance(ext, list) and len(ext) >= 4:
                    extent = {"xmin": ext[0], "ymin": ext[1], "xmax": ext[2], "ymax": ext[3]}
            except Exception:
                pass
        blocks.append({"name": d.name, "extent": extent})
    return {"blocks": blocks}


class I3SHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        raw_path = unquote(parsed.path).lstrip("/")

        if raw_path in PAGES:
            return self._serve_file(VIEWER_DIR / PAGES[raw_path], "text/html")

        # fetch_extents.py ciktisi (107 katman) varsa o sunulur; yoksa liste indirilmis bloklardan uretilir
        if raw_path == "block_extents.json" and not (DATA_DIR / raw_path).is_file():
            body = json.dumps(_build_block_extents(), ensure_ascii=False).encode("utf-8")
            return self._send_bytes(body, "application/json")

        disk_path = raw_path.replace("/SceneServer/", "/").replace("/SceneServer", "")

        candidates = [
            DATA_DIR / disk_path,
            DATA_DIR / (disk_path + ".json"),
            DATA_DIR / raw_path,
            DATA_DIR / (raw_path + ".json"),
        ]

        for candidate in candidates:
            if candidate.is_file():
                ct = self._guess_type(candidate, raw_path)
                if ct == "application/json" and ("layers/0" in raw_path or "SceneServer" in raw_path):
                    return self._serve_patched_json(candidate)
                return self._serve_file(candidate, ct)

        self.send_error(404, f"Not found: {raw_path}")

    def _serve_patched_json(self, filepath):
        try:
            data = json.loads(filepath.read_bytes())
            data = fix_texture_defs(data)
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        except Exception as e:
            self.send_error(500, str(e))
            return
        self._send_bytes(body, "application/json")

    def _guess_type(self, filepath, url_path):
        ext = filepath.suffix.lower()
        if ext in MIME_MAP:
            return MIME_MAP[ext]
        try:
            with open(filepath, "rb") as f:
                magic = f.read(8)
            if magic[:2] == b"\xff\xd8":
                return "image/jpeg"
            if magic[:5] == b"DRACO":
                return "application/octet-stream"
            if magic[:4] == b"\xab\x4b\x54\x58":
                return "image/ktx2"
            if magic[:1] in (b"{", b"["):
                return "application/json"
        except Exception:
            pass
        return "application/octet-stream"

    def _serve_file(self, filepath, content_type):
        try:
            data = filepath.read_bytes()
        except Exception as e:
            self.send_error(500, str(e))
            return
        self._send_bytes(data, content_type)

    def _send_bytes(self, data, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", len(data))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        # Sayfalar her seferinde tazelensin; veri dosyalari degismedigi icin onbellekte kalabilir
        self.send_header("Cache-Control", "no-cache" if content_type == "text/html" else "public, max-age=3600")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def log_message(self, format, *args):
        pass


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    request_queue_size = 256


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    print(f"\n  3B Istanbul I3S Server")
    print(f"  http://localhost:{port}")
    print(f"  Data: {DATA_DIR}\n")

    blocks = sorted(d.name for d in DATA_DIR.iterdir()
                    if d.is_dir() and d.name.startswith("server"))
    for b in blocks:
        print(f"    {b}: http://localhost:{port}/{b}/SceneServer")
    print()

    server = ThreadedHTTPServer(("0.0.0.0", port), I3SHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nSunucu kapatildi.")
