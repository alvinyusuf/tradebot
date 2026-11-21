# Changelog

Hanya pekerjaan selesai yang dicatat di sini. Rencana dan pekerjaan parsial berada di memory. Tanggal memakai format YYYY-MM-DD.

## 2026-11-21

- Memasang dan memverifikasi Python 3.11.18 serta uv 0.13.9 di workspace.
- Menambahkan skrip audit dan memverifikasi checksum serta skema 141 arsip bulanan dan tiga arsip harian BTCUSDT dari Binance. Arsip harian memulihkan 2.880 menit mark price.
- Menambahkan audit endpoint publik yang mencatat hasil pengambilan filter BTCUSDT dan pemulihan candle berdasarkan gap dalam manifest.
- Menyiapkan paket Python 3.11 dan lockfile, loader arsip dan Parquet, fitur kausal, strategi baseline, ledger, risk sizing, serta simulator deterministik.
- Menyiapkan CLI riset, lingkungan PPO CPU, artifact checkpoint/holdout dan laporan. Meluluskan smoke test training dan evaluasi fixture.
- Menguji jurnal SQLite, backup/restore dan skenario pemulihan dengan fault injection. Menambahkan probe feed paper publik dan tes intent berdasarkan kutipan pascasinyal.
- Menyiapkan worker paper quote-driven dengan watchdog dan snapshot SQLite, pemeriksaan bukti Gate B/paper C, serta audit metadata demo baca-saja. Menguji restart, funding tertunda dan penolakan settlement yang hilang dengan fixture.
- Menghubungkan inferensi PPO beku ke worker paper, membagi transformasi observasi dengan simulator, dan menguji close dari quote pascasinyal.
- Menambahkan supervisor paper lokal, audit dan laporan harian UTC, serta backup SQLite dan uji restore untuk state paper.
- Memulihkan sinkronisasi Windows Time dan menambahkan preflight pasar publik/Demo serta adapter validasi test order Demo.
- Mengambil snapshot filter BTCUSDT serta dua candle mark price yang hilang dari API resmi. Menyesuaikan ingest untuk histori funding dengan harga settlement kosong sambil mempertahankan rate dan timestamp REST.
- Menambahkan pemeriksaan akun Demo baca-saja, dukungan file kredensial Demo eksplisit, dan primitive entry, close, proteksi serta jurnal rekonsiliasi Demo yang diuji dengan fixture.
- Memverifikasi konfigurasi BTCUSDT Demo Isolated 1x, test order tanpa fill, dan menyelesaikan eksplorasi PPO singkat pada histori pasar dengan aturan Demo.

## 2026-11-10

### Selesai

- Mendokumentasikan definisi bot Binance Futures dan keputusan pengguna: modal sekitar USD 100, BTCUSDT perpetual USDT isolated, leverage maksimal 5x, risiko awal simulasi 0,5%, batas rugi harian 5%, timeframe 15 menit/1 jam.
- Mendokumentasikan eksperimen RL dengan strategi aturan sebagai pembanding serta pemisahan policy dan risk engine.
- Menyusun arsitektur, alur data, state/recovery, penyimpanan, validasi dan tahapan development di `docs/`.
- Menyiapkan panduan `AGENTS.md` untuk alur kerja lintas sesi (nama lowercase menunjuk file sama di filesystem ini).
- Menyiapkan state, catatan fase 00 dan template handoff dalam `memory/`.
- Menyiapkan knowledge minimum order Binance dan evaluasi RL beserta sumber/keterbatasan.

### Keterbatasan yang dicatat

- Minimum order live belum terverifikasi; akses API gagal pada sesi audit sebelumnya.
- Belum ada implementasi runtime, dataset, training, hasil backtest, atau trading uang asli.

### Koreksi dan penyelesaian definisi v0.1

- Memulihkan panduan agent yang tertimpa alias akibat filesystem case-insensitive.
- Menuntaskan aturan baseline, TP/SL, timeout, sizing, leverage, daily reset/halt, input data, biaya dan simulator dalam spesifikasi eksperimen.
- Menetapkan PPO/reward/fitur/seed, pembagian kronologis dan holdout, serta gate numerik backtest/paper.
- Menetapkan kontrak monitoring, recovery, laporan, retensi/backup dan target runtime operasi.
- Menghapus kontradiksi README/arsitektur dan menyelaraskan register keputusan, roadmap, knowledge serta memory.
- Memisahkan default development agent dari persetujuan pengguna dan fakta yang masih perlu diverifikasi. Tidak mengklaim audit data atau implementasi sudah selesai.
