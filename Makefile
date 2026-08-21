.PHONY: install bootstrap-local dev dev-local migrate seed seed-facilities ingest-blood load-check failure-drill demo demo-check test lint train tunnel sms-probe

# From a clean checkout, with postgres + redis running:
#   make install bootstrap-local migrate seed test

# Every target runs against DATABASE_URL/REDIS_URL, so the same commands work
# whether postgres and redis come from docker compose or a local install.
COMPOSE := docker compose -f infra/docker-compose.yml

install:           ## backend venv + frontend deps
	cd backend && uv sync
	cd frontend && npm install

bootstrap-local:   ## create the local role + database (compose does this itself)
	bash infra/bootstrap-local.sh

dev:               ## full stack via docker compose (canonical)
	$(COMPOSE) up --build

dev-local:         ## no-docker path: expects postgres + redis already running locally
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000 & \
	cd frontend && npm run dev

migrate:
	cd backend && .venv/bin/alembic upgrade head

seed:
	cd backend && .venv/bin/python -m app.seed

seed-facilities:  ## beds + blood stock — additive, never truncates patients
	cd backend && .venv/bin/python -m app.seed_facilities

ingest-blood:  ## refresh blood stock through the e-RaktKosh adapter (mock by default)
	cd backend && .venv/bin/python -m app.ingest_blood

train:             ## retrain ML artifacts (downloads the 110k dataset on first run)
	cd backend && .venv/bin/python ../ml/train_noshow.py
	cd backend && .venv/bin/python ../ml/train_wait.py
	cd backend && .venv/bin/python ../ml/compare_fcfs.py

demo: migrate seed  ## seeded demo day + scripted scenario
	@echo "scripted scenario lands in Phase 3 — see infra/demo-script.md"

sms-probe:         ## check the phone gateway; --send for ONE real message
	cd backend && .venv/bin/python ../infra/sms_probe.py $(ARGS)

tunnel:            ## publish the local backend for Vapi and re-point the assistant
	bash infra/tunnel.sh

failure-drill:  ## stop Redis, prove bookings survive, restart it
	backend/.venv/bin/python infra/failure_drill.py

load-check:  ## replan every doctor in the network, report the worst case
	backend/.venv/bin/python infra/load_check.py

demo-check:        ## Iron Rule 4 guard: walk the spine against a running stack
	backend/.venv/bin/python infra/demo_check.py

test:
	cd backend && .venv/bin/pytest -q
	cd frontend && npx vitest run

lint:
	cd backend && .venv/bin/ruff check . && .venv/bin/black --check .
	cd frontend && npm run lint
