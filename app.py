from datetime import datetime
from flask import Flask, render_template, request, flash, redirect, session, url_for, jsonify
from flask_session import  Session
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import check_password_hash, generate_password_hash
import sqlite3, re, threading


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

lock = threading.Lock() # Przeciwdziałanie racing condition
waiting_player = None
games = {}  # Struktura danych do gier online
sid_user_map = {}

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
    game_id = db.execute("INSERT INTO game (user_id, start, end, score, mode, date) VALUES (?, ?, ?, ?, ?, ?)", (session["user_id"], data["start"], data["end"], data["score"], "solo", datetime.now().strftime("%Y-%m-%d"))).lastrowid

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
@login_required
def join_game():
    global waiting_player

    with lock:
        sid_user_map[request.sid] = session["user_id"]

        if waiting_player is None:
            waiting_player = request.sid
            emit("waiting", {"msg": "Waiting for another player..."}, room=request.sid)
        else:
            player1 = waiting_player
            player2 = request.sid
            waiting_player = None

            # Tworzymy pokój
            room = f"game_{player1}_{player2}"
            join_room(room, sid=player1)
            join_room(room, sid=player2)
            
            # Ustalamy litery
            start = random_letter()
            end = random_letter()

            # Tworzymy strukture danych dla danego pokoju
            games[room] = {
                "players": {player1: {"words": [], "score": 0},
                            player2: {"words": [], "score": 0}},
                "letters": (start, end),
                "started": True,
            }

            # Wysyłami wiadomość do serwera, aby rozpocząć grę i z jakimi danymi
            emit("start_game", {
                "room": room,
                "start_letter": start,
                "end_letter": end,
                "time": 30
            }, room=room)

            # Uruchom timer i po 30 sekundach uruchom funkcje end_game
            threading.Timer(30.0, end_game, args=(room,)).start()


@socketio.on("submit_word")
@login_required
def submit_word(data):
    word = data.get("word", "").strip().lower()
    room = data.get("room")

    if room not in games:
        emit("error", {"msg": "Game does not exist"})
        return

    player = request.sid
    game = games[room]
    player_data = game["players"].get(player)

    if not player_data or not game["started"]:
        emit("error", {"msg": "Game hasn't started yet"})

    start, end = game["letters"]
    
    if not (word.startswith(start) and word.endswith(end)):
        emit("word_rejected", {"msg": "Wrong start/end letters"}, to=player)
        return

    if word not in VALID_WORDS:
        emit("word_rejected", {"msg": "Word not in game dictionary"}, to=player) 
        return
    
    if word in player_data["words"]:
        emit("word_rejected", {"msg": "This word was already used"}, to=player)
        return

    score = calculate_score(word)
    player_data["words"].append(word)
    player_data["score"] += score

    emit("word_accepted", {
        "word": word,
        "score": score,
        "total": player_data["score"]
    }, to=player)


def end_game(room):
    
    # Sprawdź czy room istnieje
    if room not in games:
        return
        
    # Pobierz dane gry (dane graczy, ich punkty i słowa)
    game = games[room]
    players = list(game["players"].keys())
    if len(players) < 2:
        for sid in players:
            socketio.emit("game_cancelled", {"msg": "Opponenct disconnected."}, to=sid)
        del games[room]
        return

    start, end = game["letters"]

    results = []
    with app.app_context():
        db = get_db()

        for player_sid in players:
            user_id = sid_user_map.get(player_sid)
            opponent_sid = [sid for sid in players if sid != player_sid][0]
            opponent_id = sid_user_map.get(opponent_sid)

            score = game["players"][player_sid]["score"]
            words = game["players"][player_sid]["words"]
        
            # Zapisz dane z gry w bazie danych
            game_id = db.execute("INSERT INTO game (user_id, opponent_id, start, end, score, mode, date) VALUES (?, ?, ?, ?, ?, ?, ?)", (user_id, opponent_id, start, end, score, "1v1", datetime.now().date())).lastrowid
        
            for word in words:
                db.execute("INSERT INTO words (game_id, user_id, word) VALUES (?, ?, ?)", (game_id, user_id, word))

            results.append({"sid": player_sid, "score": score, "words": words})

        db.commit()

    # Porównaj wyniki

    p1, p2 = results

    if p1["score"] > p2["score"]:
        winner, loser = p1, p2
    elif p2["score"] > p1["score"]:
        winner, loser = p2, p1
    else:
        winner = loser = None

    for p in results:
        socketio.emit("game_over", {
            "your_score": p["score"],
            "your_words": p["words"],
            "opponent_score": results[1]["score"] if p == results[0] else results[0]["score"],
            "opponent_words": results[1]["words"] if p == results[0] else results[0]["words"],
            "result": "Win" if p == winner else ("Lose" if p == loser else "Draw")
        }, room=p["sid"])

    # Usuwamy dane o zamkniętej grze
    del games[room]
    del sid_user_map[players[0]]
    del sid_user_map[players[1]]

@socketio.on("disconnect")
def handle_disconnect():
    global waiting_player
    sid = request.sid
    
    print(f"User has disconnected: {sid}")

    if sid == waiting_player:
        waiting_player = None

    user_id = sid_user_map.pop(sid, None)

    room_to_delete = None
    for room, game in games.items():
        if sid in game["players"]:
            del game["players"][sid]

            for other_sid in game["players"]:
                socketio.emit("opponent_disconnected", {}, to=other_sid)

            if not game["players"]:
                room_to_delete = room
            break
    
    if room_to_delete:
        del games[room_to_delete]
    

if __name__ == "__main__":
    socketio.run(app, debug=True, port=5000)