from fastapi import FastAPI
from pydantic import BaseModel
import psycopg2
import os
from datetime import date

app = FastAPI()

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL is None:
    raise Exception("DATABASE_URL is not set")

# Connect to Supabase Pooler
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

# Ensure table exists without 'name'
cur.execute("""
CREATE TABLE IF NOT EXISTS expense (
    id SERIAL PRIMARY KEY,
    date DATE,
    category TEXT,
    description TEXT,
    amount NUMERIC
)
""")
conn.commit()

# Pydantic model for request body without 'name'
class Item(BaseModel):
    date: date
    category: str
    description: str
    amount: float

@app.post("/items")
def insert_item(item: Item):
    cur.execute(
        """
        INSERT INTO expense (date, category, description, amount)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (item.date, item.category, item.description, item.amount)
    )
    conn.commit()
    inserted_id = cur.fetchone()[0]
    return {"status": "inserted", "id": inserted_id, "item": item.dict()}



@app.get("/items")
def get_items():
    cur.execute("SELECT id, date, category, description, amount FROM expense")
    rows = cur.fetchall()
    result = [
        {
            "id": r[0],
            "date": r[1],
            "category": r[2],
            "description": r[3],
            "amount": float(r[4])
        } 
        for r in rows
    ]
    return result

