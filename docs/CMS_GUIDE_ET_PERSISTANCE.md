# CMS guidé et conservation de la démonstration — 11 octobre 2026

Pitou peut créer une activité originale en quatre étapes : identité et variété parlée, mots et médias, consignes et guides, population/précautions/sources. Les structures proposées remplissent seulement les champs de guide vides ; elles ne fabriquent ni mots, ni transcription, ni source, ni approbation. Les champs restent éditables. Les consignes de la variété travaillée et celles de l'interface sont deux choses distinctes.

Une copie de travail privée est enregistrée après une modification. Son état est visible : en attente, en cours, enregistré ou à réessayer. Une saisie incomplète se récupère depuis l'espace éditorial. Trente copies actives sont autorisées par auteur ; mettre une copie de côté est réversible et ne supprime pas une activité. Les numéros de révision et l'empreinte du brouillon empêchent une autosauvegarde ancienne de remplacer une saisie récente. Ces protections ne certifient pas l'idempotence de toute soumission de création manuelle.

Le tableau de complétude recense les mots, sens, guides, langues, illustrations, enregistrements, transcriptions, sources et droits. Il indique la présence technique des éléments, jamais leur qualité clinique. Le paquet ZIP de relecture fournit les versions et leurs empreintes, une feuille de décisions et `recording_prompts.csv`. Ce dernier prépare chaque côté de l'activité avec mot, sens proposé, transcription proposée et variété ; les références du locuteur adulte, de la région, du consentement et les décisions restent à remplir. Aucune feuille importée ne publie ni n'approuve un contenu. Un locuteur natif et les relecteurs doivent confirmer les propositions, particulièrement en darja.

Le téléversement d'images et de WAV/MP3 accepte les mêmes fichiers validés qu'avant, avec une description de droits en langage courant et un aperçu. L'audio silencieux de recette est un fichier informatique fictif, sans modèle de parole ; aucun audio clinique natif n'a été inventé. La bibliothèque conserve ses 111 propositions originales courantes : 19 françaises, 17 anglaises, 33 en darja et 42 en arabe standard. Les copies de recette identifiées fictives sont distinctes de ce corpus. Les références documentées soutiennent les approches proposées, pas l'efficacité de Nehedrou. Voir [les recommandations ASHA](https://www.asha.org/practice-portal/clinical-topics/articulation-and-phonology/) et [les recommandations multilingues](https://www.asha.org/practice-portal/professional-issues/multilingual-service-delivery/).

## Retrouver la version à relire — 1 novembre 2026

L’espace éditorial et le tableau de préparation affichent par défaut la dernière version de chaque série. Le filtre « Toutes les versions (historique) » donne accès aux versions antérieures. Une ancienne fiche comporte un avertissement et un lien vers la dernière version; ses décisions de revue restent attachées uniquement à son empreinte. Une nouvelle version en brouillon n’est pas remplacée dans la liste par une ancienne version quand on filtre sur un autre état ou un autre type d’activité.

Le filtre de contenu permet de choisir les activités destinées à la revue professionnelle ou les exemples de démonstration. Les filtres restent appliqués lors de la pagination et du téléchargement : le ZIP contient l’ensemble des résultats correspondant à la sélection, sur toutes ses pages. Un lien vers une version précise conserve cette version historique. `review.csv` inclut `series_uuid`; les fichiers JSON incluent `series`, le numéro de version et l’empreinte CMS. Comparer ces informations avant de reporter une revue provenant d’un paquet source : un même identifiant de série ne prouve pas que les deux versions ou leurs textes sont identiques.

## Hébergement gratuit autorisé

Le projet Neon séparé « Nehedrou Demo », Francfort, utilise PostgreSQL 17 et un bucket S3 privé. Les autres projets sont exclus de cette opération. Les identifiants restent dans les variables privées de Render et dans un fichier privé hors dépôt. Le stockage est authentifié, les URL signées sont courtes, les lectures applicatives restent soumises aux permissions existantes. Les fichiers sont immuables ; aucun lien public permanent n'est créé.

Le budget est de 0 EUR : aucun passage payant n'est autorisé. Les limites de [l'offre gratuite Neon](https://neon.com/pricing) s'appliquent ; un quota atteint peut suspendre le service. [Render gratuit](https://render.com/docs/free) conserve sa veille et ses limites de disponibilité. Un stockage persistant ne constitue pas une offre de production avec SLA ou une qualification pour les données de santé.

Configurer `POSTGRES_HOST` avec l'hôte pooler pour le serveur et `POSTGRES_MIGRATION_HOST` avec l'hôte direct pour les migrations et sauvegardes ; TLS est requis. `DEMO_MODE=1`, `DEMO_EPHEMERAL=0`, `DEMO_SEED_ON_START=0` pour une base déjà initialisée. La désactivation du réensemencement conserve les objets fictifs ajoutés et évite de rejouer les initialisations à chaque démarrage. Ne pas mettre ces drapeaux sur une base vide : initialiser les comptes fictifs séparément avec leurs secrets privés. Le statut durable déclaré est une configuration ; seules les recettes de redémarrage et de restauration en prouvent le comportement dans le périmètre testé.

La base SQLite temporaire précédente ne possède pas de voie d'export intégral disponible sur le service gratuit. La nouvelle base reprend les douze comptes fictifs connus avec les mêmes mots de passe vérifiés et les données de démonstration standard ; ce n'est pas une migration exhaustive de l'ancien état temporaire. Les modifications anciennes non exportées ne sont pas garanties. Aucun dossier réel ne doit être saisi dans cette démonstration.

## Sauvegarde et restauration opérateur

Les commandes `backup_nehedrou` et `restore_nehedrou` produisent une archive Fernet authentifiée de la base et des fichiers privés. La clé `NEHEDROU_BACKUP_KEY` est fournie dans l'environnement privé, conservée séparément et jamais dans une commande, un journal ou le dépôt. Arrêter les écritures et les modifications de fichiers avant `--quiescent` ; cette option est une déclaration opérateur, pas un verrou global. Installer les outils clients de la version PostgreSQL correspondante et définir `NEHEDROU_PG_BIN` si nécessaire. La limite pilote est 64 MiB non compressés et 10000 entrées : prévoir une sauvegarde d'infrastructure en flux au-delà.

Exemples sans secret, chemins privés absolus à adapter :

```text
python manage.py backup_nehedrou --quiescent --destination E:/SauvegardesPrivees/nehedrou-20261011.nehedrou
python manage.py restore_nehedrou --source E:/SauvegardesPrivees/nehedrou-20261011.nehedrou --verify-only
python manage.py restore_nehedrou --source E:/SauvegardesPrivees/nehedrou-20261011.nehedrou --postgres-database nehedrou_restoration_test --media-destination E:/RestaurationsPrivees/medias-test
```

La cible PostgreSQL doit exister, être vide et être différente de la source et de la base active. Pour SQLite, utiliser `--sqlite-destination` avec un fichier neuf. La commande n'écrase aucun environnement actif. Les fichiers sont restaurés dans un répertoire local neuf ; leur réimportation vers un bucket distant demeure une opération séparée. La restauration base/fichiers n'est pas une transaction commune en cas de panne disque. La sauvegarde hors hébergement et la restauration isolée sont testées avec des données fictives ; leur planification récurrente n'est pas installée.

## Portée des preuves

La suite complète PostgreSQL passe 316 tests ; 31 tests ciblés passent ensuite, dont deux nouveaux cas (kit audio et démarrage sans réensemencement), soit 318 tests distincts couverts. Deux cas exercent réellement les verrous de copie de travail PostgreSQL. Les sauvegardes filesystem et S3, le refus d'une cible active et les archives corrompues sont couverts. La restauration réelle depuis Neon et son bucket privé compare les 53 tables et trois fichiers présents lors de la capture : comptages et octets identiques. Les fichiers ajoutés ensuite par les parcours HTTP ne font pas partie de cette capture historique.

Les recettes HTTPS et les captures de la publication sont livrées séparément et doivent être datées de cette publication. Elles ne certifient pas tous les navigateurs, une conformité intégrale WCAG, une charge de production, une compréhension native ou une efficacité thérapeutique.

La qualité fonctionnelle pilote peut être appréciée séparément de la préparation à une vente clinique. Restent nécessaires : relectures cliniques et linguistiques des versions exactes, enregistrements adultes natifs et droits, essais avec utilisateurs, courriels réellement reçus, exploitation et offre commerciale qualifiées. L'application continue à rendre ces limites visibles.


## Vérifications et facturation manuelle — 1 novembre 2026

Un vérificateur consulte la déclaration actuelle du relecteur avant de consigner son contrôle indépendant. Si son contenu change entre l’ouverture du formulaire et l’enregistrement, la décision est refusée : recharger la déclaration, la relire, puis enregistrer la décision. Modifier une déclaration ne rétablit jamais un ancien contrôle positif après un rejet. Le dernier contrôle historique et le statut effectif restent distincts.

Le gestionnaire disposant de `core.manage_entitlements` ouvre le cabinet dans la facturation. La consultation seule ne crée aucun droit d’accès. L’enregistrement explicite du formulaire crée ou met à jour les droits et inscrit l’opération dans l’audit; un montant négatif est refusé. La devise comporte exactement trois lettres latines majuscules, par exemple DZD. Ce contrôle de forme ne vérifie pas l’existence d’une devise ISO et ne convertit aucun montant.

Chaque facture enregistrée possède désormais une fiche accessible depuis sa liste. Une facture émise peut être marquée payée ou annulée, avec une référence de paiement ou d’annulation. Le numéro, le cabinet, le montant, la devise et la date d’enregistrement sont conservés; un statut final ne peut pas être remplacé ou rejoué. Le paiement est seulement consigné : aucune somme n’est débitée et les droits d’accès se gèrent séparément. Cette fiche interne ne constitue pas une attestation de conformité fiscale; l’entité vendeuse et le format des documents clients restent à définir avant lancement.

## Inviter les relecteurs sans service email — 1 novembre 2026

Le gestionnaire ouvre **Accès éditoriaux** (`/fr/operations/editorial-access/`, ou le même parcours sous `/en/` et `/ar/`). Il doit posséder la permission de gestion des accès ; un simple compte éditeur ou relecteur ne peut pas émettre ces invitations.

1. Saisir l'adresse du destinataire identifié, la variété parlée et un seul rôle : édition de brouillons, relecture clinique ou relecture linguistique.
2. Choisir **Lien à remettre personnellement**. Ce choix est présélectionné lorsque l'envoi par email est connu comme indisponible. Le choix du mode repose uniquement sur la configuration locale, sans test réseau ni envoi.
3. Créer l'invitation et copier le lien depuis son champ en lecture seule avant de quitter la page. Le porteur le remet personnellement au destinataire après vérification de son identité. Aucun courriel n'est envoyé par ce mode ; le lien ne prouve pas la propriété de l'adresse email.
4. Le destinataire ouvre le lien sous sept jours. Un compte existant doit se connecter avec l'adresse invitée ; pour un nouveau compte, cette adresse est fixée. Seule l'acceptation crée ou complète la capacité éditoriale pour cette variété. L'invitation n'ajoute ni accès aux dossiers, ni appartenance à un cabinet, ni publication. Un compte désactivé ne peut pas être réactivé par ce parcours.

Le lien brut est affiché uniquement dans la première réponse privée à la création. Il n'est pas récupérable depuis la liste, un GET ou un rejeu du formulaire ; seule son empreinte est conservée. Réenvoyer exactement le même acte garde l'invitation existante sans générer de nouveau token. Si le lien est perdu, créer explicitement une autre invitation : cela révoque les anciens liens non utilisés du même email, rôle et variété. Les autres invitations restent inchangées. Une invitation révoquée, expirée ou déjà acceptée n'est pas réactivée par un rejeu.

L'accès d'un publicateur déjà présent pour la même variété n'est pas modifié ; il doit être examiné directement. L'acceptation n'atteste pas les compétences du relecteur : sa déclaration, sa vérification indépendante et les revues du contenu exact restent nécessaires. Aucune activité n'est approuvée ou publiée par cette remise de lien.

Ce parcours concerne les invitations éditoriales. Il ne configure pas les courriels, la récupération de mot de passe ni les invitations de familles ou de praticiens.