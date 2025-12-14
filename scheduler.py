# scheduler.py

import time
from apscheduler.schedulers.blocking import BlockingScheduler

# Import all the functions we need to run
from backend.scripts.google_trends import fetch_and_store_google_trends
from backend.scripts.reddit import fetch_and_store_reddit_trends
# from backend.scripts.twitter import fetch_and_store_twitter_trends # We can uncomment this later
from backend.processing.analyzer import analyze_and_store_sentiment

# Define the list of keywords you want to track automatically
KEYWORDS_TO_TRACK = ["smartwatch", "AI", "Quantum Computing", "Electric Vehicle"]

def scheduled_job():
    """
    This is the main function that will be executed by the scheduler.
    It runs the entire data pipeline for all tracked keywords.
    """
    print("======================================================")
    print(f"SCHEDULER: Starting new job run at {time.ctime()}")
    print("======================================================")

    for keyword in KEYWORDS_TO_TRACK:
        print(f"\n--- Processing keyword: {keyword} ---")
        
        # --- Step 1: Fetch Raw Data ---
        print("\n[FETCHING DATA]")
        try:
            fetch_and_store_google_trends(keyword)
            fetch_and_store_reddit_trends(keyword)
            # fetch_and_store_twitter_trends(keyword) # Uncomment when Twitter script is fixed
        except Exception as e:
            print(f"❌ An error occurred during data fetching for '{keyword}': {e}")
            continue # Move to the next keyword if fetching fails

        # --- Step 2: Analyze and Clean Data ---
        print("\n[ANALYZING SENTIMENT]")
        try:
            analyze_and_store_sentiment(keyword)
        except Exception as e:
            print(f"❌ An error occurred during sentiment analysis for '{keyword}': {e}")

    print("\n======================================================")
    print(f"SCHEDULER: Job run finished at {time.ctime()}")
    print("======================================================")


# --- Scheduler Configuration ---
if __name__ == "__main__":
    # Create a scheduler instance
    scheduler = BlockingScheduler()

    # Schedule the job to run every 6 hours
    # You can change 'hours' to 'minutes' or 'days' for testing or production
    scheduler.add_job(scheduled_job, 'interval', hours=6)

    print("✅ Scheduler started. The first job will run immediately, then every 6 hours.")
    print("Press Ctrl+C to exit.")

    try:
        # Run the job once immediately at the start
        scheduled_job() 
        # Start the scheduler's main loop
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        # Gracefully shut down the scheduler on exit
        scheduler.shutdown()
        print("Scheduler shut down successfully.")