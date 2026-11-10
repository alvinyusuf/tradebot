# Spesifikasi eksperimen v0.1

Tanggal: 10 November 2026. Status: definisi lengkap untuk implementasi simulator, bukan hasil strategi tervalidasi. Parameter di bawah adalah default teknis yang dipilih agent dalam mandat pengguna untuk menuntaskan definisi; batas produk mengikuti keputusan pengguna. Perubahan parameter menghasilkan versi eksperimen baru sebelum final test.

## Scope dan parameter tetap

BTCUSDT perpetual USDⓈ-M, USDT isolated, modal simulasi 100 USDT sebagai pendekatan USD 100. Satu posisi, one-way, tanpa averaging, pyramiding atau pembalikan langsung. Auto-add margin mati. Risiko awal 0,5% per transaksi, maksimum harian 5%, leverage integer 1–5x, margin awal maksimum 25% basis equity. Tidak ada target profit harian wajib.

Keputusan sesudah candle 15m selesai; tren memakai 1h selesai. Durasi posisi maksimum 16 candle 15m (4 jam) sejak fill. Di deadline, close pada kesempatan eksekusi berikutnya. Tidak entry ulang pada candle yang sama dengan exit. Tidak membuka posisi bila sudah ada posisi atau entry berstatus unknown/pending.

## Data, waktu, dan reproducibility

- Dataset tetap: 2023-01-01 00:00 UTC sampai 2026-11-01 00:00 UTC, akhir eksklusif. Warmup tambahan 30 hari sebelum awal; tidak dinilai sebagai trading.
- Input minimum: candle contract price 1m, mark-price 1m, funding aktual beserta waktu settlement, metadata kontrak/filter bertimestamp. Turunkan candle 15m dan 1h dari 1m yang lengkap; jangan mengisi gap OHLC dengan forward-fill.
- Missing candle, funding tidak lengkap atau ketidakselarasan timestamp membuat episode terkait tidak valid; laporkan coverage dan jumlah periode yang dikeluarkan. Tidak mengeksekusi pada data stale. Training hanya mengambil episode dari blok kontigu lengkap. Validation/test tidak membuang kerugian di sekitar gap: jika posisi aktif atau interval penilaiannya melintasi gap, fold ditandai invalid dan gate ditolak sampai data diperbaiki; tidak memulai ulang modal untuk menyembunyikan gap.
- Dataset harus menyimpan source, fetched_at, available_at jika relevan, checksum, timezone UTC, schema version, duplikat/gap, dan cakupan. Manifest wajib pada setiap run.
- Metadata exchange historis yang tidak tersedia tidak boleh dibuat-buat. Run memakai snapshot aktual sebagai pendekatan diberi label `current_rules_approximation`; bukan bukti kelayakan historis/live tanpa audit tambahan.
- Spread/order book historis dan open interest tidak menjadi fitur v0.1 karena ketersediaan belum dibuktikan. Paper mengumpulkan spread/depth untuk validasi eksekusi.

## Strategi pembanding

Indikator dari candle selesai: EMA20/EMA50 pada 1h untuk tren; EMA20, RSI14, ATR14 Wilder pada 15m; rata-rata volume 20 candle sebelumnya (tidak termasuk candle sinyal).

Long: EMA20 1h > EMA50 1h; close 15m sebelumnya <= EMA20 sebelumnya dan close saat ini > EMA20 saat ini; RSI14 antara 50–70 inklusif. Short: kondisi tren/cross dibalik dan RSI antara 30–50 inklusif. Volume candle sinyal >= rata-rata volume 20 sebelumnya. Jika tidak terpenuhi, wait. Sinyal memakai order market pada open 1m berikutnya ditambah slippage. Jangan fill pada close candle sinyal.

SL berjarak 1,5 × ATR14 dari harga fill; TP berjarak 3 × ATR14 (rasio gross 2:1). ATR dibekukan pada sinyal; level tidak dijauhkan atau trailing. Rounding tick: SL long ke bawah, short ke atas; TP long ke atas, short ke bawah. Hitung risiko kembali setelah rounding. Model RL memakai aturan SL/TP dan timeout yang sama.

## Sizing dan batas harian

Misalkan E0 equity awal hari UTC, E equity terkini. Untuk v0.1 setoran/penarikan saat run dilarang; deteksi transfer pada paper membuat halt dan rekonsiliasi/rebase manual tercatat. Training/backtest tidak memiliki arus dana eksternal.

Basis risiko B = min(E0, E). Budget per entry = min(0,005 × B, sisa budget harian setelah risiko posisi/order yang sudah dialokasikan). PnL, funding, dan biaya masuk E. Sisa harian = max(0, E − 0,95 × E0); laba tidak boleh menaikkan budget harian di atas 0,05 × E0. Kandidat entry juga harus memenuhi budget biaya/slippage dan margin setelah fill.

Hitung kerugian kandidat dari kuantitas × jarak entry-SL yang telah dibulatkan, ditambah fee entry/exit, cadangan slippage exit dan funding debit yang relevan. Jangan menganggap funding credit menambah anggaran risiko. Funding mendatang tidak dianggap diketahui; gunakan nilai indikatif yang tersedia, atau cadangan absolut 0,1% notional per settlement jika data indikatif tidak tersedia. Jika tidak bisa membentuk perkiraan konservatif, skip.

Pilih kuantitas terbesar dalam budget, bulatkan ke bawah sesuai filter, lalu validasi kembali. Pilih leverage terkecil 1–5x yang memenuhi margin awal <= 25% B dan menyisakan saldo untuk biaya. Harus ada buffer jarak likuidasi dari entry minimal 2 × jarak entry-SL menurut model maintenance margin/bracket. Jika metadata/bracket wajib tidak tersedia, run tidak boleh dianggap valid untuk integrasi/live. Skip bila tidak layak, bukan memindahkan SL.

Reset hari 00.00 UTC: E0 = equity saat boundary (mark termasuk posisi terbuka). Risiko posisi yang melintasi boundary dihitung ulang terhadap budget baru sebelum mengizinkan entry. Day halt hanya boleh pulih setelah akun flat dan rekonsiliasi berhasil. Halt sistem memerlukan recovery eksplisit terpisah. Pada rugi >= 5% E0, batalkan entry dan close reduce-only, verifikasi flat dan bersihkan proteksi; jeda sampai hari berikutnya. Overshoot dicatat sebagai pelanggaran/kejadian risiko, bukan disembunyikan.

## Biaya dan simulasi eksekusi

Asumsi riset yang dibekukan, bukan klaim tarif akun Binance: taker 0,05% per fill, maker tidak digunakan. Slippage dasar 0,02% per sisi, stress 0,05% per sisi. Funding memakai settlement aktual selama posisi terbuka. Tidak double-count spread: slippage proxy mencakup spread saat tidak ada quote historis. Perubahan asumsi memerlukan versi run baru.

Entry/close keputusan menggunakan open 1m berikutnya dengan slippage melawan arah order. Gap stop dieksekusi pada harga lebih buruk antara level SL dan open candle pemicu, lalu slippage. TP disimulasikan sebagai exit market setelah trigger, bukan fill limit yang pasti. Jika TP dan SL tersentuh pada menit sama, gunakan SL dahulu. Mark price memicu SL/TP; contract price menjadi dasar harga fill sesuai model di atas. Likuidasi dipicu dari mark-price dan bracket maintenance, bukan SL; bila urutan likuidasi/stop ambigu dalam menit sama, pakai likuidasi lebih dahulu. Laporkan keterbatasan resolusi 1m.

Fee/margin/filter diperiksa setelah rounding dan simulasi fill; entry yang tidak layak ditolak, tanpa fill parsial ideal yang dibuat-buat. Model dasar historis tidak mengklaim dapat merekonstruksi antrean/depth; partial fill dan latensi diuji terpisah lewat fault injection dan demo.

## RL pertama: PPO

Observation berisi 32 candle 15m fitur tertutup: log return, (close−EMA20)/ATR, RSI14/100, ATR14/close, volume/rata-rata20; konteks 1h: (EMA20−EMA50)/ATR14 1h. Tambahkan arah posisi {-1,0,1}, unrealized PnL/B, waktu posisi/16, pemakaian margin/B, dan sisa budget harian/(0,05 E0). Tidak masukkan data masa depan, timestamp unik atau harga mentah tanpa normalisasi. Statistik standardisasi fit hanya training, dibekukan saat validasi/test.

Actions: WAIT, LONG, SHORT, HOLD, CLOSE. Saat flat, HOLD/CLOSE menjadi no-op; saat posisi aktif, LONG/SHORT/WAIT menjadi hold. Intent tidak valid dihitung dan dilaporkan, tidak menyebabkan order baru. Entry RL harus lolos volume filter yang sama serta risk engine; tidak diwajibkan memenuhi sinyal tren/cross baseline.

Reward per step = log(E_after/E_before), memakai marked equity net termasuk exit, fee dan funding; saat equity <= 0 terminasi sebagai failure dengan reward -1. Tidak ada penalti risiko tambahan v0.1; batas risiko berada di environment/risk engine. Boundary reward tidak boleh menghapus PnL atau menduplikasi fee. Episode training 30 hari kalender acak dari train, warmup 32 candle dan indikator 1h, awal flat, modal 100; likuidasi seluruh sisa posisi dan charge biaya pada akhir episode. Timeout episode ditandai truncation sesuai kontrak Gymnasium; kegagalan equity adalah termination. Test berkelanjutan per fold dengan modal 100 di awal fold, bukan reset harian ke 100.

Konfigurasi awal PPO: MLP [64,64], learning_rate 0,0003, n_steps 2048, batch_size 64, n_epochs 10, gamma 0,99, gae_lambda 0,95, clip_range 0,2, ent_coef 0,0; maksimum 1 juta step per seed, seed 11/22/33/44/55. CPU dahulu. Evaluasi checkpoint tiap 50.000 step; pemilihan hanya dari validation berdasarkan median return net dengan tie-break drawdown lebih kecil. Kebijakan evaluasi deterministik. Manifest merekam parameter efektif dan versi library; bila default library lain memengaruhi hasil, simpan juga.

## Pembagian dan probabilitas

Train awal 2023; validation [2024-01-01, 2024-04-01); test pengembangan [2024-04-01, 2024-07-01). Dua fold lanjut: perluas train sampai akhir Q1 lalu Q2 2024, validation masing-masing Q2 lalu Q3, test masing-masing Q3 lalu Q4. Semua rentang akhir eksklusif pada boundary kuartal. Purge 4 jam di akhir tiap bagian yang menghasilkan transaksi dan jangan membawa posisi ke bagian berikutnya. Normalisasi fit ulang per train fold.

Setelah desain dipilih lewat fold pengembangan: train final 2023-01-01 sampai 2025-07-01; validation final 2025-07-01 sampai 2026-01-01; final test terkunci 2026-01-01 sampai 2026-11-01. Final test hanya dijalankan setelah konfigurasi dibekukan. Jangan memakai data final test pada keputusan fitur, reward, hyperparameter atau checkpoint.

v0.1 memakai risiko tetap 0,5%; confidence RL tidak dipakai untuk sizing. Modul probabilitas profit dan adaptasi risiko masuk v0.2 setelah evaluasi terpisah, bukan syarat v0.1. Target label nanti harus membedakan TP, SL, close model dan timeout; jangan menyebut peluang TP sebagai peluang profit untuk semua jenis exit.
