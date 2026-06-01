from django.contrib import admin
from .models import Profile, Appointment, MedicalRecord, Notification, ActivityLog, Feedback, HelpTicket

admin.site.register(Profile)
admin.site.register(Appointment)
admin.site.register(MedicalRecord)
admin.site.register(Notification)
admin.site.register(ActivityLog)
admin.site.register(Feedback)
admin.site.register(HelpTicket)
