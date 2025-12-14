"""Runner for the NLP pipeline."""
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from backend.analytics.nlp_pipeline import run_pipeline
import argparse

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--keyword', required=True)
    p.add_argument('--limit', type=int, default=500)
    p.add_argument('--n_topics', type=int, default=8)
    args = p.parse_args()
    res = run_pipeline(args.keyword, limit=args.limit, n_topics=args.n_topics)
    print(res)
