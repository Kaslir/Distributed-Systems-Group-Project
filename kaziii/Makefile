.PHONY: build up down logs test-load test-endpoints clean

build:
	docker build -t ds-server:latest ./server
	docker compose build

up: build
	docker compose up -d

down:
	docker compose down --remove-orphans
	-docker rm -f $$(docker ps -aq --filter ancestor=ds-server:latest)

logs:
	docker compose logs -f

test-load:
	python scripts/async_requests.py --requests 10000 --url http://localhost:5000/home

test-endpoints:
	python scripts/endpoint_tests.py

clean: down
	-docker image rm ds-server:latest ds-load-balancer:latest
