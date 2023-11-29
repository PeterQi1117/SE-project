from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    jsonify,
)

import os
from google.cloud import storage, firestore
from pyparsing import wraps
import pyrebase
import base64

# Firebase configuration
config = {
    "apiKey": "AIzaSyBEc3NzCZIRLnbwJNs-l2IkfRAiWIqICFU",
    "authDomain": "se-project-406614.firebaseapp.com",
    "projectId": "se-project-406614",
    "storageBucket": "se-project-406614.appspot.com",
    "messagingSenderId": "3788737324",
    "appId": "1:3788737324:web:c0caf58ead4bf75a0cba89",
    "measurementId": "G-F3X9XJBT6Y",
    "databaseURL": "https://databaseName.firebaseio.com",
}

firebase = pyrebase.initialize_app(config)
auth = firebase.auth()

app = Flask(__name__)
app.secret_key = "supersecretkey"

def user_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if "user" not in session:
            return redirect("/login")
        return f(*args, **kwargs)

    return wrap

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        user = auth.sign_in_with_email_and_password(email, password)
        session["user"] = user
        return redirect(request.args.get("next") or "/")
    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        auth.create_user_with_email_and_password(email, password)
        return redirect("/login")
    return render_template("signup.html")


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/login")


storage_client = storage.Client()
bucket_name = "group-13-project-2"
bucket = storage_client.bucket(bucket_name)

db = firestore.Client()
files_metadata_collection = db.collection("files_metadata")


@app.route("/")
@user_required
def home():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
@user_required
def upload_file():
    if "file" not in request.files:
        return jsonify(error="No file part"), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify(error="No selected file"), 400

    user = session["user"]

    # Save file to Google Cloud Storage
    blob = bucket.blob(user["email"] + "/" + file.filename)
    blob.content_disposition = "attachment; filename={}".format(file.filename)
    blob.upload_from_string(file.read(), content_type=file.content_type)

    # Store metadata in Firestore
    metadata = {
        "location": user["email"] + "/" + file.filename,
        "filename": file.filename,
        "size": blob.size,
    }

    files_metadata_collection.add(metadata)

    return jsonify(success="File uploaded successfully")


@app.route("/view")
@user_required
def view_files():
    user = session["user"]

    key = user["email"] + "/"

    files = []

    files_metadata = files_metadata_collection.stream()
    for doc in files_metadata:
        file_data = doc.to_dict()
        filename = file_data["filename"]
        file_location = file_data["location"]

        if file_location.startswith(key) == False:
            continue

        blob = bucket.blob(file_location)
        file_blob = blob.download_as_bytes()
        base64_file = base64.b64encode(file_blob).decode("utf-8")

        files.append((filename, f"data:image/jpeg;base64,{base64_file}"))

    return render_template("view.html", files=files)


@app.route("/delete/<filename>", methods=["DELETE"])
@user_required
def delete_file(filename):
    user = session["user"]

    key = user["email"] + "/"

    files_metadata = files_metadata_collection.stream()
    for doc in files_metadata:
        file_data = doc.to_dict()
        file_location = file_data["location"]

        if file_location.startswith(key) == False:
            continue

        if file_data["filename"] == filename:
            doc.reference.delete()
            bucket.delete_blob(file_location)
            break

    return jsonify(success="File deleted successfully")


@app.route("/view/<filename>")
@user_required
def view_file(filename):
    user = session["user"]

    location = user["email"] + "/" + filename

    blob = bucket.blob(location)
    file_blob = blob.download_as_bytes()
    base64_file = base64.b64encode(file_blob).decode("utf-8")

    metadata = next(
        files_metadata_collection.where("filename", "==", filename).stream()
    ).to_dict()

    return render_template(
        "view-image.html",
        file=f"data:image/jpeg;base64,{base64_file}",
        metadata=metadata,
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
