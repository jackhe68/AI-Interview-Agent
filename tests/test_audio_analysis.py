"""Numerical fixtures are independent of ASR and do not require cloud access."""
import io
import json
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import audio_analysis as a

def tone(hz, seconds=2, amplitude=0.1):
    return (amplitude * np.sin(2 * np.pi * hz * np.arange(int(seconds * a.SAMPLE_RATE)) / a.SAMPLE_RATE)).astype(np.float32)

def measure(pcm, text='你好世界', intervals=None):
    if intervals is None: intervals = [{'start':0,'end':len(pcm)}]
    return a._measure(pcm, intervals, text, time.monotonic() + 10)

class NumericTests(unittest.TestCase):
    def test_known_frequencies_and_level(self):
        for hz in [65, 100, 220, 440, 490]:
            m, q = measure(tone(hz))
            self.assertAlmostEqual(m['f0_hz_median'], hz, delta=1)
            self.assertAlmostEqual(m['rms_dbfs_median'], -23.01, delta=0.2)
            self.assertLess(m['f0_semitone_iqr'], 0.1)
            self.assertGreater(q['voiced_frame_coverage'], 0.95)

    def test_pause_and_rates_original_timeline(self):
        intervals = [{'start':16000,'end':32000}, {'start':40000,'end':56000}]
        m, _ = measure(tone(220, 4), '你好世界。Java Python 123', intervals)
        self.assertEqual(m['duration_s'], 4)
        self.assertEqual(m['speech_s'], 2)
        self.assertEqual(m['pause_count'], 1)
        self.assertEqual(m['pause_total_s'], 0.5)
        self.assertEqual(m['leading_silence_s'], 1)
        self.assertEqual(m['trailing_silence_s'], 0.5)
        self.assertEqual(m['hanzi_per_min_total'], 60)
        self.assertEqual(m['hanzi_per_min_speech'], 120)
        self.assertEqual(m['english_word_count'], 2)

    def test_silence_noise_short_and_clipping(self):
        m, q = measure(np.zeros(16000, dtype=np.float32), intervals=[])
        self.assertEqual(m['speech_s'], 0)
        self.assertIsNone(m['f0_hz_median'])
        self.assertIsNone(m['pause_count'])
        self.assertIsNone(m['hanzi_per_min_total'])
        self.assertIn('no_speech', q['flags'])
        m, q = measure(np.random.default_rng(17).normal(0, .03, 32000).astype(np.float32))
        self.assertIsNone(m['f0_hz_median'])
        self.assertIn('pitch_unreliable', q['flags'])
        m, q = measure(tone(220, .1))
        self.assertIn('too_short', q['flags'])
        self.assertIsNone(m['f0_hz_median'])
        m, q = measure(np.ones(32000, dtype=np.float32))
        self.assertIn('clipping', q['flags'])
        self.assertIsNone(m['f0_hz_median'])

    def test_hanzi_and_no_invented_rate(self):
        m, q = measure(tone(220), 'Java Python 123')
        self.assertEqual(m['hanzi_count'], 0)
        self.assertIsNone(m['hanzi_per_min_total'])
        self.assertIn('no_hanzi', q['flags'])

    def test_limits_and_failure(self):
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            f.write(b'invalid')
            path = Path(f.name)
        try:
            self.assertEqual(a.analyze_audio(path)['status'], 'unavailable')
            with patch.object(a, 'BUDGET_SECONDS', -1):
                self.assertEqual(a.analyze_audio(path)['warnings'], ['budget_exceeded'])
            a._SLOT.acquire()
            try:
                self.assertEqual(a.analyze_audio(path)['warnings'], ['analysis_busy'])
            finally: a._SLOT.release()
            with patch.object(a, '_decode', side_effect=a.AnalysisLimit('audio_too_long')):
                self.assertEqual(a.analyze_audio(path)['warnings'], ['audio_too_long'])
        finally: path.unlink()

    def test_stereo_resampling_and_bounds(self):
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f: path=Path(f.name)
        try:
            samples=(.1*np.sin(2*np.pi*220*np.arange(48000)/48000)*32767).astype('<i2')
            with wave.open(str(path),'wb') as f:
                f.setnchannels(2); f.setsampwidth(2); f.setframerate(48000)
                f.writeframes(np.column_stack([samples,samples]).tobytes())
            pcm, source=a._decode(path,time.monotonic()+10)
            self.assertEqual(len(pcm),16000)
            self.assertEqual(source['original_channels'],2)
            self.assertEqual(source['original_sample_rate_hz'],48000)
            self.assertAlmostEqual(float(np.sqrt(np.mean(pcm**2))), .1/np.sqrt(2), delta=.001)
            with patch.object(a,'MAX_SECONDS',.1):
                with self.assertRaises(a.AnalysisLimit): a._decode(path,time.monotonic()+10)
        finally: path.unlink()

class RealVadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from faster_whisper.vad import get_vad_model
        get_vad_model()  # Production ASR also initializes VAD before analysis.

    def test_real_vad_silence_and_chinese_fixture(self):
        self.assertEqual(a._vad(np.zeros(32000, dtype=np.float32)), [])
        path=Path(__file__).parent/'chinese-fixture.wav'
        result=a.analyze_audio(path,'你好，我是一名计算机专业的学生。')
        self.assertIn(result['status'],['ok','partial'], result)
        self.assertGreater(result['metrics']['speech_s'],2)
        self.assertIsNotNone(result['metrics']['f0_hz_median'])
        self.assertFalse(result['emotion']['enabled'])
        json.dumps(result,allow_nan=False)

    def test_inserted_silence_on_original_timeline(self):
        pcm,_=a._decode(Path(__file__).parent/'chinese-fixture.wav',time.monotonic()+10)
        speech=pcm[:64000]
        joined=np.concatenate([np.zeros(16000),speech,np.zeros(12000),speech,np.zeros(16000)]).astype(np.float32)
        intervals=a._vad(joined)
        m,_=a._measure(joined,intervals,'测试语速',time.monotonic()+10)
        self.assertGreater(m['leading_silence_s'],.8)
        self.assertGreater(m['trailing_silence_s'],.8)
        self.assertGreaterEqual(m['pause_total_s'],.7)
        self.assertGreaterEqual(m['pause_count'],1)

if __name__=='__main__': unittest.main(verbosity=2)
