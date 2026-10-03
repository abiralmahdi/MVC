"""Start training in a separate process so the web request returns immediately."""
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from .models import TrainingRun

STALE_AFTER = timedelta(minutes=10)


def launch_training(run):
    root = Path(settings.ML_ARTIFACTS_DIR)
    (root / 'runs').mkdir(parents=True, exist_ok=True)
    log_path = root / 'runs' / f'run_{run.pk}.out'
    command = [sys.executable, str(Path(settings.BASE_DIR) / 'manage.py'), 'train_maintenance_models', '--run', str(run.pk)]
    kwargs = {}
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs['start_new_session'] = True
    with open(log_path, 'ab') as output:
        process = subprocess.Popen(command, cwd=str(settings.BASE_DIR), stdout=output, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, env=os.environ.copy(), **kwargs)
    run.pid = process.pid
    run.save(update_fields=['pid', 'updated_at'])
    return process.pid


def active_run():
    """The queued/running training, after failing runs whose process stopped reporting."""
    for run in TrainingRun.objects.filter(status__in=[TrainingRun.QUEUED, TrainingRun.RUNNING]):
        if timezone.now() - run.updated_at > STALE_AFTER:
            run.status = TrainingRun.FAILED
            run.error = run.error or 'The training process stopped reporting progress.'
            run.message = 'Stopped unexpectedly'
            run.finished_at = timezone.now()
            run.save()
            continue
        return run
    return None
