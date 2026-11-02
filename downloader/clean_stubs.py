"""
3B Istanbul - Bozuk Dosya Temizleyici
=====================================
Token gecersizken indiricinin veri yerine kaydettigi
{"message": "Invalid Token!", "status": 401} dosyalarini bulur.
download_3d.py var olan dosyalari atladigi icin bunlar silinmeden
yeniden indirilmez. Sadece bloku bu dosyalardan ibaret olan klasorler
de tamamen kaldirilir.

Kullanim:
    python downloader/clean_stubs.py             # Sadece raporla
    python downloader/clean_stubs.py --delete    # Sil
"""

import argparse
import shutil
from pathlib import Path

from download_3d import DATA_DIR

MARKER = b"Invalid Token"


def is_stub(path):
    try:
        if path.stat().st_size >= 200:
            return False
        return MARKER in path.read_bytes()
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(description="Invalid Token dosyalarini temizle")
    parser.add_argument("--output", "-o", default=str(DATA_DIR))
    parser.add_argument("--delete", action="store_true", help="Bulunanlari sil")
    args = parser.parse_args()

    root = Path(args.output)
    total_stubs = 0
    for block in sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith("server")):
        files = [p for p in block.rglob("*") if p.is_file()]
        stubs = [p for p in files if is_stub(p)]
        if not stubs:
            continue
        total_stubs += len(stubs)
        whole = len(stubs) == len(files)
        print(f"  {block.name}: {len(stubs)}/{len(files)} bozuk"
              f"{' (klasor tamamen bozuk)' if whole else ''}")
        if not args.delete:
            continue
        if whole:
            shutil.rmtree(block)
        else:
            for p in stubs:
                p.unlink()

    action = "silindi" if args.delete else "bulundu (silmek icin --delete)"
    print(f"\n[TAMAM] {total_stubs} bozuk dosya {action}")


if __name__ == "__main__":
    main()
