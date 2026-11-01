"""Offline SER evaluation only. Deliberately not enabled in interview reports.

Model: emotion2vec/emotion2vec_plus_base, converted by pankotaro.
License: FunASR Model Open Source License, bundled beside the pinned weights.
No network calls, downloads, or remote code execution are performed here.
"""
import hashlib
import json
import threading
import time
from pathlib import Path

import numpy as np

MODEL_DIR = Path(__file__).parent / 'models/emotion2vec-plus-base-onnx'
REVISION = '334d4376993c381f059cc36d2c6ed05cbfec5ca1'
_LOCK = threading.Lock()
_STATE = None


def get_model():
    global _STATE
    with _LOCK:
        if _STATE is not None:
            return _STATE
        manifest = json.loads((MODEL_DIR / 'manifest.json').read_text(encoding='utf-8'))
        if manifest['revision'] != REVISION:
            raise ValueError('unexpected_revision')
        for name in ['emotion2vec_plus_base.onnx', 'emotion2vec_head.json']:
            digest = hashlib.sha256()
            with (MODEL_DIR / name).open('rb') as f:
                for block in iter(lambda:f.read(1024 * 1024), b''): digest.update(block)
            if digest.hexdigest() != manifest['files'][name]['sha256']:
                raise ValueError('model_checksum_mismatch')
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        session = ort.InferenceSession(str(MODEL_DIR / 'emotion2vec_plus_base.onnx'),
                                       sess_options=options, providers=['CPUExecutionProvider'])
        head = json.loads((MODEL_DIR / 'emotion2vec_head.json').read_text(encoding='utf-8'))
        weights, bias = np.asarray(head['weight'], np.float32), np.asarray(head['bias'], np.float32)
        labels = head['labels']
        if weights.shape != (len(labels), 768) or bias.shape != (len(labels),):
            raise ValueError('invalid_classifier_head')
        _STATE = session, weights, bias, labels
        return _STATE


def predict(pcm):
    """At most the first 8s; scores are uncalibrated model softmax, not true emotions."""
    session, weights, bias, labels = get_model()
    if len(pcm) < 16000:
        return {'status':'unavailable', 'reason':'too_short'}
    audio = np.asarray(pcm[:8 * 16000], dtype=np.float32).reshape(1, -1)
    if not np.isfinite(audio).all() or np.max(np.abs(audio)) > 1:
        return {'status':'unavailable', 'reason':'invalid_waveform'}
    started = time.monotonic()
    features = session.run(None, {session.get_inputs()[0].name:audio})[0]
    logits = weights @ features[0].mean(axis=0) + bias
    probabilities = np.exp(logits - logits.max())
    probabilities /= probabilities.sum()
    if not np.isfinite(probabilities).all():
        return {'status':'unavailable', 'reason':'invalid_output'}
    return dict(status='experimental', model='emotion2vec/emotion2vec_plus_base',
                conversion='pankotaro/emotion2vec-plus-base-onnx', revision=REVISION,
                label=labels[int(probabilities.argmax())],
                probabilities={label:float(p) for label,p in zip(labels, probabilities)},
                confidence=float(probabilities.max()), confidence_kind='uncalibrated_softmax',
                analyzed_seconds=len(audio[0])/16000, inference_ms=round((time.monotonic()-started)*1000,1),
                warning='实验性模型预测，不代表真实心理状态；未验证中文面试准确率，不用于评分。')
