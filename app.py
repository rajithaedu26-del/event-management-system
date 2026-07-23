from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import clickhouse_connect
from datetime import datetime
import boto3
import json
import os

app = Flask(__name__)

CORS(app) 

app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    "DATABASE_URL",
    "postgresql://dbadmin:password123@eventdb.ce966q66a0se.us-east-1.rds.amazonaws.com:5432/eventdb"
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False 

db = SQLAlchemy(app)

# ---------- CLICKHOUSE ----------
clickhouse_client = clickhouse_connect.get_client(
    host="100.30.198.164",
    port=8123,
    username="admin",
    password="admin123"
)

clickhouse_client.command("""
CREATE TABLE IF NOT EXISTS analytics (
    timestamp DateTime,
    event_type String,
    page String,
    element String,
    duration Int32,
    screen String,
    referrer String
)
ENGINE = MergeTree
ORDER BY timestamp
""")

print("✅ ClickHouse table ready!")

# ---------- DATABASE TABLES ----------
class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200))
    venue = db.Column(db.String(200))
    datetime = db.Column(db.DateTime)
    price = db.Column(db.Float)
    capacity = db.Column(db.Integer)
    seats_available = db.Column(db.Integer)

class Program(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.String(50))
    track = db.Column(db.String(100))
    session = db.Column(db.String(200))
    speaker = db.Column(db.String(100))
    time = db.Column(db.String(50))

class Registration(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer)
    name = db.Column(db.String(200))
    email = db.Column(db.String(200))
    ticket_count = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# Create tables
with app.app_context():
    db.create_all()
    print("✅ Database tables created!")

# ---------- EVENT SERVICE ----------
@app.route('/events', methods=['GET'])
def get_events():
    events = Event.query.all()
    return jsonify([{
        'id': e.id,
        'title': e.title,
        'venue': e.venue,
        'datetime': e.datetime.isoformat() if e.datetime else None,
        'price': e.price,
        'capacity': e.capacity,
        'seats_available': e.seats_available
    } for e in events])

@app.route('/events', methods=['POST'])
def create_event():
    data = request.json
    event = Event(
        title=data['title'],
        venue=data['venue'],
        datetime=datetime.fromisoformat(data['datetime'].replace('Z', '+00:00')),
        price=data['price'],
        capacity=data['capacity'],
        seats_available=data['capacity']
    )
    db.session.add(event)
    db.session.commit()
    return jsonify({'id': event.id, 'status': 'created'})

@app.route('/events/<int:event_id>', methods=['PUT'])
def update_event(event_id):
    event = Event.query.get(event_id)

    if not event:
        return jsonify({'error': 'Event not found'}), 404

    data = request.json

    if 'seats_available' in data:
        event.seats_available = data['seats_available']
        db.session.commit()

        print(f"DEBUG: seats_available = {event.seats_available}", flush=True)

        # Trigger notification when seats are below 10
        if event.seats_available < 10:
            print("DEBUG: Entered notification block", flush=True)

            try:
                print("DEBUG: Creating S3 client", flush=True)

                s3 = boto3.client(
                    "s3",
                    region_name="us-east-1"
                )

                notification = {
                    "event_id": event.id,
                    "title": event.title,
                    "seats_available": event.seats_available,
                    "timestamp": datetime.utcnow().isoformat()
                }

                print("DEBUG: Uploading notification to S3...", flush=True)

                response = s3.put_object(
                    Bucket="event-notifications-476140239238",
                    Key=f"notifications/event_{event.id}_{int(datetime.utcnow().timestamp())}.json",
                    Body=json.dumps(notification),
                    ContentType="application/json"
                )

                print(f"✅ Notification sent successfully!", flush=True)
                print(response, flush=True)

            except Exception as e:
                import traceback
                print("❌ S3 ERROR OCCURRED", flush=True)
                traceback.print_exc()
                print(str(e), flush=True)

    return jsonify({
        "status": "updated",
        "seats_available": event.seats_available
    })

# ---------- PROGRAM SERVICE ----------
@app.route('/programs', methods=['GET'])
def get_programs():
    programs = Program.query.all()
    return jsonify([{
        'id': p.id,
        'day': p.day,
        'track': p.track,
        'session': p.session,
        'speaker': p.speaker,
        'time': p.time
    } for p in programs])

@app.route('/programs', methods=['POST'])
def add_program():
    data = request.json
    program = Program(
        day=data['day'],
        track=data['track'],
        session=data['session'],
        speaker=data['speaker'],
        time=data['time']
    )
    db.session.add(program)
    db.session.commit()
    return jsonify({'id': program.id, 'status': 'created'})

# ---------- REGISTRATION SERVICE ----------
@app.route('/register', methods=['POST'])
def register():
    data = request.json
    registration = Registration(
        event_id=data['event_id'],
        name=data['name'],
        email=data['email'],
        ticket_count=data['ticket_count']
    )
    db.session.add(registration)
    db.session.commit()
    
    event = Event.query.get(data['event_id'])
    if event:
        event.seats_available -= data['ticket_count']
        db.session.commit()
    
    return jsonify({'registration_id': registration.id, 'status': 'registered'})

@app.route('/registrations', methods=['GET'])
def get_registrations():
    registrations = Registration.query.all()
    return jsonify([{
        'id': r.id,
        'event_id': r.event_id,
        'name': r.name,
        'email': r.email,
        'ticket_count': r.ticket_count,
        'timestamp': r.timestamp.isoformat() if r.timestamp else None
    } for r in registrations])

# ---------- ANALYTICS ----------
@app.route('/analytics', methods=['POST'])
def analytics():
    try:
        data = request.json or {}

        event_type = data.get("type", "unknown")
        payload = data.get("data", {})

        page = payload.get("page", "")
        element = payload.get("text", "")
        duration = int(payload.get("duration", 0))
        screen = data.get("screenSize", "")
        referrer = data.get("referrer", "")

        clickhouse_client.insert(
            "analytics",
            [[
                datetime.utcnow(),
                event_type,
                page,
                element,
                duration,
                screen,
                referrer
            ]],
            column_names=[
                "timestamp",
                "event_type",
                "page",
                "element",
                "duration",
                "screen",
                "referrer"
            ]
        )

        print(f"📊 Analytics saved: {event_type}")

        return jsonify({
            "status": "saved"
        })

    except Exception as e:
        print(e)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

# ---------- HEALTH CHECK ----------
@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'service': 'event-service'})

@app.route('/')
def home():
    return jsonify({
        'service': 'Event Management API',
        'endpoints': [
            '/events (GET, POST)',
            '/events/<id> (PUT)',
            '/programs (GET, POST)',
            '/register (POST)',
            '/registrations (GET)',
            '/analytics (POST)',
            '/health (GET)'
        ]
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
