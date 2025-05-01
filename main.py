from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import telebot
import psycopg2
import os
import threading
import time
import json

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# إعدادات قاعدة البيانات PostgreSQL
DB_CONFIG = {
    'host': 'nwht0.h.filess.io',
    'database': 'Defeut_dangerpond',
    'port': '5433',
    'user': 'Defeut_dangerpond',
    'password': 'ebaac42291fd6d7122d84da205214a97ab91f6e1'
}

# الحصول على اسم المخطط (schema) المناسب
SCHEMA_NAME = DB_CONFIG['user']  # استخدام اسم المستخدم كمخطط افتراضي

# تهيئة قاعدة البيانات
def init_db():
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    try:
        # ضبط search_path إلى مخطط المستخدم
        cursor.execute(f'SET search_path TO {SCHEMA_NAME}')
        
        # التحقق من وجود المخطط وإنشائه إذا لم يكن موجودًا
        cursor.execute(f"SELECT schema_name FROM information_schema.schemata WHERE schema_name = '{SCHEMA_NAME}'")
        if not cursor.fetchone():
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}")
            conn.commit()
        
        # إنشاء جدول البوتات إذا لم يكن موجوداً - بدون استخدام public.
        cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS bots (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            token TEXT NOT NULL,
            description TEXT,
            active INTEGER DEFAULT 0
        )
        ''')
        
        # إنشاء جدول الردود إذا لم يكن موجوداً - بدون استخدام public.
        cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS responses (
            id SERIAL PRIMARY KEY,
            bot_id INTEGER,
            trigger TEXT NOT NULL,
            response TEXT NOT NULL,
            FOREIGN KEY (bot_id) REFERENCES bots (id)
        )
        ''')
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error initializing database: {e}")
        raise
    finally:
        conn.close()

# متغيرات عالمية لتخزين البوتات النشطة
active_bots = {}

def start_bot(bot_id, token):
    if bot_id in active_bots:
        return False
    
    try:
        bot = telebot.TeleBot(token)
        
        # استرجاع الردود المخصصة من قاعدة البيانات
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(f'SET search_path TO {SCHEMA_NAME}')
        cursor.execute("SELECT trigger, response FROM responses WHERE bot_id = %s", (bot_id,))
        responses = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()
        
        @bot.message_handler(func=lambda message: True)
        def handle_messages(message):
            text = message.text
            for trigger, response in responses.items():
                if trigger.lower() in text.lower():
                    bot.reply_to(message, response)
                    return
            
            # رد افتراضي إذا لم يتم العثور على مطابقة
            bot.reply_to(message, "آسف، لا أستطيع فهم ما تريد. يرجى إعادة صياغة الرسالة.")
        
        # بدء البوت في خيط منفصل
        bot_thread = threading.Thread(target=bot.polling, kwargs={'none_stop': True})
        bot_thread.daemon = True
        bot_thread.start()
        
        active_bots[bot_id] = {
            'bot': bot,
            'thread': bot_thread,
            'responses': responses
        }
        
        # تحديث حالة البوت في قاعدة البيانات
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(f'SET search_path TO {SCHEMA_NAME}')
        cursor.execute("UPDATE bots SET active = 1 WHERE id = %s", (bot_id,))
        conn.commit()
        conn.close()
        
        return True
    except Exception as e:
        print(f"Error starting bot: {e}")
        return False

def stop_bot(bot_id):
    if bot_id not in active_bots:
        return False
    
    try:
        # توقف البوت عن العمل
        active_bots[bot_id]['bot'].stop_polling()
        del active_bots[bot_id]
        
        # تحديث حالة البوت في قاعدة البيانات
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(f'SET search_path TO {SCHEMA_NAME}')
        cursor.execute("UPDATE bots SET active = 0 WHERE id = %s", (bot_id,))
        conn.commit()
        conn.close()
        
        return True
    except Exception as e:
        print(f"Error stopping bot: {e}")
        return False

# الصفحة الرئيسية
@app.route('/')
def index():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(f'SET search_path TO {SCHEMA_NAME}')
        cursor.execute("SELECT id, name, token, description, active FROM bots")
        bots = cursor.fetchall()
        conn.close()
        
        return render_template('index.html', bots=bots)
    except Exception as e:
        flash(f'حدث خطأ: {str(e)}', 'danger')
        return render_template('index.html', bots=[])

# إضافة بوت جديد
@app.route('/add_bot', methods=['GET', 'POST'])
def add_bot():
    if request.method == 'POST':
        name = request.form['name']
        token = request.form['token']
        description = request.form['description']
        
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()
            cursor.execute(f'SET search_path TO {SCHEMA_NAME}')
            cursor.execute("INSERT INTO bots (name, token, description) VALUES (%s, %s, %s)",
                          (name, token, description))
            conn.commit()
            conn.close()
            
            flash('تم إضافة البوت بنجاح!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            flash(f'فشل في إضافة البوت: {str(e)}', 'danger')
    
    return render_template('add_bot.html')

# عرض تفاصيل البوت وإدارة الردود
@app.route('/bot/<int:bot_id>')
def view_bot(bot_id):
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(f'SET search_path TO {SCHEMA_NAME}')
        cursor.execute("SELECT id, name, token, description, active FROM bots WHERE id = %s", (bot_id,))
        bot = cursor.fetchone()
        
        cursor.execute("SELECT id, trigger, response FROM responses WHERE bot_id = %s", (bot_id,))
        responses = cursor.fetchall()
        conn.close()
        
        if bot is None:
            flash('البوت غير موجود!', 'danger')
            return redirect(url_for('index'))
        
        return render_template('view_bot.html', bot=bot, responses=responses)
    except Exception as e:
        flash(f'حدث خطأ: {str(e)}', 'danger')
        return redirect(url_for('index'))

# إضافة رد جديد لبوت
@app.route('/bot/<int:bot_id>/add_response', methods=['GET', 'POST'])
def add_response(bot_id):
    if request.method == 'POST':
        trigger = request.form['trigger']
        response = request.form['response']
        
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()
            cursor.execute(f'SET search_path TO {SCHEMA_NAME}')
            cursor.execute("INSERT INTO responses (bot_id, trigger, response) VALUES (%s, %s, %s)",
                          (bot_id, trigger, response))
            conn.commit()
            conn.close()
            
            # إذا كان البوت نشطًا، قم بتحديث قائمة الردود
            if bot_id in active_bots:
                active_bots[bot_id]['responses'][trigger] = response
            
            flash('تم إضافة الرد بنجاح!', 'success')
            return redirect(url_for('view_bot', bot_id=bot_id))
        except Exception as e:
            flash(f'فشل في إضافة الرد: {str(e)}', 'danger')
    
    return render_template('add_response.html', bot_id=bot_id)

# حذف رد
@app.route('/delete_response/<int:response_id>/<int:bot_id>')
def delete_response(response_id, bot_id):
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(f'SET search_path TO {SCHEMA_NAME}')
        
        # احصل على المشغل قبل الحذف للتحديث في البوت النشط
        cursor.execute("SELECT trigger FROM responses WHERE id = %s", (response_id,))
        result = cursor.fetchone()
        
        if result is None:
            flash('الرد غير موجود!', 'danger')
            return redirect(url_for('view_bot', bot_id=bot_id))
            
        trigger = result[0]
        
        cursor.execute("DELETE FROM responses WHERE id = %s", (response_id,))
        conn.commit()
        conn.close()
        
        # إذا كان البوت نشطًا، قم بإزالة الرد من قائمة الردود
        if bot_id in active_bots and trigger in active_bots[bot_id]['responses']:
            del active_bots[bot_id]['responses'][trigger]
        
        flash('تم حذف الرد بنجاح!', 'success')
        return redirect(url_for('view_bot', bot_id=bot_id))
    except Exception as e:
        flash(f'فشل في حذف الرد: {str(e)}', 'danger')
        return redirect(url_for('view_bot', bot_id=bot_id))

# تشغيل/إيقاف البوت
@app.route('/toggle_bot/<int:bot_id>')
def toggle_bot(bot_id):
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(f'SET search_path TO {SCHEMA_NAME}')
        cursor.execute("SELECT token, active FROM bots WHERE id = %s", (bot_id,))
        result = cursor.fetchone()
        
        if result is None:
            flash('البوت غير موجود!', 'danger')
            return redirect(url_for('index'))
        
        token, active = result
        
        if active == 1:
            # إيقاف البوت
            if stop_bot(bot_id):
                flash('تم إيقاف البوت بنجاح!', 'success')
            else:
                flash('فشل في إيقاف البوت!', 'danger')
        else:
            # تشغيل البوت
            if start_bot(bot_id, token):
                flash('تم تشغيل البوت بنجاح!', 'success')
            else:
                flash('فشل في تشغيل البوت!', 'danger')
        
        return redirect(url_for('view_bot', bot_id=bot_id))
    except Exception as e:
        flash(f'حدث خطأ: {str(e)}', 'danger')
        return redirect(url_for('index'))

# تعديل معلومات البوت
@app.route('/edit_bot/<int:bot_id>', methods=['GET', 'POST'])
def edit_bot(bot_id):
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(f'SET search_path TO {SCHEMA_NAME}')
        
        if request.method == 'POST':
            name = request.form['name']
            token = request.form['token']
            description = request.form['description']
            
            cursor.execute("UPDATE bots SET name = %s, token = %s, description = %s WHERE id = %s",
                          (name, token, description, bot_id))
            conn.commit()
            
            # إذا كان البوت نشطًا، يجب إعادة تشغيله
            cursor.execute("SELECT active FROM bots WHERE id = %s", (bot_id,))
            active = cursor.fetchone()[0]
            
            if active == 1:
                stop_bot(bot_id)
                start_bot(bot_id, token)
            
            flash('تم تحديث معلومات البوت بنجاح!', 'success')
            return redirect(url_for('view_bot', bot_id=bot_id))
        
        cursor.execute("SELECT id, name, token, description FROM bots WHERE id = %s", (bot_id,))
        bot = cursor.fetchone()
        conn.close()
        
        if bot is None:
            flash('البوت غير موجود!', 'danger')
            return redirect(url_for('index'))
        
        return render_template('edit_bot.html', bot=bot)
    except Exception as e:
        flash(f'حدث خطأ: {str(e)}', 'danger')
        return redirect(url_for('index'))

# حذف بوت
@app.route('/delete_bot/<int:bot_id>')
def delete_bot(bot_id):
    try:
        # إيقاف البوت إذا كان نشطًا
        if bot_id in active_bots:
            stop_bot(bot_id)
        
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(f'SET search_path TO {SCHEMA_NAME}')
        
        # حذف الردود المرتبطة بالبوت
        cursor.execute("DELETE FROM responses WHERE bot_id = %s", (bot_id,))
        
        # حذف البوت
        cursor.execute("DELETE FROM bots WHERE id = %s", (bot_id,))
        conn.commit()
        conn.close()
        
        flash('تم حذف البوت وجميع الردود المرتبطة به بنجاح!', 'success')
        return redirect(url_for('index'))
    except Exception as e:
        flash(f'فشل في حذف البوت: {str(e)}', 'danger')
        return redirect(url_for('index'))

if __name__ == '__main__':
    # تهيئة قاعدة البيانات
    try:
        init_db()
    except Exception as e:
        print(f"Error initializing database: {e}")
        exit(1)
    
    # عند بدء التشغيل، قم بتشغيل جميع البوتات النشطة
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(f'SET search_path TO {SCHEMA_NAME}')
        cursor.execute("SELECT id, token FROM bots WHERE active = 1")
        active_bot_records = cursor.fetchall()
        conn.close()
        
        for bot_id, token in active_bot_records:
            start_bot(bot_id, token)

        port = int(os.environ.get("PORT", 5000))
        app.run(host="0.0.0.0", port=port)   
    except Exception as e:
        print(f"Error starting application: {e}")
        exit(1)
