# Fase 01 — Audit data dan runtime

Tanggal mulai: 21 November 2026.
Status: parsial. Prasyarat data tertahan.

## Tujuan dan kriteria selesai

Verifikasi runtime Python 3.11, akses sumber resmi, skema dan cakupan dataset BTCUSDT, serta metadata kontrak. Simpan checksum dan daftar gap untuk menilai prasyarat data sebelum membangun simulator.

## Input dan keputusan yang berlaku

Rentang, sumber data minimal, dan split mengikuti spesifikasi v0.1. Audit arsip memeriksa struktur dan waktu, tanpa menghitung metrik strategi pada holdout. Desember 2022 diperiksa sebagai satu arsip bulanan penuh agar 30 hari warmup tersedia.

## Checkpoint

Python 3.11.18 dan uv 0.13.9 tersedia secara lokal melalui `.tools/`. Skrip `scripts/audit_archives.py` mengunduh arsip publik Binance, membandingkan SHA-256 resmi, dan mengaudit OHLCV serta timestamp. Arsip dan manifest lokal berada di `data/audit/`.

## Validasi

Git berfungsi dan working tree awal bersih. Instalasi Python 3.11 diuji dengan `uv run --no-project --python 3.11 python --version`. Skrip lulus `py_compile` dengan Python 3.11.

Audit dengan Python 3.11 memverifikasi SHA-256 dan skema 141/141 arsip bulanan serta tiga arsip harian. Terdapat 2.060.640 candle contract price dan 4.293 catatan funding tanpa selisih interval pada pemeriksaan jadwal. Mark price bulanan memiliki 2.057.758 candle. Arsip harian memulihkan 2.880 menit, sehingga masih kurang dua menit dari 2.060.640 yang diharapkan. Cakupan mark price gabungan sekitar 99,9999% untuk seluruh arsip yang diaudit.

Exit skrip 1 mencerminkan dua candle tersisa. Manifest lokal `data/audit/manifest.json` memiliki SHA-256 `02ce4758d64967173930539bb97fb6deae1cadbcf14a3a85b6846cec66ece1dd`. Manifest menyimpan checksum sumber dan timestamp gap/pemulihan.

## Blocker dan pekerjaan tertunda

Koneksi HTTPS ke `fapi.binance.com` gagal dua kali dari workspace dengan curl exit 7 dan status HTTP 000. `exchangeInfo` BTCUSDT, snapshot filter bertimestamp, dan histori perubahan filter belum terverifikasi. Dokumentasi resmi menyebutkan fee akun dan bracket sebagai endpoint `USER_DATA` yang perlu autentikasi. Belum ada bukti aktual untuk keduanya.

Arsip bulanan dan harian sama-sama kehilangan mark price BTCUSDT 1m pada 12 Agustus 2024 pukul 10.02 dan 10.03 UTC. Permintaan REST untuk rentang itu gagal dengan curl exit 7 dan HTTP 000. Gap berada di uji pengembangan Q3 2024 yang harus mencakup seluruh interval. Perbandingan timestamp arsip funding dengan settlement API juga tertunda.

## Handoff berikutnya

Pulihkan dua candle melalui akses resmi yang tersedia dan ulangi pemeriksaan cakupan. Verifikasi metadata dan semantik settlement dari sumber resmi. Bootstrap simulator mengikuti hasil gate data.

## Checkpoint uji ulang REST — 21 November 2026

Ditambahkan `scripts/audit_public_api.py` untuk mengambil snapshot symbol BTCUSDT dan satu candle per timestamp yang tertinggal di manifest. Hasil menyimpan URL sumber, waktu pengambilan, hash respons jika diterima, dan data yang lolos pemeriksaan. Jalannya dengan Python 3.11 menghasilkan exit 1. Koneksi ke `exchangeInfo` dan kedua permintaan `markPriceKlines` ditolak dengan WinError 10061 sebelum ada respons HTTP. Laporan percobaan ada di `data/audit/public-api.json`. Validasi lokal lolos untuk deteksi kedua gap, candle contoh, penolakan timestamp yang salah dan filter contoh. Jalankan kembali audit REST ketika koneksi resmi tersedia. Jika REST berhasil, gabungkan bukti candle ke manifest cakupan sebelum menilai ulang gate.

## Checkpoint bukti REST versi 2 — 21 November 2026

Kolektor kini mempertahankan isi respons untuk revalidasi checksum candle dan funding serta mengikatnya ke hash manifest arsip. Dataset memeriksa kecocokan settlement REST terhadap menit dan rate arsip. Pengujian lokal lulus untuk jalur pemulihan dan penolakan checksum, manifest dan funding yang berbeda.

Uji ulang dengan `--verify-funding` gagal untuk empat permintaan publik, yaitu filter, dua candle, dan halaman awal funding, dengan WinError 10061 sebelum HTTP. Hash laporan lokal `73d1856620d81d0ed691238dd4f79526f681fcbb8906536bd2c658eeb89bd0c3`. CLI audit dengan laporan ini masih menemukan dua candle kosong. Loader ketat menolak hari yang gap maupun hari kontigu tanpa funding yang diverifikasi. Audit Fase 01 tetap parsial. Fase 02 dilanjutkan paralel memakai fixture sebagaimana tercatat di register keputusan.

## Uji ulang koneksi — 21 November 2026, 15.51 WIB

Resolusi DNS IPv4 berhasil untuk host Futures dan Demo. Permintaan publik `/fapi/v1/time` ke kedua host gagal terhubung ke port 443 dengan curl exit 7 dan kode 000, sebelum menerima respons HTTP. Permintaan checksum arsip publik BTCUSDT 1m Januari 2023 mendapat HTTP 200 dari `data.binance.vision`. Pengambilan ulang filter dan data REST tetap tertahan.

## Diagnostik jam Windows — 21 November 2026, 15.53 WIB

Uji ulang pukul 15.56 WIB di luar sandbox berhasil menjalankan perintah resync, tetapi layanan Windows melaporkan sumber waktu tidak menyediakan data. Endpoint waktu publik Binance juga tetap gagal terhubung ke port 443 di luar sandbox.

Windows Time berjalan tetapi status `not synchronized`, sumber `Local CMOS Clock`. Dua sampel terhadap `time.windows.com` melaporkan offset sekitar +25.199 detik. Sumber waktu sesi menunjukkan waktu yang sejalan dengan tampilan Windows setelah konversi ke UTC. NTP pembanding Cloudflare timed out. Offset terhadap Binance belum terukur. `w32tm /resync` ditolak dengan 0x80070005. Curl verbose mencatat koneksi TCP ke Futures ditolak sebelum TLS atau respons HTTP, sehingga tidak ada indikasi penolakan timestamp dari Binance pada percobaan ini.

## Sinkronisasi pulih dan preflight demo — 21 November 2026, 22.58 WIB

`w32tm /resync /rediscover` sukses memakai sumber Windows yang sudah dikonfigurasi. Status menunjukkan stratum 5, leap indicator 0, dan last sync error 0. Dua pengukuran ke `time.windows.com` menunjukkan offset sekitar -13 ms dan -57 ms. Zona waktu Windows tetap SE Asia Standard Time.

Resolver lokal mengembalikan IP yang sama untuk Futures dan Demo, sesuai pola penyaringan Biznet yang pernah didokumentasikan [Citizen Lab](https://github.com/citizenlab/filtering-annotations/blob/master/analysislib/known_dns_sigs.py). Ini indikasi penyaringan, bukan konfirmasi aturan untuk kedua hostname saat ini. Kedua koneksi resmi tetap ditolak sebelum HTTPS, dan akses arsip masih berfungsi. Preflight menyimpan bukti aktual di `data/audit/demo-preflight-20261121.json`, SHA-256 `9a97542eaca711b527aab1c5dc945af497738c5171631dfa8b8f47d90179d14b`.

## Akses publik pulih — 21 November 2026, 23.16 WIB

Preflight Futures dan Demo lulus pada jalur jaringan saat ini. Feed Futures mengembalikan candle selesai, quote dan mark segar. Offset waktu Demo sekitar 172 ms dengan ketidakpastian 245 ms. Snapshot BTCUSDT menunjukkan `MIN_NOTIONAL` 50 USDT, tick 0,10, dan minimum market quantity serta step 0,001. Snapshot ini hanya berlaku pada pengambilan tersebut. Dua candle 12 Agustus 2024 dipulihkan melalui REST.

Laporan terbaru `data/audit/public-api.json` memiliki hash `41e86399b83bc71f09ac8b6b2152b3e72816aaf6d2c2a33aff73e809349de3ab`. Pemindaian seluruh rentang dari 2 Desember 2022 hingga 1 November 2026 eksklusif memvalidasi 2.059.200 menit kontigu dan mencocokkan 4.290 rate funding dengan arsip. Ada 1.000 nilai harga settlement REST kosong. Dataset mencatat null dan menjaga timestamp terverifikasi. Simulator memakai mark open menit terkait untuk catatan tersebut.

Belum tersedia variabel kredensial Demo di environment proses, sehingga metadata akun serta uji bertanda tangan tertunda. Metadata historis dan paket bracket untuk backtest juga belum tersedia.

Snapshot publik Demo tersimpan di `data/audit/demo-exchange-info-20261121.json`. Minimum notional Demo 50 USDT dan tick 0,10. Minimum kuantitas dan step market Demo 0,0001, sedangkan snapshot Futures produksi menunjukkan 0,001. Gunakan filter sesuai lingkungan.

Kurasi Parquet selesai di `data/curated/btcusdt-1m-v01.parquet`, SHA-256 `8642600725cf1e95f07f03ca7b5b011ad05c23c343e561e941b5dd13fe6851fb`. Footer memuat 2.059.200 baris, hash bukti REST dan label model harga funding yang kosong. Pemeriksaan lokal meluluskan 113 tes dan dua subtes.
