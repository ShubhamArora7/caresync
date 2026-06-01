#!/bin/sh
# Wait for database connection if DATABASE_URL is defined
if [ -n "$DATABASE_URL" ]; then
  echo "Checking database connection..."
  python -c "
import socket, time, urllib.parse, os
db_url = os.environ.get('DATABASE_URL')
if db_url:
    url = urllib.parse.urlparse(db_url)
    host = url.hostname
    port = url.port or 5432
    if host:
        while True:
            try:
                with socket.create_connection((host, port), timeout=1):
                    break
            except OSError:
                print('Waiting for database to start...')
                time.sleep(1)
"
fi

# Run database migrations
python manage.py migrate

# Create the admin superuser
python create_superuser.py

# Start Gunicorn server (Render uses port 10000, Gunicorn listens on the port requested by the host)
gunicorn caresync_project.wsgi:application --bind 0.0.0.0:10000
