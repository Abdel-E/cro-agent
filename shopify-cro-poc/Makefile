.PHONY: help setup setup-backend setup-simulator run-backend run-frontend demo reset simulate plot test test-journey test-perception test-reasoning test-execution journey-demo

# Ubuntu/WSL often has `python3` but not `python`; use this for the static file server.
PYTHON ?= python3

BASE_URL ?= http://localhost:8000
SESSIONS ?= 5000
BASELINE ?= 1
OUTCOME ?= drop_off

help:
	@printf "Targets:\n"
	@printf "  make setup         - create venvs and install deps\n"
	@printf "  make demo          - run backend + frontend together\n"
	@printf "  make reset         - reset in-memory bandit state\n"
	@printf "  make simulate      - run contextual traffic simulation\n"
	@printf "  make plot          - generate per-segment charts from latest CSV\n"
	@printf "  make test          - run backend unit tests\n"
	@printf "  make test-journey  - run journey Phase 1 API tests\n"
	@printf "  make test-perception - run Phase 2 perception tests\n"
	@printf "  make test-reasoning - run Phase 3 reasoning tests\n"
	@printf "  make test-execution - run Phase 4 execution tests\n"
	@printf "  make journey-demo  - run one scripted journey demo flow\n"

setup: setup-backend setup-simulator

setup-backend:
	cd backend && $(PYTHON) -m venv .venv && ./.venv/bin/pip install -r requirements.txt

setup-simulator:
	cd simulator && $(PYTHON) -m venv .venv && ./.venv/bin/pip install -r requirements.txt

run-backend:
	cd backend && ./.venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

run-frontend:
	cd frontend && $(PYTHON) -m http.server 5173

demo:
	@(cd backend && ./.venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000) & BACK_PID=$$!; \
	(cd frontend && $(PYTHON) -m http.server 5173) & FRONT_PID=$$!; \
	printf "Backend:  http://localhost:8000\nFrontend: http://localhost:5173\n"; \
	printf "Press Ctrl+C to stop both.\n"; \
	trap 'kill $$BACK_PID $$FRONT_PID' INT TERM; \
	wait

simulate:
	cd simulator && ./.venv/bin/python run_simulation.py --base-url $(BASE_URL) --sessions $(SESSIONS) $(if $(filter 1,$(BASELINE)),--uniform-baseline,)

reset:
	@curl -s -X POST $(BASE_URL)/reset
	@printf "\nModel state reset at $(BASE_URL)/reset\n"

plot:
	cd simulator && ./.venv/bin/python plot_results.py

test:
	cd backend && ./.venv/bin/python -m pytest tests/ -v

test-journey:
	cd backend && ./.venv/bin/python -m pytest tests/test_api.py -v -k journey

test-perception:
	cd backend && ./.venv/bin/python -m pytest tests/test_perception.py -v

test-reasoning:
	cd backend && ./.venv/bin/python -m pytest tests/test_reasoning.py -v

test-execution:
	cd backend && ./.venv/bin/python -m pytest tests/test_execution.py -v

journey-demo:
	bash ./scripts/journey_demo.sh --base-url $(BASE_URL) --outcome $(OUTCOME)
