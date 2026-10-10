# Nehedrou — fonctions finalisées et limites

9 octobre 2026. Projet actif : E:\LocalCoderWorkspace\Nehdrou\outputs\nehdrou.

## Boucle praticien–famille

Le praticien responsable peut publier un retour daté pour les accompagnants autorisés, depuis le programme ou un rapport précis. Un texte publié reste dans l'historique ; une précision doit constituer un nouvel ajout. Aucun courriel de réception n'est simulé. Les observations professionnelles restent privées. Révocation, transfert, archivage et clôture sont contrôlés côté serveur ; les écritures relisent les droits sous verrou.

L'accueil familial montre le dernier retour et une action principale pour commencer ou reprendre le parcours. Le suivi récent ouvre maintenant le rapport correspondant. Le démarrage explicatif du tableau praticien est replié lorsque des profils existent.

## Historique utilisable

L'aperçu affiche les derniers rapports, parcours et retours. « Historique complet » ouvre une liste paginée de 20 entrées, filtrée par type, dates et état. Le tri combine date et identifiant pour conserver un ordre stable. Les anciens rapports ne disparaissent plus derrière une limite silencieuse. Un test retrouve 65 rapports sur quatre pages, même lorsqu'ils ont la même date.

Un accompagnant voit les rapports partagés du programme et ses propres parcours ; le praticien responsable voit les parcours du dossier. Un parcours personnel d'un autre accompagnant n'est pas exposé comme action de reprise.

## Arrêt du lecteur

L'arrêt dès la première étape efface les choix de réponse et conduit au rapport. La consigne d'échange avec l'enfant est alors masquée : une activité interrompue ne demande pas une tâche supplémentaire. Le libellé devient « Compte rendu des parents ». La reprise conserve la tâche et sa cible jusqu'à enregistrement ; un arrêt sans rapport ne crée aucun résultat.

## Médias éditoriaux

PNG/JPEG : format attendu, structure vérifiée et pixels décodés, maximum 6 000 pixels par côté et 16 millions de pixels. WAV : trames PCM complètes, canaux et fréquence contrôlés. MP3 : structure et propriétés MPEG contrôlées. Maximum 15 Mio et 0,05–60 secondes pour l'audio. La validation ne mesure ni la qualité phonétique ni la pertinence clinique ; elle n'est pas un décodage exhaustif MP3.

Les fichiers importés sont immuables, y compris un remplacement réutilisant leur nom. Métadonnées techniques et SHA-256 sont conservés. Un ancien média dépourvu de ces contrôles ne devient pas approuvé automatiquement : réimport requis. Les fichiers de test contiennent un silence PCM fictif, jamais présenté comme modèle clinique.

## Exports

JSON schéma 2 : identifiants programme, élément, parcours, tâche et rapport ; références réciproques cohérentes ; retours partagés inclus. Les références de tâches non autorisées sont nulles. Préchargement des relations pour que le nombre de requêtes ne croisse pas avec les parcours (comparaison testée entre 12 et 24). Les observations privées sont exportées uniquement au praticien responsable.

## Internationalisation et identité

609 messages par langue ; 574 clés d'interface contrôlées sans manque. Interface FR/EN/AR indépendante de la variété clinique et de la langue des consignes. Tajawal locale ; compteur isolé en sens gauche–droite ; en-tête mobile compact. Logo original sur surface claire. Nom public harmonisé « Nehedrou » ; dossiers et routes techniques conservés.

Des traductions complètes ne prouvent ni la compréhension native ni la validation d'un corpus algérien. Le texte saisi par le praticien reste son texte et n'est pas traduit automatiquement.

## Formulaires et CSRF

La recette réelle Chrome a reproduit une erreur invisible aux tests HTTP qui injectaient eux-mêmes l'en-tête Origin : la politique no-referrer sur les pages authentifiées amenait Chrome à émettre Origin: null pour les formulaires HTML. Politique corrigée en same-origin ; les chemins ne sont pas transmis aux sites externes. Token, cookies, contrôles d'origine, CSP et refus des origines null/externes restent actifs. Le partage et le changement de langue après connexion passent ensuite dans Chrome.

Références techniques : [MDN — Referrer-Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Referrer-Policy) et [Django 5.2 — CSRF](https://docs.djangoproject.com/en/5.2/ref/csrf/). Ce cas confirme pourquoi les tests serveur ne remplacent pas la recette navigateur.

## Vérification et usage

Les preuves détaillées figurent dans QUALIFICATION_COMMERCIALE.md, RECETTE_NAVIGATEUR.md et les journaux associés. Tous les scénarios utilisent des données fictives. Le produit permet une présentation fonctionnelle ; il ne contient pas de corpus ou d'audio clinique approuvé, ni une efficacité thérapeutique démontrée.
