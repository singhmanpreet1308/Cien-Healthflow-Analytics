
import os
import pandas as pd
import snowflake.connector
import logging
from pathlib import Path

from dotenv import load_dotenv
from snowflake.connector.pandas_tools import write_pandas

load_dotenv()

# ==========================================
#  Logging Configuration
# ==========================================

BASE_DIR = Path(__file__).resolve().parent

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "ingestion.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# ==========================================
# Dataset Configuration
# ==========================================

DATA_DIR = BASE_DIR / "../data"

datasets = {
    "medications_reference.csv": "MEDICATIONS_REFERENCE",
    "facility_monthly_metrics.csv": "FACILITY_MONTHLY_METRICS"
}

conn = None

try:
    # NEW: Pipeline Start
    logger.info("Starting Phase 03 ingestion pipeline")

    # ======================================
    # Snowflake Connection
    # ======================================

    conn = snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        authenticator=os.getenv(
            "SNOWFLAKE_AUTHENTICATOR",
            "OAUTH_AUTHORIZATION_CODE"
        ),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA"),
        role=os.getenv("SNOWFLAKE_ROLE")
    )

    # NEW: Connection log
    logger.info("Snowflake connection established successfully")

    # ======================================
    # CSV Ingestion
    # ======================================

    for filename, table_name in datasets.items():

        logger.info("Processing dataset: %s", filename)

        file_path = DATA_DIR / filename

        if not file_path.is_file():
            raise FileNotFoundError(
                f"Dataset not found: {file_path}"
            )

        df = pd.read_csv(file_path)
        df.columns = df.columns.str.upper()

        logger.info(
            "Dataset loaded: %s | Rows: %s | Columns: %s",
            filename,
            len(df),
            len(df.columns)
        )

        # Prevent duplicate loads on reruns
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) FROM RAW.{table_name}"
            )
            existing_rows = cursor.fetchone()[0]

        if existing_rows > 0:
            logger.warning(
                "Skipping %s: destination already contains %s rows",
                table_name,
                existing_rows
            )
            continue

        # ==================================
        # Load Data into Snowflake
        # ==================================

        logger.info("Starting ingestion into %s", table_name)

        success, chunks, rows, output = write_pandas(
            conn,
            df,
            table_name=table_name,
            schema="RAW",
            auto_create_table=False,
            overwrite=False
        )

        if not success or rows != len(df):
            raise RuntimeError(
                f"Load validation failed for {table_name}. "
                f"Expected {len(df)} rows, reported {rows}."
            )

        logger.info(
            "Successfully loaded %s records into %s",
            rows,
            table_name
        )

    logger.info("Phase 03 ingestion pipeline completed")

# ==========================================
# NEW: Error Handling
# ==========================================

except Exception:
    logger.exception("Ingestion pipeline failed")
    raise

# ==========================================
# NEW: Connection Cleanup
# ==========================================

finally:
    if conn is not None:
        conn.close()
        logger.info("Snowflake connection closed")
