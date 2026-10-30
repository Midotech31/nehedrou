# Historique des livraisons locales

Les chiffres et états ci-dessous sont historiques. Le README et l'[inventaire horodaté](INVENTAIRE_CONTENUS.md) décrivent la portée courante ; QUALIFICATION_COMMERCIALE.md reste un rapport daté de la version 6.

# Dossier actif sur E:

Le dossier de travail actuel est `E:\LocalCoderWorkspace\Nehdrou\outputs\nehdrou`.
Lancer `E:\LocalCoderWorkspace\Nehdrou\Demarrer-Nehdrou.cmd`, puis ouvrir http://127.0.0.1:8000/fr/.
Django, BrowserAct, uv, cache et fichiers temporaires sont préparés sur E:. La copie sur C: est conservée.
Le serveur de démonstration peut déjà être actif : inutile de le démarrer deux fois.

# Qualification du 9 octobre 2026

La version actuelle reste une démonstration technique, sans feu vert pour la vente clinique. Le dossier docs/QUALIFICATION_COMMERCIALE.md présente les critères, les preuves et les blocages concrets.

Nouveautés de cette qualification : thème unifié product.css, navigation par rôle, réglages regroupés, aide multilingue, contrats de contraste, fermeture de la pratique pour un profil archivé et relecture de l’état du programme avant enregistrement. La suite compte 47 tests, tous réussis sur SQLite ; 461 messages par langue et 441 clés d’interface contrôlées sans entrée manquante.

Les sections ci-dessous conservent l’historique des révisions précédentes ; les chiffres courants sont ceux indiqués ci-dessus.

---

# Livraison révisée — langues et expérience utilisateur

Révision du 9 octobre 2026 : le défaut du passage arabe → français a été reproduit puis corrigé. Les trois boutons de langue conservent la page et ses filtres. Les catalogues comprennent 435 messages par langue ; le contrôle automatique couvre 415 clés d’interface et ne trouve aucune traduction manquante.

Accueil avec aperçu du produit, tableau de bord avec participations réelles sur sept jours, bibliothèque avec filtres de langue/variété et disponibilité audio, recherche de profils actifs/archivés, choix visuel des activités dans le programme et préférences linguistiques explicites. Les textes du professionnel et les mots des exercices ne sont pas automatiquement traduits : leur langue fait partie du contenu choisi.

La suite actuelle comporte 44 tests, tous réussis sur SQLite. Les pages principales et les changements de langue ont également été vérifiés par HTTP sur le serveur actif avec authentification et CSRF. Les scripts du lecteur et du créateur de programme passent le contrôle syntaxique Node. La capture visuelle automatisée est indisponible (outil navigateur défaillant et lancement headless Edge refusé) ; aucune recette visuelle complète n’est revendiquée.

Cette révision améliore la démonstration fonctionnelle. Elle n’établit pas que l’application est prête à vendre : validation clinique, modèles audio autorisés, déploiement réel et recette visuelle restent à finaliser.

---

# Nehdrou — نهدروا

Première version Django exécutable, livrée le 9 octobre 2026. **Démonstration avec données fictives.** Le document fourni demandait une conception ; la demande dans le chat a ensuite autorisé la réalisation. Cette livraison comprend le code et la conception, sans lancement commercial.

## Ouvrir l’application

Depuis ce dossier, dans un terminal :

```powershell
python start.py
```

Ouvrir **http://127.0.0.1:8000/fr/**. Le script affiche un mot de passe généré pour les comptes `praticien`, `famille`, `autre_praticien` et `editorial`. Il le conserve dans `.demo-password` pour les relancements. Ce fichier reste local. Les comptes existants ne sont jamais réinitialisés automatiquement. Le script réutilise l’environnement Python préparé dans l’espace de travail lorsqu’il existe ; sinon il crée `.venv` avec une installation standard de Python 3.12 disposant de pip.

Le serveur reste dans le terminal. **Ctrl+C** l’arrête. Le script et Docker Compose sont destinés au développement uniquement.

## Installation standard

Prérequis : Python 3.12 à jour avec pip. Sous Linux/macOS remplacer `.venv\Scripts\python.exe` par `.venv/bin/python`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
$env:DEMO_PASSWORD = 'CHOISIR-un-mot-de-passe-local-de-plus-de-12-caracteres'
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

`requirements.txt` verrouille les versions ; `requirements.lock` ajoute les empreintes des distributions officielles PyPI. Ne pas réutiliser l’exemple de mot de passe. `.env.example` documente les variables **sans les charger automatiquement**.

## Essayer le parcours

1. Connectez-vous comme `praticien`. Explorez les trois profils fictifs, la bibliothèque et les programmes.
2. Ajoutez un profil de 4 à 7 ans ; sélectionnez sa variété parlée ; attribuez des activités de cette même variété.
3. Invitez un accompagnant depuis la fiche. Le backend local imprime le courriel dans la console. Le lien est valable trois jours, lié à l’adresse invitée et utilisable une seule fois.
4. Connectez-vous comme `famille` : seul le profil Lina est accessible. Ouvrez l’activité, choisissez une image et enregistrez un retour. Essayez une tentative interrompue.
5. Retrouvez la synthèse comme praticien ; ajoutez une observation professionnelle ; imprimez le support ou exportez le JSON autorisé.
6. Passez l’interface en arabe : navigation RTL, programme inchangé. Changez séparément la langue des consignes dans Préférences.
7. Révoquez le lien familial puis reconnectez-vous comme `famille` : les URL du profil, programme, impression, activité et export ne donnent plus accès.
8. Connectez-vous comme `editorial` sur `/fr/editorial/` pour le catalogue. Aucun dossier d’enfant n’est exposé dans l’administration technique.

Le responsable peut inviter un praticien dans Membres du cabinet. Le quota est vérifié à l’acceptation. La gestion des membres n’accorde pas automatiquement l’accès aux dossiers d’un autre professionnel.

## Fonctionnalités réalisées

- Comptes, sessions, inscription professionnelle, récupération de mot de passe ; invitations familiales et professionnelles temporaires, révocables et liées au courriel.
- Cabinets séparés, responsables et praticiens, contrôles des objets côté serveur, révocation des liens et adhésions.
- Profils minimaux, variétés parlées, programmes ordonnés, contenus attribués par version, archivage de profil et clôture de programme.
- Catalogue filtrable, contenus versionnés, conditions de publication, relectures liées à l’empreinte exacte du contenu, retrait sans réécriture de l’historique.
- Familiarisation, choix d’image évalué côté serveur, production accompagnée sans note de prononciation ; tentatives arrêtées ; idempotence signée.
- Déclarations avec identité et rôle de l’auteur ; observations professionnelles à accès limité ; synthèse, impression HTML et export JSON.
- Interface française, anglaise et arabe avec gettext, 435 messages par langue, RTL, Tajawal hébergée localement pour l’arabe et CSS responsive.
- Droits de pilote manuels, quotas, échéance, montant décimal et devise distincte ; journal d’actions ; demandes d’effacement à traitement manuel.
- Migrations, tests comportementaux, configuration PostgreSQL 17, Docker de développement, import éditorial JSON validé et atomique.

## Limites de la livraison actuelle

Le catalogue comprend 60 fiches candidates (20 par langue) et 63 exemples en mode démonstration, avec 98 pictogrammes originaux. Ces propositions lexicales ne sont pas des paires minimales cliniquement validées. Aucun modèle audio clinique ou transcription approuvée n’est fourni. Le lecteur accepte des médias éditoriaux autorisés ; en démonstration, l’accompagnant lit le mot.

L’espace éditorial, les droits par variété, la MFA avec récupération, la réattribution des profils et le traitement des demandes d’effacement sont implémentés. L’administration technique locale reste désactivée en configuration réelle ; les opérations disposent de vues dédiées. La qualification des relecteurs, la politique applicable de conservation, la validation des contenus, le déploiement et la recette visuelle indépendante restent nécessaires avant commercialisation.

## PostgreSQL 17

Prérequis : Docker Desktop avec Compose ou installation PostgreSQL 17. Docker n’a pas été utilisé pour la recette. PostgreSQL 17.11 a été exécuté localement ; le nettoyage de la base de test a rencontré une restriction Windows, documentée dans RECETTE.md.

```powershell
$env:POSTGRES_PASSWORD = 'CHOISIR-un-secret-de-developpement'
$env:DEMO_PASSWORD = 'CHOISIR-un-mot-de-passe-de-demonstration'
docker compose up --build
docker compose exec web python manage.py test core
docker compose exec web python manage.py makemigrations --check --dry-run
```

Pour PostgreSQL local sans Docker : définir `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, puis exécuter migrations et tests. SQLite est un secours local ; ses résultats ne valident pas les verrous concurrentiels de PostgreSQL.

## Commandes utiles

Avec le Python de votre environnement :

```powershell
python manage.py check
python manage.py test core
python manage.py makemigrations --check --dry-run
python scripts/compile_messages.py
python manage.py import_catalog docs/catalog-example.json
python manage.py import_catalog docs/catalog-example.json --apply
python manage.py purge_rate_windows
python manage.py createsuperuser
```

L’import sans `--apply` ne sauvegarde rien ; avec `--apply`, toutes les lignes sont importées seulement si elles sont toutes valides. Un import est toujours un brouillon. Définir des identifiants `series` et des versions explicites pour éviter les doublons. Les contraintes rejettent une version existante.

Le compilateur portable accepte les catalogues simples fournis ; pour des traductions à entrées plurielles, utiliser `django-admin compilemessages` avec GNU gettext. Les pluriels natifs de Django sont déjà disponibles. Les contenus cliniques restent dans la base, séparés de l’interface.

## Documentation

- [Conception, permissions, données et backlog](docs/CONCEPTION.md)
- [Recette et vérifications exécutées](docs/RECETTE.md)
- [Exploitation et préparation de production](docs/EXPLOITATION.md)

Versions vérifiées : [Django 5.2 LTS, correctif 5.2.18](https://www.djangoproject.com/download/), [compatibilité Python](https://docs.djangoproject.com/en/5.2/faq/install/). Dépendances obtenues depuis PyPI, empreintes vérifiées avant installation. Licence MIT du code et des illustrations originales ; licences des dépendances distinctes.

La police Tajawal est distribuée sous SIL OFL 1.1 (licence incluse dans `static/fonts/tajawal/OFL.txt`). Voir [la finition arabe](docs/FINITION_ARABE.md).

## Livraison fonctionnelle et catalogue à valider

Le choix confirmé par le commanditaire est de préparer les contenus pour validation. Le catalogue comprend 60 brouillons (20 français, 20 anglais, 20 arabe algérien provisoire), 98 pictogrammes originaux et des consignes dans les trois langues. Les copies de démonstration sont explicitement non validées ; elles ne peuvent pas être attribuées hors mode démonstration. Ces propositions lexicales ne constituent pas encore un catalogue clinique de paires minimales. Les modèles audio, transcriptions, contrastes phonémiques, pertinence des images et portée dialectale restent à compléter/revoir par les professionnels.

L’espace éditorial permet de créer/modifier un brouillon, importer des illustrations et modèles vocaux adultes autorisés, soumettre aux relectures clinique et linguistique, publier, retirer et créer une nouvelle version. Les droits sont attribués par variété. La publication réelle exige les éléments obligatoires et deux relectures favorables sur la version exacte.

Les nouveaux parcours comprennent un exercice guidé en trois étapes, la modification et réactivation d’un profil, le transfert du responsable, le remplacement d’un programme en conservant l’historique, les décisions sur demandes d’effacement, les paramètres de conservation du cabinet, la facturation manuelle sous permission dédiée et l’authentification TOTP avec codes de récupération. La MFA est obligatoire pour les professionnels en configuration réelle, facultative pour les comptes fictifs.

Vérifications exécutées : 30 tests initiaux sur SQLite ; 7 tests complémentaires sur SQLite ; suite complète de 37 tests sur PostgreSQL 17.11, résultat OK. La mise en production, les emails SMTP, la revue indépendante et la validation clinique des exercices restent à organiser. Cette livraison locale n’est pas une certification réglementaire ou clinique.

Précision PostgreSQL : les 37 tests ont produit OK, mais la commande a fini avec un code de sortie 1 lors de la suppression de la base de test (signal de checkpoint refusé par l’environnement Windows). La recette PostgreSQL n’est donc pas entièrement clôturée. Aucun test de restauration complète n’est revendiqué.


## Qualification antérieure à la révision du 9 octobre, 21 h 45

# Qualification commerciale de Nehdrou

9 octobre 2026 — décision actuelle : **vente clinique non qualifiée**.

Cette décision porte sur la version locale livrée. Un bon résultat de tests ne constitue ni une validation clinique, ni une recette visuelle, ni une autorisation de commercialisation. Les corrections ci-dessous sont effectivement présentes dans le code ; les validations externes ne sont pas simulées.

## Produit visé et direction de conception

Nehdrou relie un programme choisi par un orthophoniste à une pratique accompagnée en famille. Trois publics disposent d’actions distinctes : le praticien attribue et ajuste ; la famille pratique et rapporte ; l’équipe éditoriale prépare et relit les contenus.

La direction retenue conserve le logo fourni et le bleu-vert de la marque. Couleur d’action #126770, texte #193e47, fond #F5F8FA ; Tajawal locale pour l’arabe, police système pour le français et l’anglais. Un seul système de composants couvre les trois interfaces. Les boutons principaux ciblent au moins 44 px de hauteur. Le traitement de la langue parlée demeure distinct de la langue des menus et des consignes.

## Audit des sources et corrections livrées

| Constat vérifiable | Gravité | Correction livrée | Limite de preuve |
|---|---|---|---|
| Passage AR→FR incorrect sans cookie de langue préalable | Majeure | Résolution de la langue de l’URL avant redirection ; conservation des paramètres ; boutons directs | Les neuf combinaisons sont testées |
| Règles CSS empilées : hauteur 88 px contredite par minimum 126 px et marque minimum 110 px | Majeure | Une seule feuille product.css chargée ; anciens styles retirés du rendu | Dimensions réelles à confirmer dans le navigateur |
| Navigation dense, fonctions secondaires au même niveau que la pratique | Majeure | Navigation par rôle, icônes cohérentes, réglages regroupés, aide visible | Test utilisateurs nécessaire |
| Une activité pouvait être ouverte après archivage du profil | Majeure | Interdiction au lecteur et au service ; relecture des objets en base avant enregistrement | Tests d’archive et d’objet périmé réussis ; concurrence complète à tester |
| Statut d’un programme présent seulement dans l’objet chargé au début | Majeure | Verrouillage et relecture de l’activité/programme avant une tentative | PostgreSQL sous charge à qualifier |
| Manque de repères sur langues, audio, arrêt et interprétation des réponses | Majeure | Aide FR/EN/AR intégrée, préférences expliquées, statut audio visible | Compréhension auprès des familles non mesurée |
| Certains textes secondaires étaient trop clairs | Mineure | Palette textuelle renforcée ; six paires de couleurs calculées au-dessus de 4,5:1 | Pas un audit de tous les états ou des images |

Cet audit est fondé sur les sources, les pages HTML, les tests et la capture arabe desktop fournie par le commanditaire. Cette capture permet de constater la lisibilité insuffisante des petits textes ; elle ne constitue pas une recette de tous les écrans ni une capture de la révision suivante.

## Révision après la capture du commanditaire

La capture arabe révèle des textes secondaires et légendes trop petits par rapport au titre. Les règles correspondantes sont renforcées : Tajawal Medium pour les textes courants, corps arabe 18 px, légendes de l’accueil 16 px, titre moins dominant et mentions importantes agrandies. Le logo fourni est conservé.

L’accueil présente la cible 4–7 ans immédiatement et propose un exemple interactif sans compte sur /fr/try/, /en/try/ et /ar/try/. Trois étapes montrent les illustrations, un choix d’image puis le retour familial. Les exemples sont explicitement illustratifs, sans contraste phonologique ni audio clinique approuvés. Cette page ne lit ni n’écrit de dossier d’enfant ou de rapport ; elle n’accepte pas de commentaire libre et est inaccessible hors DEMO_MODE. Elle ne remplace pas un programme attribué.

Les sept nouveaux tests interdisent les requêtes SQL dans l’exemple public, vérifient les langues, les choix invalides, l’arrêt, la protection CSRF et le blocage en mode réel. La suite complète compte 54 tests réussis sur SQLite. Le serveur exécuté sur E: répond aux GET et POST protégés par CSRF dans les trois langues ; les synthèses sont affichées. Node accepte la syntaxe du lecteur modifié. Les clics JavaScript, le rendu de la révision et la recette mobile/clavier restent non vérifiés dans un navigateur.

La proposition de créer le navigateur local vierge « nehdrou-recette » a été présentée au commanditaire. Son retour sur la vendabilité ne vaut pas confirmation de cette création. Aucun navigateur BrowserAct n’est créé sans cet accord.

## Contraste du logo

Après le retour « le logo est trop sombre », le PNG transparent original est conservé intégralement. Son fond d’affichage devient #f8fcfc et son cadre passe à 108 × 72 px sur ordinateur, 96 × 64 px sur mobile. L’échantillon du tracé analysé passe de 2,06:1 à 6,54:1 de contraste ; il s’agit d’un calcul sur un point, sans certification. Les trois accueils servent la feuille de style logo-3 ; le fichier logo est identique à celui fourni. Voir LOGO_VISIBILITE.md et logo-contrast-check.json. La capture finale du navigateur demeure non obtenue.

## Critères avant une vente

| Domaine | État | Preuve ou action nécessaire pour clôturer |
|---|---|---|
| Comptes, accès par dossier, invitations, historique | Vérifié techniquement | 54 tests SQLite réussis ; recette de concurrence et revue indépendante restantes |
| Interface FR/EN/AR | Vérifié techniquement | 460 clés recensées, aucune traduction manquante ; relecture native et recette mobile restantes |
| Design et accessibilité | Partiellement qualifié | Contrastes principaux calculés, focus et structure sémantique implémentés ; captures desktop/mobile, clavier, zoom 200 %, lecteur d’écran, absence de débordement à confirmer |
| Exercice guidé et attribution | Vérifié techniquement | Parcours serveur testé ; trois étapes et cartes de sélection implémentées ; interaction JS réelle à valider dans le navigateur |
| Catalogue clinique | Bloquant | 60 propositions préparées, zéro catalogue clinique approuvé livré. Vérifier chaque paire, dialecte, image, consigne, population et transcription |
| Modèles audio | Bloquant | Produire des modèles adultes autorisés et relus ; documenter les droits ; tester lecture et disponibilité. Aucun enregistrement d’enfant |
| Utilisabilité | Non évalué | Faire réaliser sans aide attribution/invitation/pratique/arrêt/relecture à des praticiens et familles ; noter erreurs et incompréhensions ; aucune erreur critique non résolue |
| Mise en production | Bloquant | Hébergement réel, HTTPS, secrets, médias protégés, SMTP, vérification d’identité/courriel, exploitation de la MFA et supervision |
| Sauvegarde/restauration | Bloquant | Restauration PostgreSQL complète sur un environnement distinct, comptages et accès vérifiés. Le nettoyage de la base de test locale a échoué sous Windows ; aucune restauration complète revendiquée |
| Exploitation et support | Non qualifié | Responsable de support, procédure d’incident, suivi des versions, politique de conservation définie et parcours de demandes testés |
| Offre et conditions | Non définies | Identifier l’entité, le marché de lancement, le tarif, la devise, les conditions d’accès et les modalités de facturation. Aucun prix ou contrat inventé |

La facturation manuelle est un choix prévu dans le cadrage ; un paiement automatisé n’est pas indispensable à un pilote vendu sur facture, mais l’offre, les conditions et le traitement effectif des paiements doivent être définis.

## Parcours de recette à exécuter

1. À 1440 px, puis à 390 et 320 px, comprendre le bénéfice et le statut de démonstration dès l’accueil. Aucune promesse clinique indue ; aucune action importante hors écran.
2. Passer FR→EN→AR→FR sur accueil, bibliothèque filtrée, profil et programme. Conserver la page, les filtres et le contenu attribué. Contrôler RTL, Tajawal, nombres, focus et texte mixte.
3. Comme praticien, créer un profil fictif, choisir une variété et sélectionner des cartes. Refuser une attribution incompatible ; fournir fréquence et consignes ; retrouver le programme attribué.
4. Inviter une famille, suivre le lien dans une session distincte, vérifier l’adresse et le périmètre. Ne pas exposer un autre enfant ou cabinet. Tester expiration et révocation.
5. Comme famille, parcourir les trois étapes, sélectionner une image, enregistrer une participation. Rejouer le même envoi sans créer un doublon. Arrêter sans compter une erreur.
6. Comme praticien, consulter les retours et ajouter une observation. Vérifier que cette observation n’apparaît pas dans l’espace familial ni son export.
7. Archiver le profil ou clôturer le programme : préserver l’historique, interdire les nouvelles tentatives, afficher un état compréhensible.
8. Comme équipe éditoriale, compléter une fiche et deux médias, obtenir deux relectures sur la version exacte, publier puis retirer. Une modification invalide la validation ; une famille ne consulte pas les brouillons.
9. Activer la MFA, se reconnecter, tester un code de récupération unique, exporter les données autorisées, puis tester une demande d’effacement sur un profil exclusivement fictif.

Journal attendu pour chaque tâche : rôle, langue, largeur, navigateur, action, résultat attendu, résultat obtenu, capture, gravité, correction et nouvelle vérification. Les cas non exécutés restent marqués « non vérifié ».

## Décision et ordre de clôture

La démonstration technique peut être présentée comme travail en cours. Un pilote avec données réelles exige d’abord le catalogue de la variété retenue, les médias approuvés, le déploiement et les conditions d’exploitation. La vente ne reçoit un feu vert qu’après clôture documentée de tous les points bloquants et de toute anomalie critique/majeure du parcours.

Après accord du commanditaire, uv 0.12.24 et BrowserAct 1.4.2 ont été installés localement sur E:. Le protocole core 2.0.2 et le manuel avancé ont été chargés intégralement. Les outils, leur cache, leurs fichiers temporaires et leur état résident dans E:\LocalCoderWorkspace\Nehdrou\work. Aucun navigateur BrowserAct n’est encore créé : la création d’un navigateur Chrome indépendant demande une confirmation distincte selon le plugin. Aucun audit visuel BrowserAct n’est revendiqué à ce stade.

## Espace de travail sur E:

À la demande du commanditaire, le projet est copié dans E:\LocalCoderWorkspace\Nehdrou\outputs\nehdrou. L’environnement Django est dans E:\LocalCoderWorkspace\Nehdrou\work\venv ; les dépendances ont été réinstallées depuis requirements.lock avec vérification des empreintes. Le serveur local est exécuté depuis cette copie. La version sur C: est conservée et n’est plus le dossier actif. La base fictive et le mot de passe de démonstration sont conservés dans la copie locale, exclus de l’archive de livraison.

Le lanceur E:\LocalCoderWorkspace\Nehdrou\Demarrer-Nehdrou.cmd utilise l’environnement préparé. Si le serveur est déjà actif sur le port 8000, utiliser l’URL existante plutôt que lancer une seconde instance.

## Références de qualification

Les critères de contraste, clavier, focus, langues et états sont à vérifier selon les [WCAG 2.2 du W3C](https://www.w3.org/TR/WCAG22/). Les contrôles effectués ici ne constituent pas une déclaration de conformité WCAG.

La préparation du déploiement suit les domaines de la [checklist officielle Django 5.2](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/), notamment secrets, HTTPS, configuration de production, stockage, email et journalisation. Une configuration ne prouve pas un déploiement opérationnel.
