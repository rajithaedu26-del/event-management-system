from flask import Flask, request, jsonify
import psycopg2
import os

app = Flask(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://dbadmin:password123@eventdb.ce966q66a0se.us-east-1.rds.amazonaws.com:5432/eventdb"
)

def get_connection():
    return psycopg2.connect(DATABASE_URL)

# Create table
conn = get_connection()
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS programs (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL,
    title VARCHAR(255) NOT NULL,
    speaker VARCHAR(255),
    start_time TIMESTAMP,
    end_time TIMESTAMP
)
""")

conn.commit()
cur.close()
conn.close()

print("✅ Program table ready!")

@app.route("/health")
def health():
    return jsonify({
        "service": "program-service",
        "status": "healthy"
    })


@app.route("/programs", methods=["GET"])
def get_programs():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id,event_id,title,speaker,start_time,end_time
        FROM programs
        ORDER BY id
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    programs = []

    for row in rows:
        programs.append({
            "id": row[0],
            "event_id": row[1],
            "title": row[2],
            "speaker": row[3],
            "start_time": str(row[4]),
            "end_time": str(row[5])
        })

    return jsonify(programs)


@app.route("/programs", methods=["POST"])
def create_program():

    data = request.json

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO programs
        (event_id,title,speaker,start_time,end_time)
        VALUES (%s,%s,%s,%s,%s)
        RETURNING id
    """,(
        data["event_id"],
        data["title"],
        data.get("speaker"),
        data.get("start_time"),
        data.get("end_time")
    ))

    program_id = cur.fetchone()[0]

    conn.commit()

    cur.close()
    conn.close()

    return jsonify({
        "message":"Program created",
        "id":program_id
    }),201


if __name__ == "__main__":
    app.run(host="0.0.0.0",port=5000)
