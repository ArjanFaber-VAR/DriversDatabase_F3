import asyncio
from datetime import datetime

import psycopg2
from playwright.async_api import async_playwright

URL = "https://www.fiaformula3.com/livetiming/index.html"


def clean(text):
    return text.strip().replace("\n", " ")


def row_key(row):
    # unique identity for a driver
    return row[1]  # car_number is stable identifier


async def extract_rows(page):
    rows = []

    elements = await page.query_selector_all("table tbody tr")

    for el in elements:
        cols = await el.query_selector_all("td")
        values = [clean(await c.inner_text()) for c in cols]

        if len(values) < 6:
            continue

        rows.append(values)

    return rows


async def run():
    print("Starting...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.goto(URL, timeout=60000)
        await page.wait_for_timeout(8000)

        print("Page ready")

        last_state = {}   # car_number -> row
        changes = []      # only changed rows

        for i in range(10):
            print(f"\nSnapshot {i}")

            rows = await extract_rows(page)

            for r in rows:
                if len(r) < 6:
                    continue

                key = row_key(r)

                current = {
                    "position": r[0],
                    "car_number": r[1],
                    "driver": r[2],
                    "gap": r[3] if len(r) > 3 else None,
                    "interval": r[4] if len(r) > 4 else None,
                    "lap_time": r[5] if len(r) > 5 else None,
                    "sector1": r[6] if len(r) > 6 else None,
                    "sector2": r[7] if len(r) > 7 else None,
                    "sector3": r[8] if len(r) > 8 else None,
                    "timestamp": datetime.utcnow().isoformat()
                }

                # detect change
                if key not in last_state or last_state[key] != current:
                    changes.append(current)
                    last_state[key] = current

                    print(f"✔ Change detected: {key}")

            await asyncio.sleep(2)

        await browser.close()

    print(f"\nTotal changed rows: {len(changes)}")

    # ---------------- DB ----------------

    conn = psycopg2.connect(
        host="YOUR_HOST",
        database="YOUR_DB",
        user="YOUR_USER",
        password="YOUR_PASSWORD",
        port=5432,
        sslmode="require"
    )

    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS f3_laps_changes (
        timestamp TEXT,
        position TEXT,
        car_number TEXT,
        driver TEXT,
        gap TEXT,
        interval TEXT,
        lap_time TEXT,
        sector1 TEXT,
        sector2 TEXT,
        sector3 TEXT
    )
    """)

    conn.commit()

    insert_query = """
    INSERT INTO f3_laps_changes (
        timestamp, position, car_number, driver,
        gap, interval, lap_time,
        sector1, sector2, sector3
    )
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """

    cur.executemany(
        insert_query,
        [
            (
                r["timestamp"],
                r["position"],
                r["car_number"],
                r["driver"],
                r["gap"],
                r["interval"],
                r["lap_time"],
                r["sector1"],
                r["sector2"],
                r["sector3"],
            )
            for r in changes
        ]
    )

    conn.commit()

    cur.close()
    conn.close()

    print("Inserted only changed rows.")
