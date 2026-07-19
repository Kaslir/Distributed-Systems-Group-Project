import subprocess
import time
import re
import csv
import matplotlib.pyplot as plt

RESULTS = []

BASE_URL = "http://localhost:5000"


def run(cmd):
    return subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True
    )


def set_replicas(target):

    # Read the current cluster size before adding or removing only the difference

    rep = run(
        'powershell Invoke-RestMethod -Method Get -Uri "http://localhost:5000/rep"'
    )

    current = int(re.search(r"N=(\d+)", rep.stdout).group(1))

    if current < target:

        add = target-current

        run(
            f'''powershell Invoke-RestMethod -Method Post -Uri "{BASE_URL}/add" -ContentType "application/json" -Body '{{"n":{add},"hostnames":[]}}' '''
        )

    elif current > target:

        rm = current-target

        run(
            f'''powershell Invoke-RestMethod -Method Delete -Uri "{BASE_URL}/rm" -ContentType "application/json" -Body '{{"n":{rm},"hostnames":[]}}' '''
        )

    time.sleep(2)


for n in range(2,7):

    print(f"\nTesting N={n}")

    set_replicas(n)

    # Issue a fixed workload so average request load can be compared per replica count
    result = run(
        "python scripts/async_requests.py --requests 10000"
    )

    print(result.stdout)

    counts = []

    for line in result.stdout.splitlines():

        m = re.search(r": (\d+)$", line)

        if m:

            counts.append(int(m.group(1)))

    average = sum(counts)/len(counts)

    RESULTS.append([n, average])


# Persist the measured averages for later analysis or charting
with open("A2_results.csv","w",newline="") as f:

    writer=csv.writer(f)

    writer.writerow(["Replicas","Average Load"])

    writer.writerows(RESULTS)

x=[r[0] for r in RESULTS]

y=[r[1] for r in RESULTS]

plt.figure(figsize=(7,5))

plt.plot(x,y,marker="o")

plt.title("Average Load vs Number of Replicas")

plt.xlabel("Number of Replicas")

plt.ylabel("Average Requests per Server")

plt.grid()

plt.savefig("A2_LineChart.png")

plt.show()

print("\nDone!")
