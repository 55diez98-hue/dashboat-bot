import os
if os.path.exists('monitor_session.session'):
    os.remove('monitor_session.session')
    print("СЕССИЯ УДАЛЕНА! Перезапусти мониторинг.")
else:
    print("Сессии нет — можно авторизоваться.")
