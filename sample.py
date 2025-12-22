from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import psycopg2
from psycopg2 import pool, OperationalError
import os
from datetime import date
from contextlib import contextmanager
from typing import List

app = FastAPI()

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL is None:
    raise Exception("DATABASE_URL is not set")

# Create connection pool
connection_pool = None

@app.on_event("startup")
async def startup():
    """Initialize connection pool on startup"""
    global connection_pool
    try:
        connection_pool = pool.SimpleConnectionPool(
            1,  # min connections
            10, # max connections
            dsn=DATABASE_URL
        )
        # Test connection
        conn = connection_pool.getconn()
        cur = conn.cursor()
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
        connection_pool.putconn(conn)
        print("Database connection pool initialized successfully")
    except Exception as e:
        print(f"Failed to initialize connection pool: {e}")
        raise

@app.on_event("shutdown")
async def shutdown():
    """Close connection pool on shutdown"""
    if connection_pool:
        connection_pool.closeall()
        print("Connection pool closed")

@contextmanager
def get_db_cursor():
    """Context manager for database connections"""
    conn = None
    try:
        conn = connection_pool.getconn()
        cur = conn.cursor()
        yield cur
        conn.commit()
    except OperationalError as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    finally:
        if conn:
            cur.close()
            connection_pool.putconn(conn)

# Pydantic model
class Item(BaseModel):
    date: date
    category: str
    description: str
    amount: float

@app.post("/items")
def insert_item(item: Item):
    """Insert a new expense item"""
    with get_db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO expense (date, category, description, amount)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (item.date, item.category, item.description, item.amount)
        )
        inserted_id = cur.fetchone()[0]
        return {"status": "inserted", "id": inserted_id, "item": item.dict()}

@app.get("/items")
def get_items():
    """Get all expense items"""
    with get_db_cursor() as cur:
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

# Additional endpoints for better functionality
@app.get("/items/{item_id}")
def get_item(item_id: int):
    """Get a specific expense item by ID"""
    with get_db_cursor() as cur:
        cur.execute(
            "SELECT id, date, category, description, amount FROM expense WHERE id = %s",
            (item_id,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Item not found")
        return {
            "id": row[0],
            "date": row[1],
            "category": row[2],
            "description": row[3],
            "amount": float(row[4])
        }

@app.delete("/items/{item_id}")
def delete_item(item_id: int):
    """Delete an expense item"""
    with get_db_cursor() as cur:
        cur.execute("DELETE FROM expense WHERE id = %s RETURNING id", (item_id,))
        deleted_row = cur.fetchone()
        if not deleted_row:
            raise HTTPException(status_code=404, detail="Item not found")
        return {"status": "deleted", "id": item_id}



@app.put("/items/{item_id}")
def replace_item(item_id: int, item: Item):
    """Replace an entire expense item"""
    with get_db_cursor() as cur:
        cur.execute(
            """
            UPDATE expense 
            SET date = %s, category = %s, description = %s, amount = %s
            WHERE id = %s
            RETURNING id, date, category, description, amount
            """,
            (item.date, item.category, item.description, item.amount, item_id)
        )
        row = cur.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Item not found")
        
        return {
            "status": "replaced",
            "id": row[0],
            "date": row[1],
            "category": row[2],
            "description": row[3],
            "amount": float(row[4])
        }
# Health check endpoint
@app.get("/health")
def health_check():
    """Check if the API and database are healthy"""
    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT 1")
            return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": "disconnected", "error": str(e)}
