# Panduan AI agent Tradebot

## Wajib saat pertama membuka sesi

1. Baca `README.md`, `memory/STATE.md`, dan catatan fase aktif yang ditunjuk di sana.
2. Baca `docs/decisions.md`, `docs/architecture.md`, `docs/experiment-spec.md`, `docs/acceptance.md`, dan `docs/operations.md`.
3. Baca `CHANGELOG.md` dan knowledge yang relevan. Periksa perubahan lokal sebelum mengedit; gunakan `git status --short` jika repository berfungsi. Jangan menimpa pekerjaan pengguna.
4. Sampaikan status singkat dan lanjutkan pekerjaan yang sudah diotorisasi. Catatan next step bukan izin deployment atau trading uang asli.

## Otoritas dan sumber kebenaran

- Instruksi pengguna terbaru mengalahkan dokumen lama. Bedakan keputusan pengguna dari default teknis yang ditetapkan agent untuk development.
- `docs/experiment-spec.md` adalah kontrak eksperimen v0.1; `docs/acceptance.md` adalah gate; `docs/operations.md` adalah kontrak operasi. Bila bertentangan, hentikan bagian yang bergantung pada konflik dan sinkronkan dokumen terlebih dahulu.
- `memory/STATE.md` menyimpan status aktual; catatan fase menyimpan checkpoint/bukti; changelog hanya hasil selesai; knowledge menyimpan pengetahuan bersumber.
- Default teknis boleh diperbaiki dengan alasan dan perubahan versi. Jangan mengubah batas risiko yang disepakati pengguna atau mengubah eksperimen setelah melihat holdout untuk meloloskan hasil.

## Aturan pengerjaan

- Scope awal simulator dan paper. Default mode bukan live; jangan meminta key live untuk riset. Order uang asli dan deployment membutuhkan otorisasi eksplisit.
- Policy tidak boleh mengirim order atau mengubah risk engine. Confidence tindakan RL bukan probabilitas profit.
- Tanpa lookahead: fitur hanya data tersedia, scaler hanya training, fill setelah keputusan. Label/episode tumpang tindih dipisahkan.
- Jangan menaikkan risiko, leverage, atau mempersempit SL demi minimum order. Skip dan catat alasannya.
- Gunakan `rg` untuk pencarian. Jangan membuat subagent kecuali diminta pengguna atau instruksi yang berlaku.
- Jangan menyimpan key, token, isi secret environment, atau informasi pribadi akun di log/dokumen.
- Jalankan pemeriksaan sesuai perubahan; laporkan bukti dan keterbatasan, jangan menyamakan dokumen selesai dengan implementasi selesai.
- Verifikasi aturan Binance yang berubah melalui sumber resmi saat implementasi. Jangan mengakali pembatasan akses. Jika data tidak tersedia, tandai blocked pada audit terkait, bukan mengarang hasil.

## Persistence pada setiap checkpoint dan akhir sesi

1. Perbarui STATE: fase aktif, hasil nyata, blocker, dan next step konkret.
2. Tambahkan checkpoint catatan fase: file, keputusan, validasi dan hasil aktual.
3. Sinkronkan register keputusan, knowledge, README dan changelog jika relevan.
4. Jika fase selesai, tulis bukti kriteria selesai dan arahkan ke fase berikutnya. Jangan menutup fase hanya karena sesi berakhir.

Gunakan bahasa Indonesia pada dokumen. Template fase sengaja memiliki field yang diisi saat fase dimulai, bukan pekerjaan yang diklaim selesai.

## Catatan filesystem

Pada workspace ini `AGENTS.md` dan `agents.md` menunjuk file yang sama (case-insensitive). Pertahankan satu panduan ini; jangan menulis file pengarah dengan nama berbeda kapitalisasi karena akan menimpa isi panduan.
