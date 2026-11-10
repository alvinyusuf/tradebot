# Status proyek

Diperbarui: 10 November 2026.

## Status aktual

- Fase 00: definisi v0.1 dan persistence selesai setelah audit/revisi. Handoff: [fase 00](phases/00-definition.md).
- Fase 01: audit runtime/data berikutnya; belum dijalankan. Spesifikasi eksperimennya sudah dituntaskan dalam fase 00.
- Implementasi: belum ada runtime, dataset, training atau tes kode. Mode dokumentasi; tidak ada deployment/order.

## Kontrak yang berlaku

Baca README, register keputusan, experiment-spec, acceptance dan operations. Produk disepakati: 100 USD, BTCUSDT USDT isolated, <=5x, risiko awal 0,5%, daily limit 5%, 15m/1h. Default development agent: satu posisi, margin <=25%, UTC day, close saat daily halt, TP/SL 3/1,5 ATR, timeout 4 jam, PPO. Detail bukan parameter yang harus ditebak lagi pada sesi berikutnya.

## Next step konkret

1. Buat catatan fase 01 dari template dan audit Python 3.11, uv, filesystem/Git serta akses sumber resmi.
2. Audit data untuk rentang dan schema di experiment-spec.md; simpan manifest coverage/checksum. Ambil filter/fee/bracket sesuai akses resmi yang tersedia; jangan meminta key live untuk riset.
3. Catat hasil aktual termasuk kegagalan akses. Setelah gate data terpenuhi, bootstrap paket/config dan implementasikan domain simulator sesuai roadmap.

## Keterbatasan nyata

API exchangeInfo sebelumnya web HTTP 451, shell gagal DNS; filter live belum terverifikasi. Tarif akun/metadata historis/coverage data dan kompatibilitas library belum dibuktikan. Ini pekerjaan audit, bukan definisi kosong. Provider/budget dan kanal alert eksternal menunggu fase operasi serta instruksi pengguna sebelum pembelian/pengiriman; tidak memblokir simulator.

## Catatan filesystem dan validasi

AGENTS.md dan agents.md memiliki inode sama pada filesystem case-insensitive. Panduan utama dipulihkan; jangan membuat alias pengarah yang menimpanya. Validasi dokumentasi mencakup tautan, heading, kontradiksi status dan parameter v0.1; bukan bukti profitabilitas.
