"""
Migration: add tenant_id to truth_anchors table.
Safe to run multiple times — skips if column already exists.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from app.db import engine
from sqlalchemy import text

with engine.connect() as conn:
    # Check if column already exists
    result = conn.execute(text("PRAGMA table_info(truth_anchors)"))
    columns = [row[1] for row in result.fetchall()]

    if "tenant_id" in columns:
        print("tenant_id already exists — nothing to do.")
    else:
        conn.execute(text("ALTER TABLE truth_anchors ADD COLUMN tenant_id INTEGER REFERENCES tenants(id)"))
        conn.commit()
        print("tenant_id added to truth_anchors.")