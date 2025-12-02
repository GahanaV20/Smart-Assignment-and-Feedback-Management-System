# app.py
import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, jsonify
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "devsecret")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "static/uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

def get_db():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST","localhost"),
        user=os.getenv("DB_USER","root"),
        password=os.getenv("DB_PASSWORD","aahana@18"),
        database=os.getenv("DB_NAME","assignment_system")
    )
@app.route("/")
def home():
    return render_template("index.html")


# ---- Auth routes ----
@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]
        role = request.form["role"]
        pw_hash = generate_password_hash(password)
        db = get_db()
        cur = db.cursor()
        try:
            cur.execute("INSERT INTO users (name,email,password_hash,role) VALUES (%s,%s,%s,%s)",
                        (name,email,pw_hash,role))
            db.commit()
            flash("Registered. Please login.")
            return redirect(url_for("login"))
        except mysql.connector.IntegrityError:
            flash("Email already registered.")
        finally:
            cur.close(); db.close()
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        db = get_db(); cur = db.cursor(dictionary=True)
        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cur.fetchone()
        cur.close(); db.close()
        if user and check_password_hash(user["password_hash"], password):
            session["user"] = {"user_id": user["user_id"], "name": user["name"], "role": user["role"]}
            if user["role"] == "Teacher":
                return redirect(url_for("teacher_dashboard"))
            return redirect(url_for("student_dashboard"))
        flash("Invalid credentials")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---- Teacher dashboard (simple) ----
@app.route("/teacher")
def teacher_dashboard():
    if not session.get("user") or session["user"]["role"] != "Teacher":
        return redirect(url_for("login"))
    db = get_db(); cur=db.cursor(dictionary=True)
    cur.execute("SELECT * FROM assignments WHERE created_by=%s ORDER BY created_at DESC", (session["user"]["user_id"],))
    assignments = cur.fetchall()
    cur.close(); db.close()
    return render_template("teacher_dashboard.html", assignments=assignments)

# ---- Student dashboard (simple) ----
from datetime import datetime

@app.route("/student")
def student_dashboard():
    if not session.get("user") or session["user"]["role"] != "Student":
        return redirect(url_for("login"))

    db = get_db()
    cur = db.cursor(dictionary=True)

    # Get ALL assignments
    cur.execute("""
        SELECT a.assignment_id, a.title, a.description, a.deadline,
               a.assignment_type, a.attachment, u.name AS teacher_name
        FROM assignments a
        JOIN users u ON a.created_by = u.user_id
        ORDER BY a.deadline DESC
    """)
    assignments = cur.fetchall()

    # Get submitted assignment IDs by this student
    cur.execute("""
        SELECT assignment_id 
        FROM submissions 
        WHERE student_id = %s
    """, (session["user"]["user_id"],))

    submitted_rows = cur.fetchall()
    submitted = [row['assignment_id'] for row in submitted_rows]  # <-- MAIN FIX

    cur.close()
    db.close()

    from datetime import datetime
    now = datetime.now()   # needed for deadline check

    return render_template(
        "student_dashboard.html",
        assignments=assignments,
        submitted=submitted,   # <-- PASS PROPER LIST
        now=now
    )


# ---- Create assignment (teacher) ----
from datetime import datetime
import os

@app.route("/teacher/create", methods=["GET", "POST"])
def create_assignment():
    if not session.get("user") or session["user"]["role"] != "Teacher":
        return redirect(url_for("login"))

    db = get_db()
    cur = db.cursor()

    if request.method == "POST":
        title = request.form["title"]
        description = request.form["description"]
        assignment_type = request.form["assignment_type"]
        deadline = request.form["deadline"]

        deadline_dt = datetime.strptime(deadline, "%Y-%m-%dT%H:%M")
        if deadline_dt < datetime.now():
            flash("Deadline cannot be in the past.")
            return redirect(url_for("create_assignment"))

        attachment_path = None

        # =============================================
        # 📌 QUIZ TYPE
        # =============================================
        # =============================================
        # 📌 QUIZ TYPE — SAVE MULTIPLE QUESTIONS + OPTIONS
        # =============================================
        if assignment_type == "quiz":

            cur.execute("""
                INSERT INTO assignments (title, description, deadline, created_by, assignment_type)
                VALUES (%s, %s, %s, %s, %s)
            """, (title, description, deadline_dt, session["user"]["user_id"], assignment_type))

            assignment_id = cur.lastrowid

            questions = request.form.getlist("question[]")
            optA = request.form.getlist("option_a[]")
            optB = request.form.getlist("option_b[]")
            optC = request.form.getlist("option_c[]")
            optD = request.form.getlist("option_d[]")
            correct = request.form.getlist("correct_option[]")

            for i in range(len(questions)):
                cur.execute("""
                    INSERT INTO quiz_questions
                    (assignment_id, question_text, option_a, option_b, option_c, option_d, correct_answer)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                """, (assignment_id, questions[i], optA[i], optB[i], optC[i], optD[i], correct[i]))

            db.commit()
            flash("Quiz Assignment Created Successfully! 📝")
            return redirect(url_for("teacher_dashboard"))

        # =============================================
        # 📌 FILE TYPE — Save teacher attachment properly
        # =============================================
        if assignment_type == "file":
            file = request.files.get("attachment")
            if file and file.filename:
                filename = file.filename

                # Save file inside STATIC so students can access it
                folder = "static/uploads/assignments/"
                os.makedirs(folder, exist_ok=True)

                filepath = os.path.join(folder, filename)
                file.save(filepath)

                attachment_path = "uploads/assignments/" + filename # stored in DB for url_for()


        # =============================================
        # 📌 DEFAULT — WRITTEN ASSIGNMENT
        # =============================================
        cur.execute("""
            INSERT INTO assignments
            (title, description, deadline, created_by, assignment_type, attachment)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (title, description, deadline_dt, session["user"]["user_id"], assignment_type, attachment_path))

        db.commit()
        flash("Assignment created successfully! ✔", "success")
        return redirect(url_for("teacher_dashboard"))

    # Required for date input validation
    min_date = datetime.now().strftime("%Y-%m-%dT%H:%M")

    return render_template("create_assignment.html", min_date=min_date)


# ---- Upload submission (student) ----
# ---- Upload submission (student) ----
@app.route("/student/upload", methods=["POST"])
def upload_submission():
    if not session.get("user") or session["user"]["role"] != "Student":
        return redirect(url_for("login"))

    assignment_id = request.form["assignment_id"]
    file = request.files.get("file")

    db = get_db()
    cur = db.cursor(dictionary=True)

    # Get deadline
    cur.execute("SELECT deadline FROM assignments WHERE assignment_id=%s", (assignment_id,))
    assignment = cur.fetchone()

    from datetime import datetime
    now = datetime.now()

    # Deadline validation
    if now > assignment["deadline"]:
        flash("⛔ Deadline is over! Submission not allowed.", "danger")
        return redirect(url_for("student_dashboard"))

    # ========== SAVE FILE INTO static/uploads/ ==========
    filename = file.filename
    save_path = os.path.join("static/uploads", filename)  # actual storage path
    file.save(save_path)

    file_url = "uploads/" + filename   # this goes into DB (important!)

    # Insert submission into DB
    cur.execute("""
        INSERT INTO submissions (assignment_id, student_id, file_url, submitted_at)
        VALUES (%s, %s, %s, NOW())
    """, (assignment_id, session["user"]["user_id"], file_url))

    db.commit()
    cur.close()
    db.close()

    flash("📤 Assignment submitted successfully!", "success")
    return redirect(url_for("student_dashboard"))

@app.route("/student/quiz/<int:assignment_id>", methods=["GET", "POST"])
def take_quiz(assignment_id):
    if not session.get("user") or session["user"]["role"] != "Student":
        return redirect(url_for("login"))

    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("SELECT * FROM assignments WHERE assignment_id=%s", (assignment_id,))
    assignment = cur.fetchone()

    # Stop quiz after deadline
    from datetime import datetime
    if datetime.now() > assignment["deadline"]:
        flash("Deadline has passed — quiz closed.", "danger")
        return redirect(url_for("student_dashboard"))

    cur.execute("SELECT * FROM quiz_questions WHERE assignment_id=%s", (assignment_id,))
    questions = cur.fetchall()

    if request.method == "POST":
        # create a submission entry
        cur.execute("""
            INSERT INTO submissions (assignment_id, student_id, status)
            VALUES (%s, %s, 'Pending')
        """, (assignment_id, session["user"]["user_id"]))
        submission_id = cur.lastrowid

        # store answers
        for q in questions:
            answer = request.form.get(f"q{q['question_id']}")
            cur.execute("""
                INSERT INTO quiz_answers (submission_id, question_id, student_id, answer_text)
                VALUES (%s, %s, %s, %s)
            """, (submission_id, q["question_id"], session["user"]["user_id"], answer))

        db.commit()
        cur.close()
        db.close()

        flash("Quiz submitted successfully!", "success")
        return redirect(url_for("student_dashboard"))

    cur.close()
    db.close()

    return render_template("student_quiz.html", assignment=assignment, questions=questions)


# ---- Serve uploaded files ----
@app.route("/uploads/<path:filename>")
def uploads(filename):
    return send_from_directory(UPLOAD_DIR, filename)

@app.route("/teacher/submissions/<int:assignment_id>")
def view_submissions(assignment_id):
    if not session.get("user") or session["user"]["role"] != "Teacher":
        return redirect(url_for("login"))

    db = get_db()
    cur = db.cursor(dictionary=True)

    # Fetch assignment INCLUDING TYPE ❗
    cur.execute("SELECT title, assignment_type FROM assignments WHERE assignment_id=%s", (assignment_id,))
    assignment = cur.fetchone()

    # Fetch submissions
    cur.execute("""
        SELECT s.submission_id, s.submitted_at, s.status, s.file_url, s.marks,
               u.name AS student_name
        FROM submissions s
        JOIN users u ON s.student_id = u.user_id
        WHERE s.assignment_id=%s
        ORDER BY s.submitted_at DESC
    """, (assignment_id,))
    submissions = cur.fetchall()

    cur.close()
    db.close()

    return render_template("view_submissions.html",
                           assignment=assignment,
                           submissions=submissions)


@app.route("/teacher/review/<int:submission_id>", methods=["GET", "POST"])
def review_submission(submission_id):
    if not session.get("user") or session["user"]["role"] != "Teacher":
        return redirect(url_for("login"))

    db = get_db()
    cur = db.cursor(dictionary=True)

    # Fetch submission details
    cur.execute("""
        SELECT s.*, u.name AS student_name, a.title AS assignment_title, a.assignment_id
        FROM submissions s
        JOIN users u ON s.student_id = u.user_id
        JOIN assignments a ON s.assignment_id = a.assignment_id
        WHERE s.submission_id=%s
    """, (submission_id,))
    submission = cur.fetchone()


    # ===== WHEN TEACHER SUBMITS FEEDBACK =====
    if request.method == "POST":
        marks = request.form["marks"]
        comments = request.form["comments"]

        # ⛳ Save marks + feedback + review status inside submissions!!
        cur.execute("""
            UPDATE submissions
            SET marks=%s, feedback=%s, status='Reviewed'
            WHERE submission_id=%s
        """, (marks, comments, submission_id))

        db.commit()
        cur.close()
        db.close()

        flash("Written/File Assignment Graded Successfully 🎉", "success")
        return redirect(url_for("view_submissions", assignment_id=submission["assignment_id"]))


    return render_template("review_submission.html", submission=submission)


@app.route("/student/feedback")
def student_feedback():
    if not session.get("user") or session["user"]["role"] != "Student":
        return redirect(url_for("login"))

    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("""
        SELECT 
            a.title AS assignment_title,
            s.submitted_at,
            s.status,

            /* Single marks column for all assignments */
            IFNULL(s.total_marks, (SELECT marks FROM feedback WHERE submission_id=s.submission_id)) AS final_marks,

            s.feedback
        FROM submissions s
        JOIN assignments a ON s.assignment_id = a.assignment_id
        WHERE s.student_id = %s   -- 🔥 NOW shows written + file + quiz
        ORDER BY s.submitted_at ASC
    """, (session["user"]["user_id"],))

    records = cur.fetchall()

    # Chart Data
    labels = [r['assignment_title'] for r in records]
    marks = [r['final_marks'] if r['final_marks'] else 0 for r in records]

    return render_template("student_feedback.html",
                           records=records,
                           labels=labels,
                           marks=marks)



@app.route("/quiz/submit/<int:assignment_id>", methods=["POST"])
def submit_quiz(assignment_id):
    if not session.get("user") or session["user"]["role"] != "Student":
        return redirect(url_for("login"))

    db = get_db()
    cur = db.cursor(dictionary=True)

    # STEP 1 — Create submission row (use "" instead of NULL for file_url)
    cur.execute("""
        INSERT INTO submissions (assignment_id, student_id, status, file_url)
        VALUES (%s, %s, %s, %s)
    """, (assignment_id, session["user"]["user_id"], "Submitted", ""))   # 👈 important

    submission_id = cur.lastrowid

    # STEP 2 — Get all quiz questions
    cur.execute("SELECT question_id FROM quiz_questions WHERE assignment_id=%s", (assignment_id,))
    questions = cur.fetchall()

    # STEP 3 — Save each answer
    for q in questions:
        ans = request.form.get(f"answer_{q['question_id']}")
        cur.execute("""
            INSERT INTO quiz_answers (submission_id, question_id, student_id, answer_text)
            VALUES (%s, %s, %s, %s)
        """, (submission_id, q["question_id"], session["user"]["user_id"], ans))

    db.commit()
    cur.close()
    db.close()

    flash("Quiz Submitted Successfully 🎉", "success")
    return redirect(url_for("student_dashboard"))
@app.route("/review_quiz/<int:submission_id>", methods=["GET", "POST"])
def review_quiz_submission(submission_id):

    if not session.get("user") or session["user"]["role"] != "Teacher":
        return redirect(url_for("login"))

    db = get_db()
    cur = db.cursor(dictionary=True)

    # Get quiz questions + student responses
    cur.execute("""
        SELECT q.question_id, q.question_text, q.correct_answer,
               a.answer_text, a.marks
        FROM quiz_answers a
        JOIN quiz_questions q ON a.question_id = q.question_id
        WHERE a.submission_id = %s
    """, (submission_id,))
    answers = cur.fetchall()

    # ============ SAVE MARKS + FEEDBACK ============
    if request.method == "POST":
        total = 0  # track total marks

        for ans in answers:
            mark = request.form.get(f"mark_{ans['question_id']}")  # marks assigned manually
            mark = int(mark) if mark else 0    
            total += mark

            cur.execute("""
                UPDATE quiz_answers SET marks=%s
                WHERE submission_id=%s AND question_id=%s
            """, (mark, submission_id, ans["question_id"]))

        feedback = request.form.get("feedback")

        # SAVE TOTAL MARKS + FEEDBACK IN SUBMISSIONS TABLE
        cur.execute("""
            UPDATE submissions SET status='Reviewed', total_marks=%s, feedback=%s 
            WHERE submission_id=%s
        """, (total, feedback, submission_id))

        db.commit()
        cur.close()

        flash("Quiz Graded Successfully 🎉", "success")
        return redirect(url_for("teacher_dashboard"))

    return render_template("review_quiz_submission.html", answers=answers, submission_id=submission_id)

@app.route("/assignment/delete/<int:assignment_id>")
def delete_assignment(assignment_id):

    if not session.get("user") or session["user"]["role"] != "Teacher":
        return redirect(url_for("login"))

    db = get_db()
    cur = db.cursor()

    # 1️⃣ Delete feedback linked to submissions of this assignment
    cur.execute("""
        DELETE f FROM feedback f 
        JOIN submissions s ON f.submission_id = s.submission_id
        WHERE s.assignment_id=%s
    """, (assignment_id,))

    # 2️⃣ Delete quiz answers
    cur.execute("""
        DELETE qa FROM quiz_answers qa
        JOIN quiz_questions qq ON qa.question_id = qq.question_id
        WHERE qq.assignment_id=%s
    """, (assignment_id,))

    # 3️⃣ Delete quiz questions
    cur.execute("DELETE FROM quiz_questions WHERE assignment_id=%s", (assignment_id,))

    # 4️⃣ Delete submissions
    cur.execute("DELETE FROM submissions WHERE assignment_id=%s", (assignment_id,))

    # 5️⃣ Finally delete assignment
    cur.execute("DELETE FROM assignments WHERE assignment_id=%s", (assignment_id,))

    db.commit()
    cur.close()
    db.close()

    flash("Assignment Deleted Successfully 🗑", "danger")
    return redirect(url_for("teacher_dashboard"))

if __name__ == "__main__":
    app.run(debug=True)
