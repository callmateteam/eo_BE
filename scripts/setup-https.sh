#!/bin/bash
# EO API HTTPS 설정 - Nginx + Certbot (EC2에서 실행)
set -e

DOMAIN="eo-api.intalkpartners.com"
EMAIL="admin@intalkpartners.com"

echo "=== 1. Nginx + Certbot 설치 ==="
sudo apt-get update -y
sudo apt-get install -y nginx certbot python3-certbot-nginx

echo "=== 2. Nginx 설정 ==="
sudo tee /etc/nginx/sites-available/eo-api > /dev/null <<NGINX
server {
    listen 80;
    server_name ${DOMAIN};

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # WebSocket 지원
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
NGINX

sudo ln -sf /etc/nginx/sites-available/eo-api /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx

echo "=== 3. SSL 인증서 발급 ==="
sudo certbot --nginx -d ${DOMAIN} --non-interactive --agree-tos -m ${EMAIL}

echo "=== 4. 자동 갱신 테스트 ==="
sudo certbot renew --dry-run

echo "=== 완료! ==="
echo "https://${DOMAIN} 으로 접속 가능합니다."
