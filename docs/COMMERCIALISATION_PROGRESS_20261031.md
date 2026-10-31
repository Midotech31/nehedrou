# Progression vers la commercialisation — 31 octobre 2026

La version reste une démonstration. Ce lot corrige des comportements logiciels ; il ne constitue ni une validation clinique de Nehedrou, ni une décision d'ouverture à des données réelles. Le [bilan précédent](COMMERCIALISATION_PROGRESS_20261030.md) reste un historique daté.

## Cabinet affiché et formulaire conservé

Les formulaires de création d'enfant, d'invitation d'un praticien, de paramètres du cabinet et de notice d'information portent un contexte signé : utilisateur, cabinet, opération et version. Le serveur le relit avant toute écriture. Un formulaire ouvert sous A puis envoyé après une bascule de session vers B reçoit HTTP 409 ; ses valeurs et son contexte initial sont conservés pour éviter une attribution silencieuse à B. Le contexte expire après huit heures. Une nouvelle ouverture explicite sous le cabinet voulu est nécessaire.

Les droits, la MFA, les quotas, les contrôles de révocation et les opérations visant déjà un objet précis restent applicables. La signature ne confère aucun accès supplémentaire. Une régression PostgreSQL maintient aussi une soumission A en cours pendant la bascule de session vers B : la première reste attribuée à A et une réutilisation ultérieure du formulaire est refusée.

## Lecture privée réellement bornée

Le backend S3 de django-storages téléchargeait l'objet complet dans son spool avant le premier read limité. Le nouveau lecteur utilise get_object avec Range et un StreamingBody borné, toujours fermé. Il exige un objet complet cohérent avec les tailles et, pour HTTP 206, Content-Range. Un serveur ignorant Range n'est accepté que pour un objet complet dont la taille déclarée et effectivement lue respecte le plafond. Un contenu tronqué, encodé/compressé ou incohérent est refusé. Les octets vérifiés sont ceux livrés ; aucune décompression ou substitution implicite n'est faite.

Les plafonds restent 1 Mio pour la sonde technique et 15 Mio pour médias/preuves. Le lecteur ne donne aucun délai total garanti ; les délais et tentatives du SDK restent en vigueur. Voir [le contrat d'intégrité](media-integrity-and-rights.md).

Le diagnostic privé de l'hébergement propose un POST explicite pour lire une sentinelle technique fixe. Le serveur choisit sa clé et son empreinte attendue ; la requête ne peut désigner ni objet patient, ni URL, ni destinataire. GET/HEAD ne lancent pas cette lecture. La page affiche durée, nombre d'octets et concordance du contenu, sans contenu, clé de stockage, secret ou détail fournisseur. Voir [l'exploitation](EXPLOITATION.md).

## Langue du guide dans le CMS

La langue des consignes d'accompagnement est maintenant annoncée sur le détail éditorial, avec accès au réglage existant. Elle peut différer de la langue de l'interface et de la variété parlée des stimuli. Un guide absent dans la langue sélectionnée est signalé ; aucun repli silencieux n'invente une traduction. Les textes éditoriaux de population, limites et droits restent tels qu'ils ont été saisis, dans un bloc distinct à direction automatique. Aucun contenu ni préférence enregistrée n'est réécrit par cet affichage.

## Vérifications et portée

Les tests ciblés couvrent le contexte signé et sa concurrence, les réponses S3 exactes/tronquées/hors plafond, la fermeture des flux, le refus des encodages, les rôles/MFA/CSRF du diagnostic et les guides FR/EN/AR. Les résultats des suites générales finales sont consignés après leur achèvement dans ce document ; les journaux et captures détaillés restent privés sur E:.

Vérification d’intégration locale du 31 octobre, après comparaison avec le `main` GitHub actuel : `manage.py check`, `makemigrations --check --dry-run`, compilateur inclus et contrôle de traductions réussissent ; 1 647 clés d’interface par langue sont couvertes sans manque. La suite SQLite complète découvre **649 tests : 629 réussis, 20 ignorés** car réservés à PostgreSQL, sans échec, en 395,119 s. Trois tests supplémentaires vérifient la lecture d’une sentinelle technique à empreinte attendue, le refus d’un contenu hors plafond et l’absence de fuite de clé, empreinte ou contenu dans le diagnostic. Les résultats PostgreSQL généraux précédents, interrompus avec code non nul, ne sont pas déclarés verts ; les lots PostgreSQL ciblés documentés plus bas restent séparés. La suite logicielle ne valide pas l’efficacité clinique.

Complément PostgreSQL ciblé, exécuté après l'enregistrement de `b36ab4e` : **41/41** tests de CMS, périmètre signé des formulaires et stockage borné réussis en 7,232 s ; **6/6** tests du module de concurrence réussis en 39,227 s. Le cas `test_practice_waits_for_archive_then_refuses` qui interrompait le journal général passe également isolément (**1/1**, 4,003 s). Ces groupes se recouvrent partiellement et ne sont pas additionnés. La suite PostgreSQL générale reste à rejouer dans un environnement qui ne subit pas les checkpoints très lents observés localement.

La configuration Render effective doit toujours être vérifiée sur le service et comparée au manifeste : `render.yaml` seul ne prouve ni le healthcheck actif ni le commit servi. Une livraison n’est confirmée qu’après lecture du déploiement Render et une recette publique sur le commit attendu.

Une recette navigateur locale a constaté le refus du formulaire A après sélection de B et le repère explicite Français dans une interface arabe RTL. Elle n'a envoyé aucun courriel et n'a utilisé aucun microphone réel.

Une restauration fictive PostgreSQL 17.11, achevée le 30 octobre à 23:20 UTC (31 octobre en Algérie), inclut les migrations qualification 0003/0004. Elle retrouve les instantanés, médias exacts et notes privées, les exports professionnel/familial, le refus d'un autre cabinet et le défaut SQL vide des anciennes décisions, toujours bloquées. Les deux bases locales créées pour cet exercice ont été retirées ; archive chiffrée et clé séparée restent privées sur E:. Ce n'est ni une restauration de Neon, ni une mesure de S3, ni un engagement de reprise du service.

Une vérification bornée du stockage existant depuis le poste opérateur a relu un média image, un média audio éditorial et une sentinelle technique sans donnée personnelle. Les empreintes attendues concordent et la sentinelle privée refuse l'accès anonyme (403). Aucune activité, permission ou approbation n'a été créée. Ces échantillons ne prouvent pas la pérennité, la sauvegarde ou la latence du processus Render.

## Conditions restant à satisfaire

Le dernier inventaire documenté du 30 octobre à 22:53 UTC compte 124 versions candidates, aucune activité réelle autorisée et 222 emplacements audio vides dans les dernières versions. Ce lot ne modifie pas cet inventaire. Les médias exacts dans chaque variété offerte, leurs droits, la familiarité des mots/images, les avis clinique et linguistique compétents et les décisions de disponibilité restent à produire réellement.

La livraison/réception des courriels reste non vérifiée et le transport publié désactivé. Sauvegarde hors hébergeur, restauration du service courant, alertes, configuration effective du healthcheck Render, capacité et responsabilités d'exploitation restent à éprouver. Les pièces d'usage/pilote, le périmètre de l'offre, l'opérateur, les conditions et l'assistance restent à confirmer selon [l'offre proposée](OFFRE_PILOTE_A_VALIDER.md). Aucun prix, contrat, résultat thérapeutique, avis humain ou garantie d'hébergement n'est déduit d'une suite de tests verte. Aucun nouveau coût récurrent n'est engagé.

## Mise à jour — traçabilité du paquet et recette publiée (31 octobre 2026)

Les six sources PNG originales du petit lot FR (9 839 323 octets au total) sont maintenant incluses sous `content/review_packs/fr-p-b-initial-review-20261030/sources/`. Chaque fichier conserve son nom source et concorde avec les octets et SHA-256 du manifeste ; les douze WebP de prévisualisation restent associés. Le README d’import n’exige plus un répertoire de génération externe. Dix tests ciblés réussissent, dont le contrôle des 18 vrais fichiers et la vérification que les six propositions restent sans approbation et avec droits inconnus.

Le merge GitHub `20028ca` a une action CI `success` (run 41204966896) et le déploiement Render `dep-dbiuniijnfac73bm21u0` est `live` sur ce commit. Après déploiement, les pages publiques FR/EN/AR et `/healthz/` répondent HTTP 200 ; le crédit exact et l’image du nouveau logo sont présents dans les trois pages. Le health check du service Render reste configuré sur la chaîne vide, même si l’endpoint de santé fonctionne et que le manifeste contient `/healthz/`. L’accès à Render a présenté la page de connexion ; aucun paramètre du service n’a été modifié.

Ce correctif ne change ni la qualification des images, ni les pièces cliniques ou linguistiques, les droits, la familiarité ou les essais enfant. Ces propositions restent une prévisualisation à examiner. La suite globale SQLite a découvert 650 tests : 630 réussis, 20 ignorés car réservés à PostgreSQL, zéro échec/erreur (358,624 s). La suite globale PostgreSQL 17.11 a découvert 650 tests : 650 réussis, aucun ignoré/échec/erreur (695,987 s), sur un cluster temporaire neuf lié à 127.0.0.1 ; la base de test a été supprimée et le cluster arrêté. Aucun test ne ciblait Neon ou Render. Les contrôles Django, dérive des migrations et traductions réussissent également ; 1 647 clés UI par langue, aucun manque.


## Mise à jour — journalisation des consultations et recette de la démo (31 octobre 2026)

La PR [#8](https://github.com/Midotech31/nehedrou/pull/8) a été fusionnée sur `main` par le commit `62dd66af2966e2eabd648b12fb72a498cc35c7c1`. L'action CI GitHub `41216187765` a terminé avec succès. Le déploiement Render `dep-dbj0rbss728c738hf000` est `live` sur ce même commit. Cette correction ajoute des événements de consultation finalisés pour les listes de suivi, formulaires d'objectifs et d'exposition, écrans de démarrage/cotation/relecture des sondes, partage et création de coaching. Les événements identifient l'acteur, l'enfant, le cabinet et la finalité sans recopier le contenu clinique. Cela étend la traçabilité des vues couvertes ; ce n'est pas un journal exhaustif ni une déclaration de conformité.

Après déploiement, le navigateur de recette a chargé les pages d'accueil et d'exemple en FR, EN et AR. Le parcours FR a été suivi jusqu'au récapitulatif : découverte des mots, choix d'image, puis choix fictif de participation et de retour familial. L'interface annonce qu'aucun dossier ni retour n'est enregistré dans ce parcours ; elle sépare le choix d'image du retour de l'accompagnant et indique que ni l'un ni l'autre ne mesure la prononciation ou un progrès clinique. Aucun compte, dossier enfant ou enregistrement audio n'a été créé pendant cette recette.

La fiche candidate FR `chat`/`rat` indique son statut non approuvé, son contraste /ʃ/–/ʁ/ illustratif, son public envisagé, les aides, les limites et la portée restreinte des références. La fiche darija affiche l'étiquette « Dellys lexical attestation, local review pending » ; la source lexicale citée n'est pas présentée comme une norme ou une validation clinique. Le modèle audio adulte exact, les droits, la familiarité et les approbations humaines restent absents. La démonstration demeure explicitement non disponible pour usage clinique et aucun tarif n'est proposé.

Le point de terminaison `/healthz/` a été refusé par le navigateur de recette (`ERR_BLOCKED_BY_CLIENT`) pendant cette vérification ; ce tour ne confirme donc pas son état HTTP sur le nouveau commit. L'API Render confirme le déploiement `live`, mais le service conserve `healthCheckPath` vide. L'accès au tableau de bord Render ouvre la page de connexion dans le navigateur disponible ; ce réglage n'a pas été modifié. Sauvegarde/restauration du service Neon, livraison de courriels, surveillance opérationnelle, conditions de l'offre et validations cliniques/linguistiques demeurent à traiter avant tout pilote vendu avec des dossiers réels.


## Mise à jour — publication manuelle Render pour dépôt public (31 octobre 2026)

Le service actif utilise comme source l'URL publique `https://github.com/Midotech31/nehedrou`. L'API Render indique `autoDeploy=yes`, `autoDeployTrigger=commit` et la branche `main`, mais aucun déploiement automatique n'a suivi les fusions observées ; le dernier commit est arrivé après un déclenchement explicite. La documentation Render précise que les services raccordés par URL de dépôt Git publique doivent être déployés manuellement, car ils ne sont pas reliés aux identifiants du fournisseur Git : [Deploying on Render](https://render.com/docs/deploys) et [Web Services](https://render.com/docs/web-services). Pour cette source, le réglage exposé `autoDeploy` ne doit donc pas servir de preuve de livraison automatique. L'équipe doit vérifier chaque SHA et déclencher la publication après les contrôles CI.

Le manifeste `render.yaml` indique `autoDeployTrigger: off` et `/healthz/`, cohérents avec une procédure manuelle et le health check souhaité. L'état du service lu via l'API conserve toutefois un `healthCheckPath` vide ; le manifeste n'a pas été synchronisé au compte et aucune modification du service n'est déclarée. Ne pas synchroniser l'ensemble du Blueprint sans comparaison préalable des ressources et variables privées.

## Mise à jour — périmètre du tableau de bord dans le journal d’accès (31 octobre 2026)

Le tableau de bord calcule des totaux et rapports récents sur tous les dossiers visibles, au-delà des six programmes présentés en cartes. Il journalise maintenant une consultation par enfant du périmètre courant : cabinet professionnel (`care_delivery`) ou liens actifs du parent (`family_practice`). Le test vérifie l’acteur, le cabinet, le sujet et la finalité pour chaque rôle. Les 33 tests de `core.tests`, `manage.py check` et `makemigrations --check --dry-run` passent sous SQLite avec Django 5.2.18.

Ce correctif complète une vue agrégée et n’établit pas un journal exhaustif des traitements ni la conformité à la loi. Les opérations hors des vues couvertes, les journaux d’infrastructure, les durées de conservation, la gouvernance des accès et l’avis juridique restent à vérifier.

## Mise à jour — état de la démo après le tableau de préparation (31 octobre 2026; déploiement Render confirmé à 21:03 UTC)

La PR [#16](https://github.com/Midotech31/nehedrou/pull/16) est fusionnée dans `main` par le commit `3ef201d87b41072667797477cd278ab14d6962c1`. Le déploiement Render `dep-dbj5e90473hc73b7aoa0` est `live` sur ce SHA. La recette publique a obtenu HTTP 200 pour `/healthz/`, `/fr/`, `/en/` et `/ar/`; les trois routes de préparation en accès anonyme redirigent vers la connexion (HTTP 302). La suite locale complète du dépôt sur ce code découvre 670 tests, tous réussis sauf 20 ignorés ; `manage.py check` ne signale aucun problème. Cette suite n’est pas une preuve de validation clinique, de conformité ni de capacité de production.

Une requête SQL d’agrégats en lecture seule sur la branche Neon de démonstration `br-winter-recipe-baycdg8f` constate les versions publiées suivantes : `fr-fr-pilot` 20/20 démo, `en-us-general-pilot` 18/18 démo, `ar-msa-pilot` 42/42 démo et `ar-dz-pilot` 34/34 démo. Total : 114 versions publiées, zéro non-démo. Le même instantané compte zéro ligne de revue d’activité, zéro décision de disponibilité positive, zéro entrée active du registre des traitements et zéro sonde professionnelle publiée hors démo. La requête ne lit aucun profil, objectif, séance ni enregistrement individuel. La date d’instantané et le nom des variétés ne transforment pas ces données de test en contenu approuvé.

Le tableau de préparation privé affiche désormais ces compteurs de registre et de sondes en FR/EN/AR, tout en distinguant les vérifications techniques des décisions humaines. Les blocages demeurent : obtenir des validations cliniques et linguistiques de personnes compétentes sur les empreintes exactes du contenu et des médias, documenter les droits et la familiarité, obtenir des décisions de disponibilité valides, compléter puis faire examiner le registre par la personne responsable, et confirmer l’exploitation et l’offre commerciale. Jusqu’à ce que ces preuves existent, cette publication reste une démo, pas une version à vendre pour usage thérapeutique.

## Mise à jour — correction des propositions darija v2 et déploiement (31 octobre 2026)

L’audit du paquet darija v1 a révélé que des propositions de mots familiaux pouvaient être attribuées aux deux images, y compris au mauvais côté. La PR [#19](https://github.com/Midotech31/nehedrou/pull/19) ajoute 32 versions v2 de brouillon qui rattachent uniquement ces propositions existantes au mot de leur côté, sans créer de mots, IPA, audio, avis ni approbation. V1 reste inchangé. Le chargeur conserve le caractère idempotent et les copies de démonstration exigent `DEMO_MODE=1`.

La suite ciblée passe **19/19** ; la suite du catalogue passe **164/164**, avec **4 tests réservés à PostgreSQL ignorés**. Le premier lancement global avait échoué parce que Python ne pouvait créer de répertoire temporaire ; après création d’un répertoire temporaire sur E:, la même suite a passé. `makemigrations --check --dry-run`, le contrôle des traductions (1 752 clés couvertes en FR/EN/AR) et `git diff --check` passent. Ces tests valident des invariants logiciels et la structure des propositions, pas leur adéquation clinique.

La PR #19 a été fusionnée par `85a66603cfbcadc0a8490c1c5b8fbc964bcaff08`. Le déploiement Render `dep-dbj5t5u7bikc73egoqlg` est `live` sur ce commit ; une vérification HTTP après le déploiement donne 200 sur `/healthz/`, `/fr/`, `/en/` et `/ar/`. Aucun import du paquet dans Neon/Render n’a été exécuté : la bibliothèque de démonstration n’a pas été enrichie par ce lot. Le service Render conserve `healthCheckPath` vide ; ce réglage reste à configurer et à vérifier séparément.

Les deux versions restent des propositions sans audio darija approuvé ni relecture humaine. Il faut encore obtenir des vérifications linguistiques locales et cliniques sur les empreintes exactes, la familiarité des images et mots, les droits des médias et les décisions de disponibilité. Les validations humaines, la conformité, l’exploitation durable et l’offre commerciale restent les principaux blocages avant toute commercialisation à visée thérapeutique.

## Instantané agrégé Neon — 31 octobre 2026, 21:40 UTC

Une requête **SELECT en lecture seule**, limitée aux agrégats sur la branche Neon `main` du projet « Nehedrou Demo », n’a consulté aucun dossier individuel, objectif, séance, retour familial, nom, courriel ni média. Elle constate 114 activités publiées, toutes `is_demo=true` : 20 `fr-fr-pilot`, 18 `en-us-general-pilot`, 42 `ar-msa-pilot` et 34 `ar-dz-pilot`. Il existe 124 activités en brouillon non démonstratif (22 FR, 17 EN, 52 arabe standard, 33 darija) ; leur présence ne vaut pas validation et plusieurs sont des versions historiques.

La même lecture retourne zéro ligne dans `catalog_review`, zéro décision dans `qualification_availabilitydecision` et zéro entrée active dans `core_processingactivity`. Le registre inactif ne constitue donc pas un registre opérationnel relu. `followup_probedefinition` contient deux brouillons non démonstratifs et deux copies de démonstration en brouillon ; aucune sonde publiée. `catalog_mediaasset` contient cinq médias audio et 18 images, tous avec `rights_status=unknown` et `rights_validity=unknown`. Ces compteurs n’identifient aucun média ni détenteur de données.

Cet instantané confirme que la version publique reste une démonstration : aucune activité réelle n’est actuellement autorisée par une décision de disponibilité. Avant la vente, il faut obtenir les revues humaines exactes, renseigner les droits des médias, faire examiner le registre par le responsable et vérifier l’exploitation. La requête et les tables interrogées ne prouvent ni conformité juridique ni efficacité thérapeutique.
