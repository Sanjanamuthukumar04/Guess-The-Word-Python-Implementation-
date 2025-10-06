import sqlite3
import hashlib
import random
import re
from datetime import date, timedelta
from flask import Flask, render_template_string, request, redirect, url_for, session, g

# --- Configuration and Constants ---
DATABASE_NAME = 'guess_the_word.db'
MAX_GUESSES = 5
WORD_LENGTH = 5
MAX_DAILY_GAMES = 3
SECRET_WORDS = [
    "APPLE", "GRAPE", "JUICE", "LEMON", "PEACH",
    "WORLD", "LIGHT", "HEART", "MONEY", "STORE",
    "TABLE", "CHAIR", "WATER", "EARTH", "PLANT",
    "SPACE", "DREAM", "SHIFT", "BREAK", "TRAIN"
]

# Initialize Flask app
app = Flask(__name__)
# The secret key is essential for managing sessions (where we store logged-in user info and game state)
app.secret_key = 'super_secret_game_key_12345' 

# --- Database Setup and Connection ---

def get_db_connection():
    """Opens a new database connection if there is none yet for the current application context."""
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE_NAME)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    """Closes the database connection at the end of the request."""
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def initialize_db():
    """Creates tables and seeds initial data if they don't exist."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    # USERS Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin BOOLEAN NOT NULL DEFAULT 0
        );
    ''')

    # SECRET_WORDS Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS secret_words (
            id INTEGER PRIMARY KEY,
            word TEXT UNIQUE NOT NULL
        );
    ''')
    
    # GAME_HISTORY Table (Tracks each game session)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS game_history (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            secret_word_id INTEGER NOT NULL,
            is_won BOOLEAN NOT NULL,
            date_played TEXT NOT NULL, -- YYYY-MM-DD
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (secret_word_id) REFERENCES secret_words(id)
        );
    ''')

    # GUESS_DETAILS Table (Stores every guess made in a game)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS guess_details (
            id INTEGER PRIMARY KEY,
            history_id INTEGER NOT NULL,
            guess_number INTEGER NOT NULL,
            guessed_word TEXT NOT NULL,
            FOREIGN KEY (history_id) REFERENCES game_history(id)
        );
    ''')

    # Seed Secret Words (insert only if not exists)
    for word in SECRET_WORDS:
        try:
            cursor.execute("INSERT INTO secret_words (word) VALUES (?)", (word,))
        except sqlite3.IntegrityError:
            pass

    conn.commit()
    conn.close()

# Ensure DB is initialized before first request
with app.app_context():
    initialize_db()

# --- Utility Functions (Adapted from utils.py and auth.py) ---

def hash_password(password):
    """Hashes a password using SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()

def check_password(password, hashed_password):
    """Checks if a password matches the stored hash."""
    return hash_password(password) == hashed_password

def validate_username(username):
    """Username must have at least 5 letters (upper/lower case)."""
    if len(username) < 5 or not re.search(r'[a-zA-Z]{5,}', username):
        return "Username must be at least 5 characters and contain 5 letters."
    return None

def validate_password(password):
    """Password must be >= 5 chars, have alpha, numeric, and one of $, %, *, @."""
    if len(password) < 5:
        return "Password must be at least 5 characters long."
    if not re.search(r'[a-zA-Z]', password):
        return "Password must contain at least one alphabet character."
    if not re.search(r'\d', password):
        return "Password must contain at least one numeric digit."
    if not re.search(r'[\$%\*@]', password):
        return "Password must contain one of the special characters: $, %, *, or @."
    return None

def get_today_date():
    """Returns today's date in 'YYYY-MM-DD' format."""
    return date.today().strftime('%Y-%m-%d')

def get_games_played_today(user_id):
    """Checks how many games the user has played today."""
    db = get_db_connection()
    cursor = db.cursor()
    today = get_today_date()
    cursor.execute(
        "SELECT COUNT(*) FROM game_history WHERE user_id = ? AND date_played = ?",
        (user_id, today)
    )
    return cursor.fetchone()[0]

# --- Game Logic (Adapted from game.py) ---

def get_guess_feedback(secret_word, guess):
    """
    Generates color-coded feedback (tailwind classes) for a guess.
    Returns a list of dictionaries [{'letter': 'A', 'color': 'bg-green-500'}, ...]
    """
    word_length = len(secret_word)
    secret_list = list(secret_word)
    feedback_list = []
    
    # 1. Check for Green (correct letter and position)
    status = ['GREY'] * word_length
    for i in range(word_length):
        if guess[i] == secret_word[i]:
            status[i] = 'GREEN'
            secret_list[i] = None 

    # 2. Check for Orange (correct letter, wrong position)
    for i in range(word_length):
        if status[i] != 'GREEN':
            try:
                idx = secret_list.index(guess[i])
                status[i] = 'ORANGE'
                secret_list[idx] = None
            except ValueError:
                status[i] = 'GREY' 

    # 3. Format into Tailwind classes
    for i in range(word_length):
        letter = guess[i]
        color_class = 'bg-gray-400' # Grey
        if status[i] == 'GREEN':
            color_class = 'bg-green-500' 
        elif status[i] == 'ORANGE':
            color_class = 'bg-yellow-500' # Using Yellow for Orange visibility
        
        feedback_list.append({'letter': letter, 'color': color_class})

    return feedback_list

def get_random_secret_word():
    """Fetches a random secret word and its ID from the database."""
    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute("SELECT id, word FROM secret_words ORDER BY RANDOM() LIMIT 1")
    word_data = cursor.fetchone()
    if word_data:
        return word_data['word'], word_data['id']
    return None, None

def start_new_game(user_id):
    """Starts a new game, saves initial history entry, and returns the history_id and word."""
    secret_word, secret_word_id = get_random_secret_word()
    if not secret_word:
        return None, None

    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO game_history (user_id, secret_word_id, is_won, date_played) VALUES (?, ?, ?, ?)",
        (user_id, secret_word_id, 0, get_today_date())
    )
    db.commit()
    history_id = cursor.lastrowid
    
    # Store essential game state in the session
    session['game_active'] = True
    session['history_id'] = history_id
    session['secret_word'] = secret_word
    session['guesses'] = [] # List of feedback lists (the board history)
    
    return history_id, secret_word

def save_guess_detail(history_id, guess_number, guessed_word):
    """Saves the user's guess to the GUESS_DETAILS table."""
    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO guess_details (history_id, guess_number, guessed_word) VALUES (?, ?, ?)",
        (history_id, guess_number, guessed_word)
    )
    db.commit()

def update_game_win_status(history_id, is_won):
    """Updates the game history entry with the final win/loss status."""
    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute(
        "UPDATE game_history SET is_won = ? WHERE id = ?",
        (1 if is_won else 0, history_id)
    )
    db.commit()
    session['game_active'] = False # End the game

# --- HTML Template (Using Tailwind CSS and Jinja) ---

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Guess The Word - {{ title }}</title>
    <!-- Tailwind CSS CDN -->
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { font-family: 'Inter', sans-serif; }
        .grid-cell {
            width: 48px;
            height: 48px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.5rem;
            font-weight: bold;
            color: white;
            border-radius: 0.5rem;
            transition: all 0.3s ease-in-out;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -2px rgba(0, 0, 0, 0.1);
        }
        .container-card {
            max-width: 450px;
            width: 95%;
        }
    </style>
</head>
<body class="bg-gray-100 flex items-center justify-center min-h-screen p-4">

    <div class="container-card bg-white p-8 rounded-xl shadow-2xl">
        <header class="mb-6 text-center">
            <h1 class="text-3xl font-extrabold text-indigo-700">
                {% if username %}{{ username }}'s {% endif %} Guess The Word
            </h1>
            <p class="text-sm text-gray-500">
                {{ subtitle }}
            </p>
        </header>
        
        <!-- Flash Messages / Notifications -->
        {% if message %}
        <div id="message-box" class="p-3 mb-4 text-sm text-white rounded-lg shadow-md 
            {% if 'success' in message|lower or 'congratulations' in message|lower %} bg-green-500 
            {% elif 'error' in message|lower or 'fail' in message|lower or 'invalid' in message|lower or 'better luck' in message|lower %} bg-red-500 
            {% else %} bg-blue-500 
            {% endif %}">
            <p>{{ message }}</p>
        </div>
        {% endif %}

        <main>
        {{ content | safe }}
        </main>
        
        <footer class="mt-8 pt-4 border-t border-gray-200 text-center">
            {% if username %}
                <a href="{{ url_for('logout') }}" class="text-indigo-600 hover:text-indigo-800 font-medium">
                    Logout
                </a>
                <span class="mx-2 text-gray-400">|</span>
                <a href="{{ url_for('index') }}" class="text-indigo-600 hover:text-indigo-800 font-medium">
                    Home
                </a>
            {% else %}
                <p class="text-sm text-gray-500">&copy; 2025 Guess The Word Project</p>
            {% endif %}
        </footer>
    </div>

</body>
</html>
"""

# --- Routes ---

@app.route('/', methods=['GET', 'POST'])
def index():
    """Handles the main menu, redirecting based on user authentication and role."""
    if 'user_id' not in session:
        # Not logged in: Show Login/Register form
        content = f"""
        <form method="post" action="{ url_for('login') }" class="space-y-4">
            <h2 class="text-xl font-semibold mb-4 text-gray-700">Login</h2>
            <div>
                <label for="username" class="block text-sm font-medium text-gray-700">Username</label>
                <input type="text" id="username" name="username" required 
                       class="mt-1 block w-full rounded-md border-gray-300 shadow-sm p-2 border focus:ring-indigo-500 focus:border-indigo-500">
            </div>
            <div>
                <label for="password" class="block text-sm font-medium text-gray-700">Password</label>
                <input type="password" id="password" name="password" required
                       class="mt-1 block w-full rounded-md border-gray-300 shadow-sm p-2 border focus:ring-indigo-500 focus:border-indigo-500">
            </div>
            <button type="submit" class="w-full py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500">
                Log In
            </button>
        </form>
        <p class="mt-4 text-center text-sm text-gray-600">
            New user? <a href="{ url_for('register') }" class="font-medium text-indigo-600 hover:text-indigo-500">Register here</a>
        </p>
        """
        return render_template_string(HTML_TEMPLATE, title="Login/Register", subtitle="Please log in to start playing.", content=content)
    
    # Logged in: Redirect to appropriate menu
    if session.get('is_admin'):
        return redirect(url_for('admin_dashboard'))
    else:
        return redirect(url_for('player_dashboard'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Handles user registration."""
    message = None
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        
        username_error = validate_username(username)
        password_error = validate_password(password)

        if username_error or password_error:
            message = username_error if username_error else password_error
        else:
            db = get_db_connection()
            cursor = db.cursor()
            
            # Determine if this user should be admin (only the first user)
            cursor.execute("SELECT COUNT(*) FROM users")
            user_count = cursor.fetchone()[0]
            is_admin = (user_count == 0)

            hashed_password = hash_password(password)
            try:
                cursor.execute(
                    "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
                    (username, hashed_password, 1 if is_admin else 0)
                )
                db.commit()
                role = "Admin" if is_admin else "Player"
                message = f"Success! {role} user registered. Please log in."
            except sqlite3.IntegrityError:
                message = f"Error: Username '{username}' already exists."
    
    # Registration form HTML
    content = f"""
    <form method="post" action="{ url_for('register') }" class="space-y-4">
        <h2 class="text-xl font-semibold mb-4 text-gray-700">Register Account</h2>
        <div>
            <label for="username" class="block text-sm font-medium text-gray-700">Username</label>
            <input type="text" id="username" name="username" required 
                   class="mt-1 block w-full rounded-md border-gray-300 shadow-sm p-2 border focus:ring-indigo-500 focus:border-indigo-500"
                   placeholder="Min 5 letters, e.g., PlayerOne">
            <p class="text-xs text-gray-500 mt-1">Must contain at least 5 letters (a-z, A-Z).</p>
        </div>
        <div>
            <label for="password" class="block text-sm font-medium text-gray-700">Password</label>
            <input type="password" id="password" name="password" required
                   class="mt-1 block w-full rounded-md border-gray-300 shadow-sm p-2 border focus:ring-indigo-500 focus:border-indigo-500">
            <p class="text-xs text-gray-500 mt-1">Min 5 chars, must include alpha, numeric, and one of $, %, *, @.</p>
        </div>
        <button type="submit" class="w-full py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-green-600 hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500">
            Register
        </button>
    </form>
    <p class="mt-4 text-center text-sm text-gray-600">
        Already have an account? <a href="{ url_for('index') }" class="font-medium text-indigo-600 hover:text-indigo-500">Log In</a>
    </p>
    """
    return render_template_string(HTML_TEMPLATE, title="Register", subtitle="Create your new account.", content=content, message=message)

@app.route('/login', methods=['POST'])
def login():
    """Handles user login submission."""
    username = request.form['username'].strip()
    password = request.form['password'].strip()
    db = get_db_connection()
    cursor = db.cursor()

    cursor.execute("SELECT id, username, password_hash, is_admin FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()

    if user and check_password(password, user['password_hash']):
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['is_admin'] = user['is_admin'] == 1
        
        if session['is_admin']:
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('player_dashboard'))
    else:
        # Ensuring login failure returns to the index with the login form content
        content = f"""
        <form method="post" action="{ url_for('login') }" class="space-y-4">
            <h2 class="text-xl font-semibold mb-4 text-gray-700">Login</h2>
            <div>
                <label for="username" class="block text-sm font-medium text-gray-700">Username</label>
                <input type="text" id="username" name="username" required 
                       class="mt-1 block w-full rounded-md border-gray-300 shadow-sm p-2 border focus:ring-indigo-500 focus:border-indigo-500">
            </div>
            <div>
                <label for="password" class="block text-sm font-medium text-gray-700">Password</label>
                <input type="password" id="password" name="password" required
                       class="mt-1 block w-full rounded-md border-gray-300 shadow-sm p-2 border focus:ring-indigo-500 focus:border-indigo-500">
            </div>
            <button type="submit" class="w-full py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500">
                Log In
            </button>
        </form>
        <p class="mt-4 text-center text-sm text-gray-600">
            New user? <a href="{ url_for('register') }" class="font-medium text-indigo-600 hover:text-indigo-500">Register here</a>
        </p>
        """
        return render_template_string(HTML_TEMPLATE, title="Login/Register", subtitle="Please log in to start playing.", 
                                      message="Error: Invalid username or password.",
                                      content=content)

@app.route('/logout')
def logout():
    """Clears the session and logs the user out."""
    session.clear()
    return redirect(url_for('index'))

# --- Player Routes ---

@app.route('/player')
def player_dashboard():
    """Player dashboard and game start."""
    if not session.get('user_id') or session.get('is_admin'):
        return redirect(url_for('index'))
    
    # FIX: Check for and display win/loss message immediately upon redirect
    message = session.pop('game_message', None)
    
    games_played = get_games_played_today(session['user_id'])
    
    if session.get('game_active'):
        if not message: # Only redirect to game if no win/loss message was just shown
            return redirect(url_for('game'))
    
    if games_played >= MAX_DAILY_GAMES:
        # Only set the daily limit message if no win/loss message was present
        if not message:
            message = f"Error: You have reached the daily limit of {MAX_DAILY_GAMES} games. Try again tomorrow!"
    
    # Python conditional injection to avoid Jinja/f-string syntax conflict
    game_button_html = ''
    if games_played < MAX_DAILY_GAMES and not session.get('game_active'):
        # Using an inner f-string (with triple quotes) for the button HTML fragment
        game_button_html = f"""
        <form method="post" action="{ url_for('start_game') }">
            <button type="submit" class="w-full py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500">
                Start New Guessing Game
            </button>
        </form>
        """
        
    content = f"""
    <h2 class="text-xl font-semibold mb-4 text-gray-700">Player Dashboard</h2>
    <p class="mb-4 text-gray-600">Games played today: <strong>{games_played}</strong> out of <strong>{MAX_DAILY_GAMES}</strong></p>
    
    {game_button_html}
    
    <div class="mt-6 p-4 bg-gray-50 rounded-lg">
        <h3 class="font-medium text-gray-700">How to Play:</h3>
        <ul class="list-disc list-inside text-sm text-gray-600 space-y-1 mt-2">
            <li>Guess the {WORD_LENGTH}-letter word in {MAX_GUESSES} tries.</li>
            <li><span class="inline-block w-4 h-4 bg-green-500 rounded-sm"></span>: Correct letter, correct position.</li>
            <li><span class="inline-block w-4 h-4 bg-yellow-500 rounded-sm"></span>: Correct letter, wrong position.</li>
            <li><span class="inline-block w-4 h-4 bg-gray-400 rounded-sm"></span>: Letter not in the word.</li>
        </ul>
    </div>
    """

    return render_template_string(HTML_TEMPLATE, title="Player Dashboard", subtitle=f"Welcome, {session['username']}!", content=content, username=session['username'], message=message)

@app.route('/start_game', methods=['POST'])
def start_game():
    """Initializes game state and redirects to the game board."""
    if not session.get('user_id') or session.get('is_admin'):
        return redirect(url_for('index'))

    games_played = get_games_played_today(session['user_id'])
    if games_played >= MAX_DAILY_GAMES:
        # Save a message before redirecting back
        session['game_message'] = f"Error: You have reached the daily limit of {MAX_DAILY_GAMES} games."
        return redirect(url_for('player_dashboard')) 

    history_id, secret_word = start_new_game(session['user_id'])
    
    if history_id:
        return redirect(url_for('game'))
    else:
        # Save an error message if the word couldn't be fetched
        session['game_message'] = "Error: Could not start game. No secret words available."
        return redirect(url_for('player_dashboard'))

@app.route('/game', methods=['GET', 'POST'])
def game():
    """Displays the game board and handles guesses."""
    if not session.get('user_id') or session.get('is_admin') or not session.get('game_active'):
        return redirect(url_for('player_dashboard'))

    message = None # Messages here are only for invalid input, not win/loss
    
    secret_word = session['secret_word']
    history_id = session['history_id']
    guesses = session['guesses']
    current_guess_count = len(guesses)
    
    if request.method == 'POST':
        guess_input = request.form['guess'].strip().upper()
        
        if len(guess_input) != WORD_LENGTH or not guess_input.isalpha():
            message = f"Error: Please enter exactly {WORD_LENGTH} uppercase letters."
        else:
            current_guess_count += 1
            feedback = get_guess_feedback(secret_word, guess_input)
            guesses.append(feedback)
            save_guess_detail(history_id, current_guess_count, guess_input)

            if guess_input == secret_word:
                update_game_win_status(history_id, True)
                # Store the message in the session before redirecting
                session['game_message'] = f"🎉 CONGRATULATIONS! You won in {current_guess_count} guesses!"
                return redirect(url_for('player_dashboard'))

            if current_guess_count >= MAX_GUESSES:
                update_game_win_status(history_id, False)
                # Store the message in the session before redirecting
                session['game_message'] = f"😔 Better luck next time! The word was: {secret_word}"
                return redirect(url_for('player_dashboard'))
            
            session['guesses'] = guesses # Update session after processing

    # Generate the board display
    board_html = '<div class="space-y-2">'
    for i in range(MAX_GUESSES):
        board_html += '<div class="flex justify-center space-x-2">'
        if i < len(guesses):
            # Display past guess feedback
            for cell in guesses[i]:
                board_html += f'<div class="grid-cell {cell["color"]}">{cell["letter"]}</div>'
        else:
            # Display empty slots
            for j in range(WORD_LENGTH):
                board_html += '<div class="grid-cell bg-gray-200 border border-gray-300"></div>'
        board_html += '</div>'
    board_html += '</div>'


    # Game Input Form
    input_form = f"""
    <form method="post" action="{ url_for('game') }" class="mt-6 space-y-4">
        <label for="guess" class="block text-sm font-medium text-gray-700">
            Guess {current_guess_count + 1} of {MAX_GUESSES}
        </label>
        <input type="text" id="guess" name="guess" required maxlength="{WORD_LENGTH}" pattern="[A-Za-z]{{{WORD_LENGTH}}}"
               class="mt-1 block w-full text-center text-xl uppercase rounded-md border-gray-300 shadow-sm p-2 border focus:ring-indigo-500 focus:border-indigo-500"
               placeholder="5 Letters" oninput="this.value = this.value.toUpperCase()">
        <button type="submit" class="w-full py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500">
            Submit Guess
        </button>
    </form>
    """
    
    content = f"""
    <h2 class="text-xl font-semibold mb-4 text-gray-700">Game In Progress</h2>
    <p class="mb-4 text-gray-600">Current Guess: <strong>{current_guess_count + 1}</strong></p>
    {board_html}
    {input_form}
    """

    return render_template_string(HTML_TEMPLATE, title="Play Game", subtitle="Guess the 5-letter word", content=content, username=session['username'], message=message)

# --- Admin Routes (Adapted from reports.py) ---

@app.route('/admin')
def admin_dashboard():
    """Admin Dashboard menu."""
    if not session.get('is_admin'):
        return redirect(url_for('index'))
    
    # FIX: Converted to f-string to use url_for directly and fix the 404 error
    content = f"""
    <h2 class="text-xl font-semibold mb-4 text-gray-700">Admin Dashboard</h2>
    <div class="space-y-3">
        <a href="{ url_for('admin_daily_report_view') }" class="block w-full text-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500">
            View Daily Report
        </a>
        <a href="{ url_for('admin_user_report_view') }" class="block w-full text-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500">
            View User History Report
        </a>
    </div>
    """
    return render_template_string(HTML_TEMPLATE, title="Admin Dashboard", subtitle=f"Welcome, Admin {session['username']}!", content=content, username=session['username'])

@app.route('/admin/daily_report', methods=['GET', 'POST'])
def admin_daily_report_view():
    """Admin daily report generation and display."""
    if not session.get('is_admin'):
        return redirect(url_for('index'))
    
    report_date = request.args.get('date') or get_today_date()
    db = get_db_connection()
    cursor = db.cursor()

    # 1. Number of unique users who played
    cursor.execute(
        "SELECT COUNT(DISTINCT user_id) FROM game_history WHERE date_played = ?", (report_date,)
    )
    num_users = cursor.fetchone()[0]

    # 2. Number of correct guesses (games won)
    cursor.execute(
        "SELECT COUNT(*) FROM game_history WHERE date_played = ? AND is_won = 1", (report_date,)
    )
    num_correct_guesses = cursor.fetchone()[0]

    # 3. Total games played
    cursor.execute(
        "SELECT COUNT(*) FROM game_history WHERE date_played = ?", (report_date,)
    )
    total_games = cursor.fetchone()[0]

    content = f"""
    <h2 class="text-xl font-semibold mb-4 text-gray-700">Daily Report: {report_date}</h2>
    
    <form method="get" action="{ url_for('admin_daily_report_view') }" class="mb-6 flex space-x-2">
        <input type="date" name="date" value="{report_date}" 
               class="p-2 border border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500">
        <button type="submit" class="py-2 px-4 rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700">
            View
        </button>
    </form>

    <div class="space-y-4">
        <div class="bg-indigo-50 p-4 rounded-lg shadow">
            <p class="text-sm font-medium text-indigo-700">Unique Users Played</p>
            <p class="text-3xl font-bold text-indigo-900">{num_users}</p>
        </div>
        <div class="bg-green-50 p-4 rounded-lg shadow">
            <p class="text-sm font-medium text-green-700">Correct Guesses (Wins)</p>
            <p class="text-3xl font-bold text-green-900">{num_correct_guesses}</p>
        </div>
        <div class="bg-gray-50 p-4 rounded-lg shadow">
            <p class="text-sm font-medium text-gray-700">Total Games Played</p>
            <p class="text-3xl font-bold text-gray-900">{total_games}</p>
        </div>
    </div>
    """
    return render_template_string(HTML_TEMPLATE, title="Daily Report", subtitle="View daily game statistics.", content=content, username=session['username'])

@app.route('/admin/user_report', methods=['GET', 'POST'])
def admin_user_report_view():
    """Admin user history report generation and display."""
    if not session.get('is_admin'):
        return redirect(url_for('index'))
    
    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute("SELECT username FROM users ORDER BY username")
    all_users = [row['username'] for row in cursor.fetchall()]

    target_username = request.args.get('username')
    report_data = []
    message = None

    if target_username:
        cursor.execute("SELECT id FROM users WHERE username = ?", (target_username,))
        user_data = cursor.fetchone()
        
        if user_data:
            user_id = user_data['id']
            cursor.execute(
                """
                SELECT 
                    date_played, 
                    COUNT(id) as words_tried, 
                    SUM(is_won) as correct_guesses
                FROM game_history
                WHERE user_id = ?
                GROUP BY date_played
                ORDER BY date_played DESC
                """,
                (user_id,)
            )
            report_data = cursor.fetchall()
            if not report_data:
                 message = f"Info: No game history found for user '{target_username}'."
        else:
            message = f"Error: User '{target_username}' not found."


    # User selection dropdown
    select_options = "".join(f'<option value="{user}" {"selected" if user == target_username else ""}>{user}</option>' for user in all_users)
    
    # Base content (Form)
    content = f"""
    <h2 class="text-xl font-semibold mb-4 text-gray-700">User History Report</h2>
    
    <form method="get" action="{ url_for('admin_user_report_view') }" class="mb-6 space-y-4">
        <label for="username" class="block text-sm font-medium text-gray-700">Select User:</label>
        <select id="username" name="username" required
               class="mt-1 block w-full p-2 border border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500">
            <option value="">-- Choose a User --</option>
            {select_options}
        </select>
        <button type="submit" class="w-full py-2 px-4 rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700">
            Generate Report
        </button>
    </form>
    """
    
    # FIX: Build the dynamic report table using Python f-strings if data exists
    report_table_html = ""
    if report_data:
        table_rows = ""
        for row in report_data:
            table_rows += f"""
                <tr>
                    <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{row['date_played']}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{row['words_tried']}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{row['correct_guesses']}</td>
                </tr>
            """
        
        report_table_html = f"""
            <h3 class="text-lg font-semibold mt-6 text-gray-700">History for {target_username}</h3>
            <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-gray-200 shadow-md rounded-lg">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Date</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Words Tried</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Correct Guesses</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200">
                        {table_rows}
                    </tbody>
                </table>
            </div>
        """
    
    # Concatenate the form content and the table content
    content += report_table_html

    # The final render call now only needs the fully built content
    return render_template_string(
        HTML_TEMPLATE, 
        title="User Report", 
        subtitle="View user-specific game history.", 
        content=content, 
        username=session['username'], 
        message=message
    )

@app.route('/debug_routes')
def debug_routes():
    """Displays all routes registered with the Flask application."""
    # Ensure this route is accessible even if the user is not logged in
    output = []
    for rule in app.url_map.iter_rules():
        # Exclude internal routes like static if you only want user-facing ones
        if 'static' not in rule.endpoint:
            methods = ','.join(rule.methods)
            output.append(f'<li><code class="font-mono text-xs bg-gray-200 p-1 rounded">Endpoint: {rule.endpoint}</code> | <code class="font-mono text-xs bg-gray-200 p-1 rounded">Rule: {rule}</code> | <code class="font-mono text-xs bg-gray-200 p-1 rounded">Methods: {methods}</code></li>')

    content = f"""
    <h2 class="text-xl font-semibold mb-4 text-gray-700">DEBUG: Flask Routes</h2>
    <p class="mb-4 text-gray-600">Checking server configuration. **The '/register', '/admin/daily_report', and '/admin/user_report' routes must be visible below.**</p>
    <ul class="list-disc list-inside space-y-2 text-sm text-gray-700">
        {''.join(output)}
    </ul>
    <p class="mt-8"><a href="{ url_for('index') }" class="text-indigo-600 hover:text-indigo-800 font-medium">Back to Login</a></p>
    """
    return render_template_string(HTML_TEMPLATE, title="Routes Debugger", subtitle="Confirming server endpoints.", content=content)


if __name__ == '__main__':
    # Running directly (for development/testing outside the environment)
    # This line is NECESSARY to start the web server if running locally.
    print("--- DEBUG: Registered Routes ---")
    with app.app_context(): # Ensure url_for works in the debug print block
        for rule in app.url_map.iter_rules():
            # Exclude static route for clarity
            if 'static' not in rule.endpoint:
                print(f"Endpoint: {rule.endpoint:<20} | Rule: {rule}")
    print("---------------------------------")
    app.run(debug=True)
