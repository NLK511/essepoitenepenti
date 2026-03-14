import sqlite3
conn = sqlite3.connect('/home/aurelio/workspace/trade-proposer-app/trade_proposer.db')
cursor = conn.cursor()
cursor.execute("select key, value from app_settings")
for row in cursor.fetchall():
    print(row)
conn.close()
