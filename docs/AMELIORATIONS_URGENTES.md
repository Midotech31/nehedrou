# Quatre améliorations — 10 octobre 2026

Cette livraison renforce la démonstration fonctionnelle de Nehedrou : pratique à domicile accompagnée, objectifs et activités choisis par l’orthophoniste. Elle ne délivre pas une validation clinique de l’application.

## Identité et crédit

Le logo fourni représentant un enfant qui parle remplace les bulles dans l’en-tête, l’icône navigateur et l’icône d’écran d’accueil. Le PNG original carré est conservé sans transformation. Son empreinte SHA-256 est `6041cff35999c074a1bf9a4b715f2a87f5f34e01f193941cb024a1fe39890909`. Le nom reste visible sur téléphone ; les tailles CSS sont 48, 56 ou 72 pixels selon l’écran. Le pied de page affiche exactement **Designed by Benabdeloued Mohamed Alias Pitou**, avec `lang="en"`, `dir="ltr"` et isolation bidirectionnelle.

## Contenus, preuves et statuts

Le corpus actif comprend 37 fiches v2 : 19 FR, 17 EN et une proposition locale en darja. Chaque fiche précise objectif, public, découverte, choix d’image, échange, aides, limites et points linguistiques à relire dans les trois langues de consignes. Ces guides sont accessibles en bibliothèque, programme, pratique et impression. Les sources précisent ce qu’elles étayent : méthode ou fait linguistique, sans valider la fiche ni Nehedrou.

Les brouillons réels restent à relire ; leurs copies de démonstration portent un avertissement explicite. Aucun audio clinique approuvé ni résultat thérapeutique n’est inventé. Les transcriptions FR/EN sont des propositions de travail. Pour la darja, دار / نار est documenté à Dellys par Souag (2005), sans en déduire une prononciation nationale ou une validité pédiatrique actuelle.

Vingt-trois propositions sont mises en attente : homophonie française, images anglaises inexactes, ambiguïté vocalique ou absence d’analyse locale suffisante. Les anciennes versions, programmes, rapports et relectures sont conservés. Elles sont exclues des nouvelles sélections ; les nouveaux champs vides préservent les anciennes empreintes de contenu. Tout enrichissement est inclus dans l’empreinte à relire.

Les exemples publics sont réellement adaptés : chat/rat et leurs images en FR, coat/goat en EN, دار/نار avec maison/feu en AR. La proposition darja conserve son statut local à relire. Voir [la recherche et ses limites](RECHERCHE_CONTENUS_2026.md), [le processus de validation](CONTENUS_A_VALIDER.md) et les raisons détaillées dans `catalog-exclusions-v2.json`.

## Accès par rôle

Sept profils sont séparés : responsable de cabinet, orthophoniste, accompagnant, éditeur, relecteur clinique, relecteur linguistique et gestionnaire des accès/factures. Le cabinet fictif dédié contient Maya et Sami, avec des programmes guidés dans les trois variétés. Les responsabilités cliniques restent individuelles ; un responsable de cabinet ne voit pas automatiquement les dossiers d’un autre orthophoniste. Le gestionnaire n’a pas d’accès clinique et n’est pas superutilisateur.

Les quatre comptes historiques sont conservés. L’initialisation ne réinitialise pas les mots de passe, quotas, affiliations révoquées ou programmes modifiés. Une collision avec un compte non fictif est refusée atomiquement. Les exemples permettant les relectures portent un nom et un statut fictifs ; une décision sur eux ne valide aucun contenu clinique.

Les mots de passe hébergés sont distincts, dans l’environnement privé Render et un tableau remis séparément. Ils sont exclus du code, du dépôt public, des pages et de l’archive. Les [droits et parcours de recette](ROLES_DEMONSTRATION.md) sont documentés sans secrets.

## Vérifications et publication

Les vérifications comprennent Django, absence de migration manquante, compilation des langues, statiques avec manifest, suites SQLite/PostgreSQL, démarrage hébergé, HTTPS, permissions des sept profils et rendu responsive FR/EN/AR. Les preuves actuelles sont remises séparément ; les rapports historiques ne doivent pas être confondus avec cette recette.

Avant publication : 137 tests découverts sous SQLite, 131 réussis et six cas réservés à PostgreSQL ignorés ; 137 tests réussis sous PostgreSQL, aucun ignoré. Les 635 messages par langue couvrent 599 clés d’interface, sans manque. Les neuf rendus locaux FR/EN/AR à 320, 768 et 1280 pixels présentent le logo chargé à ses proportions et le crédit exact sans débordement horizontal. Ces contrôles ne constituent pas des essais cliniques.

Le déploiement `dep-db5bav7lk1mc739d8djg` du commit `2acbb16c18726fb8831634dcb699e32bb50b4d9e` est live depuis 22:02:50 UTC. La recette distante passe 101 contrôles HTTPS, 170 contrôles des sept rôles et 24 contrôles navigateur, dont neuf affichages responsive et un parcours arabe réellement enregistré. Un contrôle PostgreSQL complémentaire prouve le verrouillage et le refus d’attribution après retrait d’une activité. Aucun résultat de ces vérifications techniques n’est une validation clinique.

Le service de test est [Nehedrou sur Render](https://nehedrou-demo.onrender.com/ar/), dans le dépôt [Midotech31/nehedrou](https://github.com/Midotech31/nehedrou). Le stockage de démonstration est temporaire et réservé aux données fictives. Les contenus/audio, la relecture locale et une évaluation clinique de l’application restent des étapes distinctes à réaliser.
