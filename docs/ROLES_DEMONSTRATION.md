# Comptes fictifs et recette par rôle

Les identifiants ci-dessous correspondent à des droits réellement disponibles. Les mots de passe sont livrés séparément dans un document privé ; ce fichier, le dépôt et l’archive n’en contiennent aucun. Utiliser seulement des données fictives. La publication utilise PostgreSQL Neon et un stockage S3 privé persistant depuis la livraison du 11 octobre 2026 ; cette persistance ne qualifie pas un usage clinique.

| Identifiant | Profil disponible | Point d’entrée après connexion | Périmètre |
|---|---|---|---|
| `responsable` | Responsable du cabinet fictif des rôles | `/fr/app/` | Membres, abonnement et paramètres de son cabinet ; dossier Maya dont il est explicitement responsable. Aucun accès automatique au dossier Sami. |
| `orthophoniste` | Orthophoniste du même cabinet | `/fr/app/` | Dossier Sami, ses programmes, rapports, observations privées et conseils partagés. Aucun droit de gestion des membres du cabinet. |
| `accompagnant` | Parent ou accompagnant autorisé | `/fr/app/` | Dossier Sami lié explicitement, programmes dans les trois variétés pilotes, pratique et rapports ; aucune modification clinique. |
| `editeur` | Éditeur et responsable de publication | `/fr/editorial/` | Rédaction, médias, nouvelles versions et transitions sur les trois variétés pilotes. Aucune relecture clinique ou linguistique. |
| `relecteur_clinique` | Relecteur clinique du catalogue | `/fr/editorial/` | Lecture et décisions de sa discipline sur les versions proposées ; aucune rédaction, mise en ligne ou consultation de dossiers. |
| `relecteur_linguistique` | Relecteur linguistique du catalogue | `/fr/editorial/` | Lecture et décisions linguistiques sur les versions proposées ; mêmes restrictions de rédaction, publication et dossiers. |
| `gestionnaire` | Gestionnaire des accès et de la facturation manuelle | `/fr/billing/` | Cabinets, plans, quotas, échéances et factures. Aucun accès aux dossiers, exports cliniques ou catalogue éditorial. |
| `pitou` | Porteur de projet et orthophoniste — compte de démonstration distinct | `/fr/app/` et `/fr/editorial/new/` | Accède comme clinicien au cabinet fictif et peut créer/modifier des brouillons éditoriaux dans les quatre variétés configurées. Ne peut ni publier ni effectuer les relectures clinique/linguistique; n’est ni staff ni superutilisateur. |

Le gestionnaire utilise la permission existante `core.manage_entitlements`. Il n’est ni superutilisateur ni administrateur Django. L’application ne fournit pas d’administration globale des utilisateurs en production ; `/admin/` reste désactivé lorsque `DEBUG=False`. Le responsable de cabinet et le gestionnaire des accès sont donc deux profils distincts.

Quatre comptes historiques restent disponibles : `praticien` (responsable du Cabinet Démonstration, dossiers Lina/Adam/Nour), `famille` (Lina uniquement), `autre_praticien` (autre cabinet, pour tester l’isolation), `editorial` (ancien profil éditorial réunissant les quatre capacités). Ils conservent leurs identifiants, mots de passe et affiliations. Les nouveaux profils séparés permettent de tester les responsabilités sans utiliser ce dernier compte combiné.

## Initialisation

Après les migrations, exécuter `python manage.py seed_demo_roles` en mode `DEMO_MODE=1`. La commande initialise aussi les exemples historiques et le catalogue candidat fictif nécessaire aux nouveaux programmes. Elle crée le cabinet stable « Cabinet Parcours des rôles · fictif », deux dossiers distincts et les affiliations explicites. Les quotas de ce cabinet sont fixés à sa création, sans relever ceux d’un ancien cabinet.

Les secrets sont lus depuis `DEMO_PASSWORD` pour les comptes historiques et, pour les nouveaux comptes, depuis :

- `DEMO_PASSWORD_RESPONSABLE`
- `DEMO_PASSWORD_ORTHOPHONISTE`
- `DEMO_PASSWORD_ACCOMPAGNANT`
- `DEMO_PASSWORD_EDITEUR`
- `DEMO_PASSWORD_RELECTEUR_CLINIQUE`
- `DEMO_PASSWORD_RELECTEUR_LINGUISTIQUE`
- `DEMO_PASSWORD_GESTIONNAIRE`

Chaque secret doit comporter au moins 12 caractères. Une variable de rôle absente utilise `DEMO_PASSWORD` comme repli local ; pour la démonstration publiée, configurer les sept secrets distincts dans l’environnement privé. Aucun secret n’est affiché par la commande.

Le compte de démonstration distinct `pitou` est initialisé uniquement lorsque le secret privé `DEMO_PASSWORD_PITOU` est configuré; il exige au moins 20 caractères. La lecture agrégée Neon du 1 novembre 2026 confirme son compte actif, son affiliation fictive et ses droits de brouillon sur quatre variétés, sans droits de publication ou de relecture. Son dernier `last_login` enregistré (30 octobre 2026) indique une connexion antérieure, pas une recette d’authentification actuelle. Aucun nouvel essai de connexion Pitou n’a été soumis lors de cet audit; ne pas diffuser son secret dans le dépôt public.

La commande est idempotente. Elle ne réinitialise ni mot de passe existant, ni état d’affiliation existant, ni programme, ni quota modifié. Un identifiant ou une adresse réservés déjà occupés par un compte non fictif, un compte privilégié inattendu ou une affiliation non fictive provoquent un refus et l’annulation de la transaction. Un groupe éditorial partagé avec de vrais utilisateurs n’est pas modifié.

## Recette utile

1. Avec `responsable`, ouvrir les membres, l’abonnement, les paramètres et Maya. L’ouverture directe de Sami ou d’un dossier de l’ancien cabinet doit être refusée. Avec `orthophoniste`, ouvrir Sami et son attribution de programme ; les pages de gestion du cabinet doivent être refusées.
2. Avec `accompagnant`, exécuter un parcours attribué en FR, EN puis AR et retrouver les rapports. Avec `orthophoniste`, ajouter un conseil partagé et une observation privée. Le conseil doit apparaître chez l’accompagnant ; l’observation privée doit rester absente de son écran et de son export.
3. Avec les deux relecteurs, ouvrir une « Relecture fictive » en cours de relecture, puis déposer une décision dans sa propre discipline. Une décision de l’autre discipline, une publication, un clonage ou un téléversement doit être refusé. Les exemples de relecture sont explicitement fictifs et ne valident aucun contenu clinique.
4. Avec `editeur`, créer une nouvelle version et ouvrir un brouillon. Les décisions de relecture doivent être refusées. La publication d’une version clinique réelle reste soumise aux champs, médias et deux relectures exigés par le catalogue.
5. Avec `gestionnaire`, ouvrir un cabinet, modifier un plan fictif et enregistrer une facture fictive. Un lien direct vers Sami, son export ou un programme doit être refusé. Aucun pseudonyme d’enfant ni rapport clinique ne doit être présenté dans la facturation.
6. Reconnecter `famille` et vérifier Lina ; reconnecter `autre_praticien` et vérifier que les autres cabinets restent inaccessibles. Relancer l’initialisation avec des variables différentes et vérifier que les mots de passe existants n’ont pas changé.

Lorsque `MFA_REQUIRED=1`, les profils professionnels, éditoriaux et de gestion restent soumis à la MFA. Le mode de présentation fictive peut utiliser `MFA_REQUIRED=0` ; l’initialisation ne désactive pas cette protection elle-même.

Vérification automatisée isolée : `python manage.py test core.tests_demo_roles`. Ces tests utilisent exclusivement des secrets synthétiques et la base de test ; ils ne prouvent ni efficacité clinique ni recette de navigateur.