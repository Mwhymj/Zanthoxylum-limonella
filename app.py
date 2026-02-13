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
    conn = sqlite3.connect(os.path.join(BASE_DIR, 'makhaen.db'), timeout=20, check_same_thread=False)
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
    # 2. ตารางผู้ใช้งาน
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'user'
        )
    ''')
    # 3. ตารางผู้เข้าชมออนไลน์
    conn.execute('''
        CREATE TABLE IF NOT EXISTS visitors (
            session_id TEXT PRIMARY KEY,
            last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # ตรวจสอบ Column role
    try:
        conn.execute("SELECT role FROM users LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
    
    # บังคับสร้าง Admin และ User เริ่มต้น
    conn.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)", ('admin', '9999', 'admin'))
    conn.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)", ('user01', '8888', 'user'))
    
    conn.commit()
    conn.close()

init_db()

def update_visitor():
    if 'visitor_id' not in session:
        session['visitor_id'] = str(uuid.uuid4())
    conn = get_db_connection()
    try:
        conn.execute('INSERT OR REPLACE INTO visitors (session_id, last_seen) VALUES (?, CURRENT_TIMESTAMP)', (session['visitor_id'],))
        conn.execute("DELETE FROM visitors WHERE last_seen < datetime('now', '-5 minutes')")
        conn.commit()
    except: pass
    finally: conn.close()

# --- Routes หลัก ---

@app.route('/')
def index():
    update_visitor()
    conn = get_db_connection()
    try:
        online_now = conn.execute('SELECT COUNT(*) FROM visitors').fetchone()[0]
        total_data = conn.execute('SELECT COUNT(id) FROM surveys').fetchone()[0]
        total_users = conn.execute('SELECT COUNT(id) FROM users').fetchone()[0]
    finally: conn.close()
    return render_template('index.html', 
                           total_images=total_data, 
                           total_markers=total_data, 
                           total_users=total_users, 
                           online_users=max(1, online_now))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = False
    if request.method == 'POST':
        user, pwd = request.form.get('username'), request.form.get('password')
        conn = get_db_connection()
        user_data = conn.execute('SELECT * FROM users WHERE username = ? AND password = ?', (user, pwd)).fetchone()
        conn.close()
        if user_data:
            session.permanent = True
            session['username'] = user_data['username']
            session['role'] = user_data['role']
            return redirect(url_for('dashboard'))
        error = True
    return render_template('login.html', error=error)

@app.route('/dashboard')
def dashboard():
    is_guest = request.args.get('view_only') == 'true'
    if 'username' not in session and not is_guest:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    data = conn.execute('SELECT * FROM surveys ORDER BY timestamp DESC').fetchall()
    conn.close()
    return render_template('dashboard.html', 
                           role=session.get('role', 'GUEST'), 
                           user=session.get('username', 'ผู้เยี่ยมชม'), 
                           data=data, 
                           is_guest=is_guest)

@app.route('/archive')
def archive():
    """หน้าคลังข้อมูลทั้งหมดสำหรับ User และ Admin"""
    conn = get_db_connection()
    data = conn.execute('SELECT * FROM surveys ORDER BY timestamp DESC').fetchall()
    conn.close()
    return render_template('archive.html', data=data)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# --- Admin Routes ---

@app.route('/admin/reports')
def admin_reports():
    """หน้ารายงานปัญหาหรือตรวจสอบข้อมูลสำรวจทั้งหมดสำหรับ Admin"""
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    conn = get_db_connection()
    reports = conn.execute('SELECT * FROM surveys ORDER BY timestamp DESC').fetchall()
    conn.close()
    return render_template('admin_reports.html', reports=reports)

@app.route('/admin/users')
def admin_users():
    """หน้าจัดการบัญชีผู้ใช้สำหรับ Admin"""
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    conn = get_db_connection()
    users = conn.execute('SELECT id, username, role FROM users').fetchall()
    conn.close()
    return render_template('admin_users.html', users=users)

# --- API ---

@app.route('/api/upload', methods=['POST'])
def upload():
    """API สำหรับรับข้อมูลจากบอร์ด Raspberry Pi (ไม่ต้อง Login)"""
    try:
        img = request.files.get('image')
        lat = request.form.get('lat')
        lng = request.form.get('lng')
        surveyor = session.get('username', 'Hardware_Box')
        
        if not img or not lat or not lng:
            return jsonify({"status": "error", "message": "Missing Data"}), 400

        file_ext = os.path.splitext(img.filename)[1]
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}{file_ext}"
        img.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        conn = get_db_connection()
        conn.execute('''
            INSERT INTO surveys (img_name, lat, lng, accuracy, surveyor, prediction, confidence) 
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (filename, lat, lng, 
              request.form.get('accuracy', 0), 
              surveyor, 
              request.form.get('prediction', 'มะแขว่น'), 
              request.form.get('confidence', 0.0)))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Data Recorded"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/delete/<int:id>', methods=['POST'])
def delete_data(id):
    if 'username' not in session: return jsonify({"status": "error", "message": "Unauthorized"}), 403
    conn = get_db_connection()
    row = conn.execute('SELECT surveyor FROM surveys WHERE id = ?', (id,)).fetchone()
    if row and (session.get('role') == 'admin' or row['surveyor'] == session.get('username')):
        conn.execute('DELETE FROM surveys WHERE id = ?', (id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"}), 200
    conn.close()
    return jsonify({"status": "error", "message": "No permission"}), 403

if __name__ == '__main__':
    # สำหรับ Render ต้องใช้ host='0.0.0.0'
    app.run(debug=True, host='0.0.0.0', port=5000)
