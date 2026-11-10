# Fase development

Status fase di sini adalah roadmap. Status aktual berada di `memory/STATE.md`.

| Fase | Hasil yang dituju | Bukti untuk selesai |
|---|---|---|
| 00 — Definisi dan persistence | Keputusan, arsitektur, panduan agent, catatan proyek | Dokumen tersedia dan konsisten; keputusan tertunda ditandai |
| 01 — Spesifikasi eksperimen dan audit data | Data/filter dapat diperiksa, aturan baseline, TP/SL, batas waktu, policy risiko dan metrik | Manifest audit dan spesifikasi berversi; ambang dipilih sebelum test akhir |
| 02 — Fondasi simulator | Paket, konfigurasi, ledger, filter order, risk engine, simulator | Tes domain/risk/no-lookahead lulus; hasil run dapat direproduksi |
| 03 — Strategi pembanding | Backtest baseline setelah biaya | Laporan kronologis, sensitivitas biaya, penolakan order |
| 04 — Eksperimen RL | Environment, training, artifact dan evaluasi PPO | Perbandingan beberapa seed/periode dengan baseline; kegagalan juga dicatat |
| 05 — Paper dan integrasi demo | Runtime recovery, proteksi dan laporan | Paper forward serta uji partial fill, unknown order, restart, halt dan recovery |
| 06 — Kesiapan operasi/live | Hosting, backup, monitoring dan rencana aktivasi | Semua gate terpenuhi dan otorisasi pengguna; boleh tidak lanjut jika model gagal |

## Langkah berikutnya

Mulai fase 01 dengan spesifikasi eksperimen, bukan mengirim order atau melatih model tanpa simulator tervalidasi. Audit akses data dan filter BTCUSDT; kegagalan akses saat ini dicatat di knowledge. Finalisasi keputusan risiko yang tertunda sebelum simulator menganggapnya sebagai perilaku wajib.

Setiap fase memakai template `memory/templates/phase.md`. Jangan menetapkan fase selesai hanya karena file dibuat: bedakan rancangan, implementasi, dan hasil verifikasi. Fase 04 yang tidak mengalahkan baseline tetap menghasilkan temuan sah; tidak memaksa promosi model.
