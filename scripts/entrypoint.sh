#!/bin/sh
set -e

echo "=== Prisma Generate ==="
python -m prisma generate

echo "=== Prisma DB Push (스키마 마이그레이션) ==="
python -m prisma db push --accept-data-loss
echo "=== 마이그레이션 완료 ==="

echo "=== 캐릭터 시드 데이터 ==="
python prisma/seed.py
echo "=== 시드 완료 ==="

echo "=== 서버 시작 ==="
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
