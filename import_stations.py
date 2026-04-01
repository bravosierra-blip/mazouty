"""
Import des stations Google Places (Phase 1) → SQLite
Usage : python import_stations.py stations_casablanca.csv
"""
import csv, sqlite3, sys, os

DATABASE = os.environ.get("DATABASE_PATH", "mazouty.db")

def import_stations(csv_path):
    if not os.path.exists(csv_path):
        print(f"Erreur : fichier '{csv_path}' introuvable"); sys.exit(1)
    conn = sqlite3.connect(DATABASE)
    imported = skipped = errors = 0
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                place_id = row.get("place_id", "")
                name = row.get("name", "")
                brand = row.get("brand", "Autre")
                address = row.get("address", "")
                latitude = float(row.get("latitude", 0))
                longitude = float(row.get("longitude", 0))
                if not place_id or not name or latitude == 0:
                    skipped += 1; continue
                rating = float(row["rating"]) if row.get("rating") else None
                ratings_count = int(float(row["user_ratings_total"])) if row.get("user_ratings_total") else None
                conn.execute(
                    "INSERT OR IGNORE INTO stations (place_id, name, brand, address, city, latitude, longitude, phone, website, rating, user_ratings_total, business_status) VALUES (?, ?, ?, ?, 'Casablanca', ?, ?, ?, ?, ?, ?, ?)",
                    (place_id, name, brand, address, latitude, longitude, row.get("phone", ""), row.get("website", ""), rating, ratings_count, row.get("business_status", "")))
                imported += 1
            except Exception as e:
                errors += 1; print(f"  Erreur: {e}")
    conn.commit(); conn.close()
    count = sqlite3.connect(DATABASE).execute("SELECT COUNT(*) FROM stations").fetchone()[0]
    print(f"\nImport terminé ! {imported} importées, {skipped} ignorées, {errors} erreurs. Total: {count}")

if __name__ == "__main__":
    if len(sys.argv) < 2: print("Usage : python import_stations.py fichier.csv"); sys.exit(1)
    import_stations(sys.argv[1])
