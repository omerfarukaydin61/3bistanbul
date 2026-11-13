# 3B İstanbul

İBB'nin 3B İstanbul şehir modelini (I3S / IntegratedMesh) bloklar halinde indirip
tarayıcıda yerel olarak görüntüler.

## Yapı

```
downloader/   İBB servisinden veri indiren scriptler
viewer/       Yerel sunucu, 3D görüntüleyici ve blok haritası
```

## Kurulum

```bash
pip install -r requirements.txt
cp .env.example .env    # DATA_DIR: verinin klasörü (indirici yazar, görüntüleyici okur)
```

Python 3.10 ve üstü.

Tüm komutlar repo kökünden çalıştırılır. `package.json` yalnızca kısayol tutar
(Node bağımlılığı yok); script argümanları `--` sonrasına yazılır.

| Kısayol | Karşılığı |
|---|---|
| `npm run dev` | `python viewer/serve.py` |
| `npm run download -- --blocks 56 59` | `python downloader/download_3d.py --blocks 56 59` |
| `npm run extents` | `python downloader/fetch_extents.py` |
| `npm run clean-stubs -- --delete` | `python downloader/clean_stubs.py --delete` |

## Görüntüleme

```powershell
npm run dev
```

- **http://localhost:8765** — 3D görüntüleyici. `DATA_DIR` içindeki indirilmiş blokları
  kendisi bulur ve yükler.
- **http://localhost:8765/blocks.html** — blok haritası. 107 katmanın tamamının sınırını
  gösterir; indirilmiş olanlar yeşil, indirilebilecek olanlar mavi. Seçilen bloklar için
  indirme komutunu üretir. Katman listesi repo'daki `viewer/block_extents.json`'dan gelir.

Port vermek için: `npm run dev -- 9000`. Sayfaları dosyadan (`file://`)
açmayın; veri yalnızca sunucu üzerinden yüklenir.

### Docker ile

```powershell
docker compose up -d --build
```

Görüntüleyici konteyner ayakta olduğu sürece **http://localhost:8765** adresinde açık kalır;
konteyner `restart: unless-stopped` ile Docker başlarken kendiliğinden kalkar, çökerse
yeniden başlar. Durdurmak için `docker compose down`.

- `.env`'deki `DATA_DIR` host'taki veri klasörüdür; konteynere `/data` olarak bağlanır.
  Python kurulumu gerekmez, yalnızca `.env` gerekir.
- Yeni blok indirildiğinde konteyneri yeniden başlatmak gerekmez; sayfayı yenilemek yeter.
- İndirme konteyner içinden de çalıştırılabilir (veri aynı klasöre iner):
  `docker compose exec viewer python downloader/download_3d.py --blocks 56 59`
- `viewer/` dosyaları imaja kopyalanır; değiştirildiklerinde `docker compose up -d --build`
  ile imaj yeniden üretilir. `fetch_extents.py` repo dosyasını yazdığı için host'ta çalıştırılır.

## İndirme

```powershell
npm run download -- --blocks 56 59
```

- `--blocks` tam eşleşme yapar: `57` → `Blok_57`; `Yama_56_57`, `Adalar` gibi adlar
  kendileriyle eşleşir. Verilmezse tüm katmanlar iner (~3.3 TB).
- Var olan dosyalar atlanır; yarım kalan bir blok aynı komutla tamamlanır.
- Sadece görüntüleyicinin kullandığı Draco geometri (`geometries/1`) ve JPEG doku iner; blok başına ~30 GB.

### Yardımcı scriptler

| Script | Ne yapar |
|---|---|
| `downloader/fetch_extents.py` | Her katmanın kapsama alanını çekip repo'daki `viewer/block_extents.json`'u yeniden yazar. Blok haritası ve görüntüleyici bu dosyayı kullanır. Yalnızca İBB katman listesi değiştiğinde çalıştırılır. |
| `downloader/clean_stubs.py` | Token hatası sırasında veri yerine kaydedilmiş `Invalid Token` dosyalarını bulur; `--delete` ile siler. |

Aynı anda birden fazla indirme ya da `fetch_extents.py` çalıştırmayın: her biri yeni
token alır ve diğerinin token'ını geçersiz kılar.
