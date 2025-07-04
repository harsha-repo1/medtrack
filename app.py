from flask import Flask, render_template, request, redirect, session
from flask_mail import Mail, Message
import boto3

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'



# ---------- AWS DynamoDB Configuration ----------
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')  # Change region if needed
users_table = dynamodb.Table('users')

# ---------- Email (SMTP) Configuration ----------
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'your_email@gmail.com'       # ✅ Your Gmail
app.config['MAIL_PASSWORD'] = 'your_app_password'          # ✅ Use Gmail App Password

mail = Mail(app)

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
            return "User already exists!"

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
                recipients=[username],  # Assuming username is email
                body=f"Hello {username},\n\nThank you for registering as a {role} on MedTrack."
            )
            mail.send(msg)
        except Exception as e:
            print(f"Email error: {e}")

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

        return "Invalid credentials!"

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

if __name__ == '__main__':
    app.run(debug=True)