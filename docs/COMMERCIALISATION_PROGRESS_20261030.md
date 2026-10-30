# Progression vers la commercialisation — 30 octobre 2026

Cette étape poursuit l’objectif d’une version commercialisable. Elle ne le déclare pas atteint. Les validations humaines, les conditions d’exploitation réelles et la décision d’ouverture restent nécessaires.

## Changements logiciels

- **Enrôlement MFA** : deux premières ouvertures simultanées utilisent la même clé provisoire. Les doublons historiques sont conservés sans erreur 500 ; le QR n’est plus livré après activation d’une clé confirmée.
- **Décision d’ouverture** : choisir une activité ou un protocole existant dans son périmètre. Le serveur calcule module, variété et empreinte, puis relit la cible sous verrou. Une modification depuis la préparation entraîne 409. La cible historique est conservée par une migration additive ; les anciennes décisions ne sont pas réattribuées. Le retrait reste possible selon les droits, y compris sur une cible historique disparue.
- **Dossier de preuves du CMS** : les champs éditoriaux renseignés restent distincts des droits et avis qualifiés. Le dossier décrit les manques par version, média et preuve, avec actions et rôles responsables. Le ZIP ajoute les tâches, médias et empreintes ; les décisions humaines restent vierges. Voir [le contrat du dossier](EDITORIAL_EVIDENCE_DOSSIER.md).
- **Coût de la page qualité** : pagination SQL avant les vérifications de fichiers, 16 versions au maximum ; le compteur audio annonce son périmètre de page. Aucun cache durable d’intégrité n’est ajouté.
- **Couverture de lancement** : les compteurs de langue d’interface sont descriptifs. La vérification stricte exige du contenu réellement disponible dans chaque variété offerte : français de France, anglais des États-Unis, arabe standard et darja algérienne par défaut. MSA ne couvre pas la darja. Voir [les conditions de lancement](LANCEMENT.md).
- **Diagnostic privé de l’hébergement** : page `/fr/operations/` (également EN/AR), réservée à la permission existante de gestion de plateforme et à la MFA prévue. Le GET lit la configuration du processus serveur sans exposer identifiants, hôtes ou dossiers. Un POST protégé peut mesurer SELECT 1. Aucun courriel n’est envoyé. Le rapport indique date, origine du processus et commit de déploiement lorsqu’il est fourni.
- **Délais PostgreSQL** : connexion limitée à 5 secondes ; le diagnostic utilise un statement_timeout local de 2 secondes et restitue le réglage d’une transaction appelante. Ce réglage serveur ne constitue pas un délai réseau de bout en bout. Les options TLS sont conservées.
- **Courriels** : les expéditeurs sur un sous-domaine d’exemple ne donnent plus un faux indicateur de configuration adaptée. La configuration ne prouve ni l’envoi ni la réception.
- **Langues et téléphone** : 106 nouveaux libellés FR/EN/AR, avec le retour à la ligne des longues empreintes et invalidation du cache CSS constaté au navigateur. Le logo, Tajawal et le crédit de conception sont conservés.

## Vérifications

- PostgreSQL 17 isolé : **490/490 réussis, aucun ignoré**, 417,344 s (429,687 s avec préparation/migrations). Les 15 cas de concurrence et les deux contrôles de délais PostgreSQL ont été exécutés.
- SQLite isolé : **490 découverts, 473 réussis et 17 réservés à PostgreSQL**, aucun échec/erreur, 338,272 s (346,875 s avec préparation).
- Django check, absence de dérive des migrations et traductions : **1 597 clés UI par langue, zéro manque** ; 106 libellés ajoutés.
- Le premier passage de chaque base a signalé une seule ancienne assertion exigeant OPTIONS={} ; elle exige désormais connect_timeout=5. Les deux suites complètes ont ensuite été rejouées avec succès. Les journaux initiaux sont conservés séparément.
- Au navigateur local : connexion du gestionnaire fictif et test SELECT 1, dossier de version exacte, préparation sans enregistrement d’une décision, bascule FR/AR/EN ; à 390 px, largeur de page et zone visible de 375 px après correction du débordement des empreintes. Aucun test sur téléphone physique ni nouvelle validation de lecteur d’écran n’est revendiqué.

Aucun test de mutation n’a utilisé Neon ou le stockage publié. Les journaux complets et observations privées sont conservés sur E:, hors du dépôt public. Ces résultats attestent des comportements logiciels ; ils n’attestent pas l’efficacité clinique ou une autorisation de vente.

## Compatibilité complémentaire du déploiement progressif

Après le point de contrôle global **d099df4 — 490 tests**, une reproduction PostgreSQL fictive a montré que l'ancienne liste de colonnes d'INSERT échouait sur target_snapshot : colonne NOT NULL sans défaut SQL permanent, SQLSTATE 23502. Le défaut Python de la migration 0003 ne protège pas une insertion émise par un processus de l'ancienne version encore actif pendant le remplacement progressif.

La nouvelle migration **0004** conserve un défaut SQL `{}` et le modèle garde son constructeur Python `dict`. **La migration 0003 déjà publiée reste inchangée.** Le champ vide décrit une cible historique non documentée : aucune cible, compétence, preuve ou approbation humaine n'est déduite. Les anciennes empreintes et les restrictions de lecture/retrait restent conservées.

Trois régressions exécutent réellement l'INSERT avec les anciennes colonnes, sa lecture par le code actuel, l'absence de réattribution, l'isolation du propriétaire et son retrait append-only ; elles vérifient aussi que les défauts vides des instances sont indépendants. Le lot affecté qualification/ouverture/livraison passe **38/38 sous PostgreSQL, sans ignoré/échec/erreur, 48,454 s**, et **38/38 sous SQLite, sans ignoré/échec/erreur, 46,792 s**. Django check, absence de dérive des migrations et diff-check réussissent. Journaux privés : `E:\LocalCoderWorkspace\Nehdrou\outputs\OCT30_CORRECTIONS\rolling-default-postgresql.log` et `E:\LocalCoderWorkspace\Nehdrou\outputs\OCT30_CORRECTIONS\rolling-default-sqlite.log` ; résumés privés correspondants avec le suffixe `-summary.json`. Aucun nouveau rapport interne n’est ajouté au dépôt.

Ces deux lots locaux fictifs distincts sont postérieurs au checkpoint d099df4 de 490 tests et le recouvrent ; ils ne sont pas additionnés entre eux ni aux 490 ; **aucune nouvelle exécution globale de 490 tests n'est revendiquée après ce correctif**. Aucun dossier de production n'a été utilisé et aucune migration distante n'a été exécutée par cette vérification.

## Limites de mise en service

La préparation d’un dossier, une déclaration de compétence, un fichier téléversé, un avis non favorable ou une suite de tests verte ne créent aucune approbation clinique. Les enregistrements natifs, les droits, les relectures clinique et linguistique, la familiarité des images, les pièces d’usage/pilote et les décisions restent à produire réellement. Les interfaces de relecture et d’ouverture servent à consigner ces pièces exactes.

La réception des invitations/réinitialisations, les sauvegardes et une restauration de production, les alertes et le réglage effectif du healthcheck Render doivent être attestés dans l’environnement publié. Le diagnostic privé décrit seulement ce qu’il observe. Aucune migration de cette étape n’invente de preuve, de contrat, de prix, de résultat thérapeutique ou d’approbation humaine. Le budget récurrent autorisé reste 0 €.

## Étape courriels encore nécessaire

La configuration SMTP par défaut utilise le port 587. Render Free bloque les sorties vers les ports 25, 465 et 587 ; même des paramètres SMTP renseignés ne démontrent donc pas un transport utilisable sur cette offre. Le lot logiciel suivant ajoute un transport HTTPS explicitement activable et ses tests à réseau simulé ; la configuration fournisseur/expéditeur et la recette réelle restent nécessaires avant de déclarer invitations et récupération opérationnelles. Voir [le contrat et les limites des courriels](EMAIL_TRANSPORTS.md). Aucun compte fournisseur, domaine, clé ou envoi n’a été créé. [Documentation officielle Render Free](https://render.com/docs/free).

## Lot logiciel courriels — tests et limites

- Transport HTTPS Resend disponible dans le code, **désactivé par défaut** ; aucun compte fournisseur, domaine, clé réelle, envoi ou réception n’a été créé ni vérifié. Le contrat couvre TLS, destination fixe, délais et réponses bornés, erreurs génériques et absence de repli automatique. Voir [EMAIL_TRANSPORTS.md](EMAIL_TRANSPORTS.md).
- Le défaut non-DEBUG devient un backend désactivé qui refuse l’envoi sans imprimer les liens d’accès dans les logs. La console reste locale en DEBUG ; le modèle `.env.example` n’impose plus de console explicite susceptible de contourner ce défaut. Un backend SMTP déjà explicitement configuré reste sélectionné.
- Le diagnostic privé et le contrôle de lancement suivent le backend sélectionné ; la section historique `smtp` reste présente. Aucun GET/HEAD ou contrôle de configuration ne contacte le fournisseur et aucun secret n’est affiché.
- La récupération utilise maintenant l’origine canonique de l’exploitant, indépendamment d’un Host de requête même autorisé. Avant correction, les régressions reproduisaient `http://testserver` et l’alias autorisé dans les liens au lieu de l’origine attendue. L’origine est contrôlée au démarrage, notamment pour les délimiteurs `?`/`#` même vides qui cassaient les liens d’invitation concaténés.

Vérifications locales fictives, sans réseau fournisseur : **546/546 tests PostgreSQL réussis**, aucun ignoré, 468,774 s (476,156 s avec préparation/destruction) ; **546 découverts sous SQLite, 529 réussis et 17 réservés à PostgreSQL ignorés**, aucun échec/erreur, 370,384 s (376,203 s avec préparation). Les 14 tests de parcours HTTP simulé sont aussi vérifiés séparément sur chaque base : invitations famille/praticien, FR/EN/AR, lien canonique et unique, alias, expiration, révocation, isolation et erreurs neutres. Ces lots se recouvrent et ne sont pas additionnés.

Les cinq tests de démarrage ont également été rejoués avec le dernier garde-fou des délimiteurs vides et réussissent ; ce complément est distinct des suites générales déjà lancées, sans addition aux 546. Django check, absence de dérive de migration et diff-check réussissent. **1 607 clés UI par langue, zéro manque**, dix libellés supplémentaires. Le contrôle de 584 fichiers destinés au dépôt n’a trouvé aucune valeur privée connue. Les comptes et leurs droits ne sont pas modifiés par ce lot.

Un inventaire éditorial borné, en transaction de lecture seule, daté du **30 octobre 2026 à 22:00:00 UTC** confirme encore **124 versions candidates, zéro avis positif sur contenu non démo, zéro activité actuellement autorisée pour l’usage réel et 222 emplacements audio vides** dans les dernières versions candidates. Il ne lit ni n’exporte les dossiers de soins. Aucune approbation ou autorisation d’ouverture n’est déduite de l’ajout d’un backend courriel.

L’objectif commercial reste ouvert : médias natifs et droits, relectures et pièces de qualification humaines, configuration/réception des courriels, garanties d’exploitation, sauvegarde/restauration réelles et conditions de l’offre restent à établir. La version publiée reste destinée à la démonstration. Aucun prix, résultat thérapeutique, témoignage ou approbation n’est inventé.


## Lot parcours hybrides, collecte audio guidée et invitations

- Un compte ayant un rôle professionnel, éditorial ou de plateforme et un lien familial peut choisir son espace. Les listes familiales suivent exclusivement les liens actifs ; elles n'exposent ni les autres dossiers professionnels, ni les notes privées ou mots réservés. L'acceptation d'une invitation sélectionne son espace. Le choix d'espace ne crée aucun droit et ne remplace pas la MFA des rôles réels. Le retrait du dernier rôle professionnel ne masque plus les programmes familiaux.
- Chaque mot d'un brouillon sauvegardé peut ouvrir une collecte audio avec mot, sens de travail, variété, transcription et version exacts. Sauvegarder le fichier puis l'associer sont deux actions distinctes. Le contexte signé expire après deux heures ; l'association relit et verrouille l'activité et le média, conserve les prises en cas de conflit et ne crée aucune approbation. Voir [le parcours audio](AUDIO_ET_VOIX_ADULTES.md).
- Les invitations distinguent désormais l'enregistrement de l'envoi lorsque le transport est désactivé ou incomplet. Une relance dans cette configuration conserve le jeton existant. Les erreurs temporaires d'un transport renseigné gardent leur procédure de relance ; aucune configuration ne prouve une réception. La récupération reste neutre et aucun courriel réel n'a été envoyé par cette recette.
- Sur téléphone, les sélecteurs d'espace et de cabinet restent accessibles. La recette locale fictive FR/EN/AR à 390 × 844 constate 375 px de zone visible et 375 px de contenu, sans débordement horizontal. Le formulaire de collecte conserve le mot français et sa variété lorsque l'interface passe à l'anglais ou à l'arabe RTL ; sa source vocale reste à choisir. Aucun téléphone physique ni microphone réel n'a été utilisé.

Une revue supplémentaire a reproduit un formulaire conservé sous le cabinet A après révocation de son affiliation : le nouveau repli de lecture vers B pouvait réorienter son POST vers B. Le correctif refuse cette écriture implicite, conserve la sélection caduque et permet de confirmer explicitement le cabinet actif, même lorsqu'il est seul. Le GET de repli n'enregistre pas B silencieusement. Ce scénario est couvert séparément des contrôles généraux ci-dessous.

Point de contrôle général avant ce dernier garde de sélection : PostgreSQL **597/597 réussis**, aucun ignoré, 544,020 s (562,297 s avec préparation/destruction) ; SQLite **597 découverts, 578 réussis et 19 réservés à PostgreSQL ignorés**, aucun échec/erreur, 422,275 s (436,922 s avec préparation/destruction). Les deux courses de la collecte audio sont exécutées sous PostgreSQL. Le correctif mobile est ensuite vérifié au navigateur ; ces tests serveur ne sont pas présentés comme une validation visuelle. Le dernier garde de sélection et ses tests ciblés sont consignés séparément, sans addition à ces 597.


La première sélection de lecture est désormais mémorisée avant d'afficher un formulaire lorsque la session n'a encore aucun cabinet. Cela ferme également le cas première connexion sous A, révocation A, puis ancien POST vers le repli B. Cette mémorisation initiale ne s'applique jamais au repli d'une sélection existante invalide ; les POST directs historiques sans sélection restent compatibles.

Vérification du dernier garde, postérieure au point de contrôle général : **33/33 tests ciblés réussis sous PostgreSQL, aucun ignoré**, 24,503 s (44,844 s avec préparation/destruction) ; **33/33 sous SQLite**, aucun ignoré/échec/erreur, 19,568 s. Ce lot comprend les 21 méthodes hybrides finales, les six vues d'invitations et six anciens parcours de création, quotas, historique et révocation. Un replay indépendant vérifie aussi le refus avant/après lecture du repli, le sélecteur à une option et la création uniquement après sélection explicite. Les passages antérieurs de 32 et les 597 généraux se recouvrent ; aucune nouvelle suite globale de 600 tests n'est revendiquée après ce correctif.

Contrôles complémentaires : Django check et absence de dérive des migrations réussis ; **1 635 clés UI FR/EN/AR, zéro manque** ; diff-check propre et aucune valeur privée connue trouvée parmi 590 fichiers destinés au dépôt. Aucun changement de schéma, compte, mot de passe, droit éditorial ou approbation clinique n'est ajouté par ce lot. Les fixtures et captures de recette restent hors du dépôt public, sur E:.

Ces améliorations rendent les parcours logiciels plus robustes et facilitent la collecte de vrais médias. Elles ne remplissent pas les emplacements audio avec des voix validées, ne constituent pas une relecture clinique/linguistique, ne démontrent pas une réception de courriels et ne qualifient pas l'hébergement pour la vente. Les limites et décisions d'ouverture documentées restent applicables.
