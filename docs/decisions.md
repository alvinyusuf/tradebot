# Register keputusan

Diperbarui: 10 November 2026. Status `disepakati` berarti persetujuan pengguna dalam percakapan, bukan sistem telah diimplementasikan.

| ID | Keputusan | Status | Alasan / batas |
|---|---|---|---|
| D001 | Binance Futures, long/short dan TP/SL otomatis | Disepakati | Pengguna memilih Futures, bukan Spot |
| D002 | Modal awal sekitar USD 100 | Disepakati | Anggaran trading, bukan komputasi/hosting |
| D003 | Rugi harian maksimal 5% | Disepakati | Tidak bertambah karena confidence atau profit intrahari; eksekusi dapat overshoot |
| D004 | Risiko awal simulasi 0,5% per transaksi, termasuk cadangan biaya | Disepakati | Hingga 1% hanya opsi evaluasi berikutnya |
| D005 | BTCUSDT perpetual USDⓈ-M, margin USDT, isolated, leverage maksimal 5x | Disepakati untuk eksperimen | Tidak mengotorisasi order uang asli |
| D006 | Keputusan 15 menit, konteks candle selesai 1 jam | Disepakati | Proteksi/risiko tetap dipantau di antara candle |
| D007 | RL sebagai kandidat, strategi aturan sebagai pembanding | Disepakati | Eksplorasi di simulator; model inference beku |
| D008 | Risk engine di luar policy; TP/SL awal berbasis volatilitas | Disepakati sebagai pendekatan | Parameter dan kebijakan darurat ditetapkan sebagai default v0.1 di spesifikasi/operasi |
| D009 | Modular monolith Python, Parquet, SQLite, Gymnasium/SB3 | Pilihan teknis awal | Dipilih untuk spesifikasi lokal; belum diuji/dipasang |
| D010 | PPO sebagai algoritme pertama | Default development v0.1 | Tidak otomatis dipromosikan bila training berhasil |
| D011 | Satu posisi, margin maksimum 25%, auto-add margin mati | Default development v0.1 oleh agent | Ditentukan untuk menyelesaikan definisi; bukan klaim persetujuan eksplisit pengguna |
| D012 | Reset 00.00 UTC; cancel entry dan close saat limit harian | Default development v0.1 oleh agent | Detail recovery dan overshoot dalam spesifikasi/operasi |
| D013 | Risiko adaptif berdasarkan probabilitas profit | Tujuan pengguna, ditunda penerapannya | Confidence tindakan RL bukan peluang profit; perlu kalibrasi terpisah |
| D014 | Persistent context melalui docs/memory/knowledge dan AGENTS | Disepakati | File adalah sumber handoff antar sesi |

Angka 50% untuk transaksi/leverage sebelumnya ambigu dan tidak dipakai. Keputusan berikutnya menetapkan 0,5% risiko dan maksimum 5x. Jangan menghidupkan kembali angka tersebut sebagai konfigurasi.

Perubahan keputusan: tambahkan tanggal, konteks, alasan, dan keputusan pengganti; sinkronkan README, arsitektur, dan memory. Jangan mengubah keputusan pengguna hanya berdasarkan hasil backtest yang lebih menarik.

## Penyelesaian definisi v0.1 — 10 November 2026

Pengguna meminta agent menuntaskan definisi yang sebelumnya masih menggantung. Parameter teknis berikut ditetapkan agent untuk development, tanpa mengklaim persetujuan individual pengguna: baseline EMA/RSI/volume, TP 3 ATR/SL 1,5 ATR, timeout 4 jam, PPO dan reward log equity net, data/split tetap, fee/slippage proxy, gate numerik, kontrak recovery/backup dan laporan. Seluruh nilai lengkap berada di `experiment-spec.md`, `acceptance.md`, dan `operations.md`.

Definisi v0.1 kini dibekukan untuk implementasi. Perubahan harus punya alasan, versi dan dampak pada perbandingan. Fee/filter aktual dan hasil training bukan keputusan desain: harus dibuktikan lewat audit/tes. Anggaran provider serta kanal pengiriman eksternal merupakan gate otorisasi operasional, bukan blocker simulator.

## Urutan implementasi — 21 November 2026

Fondasi simulator dikerjakan paralel dengan audit data yang tertahan, menggunakan fixture sintetis untuk memeriksa perilaku modul. Perubahan urutan ini hanya menyangkut pekerjaan engineering. Spesifikasi eksperimen dan syarat validitas data v0.1 tetap berlaku untuk hasil baseline, RL, paper dan live.

Implementasi offline memakai PyTorch CPU dari indeks resmi di Windows dan Linux. Saat tidak tersedia funding indikatif, simulator mencadangkan hingga empat settlement dengan 0,1% per settlement selama posisi empat jam sebagai asumsi konservatif. Resolusi OHLC membatasi urutan intramenit dan model likuidasi belum mencakup biaya likuidasi aktual Binance. Periksa asumsi ini bersama bukti data sebelum menilai hasil promosi.

## Harga funding historis yang kosong — 21 November 2026

REST memberikan rate dan waktu settlement, tetapi `markPrice` kosong pada 1.000 catatan awal. Dataset menyimpan nilai harga tersebut sebagai null dan mempertahankan timestamp yang terverifikasi. Simulator menghitung nominal funding memakai mark open menit settlement untuk baris yang kosong. Ini pendekatan resolusi data untuk riset historis, dicatat di artifact; paper tetap memerlukan mark settlement aktual.

## Isolated 1x dan eksplorasi Demo

Pengguna menyetujui pengaturan awal BTCUSDT Demo Isolated 1x. Test order memeriksa autentikasi dan penerimaan request tanpa fill. Pada modal v0.1 100 USDT dan margin maksimum 25%, konfigurasi 1x menampung maksimal notional 25 USDT, di bawah minimum Demo 50 USDT. Eksplorasi lokal terpisah memakai data historis dan snapshot aturan Demo, dengan sizing simulator v0.1 hingga 5x dan biaya proxy v0.1. Artifact eksplorasi tidak digunakan sebagai pengganti percobaan formal atau untuk promosi.
