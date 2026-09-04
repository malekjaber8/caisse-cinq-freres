#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Livre de Caisse — Les Cinq Frères
Application de bureau 100% locale (aucune connexion internet requise).
Toutes les données sont stockées dans un fichier SQLite local (caisse.db)
situé à côté de ce script.

Lancer :  python caisse_app.py
"""

import os
import csv
import hashlib
import json
import platform
import shutil
import sqlite3
import sys
import uuid
import calendar as calendar_mod
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from datetime import date, datetime, timedelta
import webbrowser
import html

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "caisse.db")
EXPORTS_DIR = os.path.join(APP_DIR, "etats_imprimes")
ASSETS_DIR = os.path.join(APP_DIR, "assets")
ATTACHMENTS_DIR = os.path.join(APP_DIR, "justificatifs")
ATTACHMENT_FILETYPES = [("Photos et PDF", "*.jpg *.jpeg *.png *.pdf"), ("Tous les fichiers", "*.*")]
BACKUP_DIR = os.path.join(APP_DIR, "sauvegardes")
BACKUP_RETENTION_DAYS = 30

CATEGORIE_VERSEMENT = "Versement banque"

DEFAULT_CATEGORIES = [
    "Carburant / Vidange",
    "Entretien véhicule",
    "Internet / Téléphone",
    "Fournitures bureau",
    "Salaires",
    CATEGORIE_VERSEMENT,
    "Livraison / Transport",
    "Autre",
]

FR_MOIS = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet",
           "Août", "Septembre", "Octobre", "Novembre", "Décembre"]
FR_JOURS = ["Lu", "Ma", "Me", "Je", "Ve", "Sa", "Di"]

# Palette de marque "Société Magasin Les Cinq Frères" (extraite du logo)
NAVY = "#004E74"        # bleu marine — actions principales, titres
NAVY_DEEP = "#00354F"   # bleu marine profond — en-tête, bandeau résumé
TEAL = "#08A4B0"        # turquoise — accents sur fond sombre
TEAL_DARK = "#067885"   # turquoise foncé — accents sur fond clair, survol
INK = "#1F2A33"         # texte principal
MUTED = "#5B6B79"       # texte secondaire
BG = "#F4F6F8"          # fond général de l'application
SURFACE = "#FFFFFF"     # fond des panneaux / tableaux
BORDER = "#DCE3E8"      # séparateurs, bordures
SUCCESS = "#1B8A5A"     # montant final positif
DANGER = "#C1373B"      # montant final négatif (caisse en déficit)

ASSETS_DIR = os.path.join(APP_DIR, "assets")


def fmt(n):
    try:
        return f"{n:,.3f}".replace(",", " ") + " DT"
    except Exception:
        return "0.000 DT"


def parse_amount(text):
    """Convertit un texte saisi dans un champ montant en nombre, en tolérant
    les espaces (normaux ou insécables) utilisées comme séparateur de
    milliers - comme dans l'affichage de fmt() ci-dessus, ex: '1 550.000' -
    et la virgule comme séparateur décimal. Lève ValueError si le texte,
    une fois nettoyé, n'est toujours pas un nombre valide."""
    cleaned = text.strip().replace("\xa0", "").replace(" ", "").replace(" ", "")
    cleaned = cleaned.replace(",", ".")
    return float(cleaned)


# ---------------------------------------------------------------------------
# Base de données
# ---------------------------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS jours (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        jour_date TEXT UNIQUE NOT NULL,
        solde_initial REAL NOT NULL DEFAULT 0,
        recettes REAL NOT NULL DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS depenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        jour_id INTEGER NOT NULL,
        motif TEXT NOT NULL,
        categorie TEXT NOT NULL,
        montant REAL NOT NULL,
        piece_jointe TEXT,
        FOREIGN KEY (jour_id) REFERENCES jours(id) ON DELETE CASCADE
    )""")
    # Migration : les bases existantes créées avant l'ajout des justificatifs
    # n'ont pas encore la colonne piece_jointe.
    c.execute("PRAGMA table_info(depenses)")
    cols = [row[1] for row in c.fetchall()]
    if "piece_jointe" not in cols:
        c.execute("ALTER TABLE depenses ADD COLUMN piece_jointe TEXT")
    c.execute("""CREATE TABLE IF NOT EXISTS app_config (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        horodatage TEXT NOT NULL,
        jour_date TEXT NOT NULL,
        description TEXT NOT NULL
    )""")
    conn.commit()
    conn.close()


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# Configuration / protection par mot de passe
# ---------------------------------------------------------------------------
def get_config(key, default=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM app_config WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default


def set_config(key, value):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO app_config (key, value) VALUES (?, ?) "
              "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Verrou "poste actif" — quand caisse.db est partagé via un dossier cloud
# (OneDrive/Google Drive) entre plusieurs ordinateurs, avertit si un AUTRE
# poste a utilisé l'application très récemment, pour éviter que deux
# personnes n'écrasent leurs saisies l'une de l'autre. Stocké dans la table
# app_config déjà existante (aucune migration de schéma nécessaire).
# ---------------------------------------------------------------------------
LOCK_MAX_AGE_SECONDS = 300


def machine_name():
    return os.environ.get("COMPUTERNAME") or platform.node() or "Poste inconnu"


def check_active_lock(current_machine, max_age_seconds=LOCK_MAX_AGE_SECONDS):
    lock_machine = get_config("lock_machine")
    lock_heartbeat = get_config("lock_heartbeat_at")
    if not lock_machine or lock_machine == current_machine or not lock_heartbeat:
        return None
    try:
        last = datetime.strptime(lock_heartbeat, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    if (datetime.now() - last).total_seconds() > max_age_seconds:
        return None
    return {"machine": lock_machine, "heartbeat_at": lock_heartbeat}


def touch_lock(current_machine):
    set_config("lock_machine", current_machine)
    set_config("lock_heartbeat_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


def release_lock(current_machine):
    if get_config("lock_machine") == current_machine:
        set_config("lock_machine", "")
        set_config("lock_heartbeat_at", "")


def get_categories():
    """Liste des catégories, modifiable depuis l'appli (stockée en base).
    CATEGORIE_VERSEMENT est toujours présente : son traitement spécial
    (déduite de la caisse mais pas comptée comme dépense) en dépend."""
    raw = get_config("categories")
    if raw:
        try:
            cats = json.loads(raw)
            if isinstance(cats, list) and cats:
                if CATEGORIE_VERSEMENT not in cats:
                    cats.append(CATEGORIE_VERSEMENT)
                return cats
        except (ValueError, TypeError):
            pass
    return list(DEFAULT_CATEGORIES)


def set_categories(cats):
    cats = [c.strip() for c in cats if c.strip()]
    if CATEGORIE_VERSEMENT not in cats:
        cats.append(CATEGORIE_VERSEMENT)
    set_config("categories", json.dumps(cats, ensure_ascii=False))


def _hash_secret(secret, salt=None):
    if salt is None:
        salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, 100_000)
    return salt.hex(), digest.hex()


def _verify_secret(secret, salt_hex, hash_hex):
    salt = bytes.fromhex(salt_hex)
    _, digest_hex = _hash_secret(secret, salt)
    return digest_hex == hash_hex


def is_password_configured():
    return get_config("password_hash") is not None


def set_password(password, question=None, answer=None):
    salt, h = _hash_secret(password)
    set_config("password_salt", salt)
    set_config("password_hash", h)
    if question and answer:
        asalt, ah = _hash_secret(answer.strip().lower())
        set_config("security_question", question)
        set_config("security_answer_salt", asalt)
        set_config("security_answer_hash", ah)


def check_password(password):
    salt, h = get_config("password_salt"), get_config("password_hash")
    if not salt or not h:
        return False
    return _verify_secret(password, salt, h)


def get_security_question():
    return get_config("security_question", "")


def check_security_answer(answer):
    salt, h = get_config("security_answer_salt"), get_config("security_answer_hash")
    if not salt or not h:
        return False
    return _verify_secret(answer.strip().lower(), salt, h)


# ---------------------------------------------------------------------------
# Sauvegarde automatique (caisse.db + justificatifs) dans sauvegardes/
# ---------------------------------------------------------------------------
def backup_now():
    """Copie caisse.db et les justificatifs dans sauvegardes/, horodatés.
    Best-effort : ne lève jamais d'exception (ne doit jamais bloquer l'appli)."""
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%Hh%M")
        db_backup = os.path.join(BACKUP_DIR, f"caisse_{stamp}.db")
        shutil.copy2(DB_PATH, db_backup)
        if os.path.isdir(ATTACHMENTS_DIR) and os.listdir(ATTACHMENTS_DIR):
            shutil.make_archive(os.path.join(BACKUP_DIR, f"justificatifs_{stamp}"), "zip", ATTACHMENTS_DIR)
        _cleanup_old_backups()
        return db_backup
    except OSError:
        return None


def _cleanup_old_backups():
    cutoff = datetime.now() - timedelta(days=BACKUP_RETENTION_DAYS)
    for name in os.listdir(BACKUP_DIR):
        path = os.path.join(BACKUP_DIR, name)
        try:
            if datetime.fromtimestamp(os.path.getmtime(path)) < cutoff:
                os.remove(path)
        except OSError:
            pass


def _backup_exists_for_today():
    if not os.path.isdir(BACKUP_DIR):
        return False
    today = datetime.now().strftime("%Y-%m-%d")
    return any(name.startswith(f"caisse_{today}") for name in os.listdir(BACKUP_DIR))


def maybe_daily_backup():
    """Appelé au démarrage : fait une sauvegarde si aucune n'existe pour
    aujourd'hui. Silencieux, ne doit jamais empêcher l'appli de démarrer."""
    try:
        if os.path.exists(DB_PATH) and not _backup_exists_for_today():
            backup_now()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Journal des modifications a posteriori (jours passés déverrouillés)
# ---------------------------------------------------------------------------
def log_audit(jour_date, description):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO audit_log (horodatage, jour_date, description) VALUES (?, ?, ?)",
              (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), jour_date, description))
    conn.commit()
    conn.close()


def list_audit_log(limit=300):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT horodatage, jour_date, description FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [{"horodatage": r[0], "jour_date": r[1], "description": r[2]} for r in rows]


def upsert_jour(jour_date, solde_initial, recettes, expenses):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id FROM jours WHERE jour_date = ?", (jour_date,))
    row = c.fetchone()
    if row:
        jour_id = row[0]
        c.execute("UPDATE jours SET solde_initial=?, recettes=? WHERE id=?",
                  (solde_initial, recettes, jour_id))
        c.execute("DELETE FROM depenses WHERE jour_id=?", (jour_id,))
    else:
        c.execute("INSERT INTO jours (jour_date, solde_initial, recettes) VALUES (?,?,?)",
                  (jour_date, solde_initial, recettes))
        jour_id = c.lastrowid
    for e in expenses:
        c.execute("INSERT INTO depenses (jour_id, motif, categorie, montant, piece_jointe) VALUES (?,?,?,?,?)",
                  (jour_id, e["motif"], e["categorie"], e["montant"], e.get("piece_jointe")))
    conn.commit()
    conn.close()
    return jour_id


def load_jour(jour_date):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, solde_initial, recettes FROM jours WHERE jour_date=?", (jour_date,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None
    jour_id, solde_initial, recettes = row
    c.execute("SELECT id, motif, categorie, montant, piece_jointe FROM depenses WHERE jour_id=?", (jour_id,))
    expenses = [{"id": r[0], "motif": r[1], "categorie": r[2], "montant": r[3], "piece_jointe": r[4]}
                for r in c.fetchall()]
    conn.close()
    return {"jour_date": jour_date, "solde_initial": solde_initial, "recettes": recettes, "expenses": expenses}


# ---------------------------------------------------------------------------
# Justificatifs (photos / PDF de factures) — stockés dans un dossier local,
# seul le nom de fichier est conservé dans la base.
# ---------------------------------------------------------------------------
def save_attachment(source_path):
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    ext = os.path.splitext(source_path)[1].lower()
    filename = f"{uuid.uuid4().hex}{ext}"
    shutil.copy2(source_path, os.path.join(ATTACHMENTS_DIR, filename))
    return filename


def open_attachment(filename):
    path = os.path.join(ATTACHMENTS_DIR, filename)
    if not os.path.exists(path):
        messagebox.showerror("Fichier introuvable", "Ce justificatif est introuvable sur le disque.")
        return
    os.startfile(path)


def days_with_entries(year, month):
    """Ensemble des dates (YYYY-MM-DD) déjà enregistrées pour ce mois — utilisé
    pour repérer les jours saisis dans le calendrier."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT jour_date FROM jours WHERE jour_date LIKE ?", (f"{year:04d}-{month:02d}-%",))
    result = {r[0] for r in c.fetchall()}
    conn.close()
    return result


def list_jours():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT jour_date, solde_initial, recettes FROM jours ORDER BY jour_date DESC")
    rows = c.fetchall()
    result = []
    for jour_date, solde_initial, recettes in rows:
        c.execute("SELECT COALESCE(SUM(montant),0), COUNT(*) FROM depenses WHERE jour_id=(SELECT id FROM jours WHERE jour_date=?)", (jour_date,))
        total_dep, nb = c.fetchone()
        final = solde_initial + recettes - total_dep
        result.append({"date": jour_date, "solde_initial": solde_initial, "recettes": recettes,
                        "total_depenses": total_dep, "nb_depenses": nb, "final": final})
    conn.close()
    return result


def last_day_before(jour_date):
    """Dernière journée enregistrée avant jour_date : sa date et son montant
    final. Sert à reporter automatiquement le solde de caisse jour après jour,
    et à détecter le début d'un nouveau mois (quand cette date change de mois)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT jour_date, solde_initial, recettes FROM jours WHERE jour_date < ? ORDER BY jour_date DESC LIMIT 1", (jour_date,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None
    d, si, rec = row
    c.execute("SELECT COALESCE(SUM(montant),0) FROM depenses WHERE jour_id=(SELECT id FROM jours WHERE jour_date=?)", (d,))
    total_dep = c.fetchone()[0]
    conn.close()
    return {"date": d, "final": si + rec - total_dep}


def _period_stats(start_date, end_date):
    """Agrège les journées de start_date à end_date (inclus), en distinguant
    les vraies dépenses des versements banque (qui ne sont pas des dépenses
    mais réduisent quand même l'espèce en caisse)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, jour_date, solde_initial, recettes FROM jours WHERE jour_date BETWEEN ? AND ? ORDER BY jour_date",
              (start_date, end_date))
    rows = c.fetchall()
    total_recettes = total_depenses = total_versements = 0.0
    par_categorie = {}
    par_motif = {}
    days = []
    movements = []
    for jour_id, jour_date, solde_initial, recettes in rows:
        c.execute("SELECT categorie, motif, montant, piece_jointe FROM depenses WHERE jour_id=?", (jour_id,))
        day_dep = day_vers = 0.0
        if recettes:
            movements.append({"date": jour_date, "type": "Recette", "categorie": "", "motif": "",
                               "montant": recettes, "piece_jointe": None})
        for cat, motif, montant, piece_jointe in c.fetchall():
            par_categorie[cat] = par_categorie.get(cat, 0) + montant
            motif_key = (motif or "").strip().lower()
            if motif_key:
                # Regroupe par motif exact (insensible à la casse/espaces) :
                # permet de retrouver, par exemple, tout ce qui a été noté
                # au nom d'un employé donné, quelle que soit sa catégorie.
                entry = par_motif.setdefault(motif_key, {"label": motif.strip(), "total": 0.0,
                                                            "count": 0, "dates": []})
                entry["total"] += montant
                entry["count"] += 1
                entry["dates"].append(jour_date)
            is_versement = cat == CATEGORIE_VERSEMENT
            if is_versement:
                total_versements += montant
                day_vers += montant
            else:
                total_depenses += montant
                day_dep += montant
            movements.append({"date": jour_date, "type": "Versement banque" if is_versement else "Dépense",
                               "categorie": cat, "motif": motif, "montant": -montant, "piece_jointe": piece_jointe})
        total_recettes += recettes
        final = solde_initial + recettes - day_dep - day_vers
        days.append({"date": jour_date, "solde_initial": solde_initial, "recettes": recettes,
                      "depenses": day_dep, "versements": day_vers, "final": final})
    conn.close()
    return {
        "start": start_date, "end": end_date, "nb_jours": len(days),
        "total_recettes": total_recettes, "total_depenses": total_depenses,
        "total_versements": total_versements, "par_categorie": par_categorie,
        "par_motif": par_motif,
        "days": days, "movements": movements,
        "solde_debut": days[0]["solde_initial"] if days else None,
        "solde_fin": days[-1]["final"] if days else None,
    }


def week_stats(monday_date):
    """monday_date : 'YYYY-MM-DD' du lundi de la semaine voulue."""
    end = (datetime.strptime(monday_date, "%Y-%m-%d") + timedelta(days=6)).strftime("%Y-%m-%d")
    return _period_stats(monday_date, end)


def month_stats_full(year, month):
    start = f"{year:04d}-{month:02d}-01"
    end_day = calendar_mod.monthrange(year, month)[1]
    end = f"{year:04d}-{month:02d}-{end_day:02d}"
    return _period_stats(start, end)


def monthly_stats(year_month):
    """year_month format 'YYYY-MM'"""
    y, m = int(year_month[:4]), int(year_month[5:7])
    return month_stats_full(y, m)


def year_stats_full(year):
    return _period_stats(f"{year:04d}-01-01", f"{year:04d}-12-31")


def _group_days_by_month(days):
    """Agrège une liste de jours (issue de _period_stats) par mois, dans
    l'ordre chronologique — utilisé pour le détail du rapport annuel."""
    months = {}
    for d in days:
        ym = d["date"][:7]
        m = months.setdefault(ym, {"recettes": 0.0, "depenses": 0.0, "versements": 0.0,
                                     "solde_initial": d["solde_initial"], "final": None})
        m["recettes"] += d["recettes"]
        m["depenses"] += d["depenses"]
        m["versements"] += d["versements"]
        m["final"] = d["final"]
    return months


# ---------------------------------------------------------------------------
# Export / impression (génère une page HTML locale, ouverte dans le navigateur)
# ---------------------------------------------------------------------------
_LOGO_DATA_URI_CACHE = None


def _logo_data_uri():
    """Encode le logo en base64 pour que la fiche imprimée reste autonome
    (lisible même si le dossier etats_imprimes/ est copié ailleurs)."""
    global _LOGO_DATA_URI_CACHE
    if _LOGO_DATA_URI_CACHE is None:
        path = os.path.join(ASSETS_DIR, "logo_print.png")
        if os.path.exists(path):
            import base64
            with open(path, "rb") as f:
                _LOGO_DATA_URI_CACHE = "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
        else:
            _LOGO_DATA_URI_CACHE = ""
    return _LOGO_DATA_URI_CACHE


def export_print_html(jour_date, solde_initial, recettes, expenses, total_depenses, total_versements, final):
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    if expenses:
        rows = "".join(
            f"<tr><td>{html.escape(e['motif'])}</td>"
            f"<td class='muted'>{html.escape(e['categorie'])}</td>"
            f"<td class='amt'>{fmt(e['montant'])}</td></tr>"
            for e in expenses
        )
    else:
        rows = "<tr><td colspan='3' class='muted' style='text-align:center'>Aucune dépense ce jour</td></tr>"
    logo_uri = _logo_data_uri()
    logo_html = f'<img src="{logo_uri}" alt="Les Cinq Frères" class="logo">' if logo_uri else ""
    final_class = "positive" if final >= 0 else "negative"
    try:
        date_affichee = datetime.strptime(jour_date, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        date_affichee = jour_date
    content = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<title>Etat de caisse {jour_date}</title>
<style>
 :root {{
   --navy:#004E74; --navy-deep:#00354F; --teal:#08A4B0; --ink:#1F2A33;
   --muted:#5B6B79; --border:#DCE3E8; --success:#1B8A5A; --danger:#C1373B; --bg:#F4F6F8;
 }}
 * {{ box-sizing:border-box; }}
 body {{ font-family:'Segoe UI', Arial, sans-serif; background:var(--bg); color:var(--ink); margin:0; padding:40px 16px; font-size:15px; }}
 .card {{ max-width:640px; margin:0 auto; background:#fff; border:1px solid var(--border); border-radius:12px;
          box-shadow:0 6px 20px rgba(0,78,116,0.10); overflow:hidden; }}
 .head {{ background:var(--navy-deep); color:#fff; padding:26px 48px; text-align:center; }}
 .logo {{ height:56px; margin-bottom:10px; }}
 .head h1 {{ margin:0; font-size:18px; letter-spacing:0.5px; }}
 .head p {{ margin:5px 0 0; font-size:13px; color:var(--teal); font-weight:600; text-transform:uppercase; letter-spacing:1px; }}
 .body {{ padding:0 48px 40px; }}
 .date-row {{ display:flex; justify-content:space-between; align-items:baseline;
              padding:20px 0 16px; border-bottom:2px solid var(--navy); margin-bottom:20px; }}
 .date-row .label {{ font-size:12px; color:var(--muted); text-transform:uppercase; letter-spacing:0.5px; }}
 .date-row .value {{ font-size:20px; font-weight:700; color:var(--navy); }}
 .date-row .gen {{ font-size:11px; color:var(--muted); text-align:right; }}
 table {{ width:100%; border-collapse:collapse; }}
 .tbl-expenses {{ font-size:14px; border:1px solid var(--border); }}
 .tbl-expenses th {{ background:var(--bg); color:var(--muted); font-size:11px; text-transform:uppercase;
                      letter-spacing:0.5px; text-align:left; padding:8px 10px; border-bottom:1px solid var(--border); }}
 .tbl-expenses th.amt {{ text-align:right; }}
 .tbl-expenses td {{ padding:9px 10px; border-bottom:1px solid var(--border); }}
 .tbl-expenses tr:last-child td {{ border-bottom:none; }}
 .muted {{ color:var(--muted); }}
 .amt {{ text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }}
 .totals {{ margin-top:18px; font-size:15px; }}
 .totals td {{ padding:6px 0; }}
 .totals tr.final td {{ padding-top:14px; margin-top:6px; border-top:2px solid var(--navy);
                         font-weight:700; font-size:20px; }}
 .totals tr.final.positive td {{ color:var(--success); }}
 .totals tr.final.negative td {{ color:var(--danger); }}
 .signatures {{ display:flex; gap:32px; margin-top:56px; }}
 .sig-box {{ flex:1; text-align:center; }}
 .sig-line {{ height:40px; border-bottom:1px solid var(--ink); }}
 .sig-box span {{ display:block; margin-top:8px; font-size:12px; color:var(--muted); }}
 .foot {{ text-align:center; padding:0 48px 28px; }}
 button {{ background:var(--navy); color:#fff; border:none; border-radius:8px; padding:12px 28px;
           font-size:14px; font-weight:600; cursor:pointer; }}
 button:hover {{ background:var(--navy-deep); }}
 @media print {{ body {{ background:#fff; padding:0; }} .card {{ box-shadow:none; border:none; max-width:100%; }} .foot {{ display:none; }} }}
</style></head>
<body>
<div class="card">
  <div class="head">
    {logo_html}
    <h1>SOCIÉTÉ MAGASIN LES CINQ FRÈRES</h1>
    <p>État de caisse journalier</p>
  </div>
  <div class="body">
    <div class="date-row">
      <div><div class="label">Date</div><div class="value">{date_affichee}</div></div>
      <div class="gen">Généré le<br>{datetime.now().strftime('%d/%m/%Y à %H:%M')}</div>
    </div>
    <table class="tbl-expenses">
      <thead><tr><th>Désignation</th><th>Catégorie</th><th class="amt">Montant</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <table class="totals">
     <tr><td>Solde initial</td><td class="amt">{fmt(solde_initial)}</td></tr>
     <tr><td>Recette du jour</td><td class="amt">+ {fmt(recettes)}</td></tr>
     <tr><td>Total dépenses</td><td class="amt">- {fmt(total_depenses)}</td></tr>
     {"<tr><td>Versements banque</td><td class='amt'>- " + fmt(total_versements) + "</td></tr>" if total_versements else ""}
     <tr class="final {final_class}"><td>SOLDE FINAL</td><td class="amt">{fmt(final)}</td></tr>
    </table>
    <div class="signatures">
      <div class="sig-box"><div class="sig-line"></div><span>Signature caissier(ère)</span></div>
      <div class="sig-box"><div class="sig-line"></div><span>Signature responsable</span></div>
    </div>
  </div>
  <div class="foot"><button onclick="window.print()">🖨 Imprimer</button></div>
</div>
</body></html>"""
    path = os.path.join(EXPORTS_DIR, f"etat_{jour_date}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    webbrowser.open(f"file://{path}")


def export_period_report_html(period_type, period_label, filename_slug, stats):
    """Rapport imprimable pour une période (semaine ou mois) : totaux,
    répartition par catégorie et détail jour par jour."""
    os.makedirs(EXPORTS_DIR, exist_ok=True)

    if stats["par_categorie"]:
        cat_rows = "".join(
            f"<tr><td>{html.escape(cat)}</td><td class='amt'>{fmt(montant)}</td></tr>"
            for cat, montant in sorted(stats["par_categorie"].items(), key=lambda x: -x[1])
        )
    else:
        cat_rows = "<tr><td colspan='2' class='muted' style='text-align:center'>Aucune dépense</td></tr>"

    if stats.get("par_motif"):
        motif_rows = "".join(
            f"<tr><td>{html.escape(m['label'])}</td><td class='amt'>{m['count']}</td>"
            f"<td class='amt'>{fmt(m['total'])}</td></tr>"
            for m in sorted(stats["par_motif"].values(), key=lambda x: -x["total"])
        )
    else:
        motif_rows = "<tr><td colspan='3' class='muted' style='text-align:center'>Aucun motif enregistré</td></tr>"

    if stats["days"]:
        day_rows = "".join(
            f"<tr><td>{d['date']}</td><td class='amt'>{fmt(d['recettes'])}</td>"
            f"<td class='amt'>{fmt(d['depenses'])}</td><td class='amt'>{fmt(d['versements'])}</td>"
            f"<td class='amt' style='font-weight:700; color:{SUCCESS if d['final'] >= 0 else DANGER}'>{fmt(d['final'])}</td></tr>"
            for d in stats["days"]
        )
    else:
        day_rows = "<tr><td colspan='5' class='muted' style='text-align:center'>Aucune journée enregistrée sur cette période</td></tr>"

    solde_debut_txt = fmt(stats["solde_debut"]) if stats["solde_debut"] is not None else "—"
    solde_fin_txt = fmt(stats["solde_fin"]) if stats["solde_fin"] is not None else "—"
    final_class = "positive" if (stats["solde_fin"] or 0) >= 0 else "negative"
    logo_uri = _logo_data_uri()
    logo_html = f'<img src="{logo_uri}" alt="Les Cinq Frères" class="logo">' if logo_uri else ""

    content = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<title>Rapport {period_type.lower()} — {period_label}</title>
<style>
 :root {{
   --navy:#004E74; --navy-deep:#00354F; --teal:#08A4B0; --ink:#1F2A33;
   --muted:#5B6B79; --border:#DCE3E8; --success:#1B8A5A; --danger:#C1373B; --bg:#F4F6F8;
 }}
 * {{ box-sizing:border-box; }}
 body {{ font-family:'Segoe UI', Arial, sans-serif; background:var(--bg); color:var(--ink); margin:0; padding:40px 16px; font-size:14px; }}
 .card {{ max-width:760px; margin:0 auto; background:#fff; border:1px solid var(--border); border-radius:12px;
          box-shadow:0 6px 20px rgba(0,78,116,0.10); overflow:hidden; }}
 .head {{ background:var(--navy-deep); color:#fff; padding:26px 48px; text-align:center; }}
 .logo {{ height:52px; margin-bottom:10px; }}
 .head h1 {{ margin:0; font-size:17px; letter-spacing:0.5px; }}
 .head p {{ margin:5px 0 0; font-size:12px; color:var(--teal); font-weight:600; text-transform:uppercase; letter-spacing:1px; }}
 .body {{ padding:0 48px 36px; }}
 .period-row {{ display:flex; justify-content:space-between; align-items:baseline;
                 padding:20px 0 16px; border-bottom:2px solid var(--navy); margin-bottom:20px; }}
 .period-row .label {{ font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:0.5px; }}
 .period-row .value {{ font-size:18px; font-weight:700; color:var(--navy); }}
 .period-row .gen {{ font-size:11px; color:var(--muted); text-align:right; }}
 h2.section {{ font-size:12px; text-transform:uppercase; letter-spacing:0.5px; color:var(--muted);
               margin:22px 0 8px; }}
 table {{ width:100%; border-collapse:collapse; }}
 .tbl {{ font-size:13px; border:1px solid var(--border); }}
 .tbl th {{ background:var(--bg); color:var(--muted); font-size:10.5px; text-transform:uppercase;
            letter-spacing:0.5px; text-align:left; padding:7px 9px; border-bottom:1px solid var(--border); }}
 .tbl th.amt {{ text-align:right; }}
 .tbl td {{ padding:7px 9px; border-bottom:1px solid var(--border); }}
 .tbl tr:last-child td {{ border-bottom:none; }}
 .muted {{ color:var(--muted); }}
 .amt {{ text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }}
 .totals {{ margin-top:6px; font-size:14px; }}
 .totals td {{ padding:6px 0; }}
 .totals tr.final td {{ padding-top:12px; border-top:2px solid var(--navy); font-weight:700; font-size:18px; }}
 .totals tr.final.positive td {{ color:var(--success); }}
 .totals tr.final.negative td {{ color:var(--danger); }}
 .signatures {{ display:flex; gap:32px; margin-top:44px; }}
 .sig-box {{ flex:1; text-align:center; }}
 .sig-line {{ height:36px; border-bottom:1px solid var(--ink); }}
 .sig-box span {{ display:block; margin-top:8px; font-size:11px; color:var(--muted); }}
 .foot {{ text-align:center; padding:0 48px 26px; }}
 button {{ background:var(--navy); color:#fff; border:none; border-radius:8px; padding:12px 28px;
           font-size:14px; font-weight:600; cursor:pointer; }}
 button:hover {{ background:var(--navy-deep); }}
 @media print {{ body {{ background:#fff; padding:0; }} .card {{ box-shadow:none; border:none; max-width:100%; }} .foot {{ display:none; }} }}
</style></head>
<body>
<div class="card">
  <div class="head">
    {logo_html}
    <h1>SOCIÉTÉ MAGASIN LES CINQ FRÈRES</h1>
    <p>Rapport {period_type.lower()}</p>
  </div>
  <div class="body">
    <div class="period-row">
      <div><div class="label">Période</div><div class="value">{period_label}</div></div>
      <div class="gen">Généré le<br>{datetime.now().strftime('%d/%m/%Y à %H:%M')}</div>
    </div>

    <h2 class="section">Détail par jour</h2>
    <table class="tbl">
      <thead><tr><th>Date</th><th class="amt">Recettes</th><th class="amt">Dépenses</th>
        <th class="amt">Versements</th><th class="amt">Solde final</th></tr></thead>
      <tbody>{day_rows}</tbody>
    </table>

    <h2 class="section">Dépenses par catégorie</h2>
    <table class="tbl">
      <thead><tr><th>Catégorie</th><th class="amt">Montant</th></tr></thead>
      <tbody>{cat_rows}</tbody>
    </table>

    <h2 class="section">Détail par motif (ex: par employé)</h2>
    <table class="tbl">
      <thead><tr><th>Motif</th><th class="amt">Nb</th><th class="amt">Montant total</th></tr></thead>
      <tbody>{motif_rows}</tbody>
    </table>

    <table class="totals">
     <tr><td>Solde en début de période</td><td class="amt">{solde_debut_txt}</td></tr>
     <tr><td>Total recettes</td><td class="amt">+ {fmt(stats['total_recettes'])}</td></tr>
     <tr><td>Total dépenses</td><td class="amt">- {fmt(stats['total_depenses'])}</td></tr>
     {"<tr><td>Total versements banque</td><td class='amt'>- " + fmt(stats['total_versements']) + "</td></tr>" if stats['total_versements'] else ""}
     <tr class="final {final_class}"><td>SOLDE EN FIN DE PÉRIODE</td><td class="amt">{solde_fin_txt}</td></tr>
    </table>

    <div class="signatures">
      <div class="sig-box"><div class="sig-line"></div><span>Signature responsable</span></div>
    </div>
  </div>
  <div class="foot"><button onclick="window.print()">🖨 Imprimer</button></div>
</div>
</body></html>"""
    path = os.path.join(EXPORTS_DIR, f"rapport_{filename_slug}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    webbrowser.open(f"file://{path}")


def export_weekly_report(monday_date):
    stats = week_stats(monday_date)
    end = stats["end"]
    try:
        d1 = datetime.strptime(monday_date, "%Y-%m-%d").strftime("%d/%m/%Y")
        d2 = datetime.strptime(end, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        d1, d2 = monday_date, end
    label = f"Semaine du {d1} au {d2}"
    export_period_report_html("Hebdomadaire", label, f"semaine_{monday_date}", stats)


def export_monthly_report(year, month):
    stats = month_stats_full(year, month)
    label = f"{FR_MOIS[month - 1]} {year}"
    export_period_report_html("Mensuel", label, f"mois_{year:04d}-{month:02d}", stats)


def export_yearly_report(year):
    """Rapport annuel imprimable : détail mois par mois (12 lignes, plus
    lisible à l'impression que 365 lignes journalières) + répartition par
    catégorie sur l'année entière."""
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    stats = year_stats_full(year)
    months = _group_days_by_month(stats["days"])

    if months:
        month_rows = "".join(
            f"<tr><td>{FR_MOIS[int(ym[5:7]) - 1]}</td><td class='amt'>{fmt(m['recettes'])}</td>"
            f"<td class='amt'>{fmt(m['depenses'])}</td><td class='amt'>{fmt(m['versements'])}</td>"
            f"<td class='amt' style='font-weight:700; color:{SUCCESS if m['final'] >= 0 else DANGER}'>{fmt(m['final'])}</td></tr>"
            for ym, m in sorted(months.items())
        )
    else:
        month_rows = "<tr><td colspan='5' class='muted' style='text-align:center'>Aucune journée enregistrée sur cette année</td></tr>"

    if stats["par_categorie"]:
        cat_rows = "".join(
            f"<tr><td>{html.escape(cat)}</td><td class='amt'>{fmt(montant)}</td></tr>"
            for cat, montant in sorted(stats["par_categorie"].items(), key=lambda x: -x[1])
        )
    else:
        cat_rows = "<tr><td colspan='2' class='muted' style='text-align:center'>Aucune dépense</td></tr>"

    if stats.get("par_motif"):
        motif_rows = "".join(
            f"<tr><td>{html.escape(m['label'])}</td><td class='amt'>{m['count']}</td>"
            f"<td class='amt'>{fmt(m['total'])}</td></tr>"
            for m in sorted(stats["par_motif"].values(), key=lambda x: -x["total"])
        )
    else:
        motif_rows = "<tr><td colspan='3' class='muted' style='text-align:center'>Aucun motif enregistré</td></tr>"

    solde_debut_txt = fmt(stats["solde_debut"]) if stats["solde_debut"] is not None else "—"
    solde_fin_txt = fmt(stats["solde_fin"]) if stats["solde_fin"] is not None else "—"
    final_class = "positive" if (stats["solde_fin"] or 0) >= 0 else "negative"
    logo_uri = _logo_data_uri()
    logo_html = f'<img src="{logo_uri}" alt="Les Cinq Frères" class="logo">' if logo_uri else ""

    content = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<title>Rapport annuel — {year}</title>
<style>
 :root {{
   --navy:#004E74; --navy-deep:#00354F; --teal:#08A4B0; --ink:#1F2A33;
   --muted:#5B6B79; --border:#DCE3E8; --success:#1B8A5A; --danger:#C1373B; --bg:#F4F6F8;
 }}
 * {{ box-sizing:border-box; }}
 body {{ font-family:'Segoe UI', Arial, sans-serif; background:var(--bg); color:var(--ink); margin:0; padding:40px 16px; font-size:14px; }}
 .card {{ max-width:760px; margin:0 auto; background:#fff; border:1px solid var(--border); border-radius:12px;
          box-shadow:0 6px 20px rgba(0,78,116,0.10); overflow:hidden; }}
 .head {{ background:var(--navy-deep); color:#fff; padding:26px 48px; text-align:center; }}
 .logo {{ height:52px; margin-bottom:10px; }}
 .head h1 {{ margin:0; font-size:17px; letter-spacing:0.5px; }}
 .head p {{ margin:5px 0 0; font-size:12px; color:var(--teal); font-weight:600; text-transform:uppercase; letter-spacing:1px; }}
 .body {{ padding:0 48px 36px; }}
 .period-row {{ display:flex; justify-content:space-between; align-items:baseline;
                 padding:20px 0 16px; border-bottom:2px solid var(--navy); margin-bottom:20px; }}
 .period-row .label {{ font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:0.5px; }}
 .period-row .value {{ font-size:18px; font-weight:700; color:var(--navy); }}
 .period-row .gen {{ font-size:11px; color:var(--muted); text-align:right; }}
 h2.section {{ font-size:12px; text-transform:uppercase; letter-spacing:0.5px; color:var(--muted);
               margin:22px 0 8px; }}
 table {{ width:100%; border-collapse:collapse; }}
 .tbl {{ font-size:13px; border:1px solid var(--border); }}
 .tbl th {{ background:var(--bg); color:var(--muted); font-size:10.5px; text-transform:uppercase;
            letter-spacing:0.5px; text-align:left; padding:7px 9px; border-bottom:1px solid var(--border); }}
 .tbl th.amt {{ text-align:right; }}
 .tbl td {{ padding:7px 9px; border-bottom:1px solid var(--border); }}
 .tbl tr:last-child td {{ border-bottom:none; }}
 .muted {{ color:var(--muted); }}
 .amt {{ text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }}
 .totals {{ margin-top:6px; font-size:14px; }}
 .totals td {{ padding:6px 0; }}
 .totals tr.final td {{ padding-top:12px; border-top:2px solid var(--navy); font-weight:700; font-size:18px; }}
 .totals tr.final.positive td {{ color:var(--success); }}
 .totals tr.final.negative td {{ color:var(--danger); }}
 .signatures {{ display:flex; gap:32px; margin-top:44px; }}
 .sig-box {{ flex:1; text-align:center; }}
 .sig-line {{ height:36px; border-bottom:1px solid var(--ink); }}
 .sig-box span {{ display:block; margin-top:8px; font-size:11px; color:var(--muted); }}
 .foot {{ text-align:center; padding:0 48px 26px; }}
 button {{ background:var(--navy); color:#fff; border:none; border-radius:8px; padding:12px 28px;
           font-size:14px; font-weight:600; cursor:pointer; }}
 button:hover {{ background:var(--navy-deep); }}
 @media print {{ body {{ background:#fff; padding:0; }} .card {{ box-shadow:none; border:none; max-width:100%; }} .foot {{ display:none; }} }}
</style></head>
<body>
<div class="card">
  <div class="head">
    {logo_html}
    <h1>SOCIÉTÉ MAGASIN LES CINQ FRÈRES</h1>
    <p>Rapport annuel</p>
  </div>
  <div class="body">
    <div class="period-row">
      <div><div class="label">Année</div><div class="value">{year}</div></div>
      <div class="gen">Généré le<br>{datetime.now().strftime('%d/%m/%Y à %H:%M')}</div>
    </div>

    <h2 class="section">Détail par mois</h2>
    <table class="tbl">
      <thead><tr><th>Mois</th><th class="amt">Recettes</th><th class="amt">Dépenses</th>
        <th class="amt">Versements</th><th class="amt">Solde fin de mois</th></tr></thead>
      <tbody>{month_rows}</tbody>
    </table>

    <h2 class="section">Dépenses par catégorie (année entière)</h2>
    <table class="tbl">
      <thead><tr><th>Catégorie</th><th class="amt">Montant</th></tr></thead>
      <tbody>{cat_rows}</tbody>
    </table>

    <h2 class="section">Détail par motif (ex: par employé) — année entière</h2>
    <table class="tbl">
      <thead><tr><th>Motif</th><th class="amt">Nb</th><th class="amt">Montant total</th></tr></thead>
      <tbody>{motif_rows}</tbody>
    </table>

    <table class="totals">
     <tr><td>Solde en début d'année</td><td class="amt">{solde_debut_txt}</td></tr>
     <tr><td>Total recettes</td><td class="amt">+ {fmt(stats['total_recettes'])}</td></tr>
     <tr><td>Total dépenses</td><td class="amt">- {fmt(stats['total_depenses'])}</td></tr>
     {"<tr><td>Total versements banque</td><td class='amt'>- " + fmt(stats['total_versements']) + "</td></tr>" if stats['total_versements'] else ""}
     <tr class="final {final_class}"><td>SOLDE EN FIN D'ANNÉE</td><td class="amt">{solde_fin_txt}</td></tr>
    </table>

    <div class="signatures">
      <div class="sig-box"><div class="sig-line"></div><span>Signature responsable</span></div>
      <div class="sig-box"><div class="sig-line"></div><span>Signature comptable</span></div>
    </div>
  </div>
  <div class="foot"><button onclick="window.print()">🖨 Imprimer</button></div>
</div>
</body></html>"""
    path = os.path.join(EXPORTS_DIR, f"rapport_annee_{year}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    webbrowser.open(f"file://{path}")


def export_yearly_csv(year):
    export_csv_report(str(year), f"annee_{year}", year_stats_full(year))


def _num_fr(value):
    """Nombre au format attendu par Excel en français (virgule décimale)."""
    return f"{value:.3f}".replace(".", ",")


def export_csv_report(period_label, filename_slug, stats):
    """Export CSV pour le comptable : résumé, répartition par catégorie et
    journal détaillé de tous les mouvements (recettes, dépenses, versements).
    Séparateur point-virgule / virgule décimale : format attendu par Excel FR."""
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    path = os.path.join(EXPORTS_DIR, f"export_{filename_slug}.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")

        w.writerow(["RÉSUMÉ DE LA PÉRIODE"])
        w.writerow(["Période", period_label])
        w.writerow(["Solde en début de période", _num_fr(stats["solde_debut"]) if stats["solde_debut"] is not None else ""])
        w.writerow(["Total recettes", _num_fr(stats["total_recettes"])])
        w.writerow(["Total dépenses", _num_fr(stats["total_depenses"])])
        w.writerow(["Total versements banque", _num_fr(stats["total_versements"])])
        w.writerow(["Solde en fin de période", _num_fr(stats["solde_fin"]) if stats["solde_fin"] is not None else ""])
        w.writerow([])

        w.writerow(["DÉPENSES PAR CATÉGORIE"])
        w.writerow(["Catégorie", "Montant"])
        for cat, montant in sorted(stats["par_categorie"].items(), key=lambda x: -x[1]):
            w.writerow([cat, _num_fr(montant)])
        w.writerow([])

        w.writerow(["DÉTAIL PAR MOTIF (EX: PAR EMPLOYÉ)"])
        w.writerow(["Motif", "Nombre", "Montant total"])
        for m in sorted(stats.get("par_motif", {}).values(), key=lambda x: -x["total"]):
            w.writerow([m["label"], m["count"], _num_fr(m["total"])])
        w.writerow([])

        w.writerow(["DÉTAIL JOUR PAR JOUR"])
        w.writerow(["Date", "Solde initial", "Recettes", "Dépenses", "Versements banque", "Solde final"])
        for d in stats["days"]:
            w.writerow([d["date"], _num_fr(d["solde_initial"]), _num_fr(d["recettes"]),
                        _num_fr(d["depenses"]), _num_fr(d["versements"]), _num_fr(d["final"])])
        w.writerow([])

        w.writerow(["JOURNAL DES MOUVEMENTS"])
        w.writerow(["Date", "Type", "Catégorie", "Motif", "Montant", "Justificatif"])
        for mv in stats["movements"]:
            w.writerow([mv["date"], mv["type"], mv["categorie"], mv["motif"],
                        _num_fr(mv["montant"]), "Oui" if mv["piece_jointe"] else ""])

    if os.name == "nt":
        os.startfile(path)
    else:
        webbrowser.open(f"file://{path}")
    return path


def export_weekly_csv(monday_date):
    stats = week_stats(monday_date)
    end = stats["end"]
    try:
        d1 = datetime.strptime(monday_date, "%Y-%m-%d").strftime("%d/%m/%Y")
        d2 = datetime.strptime(end, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        d1, d2 = monday_date, end
    export_csv_report(f"Semaine du {d1} au {d2}", f"semaine_{monday_date}", stats)


def export_monthly_csv(year, month):
    stats = month_stats_full(year, month)
    export_csv_report(f"{FR_MOIS[month - 1]} {year}", f"mois_{year:04d}-{month:02d}", stats)


# ---------------------------------------------------------------------------
# Calendrier mensuel (pur Tkinter — aucune dépendance), réutilisé à la fois
# dans le sélecteur de date en popup et dans la vue Historique.
# ---------------------------------------------------------------------------
def render_month_calendar(container, year, month, *, selected_date=None, marked_dates=None,
                            on_prev=None, on_next=None, on_pick=None, on_close=None, on_today=None):
    for w in container.winfo_children():
        w.destroy()
    marked_dates = marked_dates or set()
    today_str = datetime.now().strftime("%Y-%m-%d")

    header = tk.Frame(container, bg=NAVY_DEEP)
    header.pack(fill="x")
    prev_lbl = tk.Label(header, text="◀", bg=NAVY_DEEP, fg="white", font=("Segoe UI", 10, "bold"),
                          padx=12, pady=8, cursor="hand2")
    prev_lbl.pack(side="left")
    if on_prev:
        prev_lbl.bind("<Button-1>", lambda e: on_prev())
    tk.Label(header, text=f"{FR_MOIS[month - 1]} {year}", bg=NAVY_DEEP, fg="white",
              font=("Segoe UI", 10, "bold")).pack(side="left", expand=True)
    if on_close:
        close_lbl = tk.Label(header, text="✕", bg=NAVY_DEEP, fg="#A9C2CF", font=("Segoe UI", 9, "bold"),
                               padx=10, pady=8, cursor="hand2")
        close_lbl.pack(side="right")
        close_lbl.bind("<Button-1>", lambda e: on_close())
    next_lbl = tk.Label(header, text="▶", bg=NAVY_DEEP, fg="white", font=("Segoe UI", 10, "bold"),
                          padx=12, pady=8, cursor="hand2")
    next_lbl.pack(side="right")
    if on_next:
        next_lbl.bind("<Button-1>", lambda e: on_next())

    days_row = tk.Frame(container, bg=SURFACE)
    days_row.pack(fill="x", pady=(8, 2))
    for name in FR_JOURS:
        tk.Label(days_row, text=name, bg=SURFACE, fg=MUTED, font=("Segoe UI", 8, "bold"),
                  width=4).pack(side="left")

    grid = tk.Frame(container, bg=SURFACE)
    grid.pack(padx=6)
    for week in calendar_mod.Calendar(firstweekday=0).monthdayscalendar(year, month):
        row = tk.Frame(grid, bg=SURFACE)
        row.pack()
        for day in week:
            if day == 0:
                tk.Label(row, bg=SURFACE, width=4, height=2).pack(side="left")
                continue
            dstr = f"{year:04d}-{month:02d}-{day:02d}"
            is_selected = dstr == selected_date
            is_today = dstr == today_str
            has_entry = dstr in marked_dates
            bg = NAVY if is_selected else SURFACE
            if is_selected:
                fg = "white"
            elif has_entry:
                fg = TEAL_DARK
            elif is_today:
                fg = NAVY
            else:
                fg = INK
            lbl = tk.Label(row, text=str(day), bg=bg, fg=fg, width=4, height=2, cursor="hand2",
                            font=("Segoe UI", 9, "bold" if (is_selected or is_today or has_entry) else "normal"))
            lbl.pack(side="left", padx=1, pady=1)
            if on_pick:
                lbl.bind("<Button-1>", lambda e, dd=day: on_pick(f"{year:04d}-{month:02d}-{dd:02d}"))

    if on_today:
        foot = tk.Frame(container, bg=SURFACE)
        foot.pack(fill="x", pady=(2, 8))
        today_lbl = tk.Label(foot, text="Aujourd'hui", bg=SURFACE, fg=TEAL_DARK,
                              font=("Segoe UI", 8, "bold underline"), cursor="hand2")
        today_lbl.pack()
        today_lbl.bind("<Button-1>", lambda e: on_today())


class CalendarPopup(tk.Toplevel):
    def __init__(self, parent, initial_date, on_pick):
        super().__init__(parent)
        self.on_pick_final = on_pick
        self.overrideredirect(True)
        self.configure(bg=BORDER)

        try:
            y, m, _ = (int(p) for p in initial_date.split("-"))
            self.selected_date = initial_date
        except (ValueError, AttributeError):
            today = datetime.now()
            y, m = today.year, today.month
            self.selected_date = today.strftime("%Y-%m-%d")
        self.cur_year, self.cur_month = y, m

        self.card = tk.Frame(self, bg=SURFACE)
        self.card.pack(padx=1, pady=1)
        self._build()

        self.bind("<Escape>", lambda e: self.destroy())
        self.transient(parent)
        # Fenêtre sans bordure : on force son affichage au premier plan,
        # sinon elle peut se retrouver masquée derrière la fenêtre principale.
        self.lift()
        self.attributes("-topmost", True)
        try:
            self.focus_force()
        except tk.TclError:
            pass

    def _build(self):
        render_month_calendar(
            self.card, self.cur_year, self.cur_month,
            selected_date=self.selected_date,
            marked_dates=days_with_entries(self.cur_year, self.cur_month),
            on_prev=lambda: self._change_month(-1),
            on_next=lambda: self._change_month(1),
            on_pick=self._pick,
            on_close=self.destroy,
            on_today=self._pick_today,
        )

    def _change_month(self, delta):
        m = self.cur_month + delta
        y = self.cur_year
        if m < 1:
            m, y = 12, y - 1
        elif m > 12:
            m, y = 1, y + 1
        self.cur_year, self.cur_month = y, m
        self._build()

    def _pick(self, dstr):
        self.destroy()
        self.on_pick_final(dstr)

    def _pick_today(self):
        self._pick(datetime.now().strftime("%Y-%m-%d"))


# ---------------------------------------------------------------------------
# Fenêtres de connexion / configuration du mot de passe
#
# PasswordSetupDialog et LoginDialog sont de VRAIES fenêtres racines (tk.Tk),
# chacune pilotée par son propre mainloop() appelé depuis __main__ — et non
# des Toplevel affichés via wait_window() avant qu'un mainloop() ne tourne.
# Ce deuxième schéma (essayé d'abord) ne s'affichait pas de façon fiable.
# ---------------------------------------------------------------------------
def _auth_style(root):
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("TEntry", fieldbackground=SURFACE, foreground=INK,
                     bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=6)
    style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 8),
                     background=NAVY, foreground="white", borderwidth=0, relief="flat")
    style.map("Primary.TButton", background=[("active", NAVY_DEEP)])


def _auth_field(card, label, var, show=None):
    tk.Label(card, text=label, bg=SURFACE, fg=INK, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(8, 2))
    kwargs = {"show": show} if show else {}
    entry = ttk.Entry(card, textvariable=var, width=34, **kwargs)
    entry.pack(anchor="w")
    return entry


def _auth_center(win):
    win.update_idletasks()
    w, h = win.winfo_width(), win.winfo_height()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    win.geometry(f"+{(sw - w) // 2}+{(sh - h) // 3}")
    win.lift()
    win.focus_force()


class PasswordSetupDialog(tk.Tk):
    """Premier lancement : définir le mot de passe + la question de secours."""

    def __init__(self):
        super().__init__()
        self.result = False
        self.title("Configuration — Livre de Caisse")
        self.configure(bg=SURFACE)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        _auth_style(self)

        card = tk.Frame(self, bg=SURFACE, padx=28, pady=24)
        card.pack()
        tk.Label(card, text="🔒 Sécuriser l'application", bg=SURFACE, fg=NAVY,
                  font=("Segoe UI", 14, "bold")).pack(anchor="w")
        tk.Label(card, text="Définis un mot de passe pour protéger l'accès à la caisse.\n"
                             "La question de secours permet de le réinitialiser en cas d'oubli.",
                  bg=SURFACE, fg=MUTED, font=("Segoe UI", 9), wraplength=320, justify="left").pack(anchor="w", pady=(4, 0))

        self.var_pw1 = tk.StringVar()
        self.var_pw2 = tk.StringVar()
        self.var_question = tk.StringVar()
        self.var_answer = tk.StringVar()

        _auth_field(card, "Mot de passe", self.var_pw1, show="•")
        _auth_field(card, "Confirmer le mot de passe", self.var_pw2, show="•")
        _auth_field(card, "Question de secours (ex: Nom du premier employé ?)", self.var_question)
        _auth_field(card, "Réponse", self.var_answer)

        ttk.Button(card, text="Valider", style="Primary.TButton",
                    command=self._on_validate).pack(anchor="w", pady=(18, 0))

        _auth_center(self)

    def _on_validate(self):
        pw1, pw2 = self.var_pw1.get(), self.var_pw2.get()
        question, answer = self.var_question.get().strip(), self.var_answer.get().strip()
        if len(pw1) < 4:
            messagebox.showwarning("Mot de passe trop court", "Au moins 4 caractères.", parent=self)
            return
        if pw1 != pw2:
            messagebox.showwarning("Erreur", "Les deux mots de passe ne correspondent pas.", parent=self)
            return
        if not question or not answer:
            messagebox.showwarning("Champ manquant", "Merci de renseigner la question et la réponse de secours.", parent=self)
            return
        set_password(pw1, question, answer)
        self.result = True
        self.destroy()

    def _on_cancel(self):
        self.result = False
        self.destroy()


class ResetPasswordDialog(tk.Toplevel):
    """Réinitialisation via la question de secours (mot de passe oublié),
    ouverte depuis une fenêtre de connexion déjà affichée (mainloop actif)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.result = False
        self.title("Mot de passe oublié")
        self.configure(bg=SURFACE)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        card = tk.Frame(self, bg=SURFACE, padx=28, pady=24)
        card.pack()
        tk.Label(card, text="Réinitialiser le mot de passe", bg=SURFACE, fg=NAVY,
                  font=("Segoe UI", 12, "bold")).pack(anchor="w")

        question = get_security_question() or "(aucune question de secours n'a été définie)"
        tk.Label(card, text=question, bg=SURFACE, fg=INK, font=("Segoe UI", 9, "bold"),
                  wraplength=320, justify="left").pack(anchor="w", pady=(10, 0))
        self.var_answer = tk.StringVar()
        _auth_field(card, "Réponse", self.var_answer)

        self.var_pw1 = tk.StringVar()
        self.var_pw2 = tk.StringVar()
        _auth_field(card, "Nouveau mot de passe", self.var_pw1, show="•")
        _auth_field(card, "Confirmer", self.var_pw2, show="•")

        ttk.Button(card, text="Réinitialiser", style="Primary.TButton",
                    command=self._on_validate).pack(anchor="w", pady=(18, 0))

        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 3}")
        self.transient(parent)
        self.lift()
        self.attributes("-topmost", True)
        self.after(200, lambda: self.attributes("-topmost", False))
        self.focus_force()
        self.grab_set()
        self.wait_window(self)

    def _on_validate(self):
        if not check_security_answer(self.var_answer.get()):
            messagebox.showerror("Réponse incorrecte", "Cette réponse ne correspond pas.", parent=self)
            return
        pw1, pw2 = self.var_pw1.get(), self.var_pw2.get()
        if len(pw1) < 4:
            messagebox.showwarning("Mot de passe trop court", "Au moins 4 caractères.", parent=self)
            return
        if pw1 != pw2:
            messagebox.showwarning("Erreur", "Les deux mots de passe ne correspondent pas.", parent=self)
            return
        salt, h = _hash_secret(pw1)
        set_config("password_salt", salt)
        set_config("password_hash", h)
        messagebox.showinfo("Mot de passe réinitialisé", "Tu peux maintenant te reconnecter.", parent=self)
        self.result = True
        self.destroy()


class LoginDialog(tk.Tk):
    def __init__(self):
        super().__init__()
        self.result = False
        self.title("Connexion — Livre de Caisse")
        self.configure(bg=SURFACE)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        _auth_style(self)

        card = tk.Frame(self, bg=SURFACE, padx=28, pady=24)
        card.pack()

        logo_path = os.path.join(ASSETS_DIR, "logo_header.png")
        if os.path.exists(logo_path):
            self._logo_img = tk.PhotoImage(file=logo_path)
            tk.Label(card, image=self._logo_img, bg=SURFACE).pack(pady=(0, 8))

        tk.Label(card, text="SOCIÉTÉ MAGASIN LES CINQ FRÈRES", bg=SURFACE, fg=NAVY,
                  font=("Segoe UI", 12, "bold")).pack()
        tk.Label(card, text="Entre le mot de passe pour continuer", bg=SURFACE, fg=MUTED,
                  font=("Segoe UI", 9)).pack(pady=(2, 14))

        self.var_pw = tk.StringVar()
        entry = _auth_field(card, "Mot de passe", self.var_pw, show="•")
        entry.bind("<Return>", lambda ev: self._on_validate())

        self.lbl_error = tk.Label(card, text="", bg=SURFACE, fg=DANGER, font=("Segoe UI", 8, "bold"))
        self.lbl_error.pack(pady=(6, 0))

        ttk.Button(card, text="Se connecter", style="Primary.TButton",
                    command=self._on_validate).pack(anchor="w", pady=(14, 0))

        forgot = tk.Label(card, text="Mot de passe oublié ?", bg=SURFACE, fg=TEAL_DARK,
                            font=("Segoe UI", 8, "underline"), cursor="hand2")
        forgot.pack(pady=(10, 0))
        forgot.bind("<Button-1>", lambda ev: self._on_forgot())

        _auth_center(self)
        entry.focus_set()

    def _on_validate(self):
        if check_password(self.var_pw.get()):
            self.result = True
            self.destroy()
        else:
            self.lbl_error.config(text="Mot de passe incorrect.", fg=DANGER)
            self.var_pw.set("")

    def _on_forgot(self):
        if ResetPasswordDialog(self).result:
            self.lbl_error.config(text="Mot de passe réinitialisé — reconnecte-toi.", fg=SUCCESS)

    def _on_cancel(self):
        self.result = False
        self.destroy()


class LockWarningDialog(tk.Tk):
    """Affichée avant l'ouverture de la caisse si un autre poste (partage
    cloud type OneDrive) l'a utilisée très récemment, pour éviter d'écraser
    ses saisies en travaillant en même temps sur le même jour."""

    def __init__(self, lock_info):
        super().__init__()
        self.result = False
        self.title("Attention — Livre de Caisse")
        self.configure(bg=SURFACE)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        _auth_style(self)

        card = tk.Frame(self, bg=SURFACE, padx=28, pady=24)
        card.pack()
        tk.Label(card, text="⚠️ Caisse peut-être en cours d'utilisation", bg=SURFACE, fg=DANGER,
                  font=("Segoe UI", 12, "bold"), wraplength=360, justify="left").pack(anchor="w")

        msg = (f"Le poste « {lock_info['machine']} » a utilisé cette caisse à "
               f"{lock_info['heartbeat_at']} (il y a moins de 5 minutes).\n\n"
               "Si cette personne a encore l'application ouverte en ce moment et que "
               "vous enregistrez chacun une journée en même temps, l'un de vous risque "
               "d'effacer les saisies de l'autre.\n\n"
               "Vérifie avec elle avant de continuer, ou attends quelques minutes.")
        tk.Label(card, text=msg, bg=SURFACE, fg=INK, font=("Segoe UI", 9),
                  wraplength=360, justify="left").pack(anchor="w", pady=(10, 0))

        btns = tk.Frame(card, bg=SURFACE)
        btns.pack(anchor="w", pady=(18, 0))
        ttk.Button(btns, text="Continuer quand même", style="Primary.TButton",
                    command=self._on_continue).pack(side="left")
        tk.Button(btns, text="Quitter", command=self._on_cancel,
                   bg=SURFACE, fg=MUTED, relief="flat", font=("Segoe UI", 9, "underline"),
                   cursor="hand2").pack(side="left", padx=(14, 0))

        _auth_center(self)

    def _on_continue(self):
        self.result = True
        self.destroy()

    def _on_cancel(self):
        self.result = False
        self.destroy()


# ---------------------------------------------------------------------------
# Interface graphique
# ---------------------------------------------------------------------------
class CaisseApp(tk.Tk):
    def __init__(self, current_machine=None):
        super().__init__()
        self.title("Société Magasin Les Cinq Frères — Livre de Caisse")
        self.geometry("920x620")
        self.configure(bg=BG)
        self.machine_name = current_machine or machine_name()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.expenses = []  # dépenses de la journée en cours de saisie

        self._build_style()
        self._load_icon_images()
        self._build_header()

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=14, pady=10)

        self.tab_saisie = ttk.Frame(self.notebook, style="Paper.TFrame")
        self.tab_hist = ttk.Frame(self.notebook, style="Paper.TFrame")
        self.tab_dash = ttk.Frame(self.notebook, style="Paper.TFrame")
        self.notebook.add(self.tab_saisie, text="  Saisie du jour  ")
        self.notebook.add(self.tab_hist, text="  Historique  ")
        self.notebook.add(self.tab_dash, text="  Tableau de bord  ")

        self._build_saisie_tab()
        self._build_historique_tab()
        self._build_dashboard_tab()

        self.notebook.bind("<<NotebookTabChanged>>", lambda e: self._refresh_all())
        self._new_day(datetime.now().strftime("%Y-%m-%d"))
        self._heartbeat_loop()

    def _heartbeat_loop(self):
        # Signale que ce poste utilise la caisse en ce moment (utile quand
        # caisse.db est partagé entre plusieurs ordinateurs via un dossier
        # cloud) — répété toutes les 45s tant que l'application est ouverte.
        touch_lock(self.machine_name)
        self.after(45000, self._heartbeat_loop)

    def _on_close(self):
        release_lock(self.machine_name)
        self.destroy()

    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Paper.TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=INK, font=("Segoe UI", 10))
        style.configure("Header.TLabel", background=NAVY_DEEP, foreground="white", font=("Segoe UI", 15, "bold"))
        style.configure("Cat.TLabel", background=BG, foreground=TEAL_DARK, font=("Segoe UI", 9, "bold"))

        # Boutons
        style.configure("TButton", font=("Segoe UI", 10, "bold"), padding=(14, 8),
                         background=SURFACE, foreground=NAVY, borderwidth=1, relief="flat")
        style.map("TButton",
                   background=[("active", BORDER)],
                   bordercolor=[("!disabled", BORDER)])
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 8),
                         background=NAVY, foreground="white", borderwidth=0, relief="flat")
        style.map("Primary.TButton", background=[("active", NAVY_DEEP)])
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 8),
                         background=TEAL, foreground="white", borderwidth=0, relief="flat")
        style.map("Accent.TButton", background=[("active", TEAL_DARK)])

        # Champs de saisie
        style.configure("TEntry", fieldbackground=SURFACE, foreground=INK,
                         bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=6)
        style.configure("TCombobox", fieldbackground=SURFACE, background=SURFACE, foreground=INK, padding=6)

        # Tableaux
        style.configure("Treeview", font=("Segoe UI", 10), rowheight=26,
                         background=SURFACE, fieldbackground=SURFACE, foreground=INK, borderwidth=0)
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"),
                         background=NAVY, foreground="white", relief="flat", padding=6)
        style.map("Treeview.Heading", background=[("active", NAVY)])
        style.map("Treeview", background=[("selected", TEAL)], foreground=[("selected", "white")])

        # Onglets
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", font=("Segoe UI", 10, "bold"), background=BORDER,
                         foreground=INK, padding=(18, 10), borderwidth=0)
        style.map("TNotebook.Tab",
                   background=[("selected", NAVY)],
                   foreground=[("selected", "white")])

    def _load_icon_images(self):
        sizes = (16, 32, 48, 64, 128)
        self._icon_imgs = []
        for size in sizes:
            path = os.path.join(ASSETS_DIR, f"icon_{size}.png")
            if os.path.exists(path):
                self._icon_imgs.append(tk.PhotoImage(file=path))
        if self._icon_imgs:
            self.iconphoto(True, *self._icon_imgs)

    def _build_header(self):
        header = tk.Frame(self, bg=NAVY_DEEP, height=68)
        header.pack(fill="x")
        header.pack_propagate(False)

        left = tk.Frame(header, bg=NAVY_DEEP)
        left.pack(side="left", padx=18, pady=10)

        logo_path = os.path.join(ASSETS_DIR, "logo_header.png")
        if os.path.exists(logo_path):
            self._logo_img = tk.PhotoImage(file=logo_path)
            tk.Label(left, image=self._logo_img, bg=NAVY_DEEP).pack(side="left", padx=(0, 12))

        titles = tk.Frame(left, bg=NAVY_DEEP)
        titles.pack(side="left")
        tk.Label(titles, text="SOCIÉTÉ MAGASIN LES CINQ FRÈRES", bg=NAVY_DEEP, fg="white",
                  font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(titles, text="Livre de Caisse", bg=NAVY_DEEP, fg=TEAL,
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")

        tk.Label(header, text="Application locale — aucune donnée en ligne", bg=NAVY_DEEP, fg="#A9C2CF",
                  font=("Segoe UI", 9), padx=18).pack(side="right")

    # ----- Saisie du jour -------------------------------------------------
    def _build_saisie_tab(self):
        f = self.tab_saisie

        self.lbl_month_title = tk.Label(f, text="", bg=BG, fg=NAVY, font=("Segoe UI", 13, "bold"),
                                          anchor="w", padx=16)
        self.lbl_month_title.pack(fill="x", pady=(12, 0))

        top = ttk.Frame(f, style="Paper.TFrame")
        top.pack(fill="x", padx=16, pady=(4, 8))

        ttk.Label(top, text="Date", style="Cat.TLabel").grid(row=0, column=0, sticky="w")
        date_box = ttk.Frame(top, style="Paper.TFrame")
        date_box.grid(row=1, column=0, sticky="w", padx=(0, 20))
        self.var_date = tk.StringVar()
        e_date = ttk.Entry(date_box, textvariable=self.var_date, width=13, state="readonly")
        e_date.pack(side="left")
        self.btn_calendar = ttk.Button(date_box, text="📅", width=3, command=self._show_calendar)
        self.btn_calendar.pack(side="left", padx=(4, 0))

        self.lbl_solde_caption = ttk.Label(top, text="Solde initial", style="Cat.TLabel")
        self.lbl_solde_caption.grid(row=0, column=1, sticky="w")
        self.var_solde = tk.StringVar(value="0")
        self.e_solde = ttk.Entry(top, textvariable=self.var_solde, width=14)
        self.e_solde.grid(row=1, column=1, sticky="w", padx=(0, 20))

        ttk.Label(top, text="Recettes du jour", style="Cat.TLabel").grid(row=0, column=2, sticky="w")
        self.var_recettes = tk.StringVar(value="0")
        self.e_recettes = ttk.Entry(top, textvariable=self.var_recettes, width=14)
        self.e_recettes.grid(row=1, column=2, sticky="w")
        self.var_recettes.trace_add("write", lambda *a: self._refresh_summary())
        self.var_solde.trace_add("write", lambda *a: self._refresh_summary())

        # Bandeau de verrouillage (jours passés)
        self.lock_bar = tk.Frame(f, bg="#FBEFD9")
        self.lbl_lock = tk.Label(self.lock_bar, text="🔒 Journée déjà passée — verrouillée pour éviter les modifications accidentelles.",
                                   bg="#FBEFD9", fg="#7A5A1E", font=("Segoe UI", 9, "bold"), padx=14, pady=8)
        self.lbl_lock.pack(side="left")
        ttk.Button(self.lock_bar, text="🔓 Déverrouiller pour corriger",
                    command=self._unlock_day).pack(side="right", padx=14, pady=6)
        # (empaqueté/masqué dynamiquement par _apply_lock_state)

        # Ajout dépense
        self.add_frame = add_frame = ttk.Frame(f, style="Paper.TFrame")
        add_frame.pack(fill="x", padx=16, pady=8)
        ttk.Label(add_frame, text="Motif", style="Cat.TLabel").grid(row=0, column=0, sticky="w")
        self.var_motif = tk.StringVar()
        self.e_motif = ttk.Entry(add_frame, textvariable=self.var_motif, width=28)
        self.e_motif.grid(row=1, column=0, padx=(0, 10))

        cat_head = ttk.Frame(add_frame, style="Paper.TFrame")
        cat_head.grid(row=0, column=1, sticky="ew")
        ttk.Label(cat_head, text="Catégorie", style="Cat.TLabel").pack(side="left")
        gear = tk.Label(cat_head, text="⚙", bg=BG, fg=TEAL_DARK, font=("Segoe UI", 9, "bold"), cursor="hand2")
        gear.pack(side="left", padx=(6, 0))
        gear.bind("<Button-1>", lambda e: self._manage_categories())
        self.var_cat = tk.StringVar(value=get_categories()[0])
        self.cb_categorie = ttk.Combobox(add_frame, textvariable=self.var_cat, values=get_categories(), width=22, state="readonly")
        self.cb_categorie.grid(row=1, column=1, padx=(0, 10))

        ttk.Label(add_frame, text="Montant", style="Cat.TLabel").grid(row=0, column=2, sticky="w")
        self.var_montant = tk.StringVar()
        e_montant = ttk.Entry(add_frame, textvariable=self.var_montant, width=12)
        e_montant.grid(row=1, column=2, padx=(0, 10))
        e_montant.bind("<Return>", lambda e: self.btn_add_expense.invoke())
        self.e_montant = e_montant

        self._editing_idx = None
        self.btn_add_expense = ttk.Button(add_frame, text="+ Ajouter", style="Primary.TButton",
                                            command=self._add_expense)
        self.btn_add_expense.grid(row=1, column=3, padx=(0, 6))
        self.btn_cancel_edit = ttk.Button(add_frame, text="✕ Annuler", command=self._cancel_edit)
        self.btn_cancel_edit.grid(row=1, column=4, padx=(0, 20))
        self.btn_cancel_edit.grid_remove()

        ttk.Label(add_frame, text="Justificatif", style="Cat.TLabel").grid(row=0, column=5, sticky="w")
        attach_box = ttk.Frame(add_frame, style="Paper.TFrame")
        attach_box.grid(row=1, column=5, sticky="w")
        self._pending_attachment = None
        self.btn_attach = ttk.Button(attach_box, text="📎 Joindre", command=self._pick_attachment)
        self.btn_attach.pack(side="left")
        self.lbl_attachment = tk.Label(attach_box, text="aucun fichier", bg=BG, fg=MUTED,
                                        font=("Segoe UI", 8, "italic"))
        self.lbl_attachment.pack(side="left", padx=(8, 0))

        # Liste des dépenses — tableau structuré : Désignation | Montant
        self.selected_expense_idx = None
        self._expense_row_widgets = []

        card = tk.Frame(f, bg=BORDER)
        card.pack(fill="both", expand=True, padx=16, pady=8)
        inner = tk.Frame(card, bg=SURFACE)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        head = tk.Frame(inner, bg=BG)
        head.pack(fill="x")
        head.columnconfigure(0, weight=1)
        tk.Label(head, text="DÉSIGNATION", bg=BG, fg=MUTED, font=("Segoe UI", 9, "bold"),
                  anchor="w", padx=14, pady=9).grid(row=0, column=0, sticky="ew")
        tk.Label(head, text="", bg=BG, width=3).grid(row=0, column=1)
        tk.Label(head, text="MONTANT", bg=BG, fg=MUTED, font=("Segoe UI", 9, "bold"),
                  anchor="e", padx=14, pady=9, width=16).grid(row=0, column=2, sticky="e")
        tk.Frame(inner, bg=BORDER, height=2).pack(fill="x")

        rows_area = tk.Frame(inner, bg=SURFACE)
        rows_area.pack(fill="both", expand=True)
        self.dep_canvas = tk.Canvas(rows_area, bg=SURFACE, highlightthickness=0, height=230, takefocus=1)
        vsb = ttk.Scrollbar(rows_area, orient="vertical", command=self.dep_canvas.yview)
        self.dep_canvas.configure(yscrollcommand=vsb.set)
        self.dep_canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.dep_rows_frame = tk.Frame(self.dep_canvas, bg=SURFACE)
        self._dep_canvas_window = self.dep_canvas.create_window((0, 0), window=self.dep_rows_frame, anchor="nw")
        self.dep_rows_frame.bind("<Configure>", lambda e: self.dep_canvas.configure(scrollregion=self.dep_canvas.bbox("all")))
        self.dep_canvas.bind("<Configure>", lambda e: self.dep_canvas.itemconfig(self._dep_canvas_window, width=e.width))
        self.dep_canvas.bind("<Button-1>", lambda e: self.dep_canvas.focus_set())
        self.dep_canvas.bind("<Delete>", lambda e: self._remove_selected_expense())

        row_actions = ttk.Frame(f, style="Paper.TFrame")
        row_actions.pack(fill="x", padx=16)
        self.btn_edit_selected = ttk.Button(row_actions, text="✏️ Modifier la dépense sélectionnée",
                                              command=self._edit_selected_expense)
        self.btn_edit_selected.pack(side="left", padx=(0, 10))
        self.btn_remove_selected = ttk.Button(row_actions, text="Supprimer la dépense sélectionnée",
                                                command=self._remove_selected_expense)
        self.btn_remove_selected.pack(side="left")

        # Résumé
        summary = tk.Frame(f, bg=NAVY_DEEP)
        summary.pack(fill="x", padx=16, pady=12)
        self.txt_summary = tk.Text(summary, bg=NAVY_DEEP, fg="white", font=("Consolas", 12),
                                    relief="flat", height=5, width=44, padx=16, pady=10,
                                    highlightthickness=0, borderwidth=0, cursor="arrow")
        self.txt_summary.tag_configure("muted", foreground="#B9D2DB")
        self.txt_summary.tag_configure("positive", foreground=SUCCESS, font=("Consolas", 13, "bold"))
        self.txt_summary.tag_configure("negative", foreground="#FF8A80", font=("Consolas", 13, "bold"))
        self.txt_summary.configure(state="disabled")
        self.txt_summary.pack(anchor="w")

        actions = ttk.Frame(f, style="Paper.TFrame")
        actions.pack(fill="x", padx=16, pady=(0, 16))
        self.btn_save_day = ttk.Button(actions, text="💾 Enregistrer la journée", style="Primary.TButton",
                                         command=self._save_day)
        self.btn_save_day.pack(side="left", padx=(0, 10))
        ttk.Button(actions, text="🖨 Imprimer / Exporter", style="Accent.TButton",
                    command=self._print_current).pack(side="left")

    def _show_calendar(self):
        if getattr(self, "_calendar_popup", None) is not None:
            try:
                self._calendar_popup.destroy()
            except tk.TclError:
                pass
            self._calendar_popup = None
            return

        popup = CalendarPopup(self, self.var_date.get(), self._on_date_picked)
        self._calendar_popup = popup
        popup.bind("<Destroy>", self._on_calendar_closed, add="+")

        self.update_idletasks()
        x = self.btn_calendar.winfo_rootx()
        y = self.btn_calendar.winfo_rooty() + self.btn_calendar.winfo_height() + 2
        popup.update_idletasks()
        pw, ph = popup.winfo_reqwidth(), popup.winfo_reqheight()
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        x = max(0, min(x, screen_w - pw))
        y = max(0, min(y, screen_h - ph))
        popup.geometry(f"+{x}+{y}")

    def _on_calendar_closed(self, event):
        if event.widget is self._calendar_popup:
            self._calendar_popup = None

    def _on_date_picked(self, jour_date):
        self._new_day(jour_date)

    def _new_day(self, jour_date):
        self.var_date.set(jour_date)
        try:
            y, m, _ = (int(p) for p in jour_date.split("-"))
            self.lbl_month_title.config(text=f"🗓  CAISSE — {FR_MOIS[m - 1].upper()} {y}")
        except (ValueError, IndexError):
            self.lbl_month_title.config(text="")

        prev = last_day_before(jour_date)
        # Un nouveau mois commence dès que le jour précédent enregistré
        # appartient à un mois différent (ou qu'il n'y a pas de jour précédent) :
        # c'est à ce moment-là qu'on saisit le solde de départ du mois.
        is_month_start = prev is None or prev["date"][:7] != jour_date[:7]

        existing = load_jour(jour_date)
        if existing:
            self.var_recettes.set(str(existing["recettes"]))
            self.expenses = list(existing["expenses"])
        else:
            self.var_recettes.set("0")
            self.expenses = []

        if is_month_start:
            # Début de mois : solde saisi à la main (celui déjà enregistré s'il
            # y en a un, sinon 0 par défaut).
            self.lbl_solde_caption.config(text="Solde de départ du mois")
            self.var_solde.set(str(existing["solde_initial"]) if existing else "0")
            self.e_solde.configure(state="normal")
        else:
            # En cours de mois : toujours repris automatiquement du montant
            # final de la veille, non modifiable à la main.
            self.lbl_solde_caption.config(text="Solde initial (jour précédent)")
            self.var_solde.set(str(round(prev["final"], 3)))
            self.e_solde.configure(state="readonly")

        self.selected_expense_idx = None
        self._cancel_edit()
        self._refresh_expense_list()
        self._refresh_summary()

        # Une journée déjà passée est verrouillée par défaut (protection contre
        # les modifications accidentelles a posteriori) ; aujourd'hui reste
        # toujours librement modifiable.
        self._is_locked_day = jour_date != datetime.now().strftime("%Y-%m-%d")
        self._day_unlocked = False
        self._apply_lock_state()

    def _apply_lock_state(self):
        locked = self._is_locked_day and not self._day_unlocked
        if locked:
            self.lock_bar.pack(fill="x", padx=16, pady=(0, 8), before=self.add_frame)
        else:
            self.lock_bar.pack_forget()

        state = "disabled" if locked else "normal"
        combo_state = "disabled" if locked else "readonly"
        self.e_recettes.configure(state=state)
        self.e_motif.configure(state=state)
        self.e_montant.configure(state=state)
        self.cb_categorie.configure(state=combo_state)
        self.btn_attach.configure(state=state)
        self.btn_add_expense.configure(state=state)
        self.btn_edit_selected.configure(state=state)
        self.btn_remove_selected.configure(state=state)
        self.btn_save_day.configure(state=state)
        # Le solde initial garde sa propre règle (lecture seule hors début de
        # mois) : on ne le réactive jamais ici s'il était déjà readonly.
        if locked:
            self.e_solde.configure(state="disabled")
        else:
            self._new_day_solde_state_refresh()

    def _new_day_solde_state_refresh(self):
        """Réapplique l'état normal/lecture-seule du solde initial (logique
        de début de mois) après un déverrouillage."""
        prev = last_day_before(self.var_date.get())
        is_month_start = prev is None or prev["date"][:7] != self.var_date.get()[:7]
        self.e_solde.configure(state="normal" if is_month_start else "readonly")

    def _unlock_day(self):
        pw = simpledialog.askstring("Confirmation requise",
                                     "Mot de passe de l'application :", show="•", parent=self)
        if pw is None:
            return
        if not check_password(pw):
            messagebox.showerror("Mot de passe incorrect", "Impossible de déverrouiller cette journée.")
            return
        self._day_unlocked = True
        self._apply_lock_state()

    def _locked(self):
        return getattr(self, "_is_locked_day", False) and not getattr(self, "_day_unlocked", False)

    def _pick_attachment(self):
        if self._locked():
            return
        path = filedialog.askopenfilename(title="Choisir un justificatif (photo ou PDF)",
                                           filetypes=ATTACHMENT_FILETYPES)
        if not path:
            return
        self._pending_attachment = save_attachment(path)
        self.lbl_attachment.config(text=f"✓ {os.path.basename(path)}", fg=SUCCESS)

    def _add_expense(self):
        if self._locked():
            return
        motif = self.var_motif.get().strip()
        try:
            montant = parse_amount(self.var_montant.get())
        except ValueError:
            montant = 0
        if not motif or montant <= 0:
            messagebox.showwarning("Champ manquant", "Merci d'indiquer un motif et un montant valide.")
            return
        self.expenses.append({"motif": motif, "categorie": self.var_cat.get(), "montant": montant,
                               "piece_jointe": self._pending_attachment})
        self._pending_attachment = None
        self.lbl_attachment.config(text="aucun fichier", fg=MUTED)
        self.var_motif.set("")
        self.var_montant.set("")
        self._refresh_expense_list()
        self._refresh_summary()

    def _select_expense_row(self, idx):
        self.selected_expense_idx = idx
        self._highlight_selected_row()
        self.dep_canvas.focus_set()

    def _remove_selected_expense(self):
        if self._locked():
            return
        idx = self.selected_expense_idx
        if idx is None or idx >= len(self.expenses):
            return
        if idx == self._editing_idx:
            self._cancel_edit()
        del self.expenses[idx]
        self.selected_expense_idx = None
        self._refresh_expense_list()
        self._refresh_summary()

    def _edit_selected_expense(self):
        idx = self.selected_expense_idx
        if idx is None or idx >= len(self.expenses):
            messagebox.showinfo("Aucune sélection", "Sélectionnez d'abord une dépense dans le tableau.")
            return
        self._enter_edit_mode(idx)

    def _enter_edit_mode(self, idx):
        if self._locked():
            return
        e = self.expenses[idx]
        self._editing_idx = idx
        self.var_motif.set(e["motif"])
        self.var_cat.set(e["categorie"])
        self.var_montant.set(str(e["montant"]))
        self._pending_attachment = e.get("piece_jointe")
        if self._pending_attachment:
            self.lbl_attachment.config(text="✓ Justificatif joint", fg=SUCCESS)
        else:
            self.lbl_attachment.config(text="aucun fichier", fg=MUTED)
        self.btn_add_expense.config(text="✔ Enregistrer la modification", command=self._save_expense_edit)
        self.btn_cancel_edit.grid()
        self._select_expense_row(idx)

    def _cancel_edit(self):
        self._editing_idx = None
        self.var_motif.set("")
        self.var_cat.set(get_categories()[0])
        self.var_montant.set("")
        self._pending_attachment = None
        self.lbl_attachment.config(text="aucun fichier", fg=MUTED)
        self.btn_add_expense.config(text="+ Ajouter", command=self._add_expense)
        self.btn_cancel_edit.grid_remove()

    def _manage_categories(self):
        # Fenêtre sans bordure système : formule fiable retenue après le bug
        # d'affichage rencontré avec les Toplevel décorées classiques.
        win = tk.Toplevel(self)
        win.overrideredirect(True)
        win.configure(bg=BORDER)

        card = tk.Frame(win, bg=SURFACE)
        card.pack(padx=1, pady=1)

        header = tk.Frame(card, bg=NAVY_DEEP)
        header.pack(fill="x")
        tk.Label(header, text="Gérer les catégories", bg=NAVY_DEEP, fg="white",
                  font=("Segoe UI", 11, "bold"), padx=14, pady=10).pack(side="left")
        close_lbl = tk.Label(header, text="✕", bg=NAVY_DEEP, fg="#A9C2CF", font=("Segoe UI", 10, "bold"),
                               padx=12, pady=10, cursor="hand2")
        close_lbl.pack(side="right")
        close_lbl.bind("<Button-1>", lambda e: win.destroy())

        tk.Label(card, text="Double-clique un nom pour le renommer. « Versement banque » est fixe.",
                  bg=SURFACE, fg=MUTED, font=("Segoe UI", 9), anchor="w", padx=16, wraplength=320,
                  justify="left").pack(fill="x", pady=(10, 6))

        rows_frame = tk.Frame(card, bg=SURFACE)
        rows_frame.pack(fill="x", padx=16)

        def refresh_rows():
            for w in rows_frame.winfo_children():
                w.destroy()
            for cat in get_categories():
                row = tk.Frame(rows_frame, bg=SURFACE)
                row.pack(fill="x", pady=2)
                lbl = tk.Label(row, text=cat, bg=SURFACE, fg=INK, font=("Segoe UI", 10),
                                anchor="w", cursor="hand2" if cat != CATEGORIE_VERSEMENT else "arrow")
                lbl.pack(side="left", fill="x", expand=True)
                if cat == CATEGORIE_VERSEMENT:
                    tk.Label(row, text="🔒", bg=SURFACE, fg=MUTED, font=("Segoe UI", 9)).pack(side="right")
                else:
                    lbl.bind("<Double-Button-1>", lambda e, c=cat: rename_cat(c))
                    del_lbl = tk.Label(row, text="✕", bg=SURFACE, fg=DANGER, font=("Segoe UI", 9, "bold"), cursor="hand2")
                    del_lbl.pack(side="right")
                    del_lbl.bind("<Button-1>", lambda e, c=cat: delete_cat(c))

        def rename_cat(old_name):
            new_name = simpledialog.askstring("Renommer la catégorie", "Nouveau nom :",
                                                initialvalue=old_name, parent=win)
            if not new_name or not new_name.strip() or new_name.strip() == old_name:
                return
            cats = get_categories()
            cats = [new_name.strip() if c == old_name else c for c in cats]
            set_categories(cats)
            refresh_rows()
            self._sync_categories()

        def delete_cat(name):
            if messagebox.askyesno("Supprimer la catégorie",
                                     f"Supprimer « {name} » ? Les dépenses déjà enregistrées avec "
                                     "cette catégorie garderont leur nom d'origine.", parent=win):
                cats = [c for c in get_categories() if c != name]
                set_categories(cats)
                refresh_rows()
                self._sync_categories()

        def add_cat():
            name = var_new.get().strip()
            if not name:
                return
            cats = get_categories()
            if name in cats:
                messagebox.showinfo("Déjà existante", "Cette catégorie existe déjà.", parent=win)
                return
            cats.append(name)
            set_categories(cats)
            var_new.set("")
            refresh_rows()
            self._sync_categories()

        refresh_rows()

        add_row = tk.Frame(card, bg=SURFACE)
        add_row.pack(fill="x", padx=16, pady=(10, 16))
        var_new = tk.StringVar()
        e_new = ttk.Entry(add_row, textvariable=var_new, width=24)
        e_new.pack(side="left")
        e_new.bind("<Return>", lambda e: add_cat())
        ttk.Button(add_row, text="+ Ajouter", style="Primary.TButton", command=add_cat).pack(side="left", padx=(8, 0))

        win.bind("<Escape>", lambda e: win.destroy())
        win.transient(self)
        win.update_idletasks()
        w, h = win.winfo_width(), win.winfo_height()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"+{(sw - w) // 2}+{(sh - h) // 3}")
        win.lift()
        win.attributes("-topmost", True)
        win.after(300, lambda: win.attributes("-topmost", False))
        win.focus_force()

    def _sync_categories(self):
        """Reflète la liste de catégories à jour dans le formulaire de saisie."""
        cats = get_categories()
        self.cb_categorie.configure(values=cats)
        if self.var_cat.get() not in cats:
            self.var_cat.set(cats[0])

    def _save_expense_edit(self):
        motif = self.var_motif.get().strip()
        try:
            montant = parse_amount(self.var_montant.get())
        except ValueError:
            montant = 0
        if not motif or montant <= 0:
            messagebox.showwarning("Champ manquant", "Merci d'indiquer un motif et un montant valide.")
            return
        idx = self._editing_idx
        self.expenses[idx] = {"motif": motif, "categorie": self.var_cat.get(), "montant": montant,
                               "piece_jointe": self._pending_attachment}
        self._cancel_edit()
        self.selected_expense_idx = None
        self._refresh_expense_list()
        self._refresh_summary()

    def _set_widget_bg(self, widget, color):
        try:
            widget.configure(bg=color)
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self._set_widget_bg(child, color)

    def _highlight_selected_row(self):
        for i, row in enumerate(self._expense_row_widgets):
            if i == self.selected_expense_idx:
                color = "#D3ECEE"
            else:
                color = SURFACE if i % 2 == 0 else BG
            self._set_widget_bg(row, color)

    def _refresh_expense_list(self):
        for w in self.dep_rows_frame.winfo_children():
            w.destroy()
        self._expense_row_widgets = []

        if not self.expenses:
            tk.Label(self.dep_rows_frame, text="Aucune dépense ajoutée pour cette journée.",
                      bg=SURFACE, fg=MUTED, font=("Segoe UI", 9, "italic"), pady=22).pack(fill="x")
            return

        for i, e in enumerate(self.expenses):
            rowbg = SURFACE if i % 2 == 0 else BG
            row = tk.Frame(self.dep_rows_frame, bg=rowbg, cursor="hand2")
            row.pack(fill="x")
            row.columnconfigure(0, weight=1)

            left = tk.Frame(row, bg=rowbg)
            left.grid(row=0, column=0, sticky="w", padx=14, pady=8)
            tk.Label(left, text=e["motif"], bg=rowbg, fg=INK, font=("Segoe UI", 10, "bold"), anchor="w").pack(anchor="w")
            tk.Label(left, text=e["categorie"], bg=rowbg, fg=TEAL_DARK, font=("Segoe UI", 8, "bold"), anchor="w").pack(anchor="w")

            has_piece = bool(e.get("piece_jointe"))
            clip = tk.Label(row, text=("📎" if has_piece else ""), bg=rowbg, fg=TEAL_DARK,
                              font=("Segoe UI", 11), width=3, anchor="center",
                              cursor=("hand2" if has_piece else "arrow"))
            clip.grid(row=0, column=1, sticky="ns")
            if has_piece:
                clip.bind("<Button-1>", lambda ev, fn=e["piece_jointe"]: open_attachment(fn))

            amt = tk.Label(row, text=fmt(e["montant"]), bg=rowbg, fg=INK, font=("Consolas", 11, "bold"),
                            anchor="e", width=16, padx=14)
            amt.grid(row=0, column=2, sticky="e")

            tk.Frame(self.dep_rows_frame, bg=BORDER, height=1).pack(fill="x")

            for w in (row, left, amt, *left.winfo_children()):
                w.bind("<Button-1>", lambda ev, idx=i: self._select_expense_row(idx))
                w.bind("<Double-Button-1>", lambda ev, idx=i: self._enter_edit_mode(idx))
            self._expense_row_widgets.append(row)

        self._highlight_selected_row()

    def _totals(self):
        try:
            solde = parse_amount(self.var_solde.get())
        except ValueError:
            solde = 0
        try:
            recettes = parse_amount(self.var_recettes.get())
        except ValueError:
            recettes = 0
        # Le versement banque n'est pas une vraie dépense (l'argent n'est pas
        # perdu, juste déplacé) : on le compte à part, même s'il réduit aussi
        # l'espèce en caisse comme une dépense classique.
        total_dep = sum(e["montant"] for e in self.expenses if e["categorie"] != CATEGORIE_VERSEMENT)
        total_vers = sum(e["montant"] for e in self.expenses if e["categorie"] == CATEGORIE_VERSEMENT)
        final = solde + recettes - total_dep - total_vers
        return solde, recettes, total_dep, total_vers, final

    def _refresh_summary(self):
        solde, recettes, total_dep, total_vers, final = self._totals()
        nb_vers = sum(1 for e in self.expenses if e["categorie"] == CATEGORIE_VERSEMENT)
        nb_dep = len(self.expenses) - nb_vers
        self.txt_summary.configure(state="normal")
        self.txt_summary.delete("1.0", "end")
        self.txt_summary.insert("end", f"Solde initial ......... {fmt(solde)}\n", "muted")
        self.txt_summary.insert("end", f"Recettes ............... + {fmt(recettes)}\n", "muted")
        self.txt_summary.insert("end", f"Dépenses ({nb_dep}) ................ - {fmt(total_dep)}\n", "muted")
        if nb_vers:
            self.txt_summary.insert("end", f"Versements banque ({nb_vers}) ...... - {fmt(total_vers)}\n", "muted")
        self.txt_summary.insert("end", f"{'-'*38}\n", "muted")
        tag = "positive" if final >= 0 else "negative"
        self.txt_summary.insert("end", f"MONTANT FINAL CAISSE ... {fmt(final)}", tag)
        self.txt_summary.configure(state="disabled")

    def _save_day(self):
        if self._locked():
            return
        jour_date = self.var_date.get().strip()
        try:
            datetime.strptime(jour_date, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Date invalide", "Utilisez le format AAAA-MM-JJ.")
            return
        try:
            parse_amount(self.var_recettes.get())
        except ValueError:
            messagebox.showerror("Recette invalide",
                                  f"Le montant de recette saisi (« {self.var_recettes.get()} ») "
                                  "n'est pas reconnu comme un nombre.\nCorrige-le avant d'enregistrer.")
            return
        try:
            parse_amount(self.var_solde.get())
        except ValueError:
            messagebox.showerror("Solde invalide",
                                  f"Le solde de départ saisi (« {self.var_solde.get()} ») "
                                  "n'est pas reconnu comme un nombre.\nCorrige-le avant d'enregistrer.")
            return
        solde, recettes, _, _, _ = self._totals()
        upsert_jour(jour_date, solde, recettes, self.expenses)
        if jour_date != datetime.now().strftime("%Y-%m-%d"):
            log_audit(jour_date, "Journée modifiée a posteriori (après déverrouillage)")
        messagebox.showinfo("Enregistré", f"Journée du {jour_date} enregistrée.")
        self._refresh_all()

    def _print_current(self):
        solde, recettes, total_dep, total_vers, final = self._totals()
        export_print_html(self.var_date.get(), solde, recettes, self.expenses, total_dep, total_vers, final)

    # ----- Historique -------------------------------------------------
    def _build_historique_tab(self):
        f = self.tab_hist
        container = ttk.Frame(f, style="Paper.TFrame")
        container.pack(fill="both", expand=True, padx=16, pady=16)

        today = datetime.now()
        self.hist_cal_year, self.hist_cal_month = today.year, today.month
        cal_card = tk.Frame(container, bg=BORDER)
        cal_card.pack(side="left", fill="y", padx=(0, 16))
        self.hist_cal_container = tk.Frame(cal_card, bg=SURFACE)
        self.hist_cal_container.pack(padx=1, pady=1)
        tk.Label(container, text="", bg=BG, width=1).pack(side="left")  # léger espace

        right_col = ttk.Frame(container, style="Paper.TFrame")
        right_col.pack(side="left", fill="both", expand=True)

        self.selected_hist_date = None
        self._hist_row_widgets = {}

        card = tk.Frame(right_col, bg=BORDER)
        card.pack(fill="both", expand=True)
        inner = tk.Frame(card, bg=SURFACE)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        head = tk.Frame(inner, bg=NAVY)
        head.pack(fill="x")
        head.columnconfigure(0, weight=1)
        tk.Label(head, text="DATE", bg=NAVY, fg="white", font=("Segoe UI", 10, "bold"),
                  anchor="w", padx=14, pady=10).grid(row=0, column=0, sticky="ew")
        tk.Label(head, text="RECETTES", bg=NAVY, fg="white", font=("Segoe UI", 10, "bold"),
                  anchor="e", padx=14, pady=10, width=14).grid(row=0, column=1, sticky="e")
        tk.Label(head, text="DÉPENSES", bg=NAVY, fg="white", font=("Segoe UI", 10, "bold"),
                  anchor="e", padx=14, pady=10, width=14).grid(row=0, column=2, sticky="e")
        tk.Label(head, text="MONTANT FINAL", bg=NAVY, fg="white", font=("Segoe UI", 10, "bold"),
                  anchor="e", padx=14, pady=10, width=16).grid(row=0, column=3, sticky="e")

        rows_area = tk.Frame(inner, bg=SURFACE)
        rows_area.pack(fill="both", expand=True)
        self.hist_canvas = tk.Canvas(rows_area, bg=SURFACE, highlightthickness=0, takefocus=1)
        vsb = ttk.Scrollbar(rows_area, orient="vertical", command=self.hist_canvas.yview)
        self.hist_canvas.configure(yscrollcommand=vsb.set)
        self.hist_canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.hist_rows_frame = tk.Frame(self.hist_canvas, bg=SURFACE)
        self._hist_canvas_window = self.hist_canvas.create_window((0, 0), window=self.hist_rows_frame, anchor="nw")
        self.hist_rows_frame.bind("<Configure>", lambda e: self.hist_canvas.configure(scrollregion=self.hist_canvas.bbox("all")))
        self.hist_canvas.bind("<Configure>", lambda e: self.hist_canvas.itemconfig(self._hist_canvas_window, width=e.width))

        btns = ttk.Frame(right_col, style="Paper.TFrame")
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="🔄 Actualiser / Recalculer", command=self._force_refresh_historique).pack(side="left", padx=(0, 10))
        ttk.Button(btns, text="Ouvrir dans Saisie", command=self._open_selected_day).pack(side="left", padx=(0, 10))
        ttk.Button(btns, text="🖨 Imprimer ce jour", style="Accent.TButton",
                    command=self._print_selected_history).pack(side="left")

        self._refresh_hist_calendar()

    def _refresh_hist_calendar(self):
        render_month_calendar(
            self.hist_cal_container, self.hist_cal_year, self.hist_cal_month,
            marked_dates=days_with_entries(self.hist_cal_year, self.hist_cal_month),
            on_prev=lambda: self._hist_change_month(-1),
            on_next=lambda: self._hist_change_month(1),
            on_pick=self._hist_pick_day,
            on_today=self._hist_pick_today,
        )

    def _hist_change_month(self, delta):
        m = self.hist_cal_month + delta
        y = self.hist_cal_year
        if m < 1:
            m, y = 12, y - 1
        elif m > 12:
            m, y = 1, y + 1
        self.hist_cal_year, self.hist_cal_month = y, m
        self._refresh_hist_calendar()

    def _hist_pick_day(self, jour_date):
        self._new_day(jour_date)
        self.notebook.select(self.tab_saisie)

    def _hist_pick_today(self):
        self._hist_pick_day(datetime.now().strftime("%Y-%m-%d"))

    def _refresh_historique(self):
        for w in self.hist_rows_frame.winfo_children():
            w.destroy()
        self._hist_row_widgets = {}

        records = list_jours()
        if not records:
            tk.Label(self.hist_rows_frame, text="Aucune journée enregistrée pour l'instant.",
                      bg=SURFACE, fg=MUTED, font=("Segoe UI", 9, "italic"), pady=22).pack(fill="x")
            self._highlight_selected_hist_row()
            return

        for i, rec in enumerate(records):
            rowbg = SURFACE if i % 2 == 0 else BG
            row = tk.Frame(self.hist_rows_frame, bg=rowbg, cursor="hand2")
            row.pack(fill="x")
            row.columnconfigure(0, weight=1)

            tk.Label(row, text=rec["date"], bg=rowbg, fg=INK, font=("Segoe UI", 11, "bold"),
                      anchor="w", padx=14, pady=10).grid(row=0, column=0, sticky="w")
            tk.Label(row, text=fmt(rec["recettes"]), bg=rowbg, fg=INK, font=("Consolas", 11),
                      anchor="e", padx=14, width=14).grid(row=0, column=1, sticky="e")
            tk.Label(row, text=fmt(rec["total_depenses"]), bg=rowbg, fg=INK, font=("Consolas", 11),
                      anchor="e", padx=14, width=14).grid(row=0, column=2, sticky="e")
            final_color = SUCCESS if rec["final"] >= 0 else DANGER
            tk.Label(row, text=fmt(rec["final"]), bg=rowbg, fg=final_color, font=("Consolas", 12, "bold"),
                      anchor="e", padx=14, width=16).grid(row=0, column=3, sticky="e")

            tk.Frame(self.hist_rows_frame, bg=BORDER, height=1).pack(fill="x")

            for w in (row, *row.winfo_children()):
                w.bind("<Button-1>", lambda ev, d=rec["date"]: self._select_hist_row(d))
                w.bind("<Double-Button-1>", lambda ev, d=rec["date"]: self._hist_pick_day(d))
            self._hist_row_widgets[rec["date"]] = row

        self._highlight_selected_hist_row()

    def _select_hist_row(self, jour_date):
        self.selected_hist_date = jour_date
        self._highlight_selected_hist_row()

    def _highlight_selected_hist_row(self):
        for i, (d, row) in enumerate(self._hist_row_widgets.items()):
            base = SURFACE if i % 2 == 0 else BG
            color = "#D3ECEE" if d == self.selected_hist_date else base
            self._set_widget_bg(row, color)

    def _open_selected_day(self, event=None):
        if not self.selected_hist_date:
            messagebox.showinfo("Aucune sélection", "Sélectionnez une journée dans la liste.")
            return
        self._new_day(self.selected_hist_date)
        self.notebook.select(self.tab_saisie)

    def _print_selected_history(self):
        if not self.selected_hist_date:
            messagebox.showinfo("Aucune sélection", "Sélectionnez une journée dans la liste.")
            return
        rec = load_jour(self.selected_hist_date)
        total_dep = sum(e["montant"] for e in rec["expenses"] if e["categorie"] != CATEGORIE_VERSEMENT)
        total_vers = sum(e["montant"] for e in rec["expenses"] if e["categorie"] == CATEGORIE_VERSEMENT)
        final = rec["solde_initial"] + rec["recettes"] - total_dep - total_vers
        export_print_html(rec["jour_date"], rec["solde_initial"], rec["recettes"], rec["expenses"],
                            total_dep, total_vers, final)

    # ----- Tableau de bord -------------------------------------------------
    def _build_dashboard_tab(self):
        f = self.tab_dash
        top = ttk.Frame(f, style="Paper.TFrame")
        top.pack(fill="x", padx=16, pady=(16, 8))
        ttk.Label(top, text="Mois (AAAA-MM)", style="Cat.TLabel").pack(side="left", padx=(0, 8))
        self.var_month = tk.StringVar(value=datetime.now().strftime("%Y-%m"))
        e = ttk.Entry(top, textvariable=self.var_month, width=10)
        e.pack(side="left")
        e.bind("<Return>", lambda ev: self._refresh_dashboard())
        ttk.Button(top, text="Actualiser", style="Primary.TButton",
                    command=self._refresh_dashboard).pack(side="left", padx=8)
        ttk.Button(top, text="🖨 Rapport du mois", style="Accent.TButton",
                    command=self._print_month_report).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="📊 Export CSV (comptable)",
                    command=self._export_month_csv).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="💾 Sauvegarder maintenant",
                    command=self._backup_now).pack(side="right")
        ttk.Button(top, text="🕘 Journal des modifications",
                    command=self._show_audit_log).pack(side="right", padx=(0, 8))

        today = datetime.now()
        self.cur_week_monday = today - timedelta(days=today.weekday())
        week_bar = ttk.Frame(f, style="Paper.TFrame")
        week_bar.pack(fill="x", padx=16, pady=(0, 12))
        ttk.Label(week_bar, text="Semaine", style="Cat.TLabel").pack(side="left", padx=(0, 8))
        ttk.Button(week_bar, text="◀", width=3, command=lambda: self._change_week(-1)).pack(side="left")
        self.lbl_week_range = ttk.Label(week_bar, text="", font=("Segoe UI", 10, "bold"))
        self.lbl_week_range.pack(side="left", padx=8)
        ttk.Button(week_bar, text="▶", width=3, command=lambda: self._change_week(1)).pack(side="left")
        ttk.Button(week_bar, text="🖨 Rapport de la semaine", style="Accent.TButton",
                    command=self._print_week_report).pack(side="left", padx=(12, 0))
        ttk.Button(week_bar, text="📊 Export CSV (comptable)",
                    command=self._export_week_csv).pack(side="left", padx=(8, 0))

        self.cur_year = datetime.now().year
        year_bar = ttk.Frame(f, style="Paper.TFrame")
        year_bar.pack(fill="x", padx=16, pady=(0, 12))
        ttk.Label(year_bar, text="Année", style="Cat.TLabel").pack(side="left", padx=(0, 8))
        ttk.Button(year_bar, text="◀", width=3, command=lambda: self._change_year(-1)).pack(side="left")
        self.lbl_year = ttk.Label(year_bar, text="", font=("Segoe UI", 10, "bold"))
        self.lbl_year.pack(side="left", padx=8)
        ttk.Button(year_bar, text="▶", width=3, command=lambda: self._change_year(1)).pack(side="left")
        ttk.Button(year_bar, text="🖨 Rapport annuel", style="Accent.TButton",
                    command=self._print_year_report).pack(side="left", padx=(12, 0))
        ttk.Button(year_bar, text="📊 Export CSV (comptable)",
                    command=self._export_year_csv).pack(side="left", padx=(8, 0))
        self._refresh_year_label()

        search_bar = ttk.Frame(f, style="Paper.TFrame")
        search_bar.pack(fill="x", padx=16, pady=(0, 12))
        ttk.Label(search_bar, text="🔍 Rechercher un motif (ex: nom d'un employé)", style="Cat.TLabel").pack(side="left", padx=(0, 8))
        self.var_motif_search = tk.StringVar()
        e_search = ttk.Entry(search_bar, textvariable=self.var_motif_search, width=22)
        e_search.pack(side="left")
        e_search.bind("<Return>", lambda ev: self._search_motif())
        self.var_motif_all = tk.BooleanVar(value=False)
        ttk.Checkbutton(search_bar, text="Tout l'historique (sinon: mois ci-dessus)",
                         variable=self.var_motif_all).pack(side="left", padx=(10, 0))
        ttk.Button(search_bar, text="Rechercher", style="Primary.TButton",
                    command=self._search_motif).pack(side="left", padx=(10, 0))

        self.txt_dash = tk.Text(f, font=("Consolas", 11), bg=SURFACE, fg=INK, relief="flat",
                                 height=26, wrap="word", highlightthickness=0, borderwidth=0)
        self.txt_dash.tag_configure("title", foreground=NAVY, font=("Consolas", 12, "bold"))
        self.txt_dash.tag_configure("muted", foreground=MUTED)
        self.txt_dash.tag_configure("bar", foreground=TEAL_DARK)
        self.txt_dash.tag_configure("cat", foreground=INK, font=("Consolas", 11, "bold"))
        self.txt_dash.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        self._refresh_week_label()

    def _change_week(self, delta):
        self.cur_week_monday += timedelta(days=7 * delta)
        self._refresh_week_label()

    def _refresh_week_label(self):
        monday = self.cur_week_monday
        sunday = monday + timedelta(days=6)
        self.lbl_week_range.config(text=f"Du {monday.strftime('%d/%m/%Y')} au {sunday.strftime('%d/%m/%Y')}")

    def _print_week_report(self):
        export_weekly_report(self.cur_week_monday.strftime("%Y-%m-%d"))

    def _export_week_csv(self):
        export_weekly_csv(self.cur_week_monday.strftime("%Y-%m-%d"))

    def _change_year(self, delta):
        self.cur_year += delta
        self._refresh_year_label()

    def _refresh_year_label(self):
        self.lbl_year.config(text=str(self.cur_year))

    def _print_year_report(self):
        export_yearly_report(self.cur_year)

    def _export_year_csv(self):
        export_yearly_csv(self.cur_year)

    def _parse_month_field(self):
        year_month = self.var_month.get().strip()
        try:
            return int(year_month[:4]), int(year_month[5:7])
        except (ValueError, IndexError):
            messagebox.showerror("Mois invalide", "Utilisez le format AAAA-MM.")
            return None

    def _print_month_report(self):
        ym = self._parse_month_field()
        if ym:
            export_monthly_report(*ym)

    def _export_month_csv(self):
        ym = self._parse_month_field()
        if ym:
            export_monthly_csv(*ym)

    def _backup_now(self):
        path = backup_now()
        if path:
            messagebox.showinfo("Sauvegarde effectuée",
                                 f"Une copie de la caisse a été enregistrée dans :\n{BACKUP_DIR}")
        else:
            messagebox.showerror("Échec de la sauvegarde",
                                  "La sauvegarde n'a pas pu être effectuée. Vérifie l'espace disque disponible.")

    def _show_audit_log(self):
        # Fenêtre sans bordure système, comme le calendrier : c'est la seule
        # formule qui s'affiche de façon fiable sur cet ordinateur (les
        # fenêtres Toplevel décorées classiques restent parfois blanches).
        win = tk.Toplevel(self)
        win.overrideredirect(True)
        win.configure(bg=BORDER)

        card = tk.Frame(win, bg=SURFACE)
        card.pack(padx=1, pady=1)

        header = tk.Frame(card, bg=NAVY_DEEP)
        header.pack(fill="x")
        tk.Label(header, text="Journal des modifications", bg=NAVY_DEEP, fg="white",
                  font=("Segoe UI", 11, "bold"), padx=14, pady=10).pack(side="left")
        close_lbl = tk.Label(header, text="✕", bg=NAVY_DEEP, fg="#A9C2CF", font=("Segoe UI", 10, "bold"),
                               padx=12, pady=10, cursor="hand2")
        close_lbl.pack(side="right")
        close_lbl.bind("<Button-1>", lambda e: win.destroy())

        tk.Label(card, text="Journées déjà passées qui ont été déverrouillées puis modifiées.",
                  bg=SURFACE, fg=MUTED, font=("Segoe UI", 9), anchor="w", padx=16).pack(fill="x", pady=(10, 6))

        entries = list_audit_log()
        txt = tk.Text(card, bg=SURFACE, fg=INK, font=("Consolas", 10), relief="flat",
                       highlightthickness=0, borderwidth=0, padx=16, wrap="word", width=62, height=18)
        txt.tag_configure("date", foreground=NAVY, font=("Consolas", 10, "bold"))
        txt.tag_configure("muted", foreground=MUTED)
        if entries:
            for entry in entries:
                txt.insert("end", f"{entry['horodatage']}  ", "date")
                txt.insert("end", f"— journée du {entry['jour_date']}\n", "muted")
                txt.insert("end", f"    {entry['description']}\n\n")
        else:
            txt.insert("end", "Aucune modification a posteriori enregistrée pour l'instant.", "muted")
        txt.configure(state="disabled")
        txt.pack(fill="both", expand=True, padx=0, pady=(0, 14))

        win.bind("<Escape>", lambda e: win.destroy())
        win.transient(self)
        win.update_idletasks()
        w, h = win.winfo_width(), win.winfo_height()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"+{(sw - w) // 2}+{(sh - h) // 3}")
        win.lift()
        win.attributes("-topmost", True)
        win.after(300, lambda: win.attributes("-topmost", False))
        win.focus_force()

    def _search_motif(self):
        query = self.var_motif_search.get().strip()
        if not query:
            messagebox.showwarning("Champ vide", "Tape un nom ou un mot à rechercher (ex: un nom d'employé).")
            return
        if self.var_motif_all.get():
            start, end, period_label = "0000-01-01", "9999-12-31", "tout l'historique"
        else:
            ym = self._parse_month_field()
            if not ym:
                return
            y, m = ym
            start = f"{y:04d}-{m:02d}-01"
            end = f"{y:04d}-{m:02d}-{calendar_mod.monthrange(y, m)[1]:02d}"
            period_label = f"{FR_MOIS[m - 1]} {y}"
        stats = _period_stats(start, end)
        q = query.lower()
        matches = [mv for mv in stats["movements"]
                    if mv["type"] != "Recette" and q in (mv["motif"] or "").lower()]
        self._show_motif_search_results(query, period_label, matches)

    def _show_motif_search_results(self, query, period_label, matches):
        win = tk.Toplevel(self)
        win.overrideredirect(True)
        win.configure(bg=BORDER)

        card = tk.Frame(win, bg=SURFACE)
        card.pack(padx=1, pady=1)

        header = tk.Frame(card, bg=NAVY_DEEP)
        header.pack(fill="x")
        tk.Label(header, text=f"Résultats pour « {query} »", bg=NAVY_DEEP, fg="white",
                  font=("Segoe UI", 11, "bold"), padx=14, pady=10).pack(side="left")
        close_lbl = tk.Label(header, text="✕", bg=NAVY_DEEP, fg="#A9C2CF", font=("Segoe UI", 10, "bold"),
                               padx=12, pady=10, cursor="hand2")
        close_lbl.pack(side="right")
        close_lbl.bind("<Button-1>", lambda e: win.destroy())

        total = sum(-mv["montant"] for mv in matches)
        tk.Label(card, text=f"Période : {period_label}   —   {len(matches)} résultat(s)   —   total : {fmt(total)}",
                  bg=SURFACE, fg=MUTED, font=("Segoe UI", 9), anchor="w", padx=16).pack(fill="x", pady=(10, 6))

        txt = tk.Text(card, bg=SURFACE, fg=INK, font=("Consolas", 10), relief="flat",
                       highlightthickness=0, borderwidth=0, padx=16, wrap="word", width=62, height=18)
        txt.tag_configure("date", foreground=NAVY, font=("Consolas", 10, "bold"))
        txt.tag_configure("muted", foreground=MUTED)
        if matches:
            for mv in sorted(matches, key=lambda x: x["date"]):
                txt.insert("end", f"{mv['date']}  ", "date")
                txt.insert("end", f"— {mv['categorie']}\n", "muted")
                txt.insert("end", f"    {mv['motif']} : {fmt(-mv['montant'])}\n\n")
        else:
            txt.insert("end", "Aucun résultat pour cette recherche sur cette période.", "muted")
        txt.configure(state="disabled")
        txt.pack(fill="both", expand=True, padx=0, pady=(0, 14))

        win.bind("<Escape>", lambda e: win.destroy())
        win.transient(self)
        win.update_idletasks()
        w, h = win.winfo_width(), win.winfo_height()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"+{(sw - w) // 2}+{(sh - h) // 3}")
        win.lift()
        win.attributes("-topmost", True)
        win.after(300, lambda: win.attributes("-topmost", False))
        win.focus_force()

    def _refresh_dashboard(self):
        stats = monthly_stats(self.var_month.get().strip())
        self.txt_dash.config(state="normal")
        self.txt_dash.delete("1.0", "end")
        self.txt_dash.insert("end", f"RÉSUMÉ DU MOIS {self.var_month.get()}\n", "title")
        self.txt_dash.insert("end", "=" * 46 + "\n\n", "muted")
        self.txt_dash.insert("end", f"Jours enregistrés ......... {stats['nb_jours']}\n")
        self.txt_dash.insert("end", f"Total recettes ............ {fmt(stats['total_recettes'])}\n")
        self.txt_dash.insert("end", f"Total dépenses ............ {fmt(stats['total_depenses'])}\n")
        if stats["total_versements"]:
            self.txt_dash.insert("end", f"Versements banque ......... {fmt(stats['total_versements'])}\n")
        self.txt_dash.insert("end", "\n")
        self.txt_dash.insert("end", "Dépenses par catégorie :\n", "title")
        self.txt_dash.insert("end", "-" * 46 + "\n", "muted")
        maxv = max(stats["par_categorie"].values(), default=1)
        for cat, montant in sorted(stats["par_categorie"].items(), key=lambda x: -x[1]):
            bar = "█" * max(1, int(montant / maxv * 24)) if maxv else ""
            self.txt_dash.insert("end", f"{cat:<24} ", "cat")
            self.txt_dash.insert("end", f"{bar}\n", "bar")
            self.txt_dash.insert("end", f"    {fmt(montant)}\n\n", "muted")
        if not stats["par_categorie"]:
            self.txt_dash.insert("end", "(aucune dépense ce mois-ci)\n")
        self.txt_dash.config(state="disabled")

    def _refresh_all(self):
        self._refresh_historique()
        self._refresh_hist_calendar()
        self._refresh_dashboard()

    def _force_refresh_historique(self):
        """Reconstruit entièrement l'Historique, le calendrier et le tableau
        de bord à partir de la base de données (jamais depuis un affichage
        mis en mémoire) : si un chiffre affiché semblait ne pas correspondre
        à la fiche du jour, ce bouton force un recalcul propre. Ne modifie
        jamais les données elles-mêmes, seulement leur affichage."""
        self._refresh_all()
        messagebox.showinfo("Actualisé", "Les chiffres de l'historique ont été recalculés depuis la base de données.")


if __name__ == "__main__":
    if os.name == "nt":
        # Sans cela, sur un écran avec mise à l'échelle Windows (125%, 150%...),
        # les coordonnées Tkinter ne correspondent plus aux pixels réels et les
        # fenêtres (ex: le calendrier) s'affichent au mauvais endroit.
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    init_db()

    # Écran de connexion (ou création du mot de passe au tout premier lancement)
    # avant d'afficher la caisse elle-même.
    if not is_password_configured():
        auth_dlg = PasswordSetupDialog()
    else:
        auth_dlg = LoginDialog()
    auth_dlg.mainloop()
    authorized = auth_dlg.result
    if not authorized:
        sys.exit(0)

    # Si caisse.db est partagé via un dossier cloud (OneDrive/Google Drive)
    # entre plusieurs postes, avertit si un autre poste l'a utilisée il y a
    # moins de 5 minutes, pour éviter que deux personnes n'écrasent leurs
    # saisies en travaillant en même temps sur le même jour.
    current_machine = machine_name()
    lock_info = check_active_lock(current_machine)
    if lock_info:
        warn_dlg = LockWarningDialog(lock_info)
        warn_dlg.mainloop()
        if not warn_dlg.result:
            sys.exit(0)

    maybe_daily_backup()

    app = CaisseApp(current_machine)
    app.mainloop()
