from flask import Flask, render_template, request, redirect, session, url_for
from flask_session import  Session
from werkzeug.security import check_password_hash, generate_password_hash
import sqlite3, re

app = Flask(__name__)

app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = "./.flask_session"
app.config["SESSION_PERMANENT"] = False
Session(app)

con = sqlite3.connect("game.db", check_same_thread=False)
db = con.cursor()

@app.route("/")
def index():
    #main game menu / looking for matches
    return render_template("index.html")

@app.route("/login")
def login():
    #user logging in
    return render_template("register.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    #user registering

    #forget any user_id
    session.clear()

    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")
        confirm = request.form.get("confrim")

        if not username:
            return
        

    else:    
        render_template("register.html")

@app.route("/friends")
def friends():
    #adding friends and showing friends list
    render_template("friends.html")

@app.route("/logout")
def logout():
    #user logging out
    render_template("index.html")

@app.route("/profile")
def profile():
    #view users profile
    render_template("profile.html")


if __name__ == "__main__":
    app.run(debug=True, port=5000)