# Use official Python image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . /app/

# Collect static files (optional)
RUN python manage.py collectstatic --noinput

# Expose port
EXPOSE 8000

# Start the Django app with Gunicorn
CMD ["gunicorn", "MVC.wsgi:application", "--bind", "0.0.0.0:8000"]
