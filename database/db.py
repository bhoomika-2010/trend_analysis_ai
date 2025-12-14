# database/db.py
import mysql.connector
from mysql.connector import Error
import json # For handling JSON data for insertion

# Your connection details
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "Mysql@12345",
    "database": "trend_analysis"
}

def get_db_connection():
    """Establishes and returns a database connection."""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except Error as e:
        print(f"Error connecting to MySQL database: {e}")
        return None


def create_tables():
    """Create additional tables for topics, entities, influencers, aggregates, and geo metrics."""
    conn = get_db_connection()
    if conn is None:
        print('Cannot create tables: DB connection failed')
        return False

    cursor = conn.cursor()
    try:
        # Topics table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INT AUTO_INCREMENT PRIMARY KEY,
            keyword VARCHAR(255) NOT NULL,
            platform VARCHAR(100) NOT NULL,
            topic_id VARCHAR(100),
            topic_label TEXT,
            score FLOAT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_topic (keyword, platform, topic_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # Entities table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            id INT AUTO_INCREMENT PRIMARY KEY,
            keyword VARCHAR(255) NOT NULL,
            platform VARCHAR(100) NOT NULL,
            entity TEXT,
            entity_type VARCHAR(50),
            support INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # Influencers table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS influencers (
            id INT AUTO_INCREMENT PRIMARY KEY,
            keyword VARCHAR(255) NOT NULL,
            platform VARCHAR(100) NOT NULL,
            user_id VARCHAR(255),
            username VARCHAR(255),
            followers BIGINT DEFAULT 0,
            engagements INT DEFAULT 0,
            influence_score FLOAT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_influencer (keyword, platform, user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # Trend aggregates (daily/weekly)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS trend_aggregates (
            id INT AUTO_INCREMENT PRIMARY KEY,
            keyword VARCHAR(255) NOT NULL,
            platform VARCHAR(100) NOT NULL,
            date DATE NOT NULL,
            avg_score FLOAT,
            mentions INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_aggregate (keyword, platform, date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # Geo metrics (daily)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS geo_metrics (
            id INT AUTO_INCREMENT PRIMARY KEY,
            keyword VARCHAR(255) NOT NULL,
            platform VARCHAR(100) NOT NULL,
            country VARCHAR(100),
            region VARCHAR(100),
            city VARCHAR(100),
            `date` DATE,
            metric FLOAT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_geo (keyword, platform, country, `date`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # Post enrichment table: sentiment + assigned topic per post
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS post_enrichment (
            id INT AUTO_INCREMENT PRIMARY KEY,
            platform_post_id VARCHAR(255) NOT NULL,
            keyword VARCHAR(255) NOT NULL,
            platform VARCHAR(100),
            sentiment_compound FLOAT,
            assigned_topic VARCHAR(100),
            topic_weight FLOAT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_post (platform_post_id, keyword)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        conn.commit()
        print('✅ Database tables created or already exist.')
        return True
    except Error as e:
        print(f"Error creating tables: {e}")
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()

def insert_raw_row(platform, platform_post_id, keyword, post_time, author,
                   title, content, score, url, raw_json):
    """
    Inserts a single row into the 'raw_data' table.
    """
    conn = get_db_connection()
    if conn is None:
        return

    cursor = conn.cursor()
    query = """
    INSERT INTO raw_data (platform, platform_post_id, keyword, post_time, author,
                          title, content, score, url, raw_json)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    try:
        cursor.execute(query, (platform, platform_post_id, keyword, post_time, author,
                               title, content, score, url, raw_json))
        conn.commit()
        print(f"Successfully inserted raw data for {platform_post_id}")
    except Error as e:
        print(f"Error inserting raw data: {e}")
        conn.rollback() # Rollback in case of error
    finally:
        cursor.close()
        conn.close()

# You might also want functions for inserting into trends_cleaned later
# def insert_cleaned_trend(keyword, platform, average_score, mentions, peak_time):
#     # ... implementation ...
def insert_cleaned_trend(keyword, platform, average_score, mentions, peak_time):
    """
    Inserts or updates a single row into the 'trends_cleaned' table.
    """
    conn = get_db_connection()
    if conn is None:
        return

    cursor = conn.cursor()
    # We will use ON DUPLICATE KEY UPDATE.
    # This requires a UNIQUE constraint on the (keyword, platform) combo.
    query = """
    INSERT INTO trends_cleaned (keyword, platform, average_score, mentions, peak_time)
    VALUES (%s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        average_score = VALUES(average_score),
        mentions = VALUES(mentions),
        peak_time = VALUES(peak_time),
        created_at = CURRENT_TIMESTAMP
    """
    try:
        cursor.execute(query, (keyword, platform, average_score, mentions, peak_time))
        conn.commit()
        print(f"✅ Cleaned trend for '{keyword}' on '{platform}' inserted/updated.")
    except Error as e:
        print(f"❌ Error inserting/updating cleaned trend for '{keyword}' on '{platform}': {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()