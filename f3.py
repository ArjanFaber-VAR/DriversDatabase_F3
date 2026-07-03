import asyncio
import hashlib
import re
from datetime import datetime

import pandas as pd
import psycopg2
from playwright.async_api import async_playwright

URL = "https://www.fiaformula3.com/livetiming/index.html"


def make_hash(text: str) -> str:
    normalized = " ".join(text.split())
    return hashlib.md5(normalized.encode()).hexdigest()


async def run():
    snapshots = []

    print("Launching browser...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            slow_mo=100
        )

        page = await browser.new_page()

        print("Going to page...")
        await page.goto(URL, timeout=60000)

        print("Page loaded")
        await page.wait_for_timeout(5000)

        print("Starting scraping loop...")

        last_hash = None

        for i in range(1):
            text = await page.evaluate("document.body.innerText")
            current_hash = make_hash(text)

            print(f"\nSNAPSHOT {i}")

            if current_hash != last_hash:
                print("✔ Change detected → storing snapshot")

                snapshots.append({
                    "timestamp": datetime.utcnow().isoformat(),
                    "raw_text": text
                })

                last_hash = current_hash
            else:
                print("⏭ No change → skipped")

            await asyncio.sleep(2)

        await browser.close()

    print(f"\nCollected {len(snapshots)} unique snapshots")

    pattern = re.compile(
        r'(\d+)\s+'                      # position
        r'(\d+)\s+'                      # car number
        r'([A-Z]\.[A-Z ]+)\s+'           # driver name
        r'([A-Z0-9\.L]+)\s+'             # gap
        r'([A-Z0-9\.L]+)\s+'             # interval
        r'((?:\d:\d{2}\.\d+)|STOP)\s+'   # lap time
        r'([0-9\.]+|STOP)\s+'
        r'([0-9\.]+|STOP)\s+'
        r'([0-9\.]+)?\s*'
        r'(\d+)?'
    )

    rows = []

    for snapshot in snapshots:
        timestamp = snapshot["timestamp"]
        raw_text = snapshot["raw_text"]

        for match in pattern.finditer(raw_text):
            rows.append({
                "timestamp": timestamp,
                "position": int(match.group(1)),
                "car_number": int(match.group(2)),
                "driver": match.group(3).strip(),
                "gap": match.group(4),
                "interval": match.group(5),
                "lap_time": match.group(6),
                "sector1": match.group(7),
                "sector2": match.group(8),
                "sector3": match.group(9),
                "pit_stops": match.group(10)
            })

    laps_df = pd.DataFrame(rows)

    print(f"Parsed {len(laps_df)} lap records")

    if laps_df.empty:
        print("No lap data found.")
        return

    conn = psycopg2.connect(
        host="ep-long-glitter-at9v26w9-pooler.c-9.us-east-1.aws.neon.tech",
        database="neondb",
        user="neondb_owner",
        password="npg_P6OimSTt9ngC",
        port=5432,
        sslmode="require"
    )

    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS f3_laps (
        timestamp TEXT,
        position INT,
        car_number INT,
        driver TEXT,
        gap TEXT,
        interval TEXT,
        lap_time TEXT,
        sector1 TEXT,
        sector2 TEXT,
        sector3 TEXT,
        pit_stops TEXT
    )
    """)

    conn.commit()

    insert_query = """
    INSERT INTO f3_laps (
        timestamp,
        position,
        car_number,
        driver,
        gap,
        interval,
        lap_time,
        sector1,
        sector2,
        sector3,
        pit_stops
    )
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """

    cur.executemany(
        insert_query,
        laps_df.values.tolist()
    )

    conn.commit()

    print("Inserted rows into PostgreSQL")
    print("DONE")
    delete_query = """
DELETE FROM f3_laps
WHERE
    sector1 IS NULL OR sector1 = '' OR sector1 = 'STOP'
    OR sector2 IS NULL OR sector2 = '' OR sector2 = 'STOP'
    OR sector3 IS NULL OR sector3 = '' OR sector3 = 'STOP'
"""

    cur.execute(delete_query)
    conn.commit()

    cur.close()
    conn.close()

    print("Deleted incomplete rows into PostgreSQL")
    print("DONE")


asyncio.run(run())
