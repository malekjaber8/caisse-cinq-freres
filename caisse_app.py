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
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import date, datetime
import webbrowser
import html

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "caisse.db")
EXPORTS_DIR = os.path.join(APP_DIR, "etats_imprimes")
ASSETS_DIR = os.path.join(APP_DIR, "assets")

CATEGORIES = [
    "Carburant / Vidange",
    "Entretien véhicule",
    "Internet / Téléphone",
    "Fournitures bureau",
    "Salaires",
    "Versement banque",
    "Livraison / Transport",
    "Autre",
]

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
        FOREIGN KEY (jour_id) REFERENCES jours(id) ON DELETE CASCADE
    )""")
    conn.commit()
    conn.close()


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


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
        c.execute("INSERT INTO depenses (jour_id, motif, categorie, montant) VALUES (?,?,?,?)",
                  (jour_id, e["motif"], e["categorie"], e["montant"]))
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
    c.execute("SELECT id, motif, categorie, montant FROM depenses WHERE jour_id=?", (jour_id,))
    expenses = [{"id": r[0], "motif": r[1], "categorie": r[2], "montant": r[3]} for r in c.fetchall()]
    conn.close()
    return {"jour_date": jour_date, "solde_initial": solde_initial, "recettes": recettes, "expenses": expenses}


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


def last_final_before(jour_date):
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
    return si + rec - total_dep


def monthly_stats(year_month):
    """year_month format 'YYYY-MM'"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, recettes FROM jours WHERE jour_date LIKE ?", (year_month + "%",))
    jours = c.fetchall()
    total_recettes = sum(r for _, r in jours)
    par_categorie = {}
    total_depenses = 0.0
    for jour_id, _ in jours:
        c.execute("SELECT categorie, montant FROM depenses WHERE jour_id=?", (jour_id,))
        for cat, montant in c.fetchall():
            par_categorie[cat] = par_categorie.get(cat, 0) + montant
            total_depenses += montant
    conn.close()
    return {"nb_jours": len(jours), "total_recettes": total_recettes,
            "total_depenses": total_depenses, "par_categorie": par_categorie}


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


def export_print_html(jour_date, solde_initial, recettes, expenses, total_depenses, final):
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    rows = "".join(
        f"<tr><td>{html.escape(e['motif'])}<span class='cat'>{html.escape(e['categorie'])}</span></td>"
        f"<td class='amt'>{fmt(e['montant'])}</td></tr>"
        for e in expenses
    )
    logo_uri = _logo_data_uri()
    logo_html = f'<img src="{logo_uri}" alt="Les Cinq Frères" class="logo">' if logo_uri else ""
    final_class = "positive" if final >= 0 else "negative"
    content = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<title>Etat de caisse {jour_date}</title>
<style>
 :root {{
   --navy:#004E74; --navy-deep:#00354F; --teal:#08A4B0; --ink:#1F2A33;
   --muted:#5B6B79; --border:#DCE3E8; --success:#1B8A5A; --danger:#C1373B; --bg:#F4F6F8;
 }}
 * {{ box-sizing:border-box; }}
 body {{ font-family:'Segoe UI', Arial, sans-serif; background:var(--bg); color:var(--ink); margin:0; padding:32px 16px; }}
 .card {{ max-width:480px; margin:0 auto; background:#fff; border:1px solid var(--border); border-radius:10px;
          box-shadow:0 4px 14px rgba(0,78,116,0.08); overflow:hidden; }}
 .head {{ background:var(--navy-deep); color:#fff; padding:22px 24px; text-align:center; }}
 .logo {{ height:56px; margin-bottom:8px; }}
 .head h1 {{ margin:0; font-size:16px; letter-spacing:0.5px; }}
 .head p {{ margin:4px 0 0; font-size:12px; color:var(--teal); font-weight:600; }}
 .meta {{ text-align:center; padding:12px 24px 0; font-size:12px; color:var(--muted); }}
 table {{ width:100%; border-collapse:collapse; font-size:13px; }}
 .items {{ padding:8px 24px 0; }}
 .items td {{ padding:7px 0; border-bottom:1px solid var(--border); }}
 .items .cat {{ display:block; font-size:11px; color:var(--muted); }}
 .amt {{ text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }}
 .totals {{ padding:14px 24px 22px; }}
 .totals td {{ padding:5px 0; }}
 .totals tr.final td {{ padding-top:12px; border-top:2px solid var(--border); font-weight:700; font-size:16px; }}
 .totals tr.final.positive td {{ color:var(--success); }}
 .totals tr.final.negative td {{ color:var(--danger); }}
 .foot {{ text-align:center; padding:0 24px 22px; }}
 button {{ background:var(--navy); color:#fff; border:none; border-radius:6px; padding:10px 22px;
           font-size:13px; font-weight:600; cursor:pointer; }}
 button:hover {{ background:var(--navy-deep); }}
 @media print {{ body {{ background:#fff; padding:0; }} .card {{ box-shadow:none; border:none; }} .foot {{ display:none; }} }}
</style></head>
<body>
<div class="card">
  <div class="head">
    {logo_html}
    <h1>SOCIÉTÉ MAGASIN LES CINQ FRÈRES</h1>
    <p>État de caisse</p>
  </div>
  <p class="meta">{jour_date} — généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}</p>
  <table class="items">{rows}</table>
  <table class="totals">
   <tr><td>Solde initial</td><td class="amt">{fmt(solde_initial)}</td></tr>
   <tr><td>Recettes</td><td class="amt">+ {fmt(recettes)}</td></tr>
   <tr><td>Total dépenses</td><td class="amt">- {fmt(total_depenses)}</td></tr>
   <tr class="final {final_class}"><td>MONTANT FINAL</td><td class="amt">{fmt(final)}</td></tr>
  </table>
  <div class="foot"><button onclick="window.print()">🖨 Imprimer</button></div>
</div>
</body></html>"""
    path = os.path.join(EXPORTS_DIR, f"etat_{jour_date}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    webbrowser.open(f"file://{path}")


# ---------------------------------------------------------------------------
# Interface graphique
# ---------------------------------------------------------------------------
class CaisseApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Société Magasin Les Cinq Frères — Livre de Caisse")
        self.geometry("920x620")
        self.configure(bg=BG)
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
        top = ttk.Frame(f, style="Paper.TFrame")
        top.pack(fill="x", padx=16, pady=(16, 8))

        ttk.Label(top, text="Date (AAAA-MM-JJ)", style="Cat.TLabel").grid(row=0, column=0, sticky="w")
        self.var_date = tk.StringVar()
        e_date = ttk.Entry(top, textvariable=self.var_date, width=16)
        e_date.grid(row=1, column=0, sticky="w", padx=(0, 20))
        e_date.bind("<Return>", lambda e: self._new_day(self.var_date.get()))

        ttk.Label(top, text="Solde initial", style="Cat.TLabel").grid(row=0, column=1, sticky="w")
        self.var_solde = tk.StringVar(value="0")
        ttk.Entry(top, textvariable=self.var_solde, width=14).grid(row=1, column=1, sticky="w", padx=(0, 20))

        ttk.Label(top, text="Recettes du jour", style="Cat.TLabel").grid(row=0, column=2, sticky="w")
        self.var_recettes = tk.StringVar(value="0")
        ttk.Entry(top, textvariable=self.var_recettes, width=14).grid(row=1, column=2, sticky="w")
        self.var_recettes.trace_add("write", lambda *a: self._refresh_summary())
        self.var_solde.trace_add("write", lambda *a: self._refresh_summary())

        # Ajout dépense
        add_frame = ttk.Frame(f, style="Paper.TFrame")
        add_frame.pack(fill="x", padx=16, pady=8)
        ttk.Label(add_frame, text="Motif", style="Cat.TLabel").grid(row=0, column=0, sticky="w")
        self.var_motif = tk.StringVar()
        ttk.Entry(add_frame, textvariable=self.var_motif, width=28).grid(row=1, column=0, padx=(0, 10))

        ttk.Label(add_frame, text="Catégorie", style="Cat.TLabel").grid(row=0, column=1, sticky="w")
        self.var_cat = tk.StringVar(value=CATEGORIES[0])
        ttk.Combobox(add_frame, textvariable=self.var_cat, values=CATEGORIES, width=22, state="readonly").grid(row=1, column=1, padx=(0, 10))

        ttk.Label(add_frame, text="Montant", style="Cat.TLabel").grid(row=0, column=2, sticky="w")
        self.var_montant = tk.StringVar()
        e_montant = ttk.Entry(add_frame, textvariable=self.var_montant, width=12)
        e_montant.grid(row=1, column=2, padx=(0, 10))
        e_montant.bind("<Return>", lambda e: self._add_expense())

        ttk.Button(add_frame, text="+ Ajouter", command=self._add_expense).grid(row=1, column=3)

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
        tk.Label(head, text="MONTANT", bg=BG, fg=MUTED, font=("Segoe UI", 9, "bold"),
                  anchor="e", padx=14, pady=9, width=16).grid(row=0, column=1, sticky="e")
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

        del_btn = ttk.Button(f, text="Supprimer la dépense sélectionnée", command=self._remove_selected_expense)
        del_btn.pack(anchor="w", padx=16)

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
        ttk.Button(actions, text="💾 Enregistrer la journée", style="Primary.TButton",
                    command=self._save_day).pack(side="left", padx=(0, 10))
        ttk.Button(actions, text="🖨 Imprimer / Exporter", style="Accent.TButton",
                    command=self._print_current).pack(side="left")

    def _new_day(self, jour_date):
        self.var_date.set(jour_date)
        existing = load_jour(jour_date)
        if existing:
            self.var_solde.set(str(existing["solde_initial"]))
            self.var_recettes.set(str(existing["recettes"]))
            self.expenses = list(existing["expenses"])
        else:
            prev_final = last_final_before(jour_date)
            self.var_solde.set(str(round(prev_final, 3)) if prev_final is not None else "0")
            self.var_recettes.set("0")
            self.expenses = []
        self.selected_expense_idx = None
        self._refresh_expense_list()
        self._refresh_summary()

    def _add_expense(self):
        motif = self.var_motif.get().strip()
        try:
            montant = float(self.var_montant.get().replace(",", "."))
        except ValueError:
            montant = 0
        if not motif or montant <= 0:
            messagebox.showwarning("Champ manquant", "Merci d'indiquer un motif et un montant valide.")
            return
        self.expenses.append({"motif": motif, "categorie": self.var_cat.get(), "montant": montant})
        self.var_motif.set("")
        self.var_montant.set("")
        self._refresh_expense_list()
        self._refresh_summary()

    def _select_expense_row(self, idx):
        self.selected_expense_idx = idx
        self._highlight_selected_row()
        self.dep_canvas.focus_set()

    def _remove_selected_expense(self):
        idx = self.selected_expense_idx
        if idx is None or idx >= len(self.expenses):
            return
        del self.expenses[idx]
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

            amt = tk.Label(row, text=fmt(e["montant"]), bg=rowbg, fg=INK, font=("Consolas", 11, "bold"),
                            anchor="e", width=16, padx=14)
            amt.grid(row=0, column=1, sticky="e")

            tk.Frame(self.dep_rows_frame, bg=BORDER, height=1).pack(fill="x")

            for w in (row, left, amt, *left.winfo_children()):
                w.bind("<Button-1>", lambda ev, idx=i: self._select_expense_row(idx))
            self._expense_row_widgets.append(row)

        self._highlight_selected_row()

    def _totals(self):
        try:
            solde = float(self.var_solde.get().replace(",", "."))
        except ValueError:
            solde = 0
        try:
            recettes = float(self.var_recettes.get().replace(",", "."))
        except ValueError:
            recettes = 0
        total_dep = sum(e["montant"] for e in self.expenses)
        final = solde + recettes - total_dep
        return solde, recettes, total_dep, final

    def _refresh_summary(self):
        solde, recettes, total_dep, final = self._totals()
        self.txt_summary.configure(state="normal")
        self.txt_summary.delete("1.0", "end")
        self.txt_summary.insert("end", f"Solde initial ......... {fmt(solde)}\n", "muted")
        self.txt_summary.insert("end", f"Recettes ............... + {fmt(recettes)}\n", "muted")
        self.txt_summary.insert("end", f"Total dépenses ({len(self.expenses)}) ...... - {fmt(total_dep)}\n", "muted")
        self.txt_summary.insert("end", f"{'-'*38}\n", "muted")
        tag = "positive" if final >= 0 else "negative"
        self.txt_summary.insert("end", f"MONTANT FINAL CAISSE ... {fmt(final)}", tag)
        self.txt_summary.configure(state="disabled")

    def _save_day(self):
        jour_date = self.var_date.get().strip()
        try:
            datetime.strptime(jour_date, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Date invalide", "Utilisez le format AAAA-MM-JJ.")
            return
        solde, recettes, _, _ = self._totals()
        upsert_jour(jour_date, solde, recettes, self.expenses)
        messagebox.showinfo("Enregistré", f"Journée du {jour_date} enregistrée.")
        self._refresh_all()

    def _print_current(self):
        solde, recettes, total_dep, final = self._totals()
        export_print_html(self.var_date.get(), solde, recettes, self.expenses, total_dep, final)

    # ----- Historique -------------------------------------------------
    def _build_historique_tab(self):
        f = self.tab_hist
        cols = ("date", "recettes", "depenses", "final")
        self.tree_hist = ttk.Treeview(f, columns=cols, show="headings", height=18)
        headers = {"date": "Date", "recettes": "Recettes", "depenses": "Dépenses", "final": "Montant final"}
        for c in cols:
            self.tree_hist.heading(c, text=headers[c])
            self.tree_hist.column(c, width=180, anchor="center" if c != "date" else "w")
        self.tree_hist.pack(fill="both", expand=True, padx=16, pady=16)
        self.tree_hist.bind("<Double-1>", self._open_selected_day)
        self.tree_hist.tag_configure("even", background=SURFACE)
        self.tree_hist.tag_configure("odd", background=BG)
        self.tree_hist.tag_configure("deficit", foreground=DANGER)

        btns = ttk.Frame(f, style="Paper.TFrame")
        btns.pack(fill="x", padx=16, pady=(0, 12))
        ttk.Button(btns, text="Ouvrir dans Saisie", command=self._open_selected_day).pack(side="left", padx=(0, 10))
        ttk.Button(btns, text="🖨 Imprimer ce jour", style="Accent.TButton",
                    command=self._print_selected_history).pack(side="left")

    def _refresh_historique(self):
        self.tree_hist.delete(*self.tree_hist.get_children())
        for i, rec in enumerate(list_jours()):
            tags = ["even" if i % 2 == 0 else "odd"]
            if rec["final"] < 0:
                tags.append("deficit")
            self.tree_hist.insert("", "end", iid=rec["date"], values=(
                rec["date"], fmt(rec["recettes"]), fmt(rec["total_depenses"]), fmt(rec["final"])
            ), tags=tags)

    def _open_selected_day(self, event=None):
        sel = self.tree_hist.selection()
        if not sel:
            return
        self._new_day(sel[0])
        self.notebook.select(self.tab_saisie)

    def _print_selected_history(self):
        sel = self.tree_hist.selection()
        if not sel:
            messagebox.showinfo("Aucune sélection", "Sélectionnez une journée dans la liste.")
            return
        rec = load_jour(sel[0])
        total_dep = sum(e["montant"] for e in rec["expenses"])
        final = rec["solde_initial"] + rec["recettes"] - total_dep
        export_print_html(rec["jour_date"], rec["solde_initial"], rec["recettes"], rec["expenses"], total_dep, final)

    # ----- Tableau de bord -------------------------------------------------
    def _build_dashboard_tab(self):
        f = self.tab_dash
        top = ttk.Frame(f, style="Paper.TFrame")
        top.pack(fill="x", padx=16, pady=16)
        ttk.Label(top, text="Mois (AAAA-MM)", style="Cat.TLabel").pack(side="left", padx=(0, 8))
        self.var_month = tk.StringVar(value=datetime.now().strftime("%Y-%m"))
        e = ttk.Entry(top, textvariable=self.var_month, width=10)
        e.pack(side="left")
        e.bind("<Return>", lambda ev: self._refresh_dashboard())
        ttk.Button(top, text="Actualiser", style="Primary.TButton",
                    command=self._refresh_dashboard).pack(side="left", padx=8)

        self.txt_dash = tk.Text(f, font=("Consolas", 11), bg=SURFACE, fg=INK, relief="flat",
                                 height=26, wrap="word", highlightthickness=0, borderwidth=0)
        self.txt_dash.tag_configure("title", foreground=NAVY, font=("Consolas", 12, "bold"))
        self.txt_dash.tag_configure("muted", foreground=MUTED)
        self.txt_dash.tag_configure("bar", foreground=TEAL_DARK)
        self.txt_dash.tag_configure("cat", foreground=INK, font=("Consolas", 11, "bold"))
        self.txt_dash.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def _refresh_dashboard(self):
        stats = monthly_stats(self.var_month.get().strip())
        self.txt_dash.config(state="normal")
        self.txt_dash.delete("1.0", "end")
        self.txt_dash.insert("end", f"RÉSUMÉ DU MOIS {self.var_month.get()}\n", "title")
        self.txt_dash.insert("end", "=" * 46 + "\n\n", "muted")
        self.txt_dash.insert("end", f"Jours enregistrés ......... {stats['nb_jours']}\n")
        self.txt_dash.insert("end", f"Total recettes ............ {fmt(stats['total_recettes'])}\n")
        self.txt_dash.insert("end", f"Total dépenses ............ {fmt(stats['total_depenses'])}\n\n")
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
        self._refresh_dashboard()


if __name__ == "__main__":
    init_db()
    app = CaisseApp()
    app.mainloop()
