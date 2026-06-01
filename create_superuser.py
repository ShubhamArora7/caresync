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

# 2. Patient
if not User.objects.filter(username='patient').exists():
    user = User.objects.create_user('patient', 'patient@caresync.com', 'patient123', first_name='John', last_name='Doe')
    profile = user.profile
    profile.role = 'patient'
    profile.phone = '1234567890'
    profile.save()
    print("Default Patient created: patient / patient123")
else:
    print("Default Patient already exists.")

# 3. Doctor
if not User.objects.filter(username='doctor').exists():
    user = User.objects.create_user('doctor', 'doctor@caresync.com', 'doctor123', first_name='John', last_name='Watson')
    profile = user.profile
    profile.role = 'doctor'
    profile.phone = '9876543210'
    profile.hospital = 'Fortis_SB'
    profile.department = 'Cardiology'
    profile.is_approved = True
    profile.save()
    print("Default Doctor created: doctor / doctor123")
else:
    print("Default Doctor already exists.")
