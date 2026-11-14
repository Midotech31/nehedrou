# CMS : preuves de familiarité et variantes locales

Le formulaire simple de création et d’édition d’une activité permet de documenter chaque mot sans écrire de JSON. Ce parcours aide à préparer une relecture ; il ne valide ni le document joint, ni l’activité, ni Nehedrou.

## Parcours de l’éditeur

1. Dans **Contenus et droits**, téléverser une pièce privée de catégorie « Familiarité des mots et des images » dans la variété parlée concernée. Documenter son auteur, sa date, son périmètre et sa validité. Une note de familiarité seule ne constitue pas cette pièce.
2. Dans le CMS, ouvrir **Mots et médias**. Pour chaque mot, choisir la pièce existante qui concerne réellement ce mot et son illustration. La sélection est limitée aux documents déjà accessibles à l’éditeur. Enregistrer une référence ne prouve pas que son contenu est pertinent.
3. Si nécessaire, ouvrir les détails phonologiques et saisir les variantes admissibles, une par ligne sous la forme `forme API ; raison`. Documenter le contexte régional et faire relire ces propositions. Une variante ne devient pas automatiquement une paire minimale ou une forme adaptée à un enfant.
4. Enregistrer le brouillon, puis suivre les relectures clinique et linguistique indépendantes et la décision de disponibilité de la version exacte.

L’interface peut être française, anglaise ou arabe ; la pièce doit toujours correspondre à la **variété parlée de l’activité**. Une pièce d’arabe standard ne remplace pas une pièce de darija régionale.

## Conservation et contrôles

- Une sélection inchangée conserve sa référence et son empreinte enregistrées. Une sauvegarde ordinaire ne répare pas silencieusement une empreinte périmée.
- Le choix vide conserve une référence historique. La case de suppression doit être cochée explicitement pour la retirer. Pour remplacer un document devenu inexact, téléverser une nouvelle pièce immuable et la sélectionner.
- Une nouvelle sélection est vérifiée côté serveur : périmètre privé, catégorie, variété, validité et intégrité des octets. Une pièce absente, révoquée, expirée ou altérée ne peut pas être liée par ce sélecteur.
- Les variantes historiques et leurs attributs supplémentaires sont conservés quand leur texte n’a pas changé. Une modification explicite remplace les variantes concernées sans reporter implicitement d’anciennes attestations.
- Les copies de travail restent privées et récupérables. L’enregistrement reste un brouillon ; aucun avis, droit de publication ou accès clinique n’est ajouté.

Les références et variantes sont intégrées à l’empreinte du contenu relu. Les exigences de médias exacts, de droits, de compétence indépendante, de deux avis distincts et de disponibilité restent applicables.

## Limites du lancement

La [checklist de lancement en Algérie](CHECKLIST_LANCEMENT_ALGERIE_20261101.md) reste applicable. Le relevé agrégé en lecture seule du 14 novembre 2026 compte zéro avis sur une activité réelle, zéro déclaration de compétence active, zéro décision de disponibilité et zéro activité réelle publiée. Le logiciel ne peut pas remplacer les personnes et pièces nécessaires à ces décisions.

## Vérifications du lot

Préparation locale sur base SQLite et médias techniques fictifs isolés : 56 tests ciblés réussis, aucun ignoré, couvrant l’édition originale, les pièces privées, les variantes et la récupération des copies de travail. Les contrôles utilisent de vrais octets de fichiers techniques ; ils ne simulent pas de résultat clinique.

Une recette CUA locale a créé un seul brouillon fictif, enregistré sa copie de travail, récupéré les nouvelles sélections et variantes puis enregistré le brouillon sans publication. Après chargement du code final, sa réouverture FR/EN/AR à 320 × 844 px conserve les champs ; largeur utile et largeur de document mesurées : 305/305 px. Le texte d’aide technique anglais a été retiré du formulaire simple. Cette recette sur fenêtre étroite ne constitue pas un essai sur téléphone physique ou lecteur d’écran.

La CI complète et la recette publiée de la livraison sont à lire sur la PR associée à ce fichier. Les anciennes recettes datées ne sont pas présentées comme de nouveaux essais de cette version. Aucun compte réel, fichier clinique ou décision humaine n’a été modifié par cette préparation.
