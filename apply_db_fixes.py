import psycopg2
import os
import sys

# Configuration
DB_HOST = "omv.local"
DB_PORT = 5432
DB_USER = "casaos"
DB_PASS = "casaos"
SQL_FILE = "fix_all_stream_sample_rates.sql"

def try_connect(db_name):
    print(f"Attempting to connect to DB '{db_name}' at {DB_HOST}:{DB_PORT}...")
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=db_name,
            user=DB_USER,
            password=DB_PASS
        )
        conn.autocommit = True
        return conn
    except psycopg2.OperationalError as e:
        print(f"Connection to '{db_name}' failed: {e}")
        return None

def apply_fixes():
    # Try 'casaos' first (default in pi compose), then 'alerts' (default in app)
    conn = try_connect("casaos")
    if not conn:
        print("Retrying with DB 'alerts'...")
        conn = try_connect("alerts")
    
    if not conn:
        print("CRITICAL: Could not connect to any database.")
        return

    try:
        cur = conn.cursor()
        print("Connected successfully!")
        
        # Check time
        cur.execute("SELECT NOW();")
        result = cur.fetchone()
        db_time = result[0] if result else None
        print(f"Database Server Time: {db_time}")
        
        # Check if tables exist
        try:
            cur.execute("SELECT count(*) FROM radio_receivers;")
            print("Table 'radio_receivers' found.")
        except psycopg2.errors.UndefinedTable:
            print("Table 'radio_receivers' NOT found in this database.")
            conn.close()
            return

        # Read SQL file
        print(f"Reading {SQL_FILE}...")
        try:
            # FIX: Specify encoding='utf-8' to handle emojis/special chars in SQL file
            with open(SQL_FILE, 'r', encoding='utf-8') as f:
                sql_content = f.read()
        except FileNotFoundError:
            print(f"Error: Could not find {SQL_FILE}")
            return
            
        # Execute SQL
        print("Applying fixes...")
        clean_sql = []
        for line in sql_content.splitlines():
            if line.strip().startswith('\\'):
                print(f"   Skipping psql command: {line.strip()}")
            else:
                clean_sql.append(line)
        
        final_sql = '\n'.join(clean_sql)
        
        # Debug: Print the SQL around the error area
        print("Debug: Checking SQL content...")
        if "audio_source_configs asc" in final_sql:
            print("❌ ERROR: SQL still contains 'asc' alias!")
        else:
            print("✅ SQL looks correct (no 'asc' alias).")
            
        cur.execute(final_sql)
        
        print("SQL script executed successfully.")
        
        # Verify results
        print("\nVerifying SDR Sample Rates:")
        cur.execute("SELECT identifier, sample_rate FROM radio_receivers WHERE enabled = true;")
        rows = cur.fetchall()
        for row in rows:
            print(f"   - {row[0]}: {row[1]} Hz")
            
        conn.close()
        print("\nDone! Please restart the sdr-service on the remote machine.")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    apply_fixes()
