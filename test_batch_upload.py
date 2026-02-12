import requests
import os
import time

# ตั้งค่าที่อยู่ API และโฟลเดอร์
url = 'http://127.0.0.1:5000/api/upload'
folder_path = 'dataset'

# ตรวจสอบว่ามีโฟลเดอร์ dataset จริงไหม
if not os.path.exists(folder_path):
    print(f"ไม่พบโฟลเดอร์ {folder_path}!")
    exit()

# วนลูปส่งทุกไฟล์ที่อยู่ในโฟลเดอร์
for filename in os.listdir(folder_path):
    # เลือกเฉพาะไฟล์รูปภาพ
    if filename.endswith(('.png', '.jpg', '.jpeg')):
        file_path = os.path.join(folder_path, filename)
        
        # จำลองข้อมูล (คุณสามารถเปลี่ยนพิกัดให้ต่างกันได้ในแต่ละรูป)
        data = {
            'lat': 19.0308,  # พิกัดหน้า ม.พะเยา
            'lng': 99.9263,
            'accuracy': 99.0,
            'user': 'Folder_Uploader'
        }

        with open(file_path, 'rb') as f:
            files = {'image': f}
            try:
                response = requests.post(url, data=data, files=files)
                if response.status_code == 200:
                    print(f"✅ อัปโหลดสำเร็จ: {filename}")
                else:
                    print(f"❌ อัปโหลดล้มเหลว: {filename} -> {response.text}")
            except Exception as e:
                print(f"⚠️ เกิดข้อผิดพลาด: {e}")
        
        # พักสักนิดเพื่อไม่ให้เครื่องค้าง
        time.sleep(0.5)

print("\n--- เสร็จสิ้นการอัปโหลดทั้งหมด ---")