
import os
from dotenv import load_dotenv
import snowflake.connector

load_dotenv()

conn = None

try:
    conn = snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        authenticator="OAUTH_AUTHORIZATION_CODE",
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA"),
        role=os.getenv("SNOWFLAKE_ROLE"),
        login_timeout=60
    )

    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT
                CURRENT_USER(),
                CURRENT_ROLE(),
                CURRENT_DATABASE(),
                CURRENT_SCHEMA()
        """)

        print("Snowflake connection successful!")
        print(cursor.fetchone())

except Exception as e:
    print(f"Connection failed: {e}")

finally:
    if conn is not None:
        conn.close()
