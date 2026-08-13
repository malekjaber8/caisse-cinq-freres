# Livre de Caisse — Les Cinq Frères

Application de bureau **100% locale**. Aucune connexion internet, aucune donnée envoyée
en ligne : tout est stocké dans un fichier `caisse.db` (base SQLite) créé automatiquement
à côté du programme, sur l'ordinateur de la société.

## 1. Lancer l'application (besoin de Python, une seule fois)

1. Installer Python 3 (gratuit) depuis https://www.python.org/downloads/ si ce n'est pas déjà fait
   (cocher "Add Python to PATH" pendant l'installation).
2. Placer tout le dossier du projet (`caisse_app.py`, `Lancer Livre de Caisse.pyw`, `assets/`...)
   dans un dossier, par exemple `C:\CaisseCinqFreres\`.
3. Pour l'usage quotidien : **double-clique sur `Lancer Livre de Caisse.pyw`** — ça ouvre
   uniquement la fenêtre de l'application, sans fenêtre noire de terminal à côté.
   (`tkinter` est inclus avec Python, aucune autre installation n'est nécessaire)

   Pour le développement/débogage (voir les messages d'erreur éventuels dans un terminal),
   utilise plutôt `caisse_app.py` directement :
   ```
   python caisse_app.py
   ```

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

- **Connexion protégée par mot de passe** à l'ouverture (avec question de secours
  pour réinitialiser en cas d'oubli)
- Système **mensuel** : le solde de départ se saisit une seule fois, au premier
  jour du mois ; ensuite il est reporté automatiquement chaque jour
- Sélection de la date via un **calendrier** (les jours déjà saisis sont repérés)
- Saisie des recettes du jour et des dépenses une par une (motif + catégorie + montant),
  **modifiables** directement après coup (pas besoin de supprimer/ressaisir)
- Catégorie dédiée **« Versement banque »** pour les dépôts en banque — comptée à
  part des vraies dépenses (ce n'est pas une dépense, juste un déplacement d'argent),
  mais toujours déduite du montant en caisse
- Calcul automatique du montant final en caisse
- Justificatif (photo ou PDF de facture) attachable à chaque dépense, consultable
  à tout moment même si le papier d'origine est perdu — stocké dans le dossier
  `justificatifs/`
- Historique de toutes les journées avec calendrier intégré
- Tableau de bord mensuel : total recettes/dépenses et répartition par catégorie
- **Rapports hebdomadaire, mensuel et annuel imprimables**, et **export CSV** (format
  Excel français) pour le comptable : résumé, catégories, détail jour par jour (ou
  mois par mois pour l'année), journal complet des mouvements
- Verrouillage automatique des jours passés (modification protégée par mot de passe)
  avec journal des modifications (qui a changé quoi, et quand)
- Gestion des catégories de dépenses directement depuis l'application
- Impression des fiches et rapports : génère une page propre et l'ouvre dans le
  navigateur (Ctrl+P pour imprimer sur papier ou enregistrer en PDF) — fonctionne
  aussi hors ligne

## 4. Sauvegarde

Une **sauvegarde automatique** de `caisse.db` (et des justificatifs) est faite une
fois par jour, à l'ouverture de l'application, dans le dossier `sauvegardes/`
(conservée 30 jours). Un bouton **« 💾 Sauvegarder maintenant »** dans l'onglet
Tableau de bord permet aussi de le faire à tout moment.

Cette sauvegarde reste néanmoins **sur le même ordinateur** : pense à copier de
temps en temps `caisse.db`, `justificatifs/` et `sauvegardes/` sur une clé USB ou
un dossier partagé de la société, pour être protégé même en cas de panne du disque.

## 5. Mot de passe oublié

Sur l'écran de connexion, clique sur **« Mot de passe oublié ? »** et réponds à la
question de secours définie lors de la première configuration. Si la question de
secours a aussi été oubliée, il faut qu'une personne ayant accès au fichier
`caisse.db` supprime les lignes `password_hash`/`password_salt` de la table
`app_config` (via un outil SQLite) pour repartir sur une configuration neuve.

## 6. Prochaines évolutions possibles

- Saisie vocale des dépenses
- Reconnaissance automatique de tickets/factures (photo → montant + motif détectés)
- Alerte automatique quand le montant en caisse dépasse un seuil
- Accès partagé entre plusieurs postes du magasin (mode réseau local)
