COMPOSE ?= docker compose
.DEFAULT_GOAL := help

.PHONY: help up down logs build restart ps psql postgres prod prod-down clean

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

up: ## Start Postgres, backend (:8000), and frontend (:5173)
	$(COMPOSE) up -d --build

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

prod: ## Start Postgres + combined app image on :8080
	$(COMPOSE) --profile prod up -d --build postgres app

prod-down: ## Stop prod-profile services
	$(COMPOSE) --profile prod down

clean: ## Stop everything and delete the Postgres volume
	$(COMPOSE) --profile prod down -v
