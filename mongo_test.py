"""MongoDB Atlas connection check. Reads MONGO_URL from .env; never prints the URL."""
import os
import sys

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
uri = os.getenv("MONGO_URL")
if not uri:
    sys.exit("MONGO_URL .env içinde yok.")
if "<db_password>" in uri:
    sys.exit("MONGO_URL içinde hâlâ <db_password> yazıyor; gerçek şifreyi koy.")

client = MongoClient(uri, serverSelectionTimeoutMS=10_000)
try:
    client.admin.command("ping")
    db = client.get_default_database(default="kriptokapi")
    db.baglanti_testi.insert_one({"test": True})
    db.baglanti_testi.drop()
    print(f"Bağlantı başarılı. Veritabanı: {db.name}, okuma/yazma çalışıyor.")
except Exception as e:
    print(f"Bağlantı hatası: {type(e).__name__}: {str(e).split(',')[0]}")
finally:
    client.close()
