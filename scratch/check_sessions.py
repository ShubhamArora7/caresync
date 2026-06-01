import os
import sys
import django

# Add project root directory to path
sys.path.append(os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'caresync_project.settings')
django.setup()

from django.contrib.sessions.models import Session

print("Reading active sessions...")
for s in Session.objects.all():
    data = s.get_decoded()
    if 'pending_signup' in data:
        pending = data['pending_signup']
        print(f"Pending Signup:")
        print(f"  Username: {pending.get('username')}")
        print(f"  Email:    {pending.get('email')}")
        print(f"  Role:     {pending.get('role')}")
        if 'signup_otp' in data:
            print(f"  OTP:      {data['signup_otp']}")
