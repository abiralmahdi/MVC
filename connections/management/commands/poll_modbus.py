from django.core.management.base import BaseCommand
import time
from connections import datastorage

class Command(BaseCommand):
    help = 'Poll PAC4200 continuously'

    def handle(self, *args, **kwargs):
        while True:
            datastorage.main('192.168.0.80')
            time.sleep(3)