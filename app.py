from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
from datetime import datetime
import os
import uuid

app = Flask(__name__)
app.secret_key = 'makhaen_up_key'

# --- การตั้งค่าเส้นทางไฟล์ ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# --- การจัดการฐานข้อมูล ---
def get_db_connection():
    conn = sqlite3.connect(os.path.join(BASE_DIR, 'makhaen.db'), timeout=20)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    # 1. ตารางเก็บข้อมูลการสำรวจ
    conn.execute('''
        CREATE TABLE IF NOT EXISTS surveys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            img_name TEXT NOT NULL,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            accuracy REAL,
            surveyor TEXT,
            prediction TEXT,      
            confidence REAL,      
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'completed'
        )
    ''')
    # 2. ตาราง users
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'user'
        )
    ''')
    # 3. ตารางบันทึกคนออนไลน์
    conn.execute('''
        CREATE TABLE IF NOT EXISTS visitors (
            session_id TEXT PRIMARY KEY,
            last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # แก้ไขโครงสร้างตารางหากไม่มีคอลัมน์ role
    try:
        conn.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
    except sqlite3.OperationalError:
        pass 
    
    # จัดการ Admin: admin / 9999
    conn.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)", 
                 ('admin', '9999', 'admin'))
    conn.execute("UPDATE users SET password = ? WHERE username = ?", ('9999', 'admin'))

    # จัดการ User: user01 / 8888
    conn.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)", 
                 ('user01', '8888', 'user'))
    conn.execute("UPDATE users SET password = ? WHERE username = ?", ('8888', 'user01'))
    
    conn.commit()
    conn.close()

init_db()

# --- Routes หลัก ---

@app.route('/')
def index():
    if 'visitor_id' not in session:
        session['visitor_id'] = str(uuid.uuid4())
    
    conn = get_db_connection()
    try:
        conn.execute('INSERT OR REPLACE INTO visitors (session_id, last_seen) VALUES (?, CURRENT_TIMESTAMP)', 
                     (session['visitor_id'],))
        conn.execute("DELETE FROM visitors WHERE last_seen < datetime('now', '-5 minutes')")
        conn.commit()

        online_now = conn.execute('SELECT COUNT(*) FROM visitors').fetchone()[0]
        stats = conn.execute('SELECT COUNT(id) FROM surveys').fetchone()
        total_data = stats[0] if stats else 0
        user_stats = conn.execute('SELECT COUNT(id) FROM users').fetchone()
        total_users = user_stats[0] if user_stats else 0
    finally:
        conn.close()
    
    return render_template('index.html', total_images=total_data, total_markers=total_data, 
                           total_users=total_users, online_users=online_now)

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = False
    if request.method == 'POST':
        user = request.form.get('username')
        pwd = request.form.get('password')
        conn = get_db_connection()
        user_data = conn.execute('SELECT * FROM users WHERE username = ? AND password = ?', 
                                 (user, pwd)).fetchone()
        conn.close()

        if user_data:
            session['user'] = user_data['username']
            session['role'] = user_data['role']
            return redirect(url_for('dashboard'))
        else:
            error = True
    return render_template('login.html', error=error)

@app.route('/dashboard')
def dashboard():
    is_guest = request.args.get('view_only') == 'true'
    if 'user' not in session and not is_guest:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    try:
        data = conn.execute('SELECT * FROM surveys ORDER BY timestamp DESC').fetchall()
        role = session.get('role', 'guest')
        user_name = session.get('user', 'ผู้เยี่ยมชม')
    finally:
        conn.close()
    
    return render_template('dashboard.html', role=role, user=user_name, data=data, is_guest=is_guest)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# --- Admin Routes ---

@app.route('/admin/reports')
def admin_reports():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    conn = get_db_connection()
    reports = conn.execute('SELECT * FROM surveys ORDER BY timestamp DESC').fetchall()
    conn.close()
    return render_template('admin_reports.html', reports=reports)

@app.route('/admin/users')
def admin_users():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    conn = get_db_connection()
    users = conn.execute('SELECT id, username, role FROM users').fetchall()
    conn.close()
    return render_template('admin_users.html', users=users)

# --- API ---

@app.route('/api/upload', methods=['POST'])
def upload():
    try:
        img = request.files['image']
        lat, lng = request.form.get('lat'), request.form.get('lng')
        surveyor = session.get('user', 'Hardware_Box')
        
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{img.filename}"
        img.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        conn = get_db_connection()
        conn.execute('''
            INSERT INTO surveys (img_name, lat, lng, accuracy, surveyor, prediction, confidence) 
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (filename, lat, lng, request.form.get('accuracy', 0), surveyor, 
              request.form.get('prediction', 'Unknown'), request.form.get('confidence', 0.0)))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/delete/<int:id>', methods=['POST'])
def delete_data(id):
    if 'user' not in session:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
    
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT surveyor FROM surveys WHERE id = ?', (id,)).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "Data not found"}), 404
            
        if session.get('role') == 'admin' or row['surveyor'] == session.get('user'):
            conn.execute('DELETE FROM surveys WHERE id = ?', (id,))
            conn.commit()
            return jsonify({"status": "success"}), 200
        else:
            return jsonify({"status": "error", "message": "No permission"}), 403
    finally:
        conn.close()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
