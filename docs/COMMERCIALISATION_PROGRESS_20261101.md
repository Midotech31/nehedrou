# État de préparation commerciale — 1 novembre 2026

Cette note consolide des vérifications reproductibles du dépôt et l’état observé des services le 1 novembre 2026. Elle distingue les tests de code, la démonstration hébergée et les preuves requises avant une commercialisation. Elle ne vaut ni approbation clinique, ni qualification juridique, ni engagement d’exploitation.

## État technique vérifié

- La CI GitHub de la PR #30 (run 128, commit `3f53e6c`) réussit la compilation et le contrôle des traductions, les vérifications Django et des migrations, la suite de tests complète, le build Docker et le test de démarrage HTTP.
- Les 16 tests de `catalog.tests_authoring` passent sur le checkout local. Ils couvrent la création d’activité à partir d’une fiche vide, les permissions d’édition séparées de la relecture/publication, les interfaces FR/EN/AR, et le compte fictif Pitou sans privilèges staff ou superuser.
- La PR #25 fournit une préparation hors ligne à la relecture de 42 brouillons MSA v1 et 32 brouillons Darija v2, avec une grille audio, images, sources et dix affectations de relecture encore vierges. Elle n’importe ni n’approuve les contenus.
- Les PR #25, #26, #27 et #28 ont été fusionnées après CI verte. Le SHA de `main` reste `60ad20c53bae19780992d0c8cb890ec7a1170a17`; la PR #30 est encore ouverte et ses changements ne sont pas publiés.
- Le run 128 de la PR #30 (commit `3f53e6c348a8c4931738d326edfe48d65e2beee6`) a terminé avec succès. Les 11 tests du dossier de relecture et d’export passent aussi localement dans l’environnement virtuel du dépôt, avec une base SQLite jetable. Ces preuves portent sur la branche de la PR; elles ne changent pas le commit de `main` ni le service publié.

Ces résultats établissent des comportements logiciels dans leur périmètre testé. Ils ne démontrent ni l’efficacité thérapeutique de Nehedrou, ni la justesse de chaque mot ou de chaque variété, ni la sécurité de l’exploitation sur des dossiers réels.

## Configuration Render observée après mise à jour

L’API Render confirme que `nehedrou-demo` est un service web au plan gratuit, dans la région Frankfurt, rattaché à `main`. Le déploiement `dep-dbj8457lk1mc738gthkg` est `live` sur le même SHA `60ad20c53bae19780992d0c8cb890ec7a1170a17` que `main`. Le service est donc à jour avec le code fusionné.

Le service conserve `healthCheckPath` vide alors que `render.yaml` déclare `/healthz/`. L’API indique `autoDeploy=yes`, mais le dépôt est rattaché par URL publique; la documentation Render précise qu’une telle source doit être déployée manuellement. Le déploiement observé a été déclenché par API. Ne pas déduire du seul champ API qu’un push Git déclenche une publication. Aucun appel de synchronisation Blueprint n’a été fait.

La vérification HTTP après déploiement a retourné 200 pour `/healthz/`, `/fr/`, `/en/` et `/ar/`. Les pages FR/EN/AR répondent avec le `lang` attendu; AR est `dir=rtl` et référence Tajawal. L’interface arabe charge `nehedrou-child-profile` et réutilise ce fichier comme favicon. Les journaux de requête n’ont montré aucun 5xx entre 00:06 et 00:07 UTC, et les journaux applicatifs aucun niveau `error` entre 00:04 et 00:08 UTC. Cette observation courte est une recette de fumée, pas une mesure de disponibilité. Une recette UI isolée a depuis été réalisée sur ordinateur et sur des fenêtres mobiles de 390×844 et 320×640 pixels.

Un réglage confirmé reste à aligner dans Render; un autre doit être vérifié si la source du service change :

1. le service actif a `healthCheckPath` vide alors que `render.yaml` déclare `/healthz/`; le endpoint renvoie 200 mais n’est pas utilisé comme health check HTTP par Render;
2. L’API renvoie `autoDeploy=yes` tandis que `render.yaml` demande `autoDeployTrigger: "off"`; avec la source actuelle par URL publique, Render documente que le déploiement est manuel. Si la source Git est reconnectée, vérifier alors la politique effective avant d’activer les mises à jour automatiques.

Le workspace ne contient pas de base Render gérée. Le blueprint indique l’usage d’une base PostgreSQL et d’un stockage média S3 externes; cela ne prouve ni la persistance de chaque objet, ni une sauvegarde restaurable. L’inspection Neon en lecture seule du 1 novembre confirme un projet `free_v3`, une rétention d’historique de 21 600 secondes (six heures), aucun instantané manuel et aucun calendrier de sauvegarde configuré. Le compute était idle et sa suspension était intervenue 5 min 19 s après sa dernière activité; aucun changement de réglage n’a été nécessaire pour le laisser s’endormir. La documentation Neon indique que les calendriers automatiques sont réservés aux plans payants et que le stockage des instantanés est facturé selon le volume; aucune sauvegarde payante n’a été configurée. La version actuelle est une démo gratuite. Les parcours publics ont été testés sans connexion authentifiée; les rôles protégés, permissions et scénarios de sauvegarde/restauration ne sont pas couverts par cette recette.

## Instantané en lecture seule du catalogue (1 novembre 2026)

Une requête agrégée en lecture seule sur la branche principale du projet Neon « Nehedrou Demo » dénombre 124 fiches non démonstratives, toutes à l’état brouillon : 22 pour le français de France, 17 pour l’anglais général des États-Unis, 52 pour l’arabe standard et 33 pour la Darija algérienne pilote. Aucun contenu non démonstratif n’est en état de relecture ou publié. Les tables de relecture et de décision de disponibilité ne contiennent aucune ligne. Aucun des 124 brouillons ne référence de fichier audio. Les 114 fiches publiées dans cet instantané sont des copies de démonstration, auxquelles s’ajoutent 8 brouillons et 3 fiches en état de relecture de démonstration.

Cet inventaire agrégé n’expose aucun compte ni dossier individuel. Il confirme qu’aucune fiche réelle n’a encore passé la revue humaine ou reçu une autorisation d’usage. Il décrit la base consultée à cet instant; il ne constitue ni une recette complète de la connexion Render–Neon, ni une validation clinique.

Le rapprochement exact par série et version avec `content/review_packs/ar-initial-review-20261101/candidates_for_review.csv` révèle une divergence de livraison : les 42 fiches MSA du paquet correspondent à 42 versions CMS en brouillon, mais les 32 versions Darija v2 du paquet ne sont pas présentes dans Neon. Les 32 séries correspondantes y restent en version 1. Le paquet ne contient par ailleurs pas 50 autres brouillons CMS : 10 MSA, 1 Darija, 22 FR et 17 EN. Ainsi, seulement 42 des 124 versions de brouillon actuelles correspondent exactement au paquet de revue; 82 versions CMS n’ont pas de couverture exacte dans ce dossier. Il faut réconcilier les versions et préparer la revue des autres contenus avant de considérer qu’un dossier d’avis couvre le catalogue.

Un contrôle structurel complémentaire, en lecture seule, a trouvé des listes family_word_candidates A/B identiques dans 32 des 33 brouillons Darija v1; dans 17 fiches, le premier candidat B est exactement le mot A alors que les deux mots principaux diffèrent. Ce signal ne prouve pas à lui seul une erreur : des formes partagées peuvent être intentionnelles et doivent être confirmées par un locuteur compétent de la variété retenue. La PR #30 ajoute une tâche explicite au dossier de relecture pour faire vérifier ces listes; elle se clôt uniquement après une décision linguistique positive sur l’empreinte exacte, donnée par une personne dont l’autorisation et la compétence restent valides pour cette variété. Aucun texte du CMS n’est modifié, et aucune approbation ou disponibilité n’est créée par cette alerte. Le test local ciblé (11 tests du dossier) passe; ce changement n’est pas encore dans le commit Render publié.

Les 82 versions sans correspondance exacte concernent le paquet statique hors ligne, pas l’absence d’un export dans l’application. Le CMS fournit déjà à l’éditeur un téléchargement daté depuis l’espace « Content quality and review preparation » : il inclut les activités de son périmètre, leurs empreintes exactes, le dossier des pièces à examiner et des champs de revue vierges. Le code testé par la CI de la PR génère ces archives sans dossiers d’enfants, comptes ou secrets, et sans créer de décisions. Le parcours authentifié et le ZIP complet n’ont toutefois pas été testés sur Render; il faut le faire sur place avant d’envoyer le paquet aux relecteurs. Réexporter après chaque modification, puis affecter les versions exactes aux personnes compétentes.

## Recette UI publique réalisée

La recette a utilisé un profil de navigateur Chrome vierge et isolé, sans importer de profil personnel ni accéder à des données réelles. Les pages `/fr/`, `/en/` et `/ar/` ont été ouvertes; leur sélecteur de langue, les liens vers les essais et la navigation publique ont été exercés. Les essais `/fr/try/`, `/en/try/` et `/ar/try/` s’ouvrent et progressent dans les trois étapes. L’essai bloque l’étape suivante lorsqu’aucune réponse n’est sélectionnée. Les écrans présentent explicitement les exemples comme non validés, signalent l’absence d’un score de prononciation et indiquent que le profil/rapport de l’enfant n’est pas conservé. La recette s’est arrêtée avant l’envoi final d’un rapport.

Les contrôles responsive sur FR/EN/AR à 390×844 et sur AR à 320×640 ont confirmé que la largeur du document ne dépasse pas celle de la fenêtre. Le document conserve `lang` approprié et l’arabe `dir=rtl`; les boutons et textes se replient sans défilement horizontal. Les captures de recette restent locales et ne contiennent pas de données utilisateur; elles ne sont pas ajoutées au dépôt public. Aucune connexion à un compte, aucun test des permissions privées et aucune validation clinique ou audio n’ont été effectués.
## Ce que le plan gratuit permet — et ne permet pas

Render précise que ses services gratuits sont destinés aux essais, démonstrations et projets personnels, et **ne doivent pas être utilisés pour des applications de production**. Un service web gratuit s’endort après 15 minutes sans trafic, peut prendre environ une minute à se réveiller et possède un système de fichiers éphémère. Des limites de bande passante ou un volume élevé de trafic sortant vers une base ou un stockage externe peuvent suspendre le service. Le plan gratuit ne peut pas avoir de disque persistant et ne permet pas les connexions SMTP sortantes sur les ports 465 et 587. Voir la [documentation officielle Render sur les services gratuits](https://render.com/docs/free).

La page tarifaire Render consultée le 1 novembre 2026 affiche un service web Starter à 7 USD/mois ; le montant n’inclut pas nécessairement le coût d’une base, d’un stockage durable, du transfert, du domaine, des sauvegardes ou de l’assistance. Voir [les tarifs Render](https://render.com/pricing).

Au relevé du 1 novembre, l’offre gratuite Neon affiche 100 CU-heures mensuelles, 1 Go de stockage PostgreSQL et 5 Go de stockage objet par projet. À épuisement des quotas, le compute peut être suspendu et les opérations qui augmentent le stockage peuvent échouer. Le projet dispose d’une restauration instantanée limitée à six heures, mais n’a ni instantané manuel ni calendrier automatique configuré. Ces limites rendent le gratuit utile pour la démo, mais ne constituent pas une stratégie de sauvegarde restaurable pour la production. Vérifier le plan et l’usage actuels du projet Nehedrou dans Neon avant toute ouverture commerciale. Voir la [tarification officielle Neon](https://neon.com/pricing) et la [documentation Neon sur les sauvegardes](https://neon.com/docs/guides/backup-restore).

Le budget communiqué pour le moment est de 0 EUR/mois. Dans ce cadre, le service doit rester clairement présenté comme une démonstration, sans dossiers réels, sans promesse de disponibilité et sans vente d’un service thérapeutique. Un lancement commercial durable nécessite un budget récurrent accepté et une vérification de coûts complets, ou un autre hébergement dont les conditions conviennent réellement à la production.

## Conditions restantes avant lancement commercial

### Contenus et usage clinique

- Faire relire chaque contenu par des personnes compétentes, natives ou expertes de la variété annoncée, et un orthophoniste distinct de l’auteur lorsque c’est possible.
- Confirmer région, registre, formes parlées, sens, illustrations et familiarité des mots. Pour les 10 propositions MSA classées comme contrastes, valider séparément les formes phonologiques et la pertinence pour le profil visé. Aucune paire Darija n’est déclarée minimale dans le paquet.
- Créer des enregistrements modèles uniquement après validation de la forme orale exacte, avec locuteur adulte compétent, consentement et droits vérifiables. Aucune activité ou aucun enregistrement n’est approuvé par le dossier de relecture.
- Séparer la preuve concernant une approche professionnelle de la validation clinique de l’application elle-même. Ne publier aucun résultat d’efficacité ou témoignage absent.

### Exploitation et obligations

- Obtenir l’accord pour un budget durable ; choisir un service web qui ne s’endort pas, une base et un stockage durables, des sauvegardes hors site et une procédure de restauration testée.
- Configurer puis vérifier dans Render le health check `/healthz/` et la politique d’auto-déploiement; les réglages du service actif n’ont pas encore été modifiés. Le commit applicatif déployé `60ad20c53bae19780992d0c8cb890ec7a1170a17` a une recette publique FR/EN/AR, mais aucune recette authentifiée.
- Tester réellement l’envoi et la réception des invitations et de la récupération de compte avec un transport HTTPS ou SMTP autorisé ; le résultat de readiness de configuration seul n’atteste pas la livraison.
- Confirmer le registre de traitements, les durées de conservation, les responsabilités, l’assistance, les conditions d’usage et les obligations des marchés ciblés avec les personnes compétentes.
- Compléter le rapport `check_readiness --strict` sur la configuration de production réelle, sans transmettre ni consigner les secrets, et réaliser un exercice de restauration à partir d’une sauvegarde de production autorisée.

Les tests automatisés ne peuvent pas combler l’absence de validation humaine, d’un budget accepté, d’une livraison email vérifiée, d’une sauvegarde opérationnelle ou d’une conformité vérifiée pour les marchés visés. Nehedrou n’est donc pas encore qualifiée pour une vente telle quelle.
