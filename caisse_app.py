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

WALNUT = "#4a3222"
WALNUT_DEEP = "#38251a"
PAPER = "#f7f2e7"
PAPER_DARK = "#efe6d3"
BRASS = "#a97b2f"
GREEN = "#3f6b4a"
ROSE = "#a94438"


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
def export_print_html(jour_date, solde_initial, recettes, expenses, total_depenses, final):
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    rows = "".join(
        f"<tr><td>{html.escape(e['motif'])} ({html.escape(e['categorie'])})</td>"
        f"<td style='text-align:right'>{fmt(e['montant'])}</td></tr>"
        for e in expenses
    )
    content = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<title>Etat de caisse {jour_date}</title>
<style>
 body {{ font-family: 'Courier New', monospace; max-width: 480px; margin: 40px auto; color:#2c2117; }}
 h1 {{ text-align:center; margin-bottom:0; font-size:20px; }}
 p.sub {{ text-align:center; margin-top:4px; font-size:12px; }}
 table {{ width:100%; border-collapse:collapse; font-size:13px; margin-top:10px; }}
 td {{ padding:4px 0; }}
 hr {{ border:none; border-top:1px dashed #999; margin:12px 0; }}
 .final {{ font-weight:bold; font-size:16px; }}
 button {{ margin-top:20px; padding:8px 16px; }}
</style></head>
<body>
<h1>LES CINQ FRÈRES</h1>
<p class="sub">État de caisse — {jour_date}<br>Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}</p>
<hr>
<table>{rows}</table>
<hr>
<table>
 <tr><td>Solde initial</td><td style="text-align:right">{fmt(solde_initial)}</td></tr>
 <tr><td>Recettes</td><td style="text-align:right">+ {fmt(recettes)}</td></tr>
 <tr><td>Total dépenses</td><td style="text-align:right">- {fmt(total_depenses)}</td></tr>
 <tr class="final"><td>MONTANT FINAL</td><td style="text-align:right">{fmt(final)}</td></tr>
</table>
<button onclick="window.print()">Imprimer</button>
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
        self.title("Livre de Caisse — Les Cinq Frères")
        self.geometry("880x600")
        self.configure(bg=PAPER)
        self.expenses = []  # dépenses de la journée en cours de saisie

        self._build_style()
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
        style.configure("Paper.TFrame", background=PAPER)
        style.configure("TLabel", background=PAPER, foreground=WALNUT, font=("Segoe UI", 10))
        style.configure("Header.TLabel", background=WALNUT_DEEP, foreground=PAPER, font=("Georgia", 15, "bold"))
        style.configure("Cat.TLabel", background=PAPER, foreground=BRASS, font=("Segoe UI", 9, "bold"))
        style.configure("TButton", font=("Segoe UI", 10, "bold"), padding=6)
        style.configure("Treeview", font=("Consolas", 10), rowheight=24)
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

    def _build_header(self):
        header = tk.Frame(self, bg=WALNUT_DEEP, height=64)
        header.pack(fill="x")
        tk.Label(header, text="📒  Livre de Caisse — Les Cinq Frères", bg=WALNUT_DEEP, fg=PAPER,
                  font=("Georgia", 15, "bold"), padx=16, pady=16).pack(side="left")
        tk.Label(header, text="Application locale — aucune donnée en ligne", bg=WALNUT_DEEP, fg=BRASS,
                  font=("Segoe UI", 9), padx=16).pack(side="right")

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

        # Liste des dépenses
        cols = ("motif", "categorie", "montant")
        self.tree_dep = ttk.Treeview(f, columns=cols, show="headings", height=9)
        self.tree_dep.heading("motif", text="Motif")
        self.tree_dep.heading("categorie", text="Catégorie")
        self.tree_dep.heading("montant", text="Montant")
        self.tree_dep.column("motif", width=340)
        self.tree_dep.column("categorie", width=200)
        self.tree_dep.column("montant", width=120, anchor="e")
        self.tree_dep.pack(fill="both", expand=True, padx=16, pady=8)
        self.tree_dep.bind("<Delete>", lambda e: self._remove_selected_expense())

        del_btn = ttk.Button(f, text="Supprimer la dépense sélectionnée", command=self._remove_selected_expense)
        del_btn.pack(anchor="w", padx=16)

        # Résumé
        summary = tk.Frame(f, bg=WALNUT_DEEP)
        summary.pack(fill="x", padx=16, pady=12)
        self.lbl_summary = tk.Label(summary, text="", bg=WALNUT_DEEP, fg=PAPER, font=("Consolas", 12),
                                     justify="left", padx=16, pady=10)
        self.lbl_summary.pack(anchor="w")

        actions = ttk.Frame(f, style="Paper.TFrame")
        actions.pack(fill="x", padx=16, pady=(0, 16))
        ttk.Button(actions, text="💾 Enregistrer la journée", command=self._save_day).pack(side="left", padx=(0, 10))
        ttk.Button(actions, text="🖨 Imprimer / Exporter", command=self._print_current).pack(side="left")

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
        self._refresh_expense_tree()
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
        self._refresh_expense_tree()
        self._refresh_summary()

    def _remove_selected_expense(self):
        sel = self.tree_dep.selection()
        if not sel:
            return
        idx = self.tree_dep.index(sel[0])
        del self.expenses[idx]
        self._refresh_expense_tree()
        self._refresh_summary()

    def _refresh_expense_tree(self):
        self.tree_dep.delete(*self.tree_dep.get_children())
        for e in self.expenses:
            self.tree_dep.insert("", "end", values=(e["motif"], e["categorie"], fmt(e["montant"])))

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
        self.lbl_summary.config(text=(
            f"Solde initial ......... {fmt(solde)}\n"
            f"Recettes ............... + {fmt(recettes)}\n"
            f"Total dépenses ({len(self.expenses)}) ...... - {fmt(total_dep)}\n"
            f"{'-'*38}\n"
            f"MONTANT FINAL CAISSE ... {fmt(final)}"
        ))

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

        btns = ttk.Frame(f, style="Paper.TFrame")
        btns.pack(fill="x", padx=16, pady=(0, 12))
        ttk.Button(btns, text="Ouvrir dans Saisie", command=self._open_selected_day).pack(side="left", padx=(0, 10))
        ttk.Button(btns, text="🖨 Imprimer ce jour", command=self._print_selected_history).pack(side="left")

    def _refresh_historique(self):
        self.tree_hist.delete(*self.tree_hist.get_children())
        for rec in list_jours():
            self.tree_hist.insert("", "end", iid=rec["date"], values=(
                rec["date"], fmt(rec["recettes"]), fmt(rec["total_depenses"]), fmt(rec["final"])
            ))

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
        ttk.Button(top, text="Actualiser", command=self._refresh_dashboard).pack(side="left", padx=8)

        self.txt_dash = tk.Text(f, font=("Consolas", 11), bg=PAPER, fg=WALNUT, relief="flat",
                                 height=26, wrap="word")
        self.txt_dash.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def _refresh_dashboard(self):
        stats = monthly_stats(self.var_month.get().strip())
        self.txt_dash.config(state="normal")
        self.txt_dash.delete("1.0", "end")
        self.txt_dash.insert("end", f"RÉSUMÉ DU MOIS {self.var_month.get()}\n")
        self.txt_dash.insert("end", "=" * 46 + "\n\n")
        self.txt_dash.insert("end", f"Jours enregistrés ......... {stats['nb_jours']}\n")
        self.txt_dash.insert("end", f"Total recettes ............ {fmt(stats['total_recettes'])}\n")
        self.txt_dash.insert("end", f"Total dépenses ............ {fmt(stats['total_depenses'])}\n\n")
        self.txt_dash.insert("end", "Dépenses par catégorie :\n")
        self.txt_dash.insert("end", "-" * 46 + "\n")
        maxv = max(stats["par_categorie"].values(), default=1)
        for cat, montant in sorted(stats["par_categorie"].items(), key=lambda x: -x[1]):
            bar = "█" * max(1, int(montant / maxv * 24)) if maxv else ""
            self.txt_dash.insert("end", f"{cat:<24} {bar}\n    {fmt(montant)}\n\n")
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
