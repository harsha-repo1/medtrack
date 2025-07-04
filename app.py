import os
import uuid
import boto3
from flask import Flask, render_template, request, redirect, session, url_for, flash
from flask_mail import Mail, Message
from dotenv import load_dotenv
from botocore.exceptions import ClientError

# Load environment variables from .env
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your_secret_key_here')

# ---------- AWS Configuration ----------
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')

# DynamoDB
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
dynamodb_client = boto3.client('dynamodb', region_name=AWS_REGION)

# SNS
SNS_TOPIC_ARN = os.getenv('SNS_TOPIC_ARN')
sns = boto3.client('sns', region_name=AWS_REGION)

# ---------- Flask-Mail Configuration ----------
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'true').lower() == 'true'
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
mail = Mail(app)

# ---------- DynamoDB Table Creation (if not exists) ----------
def create_table_if_not_exists(table_name, key_schema, attribute_definitions):
    try:
        dynamodb_client.describe_table(TableName=table_name)
    except dynamodb_client.exceptions.ResourceNotFoundException:
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=key_schema,
            AttributeDefinitions=attribute_definitions,
            BillingMode='PAY_PER_REQUEST'
        )
        # Wait for table to be created
        waiter = dynamodb_client.get_waiter('table_exists')
        waiter.wait(TableName=table_name)

# Users table
create_table_if_not_exists(
    'users',
    [{'AttributeName': 'username', 'KeyType': 'HASH'}],
    [{'AttributeName': 'username', 'AttributeType': 'S'}]
)
users_table = dynamodb.Table('users')

# Doctors table
create_table_if_not_exists(
    'doctors',
    [{'AttributeName': 'doctor_id', 'KeyType': 'HASH'}],
    [{'AttributeName': 'doctor_id', 'AttributeType': 'S'}]
)
doctors_table = dynamodb.Table('doctors')

# Appointments table
create_table_if_not_exists(
    'appointments',
    [
        {'AttributeName': 'appointment_id', 'KeyType': 'HASH'},
        {'AttributeName': 'doctor_id', 'KeyType': 'RANGE'}
    ],
    [
        {'AttributeName': 'appointment_id', 'AttributeType': 'S'},
        {'AttributeName': 'doctor_id', 'AttributeType': 'S'}
    ]
)
appointments_table = dynamodb.Table('appointments')

# ---------- SNS Notification Function ----------
def send_sns_notification(message):
    if SNS_TOPIC_ARN:
        try:
            sns.publish(
                TopicArn=SNS_TOPIC_ARN,
                Message=message,
                Subject='MedTrack Notification'
            )
        except Exception as e:
            print(f"SNS error: {e}")

# ---------- Routes ----------
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        role = request.form['role']
        username = request.form['username']
        password = request.form['password']

        # Check if user exists
        response = users_table.get_item(Key={'username': username})
        if 'Item' in response:
            flash("User already exists!", "danger")
            return render_template('register.html')

        # Add new user
        users_table.put_item(Item={
            'username': username,
            'password': password,
            'role': role
        })

        # Send Welcome Email
        try:
            msg = Message(
                subject="Welcome to MedTrack!",
                sender=app.config['MAIL_USERNAME'],
                recipients=[username],
                body=f"Hello {username},\n\nThank you for registering as a {role} on MedTrack."
            )
            mail.send(msg)
        except Exception as e:
            print(f"Email error: {e}")

        flash("Registration successful! Please log in.", "success")
        return redirect('/login')

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        response = users_table.get_item(Key={'username': username})
        user = response.get('Item')

        if user and user['password'] == password:
            session['username'] = username
            session['role'] = user['role']
            return redirect(f"/{user['role']}")
        flash("Invalid credentials!", "danger")

    return render_template('login.html')

@app.route('/doctor')
def doctor_dashboard():
    if 'role' in session and session['role'] == 'doctor':
        return render_template('doctor_dashboard.html', username=session['username'])
    return redirect('/login')

@app.route('/patient')
def patient_dashboard():
    if 'role' in session and session['role'] == 'patient':
        return render_template('patient_dashboard.html', username=session['username'])
    return redirect('/login')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# ---------- Example: Book Appointment Route ----------
@app.route('/appointment/book', methods=['GET', 'POST'])
def book_appointment():
    if 'role' not in session or session['role'] != 'patient':
        return redirect('/login')
    if request.method == 'POST':
        appointment_id = str(uuid.uuid4())
        doctor_id = request.form['doctor_id']
        patient_email = session['username']
        date = request.form['date']
        reason = request.form['reason']

        # You can add 'time' and other fields as needed
        appointments_table.put_item(Item={
            'appointment_id': appointment_id,
            'doctor_id': doctor_id,
            'patient_email': patient_email,
            'date': date,
            'reason': reason,
            'status': 'Scheduled'
        })

        send_sns_notification(
            f"New appointment booked with Doctor ID {doctor_id} on {date} for {patient_email}"
        )

        flash("Appointment booked successfully!", "success")
        return redirect(url_for('patient_dashboard'))

    # Fetch doctors for dropdown
    doctors = doctors_table.scan().get('Items', [])
    return render_template('book_appointment.html', doctors=doctors)

# ---------- Example: Doctor View Appointments ----------
@app.route('/doctor/appointments')
def doctor_appointments():
    if 'role' not in session or session['role'] != 'doctor':
        return redirect('/login')
    doctor_id = session['username']  # Adjust if you use a different doctor identifier
    response = appointments_table.scan(
        FilterExpression=boto3.dynamodb.conditions.Attr('doctor_id').eq(doctor_id)
    )
    appointments = response.get('Items', [])
    return render_template('view_appointment_doctor.html', appointments=appointments)

# ---------- Example: Patient View Appointments ----------
@app.route('/patient/appointments')
def patient_appointments():
    if 'role' not in session or session['role'] != 'patient':
        return redirect('/login')
    patient_email = session['username']
    response = appointments_table.scan(
        FilterExpression=boto3.dynamodb.conditions.Attr('patient_email').eq(patient_email)
    )
    appointments = response.get('Items', [])
    return render_template('view_appointment_patient.html', appointments=appointments)

# ---------- Doctor Registration (optional) ----------
@app.route('/doctor/register', methods=['GET', 'POST'])
def doctor_register():
    if request.method == 'POST':
        doctor_id = str(uuid.uuid4())
        name = request.form['name']
        specialization = request.form['specialization']
        email = request.form['email']
        doctors_table.put_item(Item={
            'doctor_id': doctor_id,
            'name': name,
            'specialization': specialization,
            'email': email
        })
        flash("Doctor registered successfully!", "success")
        return redirect('/login')
    return render_template('doctor_register.html')

# ---------- Run App ----------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
