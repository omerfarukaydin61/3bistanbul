"""
3B Istanbul - 3D Veri Indirme Scripti
=====================================
Istanbul Buyuksehir Belediyesi 3D sehir modelini (I3S/IntegratedMesh)
indirip lokal olarak goruntuleyebilmenizi saglar.

Kullanim:
    python downloader/download_3d.py                          # Tum bloklari indir
    python downloader/download_3d.py --blocks 57 60 Adalar    # Belirli bloklari indir (tam ad)
    python downloader/download_3d.py --workers 8              # 8 paralel indirme
    python downloader/download_3d.py --workers 8 --delay 0.2  # Daha yavas, guvenli

Veriler repo'daki data/ klasorune iner.
"""

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

API_URL = "https://3bistanbul-api.ibb.gov.tr/api/Sceneserver/layers"
CBS_BASE = "https://cbsapi.ibb.gov.tr/GW"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0.0.0 Safari/537.36"
)


class TokenManager:
    def __init__(self):
        self._token = None
        self._expiry = 0
        self._lock = threading.Lock()

    def get_token(self):
        now = time.time() * 1000
        if self._token and now < self._expiry - 300_000:
            return self._token

        with self._lock:
            now = time.time() * 1000
            if self._token and now < self._expiry - 300_000:
                return self._token

            print("[TOKEN] Yeni token aliniyor...")
            resp = requests.get(API_URL, timeout=30,
                                headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            data = resp.json()
            key_data = data["cbs3bKey"]
            self._token = key_data["value"]
            from datetime import datetime
            ts = key_data["timeStamp"].replace("Z", "+00:00")
            self._expiry = datetime.fromisoformat(ts).timestamp() * 1000
            print(f"[TOKEN] Token alindi, gecerlilik: {key_data['timeStamp']}")
            return self._token

    def invalidate(self):
        with self._lock:
            self._token = None


class Stats:
    def __init__(self):
        self._lock = threading.Lock()
        self.downloaded = 0
        self.skipped = 0
        self.errors = 0
        self.bytes = 0
        self.rate_limited = 0

    def add_download(self, size):
        with self._lock:
            self.downloaded += 1
            self.bytes += size

    def add_skip(self):
        with self._lock:
            self.skipped += 1

    def add_error(self):
        with self._lock:
            self.errors += 1

    def add_rate_limit(self):
        with self._lock:
            self.rate_limited += 1


class I3SDownloader:
    def __init__(self, output_dir, workers=8, delay=0.1, token_mgr=None):
        self.output_dir = Path(output_dir)
        self.workers = workers
        self.delay = delay
        self.token_mgr = token_mgr or TokenManager()
        self.stats = Stats()
        self._sessions = threading.local()

    def _get_session(self):
        if not hasattr(self._sessions, "s"):
            s = requests.Session()
            s.headers.update({
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
                "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8",
            })
            self._sessions.s = s
        return self._sessions.s

    def _get(self, url, binary=False):
        session = self._get_session()
        for attempt in range(4):
            try:
                headers = {"Authorization": f"Bearer {self.token_mgr.get_token()}"}
                resp = session.get(url, headers=headers, timeout=60)

                if resp.status_code == 401:
                    self.token_mgr.invalidate()
                    headers = {"Authorization": f"Bearer {self.token_mgr.get_token()}"}
                    resp = session.get(url, headers=headers, timeout=60)

                if resp.status_code == 429 or resp.status_code == 503:
                    self.stats.add_rate_limit()
                    wait = min(30, 2 ** (attempt + 2))
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        wait = min(60, int(retry_after))
                    print(f"  [RATE LIMIT] {resp.status_code} - {wait}s bekleniyor...")
                    time.sleep(wait)
                    continue

                # Sunucu gecersiz token'i 200 + {"message": "Invalid Token!"} olarak donebiliyor
                if resp.status_code == 200 and len(resp.content) < 200 and b"Invalid Token" in resp.content:
                    self.token_mgr.invalidate()
                    time.sleep(2 ** attempt)
                    continue

                if resp.status_code == 200:
                    ct = resp.headers.get("content-type", "")
                    if "html" in ct:
                        return None
                    if binary and resp.content[:15].startswith(b"<!DOCTYPE"):
                        return None
                    return resp.content if binary else resp.json()

                if resp.status_code == 404:
                    return None

            except requests.ConnectionError:
                time.sleep(2 ** attempt)
            except (requests.RequestException, json.JSONDecodeError) as e:
                if attempt == 3:
                    print(f"  [HATA] {url}: {e}")
                    return None
                time.sleep(2 ** attempt)

            if self.delay > 0:
                time.sleep(self.delay)

        return None

    def _save(self, path, data, binary=False):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if binary:
            path.write_bytes(data)
        else:
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path.stat().st_size

    def get_layers(self):
        print("[INFO] Katman listesi aliniyor...")
        resp = requests.get(API_URL, timeout=30,
                            headers={"User-Agent": USER_AGENT})
        data = resp.json()
        layers = data.get("layers", [])
        print(f"[INFO] {len(layers)} katman bulundu")
        return layers

    def download_layer_info(self, layer_name):
        base = f"{CBS_BASE}/{layer_name}/SceneServer"
        info_path = self.output_dir / layer_name / "SceneServer.json"

        if not info_path.exists():
            info = self._get(f"{base}/?f=json")
            if info:
                self._save(info_path, info)
            else:
                print(f"  [UYARI] {layer_name} erisim yok, atlaniyor")
                return None

        layer0_path = self.output_dir / layer_name / "layers" / "0.json"
        if not layer0_path.exists():
            layer0 = self._get(f"{base}/layers/0?f=json")
            if layer0:
                self._save(layer0_path, layer0)

        return info_path

    def download_node_pages(self, layer_name):
        base = f"{CBS_BASE}/{layer_name}/SceneServer/layers/0"
        pages_dir = self.output_dir / layer_name / "layers" / "0" / "nodepages"
        pages_dir.mkdir(parents=True, exist_ok=True)

        page_idx = 0
        all_mesh_nodes = []

        while True:
            page_path = pages_dir / f"{page_idx}.json"

            if page_path.exists():
                try:
                    page_data = json.loads(page_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, IOError):
                    page_data = None
                if page_data is None:
                    page_data = self._get(f"{base}/nodepages/{page_idx}")
                    if page_data:
                        self._save(page_path, page_data)
            else:
                page_data = self._get(f"{base}/nodepages/{page_idx}")
                if page_data:
                    self._save(page_path, page_data)

            if not page_data:
                break

            nodes = page_data.get("nodes", [])
            if not nodes:
                break

            for node in nodes:
                if node.get("mesh"):
                    all_mesh_nodes.append(node)

            page_idx += 1

        print(f"  [NODEPAGE] {page_idx} sayfa, {len(all_mesh_nodes)} mesh node")
        return all_mesh_nodes

    def download_node_resources(self, layer_name, node):
        base = f"{CBS_BASE}/{layer_name}/SceneServer/layers/0"
        node_idx = node["index"]
        mesh = node.get("mesh", {})
        geo_resource = mesh.get("geometry", {}).get("resource")

        if geo_resource is None:
            return

        node_dir = self.output_dir / layer_name / "layers" / "0" / "nodes" / str(node_idx)

        # Sadece Draco geometri (geometries/1). Goruntuleyici yalnizca bunu istiyor;
        # sikistirilmamis geometries/0 ayni veri ve ~12 kat buyuk.
        geo_path = node_dir / "geometries" / "1"
        if not geo_path.exists():
            data = self._get(f"{base}/nodes/{node_idx}/geometries/1", binary=True)
            if data:
                size = self._save(geo_path, data, binary=True)
                self.stats.add_download(size)
            else:
                self.stats.add_error()
        else:
            self.stats.add_skip()

        if self.delay > 0:
            time.sleep(self.delay * 0.5)

        # JPEG texture
        tex_path = node_dir / "textures" / "0"
        if not tex_path.exists():
            data = self._get(f"{base}/nodes/{node_idx}/textures/0", binary=True)
            if data:
                size = self._save(tex_path, data, binary=True)
                self.stats.add_download(size)
            else:
                self.stats.add_error()
        else:
            self.stats.add_skip()

        # Shared resources
        shared_path = node_dir / "shared.json"
        if not shared_path.exists():
            data = self._get(f"{base}/nodes/{node_idx}/shared?f=json")
            if data:
                self._save(shared_path, data)

        if self.delay > 0:
            time.sleep(self.delay)

    def download_block(self, layer_name):
        print(f"\n{'='*60}")
        print(f"  [BLOK] {layer_name}")
        print(f"{'='*60}")

        info = self.download_layer_info(layer_name)
        if info is None:
            return

        mesh_nodes = self.download_node_pages(layer_name)
        if not mesh_nodes:
            print(f"  [UYARI] Mesh node bulunamadi")
            return

        total = len(mesh_nodes)
        print(f"  [INDIRME] {total} node ({self.workers} worker, "
              f"{self.delay:.0f}ms delay)")
        start = time.time()
        completed = 0

        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {
                executor.submit(self.download_node_resources, layer_name, node): node
                for node in mesh_nodes
            }

            for future in as_completed(futures):
                future.result()
                completed += 1
                if completed % 200 == 0:
                    elapsed = time.time() - start
                    speed = self.stats.bytes / elapsed / 1024 / 1024 if elapsed > 0 else 0
                    eta_min = (total - completed) / (completed / elapsed) / 60 if completed > 0 else 0
                    print(f"    {completed}/{total} "
                          f"({completed*100//total}%) - "
                          f"{self.stats.bytes/1024/1024:.0f} MB - "
                          f"{speed:.1f} MB/s - "
                          f"ETA: {eta_min:.0f} dk"
                          f"{f' (rate-limit: {self.stats.rate_limited})' if self.stats.rate_limited else ''}")

        elapsed = time.time() - start
        block_dir = self.output_dir / layer_name
        block_size = sum(f.stat().st_size for f in block_dir.rglob("*") if f.is_file())
        print(f"  [TAMAM] {layer_name}: {block_size/1024/1024:.1f} MB, "
              f"{elapsed:.0f}s, hatali: {self.stats.errors}"
              f"{f', rate-limit: {self.stats.rate_limited}' if self.stats.rate_limited else ''}")

    def download_all(self, block_filter=None):
        layers = self.get_layers()

        if block_filter:
            # Tam eslesme: "57" -> Blok_57, "Yama_56_57" / "server-Blok_57" kendisi
            names = set()
            for b in block_filter:
                b = b.lower()
                for layer in layers:
                    full = layer["name"].lower()
                    short = full.split("-", 1)[-1]
                    if b in (full, short) or short == f"blok_{b}":
                        names.add(layer["name"])
            layers = [l for l in layers if l["name"] in names]
            print(f"[FILTRE] {len(layers)} blok: {[l['name'] for l in layers]}")

        total_start = time.time()

        for i, layer in enumerate(layers):
            name = layer["name"]
            print(f"\n[ILERLEME] {i+1}/{len(layers)} blok")
            self.download_block(name)

        total_elapsed = time.time() - total_start
        print(f"\n{'='*60}")
        print(f"  [TAMAMLANDI]")
        print(f"  Toplam: {self.stats.bytes/1024/1024/1024:.2f} GB")
        print(f"  Sure: {total_elapsed/3600:.1f} saat")
        print(f"  Indirilen: {self.stats.downloaded}")
        print(f"  Atlanan: {self.stats.skipped}")
        print(f"  Hatali: {self.stats.errors}")
        if self.stats.rate_limited:
            print(f"  Rate-limit: {self.stats.rate_limited}")
        print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(
        description="3B Istanbul 3D Veri Indirici"
    )
    parser.add_argument("--output", "-o", default=str(DATA_DIR))
    parser.add_argument("--blocks", "-b", nargs="+",
        help="Belirli bloklar, tam eslesme (ornek: 57 60 Yama_56_57 Adalar)")
    parser.add_argument("--workers", "-w", type=int, default=8,
        help="Paralel indirme (varsayilan: 8, guvenli maks: 12)")
    parser.add_argument("--delay", "-d", type=float, default=0.1,
        help="Istekler arasi bekleme saniye (varsayilan: 0.1)")

    args = parser.parse_args()

    print(f"""
====================================================
  3B ISTANBUL - 3D VERI INDIRICI
  I3S / IntegratedMesh / JPEG Textures
====================================================

Cikis:     {args.output}
Worker:    {args.workers}
Delay:     {args.delay}s
""")

    downloader = I3SDownloader(
        output_dir=args.output,
        workers=args.workers,
        delay=args.delay,
    )
    downloader.download_all(block_filter=args.blocks)


if __name__ == "__main__":
    main()
