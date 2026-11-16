"""
pwave_common.py — Modul bersama untuk preprocessing dan deteksi P-Wave.

Digunakan oleh p_wave_detector/main.py (mode Native Kafka) dan
p_wave_detector_load_balance/main.py (mode HTTP/NGINX).

Memastikan ambang deteksi dan logika normalisasi identik di kedua mode,
sehingga perbandingan S3 dan S4B murni mengukur topologi, bukan logika deteksi.
"""

import os
import numpy as np


# ==============================================================================
# Parameter deteksi yang dapat dikonfigurasi lewat .env
# ==============================================================================

# Ambang probabilitas P-Wave; satu window dianggap positif bila prediksi >= nilai ini.
PWAVE_THRESHOLD: float = float(os.getenv("PWAVE_THRESHOLD", "0.9"))

# Jumlah window berturut-turut yang harus semua >= PWAVE_THRESHOLD agar deteksi dikonfirmasi.
PWAVE_CONSEC: int = int(os.getenv("PWAVE_CONSEC", "20"))


def normalize(x: np.ndarray) -> np.ndarray:
    """
    Normalisasi array waveform dengan membagi setiap kolom (sumbu-0) dengan
    nilai absolut maksimumnya.

    Parameter
    ---------
    x : np.ndarray
        Array bentuk (160, 3) yang merepresentasikan satu jendela waveform.

    Kembalian
    ---------
    np.ndarray
        Array yang dinormalisasi. Jika nilai maksimum absolut adalah 0, array
        dikembalikan tanpa perubahan agar tidak ada pembagian dengan nol.
    """
    max_abs = np.max(np.abs(x), axis=0)
    # Hindari pembagian dengan nol; ganti 0 dengan 1 (kolom tetap nol setelah dibagi)
    max_abs = np.where(max_abs == 0, 1.0, max_abs)
    return x / max_abs


def normalize_batch(batch: np.ndarray) -> np.ndarray:
    """
    Normalisasi batch jendela waveform secara vektorisasi.

    Parameter
    ---------
    batch : np.ndarray
        Array bentuk (N, 160, 3) — N jendela, masing-masing 160 sampel × 3 kanal.

    Kembalian
    ---------
    np.ndarray
        Batch yang dinormalisasi dengan bentuk yang sama.
    """
    # Hitung maks absolut per jendela per kanal: shape (N, 1, 3)
    max_abs = np.max(np.abs(batch), axis=1, keepdims=True)
    max_abs = np.where(max_abs == 0, 1.0, max_abs)
    return batch / max_abs


def detect(predictions: np.ndarray,
           threshold: float = PWAVE_THRESHOLD,
           n_consec: int = PWAVE_CONSEC) -> tuple[int, float]:
    """
    Cari deteksi P-Wave pertama yang dikonfirmasi dari array prediksi model.

    Algoritmanya: geser jendela lebar `n_consec` di sepanjang `predictions`.
    Jendela dianggap valid bila **semua** nilai di dalamnya >= `threshold`.
    Di antara semua jendela valid, pilih yang memiliki nilai maksimum tertinggi.

    Parameter
    ---------
    predictions : np.ndarray
        Array 1-D probabilitas P-Wave per jendela, keluaran langsung dari model.
    threshold : float, opsional
        Ambang probabilitas per prediksi. Bawaan dari env PWAVE_THRESHOLD (0.9).
    n_consec : int, opsional
        Jumlah prediksi berturut-turut yang harus >= threshold. Bawaan dari env
        PWAVE_CONSEC (20).

    Kembalian
    ---------
    (idx, max_value) : tuple[int, float]
        idx       — indeks awal jendela deteksi terbaik.
        max_value — nilai probabilitas tertinggi dalam jendela tersebut;
                    bernilai 0.0 jika tidak ada deteksi.
    """
    best_idx = 0
    best_max = 0.0

    n = len(predictions)
    if n < n_consec:
        return best_idx, best_max

    for i in range(n - n_consec + 1):
        window = predictions[i: i + n_consec]
        if np.all(window >= threshold):
            window_max = float(np.max(window))
            if window_max > best_max:
                best_max = window_max
                best_idx = i

    return best_idx, best_max
