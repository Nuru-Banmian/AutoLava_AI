"""Create a disposable pre-identity-migration SQLite snapshot inside the image."""

import os
import sqlite3

import bcrypt

with sqlite3.connect(os.environ["AUTOLAVA_DATABASE_PATH"]) as db:
    password_hash = bcrypt.hashpw(
        os.environ["AUTOLAVA_BOOTSTRAP_PASSWORD"].encode(), bcrypt.gensalt()
    ).decode()
    db.execute(
        "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, ?)",
        (os.environ["AUTOLAVA_BOOTSTRAP_USERNAME"], password_hash, "admin", 1),
    )
    db.execute(
        "INSERT INTO stores (name, address, latitude, longitude, timezone, is_active, income_items_enabled) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("Legacy Store", "Old address", 45, 9, "Europe/Rome", 1, 1),
    )
    db.execute("INSERT INTO store_members (store_id, user_id) VALUES (1, 1)")
    db.execute(
        "INSERT INTO income_categories (store_id, name, include_in_total, is_active, sort_order) VALUES (1, 'Old category', 1, 1, 0)"
    )
    db.execute(
        "INSERT INTO store_daily_records (store_id, date, daily_revenue, income_mode, is_open, weather, weather_edited, scanned, created_by, updated_by) VALUES (1, '2026-07-28', 940, 'composed', '营业', '旧版任意天气', 0, 0, 1, 1)"
    )
    db.execute(
        "INSERT INTO daily_income_items (record_id, category_id, category_name, include_in_total, sort_order, amount) VALUES (1, 1, 'Old category', 1, 0, 940)"
    )
