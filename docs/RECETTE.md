# Qualification actuelle — version 6

102 tests PostgreSQL réussis, 96 SQLite réussis et 6 ignorés, restauration locale isolée et recette Chrome exécutées. Voir QUALIFICATION_COMMERCIALE.md et RECETTE_NAVIGATEUR.md. Les sections ci-dessous retracent les qualifications antérieures, sans constituer l’état final.

# Révision langues et présentation — 9 octobre 2026

- 44 tests passent sur SQLite (dernière suite complète : 47,189 secondes).
- Les neuf combinaisons FR/EN/AR sont testées sans dépendre d’un cookie ou de l’en-tête Referer. La page et ses filtres sont conservés.
- 435 messages par langue ; 415 clés d’interface recensées par scripts/check_translations.py ; aucune entrée manquante.
- Vérifications HTTP avec authentification et CSRF sur le serveur actif : accueil, tableau de bord, profils, bibliothèque et préférences en FR/EN/AR ; HTTP 200. Les passages AR→FR, FR→EN, EN→AR conservent les filtres.
- Recherche de profils et filtres de langue ne contournent pas l’isolation des accès.
- Syntaxe des deux scripts de parcours vérifiée avec Node ; aucune migration manquante.
- La capture du navigateur intégré échoue dans l’environnement ; un essai Edge headless n’a produit aucune capture. Aucun contrôle visuel complet ou conformité d’accessibilité n’est revendiqué.

La qualité commerciale et la validité clinique ne se déduisent pas du nombre de tests. Une recette visuelle complète, les relectures professionnelles, les audios approuvés et le déploiement restent nécessaires.

---

# Recette complémentaire — 9 octobre 2026

Suite complète : **37 tests passent sur PostgreSQL 17.11** (58,452 s). Sur SQLite, les 30 tests initiaux et les 7 complémentaires passent également. Les migrations ont été appliquées sur PostgreSQL et SQLite. Les nouveaux tests couvrent l’inventaire des 60 brouillons, l’import idempotent, le refus de publication directe, les permissions par variété, l’exclusion des familles de l’édition/facturation, le rendu des écrans éditoriaux, la MFA obligatoire et les codes de récupération à usage unique.

Ces tests ne remplacent pas une recette visuelle, une validation clinique, un test de charge, une simulation complète de concurrence ou un audit indépendant. Le navigateur automatisé reste indisponible dans cet environnement.

Le catalogue est préparé pour validation conformément à la réponse du commanditaire. Les copies publiées en mode démonstration sont des exemples non validés. Aucun modèle audio clinique approuvé n’est livré.

---

Historique de la recette initiale (les points restant à faire ci-dessous doivent être lus avec les ajouts décrits dans README) :

# Recette — 9 octobre 2026

## Vérifications exécutées

**30 tests comportementaux passent**, avec Django 5.2.18, Python 3.12.4 et SQLite. Dernière exécution : 30 tests en 30,923 secondes, résultat OK. Les tests ont été relancés après les modifications finales des modèles, services, traductions et dépendances. Aucune validation clinique ou commerciale n’a été effectuée.

| Vérification | Résultat |
|---|---|
| Migrations initiales et complémentaires sur une base locale vide | Réussies |
| `manage.py check` | Aucune anomalie |
| `makemigrations --check --dry-run` | Aucune modification non migrée |
| `manage.py test core` | 30 tests, OK |
| Compilation Python | Réussie |
| Compilation des messages fr/en/ar | 213 entrées par langue, sources PO et MO présentes |
| Import JSON fourni, sans `--apply` | 1 ligne valide ; rien sauvegardé |
| `check --deploy` avec paramètres de production et PostgreSQL configuré | Aucune anomalie ; ne vérifie pas une connexion effective ni un déploiement |
| Production sans PostgreSQL | Démarrage refusé comme prévu |
| Serveur local, pages publiques FR/EN/AR | HTTP 200 ; direction LTR/LTR/RTL |
| Chargement CSS local | HTTP 200 |
| Navigateur intégré | Ouverture demandée ; automatisation visuelle indisponible, aucun contrôle visuel revendiqué |

## Matrice de critères reliés au cadrage

| Exigence / risque | Critère | Preuve actuelle | Vérification restante |
|---|---|---|---|
| §5–7 séparation des cabinets | Lectures, actions, impression et export d’un autre cabinet refusés | Tests avec deux cabinets ; 404 | Répéter sur PostgreSQL et revue indépendante |
| §5 responsable et clinique | Le manager n’accède pas aux dossiers d’un autre responsable | Test rôle owner sans responsabilité | Transfert professionnel et accès support contrôlé |
| §5 accès familial | Seul profil lié ; retrait du lien coupe tous les accès | Tests lectures/activité/impression/export et révocation | UX de retrait avec famille pilote |
| §5 révocation membre | Session connectée ne maintient pas l’accès clinique | Test d’adhésion inactive | Révocations concurrentes PostgreSQL |
| §7 cohérence des liens | Relations cabinet/enfant/programme/session incohérentes rejetées | Tests validations modèle | Contraintes supplémentaires si écriture SQL externe |
| §4,7 attribution | Activités publiées et variété du profil uniquement | Tests variété incompatible, brouillon et mode réel | Catalogue clinique de la variété retenue |
| §4 interface | Changement UI sans mutation de variété du programme | Test de set_language | Parcours manuel multi-langue |
| §4 indisponibilité | Aucune consigne silencieusement remplacée | Test de version legacy incomplète, réponse 409 | Messages relus culturellement |
| §7,8 versionnement | Contenu publié immuable, retrait sans perte de pratique | Test de modification et retrait | Inventaire des programmes affectés dans espace éditorial |
| §8 relecture | Revue attachée à une empreinte ; modification invalide validation | Test positif et négatif | Qualification/attribution des relecteurs et workflow strict |
| §7 idempotence | Même ticket/données → même session ; conflit → rejet | Test service et ticket signé lié à l’utilisateur | Deux requêtes simultanées sur PostgreSQL |
| §3,7 interprétation | Arrêt exclu du dénominateur, qualité de parole non notée | Test correct=null et synthèse | Compréhension des écrans auprès des parents |
| §3,7 provenance | Auteur/rôle, déclaration et observation séparés | Test parcours complet et export familial | Relecture des libellés et recherche clinique distincte |
| §5 invitations | Expiration, révocation, usage unique et courriel lié | Tests et parcours complet via backend mail mémoire | SMTP et délivrabilité réelle |
| §10 récupération | Message neutre, jeton invalidé après changement de mot de passe | Test récupération et absence d’enfant dans le mail | Identité/courriel confirmé et MFA |
| §10 CSRF | Mutation sans jeton refusée | Test avec contrôle CSRF actif, 403 | Revue déploiement/proxy |
| §10 limitation | Plus de 15 POST sensibles dans la fenêtre : 429 | Test authentification | Débit au proxy et charge concurrente |
| §11 quotas | Profil/praticien supplémentaires refusés au quota | Tests quota, admission praticien et archive | Facturation opérable et migration de plans |
| §11 expiration | Pas de nouvelle attribution ; données et export conservés | Test expiration | Décider éventuelle période de grâce |
| §8 import | Fichier invalide rollback complet ; dry-run sans écriture ; brouillon uniquement | Test transactionnel et exemple de fichier réel validé | Import catalogue original validé |
| §9 langues et RTL | Toutes les vues principales rendent en fr/en/ar | Tests de pages et marqueurs HTML ; vérification HTTP publique | Clavier, contraste, lecteur d’écran, mobile, textes mixtes, impression réelle |
| §10 données | Export familial sans observation professionnelle et no-store | Test export et en-têtes | Politique de conservation et demandes d’effacement opérables |
| §14 exploitation | Migrations et sauvegarde PostgreSQL restaurable | Configuration et procédure fournies | PostgreSQL, Docker, sauvegarde/restauration non exécutés |
| §14 dépendances | Versions et hashes fixés, aucun secret embarqué dans archive | requirements.lock et archive sans base/secret | Veille et mises à jour de sécurité |

## Tests de navigateur à exécuter

Sur petits écrans 360/390 px et écran bureau : navigation clavier intégrale, focus visible, zoom 200–400 %, lecteurs d’écran FR/EN/AR, longues chaînes arabes, courriels et transcriptions LTR, impression PDF arabe et pagination. Vérifier les labels radio, feedback d’erreur, voix/audio et alternatives après ajout de contenus réels. Le CSS prévoit ces usages ; la conformité WCAG 2.2 AA n’est pas démontrée par des tests de rendu HTML.

L’outil d’automatisation du navigateur n’a pas pu initialiser son runtime dans cet environnement. Les contrôles HTTP et les tests serveur ne remplacent pas cette recette visuelle.

## PostgreSQL et restauration — prérequis

Installer PostgreSQL 17 ou Docker Desktop/Compose, fournir les secrets de développement, lancer migrations et `manage.py test core`. Compléter par deux transactions concurrentes : admission au dernier quota et retransmission de session ; vérifier absence de dépassement/doublon. Réaliser la procédure de restauration dans EXPLOITATION.md vers une nouvelle base et conserver un procès-verbal. SQLite seul ne constitue pas une validation PostgreSQL.

## Réception proposée

Livraison acceptée pour **démonstration fictive de bout en bout**. Le passage à des données réelles et au pilote facturé nécessite la fermeture des points de CONCEPTION.md : contenu relu, qualification, contrats, MFA/identité, exploitation et restauration, recette PostgreSQL et accessibilité. Les conditions non exécutées restent des travaux à faire.

## Finition Tajawal

Après la finition de l’interface : contrôle Django sans anomalie ; test existant de rendu de toutes les pages principales FR/EN/AR réussi ; page arabe et feuille de finition HTTP 200 ; quatre fichiers TrueType HTTP 200. Les polices sont préchargées en arabe et la licence OFL est incluse. La vérification visuelle de navigateur reste à effectuer.

## Logo fourni

Copie identique au fichier source (SHA-256 comparé). Présence vérifiée dans les pages publiques FR/EN/AR et chargement HTTP 200 du PNG. Contrôle Django sans anomalie. Adaptation mobile prévue par CSS ; pas de nouvelle validation visuelle revendiquée.

## Clarté de la première vue

Titre descriptif, rôle du praticien et de la famille, statut de démonstration avant inscription, absence d’offre payante et limites cliniques explicités en FR/EN/AR. Contrôle HTTP 200 et vérification des textes et de leur ordre dans les trois pages publiques. Catalogues mis à jour : 240 entrées par langue.

Précision PostgreSQL : les 37 tests ont produit OK, mais la commande a fini avec un code de sortie 1 lors de la suppression de la base de test (signal de checkpoint refusé par l’environnement Windows). La recette PostgreSQL n’est donc pas entièrement clôturée. Aucun test de restauration complète n’est revendiqué.


## Révision après la capture arabe — 9 octobre 2026

Exécution depuis E:\LocalCoderWorkspace\Nehdrou\outputs\nehdrou : 54 tests SQLite réussis en 53,716 s, nettoyage réussi et zéro erreur système. Sept tests supplémentaires portent sur l’exemple public sans accès SQL, le CSRF, les réponses invalides, l’arrêt et l’indisponibilité en mode réel. Contrôle gettext : 486 messages par langue, 460 clés utilisées, aucune traduction manquante FR/EN/AR. Node valide la syntaxe de activity.js. Les GET et POST avec CSRF de /try/ produisent une synthèse dans les trois langues sur le serveur local. Aucun rapport n’est sauvegardé par ce parcours.

La capture arabe du commanditaire permet un constat sur la révision précédente. La révision présente n’a pas encore reçu de recette interactive navigateur complète, ni de validation mobile/clavier, ni de validation clinique. Voir QUALIFICATION_COMMERCIALE.md pour la décision actuelle.

## Parcours reprenable — qualification 5

Suite finale : 89 tests découverts, 83 réussis et 6 ignorés sur SQLite en 93,818 s, code 0. Les six cas de concurrence PostgreSQL ne sont pas comptés comme réussis. Catalogue : 572 messages par langue, 539 clés utilisées, zéro traduction manquante. Migration care.0006 appliquée ; aucune modification de modèle manquante. Douze vérifications HTTP/CSRF dans VERIFICATION_PARCOURS.json. Les rendus navigateur, la recette clavier/mobile, la relecture native, PostgreSQL/restauration et les contenus cliniques restent à qualifier. Voir PARCOURS_PRATIQUE.md et QUALIFICATION_COMMERCIALE.md.
