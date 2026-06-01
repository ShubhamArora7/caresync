import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'caresync_project.settings')
django.setup()

from django.contrib.auth.models import User

# 1. Superuser
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@caresync.com', 'admin123', first_name='Admin', last_name='CareSync')
    print("Superuser created: admin / admin123")
else:
    print("Superuser already exists.")
