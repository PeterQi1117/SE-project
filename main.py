from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    jsonify,
)

import os
from google.cloud import firestore
from pyparsing import wraps
import pyrebase
import datetime
import pytz
from dateutil.relativedelta import relativedelta

os.environ["GCLOUD_PROJECT"] = "se-project-406614"

db = firestore.Client()
user_roles_collection = db.collection("user_roles")

classrooms_4_collection = db.collection("classroom-4")  # 20
classrooms_3_collection = db.collection("classroom-3")  # 18
classrooms_twaddler_collection = db.collection("classroom-twaddler")  # 16
classrooms_toddler_collection = db.collection("classroom-toddler")  # 12
classrooms_infant_collection = db.collection("classroom-infant")  # 8

enrollments_collection = db.collection("enrollments")
staff_collection = db.collection("staff")
facility_collection = db.collection("facilities")

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
        role = request.form["role"]
        auth.create_user_with_email_and_password(email, password)
        user_roles_collection.add({"email": email, "role": role})
        if role == "facility-admin":
            classrooms_4_collection.add(
                {"adminEmail": email, "teachers": [], "students": []}
            )
            classrooms_3_collection.add(
                {"adminEmail": email, "teachers": [], "students": []}
            )
            classrooms_twaddler_collection.add(
                {"adminEmail": email, "teachers": [], "students": []}
            )
            classrooms_toddler_collection.add(
                {"adminEmail": email, "teachers": [], "students": []}
            )
            classrooms_infant_collection.add(
                {"adminEmail": email, "teachers": [], "students": []}
            )

            facility_collection.add(
                {
                    "facilityName": "",
                    "facilityAddress": "",
                    "facilityPhoneNumber": "",
                    "facilityAdminName": "",
                    "facilityAdminEmail": email,
                    "facilityAdminContact": "",
                    "facilityLicenseNumber": "",
                }
            )

        return redirect("/login")
    return render_template("signup.html")


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/login")


def get_user_role(email):
    role_query = user_roles_collection.where("email", "==", email).limit(1)
    user_role = role_query.get()[0].to_dict()
    role = user_role["role"]
    return role


def get_tuition_owed(enrollment):
    classification = enrollment["classification"]

    if classification == "infant":
        cost = 300
    elif classification == "toddler":
        cost = 275
    elif classification == "twaddler":
        cost = 250
    elif classification == "3":
        cost = 225
    else:
        cost = 200

    dateEnrolled = enrollment["dateEnrolled"]
    if dateEnrolled == datetime.datetime(1970, 1, 1, tzinfo=pytz.UTC):
        return 0

    payments = enrollment["payments"]

    payments_data = []
    for payment in payments:
        payments_data.append(
            {
                "amount": payment["amount"],
                "date": payment["date"].strftime("%m/%d/%Y"),
            }
        )

    amountPaid = [payment["amount"] for payment in payments]

    current_date = datetime.datetime.now(pytz.UTC)

    weeks_since_enrolled = int((current_date - dateEnrolled).days / 7)
    tuition_owed = weeks_since_enrolled * cost - sum(amountPaid)

    return weeks_since_enrolled * cost, payments_data, tuition_owed, cost


def get_classroom_data(collection, adminEmail, classroom_id, include_attendance=False):
    ids = (
        collection.where("adminEmail", "==", adminEmail)
        .limit(1)
        .get()[0]
        .to_dict()
    )

    if not ids:
        return {"teachers": [], "students": []}

    teachers = []
    for teacher_id in ids["teachers"]:
        teacher = staff_collection.document(teacher_id).get().to_dict()

        if teacher["attendance"]:
            didAttendToday = teacher["attendance"][-1].date() == datetime.datetime.utcnow().date()
        else:
            didAttendToday = False

        teacher_data = {
            "id": teacher_id,
            "first-name": teacher["firstName"],
            "last-name": teacher["lastName"],
            "didAttendToday": didAttendToday,
        }
        teachers.append(teacher_data)

    students = []
    for student_id in ids["students"]:
        student = enrollments_collection.document(student_id).get().to_dict()

        if student["attendance"]:
            didAttendToday = student["attendance"][-1].date() == datetime.datetime.utcnow().date()
        else:
            didAttendToday = False

        student_data = {
            "id": student_id,
            "first-name": student["firstName"],
            "last-name": student["lastName"],
            "classification": student["classification"],
            "dob": student["dob"],
            "didAttendToday": didAttendToday,
        }
        students.append(student_data)

    classroom_data = {"teachers": teachers, "students": students}

    classroom_data["id"] = classroom_id

    return classroom_data


@app.route("/")
@user_required
def home():
    email = session["user"]["email"]
    role = get_user_role(email)
    if role == "facility-admin":
        earned = 0
        billed = 0

        start, end = getWeekRange(0)
        
        start = start.replace(tzinfo=pytz.UTC)
        end = end.replace(tzinfo=pytz.UTC)

        enrollments = enrollments_collection.get()

        for enrollment in enrollments:
            dict = enrollment.to_dict()

            if dict["adminEmail"] != email:
                continue

            if dict["enrolled"]:
                billed += get_tuition_owed(dict)[3]

                payments = dict["payments"]
                for payment in payments:
                    payment_date = payment["date"]
                    if start <= payment_date.replace(tzinfo=pytz.UTC) <= end:
                        earned += payment["amount"]

        classrooms_data = []

        classrooms_data.append(
            get_classroom_data(classrooms_4_collection, email, 4, True)
        )
        classrooms_data.append(
            get_classroom_data(classrooms_3_collection, email, 3, True)
        )
        classrooms_data.append(
            get_classroom_data(classrooms_twaddler_collection, email, "twaddler", True)
        )
        classrooms_data.append(
            get_classroom_data(classrooms_toddler_collection, email, "toddler", True)
        )
        classrooms_data.append(
            get_classroom_data(classrooms_infant_collection, email, "infant", True)
        )


        return render_template("dashboard_facility_admin.html", role=role, earned=earned, billed=billed, classrooms_data=classrooms_data)


    elif role == "teacher":
        teacher = (
            staff_collection.where("email", "==", session["user"]["email"])
            .limit(1)
            .get()[0]
        )

        dict = teacher.to_dict()

        if len(dict["attendance"]) % 2 == 1:
            label = "Check Out"
        else:
            label = "Check In"

        dict.update({"sign-in-out-button": label, "id": teacher.id})

        return render_template("dashboard_teacher.html", role=role, teacher=dict)
    elif role == "parent":
        enrolled_children = []
        enrollments = enrollments_collection.get()
        for enrollment in enrollments:
            dict = enrollment.to_dict()

            if dict["email"] != session["user"]["email"]:
                continue

            if dict["enrolled"] == True:
                if len(dict["attendance"]) % 2 == 1:
                    label = "Check Out"
                else:
                    label = "Check In"

                enrolled_children.append(
                    {**dict, "id": enrollment.id, "sign-in-out-button": label}
                )

        return render_template(
            "dashboard_parent.html",
            enrolled_children=enrolled_children,
            role=role,
        )

    return jsonify(error="Invalid role"), 400


@app.route("/facility", methods=["GET", "POST"])
@user_required
def facility():
    # allow the admin to edit the facility information
    adminEmail = session["user"]["email"]
    role = get_user_role(adminEmail)
    if role == "facility-admin":
        if request.method == "POST":
            facilityName = request.form["facility-name"]
            facilityAddress = request.form["facility-address"]
            facilityPhoneNumber = request.form["facility-phone-number"]
            facilityAdminName = request.form["facility-admin-name"]
            facilityAdminContact = request.form["facility-admin-contact"]
            facilityLicenseNumber = request.form["facility-license-number"]

            facility_collection.where("facilityAdminEmail", "==", adminEmail).limit(
                1
            ).get()[0].reference.update(
                {
                    "facilityName": facilityName,
                    "facilityAddress": facilityAddress,
                    "facilityPhoneNumber": facilityPhoneNumber,
                    "facilityAdminName": facilityAdminName,
                    "facilityAdminContact": facilityAdminContact,
                    "facilityLicenseNumber": facilityLicenseNumber,
                }
            )

            return redirect("/facility")

        facility_data = (
            facility_collection.where("facilityAdminEmail", "==", adminEmail)
            .limit(1)
            .get()[0]
            .to_dict()
        )

        return render_template(
            "facility_admin_facility.html", facility_data=facility_data, role=role
        )


@app.route("/enroll", methods=["GET", "POST"])
@user_required
def enroll():
    adminEmail = session["user"]["email"]
    role = get_user_role(adminEmail)
    if role == "facility-admin":
        if request.method == "POST":
            firstName = request.form["first-name"]
            lastName = request.form["last-name"]
            dob = request.form["dob"]
            allergies = request.form["allergies"]
            parentNames = request.form["parent-names"]
            phoneNumber = request.form["phone-number"]
            address = request.form["address"]
            email = request.form["email"]

            def get_years_since_dob(dob):
                current_date = datetime.date.today()
                dob_date = datetime.datetime.strptime(dob, "%Y-%m-%d").date()
                years_since_dob = current_date.year - dob_date.year
                if current_date.month < dob_date.month or (
                    current_date.month == dob_date.month
                    and current_date.day < dob_date.day
                ):
                    years_since_dob -= 1
                return years_since_dob

            years_since_dob = get_years_since_dob(dob)
            classification = ""
            if years_since_dob < 1:
                classification = "infant"
            elif years_since_dob < 2:
                classification = "toddler"
            elif years_since_dob < 3:
                classification = "twaddler"
            elif years_since_dob < 4:
                classification = "3"
            else:
                classification = "4"

            enrollments_collection.add(
                {
                    "adminEmail": adminEmail,
                    "firstName": firstName,
                    "lastName": lastName,
                    "dob": dob,
                    "allergies": allergies,
                    "parentNames": parentNames,
                    "phoneNumber": phoneNumber,
                    "address": address,
                    "email": email,
                    "classification": classification,
                    "waitlist": True,
                    "enrolled": False,
                    "dateEnrolled": datetime.datetime(1970, 1, 1),
                    "payments": [],
                    "attendance": [],
                }
            )

            return redirect("/enroll")

        enrolled_children = []
        waitlisted_children = []

        enrollments = enrollments_collection.get()
        for enrollment in enrollments:
            dict = enrollment.to_dict()
            if dict["enrolled"] == True:
                if len(dict["attendance"]) % 2 == 1:
                    label = "Check Out"
                else:
                    label = "Check In"

                enrolled_children.append(
                    {**dict, "id": enrollment.id, "sign-in-out-button": label}
                )
            elif dict["waitlist"] == True:
                waitlisted_children.append({**dict, "id": enrollment.id})

        return render_template(
            "facility_admin_enroll.html",
            enrolled_children=enrolled_children,
            waitlisted_children=waitlisted_children,
            role=role,
        )
    else:
        return jsonify(error="You do not have permission to access this page."), 403


@app.route("/enroll/edit/<id>", methods=["GET", "POST"])
@user_required
def edit_enrollment(id):
    email = session["user"]["email"]

    role = get_user_role(email)

    enrollment = enrollments_collection.document(id).get().to_dict()

    isParent = role == "parent" and email == enrollment["email"]

    if role == "facility-admin" or isParent:
        if request.method == "POST":
            firstName = request.form["first-name"]
            lastName = request.form["last-name"]
            allergies = request.form["allergies"]
            parentNames = request.form["parent-names"]
            phoneNumber = request.form["phone-number"]
            address = request.form["address"]
            email = request.form["email"]
            classification = request.form["classification"]

            enrollments_collection.document(id).update(
                {
                    "firstName": firstName,
                    "lastName": lastName,
                    "allergies": allergies,
                    "parentNames": parentNames,
                    "phoneNumber": phoneNumber,
                    "address": address,
                    "email": email,
                    "classification": classification,
                }
            )

            if isParent:
                return redirect("/")

            return redirect("/enroll")

        return render_template(
            "edit_enrollment.html", enrollment=enrollment, role=role, id=id
        )
    else:
        return jsonify(error="You do not have permission to access this page."), 403


@app.route("/disenroll", methods=["POST"])
@user_required
def disenroll():
    adminEmail = session["user"]["email"]
    role = get_user_role(adminEmail)
    if role == "facility-admin":
        enrollments_collection.document(request.form["id"]).update({"enrolled": False})

        return redirect("/enroll")
    else:
        return jsonify(error="You do not have permission to access this page."), 403


@app.route("/waitlist", methods=["POST"])
@user_required
def waitlist():
    adminEmail = session["user"]["email"]
    role = get_user_role(adminEmail)
    if role == "facility-admin":
        enrollments_collection.document(request.form["id"]).update({"waitlist": True})
        enrollments_collection.document(request.form["id"]).update({"enrolled": False})

        return redirect("/enroll")
    else:
        return jsonify(error="You do not have permission to access this page."), 403


@app.route("/unwaitlist", methods=["POST"])
@user_required
def unwaitlist():
    adminEmail = session["user"]["email"]
    role = get_user_role(adminEmail)
    if role == "facility-admin":
        enrollments_collection.document(request.form["id"]).update(
            {"waitlist": False, "dateEnrolled": datetime.datetime.utcnow()}
        )
        enrollments_collection.document(request.form["id"]).update({"enrolled": True})

        return redirect("/enroll")
    else:
        return jsonify(error="You do not have permission to access this page."), 403


@app.route("/sign-in-out", methods=["POST"])
@user_required
def sign_in_out():
    email = session["user"]["email"]
    role = get_user_role(email)

    child = enrollments_collection.document(request.form["id"]).get().to_dict()
    isParent = role == "parent" and email == child["email"]

    teacher = staff_collection.document(request.form["id"]).get().to_dict()
    isTeacher = role == "teacher" and email == teacher["email"]

    if role == "facility-admin" or isParent or isTeacher:
        timestamp = datetime.datetime.utcnow()
        if isTeacher:
            collection = staff_collection
        else:
            collection = enrollments_collection

        collection.document(request.form["id"]).update(
            {"attendance": firestore.ArrayUnion([timestamp])}
        )
        if isParent or isTeacher:
            return redirect("/")
        return redirect("/enroll")
    else:
        return jsonify(error="You do not have permission to access this page."), 403


@app.route("/staff", methods=["GET", "POST", "DELETE"])
@user_required
def staff():
    adminEmail = session["user"]["email"]
    role = get_user_role(adminEmail)
    if role == "facility-admin":
        if request.method == "POST":
            firstName = request.form["first-name"]
            lastName = request.form["last-name"]
            email = request.form["email"]
            dob = request.form["dob"]
            address = request.form["address"]
            phoneNumber = request.form["phone-number"]
            hourlySalary = request.form["hourly-salary"]

            staff_collection.add(
                {
                    "email": email,
                    "adminEmail": adminEmail,
                    "firstName": firstName,
                    "lastName": lastName,
                    "dob": dob,
                    "address": address,
                    "phoneNumber": phoneNumber,
                    "hourlySalary": hourlySalary,
                    "attendance": [],
                }
            )

            return redirect("/staff")

        staff_data = []
        staff = staff_collection.get()
        for teacher in staff:
            staff_data.append({**teacher.to_dict(), "id": teacher.id})

        return render_template(
            "facility_admin_hire.html", staff_data=staff_data, role=role
        )
    else:
        return jsonify(error="You do not have permission to access this page."), 403


@app.route("/fire-staff", methods=["POST"])
@user_required
def fire_staff():
    adminEmail = session["user"]["email"]
    role = get_user_role(adminEmail)
    if role == "facility-admin":
        staff_collection.document(request.form["id"]).delete()

        return redirect("/staff")
    else:
        return jsonify(error="You do not have permission to access this page."), 403


@app.route("/classrooms", methods=["GET"])
@user_required
def classrooms():
    adminEmail = session["user"]["email"]
    role = get_user_role(adminEmail)
    if role == "facility-admin":
        classrooms_data = []

        classrooms_data.append(
            get_classroom_data(classrooms_4_collection, adminEmail, 4)
        )
        classrooms_data.append(
            get_classroom_data(classrooms_3_collection, adminEmail, 3)
        )
        classrooms_data.append(
            get_classroom_data(classrooms_twaddler_collection, adminEmail, "twaddler")
        )
        classrooms_data.append(
            get_classroom_data(classrooms_toddler_collection, adminEmail, "toddler")
        )
        classrooms_data.append(
            get_classroom_data(classrooms_infant_collection, adminEmail, "infant")
        )

        return render_template(
            "facility_admin_classrooms.html", classrooms_data=classrooms_data, role=role
        )
    else:
        return jsonify(error="You do not have permission to access this page."), 403


@app.route("/classrooms/add-student/<type>", methods=["POST"])
@user_required
def addStudentToClassroom(type):
    adminEmail = session["user"]["email"]
    role = get_user_role(adminEmail)
    if role == "facility-admin":
        firstName = request.form["first-name"]
        lastName = request.form["last-name"]

        id = (
            enrollments_collection.where("firstName", "==", firstName)
            .where("lastName", "==", lastName)
            .get()[0]
            .id
        )

        student = enrollments_collection.document(id).get().to_dict()

        if "classification" in student and student["classification"] != type:
            return jsonify(error="Student is not in the right classroom"), 400

        if type == "4":
            collection = classrooms_4_collection
        elif type == "3":
            collection = classrooms_3_collection
        elif type == "twaddler":
            collection = classrooms_twaddler_collection
        elif type == "toddler":
            collection = classrooms_toddler_collection
        elif type == "infant":
            collection = classrooms_infant_collection

        documents = collection.where("adminEmail", "==", adminEmail).get()

        for document in documents:
            doc_data = document.to_dict()
            if "students" in doc_data:
                students_list = doc_data["students"]
            else:
                students_list = []
 
            if len(students_list) >= 8 and type == "infant":
                return jsonify(error="Classroom is full"), 400
            elif len(students_list) >= 12 and type == "toddler":
                return jsonify(error="Classroom is full"), 400
            elif len(students_list) >= 16 and type == "twaddler":
                return jsonify(error="Classroom is full"), 400
            elif len(students_list) >= 18 and type == "3":
                return jsonify(error="Classroom is full"), 400
            elif len(students_list) >= 20 and type == "4":
                return jsonify(error="Classroom is full"), 400

            if "teachers" in doc_data:
                teachers_list = doc_data["teachers"]
            else:
                teachers_list = []

            if len(teachers_list) == 0 or type == "infant" and (len(students_list) + 1) / len(teachers_list) > 4:
                return jsonify(error="Classroom needs another teacher"), 400
            elif (
                type == "toddler" and (len(students_list) + 1) / len(teachers_list) > 6
            ):
                return jsonify(error="Classroom needs another teacher"), 400
            elif (
                type == "twaddler" and (len(students_list) + 1) / len(teachers_list) > 8
            ):
                return jsonify(error="Classroom needs another teacher"), 400
            elif type == "3" and (len(students_list) + 1) / len(teachers_list) > 9:
                return jsonify(error="Classroom needs another teacher"), 400
            elif type == "4" and (len(students_list) + 1) / len(teachers_list) > 10:
                return jsonify(error="Classroom needs another teacher"), 400

            students_list.append(id)
            collection.document(document.id).update({"students": students_list})

        return redirect("/classrooms")
    else:
        return jsonify(error="You do not have permission to access this page."), 403


@app.route("/classrooms/remove-student/<type>", methods=["POST"])
@user_required
def removeStudentFromClassroom(type):
    adminEmail = session["user"]["email"]
    role = get_user_role(adminEmail)
    if role == "facility-admin":
        id = request.form["id"]

        if type == "4":
            collection = classrooms_4_collection
        elif type == "3":
            collection = classrooms_3_collection
        elif type == "twaddler":
            collection = classrooms_twaddler_collection
        elif type == "toddler":
            collection = classrooms_toddler_collection
        elif type == "infant":
            collection = classrooms_infant_collection

        documents = collection.where("adminEmail", "==", adminEmail).get()

        for document in documents:
            doc_data = document.to_dict()
            if "students" in doc_data:
                students_list = doc_data["students"]
            else:
                students_list = []
            for student in students_list:
                if student == id:
                    students_list.remove(student)
            collection.document(document.id).update({"students": students_list})

        return redirect("/classrooms")
    else:
        return jsonify(error="You do not have permission to access this page."), 403


@app.route("/classrooms/add-teacher/<type>", methods=["POST"])
@user_required
def addTeacherToClassroom(type):
    adminEmail = session["user"]["email"]
    role = get_user_role(adminEmail)
    if role == "facility-admin":
        firstName = request.form["first-name"]
        lastName = request.form["last-name"]

        id = (
            staff_collection.where("firstName", "==", firstName)
            .where("lastName", "==", lastName)
            .get()[0]
            .id
        )

        if type == "4":
            collection = classrooms_4_collection
        elif type == "3":
            collection = classrooms_3_collection
        elif type == "twaddler":
            collection = classrooms_twaddler_collection
        elif type == "toddler":
            collection = classrooms_toddler_collection
        elif type == "infant":
            collection = classrooms_infant_collection

        documents = collection.where("adminEmail", "==", adminEmail).get()

        for document in documents:
            doc_data = document.to_dict()
            if "teachers" in doc_data:
                teacher_list = doc_data["teachers"]
            else:
                teacher_list = []
            teacher_list.append(id)
            collection.document(document.id).update({"teachers": teacher_list})

        return redirect("/classrooms")
    else:
        return jsonify(error="You do not have permission to access this page."), 403


@app.route("/classrooms/remove-teacher/<type>", methods=["POST"])
@user_required
def removeTeacherFromClassroom(type):
    adminEmail = session["user"]["email"]
    role = get_user_role(adminEmail)
    if role == "facility-admin":
        id = request.form["id"]

        if type == "4":
            collection = classrooms_4_collection
        elif type == "3":
            collection = classrooms_3_collection
        elif type == "twaddler":
            collection = classrooms_twaddler_collection
        elif type == "toddler":
            collection = classrooms_toddler_collection
        elif type == "infant":
            collection = classrooms_infant_collection

        documents = collection.where("adminEmail", "==", adminEmail).get()

        for document in documents:
            doc_data = document.to_dict()
            if "teachers" in doc_data:
                teacher_list = doc_data["teachers"]
            else:
                teacher_list = []
            for teacher in teacher_list:
                if teacher == id:
                    teacher_list.remove(teacher)
            collection.document(document.id).update({"teachers": teacher_list})

        return redirect("/classrooms")
    else:
        return jsonify(error="You do not have permission to access this page."), 403


@app.route("/ledger/<id>", methods=["GET"])
@user_required
def ledger(id):
    email = session["user"]["email"]
    role = get_user_role(email)

    enrollment = enrollments_collection.document(id).get().to_dict()

    number_of_weeks = int(
        (datetime.datetime.now(pytz.UTC) - enrollment["dateEnrolled"]).days / 7
    )

    isParent = role == "parent" and email == enrollment["email"]

    if role == "facility-admin" or isParent:
        charges, payments, owed, cost = get_tuition_owed(enrollment)

        return render_template(
            "ledger_child.html",
            role=role,
            charges=charges,
            payments=payments,
            owed=owed,
            number_of_weeks=number_of_weeks,
            cost=cost,
            id=id,
            name=enrollment["firstName"] + " " + enrollment["lastName"],
        )
    else:
        return jsonify(error="You do not have permission to access this page."), 403


@app.route("/make_payment", methods=["POST"])
@user_required
def make_payment():
    email = session["user"]["email"]
    role = get_user_role(email)

    enrollment = enrollments_collection.document(request.form["id"]).get().to_dict()

    isParent = role == "parent" and email == enrollment["email"]

    if isParent:
        amount = int(request.form["amount"])

        payments = enrollment["payments"]
        payments.append({"amount": amount, "date": datetime.datetime.utcnow()})
        enrollments_collection.document(request.form["id"]).update(
            {"payments": payments}
        )

        return redirect("/ledger/" + request.form["id"])
    else:
        return jsonify(error="You do not have permission to access this page."), 403


def getWeekRange(offset):
    current_date = datetime.datetime.utcnow()
    current_date += relativedelta(weeks=offset)

    start_of_week = current_date - datetime.timedelta(days=current_date.weekday())
    end_of_week = start_of_week + datetime.timedelta(days=5)

    return start_of_week, end_of_week


def getMonthRange(offset):
    current_date = datetime.datetime.utcnow()
    current_date += relativedelta(months=offset)

    start_of_month = current_date.replace(day=1)
    end_of_month = start_of_month + relativedelta(months=1) - datetime.timedelta(days=1)

    return start_of_month, end_of_month


@app.route("/attendance/<id>/<type>/<offset>", methods=["GET"])
@user_required
def attendance(id, type, offset):
    email = session["user"]["email"]
    role = get_user_role(email)

    if role == "parent":
        dict = enrollments_collection.document(id).get().to_dict()
    elif role == "teacher":
        dict = staff_collection.document(id).get().to_dict()

    isParent = role == "parent" and email == dict["email"]
    isTeacher = role == "teacher" and email == dict["email"]

    if role == "facility-admin" or isParent or isTeacher:
        attendance = dict["attendance"]

        offset = int(offset)

        if type == "week":
            start, end = getWeekRange(offset)
        elif type == "month":
            start, end = getMonthRange(offset)

        start = start.replace(tzinfo=pytz.UTC)
        end = end.replace(tzinfo=pytz.UTC)

        attendance = [
            ts for ts in attendance if start <= ts.replace(tzinfo=pytz.UTC) <= end
        ]

        name = dict["firstName"] + " " + dict["lastName"]

        salaryEarned = 0
        hoursWorked = 0

        if isTeacher:
            hoursWorked = 0

            for i in range(1, len(attendance), 2):
                even_entry = attendance[i-1]
                odd_entry = attendance[i]
                hours_between_entries = (odd_entry - even_entry).total_seconds() / 3600
                hoursWorked += hours_between_entries

            salaryEarned = float(dict["hourlySalary"]) * hoursWorked

        return render_template(
            "attendance.html",
            attendance=attendance,
            name=name,
            role=role,
            offset=offset,
            type=type,
            id=id,
            salaryEarned=salaryEarned,
            hoursWorked=hoursWorked,
        )
    else:
        return jsonify(error="You do not have permission to access this page."), 403


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
