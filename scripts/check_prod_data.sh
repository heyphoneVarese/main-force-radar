#!/usr/bin/env bash
set -u

echo "========== 0. Find Project Directory =========="
PROJECT_DIR="${1:-}"

if [ -z "$PROJECT_DIR" ]; then
  COMPOSE_FILE="$(
    find /root /home /opt /var/www \
      -maxdepth 4 \
      -name docker-compose.yml \
      -print 2>/dev/null \
      | head -n 1
  )"
  if [ -n "$COMPOSE_FILE" ]; then
    PROJECT_DIR="$(dirname "$COMPOSE_FILE")"
  fi
fi

echo "PROJECT_DIR=${PROJECT_DIR}"

if [ -z "$PROJECT_DIR" ] || [ ! -f "$PROJECT_DIR/docker-compose.yml" ]; then
  echo "ERROR: docker-compose.yml not found"
  exit 1
fi

cd "$PROJECT_DIR" || exit 1

echo
echo "========== 1. Docker Compose PS =========="
docker compose ps

echo
echo "========== 2. Backend DATABASE_URL / SCHEDULER_ENABLED =========="
docker compose exec -T backend sh -lc \
  'env | grep -E "^(DATABASE_URL|SCHEDULER_ENABLED)=" || true'

echo
echo "========== 3. sector_flow_daily max(trade_date) =========="
docker compose exec -T backend sh -lc \
  'sqlite3 /app/data/main_force_radar.db "select max(trade_date) from sector_flow_daily;" 2>/dev/null || echo "SQLite query failed or DB not found"'

echo
echo "========== 4. market_index_daily max(trade_date) =========="
docker compose exec -T backend sh -lc \
  'sqlite3 /app/data/main_force_radar.db "select max(trade_date) from market_index_daily;" 2>/dev/null || echo "SQLite query failed or DB not found"'

echo
echo "========== 5. intraday_sector_flow max(snapshot_time) =========="
docker compose exec -T backend sh -lc \
  'sqlite3 /app/data/main_force_radar.db "select max(snapshot_time) from intraday_sector_flow;" 2>/dev/null || echo "SQLite query failed or DB not found"'
