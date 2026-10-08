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


def time_stretch(y: np.ndarray, factor: float, n_fft: int = 2048, hop: int = 512) -> np.ndarray:
    """Phase-vocoder time stretch without changing pitch. factor = output length / input length. (ch, n) in and out."""
    if abs(factor - 1.0) < 1e-3:
        return y.astype(np.float32)
    from scipy.signal import stft, istft
    outs = []
    for ch in y:
        _f, _t, Z = stft(ch, nperseg=n_fft, noverlap=n_fft - hop, padded=True)
        n_frames = Z.shape[1]
        steps = np.arange(0.0, max(1.0, n_frames - 1), 1.0 / factor)
        omega = 2 * np.pi * hop * np.arange(Z.shape[0]) / n_fft
        phase = np.angle(Z[:, 0]).astype(np.float64)
        out = np.zeros((Z.shape[0], len(steps)), dtype=np.complex128)
        for i, st in enumerate(steps):
            j = int(st)
            frac = st - j
            z0 = Z[:, j]
            z1 = Z[:, min(j + 1, n_frames - 1)]
            mag = (1 - frac) * np.abs(z0) + frac * np.abs(z1)
            out[:, i] = mag * np.exp(1j * phase)
            dphi = np.angle(z1) - np.angle(z0) - omega
            dphi -= 2 * np.pi * np.round(dphi / (2 * np.pi))
            phase += omega + dphi
        _t2, x = istft(out, nperseg=n_fft, noverlap=n_fft - hop)
        outs.append(x)
    n = min(len(o) for o in outs)
    return np.vstack([o[:n] for o in outs]).astype(np.float32)
