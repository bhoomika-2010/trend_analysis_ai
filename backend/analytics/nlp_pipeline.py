"""Topic modeling and per-post enrichment pipeline.

Performs TF-IDF + NMF topic modeling over recent posts for a keyword,
inserts/upserts discovered topics into `topics` table, and writes
per-post sentiment (VADER) and assigned topic into `post_enrichment`.

Usage:
    python backend/scripts/run_nlp_pipeline.py --keyword iphone --n_topics 8 --limit 500
"""
import logging
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from database import db
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import NMF
import spacy

logger = logging.getLogger(__name__)


def fetch_posts(keyword, limit=500):
    conn = db.get_db_connection()
    if conn is None:
        return []
    cursor = conn.cursor(dictionary=True)
    try:
        query = "SELECT platform, platform_post_id, title, content FROM raw_data WHERE keyword = %s ORDER BY post_time DESC LIMIT %s"
        cursor.execute(query, (keyword, int(limit)))
        rows = cursor.fetchall()
        posts = []
        for r in rows:
            text = ''
            if r.get('title'):
                text += str(r['title']) + '\n'
            if r.get('content'):
                text += str(r['content'])
            posts.append({
                'platform': r.get('platform'),
                'platform_post_id': r.get('platform_post_id'),
                'text': text.strip() or ''
            })
        return posts
    finally:
        cursor.close()
        conn.close()


def run_pipeline(keyword, limit=500, n_topics=8):
    # fetch posts
    posts = fetch_posts(keyword, limit=limit)
    if not posts:
        return {'success': False, 'reason': 'no_posts'}

    texts = [p['text'] for p in posts]

    # prepare NLP tools
    try:
        nlp = spacy.load('en_core_web_sm')
    except Exception as e:
        logger.exception('spaCy model load failed: %s', e)
        return {'success': False, 'reason': 'spacy_missing', 'error': str(e)}

    vader = SentimentIntensityAnalyzer()

    # vectorize
    vectorizer = TfidfVectorizer(max_df=0.95, min_df=2, stop_words='english', max_features=4000)
    X = vectorizer.fit_transform(texts)

    # NMF
    nmf = NMF(n_components=n_topics, random_state=1, init='nndsvda', max_iter=400)
    W = nmf.fit_transform(X)
    H = nmf.components_

    feature_names = vectorizer.get_feature_names_out()

    # extract topics
    topics = []
    for topic_idx, topic in enumerate(H):
        top_indices = topic.argsort()[::-1][:10]
        top_words = [feature_names[i] for i in top_indices]
        label = ' '.join(top_words[:5])
        score = float(topic.max())
        topics.append({'topic_id': f'topic_{topic_idx}', 'label': label, 'score': score, 'words': top_words})

    # write topics and per-post enrichment
    conn = db.get_db_connection()
    if conn is None:
        return {'success': False, 'reason': 'db_connect_fail'}
    cursor = conn.cursor()
    try:
        # upsert topics
        for t in topics:
            upsert = ("INSERT INTO topics (keyword, platform, topic_id, topic_label, score) "
                      "VALUES (%s, %s, %s, %s, %s) "
                      "ON DUPLICATE KEY UPDATE topic_label = VALUES(topic_label), score = VALUES(score), created_at = CURRENT_TIMESTAMP")
            cursor.execute(upsert, (keyword, 'multi', t['topic_id'], t['label'], t['score']))

        # per-post enrichment
        for idx, p in enumerate(posts):
            sentiment = vader.polarity_scores(p['text']).get('compound') if p['text'] else None
            # assigned topic by max weight
            assigned = None
            topic_weight = None
            if idx < len(W):
                row = W[idx]
                if row.size:
                    ti = int(row.argmax())
                    assigned = f'topic_{ti}'
                    topic_weight = float(row[ti])

            # upsert into post_enrichment
            # Use INSERT ... ON DUPLICATE KEY UPDATE to upsert per-post enrichment
            ins = ("INSERT INTO post_enrichment (platform_post_id, keyword, platform, sentiment_compound, assigned_topic, topic_weight) "
                   "VALUES (%s, %s, %s, %s, %s, %s) "
                   "ON DUPLICATE KEY UPDATE sentiment_compound = VALUES(sentiment_compound), assigned_topic = VALUES(assigned_topic), topic_weight = VALUES(topic_weight), created_at = CURRENT_TIMESTAMP")
            cursor.execute(ins, (p['platform_post_id'], keyword, p['platform'], sentiment, assigned, topic_weight))

        conn.commit()
        return {'success': True, 'posts_processed': len(posts), 'topics_inserted': len(topics)}
    except Exception as e:
        logger.exception('NLP pipeline DB write failed: %s', e)
        conn.rollback()
        return {'success': False, 'reason': 'db_write_failed', 'error': str(e)}
    finally:
        cursor.close()
        conn.close()


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--keyword', required=True)
    p.add_argument('--limit', type=int, default=500)
    p.add_argument('--n_topics', type=int, default=8)
    args = p.parse_args()
    print(run_pipeline(args.keyword, limit=args.limit, n_topics=args.n_topics))
