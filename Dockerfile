FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_DEBUG=0

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

# collectstatic needs a key at build time only; the real key is passed at runtime.
RUN DJANGO_SECRET_KEY=build-only-not-secret python manage.py collectstatic --noinput

EXPOSE 8000

# Web server. Run the meter poller as a second container/service with:
#   python manage.py poll_modbus
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn MVC.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120"]
