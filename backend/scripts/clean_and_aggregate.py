import sys
import os
import pandas as pd
from datetime import datetime
from mysql.connector import Error

# Adjust the path to correctly import from the project_root level
# This allows importing 'database.db' as a module.
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from database.db import get_db_connection, insert_cleaned_trend # Import your DB functions

def clean_and_aggregate_google_trends(keyword=None):
    """
    Fetches raw Google Trends data, aggregates it, and inserts/updates
    the 'trends_cleaned' table.

    Args:
        keyword (str, optional): If provided, cleans only for this keyword.
                                 Otherwise, cleans for all Google Trends keywords.
    """
    conn = get_db_connection()
    if conn is None:
        print("❌ Could not establish database connection for cleaning.")
        return

    cursor = conn.cursor(dictionary=True) # Fetch rows as dictionaries for easier access
    platform = "Google Trends"
    
    try:
        if keyword:
            print(f"🔄 Cleaning and aggregating Google Trends data for keyword: '{keyword}'...")
            query = """
            SELECT keyword, post_time, score
            FROM raw_data
            WHERE platform = %s AND keyword = %s
            ORDER BY post_time ASC;
            """
            cursor.execute(query, (platform, keyword))
        else:
            print(f"🔄 Cleaning and aggregating ALL Google Trends data...")
            query = """
            SELECT keyword, post_time, score
            FROM raw_data
            WHERE platform = %s
            ORDER BY keyword, post_time ASC;
            """
            cursor.execute(query, (platform,))
        
        raw_data_records = cursor.fetchall()
        
        if not raw_data_records:
            print(f"⚠️ No raw data found for Google Trends {'for keyword ' + keyword if keyword else ''}.")
            return

        # Convert to Pandas DataFrame for easier aggregation
        df = pd.DataFrame(raw_data_records)

        # Group by keyword and perform aggregation
        # For Google Trends:
        #   - average_score: Mean of interest scores
        #   - mentions: Count of data points (e.g., number of days/weeks with data)
        #   - peak_time: The post_time corresponding to the maximum score
        
        # Find the peak_time for each keyword first
        idx_max_score = df.loc[df.groupby('keyword')['score'].idxmax()]
        
        # Aggregate the rest
        aggregated_df = df.groupby('keyword').agg(
            average_score=('score', 'mean'),
            mentions=('score', 'count')
        ).reset_index()

        # Merge peak_time back into the aggregated DataFrame
        # We need keyword and post_time from idx_max_score
        aggregated_df = aggregated_df.merge(
            idx_max_score[['keyword', 'post_time']],
            on='keyword',
            how='left'
        )
        aggregated_df = aggregated_df.rename(columns={'post_time': 'peak_time'})

        # Insert/update into trends_cleaned table
        for index, row in aggregated_df.iterrows():
            insert_cleaned_trend(
                keyword=row['keyword'],
                platform=platform,
                average_score=float(row['average_score']), # Ensure float type
                mentions=int(row['mentions']),             # Ensure int type
                peak_time=row['peak_time']                 # Datetime object
            )
        print(f"✅ Finished cleaning and aggregating Google Trends data.")
        return True

    except Error as e:
        print(f"❌ Database error during cleaning and aggregation: {e}")
        return False
    except Exception as e:
        print(f"❌ An unexpected error occurred during cleaning and aggregation: {e}")
        return False
    finally:
        if conn:
            cursor.close()
            conn.close()

# Test execution when the script is run directly
# if __name__ == "__main__":
#     # Example: Clean for a specific keyword
#     clean_and_aggregate_google_trends(keyword="smartwatch")

    # Example: Clean for all Google Trends keywords
    # clean_and_aggregate_google_trends()