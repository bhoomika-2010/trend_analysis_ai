import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from database import db
import argparse

def aggregate_keyword(keyword, platform=None):
    conn = db.get_db_connection()
    if conn is None:
        print('DB connection failed')
        return False
    cursor = conn.cursor()
    try:
        params = [keyword]
        sql = "SELECT DATE(post_time) as dt, AVG(score) as avg_score, COUNT(*) as mentions FROM raw_data WHERE keyword = %s"
        if platform:
            sql += " AND platform = %s"
            params.append(platform)
        sql += " GROUP BY dt ORDER BY dt"
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        inserted = 0
        for dt, avg_score, mentions in rows:
            upsert = ("INSERT INTO trend_aggregates (keyword, platform, date, avg_score, mentions) "
                      "VALUES (%s, %s, %s, %s, %s) "
                      "ON DUPLICATE KEY UPDATE avg_score = VALUES(avg_score), mentions = VALUES(mentions), created_at = CURRENT_TIMESTAMP")
            plat = platform if platform else 'all'
            cursor.execute(upsert, (keyword, plat, dt, float(avg_score) if avg_score is not None else None, int(mentions)))
            inserted += 1
        conn.commit()
        print(f"Aggregated {inserted} daily rows for '{keyword}' (platform={platform or 'all'})")
        return True
    except Exception as e:
        print('Error during aggregation:', e)
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--keyword', required=True)
    p.add_argument('--platform', default=None)
    args = p.parse_args()
    aggregate_keyword(args.keyword, args.platform)
