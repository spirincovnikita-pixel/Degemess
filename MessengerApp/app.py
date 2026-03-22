from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_socketio import SocketIO, emit, join_room, leave_room
import json
import os
from datetime import datetime  # Для времени создания

app = Flask(__name__)
app.config['SECRET_KEY'] = 'supersecretkey123'
socketio = SocketIO(app, cors_allowed_origins="*", manage_session=False)

# Файлы
USERS_FILE = 'users.json'
FRIENDS_FILE = 'friends.json'
GROUPS_FILE = 'groups.json'
CHATS_FILE = 'chats.json'

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def load_friends():
    if os.path.exists(FRIENDS_FILE):
        with open(FRIENDS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            for user in data:
                if 'friends' not in data[user]:
                    data[user]['friends'] = []
            return data
    return {}

def save_friends(friends):
    with open(FRIENDS_FILE, 'w', encoding='utf-8') as f:
        json.dump(friends, f, ensure_ascii=False, indent=4)

def load_groups():
    if os.path.exists(GROUPS_FILE):
        with open(GROUPS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_groups(groups):
    with open(GROUPS_FILE, 'w', encoding='utf-8') as f:
        json.dump(groups, f, ensure_ascii=False, indent=4)

def load_chats():
    if os.path.exists(CHATS_FILE):
        with open(CHATS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_chats(chats):
    with open(CHATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(chats, f, ensure_ascii=False, indent=4)

# Онлайн-пользователи
online_users = {}

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/auth', methods=['POST'])
def auth():
    data = request.get_json()
    username = data['username'].strip()
    password = data['password']
    action = data['type']

    if not username or not password:
        return jsonify({'success': False, 'message': 'Заполните все поля'})

    users = load_users()

    if action == 'register':
        if username in users:
            return jsonify({'success': False, 'message': 'Пользователь уже существует'})
        users[username] = password
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(users, f, ensure_ascii=False, indent=4)
        friends = load_friends()
        friends[username] = {'friends': []}
        save_friends(friends)
        return jsonify({'success': True, 'message': 'Регистрация успешна'})

    elif action == 'login':
        if username not in users:
            return jsonify({'success': False, 'message': 'Пользователь не найден'})
        if users[username] != password:
            return jsonify({'success': False, 'message': 'Неверный пароль'})
        return jsonify({'success': True, 'message': 'Вход выполнен'})

    return jsonify({'success': False, 'message': 'Ошибка'})

@app.route('/chat')
def chat():
    username = request.args.get('username')
    if not username:
        return redirect(url_for('login'))
    return render_template('index.html', username=username)

@app.route('/friends/<username>')
def get_friends(username):
    friends = load_friends()
    user_friends = friends.get(username, {'friends': []})
    return jsonify(user_friends['friends'])

@app.route('/groups/<username>')
def get_user_groups(username):
    groups = load_groups()
    user_groups = {}
    for gid, group in groups.items():
        if username in group['members']:
            user_groups[gid] = group
    return jsonify(user_groups)

@app.route('/add_friend', methods=['POST'])
def add_friend():
    data = request.get_json()
    current_user = data['current_user']
    friend_name = data['friend_name'].strip()

    users = load_users()
    if friend_name not in users:
        return jsonify({'success': False, 'message': 'Пользователь не найден'})

    if friend_name == current_user:
        return jsonify({'success': False, 'message': 'Нельзя добавить самого себя'})

    friends = load_friends()
    added = False

    if friend_name not in friends[current_user]['friends']:
        friends[current_user]['friends'].append(friend_name)
        added = True

    if current_user not in friends[friend_name]['friends']:
        friends[friend_name]['friends'].append(current_user)
        added = True

    save_friends(friends)

    if added:
        if current_user in online_users:
            socketio.emit('friend_added', {'friend': friend_name}, room=current_user)
        if friend_name in online_users:
            socketio.emit('friend_added', {'friend': current_user}, room=friend_name)

    return jsonify({'success': True, 'message': f'Пользователь {friend_name} добавлен в друзья'})

@app.route('/create_group', methods=['POST'])
def create_group():
    data = request.get_json()
    creator = data['creator']
    name = data['name'].strip()

    if not name:
        return jsonify({'success': False, 'message': 'Введите название'})

    groups = load_groups()
    group_id = f"group_{len(groups) + 1}"
    while group_id in groups:
        group_id = f"group_{len(groups) + 1}"

    groups[group_id] = {
        "name": name,
        "creator": creator,
        "members": [creator],
        "admins": [creator],  # Создатель — админ
        "created_at": datetime.now().strftime("%H:%M")
    }

    save_groups(groups)

    if creator in online_users:
        socketio.emit('group_created', {
            'group_id': group_id,
            'group': groups[group_id]
        }, room=creator)

    return jsonify({'success': True, 'group_id': group_id, 'group': groups[group_id]})

@app.route('/add_to_group', methods=['POST'])
def add_to_group():
    data = request.get_json()
    requester = data['requester']
    group_id = data['group_id']
    username = data['username'].strip()

    groups = load_groups()
    if group_id not in groups:
        return jsonify({'success': False, 'message': 'Группа не найдена'})

    group = groups[group_id]

    if requester not in group['admins'] and requester != group['creator']:
        return jsonify({'success': False, 'message': 'Нет прав'})

    users = load_users()
    if username not in users:
        return jsonify({'success': False, 'message': 'Пользователь не найден'})

    if username in group['members']:
        return jsonify({'success': False, 'message': 'Уже в группе'})

    group['members'].append(username)
    save_groups(groups)

    for member in group['members']:
        socketio.emit('group_updated', {'group_id': group_id, 'group': group}, room=member)

    return jsonify({'success': True, 'group': group})

@app.route('/rename_group', methods=['POST'])
def rename_group():
    data = request.get_json()
    requester = data['requester']
    group_id = data['group_id']
    new_name = data['name'].strip()

    if not new_name:
        return jsonify({'success': False, 'message': 'Введите название'})

    groups = load_groups()
    if group_id not in groups:
        return jsonify({'success': False, 'message': 'Группа не найдена'})

    group = groups[group_id]

    if requester not in group['admins'] and requester != group['creator']:
        return jsonify({'success': False, 'message': 'Нет прав'})

    group['name'] = new_name
    save_groups(groups)

    for member in group['members']:
        socketio.emit('group_updated', {'group_id': group_id, 'group': group}, room=member)

    return jsonify({'success': True, 'group': group})

@app.route('/make_admin', methods=['POST'])
def make_admin():
    data = request.get_json()
    requester = data['requester']
    group_id = data['group_id']
    username = data['username']

    groups = load_groups()
    if group_id not in groups:
        return jsonify({'success': False, 'message': 'Группа не найдена'})

    group = groups[group_id]

    if requester not in group['admins'] and requester != group['creator']:
        return jsonify({'success': False, 'message': 'Нет прав'})

    if username not in group['members']:
        return jsonify({'success': False, 'message': 'Не участник'})

    if username in group['admins']:
        return jsonify({'success': False, 'message': 'Уже админ'})

    group['admins'].append(username)
    save_groups(groups)

    for member in group['members']:
        socketio.emit('group_updated', {'group_id': group_id, 'group': group}, room=member)

    return jsonify({'success': True, 'group': group})

@app.route('/remove_from_group', methods=['POST'])
def remove_from_group():
    data = request.get_json()
    requester = data['requester']
    group_id = data['group_id']
    username = data['username']

    groups = load_groups()
    if group_id not in groups:
        return jsonify({'success': False, 'message': 'Группа не найдена'})

    group = groups[group_id]

    if requester not in group['admins'] and requester != group['creator']:
        return jsonify({'success': False, 'message': 'Нет прав'})

    if username not in group['members']:
        return jsonify({'success': False, 'message': 'Не участник'})

    if username == group['creator']:
        return jsonify({'success': False, 'message': 'Нельзя удалить создателя'})

    group['members'].remove(username)
    if username in group['admins']:
        group['admins'].remove(username)

    save_groups(groups)

    for member in group['members']:
        socketio.emit('group_updated', {'group_id': group_id, 'group': group}, room=member)

    if username in online_users:
        socketio.emit('group_removed', {'group_id': group_id}, room=username)

    return jsonify({'success': True, 'group': group})

@app.route('/messages/<username>/<friend>')
def get_messages(username, friend):
    chats = load_chats()
    key = f"{min(username, friend)}-{max(username, friend)}"
    return jsonify(chats.get(key, []))

@app.route('/messages/group/<group_id>')
def get_group_messages(group_id):
    chats = load_chats()
    return jsonify(chats.get(f"group_{group_id}", []))

def save_message(sender, receiver, message, timestamp):
    chats = load_chats()
    key = f"{min(sender, receiver)}-{max(sender, receiver)}"
    if key not in chats:
        chats[key] = []
    chats[key].append({'sender': sender, 'message': message, 'timestamp': timestamp})
    save_chats(chats)

def save_group_message(group_id, sender, message, timestamp):
    chats = load_chats()
    key = f"group_{group_id}"
    if key not in chats:
        chats[key] = []
    chats[key].append({'sender': sender, 'message': message, 'timestamp': timestamp})
    save_chats(chats)

@socketio.on('login')
def handle_login(data):
    username = data.get('username')
    if username in load_users():
        join_room(username)
        online_users[username] = request.sid
        socketio.emit('user_status', {'user': username, 'status': 'online'}, include_self=False)
        for user in online_users:
            if user != username:
                emit('user_status', {'user': user, 'status': 'online'})
        print(f"🟢 {username} вошёл")

@socketio.on('disconnect')
def handle_disconnect():
    for user, sid in list(online_users.items()):
        if sid == request.sid:
            del online_users[user]
            socketio.emit('user_status', {'user': user, 'status': 'offline'})
            print(f"🔴 {user} вышел")
            break

@socketio.on('send_message')
def handle_send_message(data):
    sender = data['sender']
    receiver = data['receiver']
    message = data['message']
    timestamp = data['timestamp']

    friends = load_friends()
    if receiver not in friends.get(sender, {}).get('friends', []):
        emit('error', {'message': 'Вы не можете писать этому пользователю'})
        return

    save_message(sender, receiver, message, timestamp)
    emit('receive_message', data, room=sender)
    emit('receive_message', data, room=receiver)

@socketio.on('send_group_message')
def handle_send_group_message(data):
    sender = data['sender']
    group_id = data['group_id']
    message = data['message']
    timestamp = data['timestamp']

    groups = load_groups()
    if group_id not in groups:
        emit('error', {'message': 'Группа не найдена'})
        return

    if sender not in groups[group_id]['members']:
        emit('error', {'message': 'Вы не участник'})
        return

    save_group_message(group_id, sender, message, timestamp)

    for member in groups[group_id]['members']:
        emit('receive_group_message', data, room=member)

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)




