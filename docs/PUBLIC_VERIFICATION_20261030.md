# Verification publique du 30 octobre 2026

Code applicatif publie : [dcc8853](https://github.com/Midotech31/nehedrou/commit/dcc88530d4e4213f253c6a78bcc947d9ec167579).

La demonstration [FR](https://nehedrou-demo.onrender.com/fr/try/), [EN](https://nehedrou-demo.onrender.com/en/try/) et [AR](https://nehedrou-demo.onrender.com/ar/try/) a ete verifiee apres ce deploiement. Douze pages publiques repondent HTTP200 ; /healthz/ retourne status=ok. [Resultats HTTP anonymes](verification-20261030/published-http-smoke.json).

Les clics du navigateur de controle ont refonctionne apres reinitialisation de sa session : passages AR vers FR, EN puis AR, erreur immediate et focus au choix manquant, pause/reprise et resume d'arret sans choix verifies sur la demonstration publique. Les observations precedentes du blocage temporaire ne caracterisent pas un defaut serveur.

Tests logiciels isoles : suite PostgreSQL430/430 ; suite SQLite416 reussis et14 reserves a PostgreSQL. Apres le correctif complementaire de livraison des preuves, lot affecte PostgreSQL74/74 et8 nouveaux tests SQLite reussis. Les lots ne sont pas additionnes et les430 ne sont pas presentes comme rejoues apres ce correctif.

Les captures et rapports du CMS prive restent uniquement sur le poste operateur E:, hors GitHub public. Aucun contenu de dossier, secret ou capture privee n'est fourni ici. Les conditions cliniques, linguistiques, de droits et d'exploitation restent a documenter pour une ouverture reelle.

![Rendu de la demonstration publique arabe](verification-20261030/published-ar-mobile.png)
