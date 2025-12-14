"""Runner for influencer pipeline."""
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from backend.analytics.influencer_pipeline import run_pipeline
import argparse

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--keyword', required=True)
    p.add_argument('--limit', type=int, default=10000)
    args = p.parse_args()
    print(run_pipeline(args.keyword, limit=args.limit))
