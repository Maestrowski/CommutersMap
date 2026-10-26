import sys
import time
import argparse
import logging
from src.extract import fetch_site_metadata, fetch_incremental_readings
from src.transform import run_transformations

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

def parse_args():
    parser = argparse.ArgumentParser(description="Run the London Air Quality Network (LAQN) Data Pipeline.")
    parser.add_argument(
        "--days", 
        type=int, 
        default=14, 
        help="Number of days to backfill if no incremental watermark exists (default: 14)"
    )
    return parser.parse_args()

def main():
    args = parse_args()
    start_time = time.time()
    
    print("=" * 60)
    print(" 🚶 London Commuter Clean Air Map | End-to-End Pipeline")
    print("=" * 60)

    try:
        # Phase 1: Ingestion
        logger.info("[Phase 1/2] Syncing monitoring sites & incremental readings...")
        fetch_site_metadata()
        new_records = fetch_incremental_readings(days_backfill=args.days)
        logger.info(f"Ingestion complete: {new_records} new raw reading payload(s) stored.")

        # Phase 2: Transformation & Modeling
        logger.info("[Phase 2/2] Running DuckDB dimensional transformations & marts...")
        run_transformations()
        logger.info("Transformation complete: Star schema tables & marts updated.")

        elapsed = time.time() - start_time
        print("=" * 60)
        print(f"Pipeline completed successfully in {elapsed:.2f}s.")
        print(f"Processed {new_records} new reading payload(s).")
        print("=" * 60)
        sys.exit(0)

    except KeyboardInterrupt:
        logger.warning("\nPipeline execution halted by user.")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Pipeline failed during execution: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()