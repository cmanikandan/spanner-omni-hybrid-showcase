#!/usr/bin/env python3
"""Automated High-Resolution Screenshot Capture for Spanner Omni Hybrid Multi-Cloud Showcase.
Uses Selenium with Headless Chrome to capture real screenshots of all major use cases.
"""

import time
import os
import sys
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "blog" / "images"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

def create_driver(width=1440, height=900):
    options = Options()
    if os.path.exists(CHROME_PATH):
        options.binary_location = CHROME_PATH
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--window-size={width},{height}")
    options.add_argument("--force-device-scale-factor=1.5")
    options.add_argument("--hide-scrollbars")
    
    driver = webdriver.Chrome(options=options)
    return driver

def capture_dashboard_scenarios():
    print("[*] Starting Selenium WebDriver for Dashboard screenshots...")
    driver = create_driver(width=1440, height=900)
    
    try:
        # Reset chaos links first via API
        import urllib.request
        try:
            req = urllib.request.Request("http://127.0.0.1:8080/api/chaos/heal", data=b"{}", headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=3)
        except Exception as e:
            print(f"[-] Heal reset warning: {e}")

        # -------------------------------------------------------------
        # Screenshot 1: Multi-Cloud Topology & TrueTime Clock Sources
        # -------------------------------------------------------------
        print("[*] Capturing Screenshot 1: Multi-Cloud Topology & Sync Status...")
        driver.set_window_size(1440, 960)
        driver.get("http://127.0.0.1:8080/")
        time.sleep(3)  # Wait for initial WebSocket / fetch
        shot1 = OUTPUT_DIR / "screenshot_01_multi_cloud_topology.png"
        driver.save_screenshot(str(shot1))
        print(f"[+] Saved: {shot1} ({shot1.stat().st_size} bytes)")

        # -------------------------------------------------------------
        # Screenshot 2: PayMesh Financial Ledger & Cross-Cloud Propagation
        # -------------------------------------------------------------
        print("[*] Capturing Screenshot 2: PayMesh Cross-Cloud Financial Ledger...")
        driver.set_window_size(1440, 900)
        driver.execute_script("window.scrollTo(0, 520);")
        time.sleep(1)
        shot2 = OUTPUT_DIR / "screenshot_02_paymesh_cross_cloud_transfers.png"
        driver.save_screenshot(str(shot2))
        print(f"[+] Saved: {shot2} ({shot2.stat().st_size} bytes)")

        # -------------------------------------------------------------
        # Screenshot 3: OmniRetail Vector Similarity & Check Constraints
        # -------------------------------------------------------------
        print("[*] Capturing Screenshot 3: OmniRetail Vector Search & Catalog...")
        driver.set_window_size(1440, 950)
        driver.execute_script("window.scrollTo(0, 1150);")
        time.sleep(1)
        shot3 = OUTPUT_DIR / "screenshot_03_omniretail_vector_search_catalog.png"
        driver.save_screenshot(str(shot3))
        print(f"[+] Saved: {shot3} ({shot3.stat().st_size} bytes)")

        # -------------------------------------------------------------
        # Screenshot 4: Network Chaos & Simulated Multi-Cloud Partition
        # -------------------------------------------------------------
        print("[*] Triggering Partition & Capturing Screenshot 4: Chaos Mode...")
        try:
            req = urllib.request.Request("http://127.0.0.1:8080/api/chaos/isolate/gcp", data=b"{}", headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=3)
            # Submit partitioned order to induce divergence
            order_req = urllib.request.Request(
                "http://127.0.0.1:8080/api/site/laptop/checkout",
                data=b'{"customer_id":"cust-asha","product_id":"p1","quantity":3}',
                headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(order_req, timeout=3)
        except Exception as e:
            print(f"[-] Partition trigger warning: {e}")

        driver.get("http://127.0.0.1:8080/")
        time.sleep(2)
        driver.set_window_size(1440, 960)
        driver.execute_script("window.scrollTo(0, 0);")
        shot4 = OUTPUT_DIR / "screenshot_04_chaos_network_partition.png"
        driver.save_screenshot(str(shot4))
        print(f"[+] Saved: {shot4} ({shot4.stat().st_size} bytes)")

        # -------------------------------------------------------------
        # Screenshot 5: 4-Phase TrueTime Anti-Entropy Reconciliation
        # -------------------------------------------------------------
        print("[*] Triggering Reconciliation & Capturing Screenshot 5: Reconciliation Report...")
        try:
            req = urllib.request.Request("http://127.0.0.1:8080/api/demo/guided-recon", data=b"{}", headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            print(f"[-] Recon trigger warning: {e}")

        driver.get("http://127.0.0.1:8080/")
        time.sleep(2)
        driver.set_window_size(1440, 1020)
        driver.execute_script("window.scrollTo(0, 400);")
        shot5 = OUTPUT_DIR / "screenshot_05_truetime_reconciliation.png"
        driver.save_screenshot(str(shot5))
        print(f"[+] Saved: {shot5} ({shot5.stat().st_size} bytes)")

    finally:
        driver.quit()

def capture_spanner_console():
    print("[*] Capturing Screenshot 6: Native Google Spanner Omni Web Console (Port 15026)...")
    driver = create_driver(width=1440, height=900)
    try:
        driver.get("http://127.0.0.1:15026/")
        time.sleep(4)  # Wait for Angular components
        shot6 = OUTPUT_DIR / "screenshot_06_spanner_omni_web_console.png"
        driver.save_screenshot(str(shot6))
        print(f"[+] Saved: {shot6} ({shot6.stat().st_size} bytes)")
    finally:
        driver.quit()

if __name__ == "__main__":
    capture_dashboard_scenarios()
    capture_spanner_console()
    print("[✓] All 6 screenshots successfully captured!")
