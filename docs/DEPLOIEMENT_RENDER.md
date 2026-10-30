> Historique du déploiement du 11 octobre 2026. Pour la préparation actuelle du 30 octobre (PostgreSQL externe, stockage privé, supervision et sauvegardes), consulter [EXPLOITATION.md](EXPLOITATION.md). Les états et résultats ci-dessous restent ceux de leur date.

> Mise à jour du 11 octobre 2026 : la nouvelle publication utilise un projet Neon gratuit séparé et un stockage privé persistant. Les passages SQLite temporaire ci-dessous décrivent l'historique. Voir [CMS guidé et persistance](CMS_GUIDE_ET_PERSISTANCE.md) pour la configuration et les limites actuelles.

# Test en ligne sur Render

Publication du 10 octobre 2026. [Dépôt dédié Midotech31/nehedrou](https://github.com/Midotech31/nehedrou), rendu public avec l’accord du propriétaire pour permettre le déploiement. [Adresse de la démonstration](https://nehedrou-demo.onrender.com). Les bases locales, mots de passe, téléversements et environnements ne sont pas versionnés.

Le service `nehedrou-demo` utilise le plan gratuit de Render, avec Gunicorn, WhiteNoise, `DJANGO_DEBUG=0`, cookies sécurisés et origine HTTPS. `render.yaml` décrit la configuration reproductible. La création directe par le connecteur utilise les mêmes commandes : `python scripts/render_build.py` et `python scripts/render_start.py`.

La base PostgreSQL gratuite de l'espace est déjà utilisée par un autre projet. Cette démonstration emploie donc une **base SQLite temporaire indépendante**, autorisée seulement lorsque `DEMO_MODE=1` et `DEMO_EPHEMERAL=1`. Le mode clinique continue à exiger PostgreSQL. Les modifications et les fichiers téléversés peuvent disparaître à un redémarrage ou à un déploiement. Aucun dossier réel ne doit être saisi. Les comptes fictifs sont initialisés au démarrage avec un mot de passe aléatoire conservé uniquement dans les variables Render et dans le document d'accès local privé.

Les clés `DJANGO_SECRET_KEY` et `DEMO_PASSWORD` ne doivent jamais être ajoutées au dépôt. L'origine et l'hôte autorisé viennent du nom de domaine attribué par Render ; le proxy HTTPS n'est reconnu automatiquement que dans cet environnement. `/healthz/` vérifie une lecture de la base et retourne seulement un état, sans configuration ni identité. Les traductions et les fichiers statiques sont compilés pendant la construction.

Le plan gratuit peut se mettre en veille : la première ouverture peut être lente. Les courriels sont simulés dans les journaux privés, sans promesse d'envoi ou de réception. Ce déploiement ne valide ni un hébergement de données de santé ni l'efficacité clinique. Voir [les limites officielles Render](https://render.com/docs/free) et [le guide Django officiel](https://render.com/docs/deploy-django).

Les contrôles locaux et, après déploiement, les vérifications HTTPS du site sont consignés dans les preuves de livraison. Un statut de construction réussi ne remplace pas une connexion et une soumission réelles sur le site publié.

## Vérifications historiques de la première publication

108 tests découverts : 102 réussis et six ignorés, réservés à PostgreSQL ; 81,579 s. Trente contrôles isolés supplémentaires passent avec DEBUG désactivé : pages publiques FR/EN/AR, avertissement temporaire, statiques avec manifest, logo original, connexion HTTPS, cookies sécurisés, changement de langue, refus des origines externe/nulle et déconnexion. 575 clés d’interface, aucune manquante. Ces preuves locales ne sont pas une vérification du site distant.

Le Blueprint demande de saisir une clé aléatoire privée d’au moins 50 caractères ; son générateur court n’est pas utilisé. Le déploiement direct fournit une clé dédiée de 86 caractères.

## Première version publiée — historique

Le déploiement `dep-db5ajdh42hec7389hdm0` du service `srv-db5afol9fdbs73c62t10` est **live** depuis le 10 octobre 2026 à 21:12:10 UTC. Le code exécuté correspond au commit `cfc3639d2fa013c7a3c8089e171f13df3e70b1ef`. Le script de démarrage ajoute explicitement la racine du projet au chemin d’import Python ; sept tests de déploiement passent après correction, dont le lancement réel du script depuis un dossier extérieur avec migrations et initialisation fictive. Seule la remise finale à Gunicorn est remplacée dans ce test Windows ; Gunicorn a démarré réellement sur Linux chez Render.

La recette HTTPS distante réussit **89 contrôles** : FR/EN/AR, statiques et empreinte du logo, santé de la base, redirection HTTPS, cookies, CSRF, connexions des quatre comptes fictifs, reprises, démarrages et rapports sans doublons, clôture sans rapport inventé, retours familiaux et observations privées séparés, historiques, exports, impression et refus de lecture/écriture entre cabinets. Les doubles soumissions testées sont séquentielles : cette recette ne certifie pas la concurrence SQLite.

La recette dans le navigateur intégré réussit **18 contrôles** sur le site distant, avec JavaScript réellement exécuté : arabe RTL et Tajawal à 360 × 800, changements de langue, validation sans réponse, choix conservé au clavier, arrêt qui efface le choix, connexion familiale, pause/reprise, cible conservée après rechargement, enregistrement du rapport et changement de langue conservant son identifiant. Les captures et preuves JSON sont livrées séparément. Aucun avertissement ni erreur de console n’a été observé durant ces parcours ; aucun journal Render de niveau erreur n’a été relevé depuis le passage live jusqu’à 21:20:42 UTC. Ces observations ne remplacent pas une recette multi-navigateurs, des essais utilisateurs ou une validation clinique.

Le service a été créé directement : son champ de sonde HTTP est vide. `/healthz/` a bien répondu en HTTPS avec une lecture de base réussie, dans la recette distante ; `render.yaml` prévoit cette route pour une création par Blueprint.

## Quatre améliorations publiées et vérifiées

Le déploiement `dep-db5bav7lk1mc739d8djg` est **live** depuis le 10 octobre 2026 à 22:02:50 UTC. Le code exécuté correspond au commit `2acbb16c18726fb8831634dcb699e32bb50b4d9e`. La mise à jour de l’environnement a ajouté sept mots de passe de rôle distincts sans remplacer les clés existantes ; aucune valeur de secret ne figure dans ce document.

La recette réelle HTTPS passe **101 contrôles** avec les quatre comptes historiques : langues, nouveau logo et son empreinte, crédit, contenus publics adaptés, santé, protections HTTPS/CSRF, parcours, rapports, exports et isolation. La recette des sept nouveaux rôles passe **170 contrôles**, zéro échec et zéro cas non évalué : connexions, périmètres de dossiers, lectures et écritures interdites, relectures et édition. Deux avis demandant des modifications et un clone édité sont exclusivement fictifs ; aucun contenu clinique n’a été approuvé ou publié par la recette. Les comptes et leurs mots de passe historiques sont préservés.

La recette dans le navigateur intégré passe **24 contrôles** : neuf affichages FR/EN/AR à 320, 768 et 1280 pixels, démonstrations interactives adaptées, guides, connexion du nouvel accompagnant, consignes arabes, pratique attribuée en darja, retour enregistré, rechargement et changements FR/EN conservant le même rapport. Aucune erreur de console n’a été observée durant ces vues ; la requête de journaux Render de niveau erreur entre le passage live et 22:08:03 UTC n’a retourné aucun événement. Ces contrôles ne certifient ni tous les navigateurs, ni une conformité intégrale d’accessibilité, ni une efficacité clinique.

Les suites locales passent : **137 tests sous PostgreSQL**, zéro ignoré ; **131 réussis sur 137 sous SQLite**, avec six cas réservés à PostgreSQL ignorés. Un contrôle PostgreSQL ciblé supplémentaire prouve l’attente du verrou d’activité puis le refus d’une attribution après retrait. Django, migrations, statiques et traductions passent : 635 messages par langue, 599 clés d’interface, aucun manque.

Les preuves actuelles sont `VERIFICATION_RENDER_DISTANTE.json`, `RECETTE_ROLES_RENDER.json`, `RECETTE_AMELIORATIONS_NAVIGATEUR.json` et `DEPLOIEMENT_AMELIORATIONS_ETAT.json`, remises hors du code. Le tableau privé `ACCES_ROLES_RENDER.md` contient les accès opérationnels et reste exclu du dépôt, des pages et de l’archive. Le corpus actif contient 37 propositions v2 et leurs copies fictives ; il attend toujours les relectures professionnelles et les modèles audio cliniques. Voir [les améliorations](AMELIORATIONS_URGENTES.md).

### Republier une modification

Le service clone l’URL publique du dépôt, sans connexion du fournisseur Git. Malgré le drapeau d’auto-déploiement exposé par l’API, aucun webhook Git n’est établi dans cette configuration. Après avoir vérifié, commité et poussé le code, ouvrir [le service Render](https://dashboard.render.com/web/srv-db5afol9fdbs73c62t10) et choisir **Manual Deploy → Deploy latest commit**, puis attendre `live` et recontrôler `/healthz/` et les parcours. C’est le fonctionnement documenté pour [les dépôts Git publics sans connexion](https://render.com/docs/deploys#automatic-deploys). Le redéploiement peut réinitialiser les données fictives temporaires.
