# Модуль: legal_app/app.py
# Назначение: Серверная часть системы учёта дел юридического отдела
# Функционал: Аутентификация, CRUD всех сущностей, управление справочниками, файловое хранилище
# Безопасность: Хеширование bcrypt, параметризованные SQL, проверка сессий, валидация типов файлов
# Зависимости: Flask, PyMySQL, os, datetime, hashlib, werkzeug.security

from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
import pymysql
import os
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.urandom(32)  # Криптографически стойкий секретный ключ
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'jpg', 'png', 'rtf'}

# Модуль: Подключение к БД
# Назначение: Возвращает соединение с автоматическим DictCursor
# Безопасность: Использует utf8mb4, закрывает соединение после запроса
def get_db():
    return pymysql.connect(
        host='127.0.0.1',
        user='legal_user',
        password='1234',
        database='legal_department_db',
        cursorclass=pymysql.cursors.DictCursor,
        charset='utf8mb4',
        autocommit=False
    )

# Вспомогательная: Проверка расширения файла
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Маршрут: Авторизация
# Назначение: Проверка логина/пароля, создание сессии, редирект на дашборд
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        login_val = request.form.get('login', '').strip()
        password_val = request.form.get('password', '')
        if not login_val or not password_val:
            flash('Заполните все поля', 'error')
            return render_template('login.html')
        db = get_db()
        try:
            with db.cursor() as cur:
                cur.execute("SELECT user_id, login, password_hash, role_id, full_name, is_active FROM users WHERE login = %s", (login_val,))
                user = cur.fetchone()
                if user and user['is_active'] and check_password_hash(user['password_hash'], password_val):
                    session.update(user_id=user['user_id'], login=user['login'], role_id=user['role_id'], full_name=user['full_name'])
                    flash(f'Добро пожаловать, {user["full_name"]}!', 'success')
                    return redirect(url_for('dashboard'))
                flash('Неверный логин или пароль, либо аккаунт деактивирован', 'error')
        finally:
            db.close()
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Декоратор: Защита маршрутов
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Требуется авторизация', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# Маршрут: Главная панель
# Назначение: Агрегация статистики по делам и клиентам
@app.route('/')
@login_required
def dashboard():
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("""SELECT cs.status_name, COUNT(c.case_id) as cnt 
                           FROM case_statuses cs LEFT JOIN cases c ON cs.status_id = c.status_id 
                           GROUP BY cs.status_id, cs.status_name""")
            stats = cur.fetchall()
            cur.execute("SELECT COUNT(*) as total FROM clients WHERE MONTH(created_at) = MONTH(CURDATE())")
            new_clients = cur.fetchone()['total']
    finally:
        db.close()
    return render_template('dashboard.html', stats=stats, new_clients=new_clients, role=session['role_id'])

# === КЛИЕНТЫ CRUD ===
@app.route('/clients')
@login_required
def clients_list():
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("""SELECT cl.*, ct.type_name, COUNT(c.case_id) as cases_count 
                           FROM clients cl JOIN client_types ct ON cl.type_id = ct.type_id 
                           LEFT JOIN cases c ON cl.client_id = c.client_id 
                           GROUP BY cl.client_id ORDER BY cl.created_at DESC""")
            items = cur.fetchall()
    finally:
        db.close()
    return render_template('clients/list.html', items=items)

@app.route('/clients/add', methods=['GET', 'POST'])
@login_required
def client_add():
    if session['role_id'] not in [1, 2]:
        flash('Недостаточно прав', 'error'); return redirect(url_for('clients_list'))
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT type_id, type_name FROM client_types ORDER BY type_id")
            types = cur.fetchall()
        if request.method == 'POST':
            data = {k: v.strip() for k, v in request.form.items()}
            if not data.get('name') or not data.get('phone'):
                flash('ФИО и телефон обязательны', 'error')
                return render_template('clients/form.html', types=types, mode='add')
            cur.execute("SELECT client_id FROM clients WHERE phone = %s", (data['phone'],))
            if cur.fetchone():
                flash('Клиент с таким телефоном уже существует', 'warning')
                return render_template('clients/form.html', types=types, mode='add', data=data)
            cur.execute("""INSERT INTO clients (type_id, name, inn, phone, email, address, created_by) 
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        (data['type_id'], data['name'], data.get('inn'), data['phone'],
                         data.get('email'), data.get('address'), session['user_id']))
            db.commit()
            flash('Клиент успешно добавлен', 'success')
            return redirect(url_for('clients_list'))
    finally:
        db.close()
    return render_template('clients/form.html', types=types, mode='add')

# === ДЕЛА CRUD ===
@app.route('/cases')
@login_required
def cases_list():
    db = get_db()
    try:
        with db.cursor() as cur:
            sql = """SELECT c.*, cl.name as client_name, u.full_name as lawyer_name, 
                            cs.status_name, cc.category_name
                     FROM cases c 
                     JOIN clients cl ON c.client_id = cl.client_id 
                     JOIN users u ON c.assigned_user_id = u.user_id 
                     JOIN case_statuses cs ON c.status_id = cs.status_id 
                     JOIN case_categories cc ON c.category_id = cc.category_id"""
            if session['role_id'] == 3:
                sql += " WHERE c.assigned_user_id = %s"
                cur.execute(sql, (session['user_id'],))
            else:
                cur.execute(sql)
            items = cur.fetchall()
    finally:
        db.close()
    return render_template('cases/list.html', items=items, role=session['role_id'])


# === ЗАСЕДАНИЯ CRUD ===
@app.route('/hearings/<int:case_id>')
@login_required
def hearings(case_id):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM hearings WHERE case_id = %s ORDER BY hearing_date DESC", (case_id,))
            items = cur.fetchall()
            cur.execute("SELECT case_number FROM cases WHERE case_id = %s", (case_id,))
            case = cur.fetchone()
    finally:
        db.close()
    return render_template('hearings/list.html', items=items, case=case, case_id=case_id)

@app.route('/hearings/add/<int:case_id>', methods=['GET', 'POST'])
@login_required
def hearing_add(case_id):
    db = get_db()
    try:
        if request.method == 'POST':
            d = request.form
            if not all([d.get('date'), d.get('court'), d.get('room')]):
                flash('Заполните дату, суд и зал', 'error')
            else:
                with db.cursor() as cur:
                    cur.execute("""INSERT INTO hearings (case_id, hearing_date, court_name, courtroom, judge_name, result) 
                                   VALUES (%s, %s, %s, %s, %s, %s)""",
                                (case_id, d['date'], d['court'], d['room'], d.get('judge'), d.get('result')))
                    db.commit()
                flash('Заседание добавлено', 'success')
                return redirect(url_for('hearings', case_id=case_id))
        return render_template('hearings/form.html', case_id=case_id)
    finally:
        db.close()

# === ДОКУМЕНТЫ CRUD ===
@app.route('/documents/<int:case_id>')
@login_required
def docs(case_id):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("""SELECT d.*, dt.type_name, u.full_name as uploader 
                           FROM documents d JOIN document_types dt ON d.doc_type_id = dt.doc_type_id 
                           JOIN users u ON d.uploaded_by = u.user_id 
                           WHERE d.case_id = %s ORDER BY d.upload_date DESC""", (case_id,))
            items = cur.fetchall()
            cur.execute("SELECT doc_type_id, type_name FROM document_types")
            types = cur.fetchall()
    finally:
        db.close()
    return render_template('documents/list.html', items=items, types=types, case_id=case_id)

@app.route('/documents/upload/<int:case_id>', methods=['POST'])
@login_required
def doc_upload(case_id):
    if 'file' not in request.files:
        flash('Файл не выбран', 'error'); return redirect(url_for('docs', case_id=case_id))
    f = request.files['file']
    if f.filename == '' or not allowed_file(f.filename):
        flash('Недопустимый формат файла', 'error'); return redirect(url_for('docs', case_id=case_id))
    filename = secure_filename(f.filename)
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    f.save(save_path)
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM documents")
            # Простой размер для отчёта
            f.seek(0, 2); size = f.tell()
            cur.execute("""INSERT INTO documents (case_id, doc_type_id, file_name, file_path, uploaded_by, file_size) 
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (case_id, request.form.get('type_id'), filename, f'/static/uploads/{filename}', session['user_id'], size))
            db.commit()
        flash('Документ загружен', 'success')
    except Exception as e:
        flash(f'Ошибка: {e}', 'error')
    finally:
        db.close()
    return redirect(url_for('docs', case_id=case_id))

# === ПОЛЬЗОВАТЕЛИ CRUD ===
@app.route('/users')
@login_required
def users_list():
    if session['role_id'] != 1:
        flash('Доступ только администратору', 'error'); return redirect(url_for('dashboard'))
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("""SELECT u.*, r.role_name FROM users u JOIN roles r ON u.role_id = r.role_id ORDER BY u.user_id""")
            items = cur.fetchall()
            cur.execute("SELECT role_id, role_name FROM roles ORDER BY role_id")
            roles = cur.fetchall()
    finally:
        db.close()
    return render_template('users/list.html', items=items, roles=roles)

@app.route('/users/add', methods=['POST'])
@login_required
def user_add():
    if session['role_id'] != 1: return redirect(url_for('dashboard'))
    d = request.form
    if not all([d.get('login'), d.get('password'), d.get('name'), d.get('role')]):
        flash('Заполните все поля', 'error'); return redirect(url_for('users_list'))
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("INSERT INTO users (login, password_hash, role_id, full_name, email, is_active) VALUES (%s, %s, %s, %s, %s, TRUE)",
                        (d['login'], generate_password_hash(d['password']), d['role'], d['name'], d.get('email')))
            db.commit()
        flash('Пользователь создан', 'success')
    finally:
        db.close()
    return redirect(url_for('users_list'))

@app.route('/users/toggle/<int:uid>')
@login_required
def user_toggle(uid):
    if session['role_id'] != 1 or uid == session['user_id']:
        flash('Недостаточно прав или нельзя редактировать себя', 'error'); return redirect(url_for('users_list'))
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("UPDATE users SET is_active = NOT is_active WHERE user_id = %s", (uid,))
            db.commit()
    finally:
        db.close()
    return redirect(url_for('users_list'))

# === СПРАВОЧНИКИ (Unified CRUD) ===
@app.route('/refs/<table_name>')
@login_required
def refs_manage(table_name):
    allowed = {'roles', 'client_types', 'case_statuses', 'case_categories', 'document_types'}
    if table_name not in allowed or session['role_id'] != 1:
        flash('Недоступно', 'error'); return redirect(url_for('dashboard'))
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(f"SELECT * FROM {table_name} ORDER BY 1")
            items = cur.fetchall()
            cols = cur.description
    finally:
        db.close()
    return render_template('refs/manage.html', table=table_name, items=items, cols=cols)

@app.route('/refs/add/<table_name>', methods=['POST'])
@login_required
def ref_add(table_name):
    if session['role_id'] != 1: return redirect(url_for('dashboard'))
    val = request.form.get('val', '').strip()
    if not val: flash('Пустое значение', 'error'); return redirect(url_for('refs_manage', table_name=table_name))
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(f"INSERT INTO {table_name} ({list(cur.execute(f'DESCRIBE {table_name}').fetchall()[0]['Field'])[1]}) VALUES (%s)", (val,))
            db.commit()
        flash('Добавлено', 'success')
    except:
        db.rollback()
        flash('Ошибка: дубликат или нарушение целостности', 'error')
    finally:
        db.close()
    return redirect(url_for('refs_manage', table_name=table_name))

@app.route('/refs/del/<table_name>/<int:rid>')
@login_required
def ref_del(table_name, rid):
    if session['role_id'] != 1: return redirect(url_for('dashboard'))
    db = get_db()
    try:
        with db.cursor() as cur:
            pk = list(cur.execute(f'DESCRIBE {table_name}').fetchall())[0]['Field']
            cur.execute(f"DELETE FROM {table_name} WHERE {pk} = %s", (rid,))
            db.commit()
        flash('Удалено', 'success')
    except pymysql.err.IntegrityError:
        flash('Нельзя удалить: используется в основных таблицах', 'warning')
    finally:
        db.close()
    return redirect(url_for('refs_manage', table_name=table_name))


# === КЛИЕНТЫ: РЕДАКТИРОВАНИЕ ===
# Маршрут: Редактирование клиента
# Назначение: Загрузка данных, валидация, обновление записи в БД
@app.route('/clients/edit/<int:client_id>', methods=['GET', 'POST'])
@login_required
def client_edit(client_id):
    if session['role_id'] not in [1, 2]:
        flash('Недостаточно прав', 'error');
        return redirect(url_for('clients_list'))
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM clients WHERE client_id = %s", (client_id,))
            client = cur.fetchone()
            if not client:
                flash('Клиент не найден', 'error');
                return redirect(url_for('clients_list'))
            cur.execute("SELECT type_id, type_name FROM client_types ORDER BY type_id")
            types = cur.fetchall()

        if request.method == 'POST':
            data = {k: v.strip() for k, v in request.form.items()}
            if not data.get('name') or not data.get('phone'):
                flash('ФИО и телефон обязательны', 'error')
                return render_template('clients/form.html', types=types, mode='edit',
                                       data={**data, 'client_id': client_id})

            cur.execute("SELECT client_id FROM clients WHERE phone = %s AND client_id != %s",
                        (data['phone'], client_id))
            if cur.fetchone():
                flash('Клиент с таким телефоном уже существует', 'warning')
                return render_template('clients/form.html', types=types, mode='edit',
                                       data={**data, 'client_id': client_id})

            cur.execute("""UPDATE clients SET type_id=%s, name=%s, inn=%s, phone=%s, email=%s, address=%s 
                           WHERE client_id=%s""",
                        (data['type_id'], data['name'], data.get('inn'), data['phone'],
                         data.get('email'), data.get('address'), client_id))
            db.commit()
            flash('Данные клиента успешно обновлены', 'success')
            return redirect(url_for('clients_list'))
    finally:
        db.close()
    return render_template('clients/form.html', types=types, mode='edit', data=client)


# === ДЕЛА: РЕДАКТИРОВАНИЕ ===
# Маршрут: Редактирование дела
# Назначение: Изменение параметров дела, статуса, ответственного
@app.route('/cases/edit/<int:case_id>', methods=['GET', 'POST'])
@login_required
def case_edit(case_id):
    if session['role_id'] not in [1, 2]:
        flash('Недостаточно прав', 'error');
        return redirect(url_for('cases_list'))
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM cases WHERE case_id = %s", (case_id,))
            case = cur.fetchone()
            if not case:
                flash('Дело не найдено', 'error');
                return redirect(url_for('cases_list'))

            cur.execute("SELECT client_id, name FROM clients ORDER BY name")
            clients = cur.fetchall()
            cur.execute("SELECT user_id, full_name FROM users WHERE role_id = 3 AND is_active = TRUE")
            lawyers = cur.fetchall()
            cur.execute("SELECT category_id, category_name FROM case_categories")
            categories = cur.fetchall()
            cur.execute("SELECT status_id, status_name FROM case_statuses")
            statuses = cur.fetchall()

        if request.method == 'POST':
            d = request.form
            if not all([d.get('client_id'), d.get('lawyer_id'), d.get('subject'), d.get('status_id')]):
                flash('Заполните обязательные поля', 'error')
                return render_template('cases/form.html', clients=clients, lawyers=lawyers, cats=categories,
                                       statuses=statuses, mode='edit', data=case)

            cur.execute("""UPDATE cases SET client_id=%s, assigned_user_id=%s, category_id=%s, 
                           status_id=%s, subject=%s, end_date=%s WHERE case_id=%s""",
                        (d['client_id'], d['lawyer_id'], d['category_id'], d['status_id'],
                         d['subject'], d.get('end_date') or None, case_id))
            db.commit()
            flash(f'Дело {case["case_number"]} обновлено', 'success')
            return redirect(url_for('cases_list'))
    finally:
        db.close()
    return render_template('cases/form.html', clients=clients, lawyers=lawyers, cats=categories, statuses=statuses,
                           mode='edit', data=case)

@app.route('/cases/add', methods=['GET', 'POST'])
@login_required
def case_add():
    """Реализует создание нового дела с валидацией и генерацией номера"""
    if session['role_id'] not in [1, 2]: # Проверка прав: только Админ и Делопроизводитель
        flash('Недостаточно прав', 'error'); return redirect(url_for('cases_list'))
    db = get_db() # Получение соединения с БД
    try:
        with db.cursor() as cur:
            cur.execute("SELECT client_id, name FROM clients ORDER BY name") # Загрузка списка клиентов
            clients = cur.fetchall()
            cur.execute("SELECT user_id, full_name FROM users WHERE role_id = 3 AND is_active = TRUE") # Активные юристы
            lawyers = cur.fetchall()
            cur.execute("SELECT category_id, category_name FROM case_categories") # Справочник категорий
            categories = cur.fetchall()
        if request.method == 'POST': # Обработка POST-запроса формы
            data = {k: v.strip() for k, v in request.form.items()} # Очистка входных данных от пробелов
            if not all([data.get('client_id'), data.get('lawyer_id'), data.get('subject')]): # Валидация обязательных полей
                flash('Заполните клиента, юриста и суть дела', 'error')
                return render_template('cases/form.html', clients=clients, lawyers=lawyers, cats=categories, mode='add')
            cur.execute("SELECT COUNT(*) as cnt FROM cases") # Запрос текущего количества дел
            num = f"КТ-{datetime.now().year}-{cur.fetchone()['cnt']+1:04d}" # Генерация уникального номера
            cur.execute("""INSERT INTO cases (client_id, assigned_user_id, category_id, status_id, case_number, subject, start_date) 
                           VALUES (%s, %s, %s, 1, %s, %s, CURDATE())""",
                        (data['client_id'], data['lawyer_id'], data['category_id'], num, data['subject']))
            db.commit() # Фиксация транзакции
            flash(f'Дело {num} зарегистрировано', 'success')
            return redirect(url_for('cases_list'))
    finally:
        db.close()
    return render_template('cases/form.html', clients=clients, lawyers=lawyers, cats=categories, mode='add')
@app.route('/clients/delete/<int:client_id>', methods=['POST'])
@login_required
def client_delete(client_id):
    """Безопасное удаление клиента с проверкой ссылочной целостности"""
    if session['role_id'] not in [1, 2]: # Ограничение прав доступа
        flash('Недостаточно прав', 'error'); return redirect(url_for('clients_list'))
    db = get_db() # Открытие соединения
    try:
        with db.cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM cases WHERE client_id = %s", (client_id,)) # Проверка наличия дел у клиента
            result = cur.fetchone() # Получение результата подсчёта
            if result['cnt'] > 0: # Если найдены связанные записи
                flash(f'Нельзя удалить клиента с активными делами ({result["cnt"]} шт.)', 'error') # Блокировка удаления и уведомление
                return redirect(url_for('clients_list')) # Возврат в список без удаления
            cur.execute("DELETE FROM clients WHERE client_id = %s", (client_id,)) # Выполнение удаления
            db.commit() # Подтверждение транзакции
            flash('Клиент успешно удалён', 'success')
    except Exception as e: # Обработка ошибок СУБД
        db.rollback() # Откат изменений при сбое
        flash(f'Ошибка при удалении: {e}', 'error')
    finally:
        db.close() # Гарантированное закрытие соединения
    return redirect(url_for('clients_list'))
if __name__ == '__main__':
    app.run(debug=True, port=5000)