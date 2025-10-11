from django.core.management.base import BaseCommand
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from connections import datastorage
from dynamic.models import Meters

class Command(BaseCommand):
    help = 'Poll PAC4200 meters concurrently every minute'

    def handle(self, *args, **kwargs):
        while True:
            start_time = time.time()
            meters = Meters.objects.all()

            with ThreadPoolExecutor(max_workers=50) as executor:
                futures = {
                    executor.submit(datastorage.read_meter_data, meter): meter.ip
                    for meter in meters
                }

                for future in as_completed(futures):
                    ip = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        print(f"❌ Error reading meter {ip}: {e}")

            elapsed = time.time() - start_time
            sleep_time = max(0, 15 - elapsed)
            print(f"✅ Polling cycle completed in {elapsed:.2f} seconds. Sleeping {sleep_time:.2f} seconds.")
            time.sleep(sleep_time)
