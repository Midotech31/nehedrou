# Inventaire courant et historiques de contenu

Instantané agrégé de la base Neon, interrogé en lecture seule le 1 novembre 2026 à 03:45 UTC : 124 lignes non démonstratives (22 fr-FR, 17 en-US, 52 ar-MSA, 33 ar-DZ). Les 111 versions courantes sont toutes en brouillon : 19 fr-FR, 17 en-US, 42 ar-MSA et 33 ar-DZ; les 13 lignes restantes sont des versions antérieures (3 FR, 10 MSA). Aucune ne référence d’audio et aucune revue ou décision de disponibilité n’est enregistrée. La table contient cinq actifs audio sans référence à ces contenus. Audit de structure, sans lecture de données enfant : 0/33 brouillons Darija et 10/42 brouillons MSA ont deux champs de transcription renseignés. Dans 32/33 fiches Darija, les listes lexicales A/B sont identiques alors que les mots principaux diffèrent; dans 17 fiches, le premier candidat B reprend le mot A. Ces signaux exigent une révision des versions exactes par des locuteurs compétents; ils ne prouvent pas seuls une erreur phonologique. Le dossier CMS de la PR #30 ajoute l’alerte de réutilisation des listes; aucune donnée n’a été corrigée ou approuvée par cette requête. Ce relevé est un instantané daté; il ne vaut ni validation ni inventaire d’une autre base.

Mis à jour le 1 novembre 2026. Aucun décompte historique ne doit être présenté comme
une qualification clinique ou comme l'état d'une autre base.

```text
python manage.py content_inventory --json
python manage.py content_inventory --metadata-only --json
```

La commande lit uniquement le catalogue éditorial, les fichiers sources, les
médias/preuves et les décisions de qualification. Elle n'écrit pas en base,
n'initialise aucun compte et ne lit aucun dossier d'enfant, objectif individuel,
programme, observation ou passation. Elle n'exporte aucun nom d'utilisateur,
contrat, note, titre de dossier ni secret. Elle peut être exécutée par l'opérateur
sur une connexion de production autorisée en lecture seule après les migrations.
Ne pas lancer un seed ou une suite de tests contre cette connexion.

L'exécution normale vérifie les fichiers, droits, relectures et décisions actuels
pour les seules versions réelles publiées susceptibles d'être utilisées. Ce sont
des lectures de stockage, sans création d'approbation. L'option `--metadata-only`
évite ces lectures et donne une disponibilité inconnue (`null`), jamais zéro par
défaut. La sortie est horodatée ; la commande ne promet aucune validité future.
La vérification des octets est locale à cette exécution ; aucun résultat durable
n'est réutilisé par l'application.

La sortie sépare, par variété :

- les définitions des fichiers candidats sources, qui ne prouvent pas leur import ;
- les séries candidates réelles, toutes leurs versions et la dernière version de chaque série ;
- les copies de démonstration, leur historique et leur sélection publiée courante ;
- les emplacements audio vides/référencés de la dernière version candidate ;
- les fichiers téléversés uniques référencés dans tous les historiques, leurs statuts de droits et validité structurée ;
- les preuves, décisions historiques positives et états de disponibilité ;
- les paquets régionaux et les définitions de sondes globales, séparés des dossiers privés ;
- la disponibilité réelle actuelle des modules, après les contrôles exacts.

Les médias sans référence éditoriale globale restent dans le total non attribué ; ils peuvent appartenir à des protocoles de cabinet exclus de cet inventaire, ce qui ne permet aucune suppression.
Un fichier partagé peut apparaître dans plusieurs variétés. Les chemins statiques
ne sont pas comptés comme des MediaAssets téléversés. Une référence audio n'atteste
ni fichier intact, ni voix native, ni permission. Une décision historique positive
n'est pas nécessairement actuelle ; seule la colonne de disponibilité vérifiée
applique les règles courantes, dont l'expiration et la révocation.

L'audit du 30 octobre 2026 sur `c92bea8` observait 111 candidats réels en brouillon,
aucune activité réelle publiée, aucune approbation positive, aucune preuve ni
décision de disponibilité. Il recensait cinq entrées audio aux droits inconnus et
222 emplacements audio candidats vides. Il s'agit d'un instantané fourni, pas
d'une nouvelle requête de production effectuée pendant ces corrections.

Les chiffres de 60 propositions v1 et de 37 fiches v2, ainsi que les anciennes
suites de tests, sont conservés dans leurs rapports datés. Les nouveaux visuels
préparés le 30 octobre restent des éléments générés à examiner ; leur présence
ne change aucune approbation ou décision d'ouverture. Les besoins humains,
la notice finale, le cadre d'usage et la qualification compétente restent à établir.
