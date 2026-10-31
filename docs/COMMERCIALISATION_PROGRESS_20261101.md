# État de préparation commerciale — 1 novembre 2026

Cette note consolide des vérifications reproductibles du dépôt et l’état observé des services le 1 novembre 2026. Elle distingue les tests de code, la démonstration hébergée et les preuves requises avant une commercialisation. Elle ne vaut ni approbation clinique, ni qualification juridique, ni engagement d’exploitation.

## État technique vérifié

- La CI GitHub de la PR #26 (run 97) réussit la suite de tests complète, le build de l’image Docker, le démarrage de cette image sous un compte non privilégié, l’exécution des migrations sur une base SQLite fictive jetable, et la requête database-aware `/healthz/`.
- Les 16 tests de `catalog.tests_authoring` passent sur le checkout local. Ils couvrent la création d’activité à partir d’une fiche vide, les permissions d’édition séparées de la relecture/publication, les interfaces FR/EN/AR, et le compte fictif Pitou sans privilèges staff ou superuser.
- La PR #25 fournit une préparation hors ligne à la relecture de 42 brouillons MSA v1 et 32 brouillons Darija v2, avec une grille audio, images et sources. Elle n’importe ni n’approuve les contenus.
- Les PR #25 et #26 sont ouvertes, CI verte, non fusionnées et non déployées au moment de cette observation.

Ces résultats établissent des comportements logiciels dans leur périmètre testé. Ils ne démontrent ni l’efficacité thérapeutique de Nehedrou, ni la justesse de chaque mot ou de chaque variété, ni la sécurité de l’exploitation sur des dossiers réels.

## Configuration Render observée

L’API Render a indiqué que `nehedrou-demo` est un service web au plan gratuit, dans la région Frankfurt, rattaché à `main`, avec un déploiement déclaré `live` sur le commit `85a66603cfbcadc0a8490c1c5b8fbc964bcaff08`. `main` était au commit `feed05dbf76a159a4fcebac1737784ff4d6d188f`; la seule différence entre les deux révisions était une note dans `docs/COMMERCIALISATION_PROGRESS_20261031.md`.

Deux écarts de configuration sont à résoudre dans le tableau de bord Render, puis à relire dans l’API après application :

1. le service actif a `healthCheckPath` vide alors que `render.yaml` déclare `/healthz/` ;
2. le service actif a l’auto-déploiement sur commits activé alors que `render.yaml` demande `autoDeployTrigger: "off"`.

Le workspace ne contient pas de base Render gérée. Le blueprint du service indique l’usage d’une base PostgreSQL et d’un stockage média S3 externes ; cela ne prouve ni la persistance de chaque objet, ni une sauvegarde restaurable, ni le statut du projet externe. Render indique que le déploiement de ce commit est `live` ; une vérification HTTP et une recette navigateur publique des trois langues n’ont pas été répétées dans le cadre de cette note.

## Ce que le plan gratuit permet — et ne permet pas

Render précise que ses services gratuits sont destinés aux essais, démonstrations et projets personnels, et **ne doivent pas être utilisés pour des applications de production**. Un service web gratuit s’endort après 15 minutes sans trafic, peut prendre environ une minute à se réveiller et possède un système de fichiers éphémère. Des limites de bande passante ou un volume élevé de trafic sortant vers une base ou un stockage externe peuvent suspendre le service. Le plan gratuit ne peut pas avoir de disque persistant et ne permet pas les connexions SMTP sortantes sur les ports 465 et 587. Voir la [documentation officielle Render sur les services gratuits](https://render.com/docs/free).

La page tarifaire Render consultée le 1 novembre 2026 affiche un service web Starter à 7 USD/mois ; le montant n’inclut pas nécessairement le coût d’une base, d’un stockage durable, du transfert, du domaine, des sauvegardes ou de l’assistance. Voir [les tarifs Render](https://render.com/pricing).

Au même relevé, l’offre gratuite Neon inclut par projet 100 CU-heures mensuelles, 1 Go de stockage PostgreSQL, 5 Go de stockage objet et une allocation de transfert réseau public. À épuisement de 100 CU-heures ou 5 Go de transfert, le compute est suspendu jusqu’à la période suivante ; au-delà de 1 Go en base, les opérations qui augmentent le stockage échouent. Ces limites rendent le gratuit utile pour la démo, mais ne constituent pas un engagement de disponibilité ou de sauvegarde de production. Vérifier le plan et l’usage actuels du projet Nehedrou dans Neon avant toute ouverture commerciale. Voir la [tarification officielle Neon](https://neon.com/pricing).

Le budget communiqué pour le moment est de 0 EUR/mois. Dans ce cadre, le service doit rester clairement présenté comme une démonstration, sans dossiers réels, sans promesse de disponibilité et sans vente d’un service thérapeutique. Un lancement commercial durable nécessite un budget récurrent accepté et une vérification de coûts complets, ou un autre hébergement dont les conditions conviennent réellement à la production.

## Conditions restantes avant lancement commercial

### Contenus et usage clinique

- Faire relire chaque contenu par des personnes compétentes, natives ou expertes de la variété annoncée, et un orthophoniste distinct de l’auteur lorsque c’est possible.
- Confirmer région, registre, formes parlées, sens, illustrations et familiarité des mots. Pour les 10 propositions MSA classées comme contrastes, valider séparément les formes phonologiques et la pertinence pour le profil visé. Aucune paire Darija n’est déclarée minimale dans le paquet.
- Créer des enregistrements modèles uniquement après validation de la forme orale exacte, avec locuteur adulte compétent, consentement et droits vérifiables. Aucune activité ou aucun enregistrement n’est approuvé par le dossier de relecture.
- Séparer la preuve concernant une approche professionnelle de la validation clinique de l’application elle-même. Ne publier aucun résultat d’efficacité ou témoignage absent.

### Exploitation et obligations

- Obtenir l’accord pour un budget durable ; choisir un service web qui ne s’endort pas, une base et un stockage durables, des sauvegardes hors site et une procédure de restauration testée.
- Corriger puis vérifier dans Render les écarts du health check et de l’auto-déploiement ; documenter le commit exact et une recette navigateur FR/EN/AR après déploiement autorisé.
- Tester réellement l’envoi et la réception des invitations et de la récupération de compte avec un transport HTTPS ou SMTP autorisé ; le résultat de readiness de configuration seul n’atteste pas la livraison.
- Confirmer le registre de traitements, les durées de conservation, les responsabilités, l’assistance, les conditions d’usage et les obligations des marchés ciblés avec les personnes compétentes.
- Compléter le rapport `check_readiness --strict` sur la configuration de production réelle, sans transmettre ni consigner les secrets, et réaliser un exercice de restauration à partir d’une sauvegarde de production autorisée.

Les tests automatisés ne peuvent pas combler l’absence de validation humaine, d’un budget accepté, d’une livraison email vérifiée, d’une sauvegarde opérationnelle ou d’une conformité vérifiée pour les marchés visés. Nehedrou n’est donc pas encore qualifiée pour une vente telle quelle.
