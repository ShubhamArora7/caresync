import os
import sys
import django

# Add root directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'caresync_project.settings')
django.setup()

from caresync.models import Appointment
from django.contrib.auth.models import User

def backfill():
    completed_no_doc = Appointment.objects.filter(status='Completed', doctor__isnull=True)
    for app in completed_no_doc:
        # Try to find a doctor matching the hospital and department
        doc = User.objects.filter(
            profile__role='doctor',
            profile__hospital=app.hospital,
            profile__department=app.department
        ).first()
        
        # Fallback to any doctor if none matches the hospital/dept
        if not doc:
            doc = User.objects.filter(profile__role='doctor').first()
            
        if doc:
            app.doctor = doc
            app.save()
            print(f"Assigned doctor {doc.username} to completed appointment #{app.id} ({app.hospital} - {app.department})")
        else:
            print(f"No doctor found in system to assign to appointment #{app.id}")

if __name__ == '__main__':
    backfill()
