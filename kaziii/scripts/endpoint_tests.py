import requests


BASE_URL = "http://localhost:5000"


def show(method, path, **kwargs):
    # Send one test request and print its status and body for quick inspection
    response = requests.request(method, f"{BASE_URL}{path}", timeout=5, **kwargs)
    print(method, path, response.status_code, response.text)


def main():
    # Exercise replica management followed by normal and invalid routed endpoints
    show("GET", "/rep")
    show("POST", "/add", json={"n": 2, "hostnames": ["S5", "S4"]})
    show("GET", "/rep")
    show("DELETE", "/rm", json={"n": 1, "hostnames": ["S5"]})
    show("GET", "/home")
    show("GET", "/other")


if __name__ == "__main__":
    main()
