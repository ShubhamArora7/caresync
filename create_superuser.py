import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'caresync_project.settings')
django.setup()

from django.contrib.auth.models import User

if not User.objects.filter(is_superuser=True).exists():
    User.objects.create_superuser('admin', 'admin@caresync.com', 'admin123', first_name='Admin', last_name='CareSync')
    print("Superuser created: username: admin, password: admin123")
else:
    print("Superuser already exists.")
