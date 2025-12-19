from fastapi import FastAPI
import psycopg2
import os

app = FastAPI()

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL is None:
    raise Exception("DATABASE_URL is not set")

# Connect to Supabase Pooler
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

# Ensure table exists
cur.execute("""
CREATE TABLE IF NOT EXISTS items (
    id SERIAL PRIMARY KEY,
    name TEXT
)
""")
conn.commit()

@app.post("/items")
def insert_item(name: str):
    cur.execute("INSERT INTO items (name) VALUES (%s) RETURNING id", (name,))
    conn.commit()
    inserted_id = cur.fetchone()[0]
    return {"status": "inserted", "id": inserted_id, "name": name}

@app.get("/items")
def get_items():
    cur.execute("SELECT id, name FROM items")
    return cur.fetchall()
