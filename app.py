import json
import os
import sqlite3

from flask import Flask, g, jsonify, render_template, request

app = Flask(__name__)
DB_PATH = os.environ.get("DB_PATH", "quiz.db")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            questions TEXT NOT NULL,
            created TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            score INTEGER NOT NULL,
            total INTEGER NOT NULL,
            created TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.commit()
    conn.close()


init_db()


def clean_questions(raw):
    """Validate questions from the client. Returns (questions, error)."""
    if not isinstance(raw, list) or not 1 <= len(raw) <= 30:
        return None, "A quiz needs between 1 and 30 questions."
    out = []
    for i, q in enumerate(raw, start=1):
        text = str(q.get("text", "")).strip()
        options = [str(o).strip() for o in q.get("options", [])]
        answer = q.get("answer")
        if not text:
            return None, f"Question {i} has no text."
        if not 2 <= len(options) <= 6 or not all(options):
            return None, f"Question {i} needs 2 to 6 filled-in options."
        if not isinstance(answer, int) or not 0 <= answer < len(options):
            return None, f"Question {i} has no correct answer selected."
        out.append({"text": text[:300], "options": [o[:150] for o in options], "answer": answer})
    return out, None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/quizzes", methods=["GET"])
def list_quizzes():
    rows = get_db().execute(
        """
        SELECT q.id, q.title, q.questions,
               (SELECT COUNT(*) FROM scores s WHERE s.quiz_id = q.id) AS attempts
        FROM quizzes q ORDER BY q.id DESC
        """
    ).fetchall()
    return jsonify(
        [
            {
                "id": r["id"],
                "title": r["title"],
                "count": len(json.loads(r["questions"])),
                "attempts": r["attempts"],
            }
            for r in rows
        ]
    )


@app.route("/api/quizzes", methods=["POST"])
def create_quiz():
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()
    if not title:
        return jsonify(error="Give your quiz a title."), 400
    questions, error = clean_questions(data.get("questions"))
    if error:
        return jsonify(error=error), 400
    db = get_db()
    cur = db.execute(
        "INSERT INTO quizzes (title, questions) VALUES (?, ?)",
        (title[:100], json.dumps(questions)),
    )
    db.commit()
    return jsonify(id=cur.lastrowid), 201


def load_quiz(quiz_id):
    row = get_db().execute("SELECT * FROM quizzes WHERE id = ?", (quiz_id,)).fetchone()
    if row is None:
        return None, None
    return row, json.loads(row["questions"])


@app.route("/api/quizzes/<int:quiz_id>")
def get_quiz(quiz_id):
    row, questions = load_quiz(quiz_id)
    if row is None:
        return jsonify(error="Quiz not found."), 404
    # Never send the answers to the browser before the quiz is submitted.
    public = [{"text": q["text"], "options": q["options"]} for q in questions]
    return jsonify(id=row["id"], title=row["title"], questions=public)


@app.route("/api/quizzes/<int:quiz_id>/submit", methods=["POST"])
def submit_quiz(quiz_id):
    row, questions = load_quiz(quiz_id)
    if row is None:
        return jsonify(error="Quiz not found."), 404
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()[:40]
    answers = data.get("answers")
    if not name:
        return jsonify(error="Enter your name first."), 400
    if not isinstance(answers, list) or len(answers) != len(questions):
        return jsonify(error="Answer every question before submitting."), 400
    correct = [q["answer"] for q in questions]
    score = sum(1 for a, c in zip(answers, correct) if a == c)
    db = get_db()
    db.execute(
        "INSERT INTO scores (quiz_id, name, score, total) VALUES (?, ?, ?, ?)",
        (quiz_id, name, score, len(questions)),
    )
    db.commit()
    return jsonify(score=score, total=len(questions), correct=correct)


@app.route("/api/quizzes/<int:quiz_id>/leaderboard")
def leaderboard(quiz_id):
    rows = get_db().execute(
        """
        SELECT name, score, total FROM scores
        WHERE quiz_id = ? ORDER BY score DESC, created ASC LIMIT 10
        """,
        (quiz_id,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
