# Kriteria kelulusan v0.1

Ini ambang engineering/eksperimen yang dipilih sebelum pengujian, bukan janji profit atau hasil yang sudah dicapai.

## Gate A — Data dan simulator

- Manifest/checksum/split tersedia; coverage setiap rentang dinilai minimal 99,9% menit yang diharapkan. Semua gap ditampilkan; tidak menganggap gap memiliki harga tetap. Jika kurang, run ditolak untuk promosi.
- Tes long/short, rounding/minimum order, margin/bracket, funding pada boundary, equity, daily reset/halt/restart, no-lookahead, unknown submit, partial fill dan protection failure lulus. Uji determinisme run dengan seed/config sama.
- Nol pelanggaran batas keras yang disebabkan software: leverage >5x, entry di atas budget, entry tanpa state pasti, entry setelah halt. Kerugian gap di atas SL dilaporkan terpisah dari kegagalan software.
- Metadata/biaya yang hanya asumsi diberi label. Data aktual dan integrasi exchange yang diperlukan wajib diverifikasi sebelum gate demo/live.

## Gate B — RL layak masuk paper

Gunakan metrik per seed dan agregat, bukan seed terbaik saja. Semua return setelah fee/funding/slippage; biaya operasional dilaporkan terpisah.

- Final test memiliki minimal 100 transaksi tertutup per policy; kurang berarti bukti tidak cukup, bukan otomatis gagal strategi.
- Median return net lima seed >0; minimal empat dari lima seed positif.
- Median return net RL lebih tinggi daripada baseline aturan; median maximum drawdown <=10% dan setiap seed <=15%.
- Profit factor median >=1,10; bila tidak ada kerugian, laporkan tidak terdefinisi dan inspeksi sample, jangan menganggap tak terbatas sebagai bukti.
- Stress slippage 0,05% per sisi: median hasil net tetap >0 dan tidak ada likuidasi pada base/stress.
- Nol pelanggaran software pada batas risiko. Semua daily loss overshoot dianalisis; overshoot yang tidak terjelaskan memblokir promosi.
- Laporkan return per bulan, win rate, rata-rata win/loss, drawdown, biaya, funding, eksposur, turnover dan alasan skip. Jangan menggunakan win rate saja.

Bila RL tidak mengalahkan baseline, tidak dipromosikan. Baseline juga tidak otomatis diaktifkan live. Perubahan desain memerlukan eksperimen baru serta holdout yang belum dipakai untuk seleksi.

## Gate C — Paper dan demo

Paper minimal 30 hari kalender DAN 100 transaksi tertutup, maksimal observasi 90 hari; jika sampel belum cukup, status inconclusive. Hasil net paper harus positif, drawdown <=10%, tanpa likuidasi atau pelanggaran software. Model/config dibekukan sepanjang periode; pergantian versi memulai evaluasi baru.

Demo memakai kredensial demo terpisah jika tersedia/diotorisasi: uji entry/exit long dan short, konfirmasi SL/TP exchange, partial fill, timeout, unknown order, rate limit, disconnect, restart, day halt, dan restore database. Kondisi tak mudah direproduksi di demo wajib diuji dengan fault injection adapter, ditandai sesuai sumber buktinya. Tidak menafsirkan PnL demo sebagai bukti profit pasar nyata.

## Gate D — Sebelum live

Butuh otorisasi pengguna, filter/fee/bracket akun aktual, kesiapan akses resmi Binance, backup-restore terbukti, watchdog dan kanal alert yang berfungsi, serta review semua gate. Anggaran hosting/compute disetujui sebelum provisioning. Belum ada tanggal aktivasi atau target return yang dijanjikan. Hasil trading dilaporkan bersama biaya operasi; sistem yang untung trading tetapi rugi setelah operasi tidak dinyatakan menguntungkan total.
