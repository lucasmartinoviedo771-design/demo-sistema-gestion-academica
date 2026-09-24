#!/usr/bin/env bash
# Reinicio nocturno de la instancia DEMO: vuelve a cargar los datos ficticios y
# borra lo que hayan subido los visitantes (fotos de perfil, documentos).
# Lo invoca el crontab del servidor; solo actúa sobre los contenedores ipes6-demo-*.
set -euo pipefail

cd "$(dirname "$0")/../../backend"
COMPOSE=(docker compose -f docker-compose.demo.yml --env-file .env.demo)

echo "=== $(date '+%F %T') reinicio de la demo"
"${COMPOSE[@]}" exec -T -u root backend sh -c 'find /app/media -mindepth 1 -delete'
"${COMPOSE[@]}" exec -T backend /app/.venv/bin/python manage.py seed_demo --reset --yes
echo "=== $(date '+%F %T') listo"
