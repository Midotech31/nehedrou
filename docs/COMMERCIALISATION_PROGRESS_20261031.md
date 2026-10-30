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

Une recette navigateur locale a constaté le refus du formulaire A après sélection de B et le repère explicite Français dans une interface arabe RTL. Elle n'a envoyé aucun courriel et n'a utilisé aucun microphone réel.

Une restauration fictive PostgreSQL 17.11, achevée le 30 octobre à 23:20 UTC (31 octobre en Algérie), inclut les migrations qualification 0003/0004. Elle retrouve les instantanés, médias exacts et notes privées, les exports professionnel/familial, le refus d'un autre cabinet et le défaut SQL vide des anciennes décisions, toujours bloquées. Les deux bases locales créées pour cet exercice ont été retirées ; archive chiffrée et clé séparée restent privées sur E:. Ce n'est ni une restauration de Neon, ni une mesure de S3, ni un engagement de reprise du service.

Une vérification bornée du stockage existant depuis le poste opérateur a relu un média image, un média audio éditorial et une sentinelle technique sans donnée personnelle. Les empreintes attendues concordent et la sentinelle privée refuse l'accès anonyme (403). Aucune activité, permission ou approbation n'a été créée. Ces échantillons ne prouvent pas la pérennité, la sauvegarde ou la latence du processus Render.

## Conditions restant à satisfaire

Le dernier inventaire documenté du 30 octobre à 22:53 UTC compte 124 versions candidates, aucune activité réelle autorisée et 222 emplacements audio vides dans les dernières versions. Ce lot ne modifie pas cet inventaire. Les médias exacts dans chaque variété offerte, leurs droits, la familiarité des mots/images, les avis clinique et linguistique compétents et les décisions de disponibilité restent à produire réellement.

La livraison/réception des courriels reste non vérifiée et le transport publié désactivé. Sauvegarde hors hébergeur, restauration du service courant, alertes, configuration effective du healthcheck Render, capacité et responsabilités d'exploitation restent à éprouver. Les pièces d'usage/pilote, le périmètre de l'offre, l'opérateur, les conditions et l'assistance restent à confirmer selon [l'offre proposée](OFFRE_PILOTE_A_VALIDER.md). Aucun prix, contrat, résultat thérapeutique, avis humain ou garantie d'hébergement n'est déduit d'une suite de tests verte. Aucun nouveau coût récurrent n'est engagé.
