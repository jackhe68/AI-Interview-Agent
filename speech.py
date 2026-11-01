# -*- coding: utf-8 -*-
"""
AI Interview Agent · faster-whisper 语音识别封装（第四阶段 4.1）
- 模型单例懒加载，复用，不每次录音都重新加载
- CPU + int8 轻量运行，中文识别
- initial_prompt 注入技术术语，优化 Java/HashMap/JVM 等识别
- 模型加载/下载失败不崩溃，缓存错误原因供接口返回
- 使用 hf-mirror.com 镜像并绕过本地代理，避免 HuggingFace 下载 502
"""
import os
import time

# 必须在引入 faster_whisper / huggingface_hub 之前设置
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ["HF_HUB_DISABLE_XET"] = "1"            # 禁用 hf-xet（其 CAS 重建需鉴权，镜像下易 401）
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
_HF_HOSTS = "huggingface.co,cdn-lfs.huggingface.co,cdn-lfs.hf-mirror.com,hf-mirror.com"
_np = os.environ.get("NO_PROXY", "")
os.environ["NO_PROXY"] = (_np + "," + _HF_HOSTS) if _np else _HF_HOSTS
os.environ["no_proxy"] = os.environ["NO_PROXY"]

# ---- av 19.x 兼容补丁：faster-whisper 1.2.x 调用 av.open(metadata_errors=...)
#      但 av 19 已移除该参数，剥离后调用真实 open，避免 TypeError ----
try:
    import av as _av
    _orig_av_open = _av.open

    def _av_open_compat(*args, **kwargs):
        kwargs.pop("metadata_errors", None)  # av 19 不再接受此参数
        return _orig_av_open(*args, **kwargs)

    _av.open = _av_open_compat
except Exception:
    pass

_whisper_model = None
_load_error = None

MODEL_NAME = os.getenv("WHISPER_MODEL", "base")  # tiny / base / small；CPU 默认 base
# 技术术语提示，引导模型识别面试常用词
INITIAL_PROMPT = (
    "以下是大学生技术面试的中文回答，涉及 Java、Python、HashMap、ConcurrentHashMap、"
    "JVM、Spring、MySQL、Redis、线程、并发、锁、集合框架、B+ 树、索引等知识点。"
)


class AudioTooLong(ValueError):
    pass


def get_model():
    """懒加载并复用 WhisperModel。失败时缓存原因，后续直接抛出，不反复重试。"""
    global _whisper_model, _load_error
    if _whisper_model is not None:
        return _whisper_model
    if _load_error is not None:
        raise RuntimeError(_load_error)
    try:
        from faster_whisper import WhisperModel
        # CPU + int8：Windows CPU 上轻量且较快
        _whisper_model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
        return _whisper_model
    except Exception as e:
        _load_error = str(e)
        raise RuntimeError(_load_error)


def is_available():
    """探测是否可用（不触发模型加载，仅判断依赖是否就绪）。"""
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def transcribe(audio_path):
    """
    转写音频文件，返回 (text, duration_sec)。
    audio_path: 服务端临时音频文件路径（由调用方负责清理）。
    """
    # Decode with a hard sample-count bound before expensive ASR inference.
    from audio_analysis import _decode, AnalysisLimit
    try:
        audio, _ = _decode(audio_path, time.monotonic() + 15)
    except AnalysisLimit as exc:
        if str(exc) == 'audio_too_long':
            raise AudioTooLong() from None
        raise ValueError('audio_invalid_or_decode_timeout') from None
    model = get_model()
    segments, info = model.transcribe(
        audio,
        language="zh",
        initial_prompt=INITIAL_PROMPT,
        vad_filter=True,          # 过滤静音段
        beam_size=5,
    )
    text = "".join(seg.text for seg in segments).strip()
    duration = None
    try:
        duration = float(getattr(info, "duration", 0) or 0)
    except Exception:
        duration = None
    return text, duration
