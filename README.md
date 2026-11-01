# AI Interview Agent

面向求职练习的 AI 模拟面试网站，使用 Flask、DeepSeek 和 SQLite，支持文字回答、语音转写和面试复盘。

## 当前功能

- 按学科和专业逐级选择练习方向，保留直接选择岗位的入口。
- 提供多种面试难度，根据回答进行追问。
- 每题给出具体点评、回答思路、参考回答与练习建议。
- 回答草稿按面试和题目保存在当前浏览器，保留24小时，刷新后可恢复。
- 首页和历史记录可继续未完成面试，手机提供可展开的导航菜单。
- 报告后台生成，等待时先看已保存的逐题点评；可离开后回来查看，失败后手动重试。
- 静态资源按内容生成版本，重复访问可使用浏览器缓存。
- 最后一题提交后保留点评，手动点击“结束面试并查看报告”进入报告。
- 综合评分、八维分析、薄弱点建议、历史记录和 PDF 导出。
- 可选填写练习背景，并提供语音分析功能。

## 本地运行（Windows）

当前本机验证环境为 Python 3.13。在项目目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r deploy\requirements.txt
Copy-Item .env.example .env
```

在本地 `.env` 中填写 `DEEPSEEK_API_KEY`，然后启动：

```powershell
.\.venv\Scripts\python.exe app.py
```

浏览器打开 <http://127.0.0.1:5001>。首次使用语音转写需要下载 Whisper 模型；纯文字练习不需要先下载语音模型。

## 文档

- [公网试用说明](docs/public-trial-guide.md)
- [正式部署说明](deploy/README.md)
- [新评估报告复核与改进](docs/new-assessment-review.md)
- [时间与基础交互优化](docs/time-and-interaction.md)
- [继续面试与后台报告](docs/practice-flow.md)
- [草稿保护与手动查看报告](docs/draft-recovery.md)
- [专业选择与岗位推荐](docs/major-paths.md)
- [后续改进待办](docs/improvement-backlog.md)

`tests/` 包含面试流程、草稿恢复、语音、报告与浏览器交互检查；部分检查需要本机浏览器和语音模型，浏览器路径可在对应脚本中调整。

## 本地配置与数据

仓库保留代码、测试和说明文档，排除 `.env`、密钥、面试数据库、用户录音、运行日志、虚拟环境和下载模型。`tests/chinese-fixture.wav` 是语音测试使用的合成音频。PDF 中文字体及其许可位于 `assets/fonts/`。
