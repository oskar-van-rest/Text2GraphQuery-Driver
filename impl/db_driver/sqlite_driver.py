import sqlite3
import os
from driver.evaluation import DatabaseDriver

class SQLiteAdapter(DatabaseDriver):
    """
    SQLite Database Adapter for Text-to-SQL Evaluation
    """
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = None

    def connect(self):
        if not os.path.exists(self.db_path):
            print(f"Error: SQLite database not found at {self.db_path}")
            return
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("SELECT 1;")
            conn.close()
            print(f"Connected to SQLite DB: {self.db_path}")
        except Exception as e:
            print(f"Failed to connect to SQLite DB: {e}")

    def query(self, sql: str, db_name: str = None) -> list:
        """Execute the SQL and return the results as a list of tuples"""
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute(sql)
            rows = cur.fetchall()
            conn.close()
            return rows
        except Exception as e:
            return None

    def close(self):
        pass 