import os
import sys
import django

# Add project root directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'caresync_project.settings')
django.setup()

from django.contrib.auth.models import User
from caresync.models import HelpTicket

print("Starting backfill for existing HelpTicket user sequence numbers...")

for user in User.objects.all():
    tickets = HelpTicket.objects.filter(user=user).order_by('created_at', 'id')
    count = tickets.count()
    if count > 0:
        print(f"User: @{user.username} (ID: {user.id}) -> Found {count} tickets")
        for i, ticket in enumerate(tickets, 1):
            ticket.user_ticket_num = i
            ticket.save()
            print(f"  Updated ticket ID #{ticket.id} to user ticket #{i}")

print("Backfill complete!")
