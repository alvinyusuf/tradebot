# Status proyek

Terakhir diperbarui: 10 November 2026.

## Posisi saat ini

- Fase terakhir selesai: 00 — definisi awal, arsitektur, dan persistence dokumentasi.
- Fase berikutnya: 01 — spesifikasi eksperimen dan audit data; belum dimulai.
- Handoff terakhir: [fase 00](phases/00-definition.md).
- Implementasi: belum ada kode runtime, dataset, simulator, model terlatih, atau tes kode.
- Mode: dokumentasi saja; tidak ada order, deployment, atau penggunaan API key.

## Keputusan utama

Binance BTCUSDT perpetual USDⓈ-M, USDT isolated, modal sekitar USD 100, leverage maksimal 5x. Risiko awal simulasi 0,5% per transaksi dan rugi harian maksimal 5%. Keputusan candle 15 menit, konteks candle 1 jam selesai. RL kandidat eksperimen dengan baseline aturan; risk engine terpisah dan training di simulator.

## Berikutnya

1. Baca `docs/development-plan.md` dan `docs/decisions.md`.
2. Buat `memory/phases/01-experiment-spec.md` dari template saat fase dimulai.
3. Susun spesifikasi baseline, TP/SL, timeout posisi, model biaya, split data dan metrik; finalisasi kebijakan risiko yang masih usulan sebelum dipakai.
4. Audit akses data/filter Binance aktual dan runtime lokal, lalu catat hasil. Jangan mengasumsikan minimum order dari pengumuman sebagai filter live.

## Hal tertunda / keterbatasan

- Minimum order live belum terverifikasi: web menerima HTTP 451; shell gagal DNS. Ini kendala audit sumber, bukan alasan mengganti endpoint dengan cara menghindari pembatasan.
- Batas margin 25%, satu posisi, auto-add margin mati, reset 00.00 UTC dan close saat limit adalah usulan.
- Ambang kelulusan, periode data/paper trading, parameter strategi, biaya aktual akun, versi dependensi, hosting, kanal laporan belum final.
- `python` tidak tersedia saat pemeriksaan sebelumnya; `python3` berhasil dipakai untuk tooling dokumen. Versi dan dependensi belum diaudit.

## Validasi dokumentasi

Dokumen diperiksa tautan lokal dan konsistensi angka keputusan. Tidak ada klaim pengujian strategi atau minimum order live.
