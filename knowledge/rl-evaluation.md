# RL, probabilitas, dan evaluasi

Diperiksa: 10 November 2026. Berisi dasar metode dan rekomendasi proyek; belum ada hasil eksperimen Tradebot.

## Policy bukan probabilitas profit

RL belajar kebijakan tindakan untuk reward jangka panjang. Probabilitas memilih long tidak menyatakan peluang TP sebelum SL. Jika alokasi risiko ingin berbasis peluang menang, estimasi tersebut harus memiliki target eksplisit, horizon, data uji, dan kalibrasi terpisah.

Kalibrasi berarti kelompok prediksi mendekati 70% benar-benar memiliki frekuensi kejadian sekitar 70% pada data baru, dengan ketidakpastian yang tetap dilaporkan. Jumlah sampel dan perubahan kondisi penting; win rate tinggi tidak menjamin expected value positif setelah biaya.

Sumber: https://scikit-learn.org/stable/modules/calibration.html

## Eksperimen RL

Model-free RL dapat memerlukan banyak interaksi, reward yang dirancang cermat, dan hasil yang bervariasi antar seed. Gunakan lingkungan evaluasi terpisah serta beberapa percobaan, bukan training run terbaik saja.

Sumber: https://stable-baselines3.readthedocs.io/en/master/guide/rl_tips.html

Rekomendasi proyek: PPO kandidat awal, tindakan sederhana, TP/SL dan sizing di luar model. Reward berdasarkan equity net untuk mencegah kerugian belum terealisasi tersembunyi. Kebijakan risiko keras berlaku di training dan inference. Mengulang sejarah tidak menghasilkan kondisi pasar baru.

## Pencegahan kebocoran dan evaluasi

Split kronologis, scaler fit hanya di training, candle yang telah tersedia, dan eksekusi setelah sinyal. Posisi/label tumpang tindih membutuhkan pemisahan tambahan; TimeSeriesSplit saja tidak menyelesaikan seluruh kebocoran trading. Gunakan data rinci atau asumsi konservatif jika TP dan SL tersentuh pada candle sama.

Sumber split berurutan: https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html

Evaluasi hasil bersih, drawdown, turnover, eksposur, pelanggaran risiko, serta sensitivitas biaya. Pisahkan pemilihan model dari final test dan paper trading. Jangan mengubah ambang kelulusan setelah melihat test akhir untuk meloloskan model.
