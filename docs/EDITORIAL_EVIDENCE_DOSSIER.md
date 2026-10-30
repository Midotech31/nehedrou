# Dossier de preuves pour la relecture humaine

Ajout du 30 octobre 2026. Ce dossier aide à préparer les preuves et les décisions humaines d’une version exacte. Il n’accorde aucune approbation clinique, autorisation juridique ou disponibilité commerciale. Aucun GET ne crée de pièce, d’avis, de décision ou de changement d’état.

## Parcours dans le CMS

Depuis la fiche d’une activité, ouvrir **Dossier de preuves pour la relecture humaine**. La page qualité accepte `?activity=<UUID>` pour inspecter cette version seule, y compris une ancienne version retirée. Sans cible précise, la file courante exclut les versions retirées.

La complétude éditoriale existante reste distincte du dossier : un texte de droits ou une URL audio renseignée ne constitue pas une preuve valide. Le dossier détaille les manques par côté et média, puis les avis et la disponibilité. Chaque tâche indique le rôle responsable, la raison actuelle et l’action attendue. Il ne choisit aucune personne et ne déclare aucun résultat d’étude.

Les contrôles couvrent :

- définition du sens, segments, occurrences cibles et variantes ;
- référence et empreinte de la preuve de familiarité du mot et de l’image, pour la variété exacte ;
- octets exacts de chaque média, statut des droits, période structurée, provenance requise et pièce de droits ;
- texte exact, variété et source déclarée de chaque audio, ainsi qu’un signal non silencieux ;
- manifeste courant des médias ;
- dernier avis clinique et linguistique portant sur l’empreinte actuelle, permissions et déclarations de compétence toujours valides, deux personnes distinctes ;
- pièces des cinq catégories exigées pour la disponibilité et décision courante autorisée pour l’empreinte exacte.

Un document expiré, révoqué, altéré, mal relié ou d’une autre variété ne satisfait pas le contrôle. Le dossier ne déduit jamais une autorisation de la rédaction libre d’un contrat. La présence d’une transcription ne remplace pas sa comparaison humaine avec l’enregistrement. Les avis favorables antérieurs ne remplacent pas un nouvel avis sur un contenu modifié.

## ZIP de préparation

Le téléchargement existant conserve `activities.json`, `review.csv`, `recording_prompts.csv` et ses instructions. Il ajoute :

| Fichier | Contenu |
| --- | --- |
| `evidence_dossiers.json` | État daté des contrôles, tâches et médias par empreinte exacte ; schéma `nehedrou-evidence-dossiers-v1`. |
| `evidence_dossiers.sha256` | SHA-256 des octets du JSON précédent. |
| `evidence_tasks.csv` | Exigences non satisfaites, raisons et actions ; les colonnes personne affectée, preuve apportée, décision humaine et date restent vierges. |
| `media_requirements.csv` | Les quatre médias attendus, mots, identifiants et empreintes connus, périodes, source vocale déclarée et manques documentaires. |

Le ZIP constitue une photographie datée. Revenir au CMS et recontrôler l’empreinte avant de consigner une décision dans le circuit habituel. Aucun import de ces feuilles ne peut approuver ou publier du contenu. Les cellules CSV susceptibles de devenir des formules sont neutralisées.

Les nouveaux fichiers n’exportent ni contrat, ni contenu d’une pièce privée, ni provenance libre des médias, ni nom de compte, ni coordonnées du locuteur, ni clé de stockage. Pour un document d’une autre variété ou catégorie, ses métadonnées sont masquées et seule l’incompatibilité est signalée. Le reste du ZIP conserve les textes éditoriaux de l’activité déjà accessibles dans ce même périmètre.

## Périmètre et coût

L’accès suit strictement le périmètre éditorial existant : connexion et autorisation sur la variété de l’activité, ou compte superutilisateur. Une simple affiliation à un cabinet ou un lien familial ne donne pas accès au dossier éditorial. Une cible hors périmètre renvoie 404. Les réponses sont privées et `no-store`.

La page est paginée en SQL avant les contrôles de fichiers : 16 versions au maximum. Le compteur de fichiers audio concerne explicitement cette page. Le filtre **Références audio manquantes** recherche les deux champs vides en SQL ; une référence présente dont le fichier est indisponible est signalée lors du contrôle de sa page. Le filtre du guide lit uniquement les valeurs JSON locales avant pagination. Le ZIP vérifie toutes les versions de son périmètre explicite ; utiliser le lien de téléchargement par version pour un dossier unique.

Les relations et empreintes sont partagées uniquement dans la requête HTTP courante. Une requête suivante recharge les droits et relit les fichiers. La livraison des médias conserve son propre contrôle des octets de réponse, indépendant du dossier.

## Vérification locale

`catalog.tests_review_dossier` vérifie les manques réels, le rejet le plus récent, l’indépendance des avis, l’expiration avec horloge contrôlée, la modification des octets, la révocation, les empreintes de preuves, les filtres et droits HTTP, le ZIP et ses décisions vierges, ainsi que la non-divulgation des provenances et documents hors périmètre.

Le test de quatre versions entièrement documentées impose 44 calculs d’empreinte distincts et au plus 7 requêtes SQL pour le graphe batched. Un test HTTP de 36 versions impose 16 contrôles de complétude sur la page visible, 44 calculs d’empreinte et au plus 25 requêtes SQL lorsque quatre versions documentées se trouvent sur cette page. La seconde page, sans fichiers, ne calcule aucune empreinte de la première. Ces budgets de petites fixtures locales ne mesurent pas la latence S3.

Le 30 octobre 2026, une vérification HTTP authentifiée du serveur de recette local a ouvert le dossier pain/bain v3 et téléchargé son ZIP : réponses 200, une seule version, 16 tâches, quatre médias attendus, empreinte du JSON vérifiée et décisions humaines vierges. Aucun environnement publié ou secret cloud n’a été utilisé.
