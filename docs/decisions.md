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
| D008 | Risk engine di luar policy; TP/SL awal berbasis volatilitas | Disepakati sebagai pendekatan | Parameter dan kebijakan darurat belum final |
| D009 | Modular monolith Python, Parquet, SQLite, Gymnasium/SB3 | Pilihan teknis awal | Dipilih untuk spesifikasi lokal; belum diuji/dipasang |
| D010 | PPO sebagai algoritme pertama | Kandidat | Bandingkan hasil sebelum memutuskan |
| D011 | Satu posisi, margin maksimum 25%, auto-add margin mati | Usulan | Belum disepakati eksplisit |
| D012 | Reset 00.00 UTC; cancel entry dan close saat limit harian | Usulan | Definisi hari dan tindakan posisi perlu finalisasi |
| D013 | Risiko adaptif berdasarkan probabilitas profit | Tujuan pengguna, ditunda penerapannya | Confidence tindakan RL bukan peluang profit; perlu kalibrasi terpisah |
| D014 | Persistent context melalui docs/memory/knowledge dan AGENTS | Disepakati | File adalah sumber handoff antar sesi |

Angka 50% untuk transaksi/leverage sebelumnya ambigu dan tidak dipakai. Keputusan berikutnya menetapkan 0,5% risiko dan maksimum 5x. Jangan menghidupkan kembali angka tersebut sebagai konfigurasi.

Perubahan keputusan: tambahkan tanggal, konteks, alasan, dan keputusan pengganti; sinkronkan README, arsitektur, dan memory. Jangan mengubah keputusan pengguna hanya berdasarkan hasil backtest yang lebih menarik.
