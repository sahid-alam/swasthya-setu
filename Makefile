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

# `app.seed` truncates hospitals CASCADE, and beds/blood_stock hang off hospitals —
# so a reseed silently empties them and the Golden Hour and referral beats break with
# no error. Facilities are refilled here rather than left to memory.
seed:              ## full reseed. TRUNCATES patients — kills a live Telegram link
	cd backend && .venv/bin/python -m app.seed
	cd backend && .venv/bin/python -m app.seed_facilities

seed-facilities:  ## beds + blood only — additive, never truncates patients
	cd backend && .venv/bin/python -m app.seed_facilities

ingest-blood:  ## refresh blood stock through the e-RaktKosh adapter (mock by default)
	cd backend && .venv/bin/python -m app.ingest_blood

train:             ## retrain ML artifacts (downloads the 110k dataset on first run)
	cd backend && .venv/bin/python ../ml/train_noshow.py
	cd backend && .venv/bin/python ../ml/train_wait.py
	cd backend && .venv/bin/python ../ml/compare_fcfs.py

demo: migrate seed  ## everything a clean machine needs, then walk the runbook
	@echo ""
	@echo "  seeded: 3 hospitals, 30 doctors, 200 patients, 159 beds, blood stock"
	@echo "  next  : start the backend and frontend (infra/demo-script.md, top)"
	@echo "  guard : make demo-check   -> 12/12 before you present"
	@echo ""

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
