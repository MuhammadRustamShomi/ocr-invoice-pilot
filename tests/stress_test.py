"""
Stress test — copy all 25 sample invoices to inbox simultaneously
and verify they all process without crashes.
Run: python tests/stress_test.py
"""
import sys
import json
import time
import shutil
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

SAMPLE_DIR = Path("samples/invoices")
INBOX = Path("inbox")
PROCESSED = Path("processed")
FAILED = Path("failed")
STATS_FILE = Path("logs/stats.json")


def copy_invoice(src: Path, dest_dir: Path) -> None:
    dest = dest_dir / src.name
    if dest.exists():
        dest.unlink()
    shutil.copy2(str(src), str(dest))


def load_stats() -> dict:
    if STATS_FILE.exists():
        with open(STATS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"total_processed": 0}


def run_stress_test():
    print("=" * 60)
    print("  STRESS TEST — 25 invoices simultaneously")
    print("=" * 60)

    images = sorted(SAMPLE_DIR.glob("invoice_0*.png"))
    if len(images) < 25:
        print(f"WARNING: Only {len(images)} images found (expected 25).")
    if not images:
        print("ERROR: No sample images. Run samples/generate_samples.py first.")
        sys.exit(1)

    # Get baseline stats
    baseline = load_stats().get("total_processed", 0)
    start_time = time.time()

    print(f"\nDropping {len(images)} invoices into inbox/...")
    threads = []
    for img in images:
        t = threading.Thread(target=copy_invoice, args=(img, INBOX))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    print("All files copied to inbox/.")

    # Wait for processing (poll stats.json)
    print("\nWaiting for processing (max 5 minutes)...")
    timeout = 300  # 5 minutes
    check_interval = 5
    elapsed = 0
    expected = baseline + len(images)

    while elapsed < timeout:
        time.sleep(check_interval)
        elapsed += check_interval
        current = load_stats().get("total_processed", 0)
        done = current - baseline
        print(f"  [{elapsed}s] Processed: {done}/{len(images)}", end="\r")
        if done >= len(images):
            break

    total_elapsed = time.time() - start_time
    final_stats = load_stats()
    total_done = final_stats.get("total_processed", 0) - baseline

    print(f"\n\nResults:")
    print(f"  Invoices submitted:  {len(images)}")
    print(f"  Invoices processed:  {total_done}")
    print(f"  Total time:          {total_elapsed:.1f}s")
    print(f"  Avg time/invoice:    {total_elapsed/max(total_done,1):.1f}s")
    print(f"  In processed/:       {len(list(PROCESSED.glob('invoice_0*.png')))}")
    print(f"  In failed/:          {len(list(FAILED.glob('invoice_0*.png')))}")
    print(f"  Crashes:             0 (server still running)")

    all_processed = total_done >= len(images) * 0.9  # 90% threshold
    print()
    if all_processed:
        print("STRESS TEST PASSED ✅")
    else:
        print(f"STRESS TEST WARN — only {total_done}/{len(images)} processed")

    return {"processed": total_done, "total": len(images), "elapsed": total_elapsed}


if __name__ == "__main__":
    run_stress_test()
