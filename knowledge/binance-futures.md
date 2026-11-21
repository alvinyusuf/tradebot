# Binance Futures: aturan dan verifikasi

Diperiksa: 10 November 2026.

## Minimum order

Pengumuman resmi bertanggal 14 April 2026 menyatakan minimum notional BTCUSDT perpetual USDⓈ-M turun dari 100 ke 50 USDT. Ini bukti perubahan saat pengumuman, bukan bukti filter live saat ini.

Sumber: https://www.binance.com/en-NG/support/announcement/detail/10999fd17dc045de801c0c78ab29e6fc

`GET /fapi/v1/exchangeInfo` harus menjadi input validasi filter: MIN_NOTIONAL, LOT_SIZE, MARKET_LOT_SIZE sesuai jenis order, dan PRICE_FILTER. Jangan memakai pricePrecision/quantityPrecision sebagai pengganti tickSize/stepSize. Periksa juga status instrumen dan jenis order yang didukung.

Sumber: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information

Akses sesi ini: web HTTP 451; curl dari shell gagal DNS. Filter live dan harga BTC aktual belum diverifikasi. Jangan menganggap contoh kuantitas atau harga dalam chat sebagai nilai produksi.

Dampak: modal USD 100, risiko USD 0,50, dan leverage 5x belum menjamin setiap sinyal dapat dieksekusi. Bulatkan sizing ke bawah, validasi minimum dan risiko lagi, lewati order yang gagal. Jangan menaikkan risiko atau mempersempit SL hanya untuk lolos filter.

## Biaya dan margin

Biaya trading berbasis nilai fill, bukan hanya margin. Funding dapat dibayar atau diterima sesuai posisi dan kondisi kontrak; gunakan histori/jadwal yang berlaku, bukan asumsi interval tetap. Tarif akun, diskon, dan peran maker/taker perlu diverifikasi; limit order tidak selalu berarti maker.

Sumber: https://www.binance.com/en/support/faq/detail/98488a516eb84e3eb34605683dffd554

Sumber kebutuhan margin: https://www.binance.com/en/support/faq/detail/4f83b65d83654b5e933f85ef12bf769d

Isolated margin bukan jaminan batas rugi harian. SL juga tidak menjamin harga fill. Pemicu proteksi dan likuidasi harus dimodelkan sesuai mark/contract price yang dipilih dan aturan Binance aktual.

## Verifikasi berikutnya

Saat implementasi: ambil filter dan metadata akun yang diperlukan lewat akses resmi yang tersedia, simpan timestamp audit, validasi endpoint proteksi TP/SL terkini dan perbedaan demo/live. Jangan mengasumsikan contoh dokumentasi merupakan filter BTCUSDT aktual.

## Arsip publik dan batas verifikasi — 21 November 2026

Arsip bulanan USDⓈ-M dari [Binance Public Data](https://github.com/binance/binance-public-data) dapat diakses dari workspace. Arsip BTCUSDT menyediakan candle kontrak, mark price, funding dan checksum per ZIP. Arsip funding menggunakan `calc_time`, `funding_interval_hours`, dan `last_funding_rate`. API [Funding Rate History](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History) menyediakan `fundingTime` dan mark price terkait settlement. Validasi kesetaraan timestamp sebelum menggunakannya untuk membukukan funding tepat pada boundary.

Dua percobaan koneksi ke host API Futures gagal dengan curl exit 7. Snapshot filter aktual masih diperlukan. [Dokumentasi akun USDⓈ-M](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account) menetapkan bracket dan komisi pengguna sebagai endpoint `USER_DATA` bertanda tangan.

[Informasi API Futures USDⓈ-M](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info) menempatkan REST demo di `demo-fapi.binance.com`. Uji waktu publik ke host demo juga gagal sebelum HTTP. Audit metadata demo menggunakan host itu dan menyimpan hasil berlabel lingkungan demo. Filter, komisi, bracket, dan koefisien penyesuaian akun hanya berlaku untuk lingkungan dan akun yang diaudit.

Pembaruan 23.16 WIB. Endpoint Futures dan Demo sudah merespons. Snapshot Futures BTCUSDT mengembalikan minimum notional 50 USDT, tick 0,10 serta minimum kuantitas dan step market 0,001. Fee dan bracket per akun masih perlu pengukuran terpisah. [Checkpoint audit](../memory/phases/01-data-runtime-audit.md)
