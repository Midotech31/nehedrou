# Nehedrou — qualification finale de la version 6

9 octobre 2026. **Version fonctionnelle pour une présentation avec données fictives ; vente clinique internationale non qualifiée.** Je ne recommanderais pas de vendre ce produit tel quel pour un usage thérapeutique. La qualité du logiciel et la validation de son contenu sont deux preuves différentes. L’objectif de 9,5/10 n'est pas artificiellement attribué.

## Résultat concret

Le projet actif sur E: intègre le parcours ordonné reprenable, les consignes personnalisées, l'arrêt précoce, les invitations, les droits par dossier, les relectures éditoriales, l'impression et les exports. Cette révision complète la boucle de suivi par les **retours du praticien aux familles**, un **historique complet filtrable et paginé**, des **rapports consultables**, une **validation réelle des fichiers**, leur **immutabilité**, et des **exports reliés et préchargés**. Voir FINALISATION_FONCTIONNELLE.md.

La recette Chrome a révélé un blocage CSRF réel des formulaires authentifiés, absent des essais HTTP synthétiques. La politique Referrer-Policy est corrigée en same-origin. Publication du retour, changement de langue et déconnexion sont contrôlés ensuite dans Chrome. Les origines nulles et externes restent refusées. Les notes professionnelles privées ne sont jamais converties automatiquement en message à la famille.

Le logo original est conservé sur fond clair ; Tajawal est locale ; l'en-tête mobile est compact ; le compteur arabe est isolé ; le démarrage du cabinet est replié lorsque des dossiers existent. Une revue indépendante des captures a guidé ces corrections. Il ne s'agit pas d'une certification d'accessibilité.

## Preuves techniques

| Vérification | Résultat documenté |
|---|---|
| Suite PostgreSQL 17.11 | **102 tests réussis, zéro ignoré**, 164,955 s, code 0 |
| Suite SQLite | **96 réussis, 6 ignorés**, 102 découverts, 97,890 s, code 0 ; les six cas sont réservés à PostgreSQL |
| Concurrence PostgreSQL | Six cas réussis : archive/pratique, retrait/attribution, effacement/pratique, double démarrage, retransmission finale, arrêt/réponse |
| Restauration isolée | 36 tables, comptages identiques, contraintes FK validées ; exports, suivi partagé et refus inter-cabinet vérifiés ; fixture média copiée et hash vérifié |
| Traductions | 609 messages/langue ; 574 clés d'interface ; zéro clé manquante FR/EN/AR |
| Django | check sans anomalie, migrations appliquées, aucune migration manquante |
| JavaScript | Syntaxe des trois scripts contrôlée avec Node |
| HTTP local | 12 contrôles de parcours et CSRF dans les trois langues ; logo original vérifié par SHA-256 |
| Performance locale | Cinq lectures par route : médianes ~11 ms pour les accueils, 57 ms pour le tableau, 22 ms pour l'historique ; serveur local chaud, pas une charge de production |
| Recette Chrome | 18 états publics FR/EN/AR à 320/390/1440 px ; parcours authentifiés et captures précisés dans RECETTE_NAVIGATEUR.md |
| Finition finale | Deux régressions ciblées réussies après les dernières modifications de présentation (7,011 s) ; arrêt du lecteur et bilan revérifiés dans Chrome |

La restauration utilise exclusivement des données fictives dans une base distincte. Ce résultat n'atteste pas une sauvegarde automatisée de production, la restauration de tout un corpus de médias ni un objectif de disponibilité contractuel. Les tests sont des régressions ciblées, pas une preuve de l'absence de toutes les failles.

## Notes fondées sur une grille explicite

Chaque ligne contient **cinq critères de deux points**. Deux points signifient « vérifié dans le périmètre de cette livraison » ; zéro signifie « preuve absente ou condition non remplie ». Aucun demi-point d'impression esthétique. Ces notes évaluent la **complétude des preuves et fonctions du périmètre**, pas l'efficacité clinique ou la valeur intrinsèque universelle. Pas de moyenne globale mélangeant clinique et développement.

| Dimension | Note /10 | Critères vérifiés (2 points chacun) | Critères non établis (0 point) |
|---|---:|---|---|
| Pertinence clinique/pédagogique | 6 | Choix conservé au praticien ; pratique adulte/enfant avec arrêt ; portée et absence de notation de prononciation explicites | Corpus exact approuvé ; bénéfice clinique de Nehedrou démontré |
| Utilité pratique | 8 | Attribution personnalisée ; reprise/arrêt ; échange praticien/famille ; historique/impression/export | Gain de temps et adhésion observés en cabinet |
| Simplicité/accessibilité | 6 | Action familiale principale ; formulaires/labels et erreur focalisable ; adaptation inspectée sur plusieurs largeurs | Recette exhaustive technologies d'assistance ; essais utilisateurs représentatifs |
| Qualité des exercices | 2 | Versions, métadonnées, droits et publication contrôlés | Contrastes approuvés ; audio approuvé ; validation linguistique de chaque variété ; résultats thérapeutiques |
| Personnalisation | 8 | Profil/variété ; objectif/consignes ; rythme/ordre ; ajustement conservant l'historique | Pertinence clinique des adaptations validée sur utilisateurs réels |
| FR/EN/AR et RTL | 8 | Traductions complètes ; changement conservant le contexte ; Tajawal/RTL ; interface distincte de la variété clinique | Relecture native et compréhension terrain |
| Protection/sécurité | 8 | Autorisations par dossier ; CSRF en navigateur ; MFA et récupération testées ; médias immuables/audit/séparation privé-partagé | Exploitation et obligations de chaque marché qualifiées |
| Stabilité technique | 8 | Suite PostgreSQL ; concurrence ; schéma/migrations ; restauration locale isolée | Exploitation de production et incidents éprouvés |
| Performance | 4 | Mesures HTTP locales ; export sans croissance de requêtes selon le nombre de parcours | Charge concurrente production ; appareils/réseaux réels représentatifs ; supervision continue |
| Maintenabilité | 8 | Services séparés ; contrôles serveur partagés ; dépendances avec empreintes ; tests et documentation de lancement | Pipeline CI et suivi opérationnel externe effectivement installés |
| Crédibilité/attractivité commerciale | 6 | Bénéfice lisible ; marque/visuels inspectés ; limites affichées sans faux témoignages | Corpus prêt à vendre ; offre/adoption payante validée |
| Viabilité économique internationale | 2 | Comparaison officielle et scénarios chiffrés transparents | Disposition à payer ; rétention ; coûts complets réels ; offre et marchés qualifiés |

L'absence d'une preuve n'est pas une démonstration d'inefficacité. La validation clinique, la compréhension native et la disposition à payer sont **non évaluées**, pas des résultats négatifs fabriqués. Les 102 tests ne convertissent pas un exercice illustré en traitement validé.

## Recherche, différenciation et offre à tester

RECHERCHE_PRODUIT_2026.md compare six solutions et leurs prix officiels datés, en distinguant logiciel professionnel, application familiale et téléconsultation. RECHERCHE_PRODUIT.md relie les décisions aux sources cliniques et aux limites des études. Une hypothèse de différenciation est le lien cabinet–maison dans un petit cabinet multilingue : prescription précise, retour compréhensible, versions et droits contrôlés, navigateur et support imprimé.

Exemple public gratuit et accès familial inclus ; hypothèses d'offre professionnelle à 15/19/29 EUR par mois **à tester**, sans tarif public inventé ni paiement factice. Les références techniques de 25,15–45,15 USD/mois excluent assistance, édition/validation clinique, juridique, stockage et autres charges. Elles ne constituent ni marge ni seuil de rentabilité. Voir le rapport de recherche pour les sources et scénarios.

## Conditions avant vente

Zéro version clinique approuvée et zéro audio clinique approuvé sont livrés ; 60 candidats restent des brouillons et les exemples restent fictifs. Il faut faire approuver un premier corpus limité avec ses enregistrements adultes et droits, le faire relire par des natifs des variétés réellement annoncées, puis observer son usage avec praticiens/familles.

Un exploitant doit ensuite mettre en place HTTPS, PostgreSQL de production, MFA, SMTP réellement reçu, stockage/sauvegardes et restauration opérationnelle ; fixer support, offre, facturation, politique de conservation, responsabilités et marchés. `check_readiness` reste négatif sur la configuration de démonstration. Aucun achat, témoignage, autorisation réglementaire ou résultat thérapeutique n'est simulé.

Le travail réalisé améliore substantiellement la présentation et la boucle fonctionnelle. Il ne permet pas de promettre une vente internationale immédiate ni une efficacité thérapeutique. La prochaine étape pertinente est une validation d'un périmètre restreint, avec critères de succès mesurables. Voir LANCEMENT.md.
