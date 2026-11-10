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

RL diuji terhadap baseline dengan simulator bersama; model tidak mengendalikan batas risiko. Training/inference terpisah. Spesifikasi eksperimen diselesaikan pada revisi fase ini; sesi berikutnya diarahkan ke audit data/runtime, bukan live trading.

## Bukti dan keterbatasan

Verifikasi dokumentasi: tautan lokal dan konsistensi keputusan utama. Belum ada kode atau uji trading. Endpoint exchangeInfo gagal diakses; knowledge mencatat pengumuman minimum notional tanpa menganggapnya data live.

## Handoff

Baca `memory/STATE.md`. Mulai fase 01 dengan audit data/runtime sesuai spesifikasi lengkap v0.1. Bedakan default teknis agent dari keputusan eksplisit pengguna.

## Checkpoint koreksi definisi — 10 November 2026

Audit menemukan panduan AGENTS tertimpa alias karena nama case-insensitive, README/arsitektur bertentangan, serta parameter inti dan gate hanya ditunda. Panduan dipulihkan; README dipadatkan; experiment-spec.md, acceptance.md dan operations.md mengisi parameter/split/reward/risiko/recovery/gate secara eksplisit. Register keputusan, roadmap, STATE, knowledge dan changelog diselaraskan. Status implementasi tetap belum dimulai. Klaim lama bahwa pemeriksaan tautan sudah cukup untuk kelengkapan definisi dikoreksi: pemeriksaan tersebut tidak mendeteksi isi panduan yang menunjuk dirinya sendiri.

Validasi revisi: 16 file Markdown unik lolos pemeriksaan tautan lokal, heading utama dan penutupan code fence. Isi panduan AGENTS diperiksa eksplisit dan identitas inode uppercase/lowercase dikonfirmasi. Pencarian status parameter menggantung tidak menemukan parameter inti yang masih ditunda. Tidak ada tes runtime/trading karena perubahan hanya dokumentasi.
