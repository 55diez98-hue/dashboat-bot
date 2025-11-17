 import os
session_file = 'monitor_session.session'
if os.path.exists(session_file):
    os.remove(session_file)
    print(f"[FORCE] {session_file} УДАЛЕНА!")
else:
    print(f"[FORCE] {session_file} не найдена — можно авторизоваться.")
