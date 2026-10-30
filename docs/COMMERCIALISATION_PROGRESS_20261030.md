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

## Limites de mise en service

La préparation d’un dossier, une déclaration de compétence, un fichier téléversé, un avis non favorable ou une suite de tests verte ne créent aucune approbation clinique. Les enregistrements natifs, les droits, les relectures clinique et linguistique, la familiarité des images, les pièces d’usage/pilote et les décisions restent à produire réellement. Les interfaces de relecture et d’ouverture servent à consigner ces pièces exactes.

La réception des invitations/réinitialisations, les sauvegardes et une restauration de production, les alertes et le réglage effectif du healthcheck Render doivent être attestés dans l’environnement publié. Le diagnostic privé décrit seulement ce qu’il observe. Aucune migration de cette étape n’invente de preuve, de contrat, de prix, de résultat thérapeutique ou d’approbation humaine. Le budget récurrent autorisé reste 0 €.

## Étape courriels encore nécessaire

La configuration SMTP par défaut utilise le port 587. Render Free bloque les sorties vers les ports 25, 465 et 587 ; même des paramètres SMTP renseignés ne démontrent donc pas un transport utilisable sur cette offre. Une intégration HTTPS et sa recette réelle restent à réaliser avant de déclarer invitations et récupération opérationnelles. Aucun compte fournisseur, domaine, clé ou envoi n’a été créé. [Documentation officielle Render Free](https://render.com/docs/free).
