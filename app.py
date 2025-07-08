from flask import Flask, render_template
from flask_session import  Session
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)

app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = "./.flask_session"
app.config["SESSION_PERMANENT"] = False
Session(app)


@app.route("/")
def index():
    #main game menu / looking for matches
    return render_template("index.html")

@app.route("/login")
def login():
    #user loging in
    return render_template("register.html")

@app.route("/register")
def register():
    #user registering
    render_template("register.html")

@app.route("/friends")
def friends():
    #adding friends and showing friends list
    render_template("friends.html")

@app.route("/logout")
def logout():
    #user logging out
    render_template("index.html")



if __name__ == "__main__":
    app.run(debug=True, port=5000)