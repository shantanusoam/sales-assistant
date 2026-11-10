"""Synthesize and master the timeline-synced soundtrack (ElevenLabs VO + ambient synth bed + peak-aligned tactile SFX)
and generate output/captions.srt."""
from __future__ import annotations

import json
import math
import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 48000
ROOT = Path(__file__).resolve().parent
TIMELINE_PATH = ROOT / "timeline.json"
AUDIO_DIR = ROOT / "audio"
OUT_DIR = ROOT / "output"


def load_wav_mono(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        n = wf.getnframes()
        raw = wf.readframes(n)
        arr = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    # Normalize each VO clip to consistent RMS (-16 dBFS) with soft limiting
    rms = math.sqrt(float(np.mean(arr ** 2)) + 1e-12)
    target_rms = 10 ** (-16.0 / 20.0)
    arr = arr * (target_rms / rms)
    arr = np.tanh(arr * 1.15) * 0.72
    return arr


def make_sfx(kind: str) -> tuple[np.ndarray, int]:
    """Return (samples, peak_index) for each named foley/UI cue."""
    if kind in ("click_ui", "click_ui_2", "click_lock"):
        dur = 0.08
        t = np.linspace(0, dur, int(SR * dur), endpoint=False)
        freq = 1350.0 if kind != "click_lock" else 980.0
        env = np.exp(-t * 65.0) * np.sin(np.pi * np.minimum(1.0, t / 0.004))
        sig = (0.7 * np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(2 * np.pi * freq * 1.9 * t)) * env
    elif kind in ("whoosh_soft", "whoosh_pan"):
        dur = 0.38
        t = np.linspace(0, dur, int(SR * dur), endpoint=False)
        env = np.sin(np.pi * (t / dur)) ** 2.2
        f0, f1 = (180.0, 520.0) if kind == "whoosh_soft" else (240.0, 620.0)
        phase = 2 * np.pi * (f0 * t + 0.5 * (f1 - f0) * (t ** 2) / dur)
        sig = np.sin(phase) * env * 0.6
    elif kind in ("chime_rag", "pop_hint", "chime_resolve", "snap_flip"):
        dur = 0.32
        t = np.linspace(0, dur, int(SR * dur), endpoint=False)
        env = np.exp(-t * 14.0) * np.minimum(1.0, t / 0.006)
        base = 523.25 if kind == "chime_rag" else 659.25 if kind == "pop_hint" else 587.33
        sig = (0.65 * np.sin(2 * np.pi * base * t) + 0.35 * np.sin(2 * np.pi * base * 1.5 * t)) * env
    elif kind == "impact_payoff":
        # Loudest non-voice payoff hit at 33.70s right after the 33.0-33.6s silence
        dur = 0.42
        t = np.linspace(0, dur, int(SR * dur), endpoint=False)
        fade_in = np.minimum(1.0, t / 0.025)
        env = fade_in * np.exp(-t * 5.2)
        # Warm C-major9 chord + punchy mid-bass so 100ms RMS clearly peaks here
        sig = (
            0.38 * np.sin(2 * np.pi * 130.81 * t)
            + 0.34 * np.sin(2 * np.pi * 261.63 * t)
            + 0.28 * np.sin(2 * np.pi * 329.63 * t)
            + 0.24 * np.sin(2 * np.pi * 392.00 * t)
            + 0.18 * np.sin(2 * np.pi * 587.33 * t)
        ) * env
    else:
        dur = 0.1
        sig = np.zeros(int(SR * dur), dtype=np.float64)

    peak = int(np.argmax(np.abs(sig))) if sig.size else 0
    max_v = float(np.max(np.abs(sig))) if sig.size else 1.0
    if max_v > 0:
        sig = sig / max_v
    return sig, peak


def fmt_srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tl = json.loads(TIMELINE_PATH.read_text())
    dur = float(tl["meta"]["dur"])
    total_samples = int(round(dur * SR))

    # 1. Ambient Linear/ReStructure electronic synth bed (ducked under voice)
    t = np.arange(total_samples, dtype=np.float64) / SR
    pad = (
        0.38 * np.sin(2 * np.pi * 130.81 * t)
        + 0.30 * np.sin(2 * np.pi * 196.00 * t)
        + 0.22 * np.sin(2 * np.pi * 246.94 * t)
        + 0.15 * np.sin(2 * np.pi * 293.66 * t)
    ) * (0.85 + 0.15 * np.sin(2 * np.pi * 0.25 * t))
    # Fade in first 0.2s and fade out last 0.8s
    pad *= np.minimum(1.0, t / 0.2) * np.minimum(1.0, (dur - t) / 0.8)
    mix = pad * 0.045

    # 2. Place ElevenLabs VO lines
    for line in tl.get("vo", []):
        lid = line["id"]
        wav_path = AUDIO_DIR / f"{lid}.wav"
        if not wav_path.exists():
            continue
        clip = load_wav_mono(wav_path)
        start_idx = int(round(float(line["from"]) * SR))
        end_idx = min(total_samples, start_idx + clip.size)
        if end_idx > start_idx:
            mix[start_idx:end_idx] += clip[: end_idx - start_idx] * 0.56

    # 3. Map beat names to times and place peak-aligned SFX
    beat_map: dict[str, float] = {}
    for s in tl.get("scenes", []):
        sid = s["id"]
        for bname, bt in (s.get("beats") or {}).items():
            beat_map[f"{sid}.{bname}"] = float(bt)

    for cue in tl.get("sfx", []):
        at = cue["at"]
        cue_t = beat_map.get(at, 0.0) + float(cue.get("offset", 0.0))
        sig, peak_idx = make_sfx(cue["src"])
        gain = float(cue.get("gain", 0.2))
        if cue["src"] == "impact_payoff":
            # Ensure the payoff chord at 33.70s is the loudest 100ms window in the film
            gain = 1.25
        start_idx = int(round(cue_t * SR)) - peak_idx
        s0 = max(0, start_idx)
        s1 = min(total_samples, start_idx + sig.size)
        if s1 > s0:
            mix[s0:s1] += sig[s0 - start_idx : s1 - start_idx] * gain

    # 4. Enforce absolute silence in planned silences (with 40ms guard on each side)
    for sil in tl.get("silences", []):
        a = max(0, int(round((float(sil["from"]) - 0.04) * SR)))
        b = min(total_samples, int(round((float(sil["to"]) + 0.02) * SR)))
        mix[a:b] = 0.0
        # 20ms cosine ramp into and out of silence to prevent click pops
        ramp = int(0.02 * SR)
        if a > ramp:
            mix[a - ramp : a] *= np.linspace(1.0, 0.0, ramp)
        if b + ramp < total_samples:
            mix[b : b + ramp] *= np.linspace(0.0, 1.0, ramp)

    # Fade first 25ms (`sound.md` §6)
    f25 = int(0.025 * SR)
    mix[:f25] *= np.linspace(0.0, 1.0, f25)

    # Write unmastered WAV
    raw_wav = AUDIO_DIR / "mix_raw.wav"
    clipped = np.clip(mix, -0.98, 0.98)
    pcm16 = (clipped * 32767.0).astype(np.int16)
    with wave.open(str(raw_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm16.tobytes())

    # 5. Master to -14.0 LUFS integrated, True Peak <= -1.5 dBTP via exact ebur128 gain calibration
    master_wav = AUDIO_DIR / "master.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", str(raw_wav),
            "-af", "loudnorm=I=-14.0:TP=-1.6:LRA=11",
            "-ar", str(SR), "-ac", "2", str(master_wav),
        ],
        check=True,
    )

    # Re-enforce exact zero in the planned silence window after loudnorm
    for sil in tl.get("silences", []):
        a, b = float(sil["from"]) - 0.02, float(sil["to"]) + 0.01
        tmp_wav = AUDIO_DIR / "master_sil.wav"
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error", "-i", str(master_wav),
                "-af", f"volume=enable='between(t,{a:.3f},{b:.3f})':volume=0",
                str(tmp_wav),
            ],
            check=True,
        )
        tmp_wav.replace(master_wav)

    # Measure final LUFS on master.wav and apply exact linear trim to hit -14.0 LUFS
    ebur = subprocess.run(
        ["ffmpeg", "-nostats", "-i", str(master_wav), "-af", "ebur128=peak=true", "-f", "null", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ).stderr
    summary = ebur[ebur.rfind("Summary:") :]
    import re
    m_i = re.search(r"I:\s+(-?[\d.]+)\s+LUFS", summary)
    if m_i:
        cur_lufs = float(m_i.group(1))
        diff_db = -14.0 - cur_lufs
        if abs(diff_db) > 0.15:
            trimmed = AUDIO_DIR / "master_trimmed.wav"
            subprocess.run(
                [
                    "ffmpeg", "-y", "-v", "error", "-i", str(master_wav),
                    "-af", f"volume={diff_db:+.2f}dB,alimiter=limit=-1.5dB:level=false",
                    str(trimmed),
                ],
                check=True,
            )
            trimmed.replace(master_wav)

    # Write SRT captions
    srt_lines = []
    for idx, cap in enumerate(tl.get("captions", []), 1):
        srt_lines.append(f"{idx}")
        srt_lines.append(f"{fmt_srt_time(float(cap['from']))} --> {fmt_srt_time(float(cap['to']))}")
        srt_lines.append(str(cap["text"]))
        srt_lines.append("")
    (OUT_DIR / "captions.srt").write_text("\n".join(srt_lines), encoding="utf-8")
    print("Master audio and captions.srt built successfully.")


if __name__ == "__main__":
    main()
