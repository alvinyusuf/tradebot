# Fase 00 — Definisi dan persistence

Tanggal: 10 November 2026. Status: selesai untuk ruang lingkup dokumentasi awal.

## Tujuan

Mengubah percakapan definisi menjadi konteks proyek yang dapat dilanjutkan antar sesi.

## Hasil

- README mencatat tujuan, risiko, RL, timeframe, instrumen, dan keterbatasan minimum order.
- Arsitektur modular monolith memisahkan policy, risiko, eksekusi, ledger dan rekonsiliasi.
- Register keputusan membedakan kesepakatan pengguna, pilihan teknis, serta usulan.
- Roadmap, memory, knowledge, panduan agent dan changelog dibuat.

## Keputusan dan alasan

RL diuji terhadap baseline dengan simulator bersama; model tidak mengendalikan batas risiko. Training/inference terpisah. Sesi berikutnya diarahkan ke spesifikasi eksperimen dan audit data, bukan live trading.

## Bukti dan keterbatasan

Verifikasi dokumentasi: tautan lokal dan konsistensi keputusan utama. Belum ada kode atau uji trading. Endpoint exchangeInfo gagal diakses; knowledge mencatat pengumuman minimum notional tanpa menganggapnya data live.

## Handoff

Baca `memory/STATE.md`. Mulai fase 01 dengan audit data dan spesifikasi parameter yang masih terbuka. Jangan menganggap usulan batas margin/hari sebagai persetujuan pengguna.
