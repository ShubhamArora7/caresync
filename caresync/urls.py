from django.urls import path
from . import views

urlpatterns = [
    # Public pages
    path('', views.index, name='index'),
    path('about/', views.about, name='about'),
    path('contact/', views.contact, name='contact'),
    
    # Authentication
    path('signup/', views.register_patient, name='signup'),
    path('signup/doctor/', views.register_doctor, name='register_doctor'),
    path('verify-otp/', views.verify_otp, name='verify_otp'),
    path('resend-otp/', views.resend_otp, name='resend_otp'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),
    path('forgot-password/verify/', views.forgot_password_verify_view, name='forgot_password_verify'),
    path('forgot-password/resend/', views.forgot_password_resend_otp, name='forgot_password_resend_otp'),
    path('forgot-password/reset/', views.forgot_password_reset_view, name='forgot_password_reset'),
    
    # Dashboards
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard/user/', views.user_dashboard, name='user_dashboard'),
    path('dashboard/doctor/', views.doctor_dashboard, name='doctor_dashboard'),
    path('dashboard/admin/', views.admin_dashboard, name='admin_dashboard'),
    
    # Profile & Settings
    path('profile/', views.profile_view, name='profile'),
    path('profile/edit/', views.edit_profile, name='edit_profile'),
    path('profile/password/', views.change_password_view, name='change_password'),
    
    # Downloads
    path('patients/<int:patient_id>/summary/', views.download_patient_summary, name='download_patient_summary'),
    path('patients/<int:patient_id>/files/', views.download_all_patient_files, name='download_all_patient_files'),
    path('settings/', views.settings_view, name='settings'),
    
    # Admin User Management
    path('users/', views.user_management, name='user_management'),
    path('users/add/', views.user_create, name='user_create'),
    path('users/edit/<int:user_id>/', views.user_edit, name='user_edit'),
    path('users/delete/<int:user_id>/', views.user_delete, name='user_delete'),
    path('users/delete-dashboard/', views.user_delete_dashboard, name='user_delete_dashboard'),
        # Medical Files / Uploads
    path('records/upload/', views.upload_files, name='upload_files'),
    path('records/manage/', views.data_management, name='data_management'),
    path('records/xray/', views.xray_analysis, name='xray_analysis'),
    
    # Admin Features & Timelines
    path('notifications/', views.notifications_view, name='notifications'),
    path('reports/', views.reports_view, name='reports'),
    path('reports/download/', views.download_pdf_report, name='download_pdf_report'),
    path('analytics/', views.analytics_view, name='analytics'),
    path('logs/', views.activity_logs_view, name='activity_logs'),
    path('messages/', views.messages_view, name='messages'),
    
    # Utility Pages
    path('search/', views.search_view, name='search'),
    path('history/', views.history_view, name='history'),
    path('help/', views.help_center, name='help_center'),
    path('feedback/', views.feedback_view, name='feedback'),
]
