# Guess-The-Word-Python-Implementation-

Guess The Word Web Application
This project implements a web-based "Guess The Word" game following all specified requirements, including multi-user support (Player and Admin roles) and persistence via a local SQLite database.

🚀 Getting Started
Follow these steps to set up and run the application locally.

1. Prerequisites
You need Python 3.x and pip installed.

2. Installation
Install Dependencies:
Use the included requirements.txt file to install the Flask web framework and the Gunicorn production server.

pip install -r requirements.txt

Database:
The project includes the pre-initialized SQLite database file (guess_the_word.db), which contains the required 20 five-letter secret words.

3. Running the Application
To start the web server in debug mode:

python app.py

After running the command, open your web browser and navigate to:

http://127.0.0.1:5000/

4. Initial Login (Admin Setup)
When you first visit the page, click the "Register here" link.

The first user to register will automatically be assigned the Admin role.

Use the Admin credentials to test the reports functionality via the /admin dashboard.

5. Key Features
User Roles: Player and Admin roles are enforced.

Authentication: Strong password validation rules are enforced upon registration.

Game Logic: Word guessing with a 5-guess limit.

Feedback: Color-coded (Green, Orange, Grey) feedback on each guess.

Daily Limit: Players are limited to 3 unique words per day.

Admin Reports: Daily summary and detailed user history reports.
