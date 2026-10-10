# Nehedrou — نهدروا

Application Django de pratique à domicile choisie par un orthophoniste et accompagnée par la famille. Interface FR/EN/AR, Tajawal locale et RTL pour l’arabe. Le premier module vise les enfants de 4–7 ans déjà évalués par un professionnel.

**État : démonstration fonctionnelle avec données fictives, sans feu vert pour la vente clinique.** Les 60 contenus candidats attendent la validation professionnelle ; aucun modèle audio clinique approuvé n’est livré. Voir [la qualification commerciale](docs/QUALIFICATION_COMMERCIALE.md), [la recherche produit](docs/RECHERCHE_PRODUIT.md) et [les conditions de lancement](docs/LANCEMENT.md).

## Dossier actif et démarrage sur E:

- Projet : `E:\LocalCoderWorkspace\Nehdrou\outputs\nehdrou`
- Python préparé : `E:\LocalCoderWorkspace\Nehdrou\work\venv\Scripts\python.exe`
- Lanceur : `E:\LocalCoderWorkspace\Nehdrou\Demarrer-Nehdrou.cmd`

Ouvrir le lanceur, puis http://127.0.0.1:8000/fr/. Les versions anglaise et arabe sont /en/ et /ar/. Si le serveur est déjà actif, ne pas lancer une seconde instance. Ctrl+C l’arrête. La copie précédente sur C: est conservée.

**Découvrir sans compte :** /fr/try/, /en/try/ ou /ar/try/. L’exemple guidé présente les images, le choix et une synthèse fictive. Il ne consulte pas de dossier, ne sauvegarde pas de rapport et est désactivé hors mode démonstration.

Les comptes locaux sont `praticien`, `famille`, `autre_praticien` et `editorial`. Le mot de passe de démonstration se trouve localement dans `.demo-password` ; start.py l’affiche au démarrage. Les comptes existants ne sont pas réinitialisés. Secrets et base fictive sont exclus de l’archive.

## Parcours et fonctions

Le praticien crée un profil minimal, choisit la variété parlée, attribue un programme et invite la famille. La famille pratique avec les consignes choisies et rapporte participation/difficultés. Le praticien retrouve les rapports, publie des conseils partagés à la famille et conserve des observations privées distinctes. L’application ne note pas la prononciation et n’enregistre pas la voix des enfants.

Nouveautés : retour partagé du praticien, historique complet filtrable/paginé, rapports lisibles, médias vérifiés et immuables, export schéma 2 ; parcours ordonné avec reprise, essai conservé après rechargement, bilan partagé et clôture sans rapport fictif ; objectif du programme, ordre réglable et synthèse avant attribution, accueil familial direct, arrêt précoce, réponses explicites et revue hebdomadaire des difficultés. Voir [le parcours de pratique](docs/PARCOURS_PRATIQUE.md) et [les fonctions finalisées](docs/FINALISATION_FONCTIONNELLE.md).

Fonctions présentes : cabinets et droits par dossier, invitations révocables, MFA TOTP et récupération, catalogue versionné, droits éditoriaux par variété, deux relectures avant publication réelle, médias protégés, programmes ajustables, archivage/réattribution, historique, impression/export, facturation manuelle et demandes d’effacement avec décision documentée.

La langue de l’interface, celle des consignes et la variété parlée sont distinctes. Changer un menu ne traduit pas les mots d’un exercice ni le texte écrit par un professionnel. Les copies fictives du catalogue ne sont attribuables qu’en DEMO_MODE.

## Vérifications de la qualification 6

102 tests réussis sur PostgreSQL 17.11, aucun ignoré ; SQLite : 96 réussis et 6 cas de concurrence explicitement ignorés. Restauration locale isolée réussie sur 36 tables, avec exports et permissions recontrôlés. 609 messages par langue ; 574 clés d'interface, zéro manque. Contrôles Django/migrations et syntaxe JavaScript réussis. La recette Chrome sur ordinateur, tablette et mobile a identifié puis permis de corriger un blocage CSRF réel. Voir [la qualification](docs/QUALIFICATION_COMMERCIALE.md) et [la recette navigateur](docs/RECETTE_NAVIGATEUR.md) pour les périmètres et limites ; aucune validation clinique, relecture native ou certification WCAG n'est revendiquée.

## Installation sur une autre machine

Pour tester en ligne, voir [le déploiement Render](docs/DEPLOIEMENT_RENDER.md) et `render.yaml`. La démonstration gratuite hébergée emploie une base temporaire indépendante ; ses modifications peuvent disparaître. Le mode clinique continue à exiger PostgreSQL.

Utiliser une installation Python 3.12 à jour avec pip. Le lanceur portable `python start.py` crée `.venv` si aucun environnement préparé n’est trouvé, installe les versions et empreintes de `requirements.lock`, puis initialise la démonstration. Sous Windows, le Python de l’environnement est `.venv\Scripts\python.exe` ; sous Linux/macOS, `.venv/bin/python`.

Commandes utiles avec le Python de l’environnement : `manage.py check`, `manage.py test`, `manage.py makemigrations --check --dry-run`, `scripts/compile_messages.py`, `scripts/check_translations.py`, `manage.py check_readiness --json` et `manage.py check_readiness --strict`. Pour importer un catalogue : `manage.py import_catalog docs/catalog-example.json`, puis `--apply` après contrôle. Les imports restent des brouillons. Les catalogues PO simples fournis sont compilables sans gettext système ; utiliser GNU gettext pour les entrées plurielles avancées.

Docker Compose est prévu pour le développement avec PostgreSQL 17. Définir les secrets documentés dans `.env.example` ; le fichier n’est pas chargé automatiquement. En configuration réelle, Django refuse SQLite et un secret insuffisant, exige la MFA professionnelle et désactive l’administration technique locale.

## Documentation et limites restantes

[Conception et permissions](docs/CONCEPTION.md), [recette](docs/RECETTE.md), [exploitation](docs/EXPLOITATION.md), [finition arabe](docs/FINITION_ARABE.md), [qualification commerciale](docs/QUALIFICATION_COMMERCIALE.md).

La vente clinique demande encore les contenus/audio approuvés, la relecture native et les essais avec familles/praticiens, une recette multi-navigateurs et avec utilisateurs réels, un déploiement HTTPS/SMTP opérationnel, une sauvegarde/restauration de production et des conditions d’exploitation/offre définies. Aucun tarif, témoignage ou résultat thérapeutique n’est inventé.

Code et illustrations originales sous MIT ; licences des dépendances distinctes. Tajawal sous SIL OFL 1.1, texte inclus dans static/fonts/tajawal/OFL.txt. Le logo fourni par le commanditaire est conservé.
