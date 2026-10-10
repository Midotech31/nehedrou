# Suivi descriptif professionnel de Nehedrou

## Portée

Le module `followup` s'adresse à un orthophoniste responsable d'un enfant de 4 à 7 ans déjà évalué. Le professionnel choisit la cible, la variété, les variantes acceptées, les aides et la prochaine revue. Une définition de sonde est un protocole original versionné ; elle ne reproduit aucun test standardisé. Les modèles et les données de démonstration ne constituent pas une validation clinique.

L'interface existe en français, anglais et arabe. La langue du menu, la langue des consignes adultes et la variété travaillée sont distinctes. Aucun microphone, enregistrement d'enfant, diagnostic automatique, score de reconnaissance vocale, percentile ou progression thérapeutique automatique n'est requis.

## Parcours

1. Depuis **Suivi de production**, choisir un enfant dont on est responsable et créer un objectif : phonème, position/contexte, justification, réalisation attendue, variantes documentées, objectif fonctionnel, statut de l'évaluation externe et échéance.
2. Choisir une définition compatible avec la variété. Documenter les conditions et la familiarité de chaque item avant la passation. Le protocole fixe la tentative retenue avant présentation ; la meilleure réponse n'est pas sélectionnée après coup.
3. Saisir chaque occurrence cible, son mode d'élicitation, l'aide réellement utilisée et une transcription facultative. Dénomination, indice lexical et répétition restent séparés. La sonde ne fournit pas de correction pédagogique immédiate.
4. Relire puis finaliser. La version, les items, les conditions, l'objectif et les expositions sont conservés dans un instantané. Une correction ultérieure crée une révision motivée et conserve la cotation initiale ainsi que le compte rendu de finalisation.
5. Consulter le rapport professionnel, son CSV UTF-8 ou son support imprimable. Pour la famille, rédiger et partager explicitement un texte distinct. Le partage est révocable et n'ouvre aucun accès aux cotations, aux notes privées ni aux items de réserve.

Les responsables de cabinet n'ont pas automatiquement accès aux dossiers de leurs collègues. Les éditeurs, relecteurs et gestionnaires de plateforme ne gagnent pas d'accès clinique par leurs seules permissions éditoriales ou administratives.

## Cotations et calcul

| Code | Utilisation |
|---|---|
| `TARGET_ACCEPTABLE` | Réalisation acceptable de la cible selon le protocole et l'objectif. |
| `VARIANT_ACCEPTABLE` | Variante autorisée, identifiée dans une liste documentée. |
| `TARGET_INCORRECT` | Tentative audible du mot attendu, avec cible identifiable et cotable ; préciser le type d'erreur. Une omission audible de la cible peut être une erreur. |
| `NOT_SCORABLE` | Mot/tentative non cotable ; motif obligatoire. Un refus n'est pas une omission phonologique. |
| `NOT_PRESENTED` | Item non présenté ; il n'entre pas dans le dénominateur. |

Le ratio descriptif est `(TARGET_ACCEPTABLE + VARIANT_ACCEPTABLE) / (TARGET_ACCEPTABLE + VARIANT_ACCEPTABLE + TARGET_INCORRECT)`. Exemple de test logiciel : 5 acceptables + 1 variante + 3 erreurs + 2 non cotables donnent **6/9**, avec 2 exclusions. Ce n'est ni un PCC global, ni une norme, ni un résultat thérapeutique de Nehedrou. Lorsque le dénominateur vaut zéro, aucun ratio n'est calculé.

Les groupes séparent cible, variété, exposition des mots, mode d'élicitation et aide. Les passations dont la version, les conditions ou les expositions diffèrent ne sont pas présentées comme directement comparables. L'interprétation appartient au clinicien.

## Réserve et exposition

Les mots de réserve sont retirés des choix d'activités, des tâches familiales, de la bibliothèque familiale et des supports structurés destinés à la famille pour l'enfant concerné. Une réservation ne supprime aucun historique professionnel. La pratique familiale enregistre une **déclaration d'exposition**, jamais une production vocale correcte : tâche terminée = exposition entraînée ; activité arrêtée = exposition incertaine.

Une déclaration professionnelle d'exposition peut documenter une pratique extérieure. Une exposition ultérieure signale une contamination possible sans réécrire l'instantané d'une passation passée. Le clinicien doit aussi éviter de divulguer lui-même des mots réservés dans un texte libre partagé.

## Accompagnement parental

Une fiche distincte contient consignes, exemple, essai accompagné, vérification de compréhension par le clinicien et échéance. Les notes privées du clinicien ne sont pas exposées au parent. La famille peut imprimer cette fiche et déclarer une pratique hors écran : participation, aide, difficulté, arrêt et commentaire. Elle ne cote pas la phonétique.

Les programmes existants conservent leurs retours. Deux champs facultatifs ajoutent les aides déclarées et le motif d'arrêt ; les données anciennes ne reçoivent aucune réponse inventée. Aucun nombre universel de répétitions ou durée thérapeutique n'est imposé.

## Import et démonstration

Commande optionnelle : `python manage.py import_probe_definitions followup/data/probes_draft.json` vérifie sans enregistrer ; ajouter `--apply` pour enregistrer explicitement les brouillons dans un environnement autorisé. L'import est atomique et reproductible : deux définitions FR/EN non approuvées, douze items proposés, sans fichiers audio ni images. Il refuse les états publiés et les doublons de version dont le contenu diffère. Il n'appelle pas `import_catalog` et ne remplace pas le catalogue historique.

`seed_followup_demo` est réservé à `DEMO_MODE=1` et aux comptes/enfants fictifs existants. Il crée des copies de simulation explicitement non validées pour Sami, ainsi que deux objectifs et six fiches parentales (consignes adultes FR/EN/AR pour les deux variétés FR/EN). Il ne crée ni avis humain, ni compétence, ni disponibilité réelle. Le script Render appelle cette commande uniquement dans l'environnement de démonstration déjà configuré ; aucun seed n'est lancé en mode réel.

## Stockage et contrôles

Les migrations sont additives. Les opérations sensibles recontrôlent responsabilité et autorisations sous transaction ; les passations finalisées, cotations, révisions et déclarations sont conservées comme historiques. Les fonctions d'export et d'effacement des dossiers intègrent le nouveau module, et ses derniers événements prolongent l'ancre de conservation. Les liens familiaux révoqués ne donnent plus accès aux partages ni aux fiches parentales.

Les tests logiciels et la recette de cette livraison sont consignés dans le bilan privé et les journaux fournis. Ils vérifient le comportement du logiciel ; ils ne démontrent aucune efficacité clinique.
