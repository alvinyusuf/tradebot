# Kontrak operasi v0.1

Default mode `backtest`; mode valid: backtest, train, evaluate, paper, demo, live. Mode live harus membutuhkan flag eksplisit dan pemeriksaan otorisasi operasional, tidak aktif lewat fallback saat config hilang. Kontrak ini untuk implementasi; belum ada service berjalan.

## Stack dan antarmuka

Target Python 3.11, uv + pyproject.toml + lockfile, NumPy/pandas/pyarrow, Gymnasium, Stable-Baselines3/PyTorch, HTTPX dan websockets, Pydantic, Typer, pytest/Ruff. Versi exact ditetapkan oleh resolver dan diuji saat bootstrap, bukan ditebak dalam definisi. Simpan lockfile dan versi runtime pada artifact. Jika 3.11 tidak tersedia, catat keputusan migrasi sebelum mengubah target.

CLI yang akan diimplementasi: `tradebot data audit`, `tradebot backtest`, `tradebot train`, `tradebot evaluate`, `tradebot paper`, `tradebot report`, `tradebot reconcile`. Tidak mengklaim command ini sudah tersedia.

Konfigurasi wajib memiliki schema_version, mode, symbol, timeframe, risk, execution, dataset, strategy/model ID dan output_dir. Nilai tidak valid atau secret tertulis di config menyebabkan fail fast; secret hanya dari environment/secret store. Runtime membuat run ID dan snapshot konfigurasi nonrahasia.

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
