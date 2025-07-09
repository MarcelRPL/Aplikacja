from flask import session, redirect, g, current_app
from functools import wraps
import sqlite3

def login_required(f):

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)
    
    return decorated_function

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config.get("DATABASE", "game.db"),
            detect_types = sqlite3.PARSE_DECLTYPES,
            check_same_thread = False
        )
        g.db.row_factory = sqlite3.Row
    return g.db

def close_db(e=None):

    db = g.pop("db", None)
    if db is not None:
        db.close()
