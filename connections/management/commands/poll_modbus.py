from django.core.management.base import BaseCommand
from concurrent.futures import ThreadPoolExecutor, as_completed
from django.utils import timezone
from datetime import timedelta
import time

from connections import datastorage
from dynamic.models import Meters
from connections.models import SystemJob
from dashboard.timeAggregationCombined import run_time_aggregation
from dashboard.hierarchyAggregateCombined import run_hierarchy_aggregation


class Command(BaseCommand):
    help = 'Poll PAC4200 meters and run daily aggregations at 12 AM'

    def handle(self, *args, **kwargs):
        # Create or get persistent job tracker
        job, _ = SystemJob.objects.get_or_create(
            name="daily_time_and_hierarchy_aggregation"
        )

        while True:
            loop_start = time.time()

            # ======================================
            # 1️⃣ Poll meters (runs continuously)
            # ======================================
            meters = Meters.objects.all()

            with ThreadPoolExecutor(max_workers=50) as executor:
                futures = {
                    executor.submit(datastorage.read_meter_data_all, meter): meter.ip
                    for meter in meters
                }

                for future in as_completed(futures):
                    ip = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        print(f"❌ Error reading meter {ip}: {e}")

            # ======================================
            # 2️⃣ Run aggregations ONLY at 12 AM
            # ======================================
            now = timezone.localtime()

            already_ran_today = (
                job.last_run is not None and
                job.last_run.date() == now.date()
            )

            is_midnight_window = (
                now.hour == 0 and now.minute < 5
            )

            if is_midnight_window and not already_ran_today:
                print("🟡 Starting midnight aggregations...")

                try:
                    run_time_aggregation()
                    run_hierarchy_aggregation()

                    job.last_run = now
                    job.save(update_fields=["last_run"])

                    print("✅ Midnight aggregations completed")

                except Exception as e:
                    print(f"❌ Aggregation failed: {e}")

            # ======================================
            # 3️⃣ Sleep before next polling cycle
            # ======================================
            elapsed = time.time() - loop_start
            sleep_time = max(0, 15 - elapsed)

            print(
                f"⏱ Cycle completed in {elapsed:.2f}s | "
                f"Sleeping {sleep_time:.2f}s"
            )

            time.sleep(sleep_time)
