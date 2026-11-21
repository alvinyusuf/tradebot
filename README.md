# Tradebot

Service trading otomatis Binance Futures. Pengguna menetapkan modal dan risiko lalu memantau hasil. Fondasi simulator, CLI riset, dan pengujian pemulihan lokal tersedia. Status bukti data dan kesiapan operasi ada di [status proyek](memory/STATE.md). Aktivasi uang asli memerlukan otorisasi tersendiri.

## Kesepakatan produk

| Parameter | Nilai |
|---|---|
| Modal awal | Sekitar USD 100; simulasi memakai 100 USDT |
| Instrumen | BTCUSDT perpetual USDⓈ-M, margin USDT, isolated |
| Leverage maksimum | 5x |
| Risiko awal simulasi | 0,5% per transaksi termasuk cadangan biaya/slippage |
| Batas rugi harian | 5% equity awal hari |
| Timeframe | Keputusan candle 15m selesai, konteks candle 1h selesai |
| Pendekatan | RL dibanding strategi aturan; risk engine terpisah |

Estimasi peluang profit yang tervalidasi tetap tujuan pengembangan, tetapi v0.1 memakai risiko tetap. Confidence policy RL bukan probabilitas profit. Eksplorasi hanya dalam simulator; model paper/live dibekukan.

## Default development v0.1

Agent menetapkan default teknis untuk menuntaskan definisi: satu posisi, margin maksimum 25%, auto-add margin mati, reset hari 00.00 UTC; saat batas rugi tercapai cancel entry dan close reduce-only lalu halt. TP/SL 3/1,5 ATR, timeout 4 jam, PPO sebagai eksperimen pertama. Ini keputusan rancangan, bukan klaim setiap angka telah disepakati pengguna atau terbukti optimal. Detail dan evaluasi ada di spesifikasi.

Minimum order tidak dijamin oleh modal dan leverage saja. Bot wajib membaca filter yang berlaku, membulatkan sizing sesuai aturan, lalu skip jika minimum order melanggar risiko. Audit publik terbaru memperoleh snapshot filter BTCUSDT bertimestamp. Lihat [catatan Binance](knowledge/binance-futures.md) untuk hasil dan batas cakupannya.

## Dokumen acuan

- [AGENTS.md](AGENTS.md): urutan masuk dan persistence AI agent.
- [Arsitektur](docs/architecture.md): komponen dan kontrak integrasi.
- [Spesifikasi eksperimen](docs/experiment-spec.md): baseline, RL, data, TP/SL, sizing dan split.
- [Kriteria kelulusan](docs/acceptance.md): gate data, simulator, model, paper dan live.
- [Operasi](docs/operations.md): stack, recovery, monitoring, laporan dan backup.
- [Keputusan](docs/decisions.md): otoritas keputusan dan perubahan versi.
- [Roadmap](docs/development-plan.md): fase implementasi dan bukti selesai.
- [Status sesi](memory/STATE.md): handoff aktual.
- [Knowledge](knowledge/README.md): sumber dan batas kepastian.
- [Changelog](CHANGELOG.md): hasil yang selesai.

## Audit arsip lokal

Jalankan `python scripts/audit_archives.py` dengan Python 3.11 dari root repository. Skrip memeriksa checksum, skema dan cakupan arsip publik Binance. Arsip dan manifest lokal disimpan di `data/audit/`. Exit 0 menunjukkan pemeriksaan arsip selesai tanpa gap tersisa menurut pemeriksaan skrip. Status verifikasi metadata kontrak tercatat di manifest.

Setelah manifest tersedia, `python scripts/audit_public_api.py --verify-funding` mencoba mengambil filter BTCUSDT, candle mark price yang belum terpulihkan, dan histori settlement funding. Hasil dan waktu pengambilan dicatat di `data/audit/public-api.json`. Perintah ini memakai endpoint publik tanpa kredensial. Loader dataset memeriksa hash dan kecocokan data REST sebelum memakainya.

## Pengembangan simulator

`uv sync --locked --extra learning` memasang paket dan dependensi PPO CPU yang terkunci. Jalankan `uv run pytest` untuk tes lokal dan `uv run tradebot --help` untuk daftar perintah. Panduan konfigurasi, artifact, dan rentang pengembangan ada di [kontrak operasi](docs/operations.md).

## Batas kepastian

Tidak ada target profit yang dijanjikan. SL dan batas harian tidak menjamin rugi aktual tidak overshoot. Penilaian meliputi return net, drawdown, biaya, funding, likuidasi dan pelanggaran software; biaya hosting/compute dilaporkan terpisah. Definisi selesai berbeda dari implementasi/validasi selesai. Aktivasi live tetap memerlukan gate dan otorisasi pengguna.
