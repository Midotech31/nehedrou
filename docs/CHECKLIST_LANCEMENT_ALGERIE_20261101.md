# Nehedrou — état de lancement en Algérie

État vérifié le 1 novembre 2026. Marché initial : cabinets d’orthophonie en Algérie, avec pratique à domicile accompagnée et objectifs choisis par l’orthophoniste. Budget autorisé : 0 EUR. Le porteur envisage une startup; son entité juridique et ses coordonnées commerciales ne sont pas encore définies.

## Décision et preuves

**Démonstration uniquement. Le lancement clinique payant n’est pas qualifié.** Les tests logiciels ne constituent ni une validation clinique des contenus ni une décision réglementaire.

Le [diagnostic du processus Render](verification-20261101/runtime-launch-snapshot.json), lu avec le compte fictif gestionnaire, porte sur le commit publié `7a74258` avant les correctifs de cette branche. Il confirme PostgreSQL, HTTPS, stockage privé déclaré durable et mode démonstration actif. Le transport de courriels est désactivé, la MFA des rôles privilégiés n’est pas obligatoire dans la démo, le registre de plateforme est vide et aucune variété ne dispose de contenu réel actuellement disponible. Le porteur confirme ne disposer d’aucun domaine professionnel ni fournisseur de courriels pour le moment.

Le [relevé éditorial Neon en lecture seule à 16:26 UTC](verification-20261101/editorial-aggregate-snapshot.json) compte 124 versions historiques non démo, soit 111 séries courantes : FR 19, EN-US 17, arabe standard 42 et Darija algérienne pilote 33. Elles sont toutes en brouillon et manquent d’au moins une référence audio A/B. Zéro revue d’activité, décision de disponibilité et déclaration de compétence est enregistré; cinq entrées audio existent, sans que ce nombre établisse leurs droits ou leur qualification. Aucun dossier, texte d’activité, compte ou secret n’est exporté par ce relevé.

## Checklist A01–A17 actualisée

Les preuves historiques détaillées restent dans [la checklist du 30 octobre](CORRECTIONS_AUDIT_20261030.md). Le tableau distingue logiciel, recette et décisions humaines.

| Action | État vérifié / changement | Condition restante |
|---|---|---|
| A01 — pack clinique | Six concepts FR générés à examiner, paquet arabe source et export CMS des versions exactes présents. Aucun contenu réel disponible dans le diagnostic publié. | Relectures indépendantes par variété/région, familiarité, images, modèles adultes et droits; aucun import ni avis fabriqué. |
| A02 — cadre d’usage | Démo visible et portes d’ouverture par module/variété/version. Questionnaire de qualification préparé pour l’Algérie. | Finalité, qualification, responsabilités, traitements et transferts revus par les personnes compétentes. |
| A03 — continuité des dossiers | Transfert au praticien actif et révocation bloquée si dossiers encore affectés, y compris archives; historique conservé. Régressions dans la suite et cas PostgreSQL. | Recette terrain et politique opérationnelle du cabinet. |
| A04 — objectif/sonde | Position et contexte structurés, contrôles côté serveur, autre contexte explicitement justifié et séparé. | Pertinence clinique des objectifs et protocoles réels. |
| A05 — audio exact | Profil oral, variété, origine et pièces requis; octets et version contrôlés. | Enregistrements adultes et décisions humaines encore absents. |
| A06 — accès | Budgets d’authentification et invitations révocables présents. Cette branche refuse l’invitation d’un compte désactivé avant création ou remplacement, sans réactiver le compte. | Chaîne proxy réelle, MFA de production, réception et récupération réellement exercées. |
| A07 — exports | Export professionnel v3 et familial filtré; historique et réserves séparés, tests d’isolation. | Validation opérateur de conservation et exercice autorisé sur l’environnement publié. |
| A08 — droits/retrait | Validité structurée et révocation. Cette branche recharge les portes après verrous et sérialise la révocation avec l’activité/sonde liée. | Contrats réellement documentés et droits accordés; cette protection ne rend pas un contrat valide. |
| A09 — intégrité/coûts | Cache limité à la requête, livraison vérifiant ses propres octets. L’invalidation avant nouvelle écriture exclut les portes et empreintes précachées avant le verrou. | Mesures S3 représentatives; les plafonds de petites fixtures ne donnent pas une latence de production. |
| A10 — consignes MSA | Dix propositions avec précautions FR/EN/AR; comparaison source/CMS et versions explicites. | Relecture clinique et linguistique des formes et consignes exactes. |
| A11 — langues locales | Langue du mot, des consignes et de l’interface séparées; RTL/Tajawal et substitution de voix de démonstration documentés. | Compréhension native, lecteur d’écran et appareils physiques. |
| A12 — glossaire | Terminologie phonémique proposée, données préservées et langue des références indiquée. | Validation terminologique compétente. |
| A13 — pratique | Parcours, pause/arrêt et erreurs essayés sur bureau et fenêtres étroites dans les recettes datées. | Téléphones physiques, zoom et technologies d’assistance dans le périmètre retenu. |
| A14 — choix manquant | Refus immédiat côté client, validation serveur, arrêt sans choix et reprise couverts. | Essais utilisateurs et technologies d’assistance. |
| A15 — exploitation | `/healthz/` est effectivement configuré dans Render et le déploiement `7a74258` est live. Cette branche refuse une cible de restauration PostgreSQL contenant des objets utilisateur au-delà du seul schéma public. | Domaine/fournisseur d’email, réception, sauvegarde complète autorisée, destination/clé/rétention/planification, alertes et restauration d’exploitation. Le contrôle de cible impose toujours une base neuve isolée sans autre auteur d’écriture. |
| A16 — documentation | Diagnostics du processus et compteurs datés conservés; états de source, démo et contenus réels séparés. | Régénérer après les revues/publications; ne pas transformer la présence de champs ou une suite verte en approbation clinique. |
| A17 — offre | Algérie B2B confirmée; facturation manuelle auditable, statut final et montant/devise préservés; consultation sans création de droits. | Entité juridique, clientèle pilote, prix/devise/taxes, contrats, support et budget de production acceptés par le porteur. Aucun prix ni engagement n’est inventé. |

## Contrôles de cette branche

Les revues d’activités, sondes et packs portent désormais sur l’empreinte du contenu effectivement affiché. Un retour en brouillon, une édition puis une nouvelle soumission rendent l’ancien formulaire périmé; il doit être rechargé et relu. Le cache de permissions et de preuves est renouvelé après acquisition des verrous. Les revues existantes et les données historiques restent conservées.

Contrôles locaux : 36 tests de revue/invitation/ouverture réussis; 33 tests écritures/restauration/sauvegardes/concurrence sans échec, dont 15 réservés à PostgreSQL ignorés sur SQLite. Les groupes se chevauchent avec la suite complète et ne doivent pas être additionnés comme cas distincts. Le job CI PostgreSQL est étendu aux nouvelles régressions, dont l’attente de révocation observée par `pg_blocking_pids` et les catalogues d’une cible neuve. La validation complète et la publication de cette branche sont à lire sur sa PR et Render; ce document ne les anticipe pas.

La sauvegarde complète Neon vers E: avait été refusée par la revue automatique faute d’autorisation explicite d’export des dossiers. Aucun nouvel export intégral ni restauration de production n’est déclaré ici. Les compteurs agrégés et le diagnostic de configuration ne remplacent pas cette autorisation.
