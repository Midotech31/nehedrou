# Livraison finale — Nehedrou, version 6

## Verdict

Version fonctionnelle et présentable avec des dossiers fictifs. La vente pour un usage clinique réel et une commercialisation internationale restent non qualifiées : aucun exercice ni modèle audio clinique approuvé n'est fourni. Le corpus actif comprend 37 fiches v2 à relire ; les 60 propositions v1 restent archivées. Les changements scientifiques sont documentés dans RECHERCHE_CONTENUS_2026.md. La note de 9,5/10 n'est pas attribuée artificiellement ; les dimensions et critères figurent dans QUALIFICATION_COMMERCIALE.md.

## Utiliser le projet sur E:

Le projet actif est dans `E:\LocalCoderWorkspace\Nehdrou\outputs\nehdrou`. Le lanceur est `E:\LocalCoderWorkspace\Nehdrou\Demarrer-Nehdrou.cmd`. Le serveur de démonstration peut rester accessible pendant cette livraison sur [l'accueil français](http://127.0.0.1:8000/fr/), [anglais](http://127.0.0.1:8000/en/) ou [arabe](http://127.0.0.1:8000/ar/?v=qualification-6b). L'exemple public est à `/fr/try/`, `/en/try/` ou `/ar/try/` ; il ne crée pas de rapport en base.

Comptes fictifs : `praticien`, `famille`, `autre_praticien`, `editorial`. Le mot de passe local est dans le fichier privé `.demo-password` du projet actif. Il est exclu de l'archive ; aucun compte réel ou secret de production n'est livré. Une nouvelle installation génère ses propres accès de démonstration via `start.py`. Suivre README.md pour les dépendances et le lancement ; `.env.example` est un modèle, pas une configuration prête à héberger des dossiers cliniques.

## Démonstration de cinq à dix minutes

1. Montrer l'accueil puis l'exemple public : découvrir, choisir une image et renseigner la participation ; essayer aussi l'arrêt. Expliquer la continuité entre cabinet et maison et le statut fictif.
2. En praticien, ouvrir un dossier, personnaliser objectif, consignes et rythme, sélectionner et ordonner les activités ; vérifier la synthèse avant attribution.
3. En famille, commencer ou reprendre un parcours ; renseigner la participation ou arrêter, puis retrouver le bilan. La sélection d'image n'évalue pas la prononciation.
4. En praticien, consulter l'historique filtrable et le rapport ; publier un retour partagé avec la famille et montrer que les observations privées restent distinctes.
5. Présenter l'impression, l'export structuré et l'édition contrôlée des contenus. Changer la langue en gardant le contexte ; les textes libres du praticien ne sont pas traduits automatiquement.

Le scénario complet est une présentation proposée. Les interactions effectivement exécutées dans Chrome et leur périmètre se trouvent dans RECETTE_NAVIGATEUR.md ; ne pas les confondre avec une recette exhaustive de toutes les combinaisons.

## Contenu de la livraison

`Nehdrou_Django.zip` contient le code Django, les migrations, les tests, les templates, les polices locales, le logo original sur fond clair, les dépendances avec empreintes et la documentation. Il exclut les bases, secrets, médias téléversés et environnements locaux. Le fichier SHA-256 permet de contrôler l'intégrité du téléchargement. La licence du logiciel et celles des ressources sont conservées ; la validation technique d'un fichier n'accorde pas de droits sur son contenu.

Les preuves principales : 102 tests PostgreSQL réussis, dont six essais de concurrence ; 96 tests SQLite réussis et six réservés à PostgreSQL ; deux régressions de finition ; restauration fictive dans une base distincte avec 36 tables et contrôles d'accès ; 12 contrôles HTTP ; matrice Chrome des pages publiques et parcours authentifiés documentés. Les mesures locales ne constituent pas un essai de charge en production. Consulter VERIFICATION_VERSION_6.json et les journaux.

La recherche scientifique et concurrentielle datée, les hypothèses de prix et les coûts incomplets explicitement délimités figurent dans RECHERCHE_PRODUIT_2026.md. Aucune disposition à payer, rétention ou efficacité clinique de Nehedrou n'est démontrée.

## Conditions restantes avant vente clinique

Faire approuver un premier corpus limité et ses enregistrements adultes avec leurs droits, obtenir une relecture native des variétés annoncées, observer des praticiens et familles, puis qualifier l'exploitation réelle : HTTPS, PostgreSQL, MFA, réception SMTP, sauvegardes restaurables, assistance, offre et obligations du marché choisi. Les vérifications de disponibilité restent volontairement négatives dans la configuration locale de démonstration. Voir LANCEMENT.md et QUALIFICATION_COMMERCIALE.md pour les conditions vérifiables.

La version actuelle est un outil concret de présentation et de validation de produit. Elle ne permet pas de promettre une guérison, un diagnostic automatisé ou une vente internationale immédiate.
