"""
3B Istanbul - Blok Kapsama Alanlari
===================================
Her katmanin sadece layers/0 bilgisini (birkac KB) cekip kapsama alanini
(fullExtent) blocks.html'in okudugu block_extents.json dosyasina yazar.
3D veri indirmez.

Kullanim:
    python downloader/fetch_extents.py

Calisan bir download_3d.py varken calistirmayin: yeni token almak onun
token'ini gecersiz kilar.
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from download_3d import CBS_BASE, DATA_DIR, I3SDownloader


def fetch_extent(downloader, name):
    data = downloader._get(f"{CBS_BASE}/{name}/SceneServer/layers/0?f=json")
    if not data:
        print(f"  [UYARI] {name}: bilgi alinamadi")
        return {"name": name, "extent": None}
    ext = data.get("fullExtent") or data.get("store", {}).get("extent")
    if isinstance(ext, list):
        ext = {"xmin": ext[0], "ymin": ext[1], "xmax": ext[2], "ymax": ext[3]}
    print(f"  [OK] {name}")
    return {
        "name": name,
        "extent": {k: ext[k] for k in ("xmin", "ymin", "xmax", "ymax")} if ext else None,
    }


def main():
    parser = argparse.ArgumentParser(description="Blok kapsama alanlarini cek")
    parser.add_argument("--output", "-o", default=str(DATA_DIR))
    parser.add_argument("--workers", "-w", type=int, default=8)
    args = parser.parse_args()

    downloader = I3SDownloader(output_dir=args.output, workers=args.workers)
    names = [l["name"] for l in downloader.get_layers()]

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        blocks = list(executor.map(lambda n: fetch_extent(downloader, n), names))

    out = Path(args.output) / "block_extents.json"
    out.write_text(json.dumps({"blocks": blocks}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    missing = sum(1 for b in blocks if b["extent"] is None)
    print(f"\n[TAMAM] {len(blocks)} katman -> {out}"
          f"{f' ({missing} tanesinin alani yok)' if missing else ''}")


if __name__ == "__main__":
    main()
