# Fase 02 — Fondasi simulator

Tanggal mulai: 21 November 2026.
Status: modul lokal tersedia. Validasi eksperimen pasar masih tertahan.

## Tujuan dan kriteria selesai

Bangun paket Python terkunci, konfigurasi, loader data, simulator dan laporan deterministik. Buktikan perilaku domain dengan tes lokal dan ulangi simulasi pada input pasar terverifikasi sebelum menilai Gate A.

## Input dan keputusan yang berlaku

Spesifikasi eksperimen v0.1, batas risiko, periode, dan syarat promosi tetap berlaku. Audit data Fase 01 dan pekerjaan offline Fase 02 berjalan paralel. Fixture sintetis dan model smoke test tidak menjadi bukti kesiapan strategi.

## Checkpoint

- Paket `src/tradebot/`, `pyproject.toml`, dan `uv.lock` memakai Python 3.11. Ekstra learning memuat PyTorch CPU, Gymnasium, dan Stable-Baselines3.
- Loader memeriksa checksum arsip, sumber, bukti REST dan settlement funding, serta mendukung Parquet immutable. Fitur dan baseline memakai candle yang selesai. Simulator memakai ledger Decimal, sizing dengan filter dan bracket, TP/SL, funding, margin, batas UTC dan fill setelah keputusan.
- CLI menjalankan audit, kurasi, baseline, training dan evaluasi PPO. Pemilihan checkpoint memakai split validasi dan median lima seed. Jalur holdout memerlukan artifact final yang dibekukan dan indeks dari ketiga fold pengembangan. Report mencatat konfigurasi, versi implementasi, sumber, equity, transaksi dan biaya.
- Jurnal SQLite dan harness eksekusi offline menguji pemulihan order berstatus unknown, deduplikasi, partial fill, kegagalan proteksi, stale data, dan backup/restore. Worker paper lokal menghubungkan feed publik, freshness, intent dan fill simulasi berdasarkan kutipan. Checkpoint SQLite memulihkan portofolio, baseline harian, halt, cursor dan jadwal funding. Restart memerlukan rekonsiliasi sebelum entry.
- Pemeriksaan Gate B dan paper Gate C menerima metrik eksplisit dan mengembalikan lulus, gagal atau bukti belum cukup.
- Audit baca-saja demo menormalkan filter, bracket dan fee untuk BTCUSDT demo. Tes fixture memeriksa host, metode GET, signature dan whitelist output.

## Validasi

Pemeriksaan akhir menghasilkan 87 tes dan dua subtes lulus. Ruff, `uv lock --check`, serta `git diff --check` lulus. Smoke test PPO CPU menyelesaikan pelatihan singkat fixture, menyimpan checkpoint, memuat ulang model, serta menghasilkan laporan. Cek loader pada arsip nyata membaca bagian yang dipulihkan lalu menolak gap. Probe paper publik gagal dengan WinError 10061 sebelum ada HTTP. Probe waktu publik pada host demo resmi juga gagal membuka koneksi dengan curl exit 7.

## Blocker dan pekerjaan tertunda

- Endpoint publik Futures Binance belum dapat diakses dari workspace. Dua candle mark price, filter aktual dan validasi settlement funding belum tersedia. Metadata historis dan bracket/fee aktual juga belum ada.
- Belum ada backtest pasar yang sah, training PPO v0.1 lima seed pada data aktual, fold pengembangan, hasil holdout, atau dasar keputusan promosi.
- Resolusi OHLC 1m membatasi urutan intramenit. Model likuidasi memakai fill konservatif dan fee taker proxy. Biaya likuidasi aktual, antrean, dan realisme eksekusi memerlukan validasi integrasi.
- Paper memerlukan integrasi layanan unattended di host, rekonsiliasi operasional, serta observasi forward 30–90 hari. Demo order, kesiapan host, dan kanal alert eksternal masih belum dibuktikan.

## Handoff berikutnya

Ulangi audit REST lewat akses Binance yang resmi tersedia. Setelah bukti data dan metadata siap, jalankan Gate A pada input pasar, baseline, eksperimen PPO, serta evaluasi base dan stress. Gunakan hasil tersebut untuk menentukan kelayakan masuk paper dan demo sesuai `docs/acceptance.md`.

## Checkpoint inferensi paper PPO — 21 November 2026

`paper_policy.py` memuat checkpoint final CPU yang sesuai hash, dengan scaler train yang beku. Simulator dan paper berbagi transformasi observasi. Worker menggunakan mark candle yang sudah selesai untuk keputusan dan quote sesudah sinyal untuk eksekusi simulasi. Tes meliputi aksi long/short, WAIT/HOLD, close, penolakan checksum berbeda, dan halt saat inferensi gagal. Pemeriksaan terbaru meluluskan 94 tes dan dua subtes, Ruff dan `git diff --check`. Uji ulang endpoint publik Futures tetap gagal dengan curl exit 7 sebelum HTTP. Tidak ada model yang dinilai pada pasar aktual atau dipromosikan ke paper.

## Checkpoint supervisor paper — 21 November 2026

`paper_supervisor.py` menjalankan watchdog saat polling masih berjalan, membatasi ke satu permintaan aktif, mencatat heartbeat, dan memerlukan rekonsiliasi eksplisit untuk kembali siap. Uji fixture memeriksa backoff, penolakan status HTTP 4xx, audit yang gagal dan penghentian dengan polling tertunda. `paper_audit.py` menyimpan observasi ekuitas dan event untuk laporan UTC. Backup SQLite lokal diuji dengan pemulihan state ke file terpisah. Audit mengikuti checkpoint dalam transaksi terpisah. CLI menyediakan `paper report` dan `paper backup`.

Pemeriksaan terbaru meluluskan 103 tes dan dua subtes, Ruff, validasi lockfile, dan `git diff --check`. Probe waktu API Futures kembali gagal dengan curl exit 7 sebelum HTTP. Supervisor belum dijalankan sebagai layanan host atau digunakan untuk mengambil bukti paper forward.

## Checkpoint pemeriksaan awal Demo — 21 November 2026

`demo_preflight.py` memeriksa feed pasar dan server Demo secara terpisah tanpa kredensial. `demo_execution.py` menangani test order dan lookup bertanda tangan khusus host Demo. CLI menyediakan `demo preflight` dan `demo validate-order`. Tes fixture memeriksa signature, host, dan respons ambigu. Total 111 tes dan dua subtes lulus. Preflight aktual gagal di kedua koneksi. Validasi bertanda tangan, fill, dan pemulihan order Demo aktual belum dijalankan.

## Checkpoint integrasi Demo — 21 November 2026, 23.29 WIB

Preflight publik Futures dan Demo kembali lulus, termasuk candle selesai, quote dan mark segar serta waktu server Demo. `demo check-account --env-file .env` berhenti sebelum request karena dua kredensial Demo belum tersedia. Loader hanya membaca dua nama Demo yang ditentukan. Tidak ada nilai kredensial yang dicetak atau disimpan.

Adapter menyediakan primitive entry market dari rencana risiko, exit reduce-only, dan proteksi close-position SL/TP berbasis mark. Mutasi pada adapter membutuhkan pilihan aktivasi eksplisit. Jurnal menyimpan intent sebelum submit dan memakai lookup ID yang sama setelah hasil tidak pasti. Integrasi supervisor, konfirmasi fill dan recovery lintas endpoint masih perlu pembuktian pada akun Demo. Seluruh 130 tes dan dua subtes, Ruff dan `git diff --check` lulus.

## Checkpoint autentikasi Demo

Metadata Demo berhasil diambil melalui request baca-saja dan disimpan di `data/audit/demo-metadata-20261121.json`. API mengembalikan leverage 0 pada BTCUSDT. Pemeriksa sekarang melaporkannya sebagai belum dikonfigurasi. Satu kali pemeriksaan ulang memverifikasi bahwa akun masih mode crossed, one-way, flat dan tanpa order reguler atau algo. Test order ditunda hingga konfigurasi akun lulus. Tidak ada perubahan akun atau pengiriman order.

## Checkpoint konfigurasi dan eksplorasi PPO Demo

Dengan persetujuan pengguna, BTCUSDT Demo diatur ke Isolated 1x. Pemeriksaan ulang mengonfirmasi one-way, flat dan tidak ada order terbuka. Test order BUY 0,001 diterima tanpa fill. Respons aktual berupa envelope berisi nilai default; parser dan tes disesuaikan untuk bentuk tersebut. Akun tetap flat.

`scripts/explore_demo_ppo.py` melatih PPO 2.048 langkah seed 11 pada Januari–Februari 2023 dan menilai 1–8 Januari 2024 eksklusif. Eksplorasi memakai data asli dengan snapshot aturan Demo, leverage simulasi hingga 5x, dan biaya proxy v0.1. Pada tujuh hari validasi, PPO -1,5893% net, drawdown 2,1344% dan 21 transaksi. Baseline +0,0886% net, drawdown 0,4478% dan dua transaksi. Ringkasan dan model tersimpan di `runs/demo-ppo-exploration-20261121/`. Sampel ini tidak memenuhi syarat promosi. Holdout belum dibaca.
