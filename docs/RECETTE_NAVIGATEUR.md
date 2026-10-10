# Recette navigateur réelle — Nehedrou qualification 6

9 octobre 2026. Chrome local indépendant créé par BrowserAct après l'accord explicite de l'utilisateur ; aucune importation de profil. Données fictives uniquement. Le moteur du navigateur intégré reste indisponible ; cette recette utilise le navigateur indépendant, sans prétendre l'avoir réparé. Aucun MP4 n'a été enregistré.

## Procédure et résultats

La recette suit ouverture, état de page, interaction, relecture de l'état et capture. Les indices d'éléments appartenaient à chaque état ponctuel ; ils ne sont pas des identifiants réutilisables. Les captures sont de vrais rendus Chrome, pas des maquettes. Les largeurs sont imposées au navigateur par son interface DevTools publique, avec vérification de innerWidth. Cela teste une adaptation de mise en page, pas des téléphones physiques.

| Parcours effectivement exercé | Résultat |
|---|---|
| Accueil arabe et chargement des ressources | Logo original lisible sur clair ; Tajawal locale chargée ; images accessibles |
| Exemple public, arrêt immédiat, choix « besoin d'aide », soumission | Synthèse fictive « arrêté », aucune réponse comptée, pas de rapport sauvegardé |
| Langue arabe → français sur accueil | Route française et interface française |
| Connexion praticien française | Tableau accessible dans Chrome |
| Suivi hebdomadaire → programme → publication d'un retour | Défaut CSRF reproduit avant correction ; après correction, soumission enregistrée et retour affiché |
| Programme français → anglais | Même programme conservé, interface anglaise |
| Historique filtré arrêté anglais → arabe | Programme et paramètres kind/status conservés, interface arabe |
| Historique à 320 px | Aucun débordement global ; champs étiquetés, images disponibles |
| Date invalide dans l'historique | Résumé focalisé ; clic sur l'erreur mène au champ id_start visible ; focus clavier visible |
| Tableau praticien à 1024 px | Guide de démarrage replié ; indicateurs et suivi remontés ; inspection de la capture réelle |
| Déconnexion et connexion famille arabe | Uniquement le dossier fictif autorisé ; retour partagé du praticien visible |
| Début du parcours puis lecteur à 390 px | Parcours enregistré, tâche courante ouverte ; aucune image cassée ni champ sans étiquette détecté |
| Arrêt du lecteur dès la découverte | Réponses effacées ; état stopped ; consigne d'échange avec l'enfant masquée ; titre du rapport adapté |
| Choix du retour, enregistrement de l'arrêt | Rapport enregistré, arrêt sans réponse notée, bilan accessible ; publication browser POST passe |

Les messages saisis dans un programme ne sont pas traduits automatiquement. La variété française d'un enfant et les consignes du praticien peuvent rester françaises alors que les boutons sont arabes ; langue d'interface, langue de consignes et variété clinique sont des choix distincts.

## Captures et diagnostics

Les fichiers DIAGNOSTICS_PUBLIC_*.json et les PNG portant FINAL correspondent aux inspections finales. DIAGNOSTIC_HISTORIQUE_320.json, DIAGNOSTIC_TABLETTE.json et DIAGNOSTIC_EXERCICE_390.json documentent dimensions, absence de débordement global, images et étiquettes. Les anciennes captures sans qualification explicite ou indiquées comme intermédiaires ne doivent pas remplacer ces preuves.

Les points de contrôle DOM ne constituent pas un audit WCAG. « Aucun champ sans étiquette » signifie uniquement le contrôle labels/aria des entrées presentes ; il ne prouve pas une lecture parfaite avec toutes les technologies d'assistance. Un menu mobile défilant horizontalement dans sa propre zone n'est pas compté comme débordement de toute la page.

## Limites explicites

Chrome seulement. Pas de Safari/Firefox, téléphone physique, lecteur d'écran, étude utilisateurs ou relecture native. Le zoom navigateur à 200 % n'est pas qualifié ; une largeur simulée n'est pas utilisée comme preuve de zoom. Audio approuvé et qualité phonétique non testables faute de corpus validé. Le lecteur démontre une interaction et une remontée de participation, pas un bénéfice thérapeutique.

Les essais de concurrence et de restauration sont distincts : voir les journaux PostgreSQL et RESTAURATION_POSTGRESQL.json. Le lecteur public ne s'active pas en mode clinique réel. Le navigateur de recette est fermé à la fin ; son profil de recette vierge reste disponible, sans suppression de profils utilisateur.

## Matrice finale des pages publiques

Accueil et exemple interactif ont été ouverts séparément en FR, EN et AR à **320, 390 et 1440 px** : 18 états de page contrôlés dans Chrome. Les fichiers DIAGNOSTICS_PUBLIC_320.json, DIAGNOSTICS_PUBLIC_390.json et DIAGNOSTICS_PUBLIC_1440.json enregistrent la largeur réelle, la langue, le sens de lecture, les étiquettes et les images. Aucun débordement global, image cassée ou champ sans étiquette n'a été détecté dans cette matrice. Le compteur 1 / 3 reste LTR dans les trois interfaces. Ce contrôle ne prétend pas avoir exécuté chaque étape de chaque rôle dans chaque combinaison.

La revue visuelle indépendante des trois accueils à 390 px conclut à une présentation acceptable pour une démonstration publique, sans défaut visuel bloquant visible sur ces captures. Le logo, les langues, le bénéfice et le statut de démonstration sont repérables ; l'accueil arabe nomme l'orthophonie. Les captures finales du bureau arabe à 1440 px et du bilan familial à 390 px ont également été inspectées. Il s'agit d'une appréciation des pixels et du périmètre décrit, sans certification clinique ou d'accessibilité.
