"""Audio I/O and small DSP helpers (numpy + scipy + libsndfile only; no librosa, so it packages cleanly)."""
from __future__ import annotations
import math
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly, stft

AUDIO_EXT = (".wav", ".aif", ".aiff", ".flac", ".mp3", ".ogg")


def load(path: str, sr: int | None = None, mono: bool = False) -> tuple[np.ndarray, int]:
    """Load an audio file as float32 (channels, samples). Resamples when sr is given."""
    data, file_sr = sf.read(path, dtype="float32", always_2d=True)
    y = data.T  # (channels, samples)
    if mono and y.shape[0] > 1:
        y = y.mean(axis=0, keepdims=True)
    if sr and sr != file_sr:
        g = math.gcd(sr, file_sr)
        y = resample_poly(y, sr // g, file_sr // g, axis=1).astype(np.float32)
        file_sr = sr
    return np.ascontiguousarray(y, dtype=np.float32), file_sr


def duration(path: str) -> float:
    info = sf.info(path)
    return info.frames / float(info.samplerate)


def write(path: str, y: np.ndarray, sr: int) -> None:
    sf.write(path, np.asarray(y).T, sr, subtype="PCM_24")


def pitch_shift_resample(y: np.ndarray, semitones: float) -> np.ndarray:
    """Classic sampler-style pitch shift: resample, so duration changes with pitch. Fine for one-shots."""
    if abs(semitones) < 1e-6:
        return y
    ratio = 2 ** (semitones / 12.0)
    n = int(round(y.shape[1] / ratio))
    idx = np.linspace(0, y.shape[1] - 1, n)
    out = np.stack([np.interp(idx, np.arange(y.shape[1]), y[c]) for c in range(y.shape[0])])
    return out.astype(np.float32)


def power_spectrogram(mono: np.ndarray, sr: int, n_fft: int = 2048, hop: int = 512):
    f, t, Z = stft(mono, fs=sr, nperseg=n_fft, noverlap=n_fft - hop, padded=False, boundary=None)
    return f, t, (np.abs(Z) ** 2).astype(np.float32)


def onset_envelope(S: np.ndarray) -> np.ndarray:
    """Spectral flux on a log-power spectrogram: positive differences summed over bins."""
    L = np.log1p(S * 1e3)
    d = np.diff(L, axis=1, prepend=L[:, :1])
    env = np.maximum(d, 0).sum(axis=0)
    env = env - np.median(env)
    return np.maximum(env, 0).astype(np.float32)


def db(x: float) -> float:
    return float(10 * np.log10(max(x, 1e-12)))
