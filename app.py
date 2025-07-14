from datetime import datetime
from flask import Flask, render_template, request, flash, redirect, session, url_for, jsonify
from flask_session import  Session
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import check_password_hash, generate_password_hash
import sqlite3, re

from helpers import login_required, get_db, close_db
from game_logic import load_words, valid_word, calculate_score, random_letter

app = Flask(__name__)

app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = "./.flask_session"
app.config["SESSION_PERMANENT"] = False
Session(app)

socketio = SocketIO(app, async_mode="eventlet", manage_session=False)

app.teardown_appcontext(close_db)

pass_re = re.compile(r"^(?=.*\d)[A-Za-z\d]{6,}$")

VALID_WORDS = load_words(min_length=6)

waiting_player = None

@app.route("/")
@login_required
def index():
    #main game menu / looking for matches
    try:
        db = get_db()
        games = db.execute("SELECT * FROM game WHERE user_id = ? ORDER BY date DESC", (session["user_id"],))
    except ValueError:
        return render_template("index.html")
    
    return render_template("index.html", games=games)

@app.route("/login", methods=["GET", "POST"])
def login():
    # User logging in
    
    # Forget any user_id
    session.clear()

    errors = {}

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
    
        # Check if username and password were provided
        if not username:
            errors["username"] = "Can't be empty"
        
        if not password:
            errors["password"] = "Can't be empty"

        # Check if there is data for provided username
        db = get_db()
        cur = db.execute("SELECT * FROM users WHERE username = ?", (username,))
        rows = cur.fetchall()

        #Check if there is only 1 row of data and hash is matching
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], password):
            errors["both"] = "Invalid username or password"
        else:
            # Remember which user has logged in
            session["user_id"] = rows[0]["id"]

        if not errors:
            return redirect("/")
        else:
            return render_template("login.html", errors=errors)

    else:
        return render_template("login.html", errors=errors)

@app.route("/register", methods=["GET", "POST"])
def register():
    # User registering

    # Check for all the possible wrong inputs
    errors = {}
    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")
        confirm = request.form.get("confirm")

        # Check if username was provided, then if it is using allowed characters
        if not username:
            errors["username"] = "Can't be empty"
        elif not re.fullmatch(r"[A-Za-z0-9_]{3,15}", username):
            errors["username"] = "Only 3-15 letters, digits or _"
        else:
            db = get_db()
            if db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
                errors["username"] = "Username unavailable"

        # Check if password was provided, and then if it is in the right format
        if not password:
            errors["password"] = "Can't be empty"
        elif not pass_re.fullmatch(password):
            errors["password"] = "Min. 6 characters, and at least 1 digit"
        
        # Check if confirmation was provided and then if it is matching the password
        if not confirm:
            errors["confirm"] = "Repeat your password for confirmation"
        elif confirm != password:
            errors["confirm"] = "Different from password"

        if not errors:
            # Create users data in database by INSERTING his username and hashed password while checking if the username is available
            try:
                db.execute(
                    "INSERT INTO users (username, hash) VALUES (?, ?)",
                    (username, generate_password_hash(password))
                    )
                db.commit()
                return redirect("/")
            except sqlite3.IntegrityError:
                errors["username"] = "Username unavialable"

           
    return render_template("register.html", errors=errors)

@app.route("/solo", methods=["POST", "GET"])
@login_required
def solo():

    # Randomize 2 letter and check if there is a word with those letter requirements
    found = False

    while found == False:
        start = random_letter()
        end = random_letter()

        for n in VALID_WORDS:
            if n.startswith(start) and n.endswith(end):
                found = True
                break
    
    session["start_letter"] = start
    session["end_letter"] = end

    print(f"Found valid pair: {start}-{end}")
    return render_template("solo.html", start=start, end=end)

@app.route("/check_word", methods=["POST"])
@login_required
def check_word():

    # Check for the length of the word and if the word is in the dictionairy and if it has the required letters
    word = request.form.get("word")
    start = session.get("start_letter")
    end = session.get("end_letter")

    if valid_word(word, start, end, VALID_WORDS):
        points = calculate_score(word)
        return jsonify({"valid": True, "word": word, "points": points})
    else:
        return jsonify({"valid": False})

@app.route("/save_game", methods=["POST"])
@login_required
def save_game():

    # pobierz dane z gry
    data = request.get_json()

    if not all (k in data for k in ("start", "end", "score", "words")):
        return jsonify({"error": "Incomplete data"}), 400
    # Wstaw pobrane dane w tabele "game" oraz ustal jaki to game_id
    db = get_db()
    game_id = db.execute("INSERT INTO game (user_id, start, end, score, mode, date) VALUES (?, ?, ?, ?, ?, ?)", (session["user_id"], data["start"], data["end"], data["score"], "solo", datetime.now().date())).lastrowid

    # Wstaw użyte słowa w table "words"
    for word in data["words"]:
        db.execute("INSERT INTO words (game_id, user_id, word) VALUES (?, ?, ?)", (game_id, session["user_id"], word))
        
    db.commit()
    print("SESSION:", session)
    return jsonify({"success": True, "game_id": game_id})


@app.route("/game/<int:game_id>")
@login_required
def game_detail(game_id):
    db = get_db()
    game = db.execute("SELECT * FROM game WHERE id = ? AND user_id = ?", (game_id, session["user_id"])).fetchone()
    words = db.execute("SELECT word FROM words WHERE game_id = ?", (game_id,)).fetchall()

    return jsonify ({"start": game["start"], "end": game["end"], "score": game["score"], "words": [w["word"] for w in words]})

@app.route("/1v1")
@login_required
def versus():
    return render_template("1v1.html")

@app.route("/friends")
@login_required
def friends():
    #adding friends and showing friends list
    return render_template("friends.html")

@app.route("/logout")
@login_required
def logout():
    #user logging out
    session.clear()

    return redirect("/")

@app.route("/profile")
@login_required
def profile():
    #view users profile
    return render_template("profile.html")


@socketio.on("join_game")
def join_game():
    global waiting_player

    if waiting_player is None:
        waiting_player = request.sid
        emit("waiting", {"msg": "Waiting for another player..."})
    else:
        room = f"game_{waiting_player}_{request.sid}"
        join_room(room, sid=waiting_player)
        join_room(room, sid=request.sid)


@socketio.on("submit_word")
def submit_word(data):
    word = data.get("word")

if __name__ == "__main__":
    socketio.run(app, debug=True, port=5000)