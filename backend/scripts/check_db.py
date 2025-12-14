from database.db import get_db_connection

def check_keyword_counts(keyword='iphone'):
    conn = get_db_connection()
    if conn is None:
        print('DB connection failed')
        return
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM raw_data WHERE keyword=%s AND platform=%s", (keyword, 'Google Trends'))
        count = cur.fetchone()[0]
        print(f"Google Trends rows for '{keyword}': {count}")

        if count > 0:
            cur.execute("SELECT post_time, score FROM raw_data WHERE keyword=%s AND platform=%s ORDER BY post_time DESC LIMIT 5", (keyword, 'Google Trends'))
            rows = cur.fetchall()
            print('Most recent rows:')
            for r in rows:
                print(r)
    except Exception as e:
        print('Error querying DB:', e)
    finally:
        try:
            cur.close()
            conn.close()
        except:
            pass

if __name__ == '__main__':
    check_keyword_counts()
