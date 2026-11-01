"""Optional, ephemeral acoustic measurements. Never used by interview scoring.

Only NumPy/PyAV and faster-whisper's bundled Silero VAD are required.
All timestamps refer to the original decoded waveform (no silence removal).
"""
import hashlib
import importlib.metadata
import re
import threading
import time

import numpy as np

SAMPLE_RATE = 16000
MAX_SECONDS = 125
BUDGET_SECONDS = 4.0
_SLOT = threading.BoundedSemaphore(1)
VAD_PARAMETERS = dict(threshold=0.5, min_speech_duration_ms=100,
                      min_silence_duration_ms=250, speech_pad_ms=0)
PITCH_PARAMETERS = dict(frame_ms=60, hop_ms=20, fmin_hz=60, fmax_hz=500,
                        trough_threshold=0.15, min_frame_dbfs=-50,
                        min_coverage=0.2, min_valid_frames=10)


class AnalysisLimit(Exception):
    pass


def _check(deadline):
    if time.monotonic() > deadline:
        raise AnalysisLimit('budget_exceeded')


def unavailable(reason='analysis_failed'):
    return {'schema_version': 'audio-analysis.v1', 'status': 'unavailable',
            'metrics': None, 'warnings': [reason],
            'emotion': {'enabled': False, 'status': 'not_evaluated'}}


def _decode(path, deadline):
    import av
    parts, count = [], 0
    with av.open(path) as container:
        stream = container.streams.audio[0]
        source = {'original_sample_rate_hz': stream.codec_context.sample_rate,
                  'original_channels': stream.codec_context.channels,
                  'sample_rate_hz': SAMPLE_RATE}
        # Preserve channels through resampling, then take their arithmetic mean.
        # FFmpeg's default stereo->mono rematrix adds ~3dB for identical channels.
        resampler = av.AudioResampler(format='fltp', layout=stream.codec_context.layout.name, rate=SAMPLE_RATE)

        def append(frames):
            nonlocal count
            for frame in frames:
                _check(deadline)
                data = frame.to_ndarray().mean(axis=0, dtype=np.float32)
                count += len(data)
                if count > MAX_SECONDS * SAMPLE_RATE:
                    raise AnalysisLimit('audio_too_long')
                parts.append(data)

        for frame in container.decode(stream):
            _check(deadline)
            append(resampler.resample(frame))
        append(resampler.resample(None))
    pcm = np.concatenate(parts) if parts else np.empty(0, dtype=np.float32)
    if not len(pcm) or not np.isfinite(pcm).all():
        raise AnalysisLimit('invalid_audio')
    return pcm, source


def _vad(pcm):
    # Adapter for the installed faster-whisper 1.2.1 API; do not change ASR VAD.
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    return get_speech_timestamps(pcm, VadOptions(**VAD_PARAMETERS), sampling_rate=SAMPLE_RATE)


def _intervals(raw, length):
    merged = []
    for item in sorted(raw, key=lambda item: item['start']):
        start, end = max(0, int(item['start'])), min(length, int(item['end']))
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def _frames(pcm, intervals, size, hop):
    # Frames must lie wholly in one VAD interval: do not bridge silent gaps.
    for start, end in intervals:
        if end - start >= size:
            yield np.lib.stride_tricks.sliding_window_view(pcm[start:end], size)[::hop]


def _pitch(frames, deadline):
    """YIN difference/CMNDF, fixed comparison window, first qualifying trough.

    Low-periodicity frames are rejected rather than assigned a pitch.
    FFT computes the exact cross-correlation for the fixed reference window.
    """
    pitches = []
    low = int(SAMPLE_RATE / PITCH_PARAMETERS['fmax_hz'])
    high = int(np.ceil(SAMPLE_RATE / PITCH_PARAMETERS['fmin_hz']))
    for offset in range(0, len(frames), 64):
        _check(deadline)
        x = frames[offset:offset + 64].astype(np.float64)
        rms = np.sqrt(np.mean(x * x, axis=1))
        x -= x.mean(axis=1, keepdims=True)
        width = x.shape[1] - high
        fft_size = 1 << (2 * x.shape[1] - 1).bit_length()
        correlation = np.fft.irfft(np.fft.rfft(x, n=fft_size) *
                                  np.conj(np.fft.rfft(x[:, :width], n=fft_size)), n=fft_size)[:, :high + 1]
        prefix = np.pad(np.cumsum(x * x, axis=1), ((0, 0), (1, 0)))
        lags = np.arange(high + 1)
        difference = np.maximum(prefix[:, width, None] + prefix[:, width + lags] -
                                prefix[:, lags] - 2 * correlation, 0)
        cumulative = np.cumsum(difference[:, 1:], axis=1)
        cmnd = np.ones_like(difference)
        np.divide(difference[:, 1:] * np.arange(1, high + 1), cumulative,
                  out=cmnd[:, 1:], where=cumulative > 1e-15)
        for row, amplitude in zip(cmnd, rms):
            if amplitude < 10 ** (PITCH_PARAMETERS['min_frame_dbfs'] / 20):
                continue
            candidates = np.flatnonzero(row[low:high] < PITCH_PARAMETERS['trough_threshold'])
            if not len(candidates):
                continue
            lag = low + int(candidates[0])
            while lag < high and row[lag + 1] < row[lag]:
                lag += 1
            refined = float(lag)
            if 0 < lag < high:
                a, b, c = row[lag - 1:lag + 2]
                divisor = a - 2 * b + c
                if abs(divisor) > 1e-12:
                    refined += float(np.clip(0.5 * (a - c) / divisor, -0.5, 0.5))
            hz = SAMPLE_RATE / refined
            if PITCH_PARAMETERS['fmin_hz'] <= hz <= PITCH_PARAMETERS['fmax_hz']:
                pitches.append(hz)
    return pitches


def _measure(pcm, raw_intervals, text, deadline):
    intervals = _intervals(raw_intervals, len(pcm))
    duration = len(pcm) / SAMPLE_RATE
    speech_s = sum(end - start for start, end in intervals) / SAMPLE_RATE
    hanzi = len(re.findall(r'[\u3400-\u9fff\U00020000-\U0002fa1f]', text))
    english = len(re.findall(r"[A-Za-z]+(?:['-][A-Za-z]+)*", text))
    metrics = dict(duration_s=round(duration, 3), speech_s=round(speech_s, 3),
                   speech_ratio=round(speech_s / duration, 4),
                   leading_silence_s=None, trailing_silence_s=None,
                   silence_s=round(duration - speech_s, 3),
                   pause_count=None, pause_total_s=None, pause_p50_s=None,
                   pause_mean_s=None, pause_max_s=None, long_pause_count=None,
                   hanzi_count=hanzi, english_word_count=english,
                   hanzi_per_min_total=None, hanzi_per_min_speech=None,
                   english_words_per_min_speech=None,
                   rms_linear_mean=None, rms_dbfs_mean=None, rms_dbfs_median=None, rms_dbfs_iqr=None,
                   rms_dbfs_p10=None, rms_dbfs_p90=None, rms_dbfs_range=None,
                   f0_hz_median=None, f0_hz_p10=None, f0_hz_p90=None,
                   f0_hz_min=None, f0_hz_max=None, f0_hz_range=None, f0_semitone_iqr=None)
    flags = []
    clipping = float(np.mean(np.abs(pcm) >= 0.999))
    quality = dict(flags=flags, clipping_ratio=round(clipping, 6), voiced_frame_coverage=None)
    if clipping > 0.01:
        flags.append('clipping')
    if duration < 0.5:
        flags.append('too_short')
    if not intervals:
        flags.append('no_speech')
        return metrics, quality
    pauses = [(right[0] - left[1]) / SAMPLE_RATE for left, right in zip(intervals, intervals[1:])
              if right[0] - left[1] >= int(0.5 * SAMPLE_RATE)]
    metrics.update(leading_silence_s=round(intervals[0][0] / SAMPLE_RATE, 3),
                   trailing_silence_s=round((len(pcm) - intervals[-1][1]) / SAMPLE_RATE, 3),
                   pause_count=len(pauses), pause_total_s=round(sum(pauses), 3),
                   pause_mean_s=round(float(np.mean(pauses)), 3) if pauses else None,
                   pause_max_s=round(max(pauses), 3) if pauses else None,
                   long_pause_count=sum(p >= 1.5 for p in pauses),
                   pause_p50_s=round(float(np.median(pauses)), 3) if pauses else None)
    if speech_s >= 0.5:
        if english:
            metrics['english_words_per_min_speech'] = round(english * 60 / speech_s, 1)
        if hanzi:
            metrics.update(hanzi_per_min_total=round(hanzi * 60 / duration, 1),
                           hanzi_per_min_speech=round(hanzi * 60 / speech_s, 1))
        else:
            flags.append('no_hanzi')
    else:
        flags.append('insufficient_speech')
    rms = []
    for frames in _frames(pcm, intervals, 400, 160):
        _check(deadline)
        # Compute in bounded batches rather than materializing all overlapping frames.
        for offset in range(0, len(frames), 256):
            _check(deadline)
            rms.extend(np.sqrt(np.mean(frames[offset:offset + 256].astype(np.float64) ** 2, axis=1)))
    if rms:
        db = 20 * np.log10(np.maximum(rms, 1e-12))
        metrics.update(rms_linear_mean=round(float(np.mean(rms)), 6),
                       rms_dbfs_mean=round(float(20 * np.log10(max(np.mean(rms), 1e-12))), 2),
                       rms_dbfs_median=round(float(np.median(db)), 2),
                       rms_dbfs_p10=round(float(np.percentile(db, 10)), 2),
                       rms_dbfs_p90=round(float(np.percentile(db, 90)), 2),
                       rms_dbfs_range=round(float(np.max(db) - np.min(db)), 2),
                       rms_dbfs_iqr=round(float(np.percentile(db, 75) - np.percentile(db, 25)), 2))
        if np.median(db) < -45:
            flags.append('low_level')
    pitches, frame_count = [], 0
    if clipping <= 0.01:
        for frames in _frames(pcm, intervals, 960, 320):
            frame_count += len(frames)
            pitches.extend(_pitch(frames, deadline))
    coverage = len(pitches) / frame_count if frame_count else 0.0
    quality['voiced_frame_coverage'] = round(coverage, 4)
    if len(pitches) >= PITCH_PARAMETERS['min_valid_frames'] and coverage >= PITCH_PARAMETERS['min_coverage']:
        median = float(np.median(pitches))
        semitones = 12 * np.log2(np.asarray(pitches) / median)
        metrics.update(f0_hz_median=round(median, 1),
                       f0_hz_min=round(float(min(pitches)), 1), f0_hz_max=round(float(max(pitches)), 1),
                       f0_hz_range=round(float(max(pitches) - min(pitches)), 1),
                       f0_hz_p10=round(float(np.percentile(pitches, 10)), 1),
                       f0_hz_p90=round(float(np.percentile(pitches, 90)), 1),
                       f0_semitone_iqr=round(float(np.percentile(semitones, 75) - np.percentile(semitones, 25)), 2))
    else:
        flags.append('pitch_unreliable')
    return metrics, quality


def analyze_audio(audio_path, asr_text=''):
    """Best-effort measurements; single local slot; no uploads, DB, or cloud calls.

    Budget is cooperative: checks surround bounded decode/FFT batches and VAD.
    Native VAD inference is not preempted mid-call.
    """
    if not _SLOT.acquire(blocking=False):
        return unavailable('analysis_busy')
    started = time.monotonic()
    deadline = started + BUDGET_SECONDS
    try:
        digest = hashlib.sha256()
        with open(audio_path, 'rb') as source_file:
            for chunk in iter(lambda: source_file.read(1024 * 1024), b''):
                _check(deadline)
                digest.update(chunk)
        pcm, source = _decode(audio_path, deadline)
        _check(deadline)
        intervals = _vad(pcm)
        _check(deadline)
        metrics, quality = _measure(pcm, intervals, asr_text, deadline)
        _check(deadline)
        source['audio_sha256'] = digest.hexdigest()
        source['asr_text_sha256'] = hashlib.sha256(asr_text.encode('utf-8')).hexdigest()
        return dict(schema_version='audio-analysis.v1',
                    status='partial' if quality['flags'] else 'ok', source=source,
                    method=dict(feature_version='1.1.0', vad='Silero bundled with faster-whisper',
                                faster_whisper_version=importlib.metadata.version('faster-whisper'),
                                vad_parameters=VAD_PARAMETERS, pause_min_ms=500, long_pause_min_ms=1500,
                                downmix='arithmetic_channel_mean',
                                rms_frame_ms=25, rms_hop_ms=10,
                                pitch='YIN-CMNDF (fixed window, FFT)', pitch_parameters=PITCH_PARAMETERS,
                                rate_text='original_asr_hanzi_excluding_punctuation'),
                    quality=quality, metrics=metrics,
                    processing_ms=round((time.monotonic() - started) * 1000, 1),
                    emotion={'enabled': False, 'status': 'not_evaluated'},
                    warnings=['practice_only_not_scored', 'dbfs_is_not_sound_pressure_level'])
    except AnalysisLimit as exc:
        return unavailable(str(exc))
    except Exception:
        return unavailable()  # Never expose decoder/configuration exception details.
    finally:
        _SLOT.release()
