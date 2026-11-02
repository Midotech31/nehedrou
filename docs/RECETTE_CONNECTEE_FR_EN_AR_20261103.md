# Recette connectée publiée FR/EN/AR — 3 novembre 2026

La reprise du navigateur intégré a permis de terminer les connexions sur la version publiée `225b114` (PR47). Le réveil initial du service Render gratuit a été observé avant la recette ; les expirations initiales ne sont pas comptées comme des connexions réussies.

## Portée et preuve

Les douze comptes fictifs ont chacun été connectés par le formulaire public dans les trois langues, avec déconnexion entre les sessions : **36 combinaisons compte/langue distinctes réussies**. La page d’arrivée a confirmé le compte, la langue, le sens de lecture, la feuille de style publiée et le crédit exact de conception. Le bouton afficher/masquer le mot de passe a été exercé dans les trois langues avec le relecteur clinique, puis remis en mode masqué avant toute capture.

Les 201 observations initiales, dont les 36 connexions, ont été exportées dans un fichier privé sur le poste, sans mot de passe, cookie, jeton CSRF ou état interne de l’application. La matrice exportée a été contrôlée séparément : douze comptes, trois langues par compte, aucune erreur de formulaire dans les connexions retenues. Les observations mobiles/tablette sont distinctes.

La recette publiée lit les écrans et les refus. Elle ne soumet aucun avis humain, n’approuve aucun contenu, ne publie aucun corpus, ne démarre aucun exercice clinique, et ne crée ni dossier, invitation, facture, droit ou fichier média. Les écritures sur packs/protocoles restent couvertes par la [recette locale précédente](RECETTE_ROLES_PROTOCOLS_PACKS_20261101.md) et les tests automatisés ; elles ne sont pas présentées comme des écritures publiées réalisées ce jour.

## Matrice des comptes

Chaque ligne ci-dessous comporte une connexion formulaire EN, FR et AR réussie ; les parcours et refus indiqués ont aussi été observés dans les trois interfaces.

| Compte fictif | Parcours effectivement contrôlés |
|---|---|
| `relecteur_clinique` | Arrivée éditoriale ; brouillon sans formulaire de revue ; contenu soumis limité à la revue clinique ; bibliothèque et détail de protocole ; création de pack refusée. |
| `relecteur_linguistique` | Arrivée éditoriale ; contenu soumis limité à la revue linguistique ; création de pack refusée. |
| `editeur` | Création d’activité de zéro, de pack et de protocole ; variété et position explicites ; édition d’un protocole ancien non attaché avec choix vide ; refus d’édition d’un protocole déjà utilisé. Aucun formulaire enregistré. |
| `pitou` | Arrivée hybride, création d’activité de zéro sur quatre variétés et liste de dossiers non attribués. Aucun droit de relecture ou publication ajouté. |
| `responsable` | Liste de son dossier attribué, gestion des membres ; dossier d’un autre périmètre refusé et facturation de plateforme refusée. |
| `orthophoniste` | Liste et détail du dossier attribué ; refus du dossier du responsable et de la gestion des membres. |
| `accompagnant` | Liste et détail du dossier attribué sans actions cliniques, lecture de son programme darija ; qualification et édition clinique refusées. |
| `gestionnaire` | Arrivée en facturation, diagnostic d’hébergement et rapport de lancement ; dossier clinique refusé. |
| `praticien` | Liste des trois dossiers historiques attribués ; dossier du nouveau cabinet refusé. |
| `famille` | Un seul dossier historique attribué et son programme ; autre enfant du même cabinet refusé. |
| `autre_praticien` | Profil de son cabinet indépendant ; dossiers des deux autres cabinets refusés. |
| `editorial` | Arrivée historique ; deux disciplines de revue et transitions de sa portée historique ; dossier clinique refusé. Aucune action de revue ou transition exécutée. |

Les refus sont des pages localisées avec liens de récupération ; ils ne donnent aucun accès supplémentaire. L’édition d’un protocole attaché à un objectif ou à une administration reste refusée : la correction de position ancienne n’autorise pas à réécrire un protocole figé.

## Mobile, tablette et langues

Le même protocole fictif publié a été examiné dans les trois langues aux fenêtres 390 × 844 et 768 × 1024. Largeurs utile/document : 375/375 et 753/753 px respectivement, sans débordement horizontal du document. L’arabe rend `dir=rtl` et Tajawal ; le logo fourni et le crédit de conception sont présents. Une capture arabe mobile a été conservée hors du dépôt.

Ces fenêtres ne constituent pas des essais sur téléphones physiques ni une validation exhaustive au clavier ou avec un lecteur d’écran. Le nom du compte est volontairement masqué par le CSS en largeur mobile ; le collecteur de preuve utilise le nœud de nom rendu et la page protégée, sans interpréter cette présentation comme une déconnexion.

## Défaut reproduit et corrigé dans ce lot

Le rapport `/operations/readiness/` affichait la clé brute `offered_content_varieties_exist` dans ses trois langues. La commande émettait correctement ce contrôle, mais sa table de libellés HTML ne le couvrait pas.

Le correctif ajoute « Offered spoken varieties exist in the catalogue » et ses traductions françaises et arabes. La régression parcourt les contrôles réellement émis et vérifie qu’aucune clé machine n’est exposée comme libellé HTML. Le téléchargement JSON conserve les clés et valeurs originales : aucune porte de lancement, permission ou décision clinique n’est modifiée.

La régression a échoué avant correction dans les trois langues. Après correction : 29 tests opérations/readiness réussis, dont deux cas PostgreSQL ignorés localement ; `check` et compilation réussis ; 1909 clés UI par langue sans manque. La CI du HEAD final et la publication du correctif sont à confirmer dans la PR et le bilan de livraison, sans les anticiper ici.

## Conditions de commercialisation encore ouvertes

Le rapport publié observé le 2 novembre à 23:14 UTC confirme le mode démonstration actif, la MFA privilégiée non obligatoire, l’absence de transport de courriels pris en charge et zéro entrée active du registre de traitement de plateforme.

Il compte **zéro contenu non démo disponible dans chacune des quatre variétés proposées** et zéro protocole réel publié/disponible. Les dernières versions des activités réelles restent toutes en brouillon et manquent d’au moins une référence audio : FR 19, EN-US 17, arabe standard 42, darija pilote 33. La présence des champs et des propositions ne remplace pas les enregistrements exacts, les droits, la familiarité et les revues humaines des versions effectivement proposées.

La vente reste subordonnée à un corpus utile et cohérent effectivement validé pour l’offre retenue, à des responsables réels de revue/publication, au cadre du vendeur et de l’offre, et à l’acceptation de l’exploitation : courriels/récupération, MFA, registre, sauvegardes hors machine planifiées, supervision et reprise. Aucune efficacité clinique, conformité réglementaire ou autorisation de vente n’est déduite de ces tests.

Voir [la checklist de lancement](CHECKLIST_LANCEMENT_ALGERIE_20261101.md), [les rôles disponibles](ROLES_DEMONSTRATION.md) et [le lot logiciel précédent](RECETTE_ROLES_PROTOCOLS_PACKS_20261101.md).
