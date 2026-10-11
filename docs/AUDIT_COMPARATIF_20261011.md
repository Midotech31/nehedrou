# Nehedrou — audit produit et comparaison, 11 octobre 2026

Objectif : permettre à l’orthophoniste de préparer une pratique à domicile, au parent de comprendre et accompagner les activités, puis au professionnel de discuter les retours. Périmètre actuel : module initial 4–7 ans ; démonstration fictive FR/EN/AR, arabe standard et darja algérienne distincts. Audit du dépôt et du site Render à partir du commit `4cf9402`. Aucun compte réel ni dossier réel utilisé.

## Constats vérifiés avant les changements

1. La bibliothèque présente 111 activités actuelles : 19 FR, 17 EN, 42 arabe standard et 33 darja. Ses filtres et ses statuts sont opérationnels. Dans le créateur de programme, les fiches étaient seulement filtrables par variété et titre ; leurs objectifs, modalités et guides n’étaient pas consultables sur place.
2. Les programmes, parcours ordonnés, reprises, invitations, retours, impressions et historiques existent. Le rythme était un texte libre, sans dates structurées ni prochaines dates visibles pour la famille.
3. Le bilan global distingue réponses aux tâches fermées et participation, mais ne détaille pas l’aide, les arrêts et les tentatives pour chaque activité. Défaut corrigé : calcul du total avant l’exclusion des activités réservées au suivi professionnel pour un accompagnant.
4. La langue des menus et la langue choisie pour les consignes sont indépendantes. Un programme en interface arabe peut donc présenter des guides français, et les notes libres du professionnel ne sont pas traduites. Cette distinction était annoncée dans l’exercice mais insuffisamment visible sur le programme. Plusieurs titres d’onglets étaient génériques.
5. Le logo clair, Tajawal local, RTL, crédit exact, séparation des observations privées et des retours familiaux, droits par dossier et versionnement sont présents. Le README indiquait encore 37 activités actives.
6. Le CMS proposait une création originale, mais via un formulaire mêlant champs courants et JSON technique ; les trois langues de consignes étaient imposées au brouillon. Une fiche sans illustration ne montrait pas ses mots dans l’aperçu.
7. Le site gratuit utilise une base éphémère : les données fictives peuvent disparaître au redémarrage. Il ne constitue pas un hébergement clinique durable. Aucun audio natif approuvé n’est livré. L’aide vocale optionnelle de l’appareil concerne seulement certaines démonstrations lexicales en arabe standard et dépend des voix disponibles ; elle ne remplace pas un modèle natif approuvé.

Captures contemporaines : bibliothèque, tableau professionnel, programme, préparation de programme et accueil, enregistrées et inspectées pendant cet audit. Les preuves détaillées et les essais après correction sont fournis dans la livraison, hors du dépôt. Les captures concernent exclusivement les comptes fictifs.

## Comparaison sur des pages officielles

Pages consultées le 11 octobre 2026. Il s’agit de fonctions annoncées par les éditeurs, et non d’une mesure indépendante d’efficacité. Aucune souscription ni extraction de leurs contenus thérapeutiques effectuée. Prix non comparés : plateformes, populations et offres différentes. Aucune couverture spécifique de la darja algérienne ne peut être déduite d’une interface en arabe.

| Produit et segment | Fonctions documentées | Enseignement pour Nehedrou |
|---|---|---|
| [Articulation Station Hive](https://www.littlebeespeech.com/articulation-station-hive) — exercices d’articulation, appareils Apple | Progression de sons jusqu’aux conversations, choix de mots, enregistrement et écoute, cotation et rapports | Faciliter le choix professionnel et contextualiser les supports ; une progression clinique doit être choisie et évaluée par un professionnel. Pas de copie des contenus ni de cotation automatique ajoutée. |
| [Speech Blubs Pro](https://speechblubs.pro/) — outil professionnel lié à une application familiale | Construction d’activités, filtres phonétiques et thématiques, assignation à domicile, suivi annoncé | Réduire le temps de recherche pendant la préparation. Nehedrou réutilise ses métadonnées fiables : type, thème, mode de réponse, mots et contraste ; pas de filtres phonémiques reposant sur des transcriptions non qualifiées. |
| [Happyneuron](https://www.happyneuron.com/solutions/logiciels/) — plateforme francophone plus large | Nombreux outils d’évaluation/intervention ; exercices personnalisés à domicile et suivi depuis l’interface professionnelle | Renforcer le lien entre assignation et préparation du prochain rendez-vous ; ce périmètre dépasse le module initial de Nehedrou. Ses déclarations de validation ne valident pas Nehedrou. |
| [EaseTalk](https://www.easetalk.com/) — pratique entre rendez-vous, accès encore en pilote annoncé | Assignation par le thérapeute, pratique guidée ; seul le statut de réalisation choisi par la personne est partagé | La clarté du parcours et la maîtrise humaine des décisions importent davantage qu’un score prétendant mesurer la parole. Ses conversations avec IA ne sont pas un prérequis adapté à notre module enfant-parent. |
| [Galsah / جلسة](https://app.galsah.com/) — service arabophone de séances avec professionnels | Présentation de séances à distance et de comptes rendus | Alternative humaine adjacente, pas un catalogue équivalent ni une preuve de couverture de la darja. Nehedrou conserve l’accompagnement par un orthophoniste. |

## Améliorations réalisées

| Manque | Résultat logiciel | Limite conservée |
|---|---|---|
| Sélection laborieuse | Filtres par type, thème et mode ; recherche des mots, sens et contrastes normalisée pour l’arabe ; guides sur place ; ordre et sélection conservés lors d’un filtre | Changer de variété retire la sélection incompatible ; aucune activité non publiée ou réservée n’est offerte |
| Rythme peu concret | Dates de début/fin, jours convenus et minutes facultatives ; aperçu avant assignation ; prochaines dates visibles ; export `.ics` des 28 prochains jours | Aucun rythme ni durée imposé, pas d’envoi de notification ; export générique sans enfant ni notes ; fermer/archiver termine les dates à venir |
| Bilan trop global | Participation, aide/difficulté, arrêts, réponses fermées et dernier retour par activité ; exclusion des contenus réservés des totaux familiaux | Choix libres et observations non notés ; ces résultats ne mesurent pas la prononciation |
| Consignes et navigation ambiguës | Langue des consignes affichée sur le programme et l’impression, lien vers préférences, liste courte de préparation pour le parent, titres d’onglets précis | Notes personnelles non traduites automatiquement ; liste pratique distincte d’une formation professionnelle validée |
| Création éditoriale peu accessible | Éditeur guidé depuis une fiche vide ; instructions progressivement en FR/EN/AR, guides structurés, sources avec portée, mots/sens/segments/cibles, sélecteurs de médias ; aperçu des mots même sans illustration ; éditeur JSON avancé conservé | Un guide commencé doit être complet dans sa langue ; contrôles structurels des paires minimales conservés ; brouillons et relectures distincts |
| Accès Pitou demandé | Compte de recette fictif avec parcours orthophoniste et édition des brouillons pour les quatre variétés ; mot de passe dans un fichier privé hors dépôt et archive | Aucun droit de publication, superutilisateur ou approbation clinique automatique ; comptes réels et droits révoqués préservés |
| Documentation divergente | Corpus actuel corrigé, état commercial explicite et audit sourcé | Pas de certification ajoutée par une modification de documentation |

## Fondement scientifique et limites de l’inférence

L’[ASHA — troubles des sons de la parole](https://www.asha.org/practice-portal/clinical-topics/articulation-and-phonology/) décrit la sélection individualisée des objectifs et les approches contrastives. Les paires minimales doivent différer par un seul phonème et être pertinentes pour le profil et la communauté linguistique. Les activités lexicales, de demande, de routine ou de récit de Nehedrou ne sont pas toutes des exercices de paires minimales. Cette référence justifie la prudence des critères et des consignes ; elle ne prouve pas l’efficacité de l’application, d’une dose de pratique ou de notre corpus.

Les catégories de filtre décrivent des fiches, pas des diagnostics. Le calendrier matérialise une décision humaine ; les minutes n’entraînent ni timer obligatoire ni jugement d’adhésion. Les rapports servent à une discussion et les modèles vocaux de l’appareil ne sont jamais présentés comme des modèles cliniques natifs.

## Conditions encore nécessaires avant vente clinique

| Priorité | Travail restant et critère d’acceptation |
|---|---|
| Bloquant contenu | Relectures humaines indépendantes, cliniques et linguistiques, pour chaque version/variété ; familiarité locale et illustrations vérifiées ; droits et disponibilité enregistrés ; aucune approbation générée automatiquement |
| Bloquant audio | Enregistrements natifs consentis et licenciés, contrôle de chaque mot, qualité et prononciation dans la variété ; les 148 emplacements des nouvelles fiches restent vides |
| Bloquant exploitation | Base durable PostgreSQL, hébergement choisi pour l’usage prévu, MFA hors démo, SMTP, sauvegarde et restauration testée, surveillance et procédure d’incident ; ne pas saisir de dossiers réels sur la démo gratuite |
| Bloquant qualification | Responsables qualifiés, protocoles approuvés, documentation des usages/limites, formation accompagnants, essai terrain auprès de familles et professionnels, décision de mise en service et obligations applicables documentées |
| Commercial | Offre, facturation, assistance et conditions approuvées par le porteur du projet ; la facturation manuelle existante n’est pas un abonnement en ligne vendu |

**Conclusion** : version logicielle utilisable pour des essais fictifs et renforcée sur les parcours quotidiens. Pas de feu vert pour vendre un traitement validé ou utiliser cette démo avec des dossiers réels. Le module d’approbation et les garde-fous existants restent actifs. Les preuves de tests et de publication doivent être lues avec leur portée ; elles ne remplacent pas une évaluation clinique ou un audit complet d’accessibilité.
