#!/usr/bin/env bash
# 服务器初始化（Ubuntu 24.04，root 执行）
# 用法：代码上传到 /var/www/aiinterview 之后运行
#   sudo bash /var/www/aiinterview/deploy/bootstrap.sh
set -euo pipefail

APP_DIR=/var/www/aiinterview
APP_USER=deploy
DOMAIN=mymianshiguan.cn          # 改这里，或运行前 export DOMAIN=xxx

[[ $EUID -eq 0 ]] || { echo "请用 root 运行：sudo bash $0"; exit 1; }
[[ -f $APP_DIR/app.py ]] || { echo "找不到 $APP_DIR/app.py，先把代码传上去"; exit 1; }
[[ -f $APP_DIR/.env ]] || { echo "缺少 $APP_DIR/.env（至少需要 DEEPSEEK_API_KEY）"; exit 1; }

echo "==> 1/8 系统更新与基础组件"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y
apt-get install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx \
                   ufw fail2ban unattended-upgrades ca-certificates curl

echo "==> 2/8 时区与 swap"
timedatectl set-timezone Asia/Tokyo      # 与代码里“按日本时间重置额度”保持一致
if ! swapon --show | grep -q '/swapfile'; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> 3/8 运行用户"
if ! id -u "$APP_USER" >/dev/null 2>&1; then
    adduser --disabled-password --gecos "" "$APP_USER"
    usermod -aG sudo "$APP_USER"
fi

echo "==> 4/8 Python 虚拟环境与依赖"
cd "$APP_DIR"
[[ -d .venv ]] || python3 -m venv .venv
.venv/bin/pip install --upgrade pip wheel
.venv/bin/pip install -r deploy/requirements.txt

echo "==> 5/8 预热 faster-whisper（首次下载 base 模型，约 150MB，走 hf-mirror）"
if .venv/bin/python -c "import speech; speech.get_model(); print('whisper ready')"; then
    echo "    模型已就绪"
else
    echo "    !! 模型加载失败，先在服务器上手动排查网络/磁盘再继续"
    exit 1
fi

echo "==> 6/8 权限"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 600 "$APP_DIR/.env"
chmod 600 "$APP_DIR/.secret_key" 2>/dev/null || true
chmod 700 "$APP_DIR/interviews.db" 2>/dev/null || true

echo "==> 7/8 systemd 服务"
install -m 644 "$APP_DIR/deploy/aiinterview.service" /etc/systemd/system/aiinterview.service
systemctl daemon-reload
systemctl enable aiinterview
systemctl restart aiinterview
sleep 3
systemctl --no-pager --lines=20 status aiinterview || true

echo "==> 8/8 Nginx 与防火墙"
sed "s/mymianshiguan\.cn/$DOMAIN/g" "$APP_DIR/deploy/nginx.conf" > /etc/nginx/sites-available/aiinterview
ln -sf /etc/nginx/sites-available/aiinterview /etc/nginx/sites-enabled/aiinterview
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

ufw allow OpenSSH
ufw allow 80,443/tcp
ufw --force enable

curl -fsS http://127.0.0.1:5010/api/health && echo

echo
echo "完成。下一步："
echo "  1. 域名 A 记录（@ 和 www）指向本机公网 IP"
echo "  2. 解析生效后：sudo certbot --nginx -d $DOMAIN -d www.$DOMAIN --redirect"
echo "  3. 手机 4G 访问 https://$DOMAIN 完整跑一次面试流程"
