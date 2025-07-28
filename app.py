from datetime import datetime
from flask import Flask, abort, render_template, request, flash, redirect, session, url_for, jsonify
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
   
    db = get_db()
    solos = db.execute("SELECT * FROM game WHERE user_id = ? AND mode = ? ORDER BY date DESC", (session["user_id"], "solo")).fetchall()
    
    versus_games = db.execute("SELECT * FROM game WHERE user_id = ? AND mode = ? ORDER BY date DESC", (session["user_id"], "1v1")).fetchall()

    versus = []
    for game in versus_games:
        opponent_id = game["opponent_id"]
        opponent_row = db.execute("SELECT username FROM users WHERE id = ?", (opponent_id,)).fetchone()
        opponent_username = opponent_row["username"] if opponent_row else "Unknown"

        game_dict = dict(game)
        game_dict["opponent_username"] = opponent_username
        versus.append(game_dict)
   
    
    return render_template("index.html", solos=solos, versus=versus)

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

@app.route("/logout")
@login_required
def logout():
    #user logging out
    session.clear()

    return redirect("/")

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

@app.route("/match/<int:match_id>")
@login_required
def match_detail(match_id):
    viewer_id = request.args.get("viewer_id", type=int)
    db = get_db()
    games = db.execute("SELECT * FROM game WHERE match_id = ?", (match_id,)).fetchall()

    if len(games) != 2:
        return jsonify({"error": "Match not found"}), 404
    
    game_1 = games[0]
    game_2 = games[1]

    if game_1["user_id"] == viewer_id:
        player_game = game_1
        opponent_game = game_2
    else:
        player_game = game_2
        opponent_game = game_1
    
    your_words = db.execute("SELECT word FROM words WHERE game_id = ? AND user_id = ?",(player_game["id"], player_game["user_id"])).fetchall()
    opponent_words = db.execute("SELECT word FROM words WHERE game_id = ? AND user_id = ?",(opponent_game["id"], opponent_game["user_id"])).fetchall()

    return jsonify({"start": player_game["start"], "end": player_game["end"], "score": player_game["score"], "words": [w["word"] for w in your_words], "opponent_score": opponent_game["score"], "opponent_words": [w["word"] for w in opponent_words]})

@app.route("/1v1")
@login_required
def versus():
    return render_template("1v1.html")

@app.route("/search")
@login_required
def search():
    # Rendering a form for searching for other palyers
    username = request.args.get("user")

    if not username:
        flash("Must provide a username")

    db = get_db()
    user = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()

    if user:
       return redirect(url_for("view_profile", username=username))
    else:
        flash("Palyer not found")
        return render_template("search.html")
    

@app.route("/profile/<username>")
@login_required
def view_profile(username):

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

    solos = db.execute("SELECT * FROM game WHERE user_id = ? AND mode = ? ORDER BY date DESC", (user["id"], "solo")).fetchall()
    
    versus_games = db.execute("SELECT * FROM game WHERE user_id = ? AND mode = ? ORDER BY date DESC", (user["id"], "1v1")).fetchall()

    versus = []
    for game in versus_games:
        opponent_id = game["opponent_id"]
        opponent_row = db.execute("SELECT username FROM users WHERE id = ?", (opponent_id,)).fetchone()
        opponent_username = opponent_row["username"] if opponent_row else "Unknown"

        game_dict = dict(game)
        game_dict["opponent_username"] = opponent_username
        versus.append(game_dict)

    # Set highscore, winrate, wins, losses, games
    stats = {}
    stats["versus"] = db.execute("SELECT COUNT(id) FROM game WHERE user_id = ? AND mode = ?", (user["id"], "1v1")).fetchone()[0]
    stats["highscore"] = db.execute("SELECT MAX(score) FROM game WHERE user_id = ?", (user["id"],)).fetchone()[0]
    stats["highscore_versus"] = db.execute("SELECT MAX(score) FROM game WHERE user_id = ? AND mode = ?", (user["id"], "1v1")).fetchone()[0]
    stats["wins"] = db.execute("SELECT COUNT(id) FROM game WHERE user_id = ? AND result = ?", (user["id"], "win")).fetchone()[0]
    stats["losses"] = db.execute("SELECT COUNT(id) FROM game WHERE user_id = ? AND result = ?", (user["id"], "loss")).fetchone()[0]
    stats["draws"] = db.execute("SELECT COUNT(id) FROM game WHERE user_id = ? AND result = ?", (user["id"], "draw")).fetchone()[0]
    if stats["versus"] != 0:   
        stats["winrate"] = round(((stats["wins"] + 0.5 * stats["draws"]) / stats["versus"]) * 100, 2)
    else:
        stats["winrate"] = 0

    stats["word_count"] = db.execute("SELECT COUNT(DISTINCT word) FROM words WHERE user_id = ?", (user["id"],)).fetchone()[0]
    stats["valid"] = 0
    for word in VALID_WORDS:
        stats["valid"] += 1

    stats["completion"] = round((stats["word_count"] / stats["valid"]) * 100, 3) 


    if user["id"] == session["user_id"]:
        return render_template("profile.html", solos=solos, versus=versus, stats=stats, username=username)
    else:
        return render_template("player.html", solos=solos, versus=versus, stats=stats, username=username)

@app.route("/friend_request", methods=["POST"])
@login_required
def friend_request():
    data = request.get_json()
    username = data.get("friend")

    if not username:
        return jsonify({"success": False, "message": "Username missing"}), 400
    
    db = get_db()
    sender_id = session["user_id"]
    user = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()

    if not user:
        return jsonify({"success": False, "message": "User not found"}), 404
    
    receiver_id = user["id"]

    existing = db.execute("SELECT * FROM friend_requests WHERE sender_id = ? AND receiver_id = ? AND status = 'pending'", (sender_id, receiver_id)).fetchone()

    if existing:
        return jsonify({"success": False, "message": "Friend request already sent"}), 409
    
    db.execute("INSERT INTO friend_requests (sender_id, receiver_id) VALUES (?, ?)", (sender_id, receiver_id))
    db.commit()

    return jsonify({"success": True, "message": "Friend request sent"})
    
@app.route("/notifications")
@login_required
def notifications():
    db = get_db()
    user_id = session["user_id"]

    requests = db.execute("SELECT fr.id, u.username as sender_username, fr.timestamp, 'friend' AS type FROM friend_requests fr JOIN users u ON fr.sender_id = u.id " \
    "WHERE fr.receiver_id = ? AND fr.status = 'pending'", (user_id,)).fetchall()

    invites = db.execute("SELECT gi.id, u.username as sender_username, gi.timestamp, 'game' AS type FROM game_invites gi JOIN users u ON gi.sender_id = u.id " \
    "WHERE gi.receiver_id = ? AND gi.status = 'pending'", (user_id,)).fetchall()

    notifications = [dict(row) for row in requests] + [dict(row) for row in invites]

    notifications.sort(key=lambda x: x["timestamp"], reverse=True)

    return jsonify(notifications)

@app.route("/respond_request", methods=["POST"])
@login_required
def respond_request():
    data = request.get_json()
    request_id = data.get("request_id")
    action = data.get("action")

    db = get_db()
    user_id = session["user_id"]

    req = db.execute("SELECT * FROM friend_requests WHERE id = ? AND receiver_id = ?", (request_id, user_id)).fetchone()

    if not req:
        return jsonify({"success": False, "message": "Request not found"}), 404
    
    if action == "accept":
        db.execute("UPDATE friend_requests SET status = 'accepted' WHERE id = ?", (request_id,))
        db.execute("INSERT INTO friends (user_id, friend_id) VALUES (?, ?)", (user_id, req["sender_id"]))
        db.execute("INSERT INTO friends (user_id, friend_id) VALUES (?, ?)", (req["sender_id"], user_id))
    else:
        db.execute("UPDATE friend_requests SET status = 'declined' WHERE id = ?", (request_id,))

    db.commit()
    return jsonify({"success": True})

@app.route("/game_invite", methods=["POST"])
@login_required
def game_invite():
    data = request.get_json()
    username = data.get("opponent")

    if not username:
        return jsonify({"success": False, "message": "Username missing"}), 400
    
    db = get_db()
    sender_id = session["user_id"]

    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

    if not user:
        return jsonify({"success": False, "message": "User not found"}), 404
    
    receiver_id = user["id"]

    if receiver_id == sender_id:
        return jsonify({"success": False, "message": "Can't invite yourself"}), 400
    
    existing = db.execute("SELECT id FROM game_invites WHERE sender_id = ? AND receiver_id = ? AND status = 'pending'", (sender_id, receiver_id)).fetchone()

    if existing:
        return jsonify({"success": False, "message": "Invite already sent"}), 409
    
    room_id = f"room_{min(sender_id, receiver_id)}_{max(sender_id, receiver_id)}"

    db.execute("INSERT INTO game_invites (sender_id, receiver_id, room_id) VALUES (?, ?, ?)", (sender_id, receiver_id, room_id))
    db.commit()

    return jsonify({"success": True, "message": "Game invite sent", "room_id": room_id})

@app.route("/respond_invite", methods=["POST"])
@login_required
def respond_invite():
    data = request.get_json()
    invite_id = data.get("invite_id")
    action = data.get("action")

    db = get_db()
    user_id = session["user_id"]

    invite = db.execute("SELECT * FROM game_invites WHERE id = ? AND receiver_id = ?", (invite_id, user_id)).fetchone()

    if not invite:
        return jsonify({"success": False, "message": "Invite not found"}), 404
    
    if invite["status"] != "pending":
        return jsonify({"success": False, "message": "Invite expired or canceled"}), 400
    
    if action == "accept":
        db.execute("UPDATE game_invites SET status = 'accepted' WHERE id = ?", (invite_id,))
        db.commit()
        return jsonify({"success": True, "room_id": invite["room_id"]})      
    else:
        db.execute("UPDATE game_invites SET status = 'declined' WHERE id = ?", (invite_id,))
        db.commit()
        return jsonify({"success": True, "message": "Invite declined"})


@app.route("/play/<room_id>")
@login_required
def play_room(room_id):
    return render_template("1v1.html", room_id=room_id, invite_mode=True)

@socketio.on("join_game")
@login_required
def join_game(data=None):
        global waiting_player
        sid = request.sid
        user_id = session["user_id"]

        with lock:
            # INVITATION GAME
            if data and "room_id" in data:
                room_id = data["room_id"]

                # if it's the second player joining
                if room_id in games:
                    join_room(room_id, sid=sid)
                    games[room_id]["players"][sid] = {"user_id": user_id, "words": [], "score": 0}
                    games[room_id]["started"] = True

                    start, end = games[room_id]["letters"]
                    emit("start_game", {
                        "room": room_id,
                        "start_letter": start,
                        "end_letter": end,
                        "time": 30
                    }, room=room_id)

                    socketio.start_background_task(game_timer, room_id)
                    print(f"Invitation game started: {room_id}")
                
                # First player sent and invite
                else:
                    join_room(room_id, sid=sid)

                    start = random_letter()
                    end =  random_letter()
                    games[room_id] = {
                        "players": {sid: {"user_id": user_id, "words": [], "score": 0}},
                        "letters": (start, end),
                        "started": False
                    }

                    emit("waiting", {"msg": "Waiting for invited player..."}, room=sid)
                    print(f"Invitation room created: {room_id}")

                return

            # Random matchmaking 
            if waiting_player is None:
                waiting_player = sid
                emit("waiting", {"msg": "Waiting for another player..."}, room=sid)
            else:
                player1 = waiting_player
                player2 = sid
                waiting_player = None

                # Tworzymy pokój
                room_id = f"game_{player1}_{player2}"
                join_room(room_id, sid=player1)
                join_room(room_id, sid=player2)
                
                # Ustalamy litery
                start = random_letter()
                end = random_letter()

                # Tworzymy strukture danych dla danego pokoju
                games[room_id] = {
                    "players": {player1: {"words": [], "score": 0},
                                player2: {"words": [], "score": 0}},
                    "letters": (start, end),
                    "started": True,
                }

                # Wysyłami wiadomość do serwera, aby rozpocząć grę i z jakimi danymi
                emit("start_game", {
                    "room": room_id,
                    "start_letter": start,
                    "end_letter": end,
                    "time": 30
                }, room=room_id)

                # Uruchom timer i po 30 sekundach uruchom funkcje end_game
                socketio.start_background_task(game_timer, room_id)
                print(f"Game started: {room_id}")


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
    print(f"===> ENding game for room {room}")

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

        match_id = db.execute("SELECT IFNULL(MAX(match_id_, 0) + 1 FROM game)").fetchone()[0]

        for player_sid in players:
            user_id = sid_user_map.get(player_sid)
            opponent_sid = [sid for sid in players if sid != player_sid][0]
            opponent_id = sid_user_map.get(opponent_sid)

            score = game["players"][player_sid]["score"]
            op_score = game["players"][opponent_sid]["score"]
            words = game["players"][player_sid]["words"]
        
            # Zapisz dane z gry w bazie danych
            game_id = db.execute("INSERT INTO game (user_id, opponent_id, start, end, score, opponent_score, mode, date, match_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (user_id, opponent_id, start, end, score, op_score, "1v1", datetime.now().date(), match_id)).lastrowid
        
            for word in words:
                db.execute("INSERT INTO words (game_id, user_id, word) VALUES (?, ?, ?)", (game_id, user_id, word))

            results.append({"sid": player_sid, "user_id": user_id, "score": score, "words": words, "game_id": game_id})

        db.commit()

    # Porównaj wyniki

    p1, p2 = results

    if p1["score"] > p2["score"]:
        winner, loser = p1, p2
    elif p2["score"] > p1["score"]:
        winner, loser = p2, p1
    else:
        winner = loser = None
    with app.app_context():
        for p in results:
            print(f"Emitting game_over to sid: {p['sid']}")
            socketio.emit("game_over", {
                "your_score": p["score"],
                "your_words": p["words"],
                "opponent_score": results[1]["score"] if p == results[0] else results[0]["score"],
                "opponent_words": results[1]["words"] if p == results[0] else results[0]["words"],
                "result": "Win" if p == winner else ("Lose" if p == loser else "Draw")
            }, to=p["sid"])
            db = get_db()
            if p == winner:
                db.execute("UPDATE game SET result = ? WHERE id = ?", ("win", p["game_id"]))
            elif p == loser:
                db.execute("UPDATE game SET result = ? WHERE id = ?", ("loss", p["game_id"]))
            else:
                db.execute("UPDATE game SET result = ? WHERE id = ?", ("draw", p["game_id"]))
        
        db.commit()

    # Usuwamy dane o zamkniętej grze
    global waiting_player
    if waiting_player in room:
        waiting_player = None
    del games[room]
    del sid_user_map[players[0]]
    del sid_user_map[players[1]]


@socketio.on("connect")
def handle_connect():
    user_id = session.get("user_id")
    if user_id:
        sid_user_map[request.sid] = user_id
        print(f"User connected: SID={request.sid}, user_id={user_id}")
    else:
        print(f"Anonymous connection: SID={request.sid}")

@socketio.on("disconnect")
def handle_disconnect():
    global waiting_player
    sid = request.sid

    print(f"User has disconnected: {sid}")

    if sid == waiting_player:
        waiting_player = None

    user_id = sid_user_map.pop(sid, None)

    room_to_delete = None
    for room, game in list(games.items()):
        if sid in game["players"]:

            if len(game["players"]) == 1 and not game.get("started", False):
                db = get_db()
                db.execute("UPDATE game_invites SET status='canceled' WHERE room_id = ? AND status = 'pending'", (room,))
                db.commit()

                room_to_delete = room
                print(f"Invite canceled: {room}")   

            del game["players"][sid]

            for other_sid in game["players"]:
                socketio.emit("opponent_disconnected", {}, to=other_sid)

            if not game["players"]:
                room_to_delete = room
            break
    
    if room_to_delete:
        del games[room_to_delete]

def game_timer(room):
    socketio.sleep(30)
    end_game(room)
    
@app.context_processor
def inject_user():
    db = get_db()
    user_id = session.get("user_id")

    if user_id:
        user = db.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        if user:
            return {"logged_in_user": user["username"]}
    return {"logged_in_user": None}


if __name__ == "__main__":
    socketio.run(app, debug=True, port=5000)