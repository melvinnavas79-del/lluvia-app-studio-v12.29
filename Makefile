.PHONY: up down build restart logs shell test lint status deploy-local

# ── Local development ─────────────────────────────────────────────────────────

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build --no-cache backend

restart: build
	docker compose up -d backend

logs:
	docker logs lluvia_backend -f --tail 100

shell:
	docker exec -it lluvia_backend bash

# ── Quality ───────────────────────────────────────────────────────────────────

lint:
	flake8 backend/ --max-line-length=120 \
		--exclude=backend/generated_apps,backend/uploads,backend/app_templates,backend/__pycache__ \
		--ignore=E501,W503,E203

test:
	REACT_APP_BACKEND_URL=http://localhost:8001 \
		python -m pytest backend/tests/ -v --timeout=30

# ── Status ────────────────────────────────────────────────────────────────────

status:
	@echo "=== Containers ==="
	@docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep lluvia
	@echo ""
	@echo "=== Backend health ==="
	@curl -s http://localhost:8001/api/ | python3 -m json.tool
	@echo ""
	@echo "=== Console LLM provider ==="
	@docker exec lluvia_backend python3 -c \
		"from llm_router import get_console_client; c,m=get_console_client(); print('Model:', m)"

# ── Production deploy (VPS) ───────────────────────────────────────────────────
# Run this on the VPS after git pull to rebuild and deploy without docker cp

deploy-local:
	@echo "Syncing source files..."
	cp backend/console.py /opt/lluvia/backend/console.py
	cp backend/llm_router.py /opt/lluvia/backend/llm_router.py
	cp backend/agents_catalog.py /opt/lluvia/backend/agents_catalog.py
	@echo "Rebuilding image..."
	cd /opt/lluvia && docker compose build --no-cache backend
	@echo "Restarting services..."
	cd /opt/lluvia && docker compose up -d
	@echo "Verifying..."
	@sleep 10
	@curl -s http://localhost:8001/api/ | python3 -c "import sys,json; d=json.load(sys.stdin); print('Status:', d.get('status'))"
