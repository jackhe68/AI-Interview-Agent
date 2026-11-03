# 部署手册（阿里云 轻量 4核8G / Ubuntu 24.04）

面向：`mymianshiguan.cn` + 大陆地域轻量应用服务器。香港/海外机器也能用，只是不需要备案。

账户版升级、备份、恢复和安全回滚，先阅读 [账户运维交付](../docs/accounts-and-operations.md)。请用新备份工具同时保存数据库与删除台账，单独恢复旧数据库可能复活已删除数据。

## 0. 前置

- 服务器已开通，公网 IP 已知，`ssh root@IP` 能登录
- 域名实名通过、ICP 备案通过（大陆机器；香港机器跳过）
- `.env` 至少包含 `DEEPSEEK_API_KEY`
- 建议同时设置固定密钥：`SECRET_KEY=<64位随机串>`（不设则 `wsgi.py` 自动生成到 `.secret_key`）

## 1. 建用户并打通密钥登录

```bash
adduser deploy && usermod -aG sudo deploy
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy
```

本地：

```powershell
ssh-copy-id deploy@<IP>
ssh deploy@<IP> "sudo -v"
```

## 2. 上传代码（Windows 本机）

```powershell
powershell -ExecutionPolicy Bypass -File deploy\upload.ps1 -Server <IP>
```

发布包仅包含 `package_release.py` 明确列出的运行代码、页面、静态资源、PDF字体及运维文件，并附带文件摘要清单。数据库、删除台账、真实 `.env`、签名密钥、录音、模型缓存、日志和测试产物不读取、不上传，更新代码不会用本地数据覆盖服务器数据。

首次部署前，需在服务器单独创建 `.env` 并填写密钥；`.env.example` 只提供模板。数据库由应用首次初始化，签名密钥按 `wsgi.py` 的既有方式持久化生成。若需要迁移现有数据，使用账户运维文档中的备份/恢复步骤，不能把数据库混入代码包。Whisper缓存由服务器预热准备，不随代码发布。

只生成发布包、供本地检查（不会上传或连接服务器）：

```powershell
.\.venv\Scripts\python.exe deploy\package_release.py --output .test-artifacts\release-review.tar.gz
```

输出须为新文件，避免覆盖旧版本。回滚代码时使用已验证的旧代码包；数据库、配置、签名与删除台账独立保留。不得通过恢复旧数据库来回滚一次普通代码更新。

也可运行 `powershell -NoProfile -ExecutionPolicy Bypass -File deploy\upload.ps1 -PackageOnly`，同时生成并校验本地发布包，不连接服务器。正式上传前逐文件核对摘要；打包、校验、上传或远端解包任一步失败，脚本以非零退出码停止，不执行后续步骤。每次上传使用独立临时文件名，不自动重启服务，不递归改动运行数据权限。远端解包失败时不要重启服务，需先恢复完整代码包。PS5和PS7均有隔离控制流测试。

## 3. 一键初始化（服务器）

```bash
sudo bash /var/www/aiinterview/deploy/bootstrap.sh
```

脚本做这些事：装 Python/Nginx/certbot/ufw/fail2ban → 设时区与 swap → 建 venv 装依赖 →
**预热 whisper 模型** → 写 systemd 服务 → 配 Nginx → 开防火墙 → 健康检查。

## 4. 域名解析与证书（备案通过后）

```
@    A   <公网IP>
www  A   <公网IP>
```

```bash
sudo certbot --nginx -d mymianshiguan.cn -d www.mymianshiguan.cn --redirect
sudo certbot renew --dry-run
```

## 5. 自检

```bash
ss -tlnp | grep -E '5010|:80|:443'     # 5010 只应出现在 127.0.0.1
curl -I https://mymianshiguan.cn
journalctl -u aiinterview -f           # 实时日志
```

浏览器完整跑一遍：开始面试 → 录音 → 转写 → 评分 → 报告 → 语音建议。

## 6. 日常运维

| 操作 | 命令 |
|---|---|
| 看状态 | `systemctl status aiinterview` |
| 重启 | `sudo systemctl restart aiinterview` |
| 更新代码 | 本机 `upload.ps1` 后 `sudo systemctl restart aiinterview` |
| 备份数据库及删除台账 | `.venv/bin/python tools/account_store.py backup --database interviews.db --target /var/backups/iv-before-update.db`（目标须为新文件；签名密钥另行妥善保存） |
| 看磁盘 | `df -h`、`du -sh /var/log/nginx/*` |

## 注意

- **不要改成 gunicorn -w N**，单进程多线程是设计前提。
- 升级依赖时改 `deploy/requirements.txt` 再 `pip install -r`，不要 `pip install -U` 全量升。
- 根目录各 `.html` 是模板（`template_folder="."`），别挪进 `templates/`。
- 试用入口 `tools/run_public_test.py`（Cloudflare Tunnel + trials.db）与正式站互不影响，别在生产机上跑。
