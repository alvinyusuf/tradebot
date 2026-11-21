# Status proyek

Diperbarui: 21 November 2026.

## Status aktual

- Fase 00: definisi v0.1 dan persistence selesai setelah audit/revisi. Handoff: [fase 00](phases/00-definition.md).
- Fase 01: [audit data dan runtime](phases/01-data-runtime-audit.md) parsial. REST memulihkan dua menit mark price terakhir. Dataset Parquet terverifikasi memuat 2.059.200 menit tanpa gap, termasuk warmup. Metadata bracket untuk simulasi belum tersedia.
- Fase 02: [fondasi simulator](phases/02-simulator.md) mencakup CLI riset, PPO, supervisor paper dan audit harian. Pemeriksaan terbaru meluluskan 130 tes dan dua subtes, termasuk adapter dan rekonsiliasi Demo dengan fixture. Backtest dan PPO pasar aktual serta observasi paper belum dijalankan.
- Manifest lokal tersedia di `data/audit/manifest.json`. Bukti publik terbaru di `data/audit/public-api.json` berisi snapshot filter, dua candle pemulihan dan lima halaman funding. Preflight publik Futures dan Demo lulus pukul 23.16 WIB.

## Kontrak yang berlaku

Baca README, register keputusan, experiment-spec, acceptance dan operations. Produk disepakati: 100 USD, BTCUSDT USDT isolated, <=5x, risiko awal 0,5%, daily limit 5%, 15m/1h. Default development agent: satu posisi, margin <=25%, UTC day, close saat daily halt, TP/SL 3/1,5 ATR, timeout 4 jam, PPO. Detail bukan parameter yang harus ditebak lagi pada sesi berikutnya.

## Next step konkret

1. Konfigurasi Demo BTCUSDT Isolated 1x dan test order sudah terverifikasi. Sebelum eksekusi strategi Demo, selesaikan batas implementasi supervisor dan putuskan konfigurasi yang layak memenuhi margin serta minimum order. Pada parameter 100 USDT, 25% margin dan 1x, batas notional 25 USDT berada di bawah minimum Demo 50 USDT.
2. Verifikasi metadata bracket yang sesuai untuk backtest. Snapshot Demo terpisah dari snapshot Futures produksi.
3. Setelah prasyarat data terpenuhi, jalankan Gate A pada input pasar dan lanjutkan baseline/PPO, evaluasi pengembangan, dan holdout beku sesuai roadmap. Fee dan bracket aktual memerlukan bukti resmi untuk integrasi dan kesiapan live.
4. Paper forward, demo, provisioning dan alert mengikuti kelulusan sebelumnya. Supervisor dan pemulihan lokal sudah diuji dengan fixture. Integrasi layanan host, sumber rekonsiliasi operasional, dan pengujian order exchange masih tertunda.

## Keterbatasan nyata

Pada 21 November, preflight publik lulus dan autentikasi dari `.env` berhasil. Komisi dan bracket Demo terverifikasi di `data/audit/demo-metadata-20261121.json`. Demo BTCUSDT dikonfigurasi Isolated 1x atas persetujuan pengguna, lalu cek kesiapan akun dan test order lulus tanpa fill. Eksplorasi PPO satu seed 2.048 langkah pada histori pasar dengan aturan Demo menghasilkan return net -1,5893% pada tujuh hari validasi, di bawah baseline +0,0886%. Metadata produksi untuk backtest formal, provider, anggaran, dan kanal alert masih tertunda.

Uji ulang pukul 15.51 WIB mengonfirmasi DNS IPv4 Futures dan Demo berfungsi, tetapi koneksi HTTPS gagal sebelum respons HTTP. Endpoint checksum arsip publik tetap dapat diakses.

Pemeriksaan pukul 22.58 WIB menemukan Windows Time sudah sinkron setelah `w32tm /resync /rediscover`. Bukti preflight setelah akses pulih tersedia di `data/audit/demo-preflight-recheck-20261121.json`. Adapter test order Demo dan lookup sudah diuji dengan fixture. Fill dan proteksi Demo aktual belum diuji.

## Catatan filesystem dan validasi

AGENTS.md dan agents.md memiliki inode sama pada filesystem case-insensitive. Panduan utama dipulihkan; jangan membuat alias pengarah yang menimpanya. Validasi dokumentasi mencakup tautan, heading, kontradiksi status dan parameter v0.1; bukan bukti profitabilitas.
