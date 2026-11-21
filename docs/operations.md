# Kontrak operasi v0.1

Default mode `backtest`; mode valid: backtest, train, evaluate, paper, demo, live. Mode live harus membutuhkan flag eksplisit dan pemeriksaan otorisasi operasional, tidak aktif lewat fallback saat config hilang. Kontrak ini untuk implementasi; belum ada service berjalan.

## Stack dan antarmuka

Target Python 3.11, uv + pyproject.toml + lockfile, NumPy/pandas/pyarrow, Gymnasium, Stable-Baselines3/PyTorch, HTTPX dan websockets, Pydantic, Typer, pytest/Ruff. Versi exact ditetapkan oleh resolver dan diuji saat bootstrap, bukan ditebak dalam definisi. Simpan lockfile dan versi runtime pada artifact. Jika 3.11 tidak tersedia, catat keputusan migrasi sebelum mengubah target.

CLI lokal mencakup audit dan kurasi data, validasi config, backtest, training, evaluasi, laporan, review gate, probe paper, audit metadata demo, serta pembacaan jurnal rekonsiliasi. Integrasi order akun dan runtime paper unattended masih tahap terpisah.

Konfigurasi wajib memiliki schema_version, mode, symbol, timeframe, risk, execution, dataset, strategy/model ID dan output_dir. Nilai tidak valid atau secret tertulis di config menyebabkan fail fast; secret hanya dari environment/secret store. Runtime membuat run ID dan snapshot konfigurasi nonrahasia.

## Menjalankan riset lokal

- Instalasi terkunci memakai `uv sync --locked --extra learning` dengan Python 3.11. Dependensi dasar cukup untuk audit, simulator dan backtest. Ekstra `learning` menambahkan Gymnasium, Stable-Baselines3 dan PyTorch CPU.
- Config JSON memilih `mode` sesuai command, `dataset.manifest`, `dataset.metadata`, `dataset.metadata_status`, dan bila tersedia `dataset.public_api_report`. `execution.cost_scenario` menerima `base` atau `stress`. `output_dir` default `runs`.
- File metadata simulator menyimpan `status`, `symbol`, `source`, `fetched_at`, objek `order_filters` dengan `price_tick`, `quantity_step`, `min_quantity`, `max_quantity`, dan `min_notional`, serta daftar `maintenance_brackets` dengan `notional_floor`, `notional_cap`, `maintenance_rate`, `cumulative_deduction`, dan `max_leverage`. Simpan angka desimal sebagai string. Label `current_rules_approximation` menandai snapshot aturan saat ini yang digunakan untuk riset historis.
- `tradebot backtest config.json --fold 1 --split validation` menjalankan baseline pengembangan. Fold 1–3 mengikuti spesifikasi v0.1. CLI memerlukan bukti funding REST yang cocok dengan arsip. Interval yang masih mengandung gap ditolak.
- `tradebot train config.json --fold 1` memerlukan `mode: train` dan `strategy_id: ppo-v0.1`. Artifact menyimpan scaler hasil split training, versi library, identitas sumber, dan checkpoint terpilih dari skor validation lima seed. Jalankan `tradebot evaluate config.json --fold 1` dengan `mode: evaluate` dan `model_id` menunjuk direktori artifact lokal yang tepercaya. Evaluasi pengembangan menghasilkan indeks dengan ringkasan setiap seed.
- Setelah evaluasi ketiga fold, `tradebot train config.json --final` menerima tiga opsi `--development-index`, satu per fold. Sesudah konfigurasi dan artifact final dibekukan, `tradebot evaluate config.json --frozen-sha256 <hash>` membaca holdout memakai hash SHA-256 `training.json` final. Baseline yang sepadan memakai `tradebot backtest config.json --final-training <training.json> --frozen-sha256 <hash>`. Jalankan skenario base dan stress dengan pilihan biaya yang sudah ditetapkan. Hasil holdout belum tersedia.
- `tradebot report runs/<run-id>` membaca ringkasan JSON. Artifact backtest juga menyimpan equity per menit dan ledger transaksi.

## Bukti paper dan demo

- `tradebot paper probe <waktu-UTC>` memeriksa feed publik sekali mulai dari cursor menit yang diberikan. Probe memeriksa freshness quote/mark dan clock drift. Hasil probe sendiri belum membuktikan hasil forward.
- `tradebot paper check-model <direktori-artifact> --seed <seed> --frozen-sha256 <hash>` memverifikasi dan memuat artifact PPO final lokal yang tepercaya di CPU. Worker menggunakan scaler beku dan observasi dari candle yang sudah selesai. Intent close mengikuti kuotasi sesudah sinyal, kedalaman tersedia dan prioritas proteksi. Pemeriksaan model bersifat lokal.
- Supervisor lokal memakai satu polling yang berjalan di latar belakang, watchdog satu detik, heartbeat 30 detik, dan rekonsiliasi eksplisit sebelum kembali siap. Polling perlu timeout terbatas. Snapshot SQLite disimpan sebelum callback audit, sehingga kegagalan audit dapat meninggalkan checkpoint yang lebih baru dari laporan. Pengujian supervisor memakai feed fixture.
- `tradebot paper report <database> --utc-day <YYYY-MM-DD> --model-id <id> --config-id <id>` membaca observasi dan event lokal. Ringkasan menampilkan awal dan akhir cakupan, drawdown yang teramati dan perubahan penghitung bila ada observasi sebelumnya.
- `tradebot paper backup <database> <backup.sqlite>` membuat salinan SQLite konsisten tanpa menimpa tujuan. Direktori tujuan perlu mendukung hard link lokal untuk publikasi backup.
- `tradebot demo metadata <output.json>` memakai kredensial demo `BINANCE_DEMO_API_KEY` dan `BINANCE_DEMO_API_SECRET` dari environment proses. Command memakai GET pada host demo dan mencatat filter, bracket, dan komisi BTCUSDT dengan timestamp. Kredensial, signature dan data identitas akun tidak disimpan di output. Bukti ini berlaku di demo.
- `tradebot demo preflight --output data/audit/<nama>.json` memeriksa candle, quote dan mark dari feed Futures publik serta clock server Demo dari host resmi. Keduanya harus tersedia untuk skenario demo dengan data pasar aktual. Perintah ini tidak membutuhkan kredensial.
- `tradebot demo validate-order --side BUY --quantity <jumlah>` menjalankan request bertanda tangan ke endpoint test order Demo dengan kredensial Demo yang sama. Endpoint ini hanya memvalidasi request tanpa fill. Hasil validasi tidak memenuhi uji order dan recovery Gate C.
- `tradebot demo check-account` memeriksa one-way, isolated, auto-add margin, leverage, posisi flat dan ketiadaan order dari request baca-saja. Ketiga perintah akun Demo menerima `--env-file .env` untuk membaca dua nama variabel Demo secara eksplisit. Variabel proses diprioritaskan.
- Adapter transaksi Demo memiliki primitive market entry, close reduce-only dan proteksi kondisional berbasis mark price. Mutasi memerlukan aktivasi eksplisit pada objek adapter. Jurnal local menyimpan intent market sebelum pengiriman dan menahan pengiriman baru saat masih ada order yang belum pasti. Integrasi supervisor akun serta uji fill, proteksi dan recovery pada Demo aktual masih tertunda.
- `tradebot gate <evidence.json>` menilai Gate B atau bagian paper Gate C. JSON `schema_version: 1` dan `gate: B` membutuhkan map `base` dan `stress` dengan kunci seed, `baseline`, serta objek `evidence` dengan boolean `holdout_verified`, `configuration_frozen`, dan `execution_costs_verified`. `gate: paper` membutuhkan `start` dan `end` eksklusif dalam ISO 8601 UTC, `frozen`, dan `metrics`.
- Objek metrik gate menyertakan `net_return`, `max_drawdown`, `closed_trades`, `profit_factor`, `liquidations`, `software_violations`, dan `unexplained_overshoots`. Gunakan pecahan untuk return dan drawdown. Gunakan `null` untuk profit factor yang tak terdefinisi atau audit risiko yang belum diketahui. Output mencantumkan status, alasan dan checksum input. Review lokal ini tidak menjalankan promosi.

## Pemantauan dan recovery

- Watchdog lokal setiap 1 detik; quote/mark terakhir lebih tua dari 5 detik atau drift clock >1 detik membuat halt entry. Proteksi exchange tetap aktif; jangan membatalkan proteksi hanya karena data stale.
- Rekonsiliasi tiap 30 detik, setelah reconnect, dan sebelum READY. Heartbeat/log sehat tiap 30 detik. Strategi menunggu candle selesai, bukan loop polling sinyal per detik.
- Submit timeout 5 detik membuat status unknown, bukan retry submit. Query status dengan ID stabil pada backoff 1/2/4/8/15 detik ditambah jitter; jika tetap tidak pasti, terus halt dan rekonsiliasi maksimal tiap 30 detik, tanpa order entry duplikat. Hormati Retry-After/rate limit exchange di atas jadwal lokal.
- Setelah fill, target konfirmasi proteksi <=5 detik. Jika tidak terkonfirmasi, cancel entry tersisa, query proteksi, lalu close reduce-only untuk kuantitas aktual yang diketahui jika proteksi memang gagal. Bila status close tidak pasti, query dan rekonsiliasi; jangan spam order atau mengklaim flat tanpa bukti.
- Daily limit: cancel entry, close reduce-only, konfirmasi flat, bersihkan proteksi sisa dan persist halt. System halt pulih melalui rekonsiliasi dan tindakan recovery eksplisit, terpisah dari reset hari.
- Shutdown biasa: stop entry, simpan state, pertahankan proteksi exchange posisi terbuka dan laporkan posisi. Shutdown tidak membatalkan SL. Pada backtest/paper, akhir run menutup posisi dengan biaya; jangan menyamakan dengan shutdown live.

## Laporan dan alert

Versi awal CLI plus JSON/CSV/HTML statis lokal, tanpa dashboard web. Laporan harian 00.05 UTC mencakup equity, PnL realized/unrealized, fee, funding, drawdown, posisi, jumlah trade, skip minimum order, downtime dan halt. Format waktu UTC; UI/laporan boleh menampilkan Asia/Bangkok sebagai tampilan tambahan.

Event kritis langsung ke structured log/stderr dan file alert persisten: unknown order, posisi tanpa proteksi, daily halt, kegagalan database, disconnect berkepanjangan dan mismatch rekonsiliasi. Untuk lokal/paper ini cukup sebagai output development, bukan jaminan pengguna telah menerima alert. Sebelum unattended live wajib memilih dan menguji kanal eksternal dengan pengguna; tidak mengirim email/chat tanpa instruksi eksplisit.

## Penyimpanan, deployment dan biaya

Raw/curated Parquet immutable di `data/`, manifest/checksum wajib. SQLite WAL untuk satu writer runtime, transaksi atomik dan event IDs unik. Model/config/metric di `artifacts/`, laporan/log di `runs/`. Semua dataset besar, database, artifact, .env dan log diabaikan Git saat bootstrap; template config nonrahasia boleh di-commit.

Checkpoint state pada setiap event order/fill/halt. Backup SQLite konsisten lewat backup API setiap hari dan sebelum migrasi; simpan 7 harian +4 mingguan. Secret tidak ikut backup biasa. Simpan audit trading/model/manifest selama umur eksperimen; log debug 14 hari, event risiko minimum 90 hari. Uji restore sebelum demo unattended/live. Backup gagal menyebabkan alert dan blokir promosi, bukan mengklaim data terlindungi.

Development/training awal lokal CPU. Target runtime paper unattended adalah satu Linux host dengan systemd dan persistent disk; spesifikasi awal 2 vCPU/4 GB RAM untuk inference, bukan jaminan cukup untuk training. Container tidak wajib v0.1. Pemilihan provider, provisioning dan anggaran memerlukan keputusan pengguna saat fase operasi; itu gate tindakan eksternal, bukan kekosongan desain simulator. Restart policy selalu masuk RECONCILING dan tidak menghapus halt.

## Kontrak integrasi yang harus diverifikasi

Gunakan endpoint resmi Binance terbaru, validasi schema REST/WebSocket serta order proteksi/algo pada saat implementasi. Dokumentasi arsitektur tidak membekukan URL yang mungkin berubah. Integration test menyimpan timestamp/filter/fee/bracket yang digunakan tanpa secret. Jika akses resmi tidak tersedia, tandai gate integrasi gagal; paper boleh memakai simulasi berlabel, live tetap terkunci.
