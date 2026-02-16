from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import psycopg2
from psycopg2 import pool, OperationalError
import os
import requests
import json
import re  # ADD THIS
from datetime import date, datetime, timedelta  # FIXED: Add datetime
from contextlib import contextmanager
from typing import Optional, Dict, Any, List
from enum import Enum

# Add environment variables for AI configuration
AI_API_URL = os.getenv("AI_API_URL", "https://openrouter.ai/api/v1/chat/completions")
AI_API_KEY = os.getenv("AI_API_KEY", "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")
AI_MODEL = os.getenv("AI_MODEL", "deepseek/deepseek-chat-v3-0324")
AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "30"))

app = FastAPI()

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL is None:
    raise Exception("DATABASE_URL is not set")

# Create connection pool
connection_pool = None

class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"

class UserBase(BaseModel):
    name: str
    mobile: str
    role: UserRole = UserRole.USER

class UserCreate(UserBase):
    pass

class UserResponse(UserBase):
    id: int
    
    class Config:
        from_attributes = True

class Item(BaseModel):
    date: date
    category: str
    description: str
    amount: float

class ItemCreate(Item):
    user_id: int

class ItemResponse(Item):
    id: int
    user_id: int
    
    class Config:
        from_attributes = True

# Fixed: Simplified AI response models
class FinancialInsights(BaseModel):
    analysis: Optional[str] = None
    spending_patterns: Optional[str] = None
    top_categories: Optional[List[Dict[str, Any]]] = None
    unusual_patterns: Optional[str] = None
    budgeting_recommendations: Optional[List[str]] = None
    savings_opportunities: Optional[List[str]] = None

class AIAnalysisResponse(BaseModel):
    success: bool
    analysis: Optional[str] = None
    insights: Optional[FinancialInsights] = None
    error: Optional[str] = None
    expense_summary: Optional[Dict[str, Any]] = None


class AIService:
    def __init__(self):
        self.api_url = AI_API_URL
        self.api_key = AI_API_KEY
        self.model = AI_MODEL
        self.timeout = AI_TIMEOUT
    
    def analyze_expenses(self, expense_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send expense data to OpenRouter AI for analysis
        """
        try:
            # Create a comprehensive prompt for financial analysis
            prompt = self._create_financial_prompt(expense_data)
            
            # Prepare the request payload
            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": """You are a financial advisor analyzing expense data. 
                        Provide detailed, actionable insights in a structured format.
                        Focus on: spending patterns, category breakdown, unusual expenses,
                        budgeting recommendations, and savings opportunities.
                        
                        Format your response as a JSON object with these keys:
                        {
                            "analysis": "Brief overall analysis",
                            "spending_patterns": "Describe patterns in spending behavior",
                            "top_categories": [{"category": "name", "percentage": 0.0, "insight": "description"}],
                            "unusual_patterns": "Any unusual spending patterns noticed",
                            "budgeting_recommendations": ["recommendation1", "recommendation2"],
                            "savings_opportunities": ["opportunity1", "opportunity2"]
                        }"""
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.7,
                "max_tokens": 1000
            }
            
            # Make the API call
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:8000",  # Your site URL
                "X-Title": "Expense Tracker AI"
            }
            
            response = requests.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                ai_response = response.json()
                
                # Extract and parse AI's response
                ai_content = ai_response["choices"][0]["message"]["content"]
                
                # Try to parse JSON from AI response
                try:
                    # Look for JSON in the response
                    json_match = re.search(r'\{.*\}', ai_content, re.DOTALL)
                    if json_match:
                        insights_json = json.loads(json_match.group())
                    else:
                        insights_json = {"analysis": ai_content}
                except json.JSONDecodeError:
                    insights_json = {"analysis": ai_content}
                
                return {
                    "success": True,
                    "ai_raw_response": ai_response,
                    "insights": insights_json,
                    "usage": ai_response.get("usage", {})
                }
            else:
                return {
                    "success": False,
                    "error": f"AI API returned status {response.status_code}: {response.text[:200]}",
                    "status_code": response.status_code
                }
                
        except requests.exceptions.Timeout:
            return {
                "success": False,
                "error": "AI API request timed out"
            }
        except requests.exceptions.ConnectionError:
            return {
                "success": False,
                "error": "Failed to connect to AI API"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"AI API call failed: {str(e)}"
            }
    
    def _create_financial_prompt(self, expense_data: Dict[str, Any]) -> str:
        """Create a detailed prompt for financial analysis"""
        
        user_info = expense_data.get("user_info", {})
        summary = expense_data.get("summary", {})
        categories = expense_data.get("category_breakdown", [])
        transactions = expense_data.get("transactions", [])
        
        # Format categories for the prompt
        categories_text = "\n".join([
            f"- {cat['category']}: ₹{cat['total_amount']:,.2f} ({cat['percentage_of_total']:.1f}%)"
            for cat in categories[:10]  # Top 10 categories
        ])
        
        # Format recent transactions
        recent_transactions = "\n".join([
            f"- {t['date']}: ₹{t['amount']:,.2f} for {t['category']} - {t['description']}"
            for t in transactions[:10]  # Recent 10 transactions
        ])
        
        prompt = f"""
        EXPENSE ANALYSIS REQUEST
        
        User: {user_info.get('name', 'Unknown')} ({user_info.get('mobile', 'N/A')})
        Period: {expense_data.get('date_range', {}).get('start_date', 'N/A')} to {expense_data.get('date_range', {}).get('end_date', 'N/A')}
        
        SUMMARY:
        - Total Transactions: {summary.get('total_transactions', 0)}
        - Total Amount: ₹{summary.get('total_amount', 0):,.2f}
        - Average Transaction: ₹{summary.get('average_transaction_amount', 0):,.2f}
        
        CATEGORY BREAKDOWN:
        {categories_text if categories_text else "No categories found"}
        
        RECENT TRANSACTIONS:
        {recent_transactions if recent_transactions else "No transactions found"}
        
        Please analyze this expense data and provide:
        1. Overall spending patterns and habits
        2. Top spending categories with insights
        3. Any unusual or concerning patterns
        4. Specific budgeting recommendations
        5. Potential savings opportunities
        
        Provide response in JSON format as specified.
        """
        
        return prompt


# Initialize AI Service
ai_service = AIService()

def _get_expense_data_from_db(mobile: str, start_date: date, end_date: date) -> Optional[Dict[str, Any]]:
    """Helper function to fetch expense data from database - SIMPLIFIED VERSION"""
    with get_db_cursor() as cur:
        try:
            # Get user details
            cur.execute("SELECT id, name FROM users WHERE mobile = %s", (mobile,))
            user_row = cur.fetchone()
            
            if not user_row:
                print(f"DEBUG: User with mobile {mobile} not found")
                return None
            
            user_id = user_row[0]
            user_name = user_row[1]
            print(f"DEBUG: Found user: {user_name} (ID: {user_id})")
            
            # SIMPLIFIED: Query without created_at to avoid syntax errors
            cur.execute(
                """
                SELECT 
                    id,
                    date,
                    category,
                    description,
                    amount
                FROM expense 
                WHERE user_id = %s AND date BETWEEN %s AND %s
                ORDER BY date DESC, id DESC
                """,
                (user_id, start_date, end_date)
            )
            
            transactions = cur.fetchall()
            print(f"DEBUG: Found {len(transactions)} transactions")
            
            # Get summary statistics
            cur.execute(
                """
                SELECT 
                    COUNT(*) as transaction_count,
                    COALESCE(SUM(amount), 0) as total_amount,
                    MIN(date) as earliest_date,
                    MAX(date) as latest_date
                FROM expense 
                WHERE user_id = %s AND date BETWEEN %s AND %s
                """,
                (user_id, start_date, end_date)
            )
            
            summary = cur.fetchone()
            print(f"DEBUG: Summary - count: {summary[0]}, amount: {summary[1]}")
            
            if summary[0] == 0:  # No transactions
                print(f"DEBUG: No transactions found for user {user_id} in date range")
                return None
            
            # Get category distribution
            cur.execute(
                """
                SELECT 
                    category,
                    COUNT(*) as count,
                    SUM(amount) as category_total
                FROM expense 
                WHERE user_id = %s AND date BETWEEN %s AND %s
                GROUP BY category
                ORDER BY category_total DESC
                """,
                (user_id, start_date, end_date)
            )
            
            categories = cur.fetchall()
            
            # Calculate percentages
            total_amount = float(summary[1])
            category_breakdown = []
            for cat in categories:
                cat_amount = float(cat[2])
                percentage = (cat_amount / total_amount * 100) if total_amount > 0 else 0
                category_breakdown.append({
                    "category": cat[0],
                    "transaction_count": cat[1],
                    "total_amount": cat_amount,
                    "percentage_of_total": round(percentage, 2)
                })
            
            # Format transactions
            formatted_transactions = []
            for t in transactions:
                formatted_transactions.append({
                    "transaction_id": t[0],
                    "date": t[1].isoformat(),
                    "category": t[2],
                    "description": t[3] if t[3] else "No description",
                    "amount": float(t[4])
                })
            
            return {
                "user_info": {
                    "user_id": user_id,
                    "name": user_name,
                    "mobile": mobile
                },
                "date_range": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "days_in_range": (end_date - start_date).days + 1
                },
                "summary": {
                    "total_transactions": summary[0],
                    "total_amount": total_amount,
                    "average_transaction_amount": total_amount / summary[0] if summary[0] > 0 else 0,
                    "earliest_date": summary[2].isoformat() if summary[2] else None,
                    "latest_date": summary[3].isoformat() if summary[3] else None
                },
                "category_breakdown": category_breakdown,
                "transactions": formatted_transactions
            }
            
        except Exception as e:
            print(f"ERROR in _get_expense_data_from_db: {str(e)}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            raise

@app.get("/items/ai-analysis/{mobile}/{start_date}/{end_date}", response_model=AIAnalysisResponse)
def get_ai_analysis(mobile: str, start_date: date, end_date: date):
    """
    Get expense data, analyze with AI, and return combined insights
    Complete automated pipeline: Database → AI API → User
    """
    # Validate date range
    if start_date > end_date:
        raise HTTPException(
            status_code=400, 
            detail="Start date must be before or equal to end date"
        )
    
    try:
        # Get expense data from database
        expense_data = _get_expense_data_from_db(mobile, start_date, end_date)
        
        if not expense_data:
            return {
                "success": False,
                "error": "No expense data found for the given criteria",
                "expense_summary": None
            }
        
        # Call AI API for analysis
        ai_result = ai_service.analyze_expenses(expense_data)
        
        if ai_result["success"]:
            # Parse insights from AI response
            insights_data = ai_result.get("insights", {})
            
            # Create structured insights
            insights = FinancialInsights(
                analysis=insights_data.get("analysis"),
                spending_patterns=insights_data.get("spending_patterns"),
                top_categories=insights_data.get("top_categories", []),
                unusual_patterns=insights_data.get("unusual_patterns"),
                budgeting_recommendations=insights_data.get("budgeting_recommendations", []),
                savings_opportunities=insights_data.get("savings_opportunities", [])
            )
            
            return {
                "success": True,
                "analysis": insights_data.get("analysis", ""),
                "insights": insights,
                "expense_summary": {
                    "user": expense_data["user_info"]["name"],
                    "period": f"{start_date} to {end_date}",
                    "total_amount": expense_data["summary"]["total_amount"],
                    "transaction_count": expense_data["summary"]["total_transactions"],
                    "top_category": expense_data["category_breakdown"][0]["category"] if expense_data["category_breakdown"] else "None"
                }
            }
        else:
            return {
                "success": False,
                "error": ai_result["error"],
                "expense_summary": {
                    "user": expense_data["user_info"]["name"],
                    "period": f"{start_date} to {end_date}",
                    "total_amount": expense_data["summary"]["total_amount"],
                    "transaction_count": expense_data["summary"]["total_transactions"]
                }
            }
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process AI analysis: {str(e)}"
        )

# Add a simple test endpoint
@app.get("/test-ai")
def test_ai_endpoint():
    """Test if AI API is working"""
    test_data = {
        "user_info": {"name": "Test User", "mobile": "1234567890"},
        "summary": {"total_transactions": 5, "total_amount": 5000, "average_transaction_amount": 1000},
        "category_breakdown": [
            {"category": "Food", "total_amount": 2000, "percentage_of_total": 40},
            {"category": "Transport", "total_amount": 1500, "percentage_of_total": 30}
        ],
        "transactions": [
            {"date": "2024-01-15", "amount": 1000, "category": "Food", "description": "Restaurant"}
        ]
    }
    
    result = ai_service.analyze_expenses(test_data)
    return {"ai_test_result": result}
    
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
        # Test connection and create tables
        conn = connection_pool.getconn()
        cur = conn.cursor()
        
        # Create users table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                mobile TEXT UNIQUE NOT NULL,
                role TEXT DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create expense table with foreign key to users
        cur.execute("""
            CREATE TABLE IF NOT EXISTS expense (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                date DATE NOT NULL,
                category TEXT NOT NULL,
                description TEXT,
                amount NUMERIC NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        
        # Create indexes for better performance
        cur.execute("CREATE INDEX IF NOT EXISTS idx_expense_user_id ON expense(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_expense_date ON expense(date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_mobile ON users(mobile)")
        
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

# User endpoints
@app.post("/users", response_model=UserResponse)
def create_user(user: UserCreate):
    """Create a new user"""
    with get_db_cursor() as cur:
        try:
            cur.execute(
                """
                INSERT INTO users (name, mobile, role)
                VALUES (%s, %s, %s)
                RETURNING id, name, mobile, role
                """,
                (user.name, user.mobile, user.role.value)
            )
            row = cur.fetchone()
            return {
                "id": row[0],
                "name": row[1],
                "mobile": row[2],
                "role": row[3]
            }
        except psycopg2.errors.UniqueViolation:
            raise HTTPException(
                status_code=400, 
                detail="User with this mobile number already exists"
            )


@app.get("/items/filter")
def get_items_by_date_range(mobile: str, start_date: date, end_date: date):
    """
    Get expense items for a specific user within a date range.
    
    Args:
        mobile: User's mobile number
        start_date: Start date (inclusive) in YYYY-MM-DD format
        end_date: End date (inclusive) in YYYY-MM-DD format
    
    Returns:
        List of expense items within the date range
    """
    # Validate date range
    if start_date > end_date:
        raise HTTPException(
            status_code=400, 
            detail="Start date must be before or equal to end date"
        )
    
    with get_db_cursor() as cur:
        # Get user_id
        cur.execute("SELECT id FROM users WHERE mobile = %s", (mobile,))
        user_row = cur.fetchone()
        
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_id = user_row[0]
        
        # Get items within date range
        cur.execute(
            """
            SELECT id, user_id, date, category, description, amount 
            FROM expense 
            WHERE user_id = %s AND date BETWEEN %s AND %s
            ORDER BY date DESC, id DESC
            """,
            (user_id, start_date, end_date)
        )
        
        rows = cur.fetchall()
        
        # Calculate total amount for the date range
        cur.execute(
            """
            SELECT COALESCE(SUM(amount), 0) as total_amount, COUNT(*) as count
            FROM expense 
            WHERE user_id = %s AND date BETWEEN %s AND %s
            """,
            (user_id, start_date, end_date)
        )
        
        total_info = cur.fetchone()
        
        return {
            "user_id": user_id,
            "mobile": mobile,
            "start_date": start_date,
            "end_date": end_date,
            "total_amount": float(total_info[0]) if total_info[0] else 0,
            "transaction_count": total_info[1],
            "items": [
                {
                    "id": row[0],
                    "user_id": row[1],
                    "date": row[2],
                    "category": row[3],
                    "description": row[4],
                    "amount": float(row[5])
                }
                for row in rows
            ]
        }

@app.get("/items/monthly/{mobile}/{year}/{month}")
def get_monthly_items(mobile: str, year: int, month: int):
    """
    Get all expense items for a specific user in a given month.
    
    Args:
        mobile: User's mobile number
        year: Year (e.g., 2024)
        month: Month (1-12)
    """
    # Validate month
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Month must be between 1 and 12")
    
    # Calculate date range for the month
    if month == 12:
        next_year = year + 1
        next_month = 1
    else:
        next_year = year
        next_month = month + 1
    
    start_date = date(year, month, 1)
    end_date = date(next_year, next_month, 1) - timedelta(days=1)
    
    # Use the date range filter function
    return get_items_by_date_range(mobile, start_date, end_date)

@app.get("/items/daily/{mobile}/{date_str}")
def get_items_by_specific_date(mobile: str, date_str: str):
    """
    Get all expense items for a specific user on a specific date.
    
    Args:
        mobile: User's mobile number
        date_str: Date in YYYY-MM-DD format
    """
    try:
        specific_date = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    with get_db_cursor() as cur:
        # Get user_id
        cur.execute("SELECT id FROM users WHERE mobile = %s", (mobile,))
        user_row = cur.fetchone()
        
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_id = user_row[0]
        
        # Get items for the specific date
        cur.execute(
            """
            SELECT id, user_id, date, category, description, amount 
            FROM expense 
            WHERE user_id = %s AND date = %s
            ORDER BY id DESC
            """,
            (user_id, specific_date)
        )
        
        rows = cur.fetchall()
        
        # Calculate total for the day
        cur.execute(
            """
            SELECT COALESCE(SUM(amount), 0) as total_amount, COUNT(*) as count
            FROM expense 
            WHERE user_id = %s AND date = %s
            """,
            (user_id, specific_date)
        )
        
        total_info = cur.fetchone()
        
        return {
            "user_id": user_id,
            "mobile": mobile,
            "date": specific_date,
            "total_amount": float(total_info[0]) if total_info[0] else 0,
            "transaction_count": total_info[1],
            "items": [
                {
                    "id": row[0],
                    "user_id": row[1],
                    "date": row[2],
                    "category": row[3],
                    "description": row[4],
                    "amount": float(row[5])
                }
                for row in rows
            ]
        }

@app.get("/items/summary/{mobile}/{start_date}/{end_date}")
def get_date_range_summary(mobile: str, start_date: date, end_date: date):
    """
    Get a summary of expenses for a user within a date range, grouped by category.
    
    Args:
        mobile: User's mobile number
        start_date: Start date (inclusive)
        end_date: End date (inclusive)
    """
    # Validate date range
    if start_date > end_date:
        raise HTTPException(
            status_code=400, 
            detail="Start date must be before or equal to end date"
        )
    
    with get_db_cursor() as cur:
        # Get user_id
        cur.execute("SELECT id FROM users WHERE mobile = %s", (mobile,))
        user_row = cur.fetchone()
        
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_id = user_row[0]
        
        # Get category-wise summary
        cur.execute(
            """
            SELECT 
                category,
                COUNT(*) as transaction_count,
                SUM(amount) as total_amount,
                AVG(amount) as average_amount,
                MIN(amount) as min_amount,
                MAX(amount) as max_amount
            FROM expense 
            WHERE user_id = %s AND date BETWEEN %s AND %s
            GROUP BY category
            ORDER BY total_amount DESC
            """,
            (user_id, start_date, end_date)
        )
        
        rows = cur.fetchall()
        
        # Get overall totals
        cur.execute(
            """
            SELECT 
                COUNT(*) as total_transactions,
                SUM(amount) as overall_total,
                AVG(amount) as overall_average,
                MIN(date) as first_date,
                MAX(date) as last_date
            FROM expense 
            WHERE user_id = %s AND date BETWEEN %s AND %s
            """,
            (user_id, start_date, end_date)
        )
        
        overall = cur.fetchone()
        
        return {
            "user_id": user_id,
            "mobile": mobile,
            "date_range": {
                "start_date": start_date,
                "end_date": end_date
            },
            "overall_summary": {
                "total_transactions": overall[0],
                "overall_total": float(overall[1]) if overall[1] else 0,
                "overall_average": float(overall[2]) if overall[2] else 0,
                "first_date": overall[3],
                "last_date": overall[4]
            },
            "category_summary": [
                {
                    "category": row[0],
                    "transaction_count": row[1],
                    "total_amount": float(row[2]) if row[2] else 0,
                    "average_amount": float(row[3]) if row[3] else 0,
                    "min_amount": float(row[4]) if row[4] else 0,
                    "max_amount": float(row[5]) if row[5] else 0
                }
                for row in rows
            ]
        }


@app.get("/items/daily/{mobile}")
def get_daily_totals(mobile: str):
    """Get date-wise total amount for each day for a user"""
    with get_db_cursor() as cur:
        # Get user_id
        cur.execute("SELECT id FROM users WHERE mobile = %s", (mobile,))
        user_row = cur.fetchone()
        
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_id = user_row[0]
        
        # Get date and total amount for each day
        cur.execute(
            """
            SELECT date, SUM(amount) as total_amount, COUNT(*) as count
            FROM expense 
            WHERE user_id = %s
            GROUP BY date
            ORDER BY date DESC
            """,
            (user_id,)
        )
        
        rows = cur.fetchall()
        
        return [
            {
                "date": row[0],
                "total_amount": float(row[1]) if row[1] else 0,
                "transaction_count": row[2]
            }
            for row in rows
        ]


@app.get("/users/{mobile}", response_model=UserResponse)
def get_user_by_mobile(mobile: str):
    """Get user by mobile number"""
    with get_db_cursor() as cur:
        cur.execute(
            "SELECT id, name, mobile, role FROM users WHERE mobile = %s",
            (mobile,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        return {
            "id": row[0],
            "name": row[1],
            "mobile": row[2],
            "role": row[3]
        }

@app.get("/users", response_model=List[UserResponse])
def get_all_users():
    """Get all users"""
    with get_db_cursor() as cur:
        cur.execute("SELECT id, name, mobile, role FROM users ORDER BY id")
        rows = cur.fetchall()
        return [
            {
                "id": row[0],
                "name": row[1],
                "mobile": row[2],
                "role": row[3]
            }
            for row in rows
        ]

# Item endpoints that require user authentication
@app.post("/items", response_model=ItemResponse)
def insert_item(mobile: str, item: Item):
    """
    Insert a new expense item for a specific user.
    User is identified by mobile number.
    """
    # First, get the user by mobile number
    with get_db_cursor() as cur:
        # Get user_id from mobile number
        cur.execute("SELECT id FROM users WHERE mobile = %s", (mobile,))
        user_row = cur.fetchone()
        
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_id = user_row[0]
        
        # Insert the expense item
        cur.execute(
            """
            INSERT INTO expense (user_id, date, category, description, amount)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, user_id, date, category, description, amount
            """,
            (user_id, item.date, item.category, item.description, item.amount)
        )
        inserted_row = cur.fetchone()
        
        return {
            "id": inserted_row[0],
            "user_id": inserted_row[1],
            "date": inserted_row[2],
            "category": inserted_row[3],
            "description": inserted_row[4],
            "amount": float(inserted_row[5])
        }
@app.get("/items/daily-range/{mobile}/{start_date}/{end_date}")
def get_daily_totals_in_range(mobile: str, start_date: str, end_date: str):
    """
    Get daily totals for a specific date range.
    
    Example: /items/daily-range/7909103947/2024-01-01/2024-01-15
    """
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    if start > end:
        raise HTTPException(status_code=400, detail="Start date must be before or equal to end date")
    
    with get_db_cursor() as cur:
        # Get user_id
        cur.execute("SELECT id FROM users WHERE mobile = %s", (mobile,))
        user_row = cur.fetchone()
        
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_id = user_row[0]
        
        # Get daily totals for the date range
        cur.execute(
            """
            SELECT date, SUM(amount) as total_amount, COUNT(*) as count
            FROM expense 
            WHERE user_id = %s AND date BETWEEN %s AND %s
            GROUP BY date
            ORDER BY date
            """,
            (user_id, start, end)
        )
        
        rows = cur.fetchall()
        
        return {
            "user_id": user_id,
            "mobile": mobile,
            "start_date": start,
            "end_date": end,
            "daily_totals": [
                {
                    "date": row[0],
                    "total_amount": float(row[1]) if row[1] else 0,
                    "transaction_count": row[2]
                }
                for row in rows
            ]
        }
        
@app.get("/items", response_model=List[ItemResponse])
def get_items_by_user(mobile: str):
    """Get all expense items for a specific user"""
    with get_db_cursor() as cur:
        # First verify user exists and get user_id
        cur.execute("SELECT id FROM users WHERE mobile = %s", (mobile,))
        user_row = cur.fetchone()
        
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_id = user_row[0]
        
        # Get user's expenses
        cur.execute(
            """
            SELECT id, user_id, date, category, description, amount 
            FROM expense 
            WHERE user_id = %s
            ORDER BY date DESC
            """,
            (user_id,)
        )
        rows = cur.fetchall()
        
        return [
            {
                "id": row[0],
                "user_id": row[1],
                "date": row[2],
                "category": row[3],
                "description": row[4],
                "amount": float(row[5])
            }
            for row in rows
        ]

@app.get("/items/{item_id}", response_model=ItemResponse)
def get_item_by_id(mobile: str, item_id: int):
    """Get a specific expense item for a user"""
    with get_db_cursor() as cur:
        # First verify user exists and get user_id
        cur.execute("SELECT id FROM users WHERE mobile = %s", (mobile,))
        user_row = cur.fetchone()
        
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_id = user_row[0]
        
        # Get the specific item for this user
        cur.execute(
            """
            SELECT id, user_id, date, category, description, amount 
            FROM expense 
            WHERE id = %s AND user_id = %s
            """,
            (item_id, user_id)
        )
        row = cur.fetchone()
        
        if not row:
            raise HTTPException(
                status_code=404, 
                detail="Item not found or doesn't belong to this user"
            )
        
        return {
            "id": row[0],
            "user_id": row[1],
            "date": row[2],
            "category": row[3],
            "description": row[4],
            "amount": float(row[5])
        }

@app.delete("/items/{item_id}")
def delete_item(mobile: str, item_id: int):
    """Delete an expense item for a specific user"""
    with get_db_cursor() as cur:
        # First verify user exists and get user_id
        cur.execute("SELECT id FROM users WHERE mobile = %s", (mobile,))
        user_row = cur.fetchone()
        
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_id = user_row[0]
        
        # Delete the item that belongs to this user
        cur.execute(
            "DELETE FROM expense WHERE id = %s AND user_id = %s RETURNING id",
            (item_id, user_id)
        )
        deleted_row = cur.fetchone()
        
        if not deleted_row:
            raise HTTPException(
                status_code=404, 
                detail="Item not found or doesn't belong to this user"
            )
        
        return {"status": "deleted", "id": item_id, "user_id": user_id}

@app.put("/items/{item_id}", response_model=ItemResponse)
def update_item(mobile: str, item_id: int, item: Item):
    """Update an expense item for a specific user"""
    with get_db_cursor() as cur:
        # First verify user exists and get user_id
        cur.execute("SELECT id FROM users WHERE mobile = %s", (mobile,))
        user_row = cur.fetchone()
        
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_id = user_row[0]
        
        # Update the item that belongs to this user
        cur.execute(
            """
            UPDATE expense 
            SET date = %s, category = %s, description = %s, amount = %s
            WHERE id = %s AND user_id = %s
            RETURNING id, user_id, date, category, description, amount
            """,
            (item.date, item.category, item.description, item.amount, item_id, user_id)
        )
        row = cur.fetchone()
        
        if not row:
            raise HTTPException(
                status_code=404, 
                detail="Item not found or doesn't belong to this user"
            )
        
        return {
            "status": "updated",
            "id": row[0],
            "user_id": row[1],
            "date": row[2],
            "category": row[3],
            "description": row[4],
            "amount": float(row[5])
        }

# Admin endpoints (optional)
@app.get("/admin/items", response_model=List[ItemResponse])
def get_all_items_admin():
    """Get all expense items (admin only)"""
    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT e.id, e.user_id, e.date, e.category, e.description, e.amount,
                   u.name, u.mobile
            FROM expense e
            JOIN users u ON e.user_id = u.id
            ORDER BY e.date DESC
            """
        )
        rows = cur.fetchall()
        
        return [
            {
                "id": row[0],
                "user_id": row[1],
                "date": row[2],
                "category": row[3],
                "description": row[4],
                "amount": float(row[5]),
                "user_name": row[6],
                "user_mobile": row[7]
            }
            for row in rows
        ]

# Health check endpoint
@app.get("/health")
def health_check():
    """Check if the API and database are healthy"""
    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT 1")
            cur.execute("SELECT COUNT(*) FROM users")
            users_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM expense")
            expenses_count = cur.fetchone()[0]
            
            return {
                "status": "healthy",
                "database": "connected",
                "users_count": users_count,
                "expenses_count": expenses_count
            }
    except Exception as e:
        return {"status": "unhealthy", "database": "disconnected", "error": str(e)}
