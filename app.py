import os, time
print("App booted.")
print("KIRI_ENV =", os.getenv("KIRI_ENV", "unset"))
while True:
    print("heartbeat...", "KIRI_ENV =", os.getenv("KIRI_ENV", "unset"))
    time.sleep(30)
