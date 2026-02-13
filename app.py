from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
from datetime import datetime
import os
import uuid

app = Flask(__name__)
app.secret_key = 'makhaen_up_key'

# --- การตั้งค่าเส้นทางไฟล์ ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# ปรับโฟลเดอร์ให้รองรับทั้ง images และ uploads
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# --- การจัดการฐานข้อมูล ---
def get_db_connection():
    # เพิ่ม check_same_thread=False เพื่อความเสถียรบน Server
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
    
    # ตรวจสอบและเพิ่ม Column role หากยังไม่มี
    try:
        cursor = conn.execute("SELECT role FROM users LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
    
    # บังคับสร้าง Admin และ User เริ่มต้น
    conn.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)", 
                 ('admin', '9999', 'admin'))
    conn.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)", 
                 ('user01', '8888', 'user'))
    
    conn.commit()
    conn.close()

init_db()

# --- Middleware (สำหรับจัดการคนออนไลน์) ---
def update_visitor():
    if 'visitor_id' not in session:
        session['visitor_id'] = str(uuid.uuid4())
    
    conn = get_db_connection()
    try:
        conn.execute('INSERT OR REPLACE INTO visitors (session_id, last_seen) VALUES (?, CURRENT_TIMESTAMP)', 
                     (session['visitor_id'],))
        # ลบคนที่ไม่ได้ Active เกิน 5 นาที
        conn.execute("DELETE FROM visitors WHERE last_seen < datetime('now', '-5 minutes')")
        conn.commit()
    except:
        pass
    finally:
        conn.close()

# --- Routes หลัก ---

@app.route('/')
def index():
    update_visitor() # เรียกใช้งานระบบนับคนออนไลน์
    
    conn = get_db_connection()
    try:
        online_now = conn.execute('SELECT COUNT(*) FROM visitors').fetchone()[0]
        stats = conn.execute('SELECT COUNT(id) FROM surveys').fetchone()
        total_data = stats[0] if stats else 0
        user_stats = conn.execute('SELECT COUNT(id) FROM users').fetchone()
        total_users = user_stats[0] if user_stats else 0
    finally:
        conn.close()
    
    return render_template('index.html', 
                           total_images=total_data, 
                           total_markers=total_data, 
                           total_users=total_users, 
                           online_users=max(1, online_now)) # อย่างน้อยต้องโชว์ 1

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
            session.permanent = True # ทำให้ session อยู่ได้นานขึ้น
            session['user_id'] = user_data['id']
            session['username'] = user_data['username']
            session['role'] = user_data['role']
            # สำคัญ: ต้องใส่ค่าที่ Dashboard เช็ค
            session['user'] = user_data['username'] 
            
            return redirect(url_for('dashboard'))
        else:
            error = True
    return render_template('login.html', error=error)

@app.route('/dashboard')
def dashboard():
    is_guest = request.args.get('view_only') == 'true'
    
    # ตรวจสอบสิทธิ์การเข้าถึง (ถ้าไม่ล็อกอินและไม่ใช่ Guest ให้ไปหน้า Login)
    if 'username' not in session and not is_guest:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    try:
        # ดึงข้อมูลพิกัดทั้งหมด
        data = conn.execute('SELECT * FROM surveys ORDER BY timestamp DESC').fetchall()
        
        # เตรียมตัวแปรให้ตรงกับใน Template
        role = session.get('role', 'GUEST')
        user_name = session.get('username', 'ผู้เยี่ยมชม')
        
        # พิกัดเป้าหมาย (กรณีส่งพิกัดมาทาง URL เช่น /dashboard?lat=...&lng=...)
        target_lat = request.args.get('lat')
        target_lng = request.args.get('lng')
        
    finally:
        conn.close()
    
    return render_template('dashboard.html', 
                           role=role, 
                           user=user_name, 
                           data=data, 
                           is_guest=is_guest,
                           target_lat=target_lat,
                           target_lng=target_lng)

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
    if 'username' not in session:
        return jsonify({"status": "error", "message": "กรุณาเข้าสู่ระบบ"}), 403
        
    try:
        img = request.files.get('image')
        lat = request.form.get('lat')
        lng = request.form.get('lng')
        surveyor = session.get('username', 'Unknown')
        
        if not img or not lat or not lng:
            return jsonify({"status": "error", "message": "ข้อมูลไม่ครบถ้วน"}), 400

        # ตั้งชื่อไฟล์แบบป้องกันการซ้ำ
        file_ext = os.path.splitext(img.filename)[1]
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}{file_ext}"
        img.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        conn = get_db_connection()
        conn.execute('''
            INSERT INTO surveys (img_name, lat, lng, accuracy, surveyor, prediction, confidence) 
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (filename, lat, lng, request.form.get('accuracy', 0), surveyor, 
              request.form.get('prediction', 'มะแขว่น'), request.form.get('confidence', 95.0)))
        conn.commit()
        conn.close()
        
        return jsonify({"status": "success", "filename": filename}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/delete/<int:id>', methods=['POST'])
def delete_data(id):
    if 'username' not in session:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
    
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT surveyor FROM surveys WHERE id = ?', (id,)).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "ไม่พบข้อมูล"}), 404
            
        # ลบได้เฉพาะเจ้าของข้อมูลหรือ Admin
        if session.get('role') == 'admin' or row['surveyor'] == session.get('username'):
            conn.execute('DELETE FROM surveys WHERE id = ?', (id,))
            conn.commit()
            return jsonify({"status": "success"}), 200
        else:
            return jsonify({"status": "error", "message": "ไม่มีสิทธิ์ลบข้อมูลนี้"}), 403
    finally:
        conn.close()

if __name__ == '__main__':
    # รันบน Local ใช้ Port 5000
    app.run(debug=True, host='0.0.0.0', port=5000)
