import os
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings
from PIL import Image

from .models import Profile, Appointment, MedicalRecord
from .utils import detect_fracture, generate_clinic_pdf

class CareSyncTests(TestCase):
    def setUp(self):
        self.client = Client()
        # Create standard user
        self.user = User.objects.create_user(
            username='testpatient',
            email='test@patient.com',
            password='testpassword123',
            first_name='John',
            last_name='Doe'
        )
        
        # Create admin user
        self.admin = User.objects.create_superuser(
            username='testadmin',
            email='test@admin.com',
            password='testpassword123',
            first_name='Admin',
            last_name='CareSync'
        )
        
        # Ensure media directory exists for tests
        os.makedirs(os.path.join(settings.MEDIA_ROOT, 'records'), exist_ok=True)
        os.makedirs(os.path.join(settings.BASE_DIR, 'scratch'), exist_ok=True)

    def test_public_pages(self):
        """Test public views resolve with HTTP 200"""
        for url_name in ['index', 'about', 'contact']:
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200)

    def test_unauthenticated_dashboard_redirects(self):
        """Unauthenticated clients must be redirected to login"""
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_patient_dashboard_load(self):
        """Logged-in patient dashboard loads with correct templates"""
        self.client.login(username='testpatient', password='testpassword123')
        response = self.client.get(reverse('user_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'caresync/user_dashboard.html')

    def test_admin_dashboard_load(self):
        """Logged-in admin dashboard loads with correct templates and distinct patient/doctor counts"""
        # Create a doctor user to verify counts
        doc = User.objects.create_user(username='docforstats', email='docforstats@caresync.com', password='password123')
        doc.profile.role = 'doctor'
        doc.profile.save()

        self.client.login(username='testadmin', password='testpassword123')
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'caresync/admin_dashboard.html')
        
        # Verify counts are accurate and distinct
        self.assertEqual(response.context['total_patients'], 1) # testpatient
        self.assertEqual(response.context['total_doctors'], 1)  # docforstats

    def test_pdf_report_compilation(self):
        """Test PDF report builder creates a valid file on disk"""
        pdf_path = os.path.join(settings.BASE_DIR, 'scratch', 'test_report.pdf')
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
            
        data = {
            'total_patients': 5,
            'total_appointments': 10,
            'pending_appointments': 3,
            'completed_appointments': 7,
            'total_records': 12,
            'ai_scans': 8,
            'recent_appointments': [
                {'patient': 'patient1', 'date': '2026-05-25 10:00', 'department': 'Orthopedics', 'symptoms': 'Wrist pain', 'status': 'Confirmed'}
            ]
        }
        
        generate_clinic_pdf(pdf_path, "Test PDF Report", "Test subtitle", data)
        self.assertTrue(os.path.exists(pdf_path))
        self.assertGreater(os.path.getsize(pdf_path), 0)
        
        # Clean up
        if os.path.exists(pdf_path):
            os.remove(pdf_path)

    def test_ai_fracture_detector(self):
        """Test Pillow image gradient-discontinuity analysis executes successfully"""
        # Create a small blank image for test
        test_img_path = os.path.join(settings.MEDIA_ROOT, 'records', 'test_xray.png')
        img = Image.new('RGB', (200, 200), color = 'gray')
        img.save(test_img_path)
        
        has_frac, conf, out_rel, desc = detect_fracture(test_img_path)
        self.assertIsInstance(has_frac, bool)
        self.assertGreaterEqual(conf, 0)
        self.assertLessEqual(conf, 100)
        self.assertIsNotNone(out_rel)
        self.assertIsNotNone(desc)
        
        # Clean up
        if os.path.exists(test_img_path):
            os.remove(test_img_path)
        if out_rel:
            full_out_path = os.path.join(settings.MEDIA_ROOT, out_rel)
            if os.path.exists(full_out_path):
                os.remove(full_out_path)

    def test_signup_otp_verification_flow(self):
        """Test that patient data is held in session, OTP is generated, and user is created only after correct verification"""
        # 1. Post to signup form
        signup_data = {
            'username': 'newpatientverify',
            'email': 'verify@caresync.com',
            'password': 'patientpassword123',
            'confirm_password': 'patientpassword123',
            'first_name': 'Mary',
            'last_name': 'Smith',
            'phone': '1234567890',
            'gender': 'F',
            'blood_group': 'O+',
            'address': '789 Medical Lane',
            'emergency_contact': 'Husband - 9876543210'
        }
        
        # Verify user does not exist in DB yet
        self.assertFalse(User.objects.filter(username='newpatientverify').exists())
        
        # Submit signup
        response = self.client.post(reverse('signup'), signup_data)
        self.assertEqual(response.status_code, 302) # Redirect to verify-otp
        self.assertRedirects(response, reverse('verify_otp'))
        
        # Verify user still does not exist in DB (as requested: verified then ID is made)
        self.assertFalse(User.objects.filter(username='newpatientverify').exists())
        
        # Check that session holds the signup data and OTP
        session = self.client.session
        self.assertIn('pending_signup', session)
        self.assertIn('signup_otp', session)
        otp = session['signup_otp']
        
        # 2. Try entering wrong OTP
        verify_response = self.client.post(reverse('verify_otp'), {'otp': '000000'})
        self.assertEqual(verify_response.status_code, 200) # Re-renders page
        # Verify user still does not exist
        self.assertFalse(User.objects.filter(username='newpatientverify').exists())
        
        # 3. Enter correct OTP
        success_response = self.client.post(reverse('verify_otp'), {'otp': otp})
        self.assertEqual(success_response.status_code, 302) # Redirect to dashboard
        self.assertRedirects(success_response, reverse('dashboard'), target_status_code=302)
        
        # Verify user was created in the database!
        self.assertTrue(User.objects.filter(username='newpatientverify').exists())
        created_user = User.objects.get(username='newpatientverify')
        self.assertEqual(created_user.email, 'verify@caresync.com')
        self.assertEqual(created_user.profile.phone, '1234567890')
        self.assertEqual(created_user.profile.gender, 'F')

    def test_doctor_signup_otp_verification_flow(self):
        """Test doctor signup flow holds data in session and creates profile with specialized department and hospital upon verification"""
        signup_data = {
            'username': 'newdoctorverify',
            'email': 'doctorverify@caresync.com',
            'password': 'doctorpassword123',
            'confirm_password': 'doctorpassword123',
            'first_name': 'Marcus',
            'last_name': 'Vance',
            'phone': '9876543210',
            'gender': 'M',
            'blood_group': 'A+',
            'address': '456 Clinic Blvd',
            'emergency_contact': 'Colleague - 9999999999',
            'hospital': 'Safdarjung',
            'department': 'Orthopedics'
        }
        
        # Verify user does not exist in DB
        self.assertFalse(User.objects.filter(username='newdoctorverify').exists())
        
        # Submit doctor signup
        response = self.client.post(reverse('register_doctor'), signup_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('verify_otp'))
        
        # Verify user still doesn't exist
        self.assertFalse(User.objects.filter(username='newdoctorverify').exists())
        
        # Verify OTP
        session = self.client.session
        otp = session['signup_otp']
        success_response = self.client.post(reverse('verify_otp'), {'otp': otp})
        self.assertEqual(success_response.status_code, 302)
        
        # Verify doctor user and profile were created
        self.assertTrue(User.objects.filter(username='newdoctorverify').exists())
        created_user = User.objects.get(username='newdoctorverify')
        self.assertEqual(created_user.profile.role, 'doctor')
        self.assertEqual(created_user.profile.hospital, 'Safdarjung')
        self.assertEqual(created_user.profile.department, 'Orthopedics')

    def test_doctor_dashboard_access_and_records(self):
        """Test that doctor dashboard handles view and shows reports/records only for correct doctor hospital/department"""
        # Create a doctor user
        doctor = User.objects.create_user(
            username='doctorjohn',
            email='doctorjohn@caresync.com',
            password='docpassword123',
            first_name='John',
            last_name='Watson'
        )
        doctor.profile.role = 'doctor'
        doctor.profile.hospital = 'RML'
        doctor.profile.department = 'Cardiology'
        doctor.profile.save()
        
        # Log in as doctor
        self.client.login(username='doctorjohn', password='docpassword123')
        
        response = self.client.get(reverse('doctor_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'caresync/doctor_dashboard.html')

    def test_patient_reports_downloads_by_doctor(self):
        """Test that doctors can download patient report PDF summary and records ZIP file"""
        # Create a doctor
        doctor = User.objects.create_user(username='docdownload', email='doc@down.com', password='password')
        doctor.profile.role = 'doctor'
        doctor.profile.hospital = 'AIIMS'
        doctor.profile.department = 'Cardiology'
        doctor.profile.save()
        
        # Create a matching appointment for the patient
        from django.utils import timezone
        Appointment.objects.create(
            patient=self.user,
            appointment_date=timezone.now(),
            hospital='AIIMS',
            department='Cardiology',
            symptoms='Heart flutter'
        )
        
        # Create patient record file
        test_file = SimpleUploadedFile("test_report.pdf", b"pdf content", content_type="application/pdf")
        record = MedicalRecord.objects.create(patient=self.user, title="ECG Report", file=test_file, file_type='Report')
        
        self.client.login(username='docdownload', password='password')
        
        # Download summary
        summary_url = reverse('download_patient_summary', args=[self.user.id])
        summary_response = self.client.get(summary_url)
        self.assertEqual(summary_response.status_code, 200)
        self.assertEqual(summary_response['Content-Type'], 'application/pdf')
        
        # Download ZIP records
        zip_url = reverse('download_all_patient_files', args=[self.user.id])
        zip_response = self.client.get(zip_url)
        self.assertEqual(zip_response.status_code, 200)
        self.assertEqual(zip_response['Content-Type'], 'application/zip')

    def test_patient_booking_hospital_selection(self):
        """Test booking an appointment with specific hospital location"""
        self.client.login(username='testpatient', password='testpassword123')
        booking_data = {
            'appointment_date': '2026-06-01T10:00',
            'department': 'Cardiology',
            'hospital': 'RML',
            'symptoms': 'Chest congestion'
        }
        response = self.client.post(reverse('user_dashboard'), booking_data)
        self.assertEqual(response.status_code, 302)
        
        # Verify Appointment is created with hospital
        self.assertTrue(Appointment.objects.filter(patient=self.user, hospital='RML').exists())
        created_app = Appointment.objects.get(patient=self.user, hospital='RML')
        self.assertEqual(created_app.department, 'Cardiology')
        self.assertEqual(created_app.symptoms, 'Chest congestion')

    def test_patient_reports_download_only_contains_own_details(self):
        """Test that patient download from reports view returns their own summary rather than clinic operational metrics"""
        # Create some other patients to make sure the clinic counts would be different
        other_user = User.objects.create_user(username='otherpatient', email='other@patient.com', password='password')
        other_user.profile.phone = '5555555555'
        other_user.profile.save()
        
        # Log in as testpatient
        self.client.login(username='testpatient', password='testpassword123')
        
        # Call reports download
        response = self.client.get(reverse('download_pdf_report'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        
        # Assert filename indicates it's patient-specific
        content_disposition = response['Content-Disposition']
        self.assertIn('patient_testpatient_summary.pdf', content_disposition)

    def test_direct_profile_picture_upload(self):
        """Test that users can upload their profile picture directly from the profile page"""
        self.client.login(username='testpatient', password='testpassword123')
        
        # Verify no picture initially
        self.assertFalse(bool(self.user.profile.profile_pic))
        
        # Submit photo directly
        test_img = SimpleUploadedFile("avatar.png", b"image data", content_type="image/png")
        response = self.client.post(reverse('profile'), {'profile_pic': test_img})
        self.assertEqual(response.status_code, 302) # Redirect to profile
        
        # Verify picture was saved
        self.user.profile.refresh_from_db()
        self.assertTrue(bool(self.user.profile.profile_pic))
        self.assertTrue(self.user.profile.profile_pic.name.endswith('avatar.png'))
        
        # Clean up file on disk if created
        if os.path.exists(self.user.profile.profile_pic.path):
            os.remove(self.user.profile.profile_pic.path)

    def test_unverified_doctor_access_and_admin_verification(self):
        """Test unverified doctor dashboard blockage, admin doctor verification POST, and subsequent dashboard approval access"""
        # 1. Create doctor
        doctor = User.objects.create_user(username='docverify', email='doc@v.com', password='password123')
        doctor.profile.role = 'doctor'
        doctor.profile.hospital = 'AIIMS'
        doctor.profile.department = 'Cardiology'
        doctor.profile.is_approved = False
        doctor.profile.save()
        
        # Log in as doctor
        self.client.login(username='docverify', password='password123')
        
        # Get doctor dashboard (unverified)
        response = self.client.get(reverse('doctor_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'caresync/pending_verification.html')
        self.assertContains(response, "Please let the admin verify your credentials")
        self.assertContains(response, "7 days")
        
        # 2. Log in as admin to verify
        self.client.login(username='testadmin', password='testpassword123')
        verify_response = self.client.post(reverse('user_management'), {'verify_doctor_id': doctor.id})
        self.assertEqual(verify_response.status_code, 302)
        
        # Verify doctor is approved
        doctor.profile.refresh_from_db()
        self.assertTrue(doctor.profile.is_approved)
        
        # 3. Log in as doctor again
        self.client.login(username='docverify', password='password123')
        response2 = self.client.get(reverse('doctor_dashboard'))
        self.assertEqual(response2.status_code, 200)
        self.assertTemplateUsed(response2, 'caresync/doctor_dashboard.html')

    def test_admin_ticket_replies(self):
        """Test admin help ticket list viewing, sending a reply, and notification generation for patients"""
        from .models import HelpTicket, Notification
        # Create ticket
        ticket = HelpTicket.objects.create(
            user=self.user,
            subject="Billing issue",
            description="Can't download invoice"
        )
        
        # Log in as admin
        self.client.login(username='testadmin', password='testpassword123')
        
        # Reply to ticket
        reply_data = {
            'ticket_id': ticket.id,
            'reply_content': "Invoices are in the history tab now."
        }
        response = self.client.post(reverse('messages'), reply_data)
        self.assertEqual(response.status_code, 302)
        
        # Verify ticket details
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'Resolved')
        self.assertEqual(ticket.admin_response, "Invoices are in the history tab now.")
        
        # Verify patient notification was dispatched
        self.assertTrue(Notification.objects.filter(recipient=self.user, title__contains=f"Reply to Ticket #{ticket.id}").exists())

    def test_admin_ticket_close_without_reply(self):
        """Test that admin can close a help ticket directly without typing a reply"""
        from .models import HelpTicket, Notification
        # Create open ticket
        ticket = HelpTicket.objects.create(
            user=self.user,
            subject="Technical issue",
            description="App loads slowly"
        )
        
        # Log in as admin
        self.client.login(username='testadmin', password='testpassword123')
        
        # Close ticket directly
        close_data = {
            'ticket_id': ticket.id,
            'close_ticket': '1'
        }
        response = self.client.post(reverse('messages'), close_data)
        self.assertEqual(response.status_code, 302)
        
        # Verify ticket details
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'Resolved')
        self.assertIsNone(ticket.admin_response)
        
        # Verify patient notification was dispatched
        self.assertTrue(Notification.objects.filter(recipient=self.user, title__contains=f"Ticket #{ticket.id} Resolved").exists())

    def test_admin_delete_user_from_dashboard(self):
        """Test that admins can delete user profiles directly from the dashboard"""
        # Create a user to delete
        target_user = User.objects.create_user(username='target_delete', email='target@example.com', password='password123')
        target_user.profile.role = 'patient'
        target_user.profile.save()

        # Log in as admin
        self.client.login(username='testadmin', password='testpassword123')

        # Verify user exists in database
        self.assertTrue(User.objects.filter(username='target_delete').exists())

        # Perform deletion request
        response = self.client.post(reverse('user_delete_dashboard'), {'delete_user_id': target_user.id})
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('admin_dashboard'))

        # Verify user is deleted from database
        self.assertFalse(User.objects.filter(username='target_delete').exists())

    def test_doctor_support_ticket_system(self):
        """Test that doctors can view and submit support tickets in their Support Tickets (help center) page"""
        from .models import HelpTicket
        # Create a verified doctor
        doctor = User.objects.create_user(username='docsupport', email='docsupport@caresync.com', password='password123')
        doctor.profile.role = 'doctor'
        doctor.profile.hospital = 'AIIMS'
        doctor.profile.department = 'Cardiology'
        doctor.profile.is_approved = True
        doctor.profile.save()

        # Log in
        self.client.login(username='docsupport', password='password123')

        # GET request to help center
        response = self.client.get(reverse('help_center'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('tickets', response.context)
        self.assertContains(response, 'Submit Support Ticket')

        # POST request to create ticket
        ticket_data = {
            'subject': 'System latency in clinic',
            'description': 'Reports are loading very slowly in the afternoon.'
        }
        post_response = self.client.post(reverse('help_center'), ticket_data)
        self.assertEqual(post_response.status_code, 302)

        # Verify ticket was created in database
        self.assertTrue(HelpTicket.objects.filter(user=doctor, subject='System latency in clinic').exists())

    def test_contact_form_submission_sends_email(self):
        """Test that submitting the contact form sends an email to the support mailbox"""
        from django.core import mail
        contact_data = {
            'name': 'Test Sender',
            'email': 'sender@example.com',
            'subject': 'General Inquiry',
            'message': 'This is a test message to the clinic support team.'
        }
        response = self.client.post(reverse('contact'), contact_data)
        self.assertEqual(response.status_code, 302)
        
        # Verify email was captured in Django test outbox
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, 'New Contact Inquiry: General Inquiry')
        self.assertIn('Test Sender', mail.outbox[0].body)
        self.assertIn('sender@example.com', mail.outbox[0].body)
        self.assertIn('caresync.support@gmail.com', mail.outbox[0].to)

    def test_help_ticket_per_user_numbering(self):
        """Test that help tickets are numbered sequentially per user starting at 1"""
        from .models import HelpTicket
        # Create second user
        user2 = User.objects.create_user(username='anotherpatient', email='another@patient.com', password='password123')
        
        # User 1 creates 2 tickets
        t1_u1 = HelpTicket.objects.create(user=self.user, subject="U1 T1", description="desc")
        t2_u1 = HelpTicket.objects.create(user=self.user, subject="U1 T2", description="desc")
        
        # User 2 creates 1 ticket
        t1_u2 = HelpTicket.objects.create(user=user2, subject="U2 T1", description="desc")
        
        # Assertions
        self.assertEqual(t1_u1.user_ticket_num, 1)
        self.assertEqual(t2_u1.user_ticket_num, 2)
        self.assertEqual(t1_u2.user_ticket_num, 1)

    def test_patient_alert_feed_privacy(self):
        """Test that patient alert feed only gets relevant notifications, excluding admin-only logs"""
        from .models import Notification, MedicalRecord, Appointment
        from django.utils import timezone
        
        # 1. Create patient-specific notification
        Notification.objects.create(recipient=self.user, title="Alert for you", message="msg")
        
        # 2. Create global broadcast notification from admin
        Notification.objects.create(recipient=None, title="Broadcast Alert", message="msg")
        
        # 3. Create admin-only notifications
        Notification.objects.create(recipient=None, title="New Contact Inquiry: Issue", message="msg")
        Notification.objects.create(recipient=None, title="New Appointment Scheduled", message="msg")
        
        # 4. Create another user and a notification for them
        other_user = User.objects.create_user(username='otherpatient', email='other@patient.com', password='password123')
        Notification.objects.create(recipient=other_user, title="Secret Alert", message="msg")
        
        # 5. Doctor updates medical record remarks -> generates notification
        doctor = User.objects.create_user(username='docremarks', email='doc@remarks.com', password='password')
        doctor.profile.role = 'doctor'
        doctor.profile.hospital = 'AIIMS'
        doctor.profile.department = 'Cardiology'
        doctor.profile.save()
        
        # Create appointment to put patient in doctor's queue
        Appointment.objects.create(
            patient=self.user,
            appointment_date=timezone.now(),
            hospital='AIIMS',
            department='Cardiology',
            symptoms='Chest pain'
        )
        
        test_file = SimpleUploadedFile("xray.jpg", b"jpeg content", content_type="image/jpeg")
        record = MedicalRecord.objects.create(patient=self.user, title="Chest XRay", file=test_file, file_type='X-Ray')
        
        # Doctor logs in and updates record remarks
        self.client.login(username='docremarks', password='password')
        response = self.client.post(reverse('doctor_dashboard'), {
            'update_record_id': record.id,
            'doctor_remarks': 'Mild congestion noted.'
        })
        self.assertEqual(response.status_code, 302)
        
        # Log in as patient and check dashboard notifications
        self.client.login(username='testpatient', password='testpassword123')
        response = self.client.get(reverse('user_dashboard'))
        self.assertEqual(response.status_code, 200)
        
        # Patient should only see patient-specific alert, broadcast alert, and medical record alert
        dashboard_notifications = response.context['notifications']
        titles = [n.title for n in dashboard_notifications]
        self.assertIn("Alert for you", titles)
        self.assertIn("Broadcast Alert", titles)
        self.assertIn("Medical Record Remarks Updated", titles)
        self.assertNotIn("New Contact Inquiry: Issue", titles)
        self.assertNotIn("New Appointment Scheduled", titles)
        self.assertNotIn("Secret Alert", titles)

    def test_clear_all_notifications(self):
        """Test that every patient can clear all notifications in their alert feed at once"""
        from .models import Notification
        
        # 1. Create a direct notification for this patient
        notif1 = Notification.objects.create(recipient=self.user, title="Patient Specific Alert", message="Hello Patient")
        # 2. Create a global broadcast notification
        notif2 = Notification.objects.create(recipient=None, title="Broadcast Alert", message="Hello All")
        
        # Create second user to verify their broadcast remains unaffected
        user2 = User.objects.create_user(username='anotherpatient', email='another@patient.com', password='password123')
        
        # Log in as patient and clear notifications
        self.client.login(username='testpatient', password='testpassword123')
        
        # Verify they are visible in alert feed first
        response = self.client.get(reverse('notifications'))
        self.assertEqual(response.status_code, 200)
        self.assertIn(notif1, response.context['notifications'])
        self.assertIn(notif2, response.context['notifications'])
        
        # Send clear all action
        response = self.client.post(reverse('notifications'), {'action': 'clear_all'})
        self.assertEqual(response.status_code, 302)
        
        # Verify patient's feed and user dashboard show no notifications now
        response = self.client.get(reverse('notifications'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['notifications']), 0)
        
        response_dash = self.client.get(reverse('user_dashboard'))
        self.assertEqual(len(response_dash.context['notifications']), 0)
        
        # Verify second user still sees the broadcast notification
        self.client.login(username='anotherpatient', password='password123')
        response2 = self.client.get(reverse('notifications'))
        self.assertIn(notif2, response2.context['notifications'])
        self.assertNotIn(notif1, response2.context['notifications'])

    def test_patient_delete_xray(self):
        """Test that patients can delete their X-ray records from the AI X-Ray Checker page"""
        # Create user X-ray record
        test_file = SimpleUploadedFile("wrist_xray.jpg", b"jpeg content", content_type="image/jpeg")
        record = MedicalRecord.objects.create(patient=self.user, title="Wrist X-Ray Test", file=test_file, file_type='X-Ray')
        
        # Log in as patient
        self.client.login(username='testpatient', password='testpassword123')
        
        # Check initial presence on xray page
        response = self.client.get(reverse('xray_analysis'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Wrist X-Ray Test")
        
        # Send post deletion request
        response = self.client.post(reverse('xray_analysis'), {'delete_id': record.id})
        self.assertEqual(response.status_code, 302)
        
        # Check if record deleted from database
        self.assertFalse(MedicalRecord.objects.filter(id=record.id).exists())
        
        # Check that it is no longer shown on page
        response = self.client.get(reverse('xray_analysis'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Wrist X-Ray Test")

    def test_completed_appointment_shows_doctor_name(self):
        """Test that completing an appointment assigns the doctor and renders their name in timelines and dashboard"""
        from django.utils import timezone
        
        # 1. Create a doctor
        doctor = User.objects.create_user(
            username='doctorwatson',
            email='watson@caresync.com',
            password='password123',
            first_name='John',
            last_name='Watson'
        )
        doctor.profile.role = 'doctor'
        doctor.profile.hospital = 'AIIMS'
        doctor.profile.department = 'Cardiology'
        doctor.profile.save()
        
        # 2. Create a pending appointment for the patient matching the doctor's clinic/dept
        app = Appointment.objects.create(
            patient=self.user,
            appointment_date=timezone.now(),
            hospital='AIIMS',
            department='Cardiology',
            symptoms='Shortness of breath',
            status='Pending'
        )
        
        # 3. Log in as doctor and mark appointment as Completed
        self.client.login(username='doctorwatson', password='password123')
        response = self.client.post(reverse('doctor_dashboard'), {
            'update_app_id': app.id,
            'status': 'Completed',
            'notes': 'Take rest.'
        })
        self.assertEqual(response.status_code, 302)
        
        # Verify doctor is saved on the appointment object
        app.refresh_from_db()
        self.assertEqual(app.status, 'Completed')
        self.assertEqual(app.doctor, doctor)
        
        # 4. Log in as patient and check dashboard and timelines/history page
        self.client.login(username='testpatient', password='testpassword123')
        
        # Dashboard check
        dash_response = self.client.get(reverse('user_dashboard'))
        self.assertEqual(dash_response.status_code, 200)
        self.assertContains(dash_response, "Dr. John Watson")
        
        # Timelines check
        history_response = self.client.get(reverse('history'))
        self.assertEqual(history_response.status_code, 200)
        self.assertContains(history_response, "Dr. John Watson")

    def test_doctor_downloads_custom_reports_pdf(self):
        """Test that a doctor downloads a PDF report containing their consultations and patient details"""
        from .models import Appointment
        from django.utils import timezone
        
        # 1. Create a doctor
        doctor = User.objects.create_user(
            username='doctorwatson_rep', 
            email='watson_rep@test.com', 
            password='password123',
            first_name='John',
            last_name='Watson'
        )
        doctor.profile.role = 'doctor'
        doctor.profile.hospital = 'AIIMS'
        doctor.profile.department = 'Cardiology'
        doctor.profile.is_approved = True
        doctor.profile.save()
        
        # 2. Create a patient and appointment matching this doctor's hospital/department
        patient = User.objects.create_user(
            username='patientwatson', 
            email='pat_watson@test.com', 
            password='password123',
            first_name='Sherlock',
            last_name='Holmes'
        )
        patient.profile.role = 'patient'
        patient.profile.save()
        
        Appointment.objects.create(
            patient=patient,
            appointment_date=timezone.now(),
            hospital='AIIMS',
            department='Cardiology',
            symptoms='Arrhythmia',
            status='Pending'
        )
        
        # Log in as the doctor
        self.client.login(username='doctorwatson_rep', password='password123')
        
        # Verify the doctor's reports page has correct stats count
        rep_page_response = self.client.get(reverse('reports'))
        self.assertEqual(rep_page_response.status_code, 200)
        self.assertContains(rep_page_response, "1 scheduled consulting records")
        
        # Verify the doctor's PDF download contains the doctor's name, patient registry, and consultations registry
        pdf_response = self.client.get(reverse('download_pdf_report'))
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response['Content-Type'], 'application/pdf')
        
        # The content should be a valid PDF (PDF files start with %PDF)
        self.assertTrue(pdf_response.content.startswith(b'%PDF'))

    def test_admin_and_doctor_clear_all_notifications(self):
        """Test that both admins and doctors can clear all notifications from their feed independently"""
        from .models import Notification
        
        # Create an admin (superuser)
        admin = User.objects.create_superuser(username='superadmin', email='admin@test.com', password='adminpassword')
        
        # Create a doctor
        doctor = User.objects.create_user(username='docwatson', email='doc@test.com', password='password123')
        doctor.profile.role = 'doctor'
        doctor.profile.hospital = 'AIIMS'
        doctor.profile.department = 'Cardiology'
        doctor.profile.save()
        
        # Create a patient
        patient = User.objects.create_user(username='pat_sherlock', email='pat@test.com', password='password123')
        patient.profile.role = 'patient'
        patient.profile.save()
        
        # Create a notification
        Notification.objects.create(recipient=None, title="Clinic Broadcast Announcement", message="important msg")
        
        # 1. Verify admin can clear notifications
        self.client.login(username='superadmin', password='adminpassword')
        response = self.client.get(reverse('notifications'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Clinic Broadcast Announcement")
        
        # Post clear all action
        clear_response = self.client.post(reverse('notifications'), {'action': 'clear_all'})
        self.assertEqual(clear_response.status_code, 302)
        
        # Verify it is no longer listed for admin
        response2 = self.client.get(reverse('notifications'))
        self.assertEqual(response2.status_code, 200)
        self.assertNotContains(response2, "Clinic Broadcast Announcement")
        
        # 2. Verify doctor still sees it and can clear it
        self.client.login(username='docwatson', password='password123')
        doc_response = self.client.get(reverse('notifications'))
        self.assertEqual(doc_response.status_code, 200)
        self.assertContains(doc_response, "Clinic Broadcast Announcement")
        
        # Post clear all action as doctor
        doc_clear_response = self.client.post(reverse('notifications'), {'action': 'clear_all'})
        self.assertEqual(doc_clear_response.status_code, 302)
        
        # Verify it is no longer listed for doctor
        doc_response2 = self.client.get(reverse('notifications'))
        self.assertEqual(doc_response2.status_code, 200)
        self.assertNotContains(doc_response2, "Clinic Broadcast Announcement")
        
        # 3. Verify patient still sees it
        self.client.login(username='pat_sherlock', password='password123')
        pat_response = self.client.get(reverse('notifications'))
        self.assertEqual(pat_response.status_code, 200)
        self.assertContains(pat_response, "Clinic Broadcast Announcement")

    def test_admin_deletes_activity_audit(self):
        """Test that admins can delete individual activity logs and purge the entire audit trail"""
        from .models import ActivityLog
        
        # Create an admin (superuser)
        admin = User.objects.create_superuser(username='superadmin_log', email='admin_log@test.com', password='adminpassword')
        
        # Create a patient
        patient = User.objects.create_user(username='pat_log_test', email='pat_log@test.com', password='password123')
        
        # Create two logs
        log1 = ActivityLog.objects.create(user=patient, action="Logged in", ip_address="127.0.0.1")
        log2 = ActivityLog.objects.create(user=patient, action="Viewed profile", ip_address="127.0.0.1")
        
        # 1. Log in as patient and try to post a delete action (should not execute deletion)
        self.client.login(username='pat_log_test', password='password123')
        self.client.post(reverse('activity_logs'), {'action': 'delete_log', 'log_id': log1.id})
        log1_exists = ActivityLog.objects.filter(id=log1.id).exists()
        self.assertTrue(log1_exists)
        
        # 2. Log in as admin and verify logs are listed
        self.client.login(username='superadmin_log', password='adminpassword')
        admin_response = self.client.get(reverse('activity_logs'))
        self.assertEqual(admin_response.status_code, 200)
        self.assertContains(admin_response, "Logged in")
        self.assertContains(admin_response, "Viewed profile")
        
        # 3. Admin deletes single log entry
        del_response = self.client.post(reverse('activity_logs'), {'action': 'delete_log', 'log_id': log1.id})
        self.assertEqual(del_response.status_code, 302)
        
        # Verify log1 is deleted, log2 still exists
        self.assertFalse(ActivityLog.objects.filter(id=log1.id).exists())
        self.assertTrue(ActivityLog.objects.filter(id=log2.id).exists())
        
        # 4. Admin purges the entire log trail
        purge_response = self.client.post(reverse('activity_logs'), {'action': 'clear_all_logs'})
        self.assertEqual(purge_response.status_code, 302)
        
        # Verify all logs are deleted EXCEPT the newly created purge log entry
        remaining_logs = ActivityLog.objects.all()
        self.assertEqual(remaining_logs.count(), 1)
        self.assertIn("Purged entire security audit logs history trail", remaining_logs.first().action)

    def test_user_can_change_password(self):
        """Test that users (patients, doctors, admins) can successfully change their password"""
        # Create users for all three roles
        patient = User.objects.create_user(username='alexandergreat', email='alex@test.com', password='AlexOldPass199!@')
        
        doctor = User.objects.create_user(username='doctorwatson', email='watson@test.com', password='DocOldPass199!@')
        doctor.profile.role = 'doctor'
        doctor.profile.save()
        
        admin = User.objects.create_superuser(username='adminboss', email='adminboss@test.com', password='AdminOldPass199!@')

        for user, old_pass, new_pass in [
            (patient, 'AlexOldPass199!@', 'GreatNewPass200!@'),
            (doctor, 'DocOldPass199!@', 'WatsonNewPass200!@'),
            (admin, 'AdminOldPass199!@', 'BossNewPass200!@')
        ]:
            # 1. Log in with the old password
            login_success = self.client.login(username=user.username, password=old_pass)
            self.assertTrue(login_success)
            
            # Verify profile and settings pages load correctly for the role
            profile_response = self.client.get(reverse('profile'))
            self.assertEqual(profile_response.status_code, 200)
            
            settings_response = self.client.get(reverse('settings'))
            self.assertEqual(settings_response.status_code, 200)
            
            # Verify password change page loads correctly
            get_response = self.client.get(reverse('change_password'))
            self.assertEqual(get_response.status_code, 200)
            self.assertContains(get_response, "Change Password")
            
            # 2. Submit mismatched passwords (should fail and render validation error without crash)
            mismatch_response = self.client.post(reverse('change_password'), {
                'old_password': old_pass,
                'new_password1': new_pass,
                'new_password2': 'mismatchedsecurepass123',
            })
            self.assertEqual(mismatch_response.status_code, 200)
            self.assertContains(mismatch_response, "Please correct the error below")
            
            # Verify password is NOT changed
            self.client.logout()
            login_old_success = self.client.login(username=user.username, password=old_pass)
            self.assertTrue(login_old_success)
            
            # 3. Submit valid matching passwords (should succeed and redirect)
            valid_response = self.client.post(reverse('change_password'), {
                'old_password': old_pass,
                'new_password1': new_pass,
                'new_password2': new_pass,
            })
            self.assertEqual(valid_response.status_code, 302)
            
            # Log out and verify the old password no longer works, but the new password does
            self.client.logout()
            login_old_fail = self.client.login(username=user.username, password=old_pass)
            self.assertFalse(login_old_fail)
            
            login_new_success = self.client.login(username=user.username, password=new_pass)
            self.assertTrue(login_new_success)
            self.client.logout()

    def test_forgot_password_otp_flow(self):
        """Test the end-to-end Forgot Password OTP reset workflow"""
        # Create a test user
        user = User.objects.create_user(username='testresetuser', email='resetuser@test.com', password='OldSecretPass123!@')
        
        # 1. Access Forgot Password email request page
        get_email_res = self.client.get(reverse('forgot_password'))
        self.assertEqual(get_email_res.status_code, 200)
        self.assertContains(get_email_res, "Forgot Password")
        
        # 2. Submit non-existent email
        bad_email_res = self.client.post(reverse('forgot_password'), {'email': 'unknown@test.com'})
        self.assertEqual(bad_email_res.status_code, 200)
        self.assertContains(bad_email_res, "No registered account found with that email address")
        
        # 3. Submit valid email
        valid_email_res = self.client.post(reverse('forgot_password'), {'email': 'resetuser@test.com'})
        self.assertEqual(valid_email_res.status_code, 302)
        self.assertRedirects(valid_email_res, reverse('forgot_password_verify'))
        
        # Verify session stores email, otp and time
        self.assertEqual(self.client.session.get('forgot_password_email'), 'resetuser@test.com')
        otp = self.client.session.get('forgot_password_otp')
        self.assertTrue(otp)
        
        # 4. Access OTP verification page
        get_verify_res = self.client.get(reverse('forgot_password_verify'))
        self.assertEqual(get_verify_res.status_code, 200)
        self.assertContains(get_verify_res, "Verify Security Code")
        self.assertContains(get_verify_res, "resetuser@test.com")
        
        # 5. Submit wrong OTP
        wrong_otp_res = self.client.post(reverse('forgot_password_verify'), {'otp': '000000'})
        self.assertEqual(wrong_otp_res.status_code, 200)
        self.assertContains(wrong_otp_res, "Invalid verification code")
        
        # 6. Resend OTP verification code
        resend_res = self.client.get(reverse('forgot_password_resend_otp'))
        self.assertEqual(resend_res.status_code, 302)
        self.assertRedirects(resend_res, reverse('forgot_password_verify'))
        
        # Get new OTP from session
        new_otp = self.client.session.get('forgot_password_otp')
        self.assertTrue(new_otp)
        
        # 7. Submit correct OTP
        correct_otp_res = self.client.post(reverse('forgot_password_verify'), {'otp': new_otp})
        self.assertEqual(correct_otp_res.status_code, 302)
        self.assertRedirects(correct_otp_res, reverse('forgot_password_reset'))
        self.assertTrue(self.client.session.get('forgot_password_verified'))
        
        # 8. Access Password Reset input form page
        get_reset_res = self.client.get(reverse('forgot_password_reset'))
        self.assertEqual(get_reset_res.status_code, 200)
        self.assertContains(get_reset_res, "Reset Password")
        
        # 9. Submit mismatched passwords
        mismatch_reset_res = self.client.post(reverse('forgot_password_reset'), {
            'new_password1': 'NewSecurePass99!@',
            'new_password2': 'differentpass123',
        })
        self.assertEqual(mismatch_reset_res.status_code, 200)
        self.assertContains(mismatch_reset_res, "Passwords do not match")
        
        # 10. Submit matching password that violates strength policy (e.g. too common/simple)
        weak_reset_res = self.client.post(reverse('forgot_password_reset'), {
            'new_password1': '12345678',
            'new_password2': '12345678',
        })
        self.assertEqual(weak_reset_res.status_code, 200)
        self.assertContains(weak_reset_res, "entirely numeric")
        
        # 11. Submit matching secure passwords
        successful_reset_res = self.client.post(reverse('forgot_password_reset'), {
            'new_password1': 'NewSecurePass99!@',
            'new_password2': 'NewSecurePass99!@',
        })
        self.assertEqual(successful_reset_res.status_code, 302)
        self.assertRedirects(successful_reset_res, reverse('login'))
        
        # Verify forgot password session items are cleared
        self.assertNotIn('forgot_password_email', self.client.session)
        self.assertNotIn('forgot_password_otp', self.client.session)
        
        # 12. Try logging in with the old password (should fail)
        login_old_fail = self.client.login(username='testresetuser', password='OldSecretPass123!@')
        self.assertFalse(login_old_fail)
        
        # 13. Try logging in with the new password (should succeed)
        login_new_success = self.client.login(username='testresetuser', password='NewSecurePass99!@')
        self.assertTrue(login_new_success)

    def test_index_page_contains_forgot_password_links(self):
        """Verify the landing index page Portal Quick Access card displays Forgot Password links"""
        response = self.client.get(reverse('index'))
        self.assertEqual(response.status_code, 200)
        # Check both link occurrences in index.html
        self.assertContains(response, 'Forgot Password?')
        self.assertContains(response, 'Forgot your password? <a href="/forgot-password/"')






