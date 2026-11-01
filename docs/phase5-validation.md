# AI Interview Agent｜语音智能分析模块开发验收

日期：2026-10-31（Asia/Tokyo）。项目：`D:\AI_Interview_Agent`。

## 交付状态

已在原项目接入真实声学测量、回答关联、SQLite 历史读取和独立 DeepSeek 语音建议；保留原有综合评分、四维评分、历史面试和页面风格。没有重建项目，没有覆盖 `.env`，没有清空旧数据。

SER 已下载固定版本的预训练模型并完成真实本地 CPU 推理实验，但未通过中文真人面试准确性验证，因此暂不进入正式报告。用户已确认暂时没有真人录音，计划开发后邀请用户测试。本轮不把合成音频或模拟云端响应称作真人验收。

项目服务已更新并启动于 http://127.0.0.1:5001 ，健康接口正常，DeepSeek 配置可用。真实 DeepSeek 语音建议已有一次通过校验的成功调用。

## 修改与新增文件

运行代码：

| 文件 | 作用 |
| --- | --- |
| `audio_analysis.py`（新增） | 原始时间轴解码、VAD、时长、速率、停顿、RMS、YIN 基频、质量标记、资源限制 |
| `speech_review.py`（新增） | DeepSeek 内容与声学解释、原文证据校验、指标白名单、文本候选词统计 |
| `ser_experiment.py`（新增） | 固定模型的离线 SER 推理适配器，不接入正式报告 |
| `database.py` | 新增兼容表、单次分析 ID、原子关联、历史查询、建议保存及连接关闭 |
| `app.py` | 原转写接口可选分析、关联与报告扩展、语音建议重试；修正原 APIError 属性缺失 |
| `speech.py` | 在模型推理前限制解码样本数，继续保留原 faster-whisper 配置、术语提示与中文识别 |
| `interview.html`、`static/js/interview.js` | 基础分析开关、结果展示、提交时关联和取消关联 |
| `report.html`、`static/js/report.js` | 原报告内增加语言表达、真实声学指标、独立改进建议和历史空状态 |
| `static/css/style.css` | 新模块的局部表格样式；装饰提示条不再遮挡按钮点击 |
| `.gitignore` | 修正原有虚拟环境/数据库规则，排除模型、数据库和录音格式 |
| `tools/download_ser_model.py`（新增） | 固定版本模型下载与 SHA256 清单生成，仅下载公开权重，不上传录音 |

新增测试：`tests/test_audio_analysis.py`、`tests/test_speech_integration.py`、`tests/benchmark_acoustics.py`、`tests/benchmark_ser.py`、`tests/live_review_smoke.py`。扩展 `tests/test_real_asr.py`，维护 `tests/test_speech42.py` 的线程清理。原录音和 TTS 浏览器测试继续通过。

文档及结果位于 `docs/phase5-validation.md`、`docs/acoustic-benchmark.json`、`docs/ser-benchmark.json`、`docs/live-review-smoke.json`、`docs/speech-report-preview.png`。原 `docs/audio-analysis-design.md` 是上一阶段的设计基线，以本验收文档说明当前实现。

## 实际依赖

本轮没有新增 Python 运行依赖，没有安装 Torch、Transformers、librosa、scipy、soundfile、pyannote 或 parselmouth。

使用已有 NumPy 2.5.4、PyAV 19.0.2、ONNX Runtime 1.31.1、faster-whisper 1.2.1、Flask 3.1.3、OpenAI SDK 3.41.0、python-dotenv 1.2.4。浏览器测试继续使用已有 Playwright 1.64.1 和本机 Edge。

SER 权重约 373 MB，保存在 `models/emotion2vec-plus-base-onnx/`，未加入 Git。其模型卡、许可证、分类头和校验清单保存在同目录。

## 声学算法和统计口径

音频经 PyAV 解码为 16 kHz 浮点 PCM，先保留各声道重采样，再算声道算术平均；不使用会令同相双声道额外增加约 3dB 的默认下混矩阵。不会在测量前移除静音或归一化响度。

VAD 复用 faster-whisper 自带的 Silero ONNX 模型。固定参数：语音阈值 0.5、最短语音 100ms、切分静音阈值 250ms、padding 为 0。与 ASR 原有 VAD 处理分开，指标使用原始录音时间轴。[VAD 源码参考](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/vad.py)

| 指标 | 实现 |
| --- | --- |
| 总时长 | 实际解码样本数 / 16000 |
| 有效语音时长 | 合并后的 VAD 语音区间长度之和 |
| 静音总时长 | 总时长减有效语音时长；包含首尾静音 |
| 中文速率 | 原始 ASR 中文汉字数 × 60 / 有效语音秒数；另保留含停顿的总时长口径 |
| 英文速率 | 原始 ASR 英文单词数 × 60 / 有效语音秒数 |
| 混合语言 | 中文汉字、英文词独立计数，共用该段有效语音时长，不相加为统一“词速”；数字及标点不计入，JVM 等连续字母算一个词 |
| 内部停顿 | VAD 相邻语音段间至少 0.5 秒的空隙；排除首尾静音 |
| 停顿统计 | 次数、总时长、平均值、中位数、最长值；至少 1.5 秒的间隔另计长停顿 |
| 平均 RMS | 语音区间内 25ms 窗、10ms 步长，计算每帧 RMS；线性 RMS 均值再转 dBFS |
| 音量变化 | 帧 dBFS 的四分位距、P10/P90、最大最小差；保留数字指标，不解释为自信 |
| 削波 | 下混波形中绝对幅度至少 0.999 的样本比例；超过 1% 标记削波并停用基频统计 |
| 基频 | NumPy FFT 计算固定参考窗口的 YIN 差分和累积均值归一化差分；60ms 窗、20ms 步长、60–500Hz，取首个满足阈值的波谷并插值 |
| 基频质量 | 拒绝低周期性或低于 -50dBFS 的帧；至少 10 个有效帧且覆盖率至少 20% 才输出聚合值 |
| 音调变化 | 基频中位数、P10/P90、最低/最高/范围；相对本段中位数转半音后统计四分位距 |

全静音、无可靠有声帧或过短时，相应指标返回 null，不用零代替未知值。无停顿时次数为零，但平均/最长停顿为 null。英文/中文未出现时相应语言速率显示不适用。测量方法、参数、版本、原音频及 ASR 文字的 SHA256 均随结果保存，原音频不保存。

## API、关联和数据库

继续使用原 `POST /api/speech/transcribe`。新增可选表单字段 `include_analysis=true`、`session_id`、`question`。未开启分析时成功响应仍为原有 `success/text/duration`；开启时附加 `analysis`，成功持久化待关联结果时再附加 `analysis_id`。同一次上传内先转写、后分析，finally 删除临时音频。

新增 `speech_analyses` 表：`id`、`interview_id`、`question_sequence`、唯一可空 `message_id`、`result_json`、`feedback_json`、`created_at`、`expires_at`。真实指标完整保存在版本化 JSON 中，避免对旧表做破坏性迁移。所有新 SQL 使用参数绑定。

分析 ID 为服务器生成的随机值，限定同一面试、同一问题，只能关联一次；未关联时一小时过期。用户提交回答时只传 ID，不接受客户端上传的指标 JSON。插入回答和消费分析 ID 在同一个 SQLite 写事务内完成。跨场、跨题、过期或重复使用均返回 409；用户可重新识别或点“不关联本段指标”后提交文字。

回答只在 AI 成功响应后落库，失败时保留草稿及待关联分析。这也修正了原流程在 AI 失败后可能遗留用户消息、重试后重复写入的问题。跳过题目不会绑定当前录音指标。编辑回答不重算原录音速率，报告会提示两者文字存在差异。

`GET /api/report/<id>` 在原报告字段之外附加 `speech_analyses`，只读取已关联回答。建议在生成原报告后尝试生成；独立 `POST /api/report/<id>/speech-review` 支持重试。重试不改原评分，也不会重新生成已经有效的建议。旧报告无音频关联时明确显示“尚未采集”。删除面试时关联分析通过外键级联删除。

已在迁移前备份 SQLite。迁移后逐行比对，原有 6 场面试、23 条消息、1 份报告完全一致；开发与自动化测试数据使用临时数据库，正式库新表没有测试行。

## DeepSeek 智能建议

原 DeepSeek 客户端、岗位、面试状态机、出题、追问和四维评分权重保留。新增独立请求输入实际最终回答、问题、岗位名称、上下文、原始录音指标和质量标记；没有具体岗位 JD 时不会伪造招聘要求。

输出包含切题、专业知识、完整度、逻辑、重复表达、口头禅候选、指标定性解释和改进建议。内容证据必须逐字存在于最终回答；声学评论只能引用白名单中已采集的非空指标。AI 不返回正式测量值，界面从服务器测量结果单独显示数字；包含数值或心理标签的不合规声学评论/建议会被拒收。

候选词匹配和完整重复句由程序计算，不把“那个/就是/然后”等出现次数直接等同于口头禅。ASR 可能省略语气词，不能据此断言真人没有口头禅。没有词级时间对齐时，局部语速波动属于未采集项，不根据全局速率推断。

真实云端测试最初出现空内容和不合规引用，系统正常拒收并保留评分与声学结果。收紧字段约束、明确指标白名单和提高独立建议输出预算后，真实调用已成功并通过校验。生成结果仍是 AI 辅助反馈，个别响应可能因校验失败而需要重试。

## SER 模型和实际实验

对比方向：Wav2Vec2 ONNX INT8 英语分类模型较小，但缺乏中文面试验证；audEERING 模型输出维度而非这次所需的离散类别，且非商业许可不适合直接作为未来产品的默认方案。选择 emotion2vec+ 的本地 ONNX 导出进行实验，避免为测试安装 Torch/FunASR 全套依赖。

实际使用 `emotion2vec/emotion2vec_plus_base`，由 `pankotaro/emotion2vec-plus-base-onnx` 转换。固定转换仓库版本 `334d4376993c381f059cc36d2c6ed05cbfec5ca1`，校验 ONNX 与分类头 SHA256。输出九类：angry、disgusted、fearful、happy、neutral、other、sad、surprised、unknown。

[模型卡和推理方式](https://huggingface.co/pankotaro/emotion2vec-plus-base-onnx)；[原模型来源](https://huggingface.co/emotion2vec/emotion2vec_plus_base)；[模型许可证](https://huggingface.co/pankotaro/emotion2vec-plus-base-onnx/blob/334d4376993c381f059cc36d2c6ed05cbfec5ca1/LICENSE)。模型卡标注 FunASR Model Open Source License，需保留来源、作者和模型名称；本地保留了许可证文件。本轮未将模型权重或录音提交 GitHub。

本机 Windows / Python 3.13 / ONNX Runtime CPU 结果：

- 模型初始化约 1298.7ms；3 秒输入推理 220.5ms；8 秒输入两次约 621.9ms、685.4ms。
- 独立实验进程峰值工作集约 657.0MB；这不是与 Whisper 同时运行时的总内存。
- 系统合成中文音频预测 neutral；3 秒最大 softmax 约 0.973，8 秒达到浮点显示 1.0。
- 以上只是未校准的模型分数，绝不是判断真实情绪的正确率。没有真人标注数据，不能据此证明泛化准确性。

因此交付离线实验模块及全部类别分布，但不把 SER 接入默认请求，不在正式报告显示情绪类别，也不影响 ASR。后续取得用户授权和人工标注后，再评估中文、口音、噪声与不同说话人下的混淆矩阵和校准误差；达标后才考虑显式开启的实验选项。

## 实际测试

语法：Python 编译、两个页面 JavaScript 语法检查通过。

数值：8 组声学测试通过，包括 65/100/220/440/490Hz 已知频率、已知 -23.01dBFS 正弦 RMS、指定停顿、双声道重采样、噪声、静音、短音频、削波、预算和占用降级。7 组接口/关联测试通过，覆盖跨场、过期、换题、重复关联、编辑文字、AI 失败回滚、历史读取、级联删除、迁移重入和拒收编造指标。原 5 组 ASR 接口测试及原文字面试/报告回归通过。

真实 Edge 浏览器 E2E 已通过：MediaRecorder 采集系统合成中文输入 → 实际 WebM 上传 → Flask → faster-whisper → 声学计算 → 不自动提交 → 编辑后手动提交 → 单次 ID 关联 → SQLite → 报告 → 清空内存会话后历史读取。该 E2E 的云端反馈用测试替身；另有一次真实 DeepSeek 调用通过校验。原录音竞态与 TTS 浏览器回归也通过，390px 移动宽度检查无横向溢出。

另完成 11 个实际音频文件场景，除 120 秒性能样本外均调用真实 faster-whisper base：普通中文、中英混合、SAPI 快速/慢速、插入明显停顿、60 秒静音、叠加噪声、纯噪声、极短、低音量和 120 秒长音频。全部为明确标注的合成语音或生成信号，不是真人录音。测试临时音频自动清理。

代表性数值：普通中文有效语音速率约 267.9 汉字/分钟，快速约 368.7，慢速约 193.6；中英混合约 154.9 汉字/分钟、32.6 英文词/分钟。噪声与低音量样本基频返回 null，静音样本语音时长为零、速率为空。120 秒样本只测性能，不提供语速校验值。

本轮最后一次性能矩阵中，普通样本分析约 67.3ms，混合约 45.5ms，60 秒静音约 113.5ms，120 秒音频约 474.1ms；运行 Whisper 与声学矩阵的进程峰值约 370.6MB。详细值、原始转写、质量标记及所有统计见附带 JSON。

## 资源和错误处理

保留整体上传上限 25MB、浏览器最长录音 120 秒；后端解码最多 125 秒（为容器尾帧保留余量），超限在 ASR 推理前拒绝。支持 PyAV 可解码的 WebM/Opus、WAV、Ogg、MP4 等，不假定浏览器输出 WAV。

临时文件由服务端安全创建，文件名只取白名单后缀；损坏、空音频、无语音、设备权限和网络异常不会生成伪转写。分析使用单个非阻塞本地工作槽，忙碌时降级，不排队占用无限资源；合作式预算为 4 秒，检查解码和 FFT 批次，原生 VAD 单次调用不能在内部被抢占。

识别或分析失败仍可继续文字面试；SER 完全隔离。已开始的原生推理不能被浏览器取消直接终止，跨进程队列和任务抢占尚未实现。生成语音建议会向既有 DeepSeek 服务发送文本与指标，不发送原始录音。

## 重复运行

在项目目录、使用已有虚拟环境执行：

```powershell
.\.venv\Scripts\python.exe -m compileall -q app.py database.py speech.py audio_analysis.py speech_review.py ser_experiment.py tests
node --check static\js\interview.js
node --check static\js\report.js
.\.venv\Scripts\python.exe tests\test_audio_analysis.py
.\.venv\Scripts\python.exe tests\test_speech_integration.py
.\.venv\Scripts\python.exe tests\test_speech42.py
.\.venv\Scripts\python.exe tests\test_regression.py
.\.venv\Scripts\python.exe tests\test_browser42.py
.\.venv\Scripts\python.exe tests\test_tts43.py
.\.venv\Scripts\python.exe tests\test_real_asr.py
.\.venv\Scripts\python.exe tests\benchmark_ser.py
```

`tests/live_review_smoke.py` 会发起真实付费 DeepSeek 调用，不属于离线测试集。浏览器测试依次运行，使用 5009 端口；依赖本机 Edge 与已有 Whisper 模型缓存。`tools/download_ser_model.py` 可以重新获取固定模型，但正式服务不会自动下载或加载 SER。

## 邀请用户后的人工验收

1. 在 localhost 或 HTTPS 打开项目，开启麦克风，确认基础分析开关可见；讲话后停止，结果只进入可编辑文本框。
2. 分别录制普通中文、中英混合、快速、慢速、有明确停顿的同一段回答，用回放和人工时间标注核对语音区间、停顿位置与统计口径。
3. 测试长静音、噪声、极短录音和低音量，确认错误/质量提示清楚、未知基频为空，文字仍可手动作答。
4. 编辑转写后提交，确认只关联一次；报告保留原评分，新增指标基于录音，内容评价基于最终文字，并显示编辑差异提示。
5. 重录、重复点击、取消指标关联、识别时断网、跨标签页换题，确认没有旧结果错绑；回答提交失败后草稿和可用关联仍保留。
6. 结束面试并查看报告；服务重启后从历史再次进入，确认测量和有效 AI 建议仍在。旧文字报告明确显示未采集。AI 建议失败时重试按钮可用且评分不变。
7. 在 Edge/Chrome、Firefox、Safari 和手机上检查格式、麦克风权限、长表格、按钮及报告布局。实体麦克风与扬声器尚需人工验证。
8. SER 另行招募经过告知并自愿参与的测试者，建立带标注的中文样本和独立验证集；不要把模型输出直接当成用户真实心理状态。

## 尚未解决或未验证

真人音频准确性、口音/噪声泛化和真实浏览器设备矩阵尚未验收；F0 对复杂人声的倍频/半频误差仍需验证。局部语速波动未采集。dBFS 无法替代声压级，削波比例基于下混波形。文本候选词统计无法恢复被 ASR 省略的语气词。

SER CPU 推理可运行，但中文真人准确率和概率校准未验证，因此未接入正式报告。语音定性建议有严格拒收机制，个别云端输出可能需要重试。当前未新增登录权限体系，分析 ID 沿用既有随机 session_id 的访问边界；公开部署、多用户隔离和跨进程并发队列需单独加固。
