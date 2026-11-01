# Nehedrou — نهدروا

État courant : [checklist de lancement Algérie du 1 novembre 2026](docs/CHECKLIST_LANCEMENT_ALGERIE_20261101.md). Les validations humaines, l’entité vendeuse et l’exploitation de production restent distinctes de la recette logicielle.
Application Django de pratique à domicile choisie par un orthophoniste et accompagnée par la famille. Interface FR/EN/AR, Tajawal locale et RTL pour l’arabe. Le premier module vise les enfants de 4–7 ans déjà évalués par un professionnel.

**Situation au 1 novembre 2026 : démonstration fonctionnelle avec données fictives, sans ouverture clinique.** Le contrôle Neon en lecture seule de 20:18 UTC confirme 111 séries courantes réelles, toutes en brouillon : 19 pour fr-FR, 17 pour en-US, 42 pour ar-MSA et 33 pour ar-DZ pilote. Chacune manque d'au moins une référence audio A/B ; aucune revue d'activité réelle (non démo), aucune déclaration de compétence et aucune entrée active du registre de traitement de plateforme n'est enregistrée. Les responsables des vraies publications ne sont pas désignés ; entité juridique, fournisseur de courriels et domaine restent indéfinis. Les copies de démonstration sont des objets distincts et ne valident pas ces contenus. Cet instantané est daté ; régénérer la situation de la base configurée avec manage.py content_inventory --json ; voir [les définitions et la portée du catalogue](docs/INVENTAIRE_CONTENUS.md), [les pièces manquantes](docs/PIECES_MANQUANTES.md) et [les conditions de lancement](docs/LANCEMENT.md).

**Démonstration publiée sur Render :** [français](https://nehedrou-demo.onrender.com/fr/), [anglais](https://nehedrou-demo.onrender.com/en/), [arabe](https://nehedrou-demo.onrender.com/ar/). Les accès aux comptes fictifs sont livrés séparément dans un document local privé. La publication utilise la base PostgreSQL Neon dédiée et le stockage S3 privé persistant documentés depuis le 11 octobre 2026 ; le plan Render gratuit conserve sa veille et ses limites. Cette persistance n'autorise aucun dossier réel : utiliser uniquement des données fictives. Voir [la recette de publication](docs/DEPLOIEMENT_RENDER.md).

PR45 `78422207` est active depuis le 1 novembre à 20:14:28 UTC ; `/healthz/` public a répondu HTTP 200, `status: ok`. La [checklist courante](docs/CHECKLIST_LANCEMENT_ALGERIE_20261101.md#état-publié-après-pr45--1-novembre-2026) détaille la CI258 et les preuves datées. Aucune recette visuelle postérieure à PR45 n'est déclarée. La capture privée et sa restauration PostgreSQL locale isolée du 1 novembre précèdent PR44 ; leurs contrôles et limites figurent dans [le guide d'exploitation](docs/EXPLOITATION.md#capture-et-restauration-contrôlées--1-novembre-2026). Elles ne prouvent ni copie hors machine, ni planification ou objectifs de reprise.

[Livraison des quatre améliorations urgentes](docs/AMELIORATIONS_URGENTES.md) : logo de l’enfant parlant, guides étayés avec statuts explicites, sept rôles séparés et crédit de conception dans les trois langues.

[Suivi descriptif professionnel](docs/SUIVI_CLINIQUE.md) : objectifs cliniques, sondes originales versionnées, cotations humaines, rapports privés CSV/imprimables, corrections motivées et partage textuel révocable. Deux protocoles FR/EN de conception restent en brouillon ; des copies fictives et six fiches parentales FR/EN/AR permettent la recette. Le [registre des contenus et droits](docs/CONTENUS_ET_DROITS.md) et la [liste précise des pièces manquantes](docs/PIECES_MANQUANTES.md) séparent développement, relecture, pilote, autorisation d'usage et efficacité.

## Dossier actif et démarrage sur E:

- Projet : `E:\LocalCoderWorkspace\Nehdrou\outputs\nehdrou`
- Python préparé : `E:\LocalCoderWorkspace\Nehdrou\work\venv\Scripts\python.exe`
- Lanceur : `E:\LocalCoderWorkspace\Nehdrou\Demarrer-Nehdrou.cmd`

Ouvrir le lanceur, puis http://127.0.0.1:8000/fr/. Les versions anglaise et arabe sont /en/ et /ar/. Si le serveur est déjà actif, ne pas lancer une seconde instance. Ctrl+C l’arrête. Le chantier et ses pièces de travail ont été transférés sur E: le 30 octobre 2026, après vérification SHA‑256 ; utiliser exclusivement cette copie active.

**Découvrir sans compte :** /fr/try/, /en/try/ ou /ar/try/. L’exemple guidé présente les images, le choix et une synthèse fictive. Il ne consulte pas de dossier, ne sauvegarde pas de rapport et est désactivé hors mode démonstration.

Sept comptes distincts permettent de tester les droits : `responsable`, `orthophoniste`, `accompagnant`, `editeur`, `relecteur_clinique`, `relecteur_linguistique` et `gestionnaire`. Les comptes historiques `praticien`, `famille`, `autre_praticien` et `editorial` restent disponibles. Les [rôles et leurs restrictions](docs/ROLES_DEMONSTRATION.md) sont documentés sans mot de passe. Le mot de passe local par défaut se trouve dans `.demo-password` ; les sept secrets hébergés sont distincts et transmis dans un document privé. Les comptes existants ne sont pas réinitialisés. Secrets et bases sont exclus du dépôt et de l’archive.

## Audit et parcours complétés

Le [compte rendu de publication du 30 octobre](docs/LIVRAISON_CORRECTIONS_20261030.md) consigne tests et limites. La [checklist A01–A17 du 30 octobre 2026](docs/CORRECTIONS_AUDIT_20261030.md) distingue corrections testées, préparation technique et pièces humaines encore absentes : continuité des dossiers, contextes des sondes, droits/audio, authentification, export v3, langues et pratique guidée. Le [petit pack de six images](docs/GENERATED_IMAGE_REVIEW_PACK_20261030.md) reste à examiner ; [l’offre pilote](docs/OFFRE_PILOTE_A_VALIDER.md) attend les décisions du porteur.

Voir [l’audit comparatif du 11 octobre 2026](docs/AUDIT_COMPARATIF_20261011.md). La préparation de programme permet désormais de filtrer par objectif, thème et mode de réponse, de rechercher les mots et d’ouvrir les consignes sans perdre la sélection. Le professionnel peut définir un calendrier facultatif ; la famille voit les prochaines dates et peut télécharger un agenda générique sans nom d’enfant. Le bilan par activité distingue participation, demandes d’aide et réponses aux tâches fermées.

## Parcours et fonctions

Le praticien crée un profil minimal, choisit la variété parlée, attribue un programme et invite la famille. La famille pratique avec les consignes choisies et rapporte participation/difficultés. Le praticien retrouve les rapports, publie des conseils partagés à la famille et conserve des observations privées distinctes. L’application ne calcule pas automatiquement la qualité de la prononciation et n’enregistre pas la voix des enfants. Le module de suivi recueille séparément les cotations descriptives saisies par le professionnel responsable.

Nouveautés : retour partagé du praticien, historique complet filtrable/paginé, rapports lisibles, médias vérifiés et immuables, export professionnel complet et export familial filtré au schéma 3 ; parcours ordonné avec reprise, essai conservé après rechargement, bilan partagé et clôture sans rapport fictif ; objectif du programme, ordre réglable et synthèse avant attribution, accueil familial direct, arrêt précoce, réponses explicites et revue hebdomadaire des difficultés. Voir [le parcours de pratique](docs/PARCOURS_PRATIQUE.md) et [les fonctions finalisées](docs/FINALISATION_FONCTIONNELLE.md).

Fonctions présentes : cabinets et droits par dossier, invitations révocables, MFA TOTP et récupération, catalogue versionné, droits éditoriaux par variété, invitations éditoriales à privilèges limités et révocables, deux relectures avant publication réelle, médias protégés, programmes ajustables, archivage/réattribution, historique, impression/export, facturation manuelle et demandes d’effacement avec décision documentée.

La langue de l’interface, celle des consignes et la variété parlée sont distinctes. Changer un menu ne traduit pas les mots d’un exercice ni le texte écrit par un professionnel. Les copies fictives du catalogue ne sont attribuables qu’en DEMO_MODE.

## Vérifications de la qualification 6

Les tests couvrent les parcours, l’isolation des dossiers, les permissions, la pratique avec reprise, les relectures, l’intégrité des versions et le démarrage hébergé. Les cas de concurrence exigent PostgreSQL et sont explicitement ignorés sous SQLite. Les rapports des livraisons précédentes restent dans la [qualification](docs/QUALIFICATION_COMMERCIALE.md) et la [recette navigateur](docs/RECETTE_NAVIGATEUR.md). Les vérifications logicielles ne constituent ni une validation clinique, ni une relecture native, ni une certification d’accessibilité.

## Installation sur une autre machine

Pour tester en ligne, voir [le déploiement Render](docs/DEPLOIEMENT_RENDER.md) et `render.yaml`. Le Blueprint est aligné sur PostgreSQL Neon et un stockage S3 privé durable ; ne pas recréer l'ancienne configuration SQLite temporaire sur le service existant. SQLite reste réservé aux démonstrations locales ou à une option éphémère explicitement choisie. Le mode clinique exige PostgreSQL.

Utiliser une installation Python 3.12 à jour avec pip. Le lanceur portable `python start.py` crée `.venv` si aucun environnement préparé n’est trouvé, installe les versions et empreintes de `requirements.lock`, puis initialise la démonstration. Sous Windows, le Python de l’environnement est `.venv\Scripts\python.exe` ; sous Linux/macOS, `.venv/bin/python`.

Commandes utiles avec le Python de l’environnement : `manage.py check`, `manage.py test`, `manage.py makemigrations --check --dry-run`, `scripts/compile_messages.py`, `scripts/check_translations.py`, `manage.py check_readiness --json`, `manage.py check_readiness --strict` et `manage.py content_inventory --json`. Pour importer un catalogue : `manage.py import_catalog docs/catalog-example.json`, puis `--apply` après contrôle. Les imports restent des brouillons. Les catalogues PO simples fournis sont compilables sans gettext système ; utiliser GNU gettext pour les entrées plurielles avancées.

Les [transports de courriels](docs/EMAIL_TRANSPORTS.md) sont sélectionnés explicitement : SMTP lorsque l’hébergement le permet, ou HTTPS avec activation et paramètres privés. Le transport hébergé reste désactivé par défaut. Un diagnostic de configuration ne prouve ni envoi ni réception ; domaine/expéditeur, fournisseur et recette réelle restent à accepter. Aucun compte fournisseur, coût récurrent ou quota gratuit durable n’est garanti.

Docker Compose est prévu pour le développement avec PostgreSQL 17. Définir les secrets documentés dans `.env.example` ; le fichier n’est pas chargé automatiquement. En configuration réelle, Django refuse SQLite et un secret insuffisant, exige la MFA professionnelle et désactive l’administration technique locale.

## Documentation et limites restantes

[Conception et permissions](docs/CONCEPTION.md), [recette](docs/RECETTE.md), [exploitation](docs/EXPLOITATION.md), [finition arabe](docs/FINITION_ARABE.md), [qualification commerciale](docs/QUALIFICATION_COMMERCIALE.md).

La vente clinique demande encore les contenus/audio approuvés, la relecture native et les essais avec familles/praticiens, une recette multi-navigateurs et avec utilisateurs réels, un transport de courriels opérationnel, une copie hors machine et une organisation acceptée de la planification, des alertes et de la reprise, ainsi que des conditions d’exploitation/offre définies. La restauration locale isolée déjà vérifiée ne couvre pas à elle seule ces conditions. Aucun tarif, témoignage ou résultat thérapeutique n’est inventé.

Code sous MIT ; les droits des médias dépendent de chaque fichier et de ses justificatifs. Les nouveaux visuels générés restent à examiner ; la licence du code ne qualifie pas leurs droits. Licences des dépendances distinctes. Tajawal sous SIL OFL 1.1, texte inclus dans static/fonts/tajawal/OFL.txt. Le logo fourni par le commanditaire est conservé.

### Création originale dans le CMS

Les éditeurs autorisés peuvent ouvrir **Espace éditorial → Créer une activité de zéro**, renseigner une fiche vide, enregistrer le brouillon et compléter consignes, guides, sources et médias. Les instructions peuvent commencer dans une langue ; un guide ajouté doit inclure ses objectifs, public, étapes, aides et limites. Les détails phonologiques restent soumis aux contrôles structurels et à la relecture humaine. Les médias téléversés sont sélectionnables dans la fiche. L’éditeur avancé conserve l’accès aux métadonnées complètes et variantes.

En démo uniquement, la variable privée facultative `DEMO_PASSWORD_PITOU` (20 caractères minimum) permet à `seed_pitou_demo` d’initialiser le compte fictif explicitement demandé. Il a un rôle de praticien et le droit d’éditer les brouillons des quatre variétés, sans publication ni relecture approuvante. Aucun mot de passe existant, compte réel ou droit révoqué n’est remplacé. Hors démo, les comptes et attributions sont administrés explicitement ; cet initialiseur est interdit.
