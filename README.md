# Livre de Caisse — Les Cinq Frères

Application de bureau **100% locale**. Aucune connexion internet, aucune donnée envoyée
en ligne : tout est stocké dans un fichier `caisse.db` (base SQLite) créé automatiquement
à côté du programme, sur l'ordinateur de la société.

## 1. Lancer l'application (besoin de Python, une seule fois)

1. Installer Python 3 (gratuit) depuis https://www.python.org/downloads/ si ce n'est pas déjà fait
   (cocher "Add Python to PATH" pendant l'installation).
2. Placer `caisse_app.py` dans un dossier, par exemple `C:\CaisseCinqFreres\`.
3. Double-cliquer dessus, ou ouvrir un terminal dans ce dossier et taper :
   ```
   python caisse_app.py
   ```
   (`tkinter` est inclus avec Python, aucune autre installation n'est nécessaire)

## 2. Transformer en vrai logiciel .exe (optionnel, pour ton patron)

Pour avoir une icône double-clic sans que personne n'ait besoin d'installer Python :

```
pip install pyinstaller
pyinstaller --onefile --windowed --name "CaisseCinqFreres" caisse_app.py
```

Le fichier `CaisseCinqFreres.exe` sera généré dans le dossier `dist/`. Copie-le où tu veux
sur l'ordinateur de la société — il fonctionne sans internet et sans Python installé.

**Important** : garde le `.exe` (ou le script) et le fichier `caisse.db` qu'il génère dans
le même dossier — c'est là que sont stockées toutes les journées enregistrées.

## 3. Fonctionnalités actuelles

- Saisie du solde initial, des recettes du jour, et des dépenses une par une
  (motif + catégorie + montant)
- Catégorie dédiée **« Versement banque »** pour les dépôts en banque
- Calcul automatique du montant final en caisse
- Historique de toutes les journées, modifiable en double-cliquant
- Justificatif (photo ou PDF de facture) attachable à chaque dépense, consultable
  à tout moment même si le papier d'origine est perdu — stocké dans le dossier
  `justificatifs/`
- Tableau de bord mensuel : total recettes/dépenses et répartition par catégorie
- Impression : génère une page propre et l'ouvre dans le navigateur (Ctrl+P pour
  imprimer sur papier ou enregistrer en PDF) — fonctionne aussi hors ligne

## 4. Sauvegarde

Le fichier `caisse.db` contient toutes les données, et le dossier `justificatifs/`
contient les photos/PDF de factures attachées aux dépenses. Pense à sauvegarder
**les deux ensemble** de temps en temps (clé USB, dossier partagé de la société)
pour ne jamais perdre l'historique ni les justificatifs.

## 5. Prochaines évolutions possibles

- Saisie vocale des dépenses
- Reconnaissance automatique de tickets/factures (photo → montant + motif détectés)
- Alerte automatique quand le montant en caisse dépasse un seuil
- Accès partagé entre plusieurs postes du magasin (mode réseau local)
