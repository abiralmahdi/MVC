from django.core.management.base import BaseCommand, CommandError

from ml.models import TrainingRun
from ml.training import train_models


class Command(BaseCommand):
    help = "Download the public predictive-maintenance datasets, train the XGBoost models and score all plant devices."

    def add_arguments(self, parser):
        parser.add_argument('--run', type=int, help='Existing TrainingRun id (used by the Machine Learning page).')

    def handle(self, *args, **options):
        if options['run']:
            run = TrainingRun.objects.filter(pk=options['run']).first()
            if run is None:
                raise CommandError(f"Training run {options['run']} does not exist.")
        else:
            run = TrainingRun.objects.create()
        try:
            train_models(run)
        except Exception as exc:
            raise CommandError(f'Training run #{run.pk} failed: {exc}')
        self.stdout.write(self.style.SUCCESS(f'Training run #{run.pk} completed: {run.metrics.get("risk")}'))
