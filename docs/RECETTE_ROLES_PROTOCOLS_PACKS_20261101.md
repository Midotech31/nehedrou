# Recette des rôles, protocoles et packs — 1 novembre 2026

État de cette note au commit de préparation : **huit correctifs et recette locale vérifiés ; CI du commit final et publication à confirmer dans la PR et le bilan de livraison**.
La révision publiée servant de point de départ est `944c9c9`.
Les comptes, fiches et médias de recette sont fictifs. Cette note ne vaut ni validation clinique, ni conformité réglementaire, ni autorisation de vente.

## Corrections du lot

### 1. Conserver les médias déjà liés lors d'une édition collaborative de pack

Un autre éditeur autorisé pouvait ouvrir un candidat dont les médias avaient été téléversés par l'auteur initial, puis voir ces valeurs rejetées à l'enregistrement.
Le formulaire conserve désormais les médias déjà liés au candidat en plus des médias propres à l'éditeur.
Il ne permet pas de choisir un média tiers sans lien préalable ; le type image/audio reste contrôlé.
Le clonage garde les associations sans modifier le pack source.

Sources : [vue des candidats](../qualification/views.py) et [régressions de collaboration](../qualification/tests_candidate_media.py).

### 2. Refuser la création d'un pack sans droit d'édition

Un rôle de lecture/relecture ne doit pas recevoir un formulaire de création inutilisable.
L'ouverture et le POST de création exigent une variété effectivement éditable ; le refus reste HTTP 403 et ne crée aucun contenu.
Les formulaires de pack autorisés à l'éditeur restent accessibles ; les protocoles du professionnel auteur conservent leurs droits existants.

Sources : [vue des packs](../qualification/views.py) et [contrats par rôle FR/EN/AR](../qualification/tests_authoring_roles.py).

### 3. Rendre les valeurs des dates natives au format ISO

Les dates initiales typées de certains formulaires rendaient une valeur française comme `15/11/2026` dans un champ HTML `type=date`, au lieu de `2026-11-15`.
Le format d'affichage ISO est explicite pour la prochaine revue d'objectif, la revue de coaching et la date de vérification de compétence.
Les deux dates du filtre d'historique suivent aussi ce contrat lorsqu'une date initiale typée est fournie.
**Limite de ce dernier constat :** le parcours d'historique courant lie normalement les chaînes ISO du GET ; ce cas fonctionnait déjà avant la correction core.
Les parseurs, les dates enregistrées, les règles de plage et le caractère facultatif des champs ne changent pas.

Sources : [formulaires de suivi](../followup/forms.py), [formulaire de vérification](../qualification/forms.py), [filtres core](../core/forms.py), [tests de dates du suivi](../followup/tests_date_inputs.py) et [tests de l'historique](../core/tests_history_date_widgets.py).

### 4. Traduire la présentation des positions de protocole

Les positions reconnues sont affichées avec des libellés FR/EN/AR plutôt qu'avec leurs codes techniques seuls.
Le filtre de présentation ne réécrit ni position, ni protocole, ni instantané d'objectif, ni empreinte.
Un texte ancien inconnu reste affiché tel quel ; aucune équivalence clinique n'est inventée.

Sources : [filtre de présentation](../followup/templatetags/followup_labels.py) et [régressions des positions](../followup/tests_position_labels.py).

### 5. Fournir des pages 403/404 localisées et utilisables

Les refus et routes indisponibles disposent de pages FR/EN/AR avec liens de récupération vers l'accueil et, pour un compte connecté, sa vue d'ensemble.
Le statut HTTP d'origine est conservé. Les textes d'exception, chemins internes et contenus privés ne sont pas recopiés dans la page.
Une page d'erreur présentable ne donne aucun accès supplémentaire. Le lien de retour emploie un libellé d'accueil non ambigu.

Sources : [403](../templates/403.html), [404](../templates/404.html) et [tests d'erreur et de non-divulgation](../qualification/tests_error_pages.py).

### 6. Exiger un choix explicite pour une position ancienne non prise en charge

Un ancien code comme `first_consonant` n'appartient pas aux choix d'édition `initial/medial/final`.
Sans option vide, le sélecteur natif pouvait afficher sa première position et laisser croire qu'elle correspondait au contenu conservé.
L'édition et le clonage présentent maintenant un choix vide obligatoire ; un enregistrement sans choix explicite est refusé sans changer le protocole, son empreinte ou ses avis.
Les positions reconnues gardent leur présélection. Une nouvelle position et son contexte ne sont enregistrés qu'après une saisie valide explicite ; aucune équivalence automatique n'est ajoutée.

Sources : [formulaire du protocole](../followup/forms.py) et [régressions des positions anciennes](../followup/tests_legacy_position_forms.py).

### 7. Identifier les médias dans les listes de sélection

Les candidats de pack affichaient seulement `MediaAsset object (UUID)` ; les auteurs ne pouvaient pas identifier le fichier.
Les deux formulaires utilisent un libellé texte partagé : nom de fichier seul, identifiant court et statut de droits déjà traduit en FR/EN/AR, notamment « inconnu ».
Les séparateurs `/` et `\` sont traités pour retirer le préfixe de stockage ; le nom reste du texte échappé, même s'il contient du HTML malveillant.
Ce libellé ne lit aucun fichier, ne qualifie aucun média et ne change ni la sélection des UUID complets, ni les querysets de permission, ni les validations de droits.

Sources : [helper de libellé](../catalog/media_labels.py), [formulaire candidat](../qualification/forms.py), [wrapper du protocole](../followup/forms.py) et [tests des deux formulaires](../catalog/tests_media_labels.py).

### 8. Garder les longues descriptions de tâche dans la fenêtre mobile

À 390 px, un identifiant de tâche sans espaces débordait du protocole en FR/EN (largeur de document 398 px, largeur utile 375 px).
La description de protocole autorise maintenant la coupure des longues chaînes, sans modifier leur valeur ni la direction du texte.
La version du lien CSS est renouvelée pour les navigateurs déjà ouverts.
Après correction, la même page mesure 375/375 px en FR/EN/AR dans cette fenêtre de 390 px ; ceci ne représente pas un essai sur téléphone physique.

Sources : [description de protocole](../templates/followup/definition.html), [style](../static/product.css) et [version CSS](../templates/base.html).

## Contrôles isolés déjà obtenus

- Lot suivi/qualification : 139 tests, résultat OK, dont deux cas PostgreSQL ignorés sous SQLite.
- Lot dates core : cinq tests ciblés réussis, incluant trois nouveaux tests ; la régression de date initiale échouait en français avant correction.
- Lot libellés média : sept tests ciblés réussis, incluant quatre nouveaux tests et les trois régressions existantes de collaboration ; aucun ignoré.
- Intégration ciblée : 153 tests en 108,997 s, résultat OK, dont deux cas PostgreSQL ignorés ; `check`, cohérence des migrations et 1908 clés UI par langue sans manque. Le code Python et les catalogues n’ont pas changé pendant ce contrôle ; le HEAD a évolué de `7d100cb` à `913c9b4` uniquement sur le correctif CSS/template mobile. La CI du HEAD final reste requise.
- Ces lots ont des périmètres qui peuvent se chevaucher : **ne pas additionner leurs décomptes comme un total de cas distincts**.
- Ces résultats ne sont pas la CI finale de l'intégration et ne prouvent pas les parcours publiés.

## Fixture locale et séparation des preuves

Une base SQLite et un stockage local privés séparés ont préparé quatre packs, huit candidats et dix protocoles en brouillon ou soumis. La recette UI locale a ensuite créé un pack et un candidat, soumis ce pack, créé et édité sa version v2, conservé les médias déjà liés à un autre candidat, puis copié deux protocoles et enregistré leurs positions/contextes explicitement ; la copie de l’auteur de cabinet a été soumise.

Le contrôle final en lecture seule compte six packs, dix candidats et douze protocoles. Les parents v1 conservent leur position ancienne `first_consonant`, les copies portent les choix explicites, et les références image/audio sont conservées. Les sept tables de revues de packs/sondes, compétences/décisions, disponibilité, preuves et familiarité restent vides. Les métadonnées ciblées et les empreintes des quatre fichiers locaux n’ont pas changé pendant les tests d’intégration.
Les titres `RECETTE LOCALE FICTIVE` identifient ce jeu ; les images techniques et signaux sans parole sont non qualifiés et ne constituent pas des modèles thérapeutiques.
Aucune compétence humaine, preuve de familiarité, approbation de pack/protocole ou décision de disponibilité n'y est fabriquée.
Ce jeu local n'est pas un seed de Render/Neon et ne doit pas y être importé.
Les secrets de connexion et les chemins privés restent hors du dépôt et de cette note.

Les portes de publication et d'ouverture, les versions exactes, l'intégrité, les droits et la séparation des rôles restent applicables.
Voir [les rôles disponibles](ROLES_DEMONSTRATION.md) et [les conditions de lancement](CHECKLIST_LANCEMENT_ALGERIE_20261101.md).

## Recette publiée de référence avant ce lot

Sur `944c9c9`, les connexions des douze comptes fictifs ont été exercées. Onze espaces d’arrivée ont été observés en FR/EN/AR ; le relecteur clinique a été contrôlé sur les écrans de protocoles, et son retour d’arrivée dans la nouvelle matrice reste à terminer. Une interruption du navigateur a empêché l’export du tableau en mémoire ; les observations suivantes décrivent les parcours effectivement vus, sans prétendre à un journal exporté complet.

| Comptes de démonstration | Parcours observés, sans écriture de contenu publié |
|---|---|
| `responsable` | Fiches du cabinet, équipe ; fiche fictive Maya. |
| `orthophoniste` | Fiche Sami, protocoles ; équipe inaccessible. |
| `accompagnant` | Fiche Sami et programme familial ; qualification refusée. |
| `editeur` et `pitou` | Espace éditorial, création d’activité et protocoles selon les droits existants. |
| `relecteur_clinique` | Protocoles en brouillon/soumis et formulaire limité à la revue clinique. |
| `relecteur_linguistique` | Revue limitée à la dimension linguistique, sans action de publication. |
| `gestionnaire` | Facturation et remise d’invitations éditoriales ; fiche clinique étrangère inaccessible. |
| `praticien`, `famille`, `autre_praticien`, `editorial` | Espaces historiques ; famille limitée à Lina, refus de Sami au praticien étranger, revue combinée du compte éditorial historique. |

Les nouveaux packs de recette restent locaux ; la bibliothèque publiée de packs était vide. Aucune compétence, revue humaine, invitation, facture ni approbation n’a été créée dans Render/Neon. Les écritures locales ne doivent pas être présentées comme des parcours réels publiés.

## Vérifications finales à consigner avant livraison

| Étape | État de cette version de la note |
|---|---|
| Recette publiée des rôles en FR/EN/AR | Référence `944c9c9` décrite ci-dessus ; recontrôle des écrans modifiés et arrivée du relecteur clinique après publication encore à consigner. |
| Recette locale des packs et protocoles | Réussie sur intégration ; créations, copies, édition, soumissions, médias et séparation des formulaires clinique/linguistique. Aucun avis humain soumis. |
| Contrôle mobile, clavier et langues mixtes | Protocole de cabinet contrôlé à 390 px en FR/EN/AR, débordement corrigé, logo et crédit présents, Tajawal/RTL en arabe. Recette clavier/lecteur d’écran et appareils physiques non exhaustive. |
| CI de la révision finale | En attente : lien, SHA, tests exécutés/ignorés, traductions, migrations et démarrage. |
| Publication Render | En attente : déploiement exact, statut terminal et contrôle après mise en ligne. |
| Décision de lancement clinique payant | Non établie par ce lot : relectures, voix et droits réels, opérateur, offre et exploitation restent des conditions distinctes. |

Sur un environnement de test isolé, sans configuration ni données de production, les commandes de contrôle restent :

```text
python scripts/compile_messages.py
python scripts/check_translations.py
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

Ne remplacer un état « en attente » que par une preuve réellement obtenue dans le périmètre concerné.
