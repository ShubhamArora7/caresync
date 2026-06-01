import os
import sys
import django

# Add project root directory to path
sys.path.append(os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'caresync_project.settings')
django.setup()

from django.contrib.auth.models import User
from caresync.models import Appointment, Profile

print("=== Doctor Profiles ===")
for p in Profile.objects.filter(role='doctor'):
    print(f"Doctor: {p.user.username}")
    print(f"  Hospital:   {repr(p.hospital)}")
    print(f"  Department: {repr(p.department)}")
    print(f"  Approved:   {p.is_approved}")

print("\n=== Appointments ===")
for a in Appointment.objects.all():
    print(f"Appointment #{a.id}:")
    print(f"  Patient:    {a.patient.username}")
    print(f"  Hospital:   {repr(a.hospital)}")
    print(f"  Department: {repr(a.department)}")
    print(f"  Status:     {a.status}")
