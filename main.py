import sounddevice as sd
import numpy as np
import sqlite3
import time
import os
import geocoder
from scipy.io.wavfile import write
from scipy.signal import butter, lfilter
from flask import Flask, jsonify, render_template, request, g
from threading import Thread
from werkzeug.utils import secure_filename

# Create or connect to SQLite database
db_path = os.path.join(os.getcwd(), "noise_data.db")

# Initialize Flask app
app = Flask(__name__)

UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'audio_clips')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure the database and table are created at startup
def initialize_database():
    """Create the noise_data table if it doesn't exist."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS noise_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        location TEXT NOT NULL UNIQUE,
        decibel REAL NOT NULL
    )
    ''')
    conn.commit()
    conn.close()

# Call the function to initialize the database
initialize_database()

def get_decibel(audio_data):
    """Calculate decibel level from audio data."""
    rms = np.sqrt(np.mean(np.square(audio_data)))
    decibel = 20 * np.log10(rms) if rms > 0 else 0
    return decibel

def butter_bandstop(lowcut, highcut, fs, order=5):
    """Create a bandstop filter to isolate background noise."""
    nyquist = 0.5 * fs
    low = lowcut / nyquist
    high = highcut / nyquist
    b, a = butter(order, [low, high], btype='bandstop')
    return b, a

def apply_bandstop_filter(data, lowcut, highcut, fs, order=5):
    """Apply the bandstop filter to the audio data."""
    b, a = butter_bandstop(lowcut, highcut, fs, order=order)
    y = lfilter(b, a, data)
    return y

def isolate_background_noise():
    """Record audio and isolate background noise."""
    print("Recording audio to isolate background noise...")
    audio_data = sd.rec(int(44100 * 5), samplerate=44100, channels=1, dtype='float64')  # Record 5 seconds
    sd.wait()
    
    # Apply bandstop filter to remove foreground noise
    filtered_data = apply_bandstop_filter(audio_data.flatten(), lowcut=300, highcut=3000, fs=44100, order=6)
    
    # Save the isolated background noise to a file
    write("background_noise.wav", 44100, np.int16(filtered_data * 32767))
    print("Background noise isolated and saved to 'background_noise.wav'.")

def get_current_location():
    """Get the current location (latitude and longitude) using geolocation."""
    g = geocoder.ip('me')  # Use IP-based geolocation
    if g.ok:
        return g.latlng  # Returns [latitude, longitude]
    else:
        print("Unable to determine location.")
        return [None, None]

def record_noise(location="Unknown"):
    """Record background noise levels and store in SQLite database."""
    coords = get_current_location()
    if coords[0] is not None and coords[1] is not None:
        location = f"{coords[0]},{coords[1]}"  # Store only valid coordinates
    else:
        location = "Unknown"  # Fallback if coordinates are invalid

    while True:
        # Record audio for 1 second
        audio_data = sd.rec(int(44100 * 1), samplerate=44100, channels=1, dtype='float64')
        sd.wait()  # Wait until recording is finished
        
        # Apply bandstop filter to isolate background noise
        background_noise = apply_bandstop_filter(audio_data.flatten(), lowcut=300, highcut=3000, fs=44100, order=6)
        
        # Calculate decibel level of background noise
        decibel = get_decibel(background_noise)
        
        # Insert or replace data into database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('''
        INSERT OR REPLACE INTO noise_data (id, timestamp, location, decibel)
        VALUES (
            (SELECT id FROM noise_data WHERE location = ?),
            ?, ?, ?
        )
        ''', (location, time.strftime("%Y-%m-%d %H:%M:%S"), location, decibel))
        conn.commit()
        conn.close()
        
        print(f"Recorded: {time.strftime('%Y-%m-%d %H:%M:%S')} | Location: {location} | Background Noise Decibel: {decibel:.2f}")
        
        # Wait for 5 seconds before next recording
        time.sleep(1)

def get_db():
    """Get a database connection for the current thread."""
    if 'db' not in g:
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row  # Enable dictionary-like access
    return g.db

@app.teardown_appcontext
def close_db(exception):
    """Close the database connection at the end of the request."""
    db = g.pop('db', None)
    if db is not None:
        db.close()

@app.route('/')
def index():
    """Render the map UI."""
    return render_template('index.html')

@app.route('/zen-zone')
def zen_zone():
    """Render the Zen Zone page."""
    return render_template('zen_zone.html')

@app.route('/report-zen')
def report_zen():
    """Render the Report Zen Zone page."""
    return render_template('report_zen.html')

@app.route('/explore')
def explore():
    return render_template('explore.html')

@app.route('/discover')
def discover():
    return render_template('discover.html')

@app.route('/redeem')
def redeem():
    return render_template('redeem.html')

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/search')
def search():
    return render_template('search.html')


@app.route('/api/noise-data')
def noise_data():
    """Provide noise data as JSON for the frontend."""
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT timestamp, location, decibel FROM noise_data')
    rows = cursor.fetchall()
    data = [
        {'timestamp': row['timestamp'], 'location': row['location'], 'decibel': row['decibel']}
        for row in rows
    ]
    print("Noise Data Sent to Client:", data)  # Debugging log
    return jsonify(data)

@app.route('/api/record-zen-zone', methods=['POST'])
def record_zen_zone():
    """Record 30 seconds of audio and check if it qualifies as a Zen Zone."""
    location = request.json.get('location')
    if not location:
        return jsonify({'error': 'Location is required'}), 400

    # Record 30 seconds of audio
    audio_data = sd.rec(int(44100 * 30), samplerate=44100, channels=1, dtype='float64')
    sd.wait()

    # Calculate decibel level
    decibel = get_decibel(audio_data.flatten())

    if decibel < -45:
        # Save the Zen Zone to the database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO noise_data (timestamp, location, decibel)
        VALUES (?, ?, ?)
        ''', (time.strftime("%Y-%m-%d %H:%M:%S"), location, decibel))
        conn.commit()
        conn.close()

        return jsonify({'message': 'Zen Zone recorded', 'decibel': decibel}), 200
    else:
        return jsonify({'message': 'Area does not qualify as a Zen Zone', 'decibel': decibel}), 200

@app.route('/api/upload-noise-data', methods=['POST'])
def upload_noise_data():
    """Handle uploaded noise data and save to the database."""
    decibel = request.form.get('decibel')
    location = request.form.get('location')
    audio = request.files.get('audio')

    if not decibel or not location or not audio:
        return jsonify({'error': 'Missing required data'}), 400

    # Save the audio file
    filename = secure_filename(f"{time.strftime('%Y%m%d%H%M%S')}_noise.wav")
    audio_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    audio.save(audio_path)

    # Insert data into the database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO noise_data (timestamp, location, decibel)
    VALUES (?, ?, ?)
    ''', (time.strftime("%Y-%m-%d %H:%M:%S"), location, float(decibel)))
    conn.commit()
    conn.close()

    return jsonify({'message': 'Noise data uploaded successfully'}), 200

if __name__ == "__main__":
    try:
        print("Starting noise level monitoring...")
        # Start Flask app in a separate thread
        flask_thread = Thread(target=lambda: app.run(debug=True, use_reloader=False))
        flask_thread.start()

        record_noise(location="Home")  # Replace "Home" with your desired location
    except KeyboardInterrupt:
        print("Stopping noise level monitoring...")
        isolate_background_noise()  # Isolate background noise on exit
    finally:
        conn.close()