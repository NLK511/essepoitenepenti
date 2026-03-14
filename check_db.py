import sqlite3
conn = sqlite3.connect('/home/aurelio/workspace/trade-proposer-app/trade_proposer.db')
cursor = conn.cursor()
cursor.execute("select provider, api_key, api_secret from provider_credentials")
for row in cursor.fetchall():
    print(row)
conn.close()
