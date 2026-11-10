# Tradebot

Service untuk trading kripto otomatis di Binance. Pengguna menentukan modal dan batas risiko, lalu memantau hasil tanpa menjalankan transaksi satu per satu.

Status: tahap definisi. Belum ada strategi yang terbukti, kode trading, atau izin menjalankan transaksi dengan uang asli.

## Dokumentasi dan cara melanjutkan

- [Panduan AI agent](AGENTS.md): urutan membaca konteks dan aturan kerja lintas sesi.
- [Arsitektur](docs/architecture.md): modul, alur data, simulator, risiko, eksekusi dan recovery.
- [Register keputusan](docs/decisions.md): keputusan yang disepakati, pilihan teknis dan usulan.
- [Tahapan development](docs/development-plan.md): keluaran dan kriteria tiap fase.
- [Status terkini](memory/STATE.md): titik lanjut sesi berikutnya, hasil aktual dan pekerjaan tertunda.
- [Knowledge](knowledge/README.md): pengetahuan bersumber dan keterbatasan verifikasinya.
- [Changelog](CHANGELOG.md): pekerjaan yang telah selesai.

## Kebutuhan yang sudah jelas

- Service berjalan terus dan mengambil keputusan trading secara otomatis.
- Exchange yang digunakan adalah Binance.
- Produk: Futures, dengan pemilihan long/short dan pemasangan TP/SL otomatis.
- Modal awal sekitar USD 100, dengan margin USDT untuk eksperimen awal.
- Pengguna ingin alokasi risiko adaptif: peluang profit yang lebih kuat dapat memperoleh alokasi lebih besar; pasar sepi atau peluang lemah memperoleh alokasi lebih kecil atau dilewati. Besar/kecil peluang dinilai dari estimasi probabilitas.
- Probabilitas tidak otomatis membolehkan leverage tinggi atau SL diperlebar. Pemetaan probabilitas ke risiko belum ditentukan; batas keras leverage eksperimen adalah 5x.
- Batas kerugian harian maksimal 5% dari equity awal hari, dengan penyesuaian setoran/penarikan. Pada equity awal hari USD 100, anggaran rugi adalah USD 5. Basis equity dan aturan penanganannya dijabarkan dalam rancangan risiko di bawah.
- Risiko awal untuk simulasi disepakati 0,5% equity per transaksi, termasuk cadangan biaya/slippage. Pada basis equity USD 100, anggarannya USD 0,50. Nilai ini adalah anggaran rugi, bukan margin atau target profit, dan bukan jaminan batas rugi aktual.
- Kenaikan risiko hingga 1% hanya menjadi opsi evaluasi setelah bukti pada data baru dan paper trading mendukung; tidak otomatis diaktifkan.
- Pengguna terutama ingin melihat dan menilai hasil trading.

## Ruang lingkup awal

- Disepakati untuk eksperimen awal: BTCUSDT perpetual USDⓈ-M, margin USDT, isolated margin, dan batas keras leverage 5x.
- Strategi berbasis aturan menjadi pembanding untuk eksperimen reinforcement learning; RL hanya dipromosikan jika lolos evaluasi.
- Jumlah pasangan trading dibatasi; pasangan dipilih setelah memeriksa ketersediaan, likuiditas, dan ketentuan order.
- Tidak wajib selalu punya posisi. Menahan saldo adalah keputusan yang valid saat tidak ada sinyal.
- Modal yang dikelola bot dibatasi secara eksplisit.
- Mode awal adalah simulasi; trading uang asli diaktifkan terpisah setelah evaluasi dan persetujuan pengguna.

Konfigurasi instrumen dan pendekatan eksperimen telah disepakati. Detail strategi, simulasi eksekusi, dan kriteria kelulusan masih harus ditentukan dan diuji. Kesepakatan eksperimen ini bukan aktivasi trading uang asli.

## Pendekatan AI yang disepakati

- Reinforcement learning (RL) menjadi kandidat eksperimen, dengan strategi sederhana berbasis aturan sebagai pembanding.
- Fokus model awal: keputusan long, short, tidak entry, mempertahankan posisi, dan menutup posisi. Tindakan yang tersedia disesuaikan dengan keadaan posisi.
- Ukuran posisi, leverage, TP/SL, dan batas rugi harian dikendalikan modul risiko terpisah. Model tidak dapat melonggarkan batas tersebut.
- TP/SL awal memakai aturan berbasis volatilitas yang parameternya ditetapkan lewat pengujian. Model boleh meminta keluar lebih awal; proteksi tetap aktif sampai posisi benar-benar tertutup.
- Pelatihan dan eksplorasi hanya di simulator. Model untuk paper/live trading dibekukan; pembaruan model harus melewati evaluasi sebelum dipakai.
- Reward mempertimbangkan perubahan equity setelah biaya, funding, dan slippage. Penalti risiko menjadi kandidat rancangan, bukan pengganti batas keras risiko.
- RL memilih tindakan untuk hasil jangka panjang. Probabilitas memilih tindakan bukan probabilitas transaksi profit. Peningkatan risiko berdasarkan probabilitas ditunda sampai ada estimasi peluang terkalibrasi yang diuji terpisah.
- PPO menjadi kandidat algoritme pertama, belum pilihan final. Stack teknologi belum ditetapkan.
- Dana trading USD 100 terpisah dari anggaran komputasi, penyimpanan, dan hosting.

## Timeframe yang disepakati

- Keputusan strategi dibuat setelah penutupan setiap candle 15 menit.
- Konteks arah tren menggunakan candle 1 jam terakhir yang sudah selesai pada waktu keputusan. Jangan menggunakan nilai akhir candle 1 jam yang saat itu masih berjalan.
- TP/SL dan pemantauan batas risiko tetap aktif di antara keputusan strategi; tidak menunggu candle 15 menit berikutnya.
- Simulator harus memodelkan eksekusi setelah informasi candle tersedia, bukan mengasumsikan selalu mendapat harga penutupan candle sinyal.
- Pasangan eksperimen pertama yang disepakati adalah BTCUSDT perpetual USDⓈ-M dengan margin USDT dan isolated margin.

## Rencana eksperimen berikutnya

Pemeriksaan awal minimum order (10 November 2026): pengumuman resmi Binance tanggal 14 April 2026 menurunkan minimum notional BTCUSDT dari 100 menjadi 50 USDT. Ini bukan pengganti pemeriksaan filter langsung: akses exchangeInfo dari sesi ini gagal sehingga nilai live belum terverifikasi. Kuantitas minimum dan step kuantitas juga dapat membuat nilai order efektif lebih besar dari minimum notional. Sumber: https://www.binance.com/en-NG/support/announcement/detail/10999fd17dc045de801c0c78ab29e6fc

Sebelum entry, baca filter aktual MIN_NOTIONAL, LOT_SIZE, MARKET_LOT_SIZE sesuai jenis order, serta PRICE_FILTER. Bulatkan ukuran yang diizinkan risiko ke bawah sesuai step, lalu periksa kembali nilai minimum, biaya, margin, dan risiko. Jika gagal, lewati entry; jangan mempersempit SL atau menaikkan risiko hanya untuk lolos minimum. Konfigurasi modal USD 100 dan risiko 0,5% tidak menjamin setiap sinyal BTCUSDT dapat dieksekusi.

1. Tetapkan pasangan, batas durasi posisi, dan aturan pembanding sebelum menilai hasil pengujian. Timeframe keputusan 15 menit dan konteks tren 1 jam telah disepakati.
2. Audit data historis: kelengkapan, timestamp ketersediaan, funding, harga untuk pemicu SL/TP, dan aturan kontrak. Data yang tidak tersedia tidak diasumsikan ada.
3. Bangun simulator bersama untuk pembanding dan RL, mencakup margin, likuidasi, biaya, funding, slippage, minimum order, serta latensi eksekusi. Observasi hanya boleh memakai data yang sudah tersedia saat keputusan; hindari fill pada harga yang belum bisa diperdagangkan.
4. Jika TP dan SL tersentuh pada candle yang sama dan urutannya tidak diketahui, gunakan data lebih rinci atau asumsi konservatif yang dilaporkan.
5. Pisahkan periode training, pemilihan model, dan pengujian akhir secara kronologis. Normalisasi hanya dipelajari dari data training; beri pemisahan untuk label/posisi yang tumpang tindih.
6. Bandingkan strategi aturan dan RL dengan modal, biaya, serta batas risiko sama pada beberapa periode dan beberapa seed training. Jangan memilih hanya hasil training terbaik.
7. Nilai profit bersih, drawdown, pelanggaran risiko, frekuensi transaksi, dan ketahanan terhadap biaya/slippage lebih besar. Ambang kelulusan numerik belum ditetapkan; harus ditentukan sebelum pengujian akhir.
8. Lanjutkan kandidat yang lolos ke paper trading dan pengujian integrasi Futures. Keputusan uang asli tetap terpisah.

## Cara menilai hasil

Keuntungan tidak dijamin. Strategi harus dinilai bersama risikonya, bukan hanya persentase transaksi yang menang.

Laporan minimal mencakup:

- Nilai total portofolio: saldo bebas, saldo dalam order, dan posisi berdasarkan harga pasar.
- Profit/loss terealisasi dan belum terealisasi, serta hasil bersih setelah biaya trading dan funding. Biaya operasional ditampilkan terpisah.
- Perubahan nilai akibat setoran atau penarikan dipisahkan dari hasil trading.
- Maximum drawdown: penurunan terbesar dari puncak nilai portofolio.
- Jumlah transaksi, biaya, eksposur modal, dan posisi yang masih terbuka.
- Pembanding memegang aset saja (buy-and-hold) dan menahan saldo quote pada periode serta modal awal yang sama.
- Status service, waktu data terakhir, dan alasan bot berhenti atau tidak trading.

Target return, batas drawdown, dan periode evaluasi belum ditentukan. Jangan menetapkan target profit harian sebagai kepastian.

## Perilaku service

Alur utama: data pasar → sinyal strategi → pemeriksaan risiko → order Binance → rekonsiliasi order dan saldo → laporan.

- Simpan keputusan, order, fill, biaya, dan perubahan saldo agar hasil bisa ditelusuri.
- Setelah restart atau koneksi terputus, cocokkan status lokal dengan Binance sebelum mengirim order baru.
- Timeout pengiriman order dianggap berstatus belum pasti; periksa statusnya sebelum mencoba lagi agar tidak terjadi transaksi ganda.
- Tangani order yang terisi sebagian, penolakan order, batas API, dan data pasar kedaluwarsa.
- Terapkan aturan harga, kuantitas, dan nilai minimum order dari exchange.
- Batas kerugian dan eksposur harus diperiksa sebelum membuka posisi.
- Jika batas risiko tercapai atau status akun tidak bisa dipastikan, hentikan order baru dan kirim pemberitahuan. Kebijakan membatalkan order atau menutup posisi harus ditentukan secara eksplisit.
- Sediakan kontrol jeda dan penghentian darurat. Stop-loss tidak menjamin harga eksekusi atau batas rugi mutlak.
- API key hanya diberi akses yang dibutuhkan untuk trading, tanpa izin penarikan; rahasia tidak disimpan di repository atau log.

## Tahapan validasi

1. Definisikan modal, toleransi kerugian, periode evaluasi, dan kebutuhan laporan.
2. Backtest dengan data historis, biaya, funding, dan asumsi slippage yang dinyatakan. Pisahkan data pengembangan strategi dari data evaluasi.
3. Paper trading memakai data pasar langsung untuk menguji keputusan dan simulasi hasil. Eksekusi simulasi tetap memiliki keterbatasan.
4. Uji integrasi order, proteksi TP/SL, pemulihan, dan rekonsiliasi di lingkungan demo/test Binance Futures. Hasil simulasi bukan bukti profitabilitas di pasar nyata.
5. Evaluasi terhadap kriteria yang sudah ditetapkan. Aktivasi uang asli membutuhkan keputusan pengguna, dimulai dengan modal terbatas.

## Keputusan yang masih diperlukan

- Tentukan batas penggunaan margin, penambahan margin otomatis, serta kebijakan posisi saat batas harian tercapai. Instrumen, isolated margin, batas leverage 5x, risiko awal simulasi 0,5%, dan batas rugi harian 5% sudah disepakati.
- Tentukan metode estimasi dan validasi probabilitas, serta pemetaannya ke anggaran risiko.
- Berapa lama periode evaluasi dan apa arti hasil yang memuaskan?
- Laporan ingin dilihat lewat apa, dan seberapa sering?
- Service akan dijalankan di mana agar tetap hidup saat komputer pribadi mati?

Stack teknis awal telah dipilih untuk rancangan lokal dalam dokumen arsitektur; versi dan kompatibilitas belum diuji. Detail strategi, parameter TP/SL, dan hosting belum dipilih.

## Rancangan risiko Futures

- Parameter operasional memakai risiko awal simulasi 0,5% per transaksi, batas rugi harian 5%, dan batas leverage 5x yang disepakati setelah evaluasi. Angka 50% sebelumnya tidak digunakan sebagai konfigurasi.
- Risiko awal simulasi yang disepakati: 0,5% equity per transaksi termasuk cadangan biaya/slippage. Kenaikan hingga 1% masih memerlukan evaluasi dan keputusan. Usulan basis perhitungan: equity yang lebih kecil antara equity terkini dan equity awal hari, setelah penyesuaian arus dana. Sisa batas harian dapat memperkecil risiko ini lagi; kondisi lemah dapat menyebabkan transaksi dilewati.
- Batas keras leverage eksperimen yang disepakati adalah 5x. Rentang awal 1–3x tetap rekomendasi untuk diuji, bukan angka yang terbukti optimal. Pilih leverage sesuai kebutuhan margin dan jarak likuidasi; jangan menaikkannya karena minimum order atau sinyal yang belum tervalidasi.
- Rekomendasi modal margin maksimum 25% equity untuk satu posisi aktif dengan isolated margin dan tanpa penambahan margin otomatis. Angka ini berbeda dari risiko rugi di SL dan tidak menjamin batas rugi harian.
- Batas harian 5% adalah penghentian darurat, bukan target anggaran yang harus dihabiskan. Jika ukuran minimum order tidak cocok dengan risiko kecil, lewati pasangan tersebut atau tetap gunakan simulasi.
- Definisikan probabilitas sebagai peluang TP tercapai sebelum SL dalam horizon waktu tertentu, untuk arah dan level entry/TP/SL tertentu. Aturan posisi yang mencapai batas waktu harus eksplisit dalam pengujian dan eksekusi.
- Fitur kandidat: tren, momentum, volatilitas, volume, spread, dan kedalaman order book. Pasar sepi dinilai dari data likuiditas dan aktivitas, bukan jam saja.
- Bedakan skor sinyal dari probabilitas terkalibrasi. Validasi pada data di luar pengembangan secara berurutan dalam waktu, tanpa kebocoran data masa depan, dan bandingkan estimasi peluang dengan frekuensi hasil aktual.
- Pertimbangkan expected value bersih: peluang menang × rata-rata keuntungan dikurangi peluang kalah × rata-rata kerugian dan biaya. Sertakan hasil keluar karena batas waktu bila ada. Peluang menang tinggi saja belum cukup.
- Naikkan anggaran risiko per transaksi hanya di dalam batas keras jika probabilitas tervalidasi, expected value bersih, likuiditas, serta sisa anggaran harian mendukung. Jika bukti belum cukup atau kondisi berbeda dari data pengujian, kurangi risiko atau lewati transaksi.
- Makna batas lebih longgar: alokasi risiko per transaksi boleh bertambah dalam batas yang disepakati. Batas kerugian harian tetap; SL ditentukan sebelum entry dan tidak dijauhkan untuk menunda realisasi rugi.
- Tentukan entry dan SL, lalu ukuran posisi berdasarkan anggaran rugi. Pilih leverage setelahnya berdasarkan kebutuhan margin dan jarak likuidasi.
- Perkiraan rugi di SL = nilai nosional × jarak SL dalam persen + biaya dan slippage. Perhitungkan funding bila relevan.
- Rasio reward/risk membandingkan potensi hasil di TP dengan rugi di SL setelah biaya. Rasio tinggi saja tidak cukup untuk menaikkan leverage.
- Tanpa leverage tambahan berarti 1x jika kontrak mendukungnya; lewati transaksi jika batas risiko tidak terpenuhi.
- Jangan memperbesar posisi demi memenuhi minimum order apabila melanggar anggaran risiko. Jangan menggandakan posisi untuk mengejar kerugian.
- Ukur rugi harian dari equity awal hari terhadap equity terkini, termasuk PnL belum terealisasi, biaya, dan funding, dengan penyesuaian setoran/penarikan. Zona waktu reset belum ditentukan.
- Batas harian 5% tidak dinaikkan karena probabilitas sinyal, keuntungan intrahari, atau keinginan mengejar kerugian. Restart tidak mereset anggaran. Equity awal hari dan arus dana harus disimpan secara persisten.
- Risiko posisi dan calon order harus muat dalam sisa anggaran rugi harian. Mulai dengan satu posisi aktif.
- Saat batas harian tercapai: batalkan entry, tutup posisi dengan order yang hanya mengurangi posisi, lalu jeda sampai hari berikutnya. Kebijakan ini masih perlu disepakati; batas rugi tidak dijamin karena slippage atau kegagalan eksekusi.
- Tempatkan proteksi TP/SL di exchange, verifikasi setelah fill, tangani partial fill, dan bersihkan order sisa setelah posisi ditutup. Kegagalan proteksi harus memicu penanganan darurat.
- Restart dan pergantian hari tidak menghapus status risiko sebelum rekonsiliasi akun selesai.

## Referensi resmi Futures

- [Dokumentasi Futures USDⓈ-M](https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info)
- [Informasi kontrak dan aturan order](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information)
- [Kebutuhan margin](https://www.binance.com/en/support/faq/detail/4f83b65d83654b5e933f85ef12bf769d)

- [Panduan eksperimen dan evaluasi RL](https://stable-baselines3.readthedocs.io/en/master/guide/rl_tips.html)
