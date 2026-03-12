import sqlite3

conn = sqlite3.connect(r'C:\Users\verti\projects\signalweaver\data\signalweaver.db')
cur = conn.cursor()

cur.execute("ALTER TABLE policy_profiles ADD COLUMN enforcement_mode TEXT NOT NULL DEFAULT 'hard'")
cur.execute("ALTER TABLE decision_traces ADD COLUMN would_block INTEGER NOT NULL DEFAULT 0")
cur.execute("ALTER TABLE decision_traces ADD COLUMN enforcement_mode_snapshot TEXT NOT NULL DEFAULT 'hard'")
cur.execute("ALTER TABLE decision_traces ADD COLUMN override_reason TEXT NOT NULL DEFAULT ''")

conn.commit()
conn.close()
print('migration OK')