"""Runner to invoke analyzer.analyze_and_store_sentiment_and_entities from command line.
"""
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from backend.processing.analyzer import analyze_and_store_sentiment_and_entities
import argparse

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--keyword', required=True)
    args = p.parse_args()
    res = analyze_and_store_sentiment_and_entities(args.keyword)
    print(res)
