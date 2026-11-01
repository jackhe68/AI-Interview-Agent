# AI Interview Agent：4.2 自动转写与轻量 TTS 验收

日期：2026-10-31（日本时间）

## 项目与运行状态

项目位于 `D:\AI_Interview_Agent`，不是当前聊天的空工作目录。已确认仍为 Flask + 原生 HTML/CSS/JS + SQLite，面试与评分调用 DeepSeek，语音识别复用 faster-whisper。环境版本：Flask 3.1.3、faster-whisper 1.2.1、PyAV 19.0.2。本地已有 base 模型缓存。

检查开始时常用端口没有面试服务监听。完成后已启动项目原有 Flask 服务，地址为 http://127.0.0.1:5001 ，健康接口返回正常，DeepSeek 配置状态为已配置。配置状态不代表本轮验证过云端可用性；本轮没有发送付费 DeepSeek 请求。

引用聊天的预览没有实现细节，本环境也未提供 read_thread 工具；本轮以实际项目源码和本地运行结果为依据。未读取或打印 `.env` 文件内容，未输出 API Key。

## 改动文件

运行代码仅修改三个文件：

| 文件 | 改动 |
| --- | --- |
| `D:\AI_Interview_Agent\static\js\interview.js` | 自动转写、录音/请求状态保护、草稿保护、提交保护、浏览器 TTS |
| `D:\AI_Interview_Agent\interview.html` | 调整原有按钮与提示文字，添加状态播报属性；未改整体布局或 CSS |
| `D:\AI_Interview_Agent\app.py` | 现有转写路由的模型错误返回统一友好提示，避免将底层配置异常外显 |

新增 `D:\AI_Interview_Agent\tests\`：

- `test_speech42.py`：接口验证、上传校验、成功/失败、临时音频清理。
- `test_browser42.py`：浏览器交互、末尾 blob、竞态、草稿与重复操作。
- `test_real_asr.py`：真实 Edge MediaRecorder → Flask → 本地 faster-whisper。
- `test_tts43.py`：中文音色与 TTS 播放/停止、错误降级。
- `test_regression.py`：原有文字面试、SQLite、评分、历史与删除回归。
- `chinese-fixture.wav`：由 Windows 系统中文 TTS 生成的测试音频，不含真人录音。
- `requirements-dev.txt`：Playwright 1.64.1，仅用于浏览器测试。

技术设计另存于 `D:\AI_Interview_Agent\docs\audio-analysis-design.md`，本报告存于该目录的 `phase4-validation.md`。

`speech.py`、DeepSeek 提示词及面试流程、`database.py` 与数据库结构、报告评分逻辑、报告页面和 CSS 未修改。没有新建转写 API，也没有接入情绪模型或 TTS 云服务。项目没有 Git 仓库；本轮另提供运行代码差异补丁供审阅。

## 4.2 自动语音识别

用户停止录音后，先进入“正在生成完整音频”，只在 MediaRecorder 的 `stop` 事件中组装 blob。该事件位于最后一次 `dataavailable` 之后，不通过固定延时猜测音频是否完整。[事件顺序依据](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder/stop_event)

随后向原有 `POST /api/speech/transcribe` 发出一次 multipart 上传，后端继续调用 `speech.py`。识别结果进入现有文本框，绝不调用回答提交接口。回放、重新录音、手动重新识别、修改文字和 Ctrl/⌘+Enter 提交均保留。

界面区分等待权限、录音、音频收尾、上传、识别、完成和失败。上传完成事件后显示识别等待状态；这是客户端对处理阶段的展示，并非服务器实时进度。

主要边界处理：

- 录音或识别未完成时，阻止回答/跳过、重复上传和重复开始录音。
- 重新录音中止旧上传并递增录音编号；旧请求、旧设备回调和迟到结果无法覆盖当前状态。
- 用户等待识别时仍可编辑文字；有人工草稿时追加识别结果，避免覆盖。未编辑的上次转写可被重新识别结果替换。
- 空 blob 不上传；静音、无语音、解码失败、25MB 限制、权限拒绝、设备不可用和网络异常给出可恢复提示。
- 最长录音 120 秒，客户端识别等待上限 180 秒；失败保留当前音频和文字，允许重试。
- 只在回答成功后清理原回答；失败保留草稿。在下一题真正显示前持续锁住提交，防止切题等待期间重复提交。
- 结束面试和离开页面时停止设备、释放 blob URL、取消识别；结束按钮防止重复执行。

## 轻量 TTS

采用浏览器 SpeechSynthesis 最小版本，复用原“重听问题”按钮，点击“朗读问题”播放，再次点击“停止朗读”。首题及后续问题始终显示文字。当前版本不自动朗读，避免自动播放限制和未请求的声音。

通过 `getVoices()` 检测音色，并监听 `voiceschanged` 处理异步加载；优先选择 `zh-CN`，再选择其他中文音色。没有中文音色时明确提示安装系统中文语音或稍后重试，不强行使用英文音色朗读中文。[浏览器 API 依据](https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesis)

录音开始、提交、切题、结束、离开页面或播放回答录音时停止问题播报，避免将面试官声音录入回答。取消后的旧语音回调不能污染新播报状态。启动/播报超时或错误只更新 TTS 提示，不影响文字提交。

## 已执行测试

| 阶段 | 验证 | 结果 |
| --- | --- | --- |
| 4.2 | JavaScript 语法检查；Python 编译检查 | 通过 |
| 4.2 | Flask 5 组测试：页面/健康、上传校验、成功、失败清理、超限 | 全部通过 |
| 4.2 | Edge 浏览器测试：最后 blob、只上传一次、不自动提交、回放入口、取消旧识别、保留编辑、断网/静音、空音频、权限拒绝、等待权限保护 | 通过，无页面 JS 错误 |
| 4.2 | 真实 Edge MediaRecorder 录制中文合成音频，经过实际 multipart、Flask、faster-whisper CPU base，检查识别文字并确认未提交 | 通过；加入 TTS 后再次通过 |
| TTS | 语法与原 ASR 浏览器回归 | 通过 |
| TTS | 浏览器测试：不支持、无中文音色、异步音色、中文优先、播放/停止、旧事件、播报错误/异常 | 通过 |
| 原流程 | 3 主问题及 3 次追问、结束、加权分 77、报告读取、清空会话后从 DB 读取、历史、删除 | 通过 |
| 设计 | 对照当前 API、原始音频生命周期、VAD 与指标定义检查 | 已完成，仅设计，未新增运行接口 |

接口测试用转写替身覆盖错误分支；真实识别另用实际缓存模型完成。TTS 边界测试使用可控的浏览器 API 替身，没有声称自动验证过真实扬声器。原面试回归的 DeepSeek 响应为测试替身，使用临时 SQLite，未写入现有面试数据。

## 重复运行

在项目目录运行（需要现有虚拟环境及本机 Edge）：

```powershell
.\.venv\Scripts\python.exe -m pip install -r tests\requirements-dev.txt
node --check static\js\interview.js
.\.venv\Scripts\python.exe -m compileall -q app.py speech.py tests
.\.venv\Scripts\python.exe tests\test_speech42.py
.\.venv\Scripts\python.exe tests\test_browser42.py
.\.venv\Scripts\python.exe tests\test_real_asr.py
.\.venv\Scripts\python.exe tests\test_tts43.py
.\.venv\Scripts\python.exe tests\test_regression.py
```

浏览器测试依次运行，使用本地 5009 端口并自动关闭测试服务。真实 ASR 测试当前依赖本机默认缓存目录下的 faster-whisper-base 模型以及附带音频；其他机器需要调整模型缓存路径和 Edge 路径。

## 人工验收步骤

1. 打开 http://127.0.0.1:5001 ，开始一场面试；确认首题文字、进度、历史入口与原页面样式正常。
2. 点击朗读问题，确认中文可听清、再次点击可停止。录音开始时应停止朗读。没有中文音色时应有提示，仍能文字回答。
3. 允许麦克风，真实讲话 5–15 秒后停止；观察收尾、上传、识别和完成提示；检查末尾一句未丢失，文字出现后没有自动提交。
4. 回放确认声音完整；编辑转写，再手动提交。核对只进入下一题一次；尝试 Ctrl/⌘+Enter 快捷提交。
5. 识别期间输入草稿，完成后确认草稿仍在；识别期间点击重新录音，确认旧结果不会覆盖新内容。
6. 拒绝权限、静音录音、临时断网后分别重试；确认保留可用音频与草稿、失败不会卡死文字流程。连续快速点击开始/停止/重新识别，确认没有重复请求。
7. 录音达到 120 秒确认自动停止；识别期间结束面试或离开页面，确认麦克风指示灯熄灭。
8. Edge/Chrome 桌面与 Safari/iPhone、Firefox 分别验收格式和中文音色；选择无中文语音包环境确认降级。必要时使用 localhost 或 HTTPS 获取麦克风权限。

## 已知限制

- 真实用户麦克风、扬声器、不同设备和移动端浏览器仍需上述人工验收；本轮真实录音链路使用合成中文输入。
- SpeechSynthesis 的中文音色由浏览器/操作系统决定。没有新增云端账单，但部分系统音色可能由浏览器或操作系统联网提供；当前未承诺全部离线。
- faster-whisper base 的中文、专业术语和噪声环境准确率有限，应人工校对；首次加载耗时取决于设备及模型缓存。
- 客户端中止请求不会终止服务端已开始的推理。用户可恢复操作，但立即重试可能增加 CPU 工作量；跨标签页的服务端任务去重/队列不在本轮范围。
- 提交保护针对本页重复操作；原服务端没有新增跨刷新、跨标签页的幂等协议。提交响应若在服务端成功后因网络丢失，重试前应核对当前面试状态。
- 本轮未做真实 DeepSeek 云端连通性和付费评分测试；文字流程与评分回归使用确定性的测试响应。

下一阶段的原始音频/VAD/语速/停顿/音量/基频设计见同目录的音频分析设计文档。本轮没有将任何音频指标或情绪标签加入报告分数。
