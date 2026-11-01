# 下一阶段音频分析设计（本轮不接入）

## 范围和边界

目标是从回答的原始音频得到可解释、可复现的表达指标。数值由信号处理与 VAD 计算；DeepSeek 最多解释已经计算好的指标，不负责生成或补齐数值。当前既不修改报告评分，也不接入情绪识别。

现有 `POST /api/speech/transcribe` 将上传音频写入临时文件，调用 `speech.transcribe` 后在 finally 中删除。当前 `speech.py` 只返回文字和总时长，未保留 VAD 区间、帧特征或词时间戳。不能仅从现有返回值恢复原始停顿或音高。

## 建议数据管线

原始上传文件 → PyAV 解码 → 单声道 16 kHz 浮点 PCM → 质量检测 → 原始时间轴 VAD → 帧级 RMS/F0 → 聚合统计 → 可选解释。

原始文件保持完整，在提取特征前不删除静音、不先归一化响度。VAD 区间以原始采样位置表示；用原始 PCM 分析音量和停顿，避免将 ASR 去静音后的序列误当原始时间轴。

可优先评估复用 faster-whisper 已有的 Silero VAD，无需先引入情绪模型。其项目文档说明集成了 Silero VAD，并支持词时间戳；使用内部 VAD 辅助函数时需固定已验证版本、封装适配层，避免依赖未经封装的私有 API。[faster-whisper 文档](https://github.com/SYSTRAN/faster-whisper/blob/master/README.md)

质量检测先计算总时长、实际采样率、声道数、语音占比、接近满幅的削波样本比例和有效有声帧比例。无声、损坏、过短、削波严重或信噪比不足时输出质量标记；无法可靠估计的数值返回 null，不填 0 冒充测量结果。

## 指标定义

| 指标 | 计算与单位 | 限制 |
| --- | --- | --- |
| 总时长 | 解码采样数 / 采样率，秒 | 以解码结果为准，不依赖浏览器计时器 |
| 语音时长/占比 | 合并 VAD 语音区间长度；语音时长 / 总时长 | 需记录阈值、padding 和区间合并规则；噪声可能误判 |
| 内部停顿 | 第一个至最后一个语音区间之间的非语音间隔；初始建议统计 ≥300ms 的停顿 | 首尾静音另记；300ms 是待验证参数，不是心理学阈值 |
| 停顿次数/总量/分位数 | 基于上述区间计算，单位次、秒 | 全静音时没有可解释的内部停顿，返回 null |
| 中文表达速率 | ASR 原始文本去标点后的汉字数 × 60 / 总时长；另给 /语音时长的发声速率 | 命名为汉字/分钟估计，不冒充真实音节数；混合英文另计词数，不能与汉字直接等价 |
| 音量 | 原始 PCM 的 25ms 窗、10ms 步长 RMS；20log10(max(RMS, epsilon))，dBFS；语音区间内给中位数及分位差 | dBFS 不是声压级 dB SPL，麦克风增益、距离和自动增益影响大，不可跨人直接排名 |
| 基频 F0 | 在语音区间的有效有声帧估计；可评估 YIN/pYIN，初始范围 60–500Hz 并记录参数；统计 Hz 中位数及分位数 | 不对清音/静音强行估计；排除低置信帧并给有效覆盖率；范围需覆盖不同说话人 |
| 音调变化 | 对有效 F0 转换为相对本人中位数的半音差，统计 IQR | 不把高低音调直接解释为紧张、自信或能力 |

RMS 和 YIN 可参考 [librosa RMS](https://librosa.org/doc/main/generated/librosa.feature.rms.html) 与 [YIN](https://librosa.org/doc/main/api/generated/librosa.yin.html) 的官方算法接口。实现前先在本机评估依赖大小与 CPU 延迟；本轮没有安装 librosa 或编写音频分析运行代码。

ASR 原始转写和用户编辑后的回答应分开看待：速率估计基于带版本的原始转写，文字评分继续使用用户最终提交文本。不能在用户补写一大段内容后，将新增字数归到录音语速里。计数规则、模型、参数、采样率、音频摘要和特征版本必须一起记录，保证可复现。

## 建议接口（仅设计）

先定义独立内部模块，不再创建另一套转写服务：

```python
analyze_audio(audio_path, asr_segments=None, options=None) -> AudioAnalysisV1
```

后续确认实现时，可对现有 `/api/speech/transcribe` 增加可选请求字段 `include_analysis=true`，默认关闭；仅在显式开启时，在现有成功响应中增加 `analysis`。原来的 `success/text/duration` 保持兼容。分析失败时仍返回成功转写及 `analysis.status=unavailable`，不能阻断作答。本轮未实现这个字段或改变现有响应。

建议返回结构，下面 null 表示尚未执行测量，不是示例测量值：

```json
{
  "schema_version": "audio-analysis.v1",
  "status": "unavailable",
  "source": {"audio_sha256": null, "sample_rate_hz": null},
  "method": {"vad": null, "vad_parameters": null, "pitch": null, "feature_version": null},
  "quality": {"flags": [], "voiced_frame_coverage": null, "clipping_ratio": null},
  "metrics": {
    "duration_s": null,
    "speech_s": null,
    "leading_silence_s": null,
    "trailing_silence_s": null,
    "pause_count": null,
    "pause_total_s": null,
    "hanzi_per_min_total": null,
    "hanzi_per_min_speech": null,
    "rms_dbfs_median": null,
    "f0_hz_median": null,
    "f0_semitone_iqr": null
  },
  "emotion": {"enabled": false, "status": "not_evaluated"},
  "warnings": []
}
```

初期只在同一次临时音频处理内提取，不持久化原始音频，不改 SQLite。分析执行需要独立的时长/资源预算和降级机制，不能让分析失败拖垮 ASR；若 CPU 延迟测试不达标，关闭可选分析，后续再评估后台任务，而不是延长现有回答等待。

如果后续确需跨回答保存分析结果，先明确用户告知、授权、存储期限和删除方式，再单独设计关联 ID 和可选存储迁移；不能把客户端提交的分析数字直接作为可信评分输入。本轮不创建音频表、不长期保存真人录音。

## 独立可选的情绪模块

保留模块边界，默认关闭。后续只有在独立验证数据、中文与真实录音条件下校准、误差评估之后才讨论接入。输出必须有模型/版本、概率分布、质量不足时的拒绝判断，以及“概率性辅助参考，不代表真实心理状态”的提示。

不能从音高、停顿、音量或情绪模型的标签推断候选人的真实心理状态、人格、诚信、疾病或录用适合性。情绪模块不进入当前技术知识评分；不将概率最高的类别伪装成确定事实。

## 后续验证门槛

1. 用有人工标注的静音、语音和已知间隔音频验证 VAD 与停顿；区分首尾静音和内部停顿。
2. 用已知频率合成信号和不同音高的语音验证 F0；确认清音与低覆盖率返回不可用。
3. 用固定增益与已知振幅波形验证 RMS/dBFS，测量削波及自动增益影响。
4. 用中文/中英混合人工转写验证字数与速率，报告 ASR 错误造成的不确定性。
5. 在目标 Windows CPU 上测量短答与 120 秒长答的延迟、峰值内存、并发与超时；所有分析失败都要能回退到原文字面试。
6. 指标验收与说明文字通过后再考虑界面展示，仍不调整现有报告分数；情绪模块另立验证项目。
