# Changelog

Hanya pekerjaan selesai yang dicatat di sini. Rencana dan pekerjaan parsial berada di memory. Tanggal memakai format YYYY-MM-DD.

## 2026-11-10

### Selesai

- Mendokumentasikan definisi bot Binance Futures dan keputusan pengguna: modal sekitar USD 100, BTCUSDT perpetual USDT isolated, leverage maksimal 5x, risiko awal simulasi 0,5%, batas rugi harian 5%, timeframe 15 menit/1 jam.
- Mendokumentasikan eksperimen RL dengan strategi aturan sebagai pembanding serta pemisahan policy dan risk engine.
- Menyusun arsitektur, alur data, state/recovery, penyimpanan, validasi dan tahapan development di `docs/`.
- Menyiapkan `AGENTS.md` dan titik masuk `agents.md` untuk alur kerja lintas sesi.
- Menyiapkan state, catatan fase 00 dan template handoff dalam `memory/`.
- Menyiapkan knowledge minimum order Binance dan evaluasi RL beserta sumber/keterbatasan.

### Keterbatasan yang dicatat

- Minimum order live belum terverifikasi; akses API gagal pada sesi audit sebelumnya.
- Belum ada implementasi runtime, dataset, training, hasil backtest, atau trading uang asli.
