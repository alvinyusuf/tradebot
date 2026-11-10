# Changelog

Hanya pekerjaan selesai yang dicatat di sini. Rencana dan pekerjaan parsial berada di memory. Tanggal memakai format YYYY-MM-DD.

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
