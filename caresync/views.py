import os
import random
import threading
from django.core.mail import send_mail
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.forms import PasswordChangeForm
from django.http import HttpResponse
from django.db.models import Q
from django.utils import timezone
from django.conf import settings

from .models import Profile, Appointment, MedicalRecord, Notification, ActivityLog, Feedback, HelpTicket
from .forms import (PatientSignupForm, DoctorSignupForm, UserEditForm, ProfileEditForm, AppointmentForm, 
                    MedicalRecordForm, NotificationForm, FeedbackForm, HelpTicketForm)
from .utils import detect_fracture, generate_clinic_pdf, generate_doctor_report_pdf

# Helper to send email in background thread to prevent SMTP connection hangs
def send_email_async(subject, message, recipient_list, from_email=None):
    if from_email is None:
        from_email = settings.DEFAULT_FROM_EMAIL
    
    # In tests, run synchronously to satisfy outbox assertions
    if settings.EMAIL_BACKEND == 'django.core.mail.backends.locmem.EmailBackend':
        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=recipient_list,
            fail_silently=False,
        )
        return

    # Check for Brevo API key to bypass SMTP port blocks on Render
    brevo_api_key = os.environ.get('BREVO_API_KEY')

    def task():
        import json
        import urllib.request
        import urllib.error

        if brevo_api_key:
            # Send via Brevo HTTP API (Port 443, never blocked)
            url = "https://api.brevo.com/v3/smtp/email"
            headers = {
                "accept": "application/json",
                "api-key": brevo_api_key,
                "content-type": "application/json"
            }
            body = {
                "sender": {
                    "name": "CareSync",
                    "email": from_email
                },
                "to": [{"email": r} for r in recipient_list],
                "subject": subject,
                "textContent": message
            }
            try:
                data = json.dumps(body).encode('utf-8')
                req = urllib.request.Request(url, data=data, headers=headers, method='POST')
                with urllib.request.urlopen(req, timeout=10) as response:
                    res_body = response.read().decode('utf-8')
                    print(f"[EMAIL SUCCESS] Sent email via Brevo HTTP API: {res_body}")
            except Exception as e:
                print(f"[EMAIL ERROR] Brevo HTTP API send failure: {e}")
        else:
            # Fallback to standard SMTP
            try:
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=from_email,
                    recipient_list=recipient_list,
                    fail_silently=False,
                )
                print(f"[EMAIL SUCCESS] Sent email via SMTP")
            except Exception as e:
                print(f"[EMAIL ERROR] Async SMTP email send failure: {e}")

    threading.Thread(target=task).start()

# Helper to log user activities
def log_activity(user, action, request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    ActivityLog.objects.create(user=user, action=action, ip_address=ip)

# Public Views
def index(request):
    feedbacks = Feedback.objects.order_by('-created_at')[:3]
    return render(request, 'caresync/index.html', {'feedbacks': feedbacks})

def about(request):
    return render(request, 'caresync/about.html')

def contact(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        subject = request.POST.get('subject')
        message = request.POST.get('message')
        
        # Create a ticket or record as anonymous/user help ticket
        user = request.user if request.user.is_authenticated else None
        # Create notification for admin
        Notification.objects.create(
            recipient=None, # Global / Admin
            title=f"New Contact Inquiry: {subject}",
            message=f"Inquiry from {name} ({email}): {message}"
        )
        
        # Send email directly to support asynchronously
        send_email_async(
            subject=f"New Contact Inquiry: {subject}",
            message=(
                f"You have received a new contact inquiry via the CareSync portal.\n\n"
                f"Sender Name: {name}\n"
                f"Sender Email: {email}\n\n"
                f"Message:\n{message}"
            ),
            recipient_list=[settings.DEFAULT_FROM_EMAIL],
        )
            
        messages.success(request, "Your message has been sent successfully!")
        return redirect('contact')
    return render(request, 'caresync/contact.html', {'support_email': settings.DEFAULT_FROM_EMAIL})

# Authentication Views
def register_patient(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        form = PatientSignupForm(request.POST)
        if form.is_valid():
            # Get data but do NOT save User yet (as requested, verified then ID is made)
            data = form.cleaned_data.copy()
            data['role'] = 'patient'
            # Convert date of birth to string so it can be serialized in session
            if data.get('date_of_birth'):
                data['date_of_birth'] = data['date_of_birth'].strftime('%Y-%m-%d')
            
            # Generate OTP
            otp = str(random.randint(100000, 999999))
            email = data.get('email')
            print(f"[OTP DEBUG] Patient registration OTP for {email}: {otp}")
            
            # Save data to session
            request.session['pending_signup'] = data
            request.session['signup_otp'] = otp
            request.session['signup_otp_time'] = timezone.now().timestamp()
            
            # Send Email Asynchronously
            send_email_async(
                'CareSync Account Verification OTP',
                f'Dear {data.get("first_name", "User")},\n\n'
                f'Thank you for registering at CareSync. To verify your email and create your account, '
                f'please use the following One-Time Password (OTP):\n\n'
                f'OTP: {otp}\n\n'
                f'This OTP is valid for 5 minutes.\n\n'
                f'Best regards,\nCareSync Healthcare Team',
                [email],
            )
            messages.success(request, f"A 6-digit verification code has been sent to {email}. (If SMTP fails, check console logs/Render logs for fallback).")
            
            return redirect('verify_otp')
    else:
        form = PatientSignupForm()
    return render(request, 'caresync/signup.html', {'form': form})

def register_doctor(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        form = DoctorSignupForm(request.POST)
        if form.is_valid():
            # Get data but do NOT save User yet (as requested, verified then ID is made)
            data = form.cleaned_data.copy()
            data['role'] = 'doctor'
            # Convert date of birth to string so it can be serialized in session
            if data.get('date_of_birth'):
                data['date_of_birth'] = data['date_of_birth'].strftime('%Y-%m-%d')
            
            # Generate OTP
            otp = str(random.randint(100000, 999999))
            email = data.get('email')
            print(f"[OTP DEBUG] Doctor registration OTP for {email}: {otp}")
            
            # Save data to session
            request.session['pending_signup'] = data
            request.session['signup_otp'] = otp
            request.session['signup_otp_time'] = timezone.now().timestamp()
            
            # Send Email Asynchronously
            send_email_async(
                'CareSync Doctor Verification OTP',
                f'Dear Dr. {data.get("first_name", "User")},\n\n'
                f'Thank you for registering as a physician at CareSync. To verify your email and create your clinical account, '
                f'please use the following One-Time Password (OTP):\n\n'
                f'OTP: {otp}\n\n'
                f'This OTP is valid for 5 minutes.\n\n'
                f'Best regards,\nCareSync Healthcare Team',
                [email],
            )
            messages.success(request, f"A 6-digit verification code has been sent to {email}. (If SMTP fails, check console logs/Render logs for fallback).")
            
            return redirect('verify_otp')
    else:
        form = DoctorSignupForm()
    return render(request, 'caresync/doctor_signup.html', {'form': form})

def verify_otp(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
        
    signup_data = request.session.get('pending_signup')
    if not signup_data:
        messages.error(request, "No registration session found. Please fill out the signup form.")
        return redirect('signup')
        
    if request.method == 'POST':
        entered_otp = request.POST.get('otp')
        saved_otp = request.session.get('signup_otp')
        otp_time = request.session.get('signup_otp_time', 0)
        
        # Check expiry (5 minutes = 300 seconds)
        now = timezone.now().timestamp()
        if now - otp_time > 300:
            messages.error(request, "The OTP has expired. Please request a new one.")
            return render(request, 'caresync/verify_otp.html', {'email': signup_data.get('email')})
            
        if entered_otp == saved_otp:
            try:
                # OTP Verified -> Create the User and Profile (ID is made now!)
                from datetime import datetime
                user = User.objects.create_user(
                    username=signup_data['username'],
                    email=signup_data['email'],
                    password=signup_data['password'],
                    first_name=signup_data['first_name'],
                    last_name=signup_data['last_name']
                )
                
                # Update Profile
                profile = user.profile
                profile.role = signup_data.get('role', 'patient')
                profile.phone = signup_data.get('phone')
                if signup_data.get('date_of_birth'):
                    profile.date_of_birth = datetime.strptime(signup_data['date_of_birth'], '%Y-%m-%d').date()
                profile.gender = signup_data.get('gender')
                profile.blood_group = signup_data.get('blood_group')
                profile.address = signup_data.get('address')
                profile.emergency_contact = signup_data.get('emergency_contact')
                
                # Doctor specific fields
                profile.hospital = signup_data.get('hospital')
                profile.department = signup_data.get('department')
                if signup_data.get('role') == 'doctor':
                    profile.is_approved = False
                else:
                    profile.is_approved = True
                profile.save()
                
                # Log Activity & Auto Login
                log_activity(user, f"Completed email verification and registered profile as {profile.role}", request)
                
                user_auth = authenticate(request, username=user.username, password=signup_data['password'])
                if user_auth:
                    login(request, user_auth)
                    
                # Clean up session
                del request.session['pending_signup']
                del request.session['signup_otp']
                del request.session['signup_otp_time']
                
                messages.success(request, "Email verified successfully! Welcome to CareSync.")
                return redirect('dashboard')
            except Exception as e:
                messages.error(request, f"Error creating account: {e}")
        else:
            messages.error(request, "Invalid OTP code. Please check your email and try again.")
            
    return render(request, 'caresync/verify_otp.html', {'email': signup_data.get('email')})

def resend_otp(request):
    signup_data = request.session.get('pending_signup')
    if not signup_data:
        messages.error(request, "No registration session found. Please signup first.")
        return redirect('signup')
        
    otp = str(random.randint(100000, 999999))
    email = signup_data.get('email')
    print(f"[OTP DEBUG] Resent registration OTP for {email}: {otp}")
    request.session['signup_otp'] = otp
    request.session['signup_otp_time'] = timezone.now().timestamp()
    
    # Send Email Asynchronously
    send_email_async(
        'CareSync Account Verification OTP',
        f'Dear {signup_data.get("first_name", "User")},\n\n'
        f'You requested a new verification code. Please use the following One-Time Password (OTP) to complete registration:\n\n'
        f'OTP: {otp}\n\n'
        f'This OTP is valid for 5 minutes.\n\n'
        f'Best regards,\nCareSync Healthcare Team',
        [email],
    )
    messages.success(request, f"A new OTP has been sent to {email}. (If SMTP fails, check console logs/Render logs for fallback).")
        
    return redirect('verify_otp')

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        username_or_email = request.POST.get('username')
        password = request.POST.get('password')
        
        # Authenticate by username or email
        user = None
        if '@' in username_or_email:
            user_objs = User.objects.filter(email=username_or_email)
            for u in user_objs:
                authenticated_user = authenticate(request, username=u.username, password=password)
                if authenticated_user is not None:
                    user = authenticated_user
                    break
        
        if user is None:
            user = authenticate(request, username=username_or_email, password=password)

        
        if user is not None:
            login(request, user)
            log_activity(user, "Logged in", request)
            messages.success(request, f"Welcome back, {user.first_name or user.username}!")
            return redirect('dashboard')
        else:
            messages.error(request, "Invalid username or password.")
    return render(request, 'caresync/login.html')

def forgot_password_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
        
    if request.method == 'POST':
        email = request.POST.get('email')
        user = User.objects.filter(email=email).first()
        if user:
            # Generate 6-digit OTP code
            otp = str(random.randint(100000, 999999))
            print(f"[OTP DEBUG] Forgot Password OTP for {email}: {otp}")
            request.session['forgot_password_email'] = email
            request.session['forgot_password_otp'] = otp
            request.session['forgot_password_otp_time'] = timezone.now().timestamp()
            
            # Send Email Asynchronously
            send_email_async(
                'CareSync Password Reset OTP',
                f'Dear {user.first_name or user.username},\n\n'
                f'You requested a password reset code. Please use the following One-Time Password (OTP) to reset your password:\n\n'
                f'OTP: {otp}\n\n'
                f'This OTP is valid for 5 minutes.\n\n'
                f'Best regards,\nCareSync Healthcare Team',
                [email],
            )
            messages.success(request, f"A verification code has been sent to {email}. (If SMTP fails, check console logs/Render logs for fallback).")
            return redirect('forgot_password_verify')
        else:
            messages.error(request, "No registered account found with that email address.")
            
    return render(request, 'caresync/forgot_password.html')


def forgot_password_verify_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
        
    email = request.session.get('forgot_password_email')
    if not email:
        messages.error(request, "Please enter your email address first.")
        return redirect('forgot_password')
        
    if request.method == 'POST':
        entered_otp = request.POST.get('otp')
        saved_otp = request.session.get('forgot_password_otp')
        otp_time = request.session.get('forgot_password_otp_time', 0)
        
        now = timezone.now().timestamp()
        if now - otp_time > 300:
            messages.error(request, "The code has expired. Please request a new one.")
            return render(request, 'caresync/forgot_password_verify.html', {'email': email})
            
        if entered_otp == saved_otp:
            request.session['forgot_password_verified'] = True
            messages.success(request, "Code verified successfully! You can now reset your password.")
            return redirect('forgot_password_reset')
        else:
            messages.error(request, "Invalid verification code. Please check your email and try again.")
            
    return render(request, 'caresync/forgot_password_verify.html', {'email': email})


def forgot_password_resend_otp(request):
    email = request.session.get('forgot_password_email')
    if not email:
        messages.error(request, "Please enter your email address first.")
        return redirect('forgot_password')
        
    user = User.objects.filter(email=email).first()
    if not user:
        messages.error(request, "User associated with this email no longer exists.")
        return redirect('forgot_password')
        
    otp = str(random.randint(100000, 999999))
    print(f"[OTP DEBUG] Resent Forgot Password OTP for {email}: {otp}")
    request.session['forgot_password_otp'] = otp
    request.session['forgot_password_otp_time'] = timezone.now().timestamp()
    
    # Send Email Asynchronously
    send_email_async(
        'CareSync Password Reset OTP',
        f'Dear {user.first_name or user.username},\n\n'
        f'You requested a new password reset code. Please use the following One-Time Password (OTP) to reset your password:\n\n'
        f'OTP: {otp}\n\n'
        f'This OTP is valid for 5 minutes.\n\n'
        f'Best regards,\nCareSync Healthcare Team',
        [email],
    )
    messages.success(request, f"A new verification code has been sent to {email}. (If SMTP fails, check console logs/Render logs for fallback).")
        
    return redirect('forgot_password_verify')


def forgot_password_reset_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
        
    email = request.session.get('forgot_password_email')
    verified = request.session.get('forgot_password_verified')
    
    if not email or not verified:
        messages.error(request, "Access denied. Please complete verification first.")
        return redirect('forgot_password')
        
    user = User.objects.filter(email=email).first()
    if not user:
        messages.error(request, "User associated with this email no longer exists.")
        return redirect('forgot_password')
        
    errors = []
    if request.method == 'POST':
        new_password1 = request.POST.get('new_password1')
        new_password2 = request.POST.get('new_password2')
        
        if not new_password1 or not new_password2:
            errors.append("Both password fields are required.")
        elif new_password1 != new_password2:
            errors.append("Passwords do not match.")
        else:
            # Validate password strength using Django validators
            from django.contrib.auth.password_validation import validate_password
            from django.core.exceptions import ValidationError
            try:
                validate_password(new_password1, user)
            except ValidationError as ve:
                errors.extend(ve.messages)
                
        if not errors:
            user.set_password(new_password1)
            user.save()
            
            # Log audit activity
            log_activity(user, "Reset account password via Forgot Password OTP flow", request)
            
            # Clean up forgot password session keys
            del request.session['forgot_password_email']
            del request.session['forgot_password_otp']
            del request.session['forgot_password_otp_time']
            if 'forgot_password_verified' in request.session:
                del request.session['forgot_password_verified']
                
            messages.success(request, "Your password has been successfully reset! You can now log in.")
            return redirect('login')
            
    return render(request, 'caresync/forgot_password_reset.html', {'errors': errors})

def logout_view(request):
    if request.user.is_authenticated:
        log_activity(request.user, "Logged out", request)
        logout(request)
        messages.success(request, "You have been logged out.")
    return redirect('index')

@login_required
def change_password_view(request):
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  # Keep session active
            log_activity(user, "Changed password", request)
            messages.success(request, 'Your password was successfully updated!')
            return redirect('settings')
        else:
            messages.error(request, 'Please correct the error below.')
    else:
        form = PasswordChangeForm(request.user)
    return render(request, 'caresync/change_password.html', {'form': form})

# Dashboard Router
@login_required
def dashboard(request):
    if request.user.is_superuser:
        return redirect('admin_dashboard')
    elif hasattr(request.user, 'profile') and request.user.profile.role == 'doctor':
        return redirect('doctor_dashboard')
    return redirect('user_dashboard')

# User Dashboard
@login_required
def user_dashboard(request):
    appointments = Appointment.objects.filter(patient=request.user).order_by('-appointment_date')[:5]
    records = MedicalRecord.objects.filter(patient=request.user).order_by('-uploaded_at')[:5]
    notifications = Notification.objects.filter(
        Q(recipient=request.user) | Q(recipient=None)
    ).exclude(
        Q(title__startswith="New Contact Inquiry:") | Q(title="New Appointment Scheduled")
    ).exclude(
        dismissed_by=request.user
    ).order_by('-created_at')[:5]
    
    # Form handling
    if request.method == 'POST':
        if 'create_ticket' in request.POST:
            subject = request.POST.get('subject')
            description = request.POST.get('description')
            HelpTicket.objects.create(user=request.user, subject=subject, description=description)
            log_activity(request.user, f"Created a support ticket: {subject}", request)
            messages.success(request, "Support ticket created successfully!")
            return redirect('user_dashboard')
        else:
            form = AppointmentForm(request.POST)
            if form.is_valid():
                app = form.save(commit=False)
                app.patient = request.user
                app.save()
                log_activity(request.user, f"Booked an appointment in {app.department}", request)
                
                # Send admin notification
                Notification.objects.create(
                    recipient=None,
                    title="New Appointment Scheduled",
                    message=f"Patient {request.user.username} scheduled an appointment for {app.appointment_date} in {app.department}."
                )
                messages.success(request, "Appointment requested successfully!")
                return redirect('user_dashboard')
    else:
        form = AppointmentForm()
        
    help_tickets = HelpTicket.objects.filter(user=request.user).order_by('-created_at')

    context = {
        'appointments': appointments,
        'records': records,
        'notifications': notifications,
        'appointment_form': form,
        'help_tickets': help_tickets,
    }
    return render(request, 'caresync/user_dashboard.html', context)

# Admin Dashboard
@login_required
@user_passes_test(lambda u: u.is_superuser)
def admin_dashboard(request):
    total_patients = User.objects.filter(is_superuser=False, profile__role='patient').count()
    total_doctors = User.objects.filter(is_superuser=False, profile__role='doctor').count()
    total_appointments = Appointment.objects.count()
    pending_appointments = Appointment.objects.filter(status='Pending').count()
    total_records = MedicalRecord.objects.count()
    
    recent_appointments = Appointment.objects.order_by('-created_at')[:5]
    recent_users = User.objects.filter(is_superuser=False).order_by('-date_joined')[:5]
    activity_logs = ActivityLog.objects.order_by('-timestamp')[:5]
    all_users_list = User.objects.filter(is_superuser=False).select_related('profile').order_by('first_name', 'last_name', 'username')

    context = {
        'total_patients': total_patients,
        'total_doctors': total_doctors,
        'total_appointments': total_appointments,
        'pending_appointments': pending_appointments,
        'total_records': total_records,
        'recent_appointments': recent_appointments,
        'recent_users': recent_users,
        'activity_logs': activity_logs,
        'all_users_list': all_users_list,
    }
    return render(request, 'caresync/admin_dashboard.html', context)


@login_required
@user_passes_test(lambda u: u.is_superuser)
def user_delete_dashboard(request):
    if request.method == 'POST':
        user_id = request.POST.get('delete_user_id')
        if user_id:
            user_obj = get_object_or_404(User, id=user_id, is_superuser=False)
            username = user_obj.username
            log_activity(request.user, f"Deleted user profile from dashboard: {username}", request)
            user_obj.delete()
            messages.success(request, f"User {username} deleted successfully.")
    return redirect('admin_dashboard')


# Doctor Dashboard
@login_required
def doctor_dashboard(request):
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'doctor':
        messages.error(request, "Access denied. Only doctors can view this page.")
        return redirect('dashboard')
        
    doctor_profile = request.user.profile
    if not doctor_profile.is_approved:
        return render(request, 'caresync/pending_verification.html')
        
    hospital = doctor_profile.hospital
    department = doctor_profile.department
    
    # Get appointments booked at this doctor's hospital and department
    appointments = Appointment.objects.filter(hospital=hospital, department=department).order_by('-appointment_date')
    
    # Get unique patients who have appointments here
    patient_ids = appointments.values_list('patient_id', flat=True).distinct()
    patients = User.objects.filter(id__in=patient_ids).select_related('profile')
    
    # Get all reports uploaded by these patients
    records = MedicalRecord.objects.filter(patient__in=patients).order_by('-uploaded_at')
    
    # Manage appointment status changes by doctor
    if request.method == 'POST' and 'update_app_id' in request.POST:
        app_id = request.POST.get('update_app_id')
        new_status = request.POST.get('status')
        doctor_notes = request.POST.get('notes', '')
        
        app = get_object_or_404(Appointment, id=app_id, hospital=hospital, department=department)
        app.status = new_status
        app.notes = doctor_notes
        app.doctor = request.user
        app.save()
        
        log_activity(request.user, f"Updated appointment #{app.id} status to {new_status}", request)
        
        # Send patient notification
        Notification.objects.create(
            recipient=app.patient,
            title="Appointment Status Updated",
            message=f"Your appointment in {app.department} on {app.appointment_date} has been {new_status}. Notes: {doctor_notes}"
        )
        messages.success(request, f"Appointment status updated to {new_status} successfully!")
        return redirect('doctor_dashboard')

    # Manage records remarks
    if request.method == 'POST' and 'update_record_id' in request.POST:
        rec_id = request.POST.get('update_record_id')
        doctor_remarks = request.POST.get('doctor_remarks', '')
        
        # Restrict to records belonging to patients within the doctor's queue
        rec = get_object_or_404(MedicalRecord, id=rec_id, patient__in=patients)
        rec.doctor_remarks = doctor_remarks
        rec.save()
        
        log_activity(request.user, f"Added remark to record #{rec.id}", request)
        
        # Create a notification for the patient
        Notification.objects.create(
            recipient=rec.patient,
            title="Medical Record Remarks Updated",
            message=f"Doctor {request.user.username} has updated remarks on your medical record '{rec.title}'."
        )
        
        messages.success(request, "Report remark saved successfully!")
        return redirect('doctor_dashboard')

    context = {
        'hospital': hospital,
        'department': department,
        'appointments': appointments,
        'patients': patients,
        'records': records,
    }
    return render(request, 'caresync/doctor_dashboard.html', context)


# Download Patient Profile Summary PDF
@login_required
def download_patient_summary(request, patient_id):
    # Restrict to doctor, admin, or the patient themselves
    is_doctor = hasattr(request.user, 'profile') and request.user.profile.role == 'doctor'
    is_self = request.user.id == patient_id
    if not (request.user.is_superuser or is_doctor or is_self):
        messages.error(request, "Access denied.")
        return redirect('dashboard')
        
    # Security check: Doctors can only access patients in their consulting queue
    if is_doctor and not request.user.is_superuser:
        doctor_profile = request.user.profile
        has_appointment = Appointment.objects.filter(
            patient_id=patient_id,
            hospital=doctor_profile.hospital,
            department=doctor_profile.department
        ).exists()
        if not has_appointment:
            messages.error(request, "Access denied. You can only access patient charts from your department and hospital.")
            return redirect('doctor_dashboard')
        
    patient = get_object_or_404(User, id=patient_id, is_superuser=False)
    profile = patient.profile
    
    # Compile reports data
    records = MedicalRecord.objects.filter(patient=patient).order_by('-uploaded_at')
    appointments = Appointment.objects.filter(patient=patient).order_by('-appointment_date')
    
    # PDF generation using ReportLab
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="patient_{patient.username}_summary.pdf"'
    
    doc = SimpleDocTemplate(response, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    story = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=20, textColor=colors.HexColor('#0d9488'), spaceAfter=15)
    section_style = ParagraphStyle('Section', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=12, textColor=colors.HexColor('#1f2937'), spaceBefore=12, spaceAfter=8)
    body_style = ParagraphStyle('Body', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=14)
    
    # Table cell paragraph styles
    table_cell_style = ParagraphStyle(
        'SummaryTableCell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=11,
        textColor=colors.HexColor('#374151')
    )
    table_header_style = ParagraphStyle(
        'SummaryTableHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=11,
        textColor=colors.HexColor('#111827')
    )
    info_address_style = ParagraphStyle(
        'SummaryAddressCell',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=13,
        textColor=colors.HexColor('#000000')
    )
    
    story.append(Paragraph("CareSync Patient Medical Summary", title_style))
    story.append(Spacer(1, 10))
    
    # Personal Info Table
    info_data = [
        ["Patient Name:", f"{patient.first_name} {patient.last_name}", "Username:", f"@{patient.username}"],
        ["Email:", patient.email, "Phone:", profile.phone or "N/A"],
        ["Date of Birth:", str(profile.date_of_birth or "N/A"), "Gender:", profile.get_gender_display() or "N/A"],
        ["Blood Group:", profile.blood_group or "N/A", "Emergency Contact:", profile.emergency_contact or "N/A"],
        ["Address:", Paragraph(profile.address or "N/A", info_address_style), "", ""]
    ]
    t_info = Table(info_data, colWidths=[110, 150, 110, 150])
    t_info.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('TEXTCOLOR', (0,0), (0,-1), colors.HexColor('#64748b')),
        ('TEXTCOLOR', (2,0), (2,-1), colors.HexColor('#64748b')),
        ('FONTNAME', (1,0), (1,-1), 'Helvetica-Bold'),
        ('FONTNAME', (3,0), (3,-1), 'Helvetica-Bold'),
        ('SPAN', (1,4), (3,4)),
    ]))
    story.append(t_info)
    story.append(Spacer(1, 15))
    
    # Appointments History Table
    story.append(Paragraph("Consultations History", section_style))
    if appointments.exists():
        app_data = [[
            Paragraph("Date & Time", table_header_style), 
            Paragraph("Hospital Location", table_header_style), 
            Paragraph("Department", table_header_style), 
            Paragraph("Symptoms", table_header_style), 
            Paragraph("Status", table_header_style)
        ]]
        for app in appointments:
            hosp_name = app.get_hospital_display() if hasattr(app, 'get_hospital_display') else app.hospital
            app_data.append([
                Paragraph(app.appointment_date.strftime("%Y-%m-%d %H:%M"), table_cell_style),
                Paragraph(hosp_name, table_cell_style),
                Paragraph(app.department, table_cell_style),
                Paragraph(app.symptoms, table_cell_style),
                Paragraph(app.status, table_cell_style)
            ])
        t_app = Table(app_data, colWidths=[90, 150, 100, 120, 60])
        t_app.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f3f4f6')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e5e7eb')),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('TOPPADDING', (0,0), (-1,-1), 5),
        ]))
        story.append(t_app)
    else:
        story.append(Paragraph("No scheduled appointments found.", body_style))
    story.append(Spacer(1, 15))
    
    # Uploaded Documents Table
    story.append(Paragraph("Uploaded Medical Documents", section_style))
    if records.exists():
        rec_data = [["Document Title", "Category", "Uploaded At", "AI Scan"]]
        for r in records:
            ai_status = "-"
            if r.file_type == 'X-Ray' and r.ai_analyzed:
                ai_status = "Fracture" if r.ai_has_fracture else "Intact"
            rec_data.append([
                r.title,
                r.file_type,
                r.uploaded_at.strftime("%Y-%m-%d %H:%M"),
                ai_status
            ])
        t_rec = Table(rec_data, colWidths=[200, 100, 120, 100])
        t_rec.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f3f4f6')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor('#111827')),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e5e7eb')),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('TOPPADDING', (0,0), (-1,-1), 5),
        ]))
        story.append(t_rec)
    else:
        story.append(Paragraph("No uploaded documents archived.", body_style))
        
    doc.build(story)
    return response


# Download all patient files in a ZIP package
@login_required
def download_all_patient_files(request, patient_id):
    # Restrict to doctor or admin
    is_doctor = hasattr(request.user, 'profile') and request.user.profile.role == 'doctor'
    if not (request.user.is_superuser or is_doctor):
        messages.error(request, "Access denied.")
        return redirect('dashboard')
        
    # Security check: Doctors can only access patients in their consulting queue
    if is_doctor and not request.user.is_superuser:
        doctor_profile = request.user.profile
        has_appointment = Appointment.objects.filter(
            patient_id=patient_id,
            hospital=doctor_profile.hospital,
            department=doctor_profile.department
        ).exists()
        if not has_appointment:
            messages.error(request, "Access denied. You can only access patient files from your department and hospital.")
            return redirect('doctor_dashboard')
        
    patient = get_object_or_404(User, id=patient_id, is_superuser=False)
    records = MedicalRecord.objects.filter(patient=patient)
    
    if not records.exists():
        messages.error(request, "This patient does not have any uploaded records to download.")
        return redirect('doctor_dashboard' if is_doctor else 'user_management')
        
    import zipfile
    import io
    
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zip_file:
        for r in records:
            if r.file and os.path.exists(r.file.path):
                # Write file using its basename or title
                ext = os.path.splitext(r.file.path)[1]
                safe_title = "".join(c for c in r.title if c.isalnum() or c in (' ', '_', '-')).strip()
                safe_title = safe_title.replace(' ', '_')
                arcname = f"{safe_title}{ext}"
                zip_file.write(r.file.path, arcname=arcname)
                
    response = HttpResponse(buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="patient_{patient.username}_records.zip"'
    return response


# Profile Views
@login_required
def profile_view(request):
    if request.method == 'POST' and 'profile_pic' in request.FILES:
        profile = request.user.profile
        profile.profile_pic = request.FILES['profile_pic']
        profile.save()
        log_activity(request.user, "Updated profile picture directly", request)
        messages.success(request, "Profile picture updated successfully!")
        return redirect('profile')
    return render(request, 'caresync/profile.html')

@login_required
def edit_profile(request):
    if request.method == 'POST':
        u_form = UserEditForm(request.POST, instance=request.user)
        p_form = ProfileEditForm(request.POST, request.FILES, instance=request.user.profile)
        if u_form.is_valid() and p_form.is_valid():
            u_form.save()
            p_form.save()
            log_activity(request.user, "Updated profile information", request)
            messages.success(request, "Your profile has been updated!")
            return redirect('profile')
    else:
        u_form = UserEditForm(instance=request.user)
        p_form = ProfileEditForm(instance=request.user.profile)
    return render(request, 'caresync/edit_profile.html', {'u_form': u_form, 'p_form': p_form})

# Admin: User Management (CRUD)
@login_required
@user_passes_test(lambda u: u.is_superuser)
def user_management(request):
    if request.method == 'POST' and 'verify_doctor_id' in request.POST:
        doctor_id = request.POST.get('verify_doctor_id')
        doctor_profile = get_object_or_404(Profile, user_id=doctor_id, role='doctor')
        doctor_profile.is_approved = True
        doctor_profile.save()
        log_activity(request.user, f"Verified doctor credentials for @{doctor_profile.user.username}", request)
        messages.success(request, f"Doctor {doctor_profile.user.first_name} {doctor_profile.user.last_name} verified successfully!")
        return redirect('user_management')

    query = request.GET.get('q', '')
    users = User.objects.filter(is_superuser=False).select_related('profile')
    if query:
        users = users.filter(
            Q(username__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(email__icontains=query) |
            Q(profile__phone__icontains=query)
        )
    
    patients = users.filter(profile__role='patient')
    doctors = users.filter(profile__role='doctor')
    
    return render(request, 'caresync/user_management.html', {
        'patients': patients,
        'doctors': doctors,
        'query': query
    })

@login_required
@user_passes_test(lambda u: u.is_superuser)
def user_create(request):
    if request.method == 'POST':
        form = PatientSignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            log_activity(request.user, f"Created user profile: {user.username}", request)
            messages.success(request, f"User {user.username} created successfully!")
            return redirect('user_management')
    else:
        form = PatientSignupForm()
    return render(request, 'caresync/user_form.html', {'form': form, 'title': 'Create Patient Profile'})

@login_required
@user_passes_test(lambda u: u.is_superuser)
def user_edit(request, user_id):
    user_obj = get_object_or_404(User, id=user_id, is_superuser=False)
    if request.method == 'POST':
        u_form = UserEditForm(request.POST, instance=user_obj)
        p_form = ProfileEditForm(request.POST, request.FILES, instance=user_obj.profile)
        if u_form.is_valid() and p_form.is_valid():
            u_form.save()
            p_form.save()
            log_activity(request.user, f"Edited user profile: {user_obj.username}", request)
            messages.success(request, f"User {user_obj.username} updated successfully!")
            return redirect('user_management')
    else:
        u_form = UserEditForm(instance=user_obj)
        p_form = ProfileEditForm(instance=user_obj.profile)
    return render(request, 'caresync/user_form.html', {'u_form': u_form, 'p_form': p_form, 'title': f"Edit Profile: {user_obj.username}"})

@login_required
@user_passes_test(lambda u: u.is_superuser)
def user_delete(request, user_id):
    user_obj = get_object_or_404(User, id=user_id, is_superuser=False)
    username = user_obj.username
    log_activity(request.user, f"Deleted user profile: {username}", request)
    user_obj.delete()
    messages.success(request, f"User {username} deleted successfully.")
    return redirect('user_management')

# File Upload & Data Management
@login_required
def upload_files(request):
    if request.method == 'POST':
        form = MedicalRecordForm(request.POST, request.FILES)
        if form.is_valid():
            record = form.save(commit=False)
            record.patient = request.user
            record.save()
            log_activity(request.user, f"Uploaded medical document: {record.title}", request)
            messages.success(request, "Document uploaded successfully!")
            return redirect('data_management')
    else:
        form = MedicalRecordForm()
    return render(request, 'caresync/upload_files.html', {'form': form})

@login_required
def data_management(request):
    # Patient sees their own files, Admin sees everything
    if request.user.is_superuser:
        records = MedicalRecord.objects.all().order_by('-uploaded_at')
    else:
        records = MedicalRecord.objects.filter(patient=request.user).order_by('-uploaded_at')
        
    if request.method == 'POST' and 'delete_id' in request.POST:
        rec_id = request.POST.get('delete_id')
        if request.user.is_superuser:
            rec = get_object_or_404(MedicalRecord, id=rec_id)
        else:
            rec = get_object_or_404(MedicalRecord, id=rec_id, patient=request.user)
        log_activity(request.user, f"Deleted medical document: {rec.title}", request)
        rec.delete()
        messages.success(request, "Document deleted successfully.")
        return redirect('data_management')
        
    return render(request, 'caresync/data_management.html', {'records': records})

# AI Fracture Detector Page
@login_required
def xray_analysis(request):
    if request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.role == 'doctor'):
        messages.error(request, "Access denied. Only patients can run AI scan analysis.")
        return redirect('dashboard')

    # Get recent X-ray uploads
    xrays = MedicalRecord.objects.filter(patient=request.user, file_type='X-Ray').order_by('-uploaded_at')

    # Execute AI Scan view
    if request.method == 'POST' and 'delete_id' in request.POST:
        rec_id = request.POST.get('delete_id')
        record = get_object_or_404(MedicalRecord, id=rec_id, patient=request.user, file_type='X-Ray')
        log_activity(request.user, f"Deleted medical document from AI scanner: {record.title}", request)
        record.delete()
        messages.success(request, "X-Ray scan deleted successfully.")
        return redirect('xray_analysis')

    if request.method == 'POST' and 'run_ai_id' in request.POST:
        rec_id = request.POST.get('run_ai_id')
        record = get_object_or_404(MedicalRecord, id=rec_id, patient=request.user, file_type='X-Ray')
            
        # Call AI analyzer script
        has_frac, conf, out_rel, desc = detect_fracture(record.file.path)
        
        # Save results in model
        record.ai_analyzed = True
        record.ai_has_fracture = has_frac
        record.ai_result = f"Confidence: {conf}% | Findings: {desc} | Overlay: {out_rel}"
        record.save()
        
        # Log audit
        log_activity(request.user, f"Triggered AI Fracture scan on record ID #{record.id}", request)
        messages.success(request, f"AI Analysis completed for {record.title}!")
        return redirect('xray_analysis')

    # Upload & Analyze immediately in one action
    if request.method == 'POST' and 'xray_file' in request.FILES:
        title = request.POST.get('title', 'X-Ray Scan')
        xray_file = request.FILES['xray_file']
        
        record = MedicalRecord.objects.create(
            patient=request.user,
            title=title,
            file=xray_file,
            file_type='X-Ray'
        )
        
        has_frac, conf, out_rel, desc = detect_fracture(record.file.path)
        record.ai_analyzed = True
        record.ai_has_fracture = has_frac
        record.ai_result = f"Confidence: {conf}% | Findings: {desc} | Overlay: {out_rel}"
        record.save()
        
        log_activity(request.user, f"Uploaded & Scanned X-Ray ID #{record.id}", request)
        messages.success(request, "X-Ray uploaded and analyzed successfully!")
        return redirect('xray_analysis')

    parsed_xrays = []
    for xr in xrays:
        meta = {}
        if xr.ai_analyzed and xr.ai_result:
            parts = xr.ai_result.split(' | ')
            for p in parts:
                if p.startswith("Confidence:"):
                    meta['confidence'] = p.replace("Confidence: ", "")
                elif p.startswith("Findings:"):
                    meta['findings'] = p.replace("Findings: ", "")
                elif p.startswith("Overlay:"):
                    meta['overlay'] = p.replace("Overlay: ", "")
        parsed_xrays.append({'record': xr, 'meta': meta})

    return render(request, 'caresync/xray_analysis.html', {'xrays': parsed_xrays})

# Notifications & Broadcast Builder
@login_required
def notifications_view(request):
    if request.user.is_superuser:
        if request.method == 'POST' and request.POST.get('action') == 'clear_all':
            active_notifications = Notification.objects.exclude(dismissed_by=request.user)
            for notif in active_notifications:
                notif.dismissed_by.add(request.user)
            messages.success(request, "Alert feed cleared successfully!")
            return redirect('notifications')

        notifications = Notification.objects.exclude(dismissed_by=request.user).order_by('-created_at')
        if request.method == 'POST':
            form = NotificationForm(request.POST)
            if form.is_valid():
                notif = form.save()
                log_activity(request.user, f"Dispatched notification: {notif.title}", request)
                messages.success(request, "Notification sent successfully!")
                return redirect('notifications')
        else:
            form = NotificationForm()
        context = {'notifications': notifications, 'form': form}
    else:
        if request.method == 'POST' and request.POST.get('action') == 'clear_all':
            active_notifications = Notification.objects.filter(
                Q(recipient=request.user) | Q(recipient=None)
            ).exclude(
                Q(title__startswith="New Contact Inquiry:") | Q(title="New Appointment Scheduled")
            ).exclude(
                dismissed_by=request.user
            )
            for notif in active_notifications:
                notif.dismissed_by.add(request.user)
            messages.success(request, "Alert feed cleared successfully!")
            return redirect('notifications')

        notifications = Notification.objects.filter(
            Q(recipient=request.user) | Q(recipient=None)
        ).exclude(
            Q(title__startswith="New Contact Inquiry:") | Q(title="New Appointment Scheduled")
        ).exclude(
            dismissed_by=request.user
        ).order_by('-created_at')
        # Mark all as read when loaded
        unread = notifications.filter(is_read=False)
        unread.update(is_read=True)
        context = {'notifications': notifications}
        
    return render(request, 'caresync/notifications.html', context)

# Reports Summary Page
@login_required
def reports_view(request):
    is_doctor = hasattr(request.user, 'profile') and request.user.profile.role == 'doctor'
    if request.user.is_superuser:
        appointments = Appointment.objects.all().order_by('-appointment_date')
        records = MedicalRecord.objects.all()
    elif is_doctor:
        doctor_profile = request.user.profile
        hospital = doctor_profile.hospital
        department = doctor_profile.department
        appointments = Appointment.objects.filter(hospital=hospital, department=department).order_by('-appointment_date')
        patient_ids = appointments.values_list('patient_id', flat=True).distinct()
        records = MedicalRecord.objects.filter(patient_id__in=patient_ids).order_by('-uploaded_at')
    else:
        appointments = Appointment.objects.filter(patient=request.user).order_by('-appointment_date')
        records = MedicalRecord.objects.filter(patient=request.user)
    return render(request, 'caresync/reports.html', {'appointments': appointments, 'records': records})

# PDF report builder download
@login_required
def download_pdf_report(request):
    is_doctor = hasattr(request.user, 'profile') and request.user.profile.role == 'doctor'
    
    # If the user is a patient, download their own summary report
    if not (request.user.is_superuser or is_doctor):
        return download_patient_summary(request, request.user.id)

    if is_doctor:
        doctor_profile = request.user.profile
        hospital = doctor_profile.hospital
        department = doctor_profile.department
        
        appointments = Appointment.objects.filter(hospital=hospital, department=department).order_by('-appointment_date')
        patient_ids = appointments.values_list('patient_id', flat=True).distinct()
        patients = User.objects.filter(id__in=patient_ids).select_related('profile')
        
        pdf_dir = os.path.join(settings.BASE_DIR, 'scratch')
        os.makedirs(pdf_dir, exist_ok=True)
        pdf_path = os.path.join(pdf_dir, f'doctor_report_{request.user.username}.pdf')
        
        generate_doctor_report_pdf(pdf_path, request.user, appointments, patients)
        
        with open(pdf_path, 'rb') as pdf:
            response = HttpResponse(pdf.read(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="doctor_{request.user.username}_report.pdf"'
            return response

    # Assemble statistics for table
    total_patients = User.objects.filter(is_superuser=False, profile__role='patient').count()
    total_doctors = User.objects.filter(is_superuser=False, profile__role='doctor').count()
    total_appointments = Appointment.objects.count()
    pending_appointments = Appointment.objects.filter(status='Pending').count()
    completed_appointments = Appointment.objects.filter(status='Completed').count()
    total_records = MedicalRecord.objects.count()
    ai_scans = MedicalRecord.objects.filter(ai_analyzed=True).count()
    
    recent_apps_qs = Appointment.objects.order_by('-created_at')[:8]
    recent_appointments = []
    for r in recent_apps_qs:
        recent_appointments.append({
            'patient': r.patient.username,
            'date': r.appointment_date.strftime("%Y-%m-%d %H:%M"),
            'department': r.department,
            'symptoms': r.symptoms,
            'status': r.status
        })
        
    data = {
        'total_patients': total_patients,
        'total_doctors': total_doctors,
        'total_appointments': total_appointments,
        'pending_appointments': pending_appointments,
        'completed_appointments': completed_appointments,
        'total_records': total_records,
        'ai_scans': ai_scans,
        'recent_appointments': recent_appointments
    }
    
    # Write to memory or temp file
    pdf_dir = os.path.join(settings.BASE_DIR, 'scratch')
    os.makedirs(pdf_dir, exist_ok=True)
    pdf_path = os.path.join(pdf_dir, 'caresync_report.pdf')
    
    generate_clinic_pdf(
        pdf_path,
        "CareSync Clinic Operations Report",
        f"Generated on {timezone.now().strftime('%Y-%m-%d %H:%M:%S')} UTC | Requested by {request.user.username}",
        data
    )
    
    with open(pdf_path, 'rb') as pdf:
        response = HttpResponse(pdf.read(), content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="caresync_report.pdf"'
        return response

# Analytics Charts Page
@login_required
def analytics_view(request):
    # Retrieve details for dynamic charts
    # 1. Appointments per department
    dept_labels = ['General Medicine', 'Cardiology', 'Pediatrics', 'Orthopedics', 'Dermatology', 'Neurology']
    dept_counts = []
    for dept in dept_labels:
        dept_counts.append(Appointment.objects.filter(department=dept).count())
        
    # 2. Appointments status
    status_labels = ['Pending', 'Confirmed', 'Cancelled', 'Completed']
    status_counts = []
    for s in status_labels:
        status_counts.append(Appointment.objects.filter(status=s).count())

    # 3. Monthly signups (Patients and Doctors separated)
    patient_monthly_counts = [0] * 12
    doctor_monthly_counts = [0] * 12
    for user in User.objects.filter(is_superuser=False).select_related('profile'):
        month = user.date_joined.month
        if user.profile.role == 'doctor':
            doctor_monthly_counts[month-1] += 1
        else:
            patient_monthly_counts[month-1] += 1
        
    context = {
        'dept_labels': dept_labels,
        'dept_counts': dept_counts,
        'status_labels': status_labels,
        'status_counts': status_counts,
        'patient_monthly_counts': patient_monthly_counts,
        'doctor_monthly_counts': doctor_monthly_counts,
    }
    return render(request, 'caresync/analytics.html', context)

# Activity Logs Viewer
@login_required
def activity_logs_view(request):
    if request.user.is_superuser:
        if request.method == 'POST':
            action = request.POST.get('action')
            if action == 'delete_log':
                log_id = request.POST.get('log_id')
                log_item = get_object_or_404(ActivityLog, id=log_id)
                log_item.delete()
                messages.success(request, "Audit log entry deleted successfully.")
                return redirect('activity_logs')
            elif action == 'clear_all_logs':
                ActivityLog.objects.all().delete()
                log_activity(request.user, "Purged entire security audit logs history trail", request)
                messages.success(request, "Entire security audit trail purged successfully.")
                return redirect('activity_logs')
        logs = ActivityLog.objects.all().order_by('-timestamp')
    else:
        logs = ActivityLog.objects.filter(user=request.user).order_by('-timestamp')
    return render(request, 'caresync/activity_logs.html', {'logs': logs})

# Multi-criteria search
@login_required
def search_view(request):
    query = request.GET.get('q', '')
    records = MedicalRecord.objects.none()
    appointments = Appointment.objects.none()
    
    if query:
        if request.user.is_superuser:
            records = MedicalRecord.objects.filter(Q(title__icontains=query) | Q(file_type__icontains=query) | Q(patient__username__icontains=query))
            appointments = Appointment.objects.filter(Q(department__icontains=query) | Q(symptoms__icontains=query) | Q(patient__username__icontains=query))
        else:
            records = MedicalRecord.objects.filter(patient=request.user).filter(Q(title__icontains=query) | Q(file_type__icontains=query))
            appointments = Appointment.objects.filter(patient=request.user).filter(Q(department__icontains=query) | Q(symptoms__icontains=query))
            
    return render(request, 'caresync/search.html', {'records': records, 'appointments': appointments, 'query': query})

# Appointment & Upload timelines
@login_required
def history_view(request):
    if request.user.is_superuser:
        appointments = Appointment.objects.all().order_by('-appointment_date')
    else:
        appointments = Appointment.objects.filter(patient=request.user).order_by('-appointment_date')
    return render(request, 'caresync/history.html', {'appointments': appointments})

# Help desk & Support center
@login_required
def help_center(request):
    tickets = HelpTicket.objects.filter(user=request.user).order_by('-created_at')
    if request.method == 'POST':
        form = HelpTicketForm(request.POST)
        if form.is_valid():
            t = form.save(commit=False)
            t.user = request.user
            t.save()
            log_activity(request.user, f"Opened help ticket #{t.user_ticket_num}: {t.subject}", request)
            messages.success(request, "Support ticket submitted successfully!")
            return redirect('help_center')
    else:
        form = HelpTicketForm()
    return render(request, 'caresync/help_center.html', {'tickets': tickets, 'form': form})

# Feedback Center
@login_required
def feedback_view(request):
    # Patient submits feedback
    if request.method == 'POST':
        form = FeedbackForm(request.POST)
        if form.is_valid():
            f = form.save(commit=False)
            f.user = request.user
            f.save()
            log_activity(request.user, "Submitted platform feedback", request)
            messages.success(request, "Thank you for your feedback!")
            return redirect('feedback')
    else:
        form = FeedbackForm()
        
    feedbacks = Feedback.objects.all().order_by('-created_at')
    return render(request, 'caresync/feedback.html', {'feedbacks': feedbacks, 'form': form})

# Settings Settings Dashboard
@login_required
def settings_view(request):
    return render(request, 'caresync/settings.html')

# Message inbox/queries (Admin)
@login_required
@user_passes_test(lambda u: u.is_superuser)
def messages_view(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        
        # 1. Delete single client inquiry (Notification)
        if action == 'delete_inquiry':
            inquiry_id = request.POST.get('inquiry_id')
            inquiry = get_object_or_404(Notification, id=inquiry_id, recipient=None, title__startswith="New Contact Inquiry:")
            inquiry.delete()
            log_activity(request.user, f"Deleted client contact inquiry ID #{inquiry_id}", request)
            messages.success(request, "Inquiry deleted successfully.")
            return redirect('messages')
            
        # 2. Purge all client inquiries
        elif action == 'purge_inquiries':
            deleted_count, _ = Notification.objects.filter(recipient=None, title__startswith="New Contact Inquiry:").delete()
            log_activity(request.user, f"Purged all client inquiries ({deleted_count} deleted)", request)
            messages.success(request, f"Successfully deleted {deleted_count} inquiries.")
            return redirect('messages')
            
        # 3. Existing Ticket Response handling
        elif 'ticket_id' in request.POST or action == 'ticket_action':
            ticket_id = request.POST.get('ticket_id')
            ticket = get_object_or_404(HelpTicket, id=ticket_id)
            
            if 'close_ticket' in request.POST:
                ticket.status = 'Resolved'
                ticket.save()
                
                # Create a notification for the patient
                Notification.objects.create(
                    recipient=ticket.user,
                    title=f"Ticket #{ticket.user_ticket_num} Resolved",
                    message=f"Your support ticket '{ticket.subject}' has been marked as Resolved by the administrator."
                )
                log_activity(request.user, f"Marked support ticket #{ticket.user_ticket_num} as Resolved", request)
                messages.success(request, f"Ticket #{ticket.user_ticket_num} has been marked as Resolved.")
                return redirect('messages')
                
            reply_content = request.POST.get('reply_content')
            ticket.admin_response = reply_content
            ticket.status = 'Resolved'
            ticket.save()
            
            # Create a notification for the patient
            Notification.objects.create(
                recipient=ticket.user,
                title=f"Reply to Ticket #{ticket.user_ticket_num}",
                message=f"Admin responded to your support ticket '{ticket.subject}': {reply_content}"
            )
            log_activity(request.user, f"Responded to support ticket #{ticket.user_ticket_num}", request)
            role_label = ticket.user.profile.role if hasattr(ticket.user, 'profile') else 'user'
            messages.success(request, f"Response sent to {role_label} @{ticket.user.username} successfully!")
            return redirect('messages')

    # We display contact-based global messages
    queries = Notification.objects.filter(recipient=None, title__startswith="New Contact Inquiry:").order_by('-created_at')
    tickets = HelpTicket.objects.all().order_by('-created_at')
    return render(request, 'caresync/messages.html', {'queries': queries, 'tickets': tickets})
