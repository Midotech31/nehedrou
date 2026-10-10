# Test en ligne sur Render

Publication du 10 octobre 2026. [Dépôt dédié Midotech31/nehedrou](https://github.com/Midotech31/nehedrou), rendu public avec l’accord du propriétaire pour permettre le déploiement. [Adresse de la démonstration](https://nehedrou-demo.onrender.com). Les bases locales, mots de passe, téléversements et environnements ne sont pas versionnés.

Le service `nehedrou-demo` utilise le plan gratuit de Render, avec Gunicorn, WhiteNoise, `DJANGO_DEBUG=0`, cookies sécurisés et origine HTTPS. `render.yaml` décrit la configuration reproductible. La création directe par le connecteur utilise les mêmes commandes : `python scripts/render_build.py` et `python scripts/render_start.py`.

La base PostgreSQL gratuite de l'espace est déjà utilisée par un autre projet. Cette démonstration emploie donc une **base SQLite temporaire indépendante**, autorisée seulement lorsque `DEMO_MODE=1` et `DEMO_EPHEMERAL=1`. Le mode clinique continue à exiger PostgreSQL. Les modifications et les fichiers téléversés peuvent disparaître à un redémarrage ou à un déploiement. Aucun dossier réel ne doit être saisi. Les comptes fictifs sont initialisés au démarrage avec un mot de passe aléatoire conservé uniquement dans les variables Render et dans le document d'accès local privé.

Les clés `DJANGO_SECRET_KEY` et `DEMO_PASSWORD` ne doivent jamais être ajoutées au dépôt. L'origine et l'hôte autorisé viennent du nom de domaine attribué par Render ; le proxy HTTPS n'est reconnu automatiquement que dans cet environnement. `/healthz/` vérifie une lecture de la base et retourne seulement un état, sans configuration ni identité. Les traductions et les fichiers statiques sont compilés pendant la construction.

Le plan gratuit peut se mettre en veille : la première ouverture peut être lente. Les courriels sont simulés dans les journaux privés, sans promesse d'envoi ou de réception. Ce déploiement ne valide ni un hébergement de données de santé ni l'efficacité clinique. Voir [les limites officielles Render](https://render.com/docs/free) et [le guide Django officiel](https://render.com/docs/deploy-django).

Les contrôles locaux et, après déploiement, les vérifications HTTPS du site sont consignés dans les preuves de livraison. Un statut de construction réussi ne remplace pas une connexion et une soumission réelles sur le site publié.

## Vérifications avant publication

108 tests découverts : 102 réussis et six ignorés, réservés à PostgreSQL ; 81,579 s. Trente contrôles isolés supplémentaires passent avec DEBUG désactivé : pages publiques FR/EN/AR, avertissement temporaire, statiques avec manifest, logo original, connexion HTTPS, cookies sécurisés, changement de langue, refus des origines externe/nulle et déconnexion. 575 clés d’interface, aucune manquante. Ces preuves locales ne sont pas une vérification du site distant.

Le Blueprint demande de saisir une clé aléatoire privée d’au moins 50 caractères ; son générateur court n’est pas utilisé. Le déploiement direct fournit une clé dédiée de 86 caractères.
