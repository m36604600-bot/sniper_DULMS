import os
import json
import time
import random
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

# ==========================================
# 1. جلب البيانات من GitHub Secrets للأمان
# ==========================================
STUDENT_ID = os.environ.get("STUDENT_ID")
STUDENT_PASS = os.environ.get("STUDENT_PASS")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

if not all([STUDENT_ID, STUDENT_PASS, BOT_TOKEN, CHAT_ID]):
    raise ValueError("❌ البيانات مفقودة! تأكد من إعداد GitHub Secrets بشكل صحيح.")

MEMORY_FILE = "schedule_memory.json"

# ==========================================
# 2. إدارة الذاكرة لمنع تكرار الرسائل
# ==========================================
def load_memory():
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_memory(data):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# ==========================================
# 3. إرسال التنبيه لتليجرام (يفعل المنبه بهاتفك)
# ==========================================
def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
        print("✅ تم إرسال التنبيه لتليجرام بنجاح!")
    except Exception as e:
        print(f"❌ خطأ في إرسال رسالة التليجرام: {e}")

# ==========================================
# 4. تسجيل الدخول وسحب الجلسة الاحترافية
# ==========================================
def get_dulms_session():
    print("⏳ جاري فتح المتصفح وتسجيل الدخول لسحب الجلسة (Cookies)...")
    
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    # جيت هاب آكشنز يحتوي على كروم مثبتاً مسبقاً
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    try:
        driver.get("https://dulms.deltauniv.edu.eg/Login.aspx")
        
        driver.find_element(By.ID, "txtname").send_keys(STUDENT_ID)
        driver.find_element(By.ID, "txtPass").send_keys(STUDENT_PASS + Keys.RETURN)

        time.sleep(7) 
        
        selenium_cookies = driver.get_cookies()
        if not selenium_cookies:
            raise Exception("لم يتم العثور على Cookies، تأكد من صحة البيانات.")
            
        print("✅ تم سحب الجلسة بنجاح!")

    finally:
        driver.quit() 

    session = requests.Session()
    # تحديث الهيدرز بناءً على التجربة الناجحة
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Referer': 'https://dulms.deltauniv.edu.eg/Registered/CoursesRegisteration'
    })
    
    for cookie in selenium_cookies:
        session.cookies.set(cookie['name'], cookie['value'])
        
    return session

# ==========================================
# 5. منطق المراقبة واصطياد المقاعد
# ==========================================
def monitor_schedule(session):
    print(f"🔄 جاري الفحص السريع عبر APIs... | {time.strftime('%H:%M:%S')}")
    
    alerted_groups = load_memory()
    current_open_groups = []
    alerts = []
    
    courses_url = "https://dulms.deltauniv.edu.eg/Registered/GetStudentResiterationCourses"
    # البارامترات الكاملة لضمان جلب كل المواد
    params = {
        "GradeStatusIds": "0,2,3,4,5,", 
        "GroupsIds": "-1", 
        "IsVirtualRegisteration": "false"
    }
    
    try:
        courses_resp = session.get(courses_url, params=params, timeout=15)
        
        if courses_resp.status_code != 200 or '-1' in courses_resp.text:
            print("⚠️ الجلسة انتهت. سيتم إعادة تسجيل الدخول...")
            return False 

        courses_data = courses_resp.json()
        
        if not courses_data:
            print("📭 لم يتم جلب أي مواد. سيتم المحاولة مجدداً...")
            return True

        for course in courses_data:
            course_id = course['CourseId']
            course_name = f"{course['Code']} - {course['Name']}"
            
            schedule_url = "https://dulms.deltauniv.edu.eg/Registered/GetCourseSchedual"
            sched_resp = session.get(schedule_url, params={"CourseId": course_id}, timeout=15)
            
            if sched_resp.status_code == 200:
                schedule_data = sched_resp.json()
                
                for item in schedule_data:
                    # الشرط الفعلي: المادة غير مغلقة والأماكن المتاحة أكبر من صفر
                    if not item.get('IsBlocked', True): 
                        total_seats = int(item.get('StudentsCount', 0))
                        registered = int(item.get('RegisteredCount', 0))
                        available_seats = total_seats - registered
                        group_name = item.get('GroupName')
                        
                        unique_id = f"{course_id}_{group_name}"
                        
                        if available_seats > 0: 
                            current_open_groups.append(unique_id)
                            
                            if unique_id not in alerted_groups:
                                alert_msg = (
                                    f"🚨 *عاجل: مكان متاح للتسجيل!*\n"
                                    f"📚 *المادة:* {course_name}\n"
                                    f"🏷 *المجموعة/السكشن:* {group_name}\n"
                                    f"🪑 *الأماكن المتاحة:* {available_seats} من {total_seats}\n"
                                    f"👨‍🏫 *الدكتور:* {item.get('Staff')}\n"
                                    f"⏱ *الميعاد:* {item.get('Time')} ({item.get('DayWeekName')})"
                                )
                                alerts.append(alert_msg)
                                alerted_groups.append(unique_id)

        alerted_groups = [g for g in alerted_groups if g in current_open_groups]
        save_memory(alerted_groups)

        if alerts:
            final_message = "\n\n".join(alerts)
            send_telegram_alert(final_message)
        else:
            print("📭 لم يتم العثور على أي سكاشن جديدة مفتوحة حالياً.")

        return True

    except Exception as e:
        print(f"❌ خطأ أثناء الفحص: {e}")
        return False

# ==========================================
# 6. دورة التشغيل (التي ستعمل على سيرفرات جيت هاب)
# ==========================================
if __name__ == "__main__":
# send_telegram_alert("🚀 *بدأ تشغيل بوت مراقبة الجدول على سيرفرات جيت هاب...*")    
    while True:
        active_session = get_dulms_session()
        
        while True:
            session_valid = monitor_schedule(active_session)
            
            if not session_valid:
                break
                
            time.sleep(random.randint(120, 180))
