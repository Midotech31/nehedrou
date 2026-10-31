# Registre des traitements dans Nehedrou

La loi algérienne n° 25-11 du 24 juillet 2025 ajoute notamment les articles 41 bis 2 et 41 bis 3 à la loi n° 18-07. L’article 41 bis 2 décrit les éléments attendus d’un registre d’activités ; l’article 41 bis 3 prévoit un carnet automatisé des opérations, avec motifs, date et heure, ainsi que l’identité des personnes et destinataires dans la mesure du possible. Voir le [Journal officiel n° 48 de 2025](https://www.joradp.dz/FTP/JO-FRANCAIS/2025/F2025048.pdf).

## Fonction disponible

Une personne autorisée peut ouvrir `/<langue>/operations/register/` dans les interfaces françaises, anglaises et arabes. La permission `core.manage_processing_register` ouvre cette page ; elle déclenche aussi l’exigence MFA lorsque la MFA est obligatoire. Elle n’accorde ni accès aux dossiers cliniques ni accès à la facturation. Un champ `Cabinet` vide désigne le registre de la plateforme Nehedrou ; une organisation permet de distinguer un registre de cabinet.

Chaque fiche distingue le rôle de responsable du traitement ou de sous-traitant et permet de documenter les coordonnées, finalités, fondement envisagé, catégories de personnes et données, destinataires et pays, transferts, durées d’effacement, mesures de sécurité et opérations. Les utilisateurs peuvent désactiver une fiche sans la supprimer. L’export JSON authentifié inclut les fiches actives et inactives. Les consultations, créations et modifications du registre créent un événement d’audit avec acteur, objet, cabinet et finalité, sans copier le texte de la fiche dans le journal. Chaque sauvegarde conserve également un instantané versionné append-only; les instantanés sont inclus dans l’export JSON.

`check_readiness` signale si le registre plateforme est absent ou si une fiche active ne contient pas les champs requis. Pour un responsable du traitement, le contrôle exige aussi un contact de protection des données. Ce contrôle ne confirme ni la qualité d’un fondement juridique ni l’exactitude du registre.

## Limites avant ouverture commerciale

Aucune fiche réelle n’est préremplie. L’historique versionné documente les états enregistrés après déploiement de cette migration; il ne reconstitue pas les anciennes valeurs qui n’étaient pas archivées auparavant. L’exploitant doit vérifier les rôles exacts, coordonnées, finalités, bases juridiques, données, destinataires, transferts, durées et mesures avant saisie. Un conseil compétent doit déterminer les obligations applicables, les formalités et l’exactitude juridique ; le logiciel ne tranche pas ces questions.

Le journal actuel reste ciblé. Il ne consigne pas encore de manière exhaustive toutes les opérations de collecte, d’inscription, d’organisation, de conservation, d’adaptation, de modification, d’extraction, de consultation, d’utilisation, de communication, de diffusion, d’interconnexion, de verrouillage, de chiffrement, d’effacement et de destruction dans tous les parcours, tâches différées, fournisseurs et journaux d’infrastructure. L’existence d’une fiche et d’événements de consultation n’est donc pas une preuve de conformité à l’article 41 bis 3.

Pour les portes de lancement et leur portée, voir [Conditions de lancement](LANCEMENT.md) et le [rapport technique readiness](../core/management/commands/check_readiness.py).
