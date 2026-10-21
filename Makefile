.PHONY: up down logs clean

up:
	docker compose -f docker-compose.yml up -d --build

down:
	docker compose -f docker-compose.yml down

logs:
	docker compose -f docker-compose.yml logs -f

clean:
	docker compose -f docker-compose.yml down -v
