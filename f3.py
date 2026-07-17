import asyncio
from datetime import datetime

import pandas as pd
import psycopg2
from playwright.async_api import async_playwright

URL = "https://www.fiaformula3.com/livetiming/index.html"


def clean(text):
    return text.strip().replace("\n", " ")


async def extract_table_rows(page):
    """
    Extract structured table rows directly from DOM instead of innerText.
    """
    rows_data = []

    rows = await page.query_selector_all("table tbody tr")

    for row in rows:
        cols = await row.query_selector_all("td")
        values = [clean(await c.inner_text()) for c in cols]

        # Skip empty or malformed rows
        if len(values) < 6:
            continue

        rows_data.append(values)

    return rows_data


async def run():
    snapshots = []

    print("Launching browser...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print("Opening page...")
        await page.goto(URL, timeout=60000)

        # wait for live timing table to load
        await page.wait_for_timeout(8000)

        print("Starting collection loop...")

        for i in range(10):
            rows = await extract_table_rows(page)

            print(f"\nSnapshot {i} -> {len(rows)} rows")

            snapshots.append({
                "timestamp": datetime.utcnow().isoformat(),
                "rows": rows
            })

            await asyncio.sleep(2)

        await browser.close()

    print(f"\nCollected {len(snapshots)} snapshots")

    # ---------------------------
    # Convert to structured DataFrame
    # ---------------------------

    parsed_rows = []

    for snap in snapshots:
        ts = snap["timestamp"]

        for r in snap["rows"]:
            try:
                parsed_rows.append({
                    "timestamp": ts,
                    "position": r[0],
                    "car_number": r[1],
                    "driver": r[2],
                    "gap": r[3] if len(r) > 3 else None,
                    "interval": r[4] if len(r) > 4 else None,
                    "lap_time": r[5] if len(r) > 5 else None,
                    "sector1": r[6] if len(r) > 6 else None,
                    "sector2": r[7] if len(r) > 7 else None,
                    "sector3": r[8] if len(r) > 8 else None,
                    "extra": r[9] if len(r) > 9 else None,
                })
            except Exception:
                continue

    df = pd.DataFrame(parsed_rows)

    print(f"Parsed {len(df)} rows")

    if df.empty:
        print("No data found.")
        return

    # ---------------------------
    # DB connection (use env vars in real usage)
    # ---------------------------

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
        position TEXT,
        car_number TEXT,
        driver TEXT,
        gap TEXT,
        interval TEXT,
        lap_time TEXT,
        sector1 TEXT,
        sector2 TEXT,
        sector3 TEXT,
        extra TEXT
    )
    """)

    conn.commit()

    insert_query = """
    INSERT INTO f3_laps (
        timestamp, position, car_number, driver,
        gap, interval, lap_time,
        sector1, sector2, sector3, extra
    )
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """

    cur.executemany(insert_query, df.values.tolist())

    conn.commit()

    print("Inserted rows into PostgreSQL")

    # Optional cleanup
    cur.execute("""
    DELETE FROM f3_laps
    WHERE lap_time IS NULL OR lap_time = ''
    """)

    # Remove rows with missing lap times
    cur.execute("""
    DELETE FROM f3_laps
    WHERE lap_time IS NULL OR lap_time = '';
    """)

    # Remove duplicate rows (keeps one copy)
    cur.execute("""
DELETE FROM f3_laps a
USING f3_laps b
WHERE a.ctid < b.ctid
  AND a.position IS NOT DISTINCT FROM b.position
  AND a.car_number IS NOT DISTINCT FROM b.car_number
  AND a.driver IS NOT DISTINCT FROM b.driver
  AND a.gap IS NOT DISTINCT FROM b.gap
  AND a.interval IS NOT DISTINCT FROM b.interval
  AND a.lap_time IS NOT DISTINCT FROM b.lap_time
  AND a.sector1 IS NOT DISTINCT FROM b.sector1
  AND a.sector2 IS NOT DISTINCT FROM b.sector2
  AND a.sector3 IS NOT DISTINCT FROM b.sector3
  AND a.extra IS NOT DISTINCT FROM b.extra;
""")

    print(f"Deleted {cur.rowcount} duplicate rows.")



    conn.commit()

    cur.close()
    conn.close()

    print("Done.")


asyncio.run(run())
