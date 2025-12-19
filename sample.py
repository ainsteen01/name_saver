from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import psycopg2
import os
from datetime import date

app = FastAPI()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise Exception("DATABASE_URL is not set")

# Connect once
conn = psycopg2.connect(DATABASE_URL)

# Create table once at startup
with conn.cursor() as cur:
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


class Item(BaseModel):
    date: date
    category: str
    description: str
    amount: float


@app.post("/items")
def insert_item(item: Item):
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO expense (date, category, description, amount)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (item.date, item.category, item.description, item.amount)
            )
            inserted_id = cur.fetchone()[0]
            conn.commit()

        return {
            "status": "inserted",
            "id": inserted_id,
            "item": item.dict()
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/items")
def get_items():
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, date, category, description, amount FROM expense"
            )
            rows = cur.fetchall()

        return [
            {
                "id": r[0],
                "date": r[1],
                "category": r[2],
                "description": r[3],
                "amount": float(r[4])
            }
            for r in rows
        ]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
