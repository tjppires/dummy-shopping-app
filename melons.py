from flask import Flask, request, session, render_template, g, redirect, url_for, flash, jsonify
import model
import jinja2
import os
import qrcode
import uuid
import threading
import time

TIMEOUT = 40  # ~40 seconds (poorly implemented, can be less - at least 30s)
SLEEP_TIME = 10  # 10 seconds
jobs_lock = threading.Lock()
job_stats = {}
STORE_NAME = "MyStoreQR"

class Job:
    def __init__(self, uid, price):
        self.uid = uid
        self.price = price
        self.status = "waiting"
        self.ttl = TIMEOUT
        self.store_name = STORE_NAME
    def timeout(self):
        self.status = "timeout"
        self.ttl = 0
    def complete(self):
        if self.status != "timeout":
            self.status = "completed"
    def is_completed(self):
        return self.status == "completed"
    def __repr__(self):
        return "{0}:{1}".format(self.status, self.ttl)

def manage_timeouts():
    while True:
        time.sleep(SLEEP_TIME)
        jobs_lock.acquire()
        for uid in job_stats.keys():
            job_stats[uid].ttl -= SLEEP_TIME
            if job_stats[uid].ttl <= 0 and not job_stats[uid].is_completed():
                job_stats[uid].timeout()
        jobs_lock.release()

t = threading.Thread(target=manage_timeouts)
t.daemon = True
t.start()

def add_job(uid, price):
    jobs_lock.acquire()
    job_stats[uid] = Job(uid, price)
    jobs_lock.release()

def check_job(uid):
    if uid is None:
        return None
    jobs_lock.acquire()
    result = job_stats.get(uid)
    jobs_lock.release()
    return result

def complete_job(uid):
    if uid is None:
        return
    jobs_lock.acquire()
    job_stats[uid].complete()
    jobs_lock.release()

app = Flask(__name__)
app.secret_key = '\xf5!\x07!qj\xa4\x08\xc6\xf8\n\x8a\x95m\xe2\x04g\xbb\x98|U\xa2f\x03'
app.jinja_env.undefined = jinja2.StrictUndefined

@app.route("/")
def index():
    """This is the 'cover' page of the ubermelon site"""
    return redirect("/melons")
    return render_template("index.html")

@app.route("/melons")
def list_melons():
    """This is the big page showing all the melons ubermelon has to offer"""
    melons = model.get_melons()
    return render_template("all_melons.html",
                           melon_list = melons)

@app.route("/melon/<int:id>")
def show_melon(id):
    """This page shows the details of a given melon, as well as giving an
    option to buy the melon."""
    melon = model.get_melon_by_id(id)
    return render_template("melon_details.html",
                  display_melon = melon)

@app.route("/cart")
def shopping_cart():
    """TODO: Display the contents of the shopping cart. The shopping cart is a
    list held in the session that contains all the melons to be added. Check
    accompanying screenshots for details."""
    if "cart" not in session:
        flash("There is nothing in your cart.")
        return render_template("cart.html", display_cart = {}, total = 0)
    else:
        items = session["cart"]
        dict_of_melons = {}

        total_price = 0
        for item in items:
            melon = model.get_melon_by_id(item)
            total_price += melon.price
            if melon.id in dict_of_melons:
                dict_of_melons[melon.id]["qty"] += 1
            else:
                dict_of_melons[melon.id] = {"qty":1, "name": melon.common_name, "price":melon.price}
        
        return render_template("cart.html", display_cart = dict_of_melons, total = total_price)  
    

@app.route("/add_to_cart/<int:id>")
def add_to_cart(id):
    """TODO: Finish shopping cart functionality using session variables to hold
    cart list.

    Intended behavior: when a melon is added to a cart, redirect them to the
    shopping cart page, while displaying the message
    "Successfully added to cart" """

    if "cart" not in session:
        session["cart"] = []

    session["cart"].append(id)

    flash("Successfully added to cart!")
    return redirect("/cart")


@app.route("/login", methods=["GET"])
def show_login():
    session["logged_in"] = False
    return render_template("login.html")


@app.route("/login", methods=["POST"])
def process_login():
    """TODO: Receive the user's login credentials located in the 'request.form'
    dictionary, look up the user, and store them in the session."""
    session["logged_in"] = False
    email = request.form.get("email")
    # password = request.form.get("password")
    customer = model.get_customer_by_email(email)

    if customer:
        flash("Welcome, %s %s" % (customer.givenname, customer.surname))
        if "user" in session:
            session["logged_in"] = True
        else:
            session["user"] = email
            session["logged_in"] = True
        return redirect("/melons")
    else:
        flash("That is an invalid login.")
        session["logged_in"] = False
        return render_template("login.html")


@app.route("/empty")
def empty_chart():
    """Empty chart"""
    session.clear()
    return redirect("/melons")


@app.route("/checkout")
def checkout():
    """QR checkout system"""
    flash("1-Click QR code checkout")
    if "cart" not in session:
        flash("There is nothing in your cart.")
        return redirect("/melons")
    else:
        items = session["cart"]
        dict_of_melons = {}

        total_price = 0
        for item in items:
            melon = model.get_melon_by_id(item)
            total_price += melon.price
    uid = uuid.uuid4().hex
    qr_img = qrcode.make(uid)
    qr_path = "static/img/{0}.png".format(uid)
    qr_img.save(qr_path)
    add_job(uid, total_price)
    return render_template("checkout.html", display_cart={}, total=total_price, qr_id=uid)

@app.route("/success")
def success():
    session.clear()
    return render_template("success.html")

@app.route("/timeout")
def timeout():
    return render_template("transaction_failed.html")

@app.route("/validate", methods=['GET', 'POST'])
def qr_validation():
    """REST API for QR validation"""
    if request.method == "GET":
        uid = request.args.get("uid")
        job = check_job(uid)
        if not job is None:
            response = {"status": job.status, "price": job.price, "store": job.store_name}
        else:
            response = {"status": "invalid_id"}
    elif request.method == "POST":
        uid = request.values.get("uid")
        complete_job(uid)
        if uid is None:
            response = {"status": "invalid_id"}
        else:
            response = {"status": "completed"}
    return jsonify(response)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, port=port)
