import os
import sys
import django

# Add project root directory to path
sys.path.append(os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'caresync_project.settings')
django.setup()

from django.core.mail import send_mail
from django.conf import settings

try:
    print("Attempting to send email...")
    print(f"SMTP Host: {settings.EMAIL_HOST}")
    print(f"SMTP Port: {settings.EMAIL_PORT}")
    print(f"SMTP User: {settings.EMAIL_HOST_USER}")
    
    send_mail(
        'CareSync SMTP Test',
        'This is a test email from CareSync.',
        settings.DEFAULT_FROM_EMAIL,
        ['caresync.support@gmail.com'],  # send to self to test
        fail_silently=False,
    )
    print("Email sent successfully!")
except Exception as e:
    print(f"Error occurred while sending email: {e}")
