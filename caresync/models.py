from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

ROLE_CHOICES = [
    ('patient', 'Patient'),
    ('doctor', 'Doctor'),
]

DEPARTMENT_CHOICES = [
    ('General Medicine', 'General Medicine'),
    ('Cardiology', 'Cardiology'),
    ('Pediatrics', 'Pediatrics'),
    ('Orthopedics', 'Orthopedics'),
    ('Dermatology', 'Dermatology'),
    ('Neurology', 'Neurology'),
]

HOSPITAL_CHOICES = [
    ('AIIMS', 'All India Institute of Medical Sciences (AIIMS)'),
    ('Safdarjung', 'Safdarjung Hospital'),
    ('RML', 'Ram Manohar Lohia Hospital'),
    ('LNJP', 'Lok Nayak Jai Prakash Narayan Hospital'),
    ('GTB', 'Guru Teg Bahadur Hospital'),
    ('DDU', 'Deen Dayal Upadhyay Hospital'),
    ('Apollo', 'Indraprastha Apollo Hospital | Best Hospital in Delhi'),
    ('BLK_Max', 'BLK-Max Super Speciality Hospital Delhi'),
    ('Max_Saket', 'Max Super Speciality Hospital, Saket (Max Saket)'),
    ('Max_Smart', 'Max Smart Super Speciality Hospital, Saket (Max Smart)'),
    ('Fortis_VK', 'Fortis Flt Lt Rajan Dhall Hospital, Vasant Kunj - Best Hospital in New Delhi'),
    ('Fortis_SB', 'Fortis Hospital, Shalimar Bagh - Best Hospital in New Delhi'),
    ('Narayana', 'Dharamshila Narayana Superspeciality Hospital, Delhi'),
]

class Profile(models.Model):
    GENDER_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
        ('O', 'Other'),
    ]
    
    BLOOD_GROUPS = [
        ('A+', 'A+'),
        ('A-', 'A-'),
        ('B+', 'B+'),
        ('B-', 'B-'),
        ('AB+', 'AB+'),
        ('AB-', 'AB-'),
        ('O+', 'O+'),
        ('O-', 'O-'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='patient')
    phone = models.CharField(max_length=15, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True, null=True)
    blood_group = models.CharField(max_length=3, choices=BLOOD_GROUPS, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    emergency_contact = models.CharField(max_length=100, blank=True, null=True)
    profile_pic = models.ImageField(upload_to='profiles/', blank=True, null=True)
    
    # Doctor specific fields
    hospital = models.CharField(max_length=100, choices=HOSPITAL_CHOICES, blank=True, null=True)
    department = models.CharField(max_length=50, choices=DEPARTMENT_CHOICES, blank=True, null=True)
    is_approved = models.BooleanField(default=True) # Approved by default (for patients and superusers)

    def __str__(self):
        return f"{self.user.username}'s Profile ({self.role})"

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if not hasattr(instance, 'profile'):
        Profile.objects.create(user=instance)
    instance.profile.save()


class Appointment(models.Model):
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Confirmed', 'Confirmed'),
        ('Cancelled', 'Cancelled'),
        ('Completed', 'Completed'),
    ]

    patient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='appointments')
    doctor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='doctor_appointments')
    appointment_date = models.DateTimeField()
    department = models.CharField(max_length=50, choices=DEPARTMENT_CHOICES, default='General Medicine')
    hospital = models.CharField(max_length=100, choices=HOSPITAL_CHOICES, default='AIIMS')
    symptoms = models.TextField()
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='Pending')
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Appointment for {self.patient.username} on {self.appointment_date} at {self.hospital}"


class MedicalRecord(models.Model):
    FILE_TYPES = [
        ('X-Ray', 'X-Ray'),
        ('Prescription', 'Prescription'),
        ('Report', 'Report'),
        ('Other', 'Other'),
    ]

    patient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='medical_records')
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to='records/')
    file_type = models.CharField(max_length=20, choices=FILE_TYPES, default='Report')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    # AI Fracture Analysis fields
    ai_analyzed = models.BooleanField(default=False)
    ai_result = models.TextField(blank=True, null=True) # JSON or text containing coordinates and classification
    ai_has_fracture = models.BooleanField(default=False)
    doctor_remarks = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.title} ({self.file_type}) - {self.patient.username}"


class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications', blank=True, null=True) # null = Global notification
    title = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    dismissed_by = models.ManyToManyField(User, related_name='dismissed_notifications', blank=True)

    def __str__(self):
        recipient_name = self.recipient.username if self.recipient else "All Users"
        return f"Notification to {recipient_name}: {self.title}"


class ActivityLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='activity_logs')
    action = models.CharField(max_length=255)
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        user_name = self.user.username if self.user else "Anonymous"
        return f"{user_name} - {self.action} at {self.timestamp}"


class Feedback(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='feedbacks')
    rating = models.IntegerField(default=5)
    comments = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Feedback by {self.user.username} ({self.rating} stars)"


class HelpTicket(models.Model):
    STATUS_CHOICES = [
        ('Open', 'Open'),
        ('Resolved', 'Resolved'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='help_tickets')
    subject = models.CharField(max_length=200)
    description = models.TextField()
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='Open')
    admin_response = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    user_ticket_num = models.PositiveIntegerField(blank=True, null=True)

    def save(self, *args, **kwargs):
        if not self.user_ticket_num:
            existing = HelpTicket.objects.filter(user=self.user)
            if existing.exists():
                max_num = existing.aggregate(models.Max('user_ticket_num'))['user_ticket_num__max']
                self.user_ticket_num = (max_num or 0) + 1
            else:
                self.user_ticket_num = 1
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Ticket #{self.user_ticket_num or self.id} - {self.subject} ({self.status}) for @{self.user.username}"
