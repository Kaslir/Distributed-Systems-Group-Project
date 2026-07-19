import os
import random
import string
import subprocess
import threading
import time

import requests
from flask import Flask, jsonify, request

from consistent_hash import ConsistentHashMap


SERVER_IMAGE = os.getenv("SERVER_IMAGE", "ds-server:latest")
NETWORK_NAME = os.getenv("NETWORK_NAME", "kaziii_net1")
INITIAL_REPLICAS = int(os.getenv("N", "3"))
HEARTBEAT_INTERVAL = float(os.getenv("HEARTBEAT_INTERVAL", "2"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "2"))

app = Flask(__name__)
# The hash ring selects the replica that handles each proxied request
ring = ConsistentHashMap()
replicas: dict[str, int] = {}
lock = threading.RLock()
desired_replicas = INITIAL_REPLICAS


def response_ok(message, status_code=200):
    return jsonify({"message": message, "status": "successful"}), status_code


def response_fail(message, status_code=400):
    return jsonify({"message": message, "status": "failure"}), status_code


def docker(*args: str) -> str:
    result = subprocess.run(["docker", *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def random_hostname() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"S{suffix}"


def ring_balance_score() -> int:
    loads = ring.slot_loads().values()
    if not loads:
        return 0
    return max(loads) - min(loads)


def choose_server_id(hostname: str) -> int:
    used_ids = set(replicas.values())
    best_id = None
    best_score = None

    # Try several IDs and keep the one that produces the most even ring layout
    for _ in range(300):
        candidate = random.randint(100000, 999999)
        if candidate in used_ids:
            continue
        ring.add_server(hostname, candidate)
        score = ring_balance_score()
        ring.remove_server(hostname)
        if best_score is None or score < best_score:
            best_id = candidate
            best_score = score

    if best_id is not None:
        return best_id

    while True:
        server_id = random.randint(100000, 999999)
        if server_id not in used_ids:
            return server_id


def create_container(hostname: str, server_id: int) -> None:
    docker(
        "run",
        "--name",
        hostname,
        "--hostname",
        hostname,
        "--network",
        NETWORK_NAME,
        "--network-alias",
        hostname,
        "-e",
        f"SERVER_ID={server_id}",
        "-d",
        SERVER_IMAGE,
    )


def remove_container(hostname: str) -> None:
    subprocess.run(["docker", "rm", "-f", hostname], capture_output=True, text=True)


def add_replica(hostname: str | None = None) -> str:
    hostname = hostname or random_hostname()
    server_id = choose_server_id(hostname)
    create_container(hostname, server_id)
    replicas[hostname] = server_id
    ring.add_server(hostname, server_id)
    return hostname


def remove_replica(hostname: str) -> None:
    remove_container(hostname)
    replicas.pop(hostname, None)
    ring.remove_server(hostname)


def ensure_initial_replicas() -> None:
    with lock:
        if replicas:
            return
        for index in range(1, INITIAL_REPLICAS + 1):
            add_replica(f"Server{index}")


def refill_replicas() -> None:
    with lock:
        while len(replicas) < desired_replicas:
            add_replica()


def heartbeat_loop() -> None:
    # Continuously replace containers that no longer respond to health checks
    while True:
        time.sleep(HEARTBEAT_INTERVAL)
        dead = []
        with lock:
            names = list(replicas)
        for hostname in names:
            try:
                response = requests.get(f"http://{hostname}:5000/heartbeat", timeout=REQUEST_TIMEOUT)
                if response.status_code != 200:
                    dead.append(hostname)
            except requests.RequestException:
                dead.append(hostname)
        if dead:
            with lock:
                for hostname in dead:
                    if hostname in replicas:
                        remove_replica(hostname)
                refill_replicas()


@app.before_request
def boot_once():
    ensure_initial_replicas()


@app.get("/rep")
def list_replicas():
    with lock:
        names = list(replicas)
    return response_ok({"N": len(names), "replicas": names})


@app.post("/add")
def add_replicas():
    global desired_replicas
    payload = request.get_json(silent=True) or {}
    n = int(payload.get("n", 0))
    hostnames = payload.get("hostnames", [])
    if not isinstance(hostnames, list):
        return response_fail("<Error> hostnames must be a list")
    if len(hostnames) > n:
        return response_fail("<Error> Length of hostname list is more than newly added instances")
    if n < 1:
        return response_fail("<Error> n must be greater than zero")

    with lock:
        if any(name in replicas for name in hostnames):
            return response_fail("<Error> hostname already exists")
        # Fill any unnamed replica slots with unique generated hostnames
        names = list(hostnames)
        while len(names) < n:
            candidate = random_hostname()
            if candidate not in replicas and candidate not in names:
                names.append(candidate)
        try:
            for name in names:
                add_replica(name)
            desired_replicas = len(replicas)
        except Exception as exc:
            return response_fail(f"<Error> Unable to add replica: {exc}", 500)
        return response_ok({"N": len(replicas), "replicas": list(replicas)})


@app.delete("/rm")
def remove_replicas():
    global desired_replicas
    payload = request.get_json(silent=True) or {}
    n = int(payload.get("n", 0))
    hostnames = payload.get("hostnames", [])
    if not isinstance(hostnames, list):
        return response_fail("<Error> hostnames must be a list")
    if len(hostnames) > n:
        return response_fail("<Error> Length of hostname list is more than removable instances")
    if n < 1:
        return response_fail("<Error> n must be greater than zero")

    with lock:
        missing = [name for name in hostnames if name not in replicas]
        if missing:
            return response_fail(f"<Error> Unknown replicas: {missing}")
        removable = list(hostnames)
        candidates = [name for name in replicas if name not in removable]
        while len(removable) < n and candidates:
            chosen = random.choice(candidates)
            candidates.remove(chosen)
            removable.append(chosen)
        if len(removable) < n:
            return response_fail("<Error> Not enough replicas to remove")
        for name in removable:
            remove_replica(name)
        desired_replicas = len(replicas)
        return response_ok({"N": len(replicas), "replicas": list(replicas)})


@app.get("/<path:path>")
def route_request(path):
    with lock:
        if not replicas:
            return response_fail("<Error> No server replicas available", 503)
        # Select an upstream replica from the consistent-hash ring
        record = ring.get_server()
    try:
        upstream = requests.get(f"http://{record.name}:5000/{path}", timeout=REQUEST_TIMEOUT)
    except requests.RequestException:
        with lock:
            if record.name in replicas:
                remove_replica(record.name)
                refill_replicas()
        return response_fail("<Error> Replica unavailable, please retry", 503)

    if upstream.status_code == 404:
        return response_fail(f"<Error> '/{path}' endpoint does not exist in server replicas")
    return upstream.content, upstream.status_code, dict(upstream.headers)


# Run health checks in the background so request handling remains non-blocking
threading.Thread(target=heartbeat_loop, daemon=True).start()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
