FROM python:3.12-slim

# Install system dependencies needed for compiling psycopg2 and reportlab
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Make start.sh executable
RUN chmod +x start.sh

# Run collectstatic
ENV PYTHONUNBUFFERED=1
RUN python manage.py collectstatic --noinput

# Start command
CMD ["./start.sh"]
