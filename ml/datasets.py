"""Public predictive-maintenance datasets used for training (downloaded once and cached)."""
import io
import os
import ssl
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from django.conf import settings

AZURE_MIRROR = ('https://raw.githubusercontent.com/ashishpatel26/'
                'Predictive_Maintenance_using_Machine-Learning_Microsoft_Casestudy/master/data')


@dataclass(frozen=True)
class RemoteFile:
    name: str
    url: str


@dataclass(frozen=True)
class Dataset:
    key: str
    title: str
    description: str
    source: str
    files: tuple
    used_for: str


AZURE_PDM = Dataset(
    key='azure_pdm',
    title='Microsoft Azure Predictive Maintenance',
    description='Hourly voltage, rotation, pressure and vibration of 100 machines for one year (2015), '
                'with error events, maintenance records and component failures.',
    source='https://github.com/Azure-Samples/MachineLearningSamples-PredictiveMaintenance',
    files=tuple(RemoteFile(f, f'{AZURE_MIRROR}/{f}') for f in
                ('PdM_telemetry.csv', 'PdM_errors.csv', 'PdM_failures.csv', 'PdM_machines.csv', 'PdM_maint.csv')),
    used_for='Imminent failures (1-2 day warning from telemetry anomalies and error events)',
)

NASA_CMAPSS = Dataset(
    key='nasa_cmapss',
    title='NASA C-MAPSS Turbofan Degradation (FD001 + FD003)',
    description='200 engines run from healthy to failure; temperatures, pressures and speeds drift slowly '
                'as wear builds up - the "rising day by day" pattern.',
    source='https://www.nasa.gov/intelligent-systems-division/discovery-and-systems-health/pcoe/pcoe-data-set-repository/',
    files=(RemoteFile('cmapss.zip', 'https://phm-datasets.s3.amazonaws.com/NASA/6.+Turbofan+Engine+Degradation+Simulation+Data+Set.zip'),),
    used_for='Gradual degradation: failure risk within 7 days and days until maintenance',
)

AI4I_2020 = Dataset(
    key='ai4i_2020',
    title='AI4I 2020 Predictive Maintenance (UCI)',
    description='10,000 machine operating points (air/process temperature, speed, torque, tool wear) '
                'labelled with the failure type: heat dissipation, power, overstrain, tool wear.',
    source='https://archive.ics.uci.edu/dataset/601/ai4i+2020+predictive+maintenance+dataset',
    files=(RemoteFile('ai4i2020.zip', 'https://archive.ics.uci.edu/static/public/601/ai4i+2020+predictive+maintenance+dataset.zip'),),
    used_for='Most likely failure type',
)

DATASETS = [AZURE_PDM, NASA_CMAPSS, AI4I_2020]


def _ssl_context():
    """Verified TLS using certifi's up-to-date CA bundle (the OS store can lack newer roots)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def data_dir():
    path = Path(getattr(settings, 'ML_ARTIFACTS_DIR')) / 'datasets'
    path.mkdir(parents=True, exist_ok=True)
    return path


def download(dataset, report=None, chunk=1 << 16):
    """Download the dataset files that are not cached yet. ``report(done_bytes, total_bytes, file)``."""
    folder = data_dir() / dataset.key
    folder.mkdir(parents=True, exist_ok=True)
    paths = {}
    for remote in dataset.files:
        target = folder / remote.name
        paths[remote.name] = target
        if target.exists() and target.stat().st_size > 0:
            if report:
                report(target.stat().st_size, target.stat().st_size, remote.name)
            continue
        tmp = target.with_suffix(target.suffix + '.part')
        request = urllib.request.Request(remote.url, headers={'User-Agent': 'MarksVision-ML/1.0'})
        with urllib.request.urlopen(request, timeout=60, context=_ssl_context()) as response, open(tmp, 'wb') as handle:
            total = int(response.headers.get('Content-Length') or 0)
            done = 0
            while True:
                block = response.read(chunk)
                if not block:
                    break
                handle.write(block)
                done += len(block)
                if report:
                    report(done, total, remote.name)
        os.replace(tmp, target)
    return paths


def load_azure(paths):
    telemetry = pd.read_csv(paths['PdM_telemetry.csv'], parse_dates=['datetime'])
    errors = pd.read_csv(paths['PdM_errors.csv'], parse_dates=['datetime'])
    failures = pd.read_csv(paths['PdM_failures.csv'], parse_dates=['datetime'])
    return telemetry, errors, failures


def load_ai4i(paths):
    with zipfile.ZipFile(paths['ai4i2020.zip']) as archive:
        name = next(n for n in archive.namelist() if n.lower().endswith('.csv'))
        return pd.read_csv(io.BytesIO(archive.read(name)))


CMAPSS_COLUMNS = ['unit', 'cycle', 'op1', 'op2', 'op3'] + [f's{i}' for i in range(1, 22)]


def load_cmapss(paths, subsets=('FD001', 'FD003')):
    """Run-to-failure training engines of the single-operating-condition subsets."""
    frames = []
    with zipfile.ZipFile(paths['cmapss.zip']) as outer:
        inner_name = next(n for n in outer.namelist() if n.lower().endswith('cmapssdata.zip'))
        with zipfile.ZipFile(io.BytesIO(outer.read(inner_name))) as inner:
            for offset, subset in enumerate(subsets):
                name = next(n for n in inner.namelist() if n.endswith(f'train_{subset}.txt'))
                df = pd.read_csv(io.BytesIO(inner.read(name)), sep=r'\s+', header=None, names=CMAPSS_COLUMNS)
                df['unit'] = df['unit'] + 1000 * offset
                df['subset'] = subset
                frames.append(df)
    return pd.concat(frames, ignore_index=True)


def cached_size(dataset):
    folder = data_dir() / dataset.key
    return sum(p.stat().st_size for p in folder.glob('*') if p.is_file() and not p.name.endswith('.part')) if folder.exists() else 0
