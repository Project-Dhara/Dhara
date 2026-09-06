COMPOSE ?= docker compose
.DEFAULT_GOAL := help

# Local URLs (override if you change ports in docker-compose.yml)
FRONTEND_URL ?= http://localhost:3000
BACKEND_URL  ?= http://localhost:8000
PROD_URL     ?= http://localhost:8080
API_DOCS     ?= $(BACKEND_URL)/docs

.PHONY: help urls up down logs build restart ps psql postgres prod prod-down clean

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

urls: ## Print local service URLs
	@echo ""
	@echo "  Dev UI:      $(FRONTEND_URL)"
	@echo "  Dev API:     $(BACKEND_URL)"
	@echo "  API docs:    $(API_DOCS)"
	@echo "  Health:      $(BACKEND_URL)/api/health"
	@echo "  Prod (all):  $(PROD_URL)"
	@echo ""

up: ## Start Postgres, backend (:8000), and frontend (:3000)
	$(COMPOSE) up -d --build
	@echo ""
	@echo "  UI:      $(FRONTEND_URL)"
	@echo "  Backend: $(BACKEND_URL)"
	@echo "  Docs:    $(API_DOCS)"
	@echo ""

down: ## Stop containers (keeps the database volume)
	$(COMPOSE) down

logs: ## Follow logs from all running services
	$(COMPOSE) logs -f

build: ## Rebuild backend and frontend images
	$(COMPOSE) build

restart: ## Restart running services
	$(COMPOSE) restart

ps: ## Show container status
	$(COMPOSE) ps

psql: ## Open a psql shell on the Docker Postgres
	$(COMPOSE) exec postgres psql -U dhara -d dhara

postgres: ## Start only Postgres (run backend/frontend on the host)
	$(COMPOSE) up -d postgres
	@echo ""
	@echo "  Postgres: postgresql://dhara:dhara_local_password@localhost:5432/dhara"
	@echo "  UI:       $(FRONTEND_URL)  (run frontend on host)"
	@echo "  Backend:  $(BACKEND_URL)  (run backend on host)"
	@echo ""

prod: ## Start Postgres + combined app image on :8080
	$(COMPOSE) --profile prod up -d --build postgres app
	@echo ""
	@echo "  App (UI + API): $(PROD_URL)"
	@echo "  API health:     $(PROD_URL)/api/health"
	@echo ""

prod-down: ## Stop prod-profile services
	$(COMPOSE) --profile prod down

clean: ## Stop everything and delete the Postgres volume
	$(COMPOSE) --profile prod down -v
