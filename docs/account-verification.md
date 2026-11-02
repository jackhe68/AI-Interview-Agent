# 账户版验证记录

本文件保留首次账户版8be907d的历史验证快照。后续并发安全、HEAD与测试路径修复及重跑结果见 [复查修复记录](audit-followup-fixes.md)。

2026-11-02：27个测试入口通过，其中 unittest 汇总112项用例；其余入口按整段场景断言，不虚增为单独用例数。测试使用独立临时数据库和虚构资料，不清理真实用户记录。

| 测试入口 | 用例/场景 | 结果 |
| --- | --- | --- |
| test_account_browser.py | 脚本场景 | 通过 |
| test_account_migration.py | 脚本场景 | 通过 |
| test_account_restart.py | 脚本场景 | 通过 |
| test_accounts.py | 14 | 通过 |
| test_api_guard.py | 11 | 通过 |
| test_audio_analysis.py | 8 | 通过 |
| test_background.py | 9 | 通过 |
| test_browser42.py | 脚本场景 | 通过 |
| test_clarity_browser.py | 脚本场景 | 通过 |
| test_delivery.py | 4 | 通过 |
| test_delivery_browser.py | 脚本场景 | 通过 |
| test_draft_recovery.py | 7 | 通过 |
| test_flow_browser.py | 脚本场景 | 通过 |
| test_formal_security.py | 脚本场景 | 通过 |
| test_major_paths.py | 6 | 通过 |
| test_output_token_limit.py | 2 | 通过 |
| test_pdf_export.py | 6 | 通过 |
| test_practice_flow.py | 5 | 通过 |
| test_practice_value.py | 8 | 通过 |
| test_public_test.py | 5 | 通过 |
| test_regression.py | 脚本场景 | 通过 |
| test_relaxed_trial.py | 6 | 通过 |
| test_report_recovery.py | 5 | 通过 |
| test_speech42.py | 5 | 通过 |
| test_speech_integration.py | 7 | 通过 |
| test_time_clarity.py | 4 | 通过 |
| test_tts43.py | 脚本场景 | 通过 |

## 验收覆盖

| 要求 | 证据 |
| --- | --- |
| 注册、重复/并发用户名、无效字段、密码不一致 | accounts：真实scrypt、数据库约束、并发注册；account_browser：表单提示、Tab/Enter |
| 登录失败/成功、过期、退出、改密、注销 | accounts；浏览器A/B切换、改密再登录与注销；formal_security验证Secure/HttpOnly/SameSite |
| 刷新、重新登录、重启与另一设备资料一致 | accounts、account_browser、实际子进程account_restart；线上第二客户端登录 |
| 两账户、游客、直接接口隔离与CSRF | accounts覆盖状态/回答/结束/背景/报告/语音/音频/PDF/删除/重答；formal_security在API_GUARD=0仍保护 |
| 游客显式迁移、重复/非法迁移、旧游客Cookie | accounts事务及禁止任意ID；线上旧版本创建游客练习，保留同一Cookie跨升级后确认认领 |
| 注销和关联数据、临时文件 | accounts填入任务/消息/背景/回执/音频指标/重答后级联删除；录音成功/失败清理；实际进程重启清理专用目录遗留音频，保留未知文件 |
| 草稿/缓存/换账户 | 浏览器其他标签页退出使旧页隐藏并跳转，旧页不再回写；再登录A/B不出现旧会话或草稿；BFcache代码核对与重新加载 |
| 同意、姓名、背景24小时 | accounts抓取模型请求验证无昵称，未同意无账户学习阶段；background验证拒绝未同意、过期与结束清理 |
| 历史加载/错误/空/有数据/删最后条 | account_browser模拟断网与删最后条；public浏览器游客空状态；CSS互斥断言 |
| 空/空格/4000/4001/非法字符/重复回答 | accounts；draft_recovery；同request_id响应重放且只调用一次模型 |
| 断网和已保存但响应丢失 | account_browser先route.fetch让服务器保存再abort响应；核对题目和计数；离线草稿重载恢复 |
| 开始、作答、报告、重答、PDF、历史、删除 | account_browser与regression；线上真实DeepSeek完整单场验证并清理其虚构账户及练习 |
| 报告生成时重启、恢复备份不复活删除 | account_restart真实终止进程，保留DB/会话后重启；测试租约1秒，运行默认90秒；备份恢复再应用台账 |
| 移动390px/桌面/键盘/错误 | account_browser，practice_value，draft_recovery，clarity_browser；软键盘通过390×450缩小视口验证，尚无真实物理键盘覆盖 |
| 评分可信度 | 全跳过不调用模型、不显示占位0分；缺失维度未评估、证据校验、不显示薄弱点精确百分比；重答不重评分且保存版本 |

## 替身与真实服务的区别

大部分测试以可控函数替代DeepSeek，覆盖失败、超时、截断、幂等、隐私契约与界面。ASR接口的安全与临时文件测试使用转写替身；audio_analysis包含真实VAD/数值算法测试，本轮不把它称为真实麦克风或Whisper整段转写验证。

另在现有HTTPS试用网址使用虚构候选人真实调用：开始面试、提交一次回答、提前结束并生成报告，共3次DeepSeek请求。重复提交命中回执，重答不调用AI；PDF成功。两账户及第二客户端验证归属、资料、密码撤销和注销。所有验收账户与该场练习均已删除，原业务字段未变。真实AI仅验证该样本可用，不表示全部岗位反馈质量都已验证。

线上计时：作答应用3186.30ms，其中AI3175.18ms、数据库10.04ms；同一次提交重放2.75ms、AI0；报告后台34363.41ms，其中AI34343.18ms。请求/任务关联仅含摘要标识，不能据此归因此前首页9秒样本。

## 数据保留与当前部署

增量迁移后逐项比对升级前备份的原字段：公网60场面试、432条消息、17份报告全部一致；本地interviews.db原业务表为空，已执行同一迁移。两库完整性检查ok、外键错误0。公网原地址、游客签名密钥与AI并发配置1000保留。

私有操作备份留在本机当前Codex任务的 work/accounts-before-deploy，未加入Git；包含一致数据库和本次覆盖的原代码。原始测试日志、截图与测量数据在同任务 outputs。请按运维文档保护备份并设置自己的保留策略。

## 页面截图与未验证事项

截图：桌面/390px个人资料、注册错误提示、手机练习区、报告、历史错误态、线上手机注册和游客空状态。均使用虚构资料或无资料页面。

未验证：正式云主机/Nginx实际运行、真实手机/微信键盘、固定域名或持久隧道可靠性、目标并发下的容量、云端定时备份/恢复策略、全部岗位真实AI质量。具体步骤和验收条件见 accounts-and-operations.md。没有将1000配置或小样本测量称为容量验证。


## 复现主要测试

各入口在独立进程中执行，避免旧脚本共享全局测试配置。当前Windows浏览器脚本使用本机Edge路径；异机执行需调整浏览器路径，且测试依赖requests与playwright不属于服务端运行依赖。

```powershell
.\.venv\Scripts\python.exe tests/test_accounts.py
.\.venv\Scripts\python.exe tests/test_account_migration.py
.\.venv\Scripts\python.exe tests/test_account_restart.py
.\.venv\Scripts\python.exe tests/test_account_browser.py
.\.venv\Scripts\python.exe tests/test_formal_security.py
```
