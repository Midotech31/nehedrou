# État antérieur — conservé pour traçabilité

Ce fichier décrit la qualification 5, avant la recette et les corrections de la qualification 6. Il ne représente pas l’état actuel.

# Qualification commerciale de Nehdrou

9 octobre 2026 — version améliorée exécutée sur E:. **Vente clinique non qualifiée ; démonstration fonctionnelle livrée.**

La version précédente comportait des défauts concrets, dont huit reproduits dans une base de test isolée. Les corrections ci-dessous sont dans le projet actif. Aucun dossier live réel n’a été utilisé et aucune validation extérieure n’est simulée.

## Fonctions et finition ajoutées

- Accueil centré sur le bénéfice cabinet–maison, avec exemple interactif sans compte en FR/EN/AR.
- Accueil familial avec accès direct aux activités attribuées, consignes, rythme et dernier retour.
- Démarrage praticien en trois étapes ; objectif du programme ; sélection illustrée, ordre réglable et synthèse avant attribution. Le serveur vérifie que l’ordre correspond exactement à la sélection.
- Objectif et consignes visibles avant la pratique ; arrêt dès la première étape ; réponses familiales obligatoires sans présélection ; synthèse enregistrée et activité suivante facultative.
- Parcours de pratique avec ordre figé, même essai à la reprise, démarrage sans doublon, bilan partagé, clôture sans réponses fictives et export/effacement intégrés. Les anciennes pratiques individuelles sont conservées. Voir PARCOURS_PRATIQUE.md.
- Revue hebdomadaire des aides, difficultés et arrêts limitée aux dossiers autorisés. Les chiffres comptent des rapports d’activité, pas des séances thérapeutiques.
- Impression avec objectif, consignes et rythme ; états indisponibles explicites ; erreurs résumées et focus ; flèches adaptées au RTL, texte mixte isolé, petits textes agrandis.
- Logo transparent original inchangé sur une surface claire ; Tajawal locale maintenue pour l’arabe.

## Huit défauts corrigés et tests associés

| Défaut reproduit | Correction livrée |
|---|---|
| Effacement après transfert de responsabilité | Relecture de l’autorisation, du pseudonyme et de la rétention sur objets verrouillés avant suppression ; conflit présenté sans effacement |
| MFA omise pour éditeur ou opérateur financier non staff | Habilitations éditoriales et financières incluses, GET et POST protégés lorsque MFA_REQUIRED est actif |
| Ancien programme démo pratiqué en mode réel | Refus dans le lecteur et le service ; actions et illustrations masquées dans le programme et l’impression ; historique conservé |
| Publication avec audio externe inexistant | Références audio protégées de la même origine, bonne catégorie, droits et fichier présent obligatoires ; disparition ultérieure bloque aussi attribution et pratique |
| Nouvelle rejection ignorée | Dernière décision de chaque discipline sur l’empreinte exacte prise en compte ; rejection bloquante ; avis anciens conservés |
| Attribution depuis objets périmés | Enfant et activités relus sous verrou ; responsable actif, variété, disponibilité, archivage et droits recontrôlés |
| Invitation vers un compte existant produisant une 500 | Connexion proposée ; création concurrente en conflit traitée ; invitation disponible jusqu’à acceptation correcte |
| Panne SMTP après création sans audit | Invitation et audit transactionnels ; état de livraison explicite ; réessai révocable avec nouveau lien ; aucun faux succès de réception |

L’ordre de verrous clinique est harmonisé : cabinet, enfant, objets dépendants. La pratique ajoute le verrou utilisateur pour l’idempotence et verrouille uniquement la ligne ProgramItem lors de sa jointure. Une suite dédiée teste archive/pratique, retrait/attribution et effacement/pratique sur PostgreSQL ; son exécution n’est pas qualifiée dans cet environnement.

## Vérifications effectuées

**89 tests découverts : 83 réussis, 6 ignorés**, suite SQLite terminée avec code 0 en 93,818 secondes. Les six tests ignorés nécessitent PostgreSQL et ne sont pas inclus dans les 83 réussites. Django check : aucune anomalie ; migrations appliquées et aucune modification manquante ; syntaxe des trois scripts JavaScript acceptée par Node.

**572 messages par langue ; 539 clés d’interface vérifiées, zéro traduction manquante** en FR/EN/AR. Une traduction présente n’équivaut pas à une relecture native.

La recherche et les choix de conception sont documentés dans RECHERCHE_PRODUIT.md. Les tests HTTP locaux avec CSRF sont détaillés dans VERIFICATION_PARCOURS.json (douze contrôles actuels) et VERIFICATION_FINALE.json (contrôles précédents datés). Ils vérifient le serveur et le HTML ; ils ne constituent ni une recette JavaScript ni une inspection visuelle.

Le moteur du navigateur intégré échoue avant ouverture avec « failed to write kernel assets ». Aucun rendu final, screenshot final ni enregistrement MP4 n’est revendiqué. BrowserAct est installé sur E: ; le navigateur indépendant vierge proposé attend l’accord explicite requis par son protocole. Designly demande d’examiner le visuel réel et n’autorise pas un feu vert sur un résultat hypothétique.

Le serveur portable PostgreSQL 17.11, copié sur E:, échoue au démarrage sur « could not signal for checkpoint: Operation not permitted ». Une précédente suite partielle ancienne et un démarrage tenté ne valent pas recette actuelle, test de concurrence réussi ni restauration vérifiée.

## État commercial

| Domaine | État actuel |
|---|---|
| Fonctions de démonstration et droits | Testées techniquement, dans les limites ci-dessus |
| Interface et direction de conception | Implémentées ; inspection finale navigateur et relecture native restantes |
| Catalogue clinique | 60 candidats en brouillon ; 0 version clinique approuvée livrée |
| Audio clinique | 0 modèle approuvé livré ; infrastructure d’import/protection/publication présente |
| Utilisabilité terrain | Non évaluée avec praticiens et familles |
| Production | HTTPS, SMTP, PostgreSQL, concurrence, restauration et exploitation à qualifier sur environnement réel |
| Offre de vente | Marché, entité, prix, conditions et support à définir ; facturation manuelle déjà implémentée |

La commande `manage.py check_readiness --json` produit les blocages techniques sans exposer de secrets ; `--strict` échoue lorsque ces contrôles manquent. Elle ne certifie pas l’efficacité ni la conformité du service.

**Conclusion :** la base logicielle est améliorée et démontrable avec des données fictives. La présenter comme un produit clinique prêt à vendre serait trompeur. LANCEMENT.md précise les preuves permettant de clôturer chaque condition. Les validations professionnelles des exercices et modèles audio ne peuvent pas être fabriquées par du code.
