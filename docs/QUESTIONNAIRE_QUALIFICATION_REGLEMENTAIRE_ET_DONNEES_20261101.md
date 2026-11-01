# Dossier de questions précommercialisation — Nehedrou

**Version de travail : 1 novembre 2026.** Document préparatoire à compléter avec le porteur du projet, l’ANPP et un conseil compétent en données personnelles. Ce n’est ni une demande déjà envoyée, ni un avis juridique, ni une qualification de dispositif médical. Ne pas y joindre de dossier ou d’exemple identifiable d’enfant.

## Objet et réponse attendue

Obtenir une décision écrite ou une orientation officielle pour le marché de départ envisagé, avant vente, importation, mise à disposition clinique ou collecte de données réelles. Les questions ci-dessous séparent la qualification du produit, les formalités applicables et la protection des données. Chaque réponse doit préciser son périmètre, son fondement, les pièces à fournir et l’autorité compétente.

## Fiche factuelle issue du code et de la configuration observés

À confirmer par le porteur avant envoi :

| Élément | Fait observé | À confirmer |
|---|---|---|
| Produit | Application web Django « Nehedrou », interface française, anglaise et arabe; pilote d’arabe algérien/Darija. | Nom légal de l’éditeur, adresse, pays d’établissement, titulaire du produit et marchés visés. |
| Usage présenté | Activités de pratique à domicile accompagnée par un parent; activités/objectif choisis par l’orthophoniste. | Intended purpose exact et formulations approuvées dans chaque langue. |
| Parcours professionnel | Cabinet/professionnel crée un programme pour un profil, choisit variété, objectifs, activités et consignes. | Qui prescrit/valide le programme et quelle relation contractuelle existe avec la famille. |
| Profil enfant | Modèle `care.Child` : code/pseudonyme unique au cabinet, âge (contrainte pilote 4–7 ans), variétés parlées, cabinet et professionnel responsable. Pas de nom/prénom dans ce modèle. | Vérifier autres sources de données, journaux, exports, cookies et compte famille; un pseudonyme n’anonymise pas nécessairement les données reliées. |
| Programme | Titre, objectif, consignes personnalisées, fréquence, dates, jours et durée planifiés; lien vers profil, variété et activités. | Déterminer si ces champs sont considérés comme données de santé ou profilage dans l’usage réel. |
| Compte rendu de pratique | `care.PracticeSession` lie compte utilisateur, activité, cabinet et programme; conserve date, réponse A/B, cible, mode, réponse correcte si applicable, fin/arrêt, appréciation parentale (« facile/aide/difficile »), aides utilisées, raison d’arrêt et commentaire libre jusqu’à 2 000 caractères. | Régler le contenu autorisé des commentaires; définir qui peut consulter/exporter chaque champ. |
| Notes professionnelles | `care.Observation` stocke une observation libre jusqu’à 2 000 caractères; `care.ProgramFeedback` stocke un retour visible par la famille. | Préciser finalités, consignes contre les identifiants superflus, conservation et accès. |
| Audio/image | Le CMS gère des illustrations et de l’audio éditorial (adulte ou synthèse, provenance/droits). Les modèles de pratique consultés ne comportent pas de champ de voix de l’enfant. | Vérifier les flux, journaux, stockage objet et fonctions du navigateur. Ne pas présenter l’absence d’un champ comme une preuve complète d’absence de transfert audio. |
| Calcul clinique | Les choix de jeu peuvent conserver une indication « correcte » uniquement pour le mode appariement; les modes choix libre/observation ne sont pas scorés. Le code indique que l’essai public ne produit pas de score de prononciation. | Confirmer toute décision automatisée ou tout score présent hors des modèles inspectés. |
| Relecture de contenu | Le CMS sépare rédaction, relecture clinique/linguistique et autorisation de publication; les contenus non démonstratifs examinés dans le relevé du 1 novembre 2026 sont des brouillons non approuvés. | Valider le catalogue par variété avant toute mise à disposition réelle. |
| Hébergement candidat | Render web et base Neon observés en région Frankfurt; fichiers média sur stockage externe indiqué par le blueprint, région et garanties contractuelles non vérifiées. Offre gratuite actuelle, sans sauvegarde restaurable confirmée. | Fournisseurs, régions, sous-traitants, accès de support, sauvegardes, logs, transfert international et contrats exacts. |
| Fonctions conformité présentes | Modèle de registre `core.ProcessingActivity`, historique append-only, objet `PrivacyRequest`, flux interne d’accès/effacement et journaux d’audit existent dans le code. | Vérifier remplissage, activation en production, responsables, délais, export, restauration et droits d’accès. Leur présence ne constitue pas une validation juridique. |

## Demande de qualification à l’ANPP — brouillon à compléter

**Objet : Demande d’orientation écrite sur la qualification réglementaire de l’application Nehedrou**

Madame, Monsieur,

Nous préparons la mise à disposition en Algérie de Nehedrou, une application web destinée à organiser une pratique à domicile accompagnée par un parent. Un orthophoniste choisit les objectifs, les activités publiées, la variété parlée et les consignes. Le parent peut déclarer le choix effectué, l’aide apportée, le confort/difficulté ou l’arrêt et transmettre un commentaire. L’application ne réalise pas, dans le parcours de démonstration inspecté, d’analyse automatique de la voix de l’enfant ni de score de prononciation. Les réponses de séance restent toutefois liées au profil et au programme.

Nous sollicitons votre orientation sur les points suivants :

1. Au regard de l’usage décrit, de la définition de l’article 173 de la loi n° 85-05 telle que modifiée et complétée, et des règles en vigueur, Nehedrou relève-t-elle du régime des dispositifs médicaux ou d’un autre régime? Le fait qu’il s’agisse d’une application autonome, sans capteur ni analyse automatique de la voix, modifie-t-il cette qualification?
2. Quelles fonctions ou formulations (notamment « thérapie », « traitement », « rééducation », « amélioration » ou choix de parcours à partir de données de pratique) déterminent l’usage prévu et la qualification?
3. Si une homologation ou autre autorisation s’applique, quelle catégorie et quelle procédure concernent un logiciel de ce type? Qui peut légalement en être fabricant, exploitant ou demandeur en Algérie?
4. Quelles pièces sont attendues concernant sécurité, performance, évaluation clinique, gestion des risques, cycle logiciel, cybersécurité, surveillance après mise sur le marché et gestion des incidents?
5. Les allégations et supports destinés aux familles ou professionnels requièrent-ils une approbation ou un visa préalable? Quelles limites d’information ou de publicité s’appliquent avant une décision d’homologation?
6. Une démonstration sans données réelles d’enfants, une étude d’usage, et une commercialisation sont-elles soumises à des régimes différents? Quelles conditions préalables s’appliquent à chacune?

Nous pouvons transmettre la description fonctionnelle, captures d’écran, architecture, modèles de données et documentation qualité, sans inclure de données personnelles. Merci d’indiquer le service compétent, le formulaire, le fondement juridique et les étapes à suivre.

**À compléter avant envoi :** personne morale/éditeur : [à renseigner]; adresse : [à renseigner]; responsable : [à renseigner]; marché et modèle de distribution envisagés : [à renseigner]; coordonnées : [à renseigner].

## Demande d’avis données personnelles — brouillon à remettre au spécialiste/ANPDP

**Objet : Revue des rôles, données de mineurs et hébergement international — application Nehedrou**

Nous préparons une application pour des exercices à domicile choisis par un orthophoniste. Le code actuel permet de créer un profil d’enfant sous code/pseudonyme (âge 4–7, variétés parlées), un programme (objectif, instructions, calendrier), des retours de séance (réponse, aide, difficulté, motif d’arrêt et commentaire libre), ainsi que des observations professionnelles. Les données sont rattachées à des comptes et à un cabinet. Une base Neon et le service web Render sont configurés en région Frankfurt; l’emplacement du stockage des fichiers et les flux secondaires restent à inventorier. Aucun usage sur des profils réels n’est autorisé à ce stade.

Nous demandons un avis écrit portant sur :

- l’identité de chaque responsable du traitement, sous-traitant ou éventuel responsable conjoint (éditeur, cabinet, orthophoniste, hébergeurs et autres prestataires);
- le fondement applicable aux données concernant un enfant et aux informations susceptibles de révéler sa santé, ainsi que le consentement, l’information et les droits du représentant légal;
- les formalités/déclarations/autorisations requises auprès de l’ANPDP et l’application des obligations de délégué, registre et journal prévues par la loi n° 18-07 telle que modifiée par la loi n° 25-11;
- la légalité et les garanties requises pour les transferts vers Frankfurt et les éventuelles destinations de sauvegarde, support, télémétrie ou stockage objet;
- les contrats de sous-traitance, durées, effacement et propagation aux sauvegardes, export/accès/rectification/opposition, contrôle des comptes, journalisation, notification de violation et analyse d’impact éventuelle;
- les limites de données nécessaires : pseudonyme plutôt que nom, restriction des commentaires libres, durée la plus courte justifiée, désactivation des données réelles avant validation.

**À compléter avant avis :** entité exploitante : [à renseigner]; responsable proposé : [à renseigner]; contact DPO : [à renseigner]; fournisseurs/régions et sous-traitants : [à renseigner]; besoins de conservation : [à justifier]; marchés concernés : [à renseigner].

## Questions de décision interne à fermer avant usage réel

- [ ] Le marché de lancement est déterminé et un avis écrit porte sur son régime applicable.
- [ ] L’intended purpose, les claims autorisés et les formulations FR/EN/AR/Darija sont approuvés pour ce marché.
- [ ] Les rôles de responsable/sous-traitant sont contractualisés; le registre de traitement est exact et revu.
- [ ] Les bases juridiques, l’information des titulaires de l’autorité parentale et les droits sont validés.
- [ ] Le transfert international est autorisé et documenté, ou l’architecture est remplacée par une solution légalement et contractuellement validée.
- [ ] Chaque sous-traitant, région, stockage média, journal, sauvegarde et accès support est inventorié et contracté.
- [ ] Les durées sont implémentées pour enregistrements, exports, sauvegardes et journaux; l’effacement et la restauration sont testés.
- [ ] Le produit n’est pas ouvert à des familles ou cabinets réels avant clôture des points ci-dessus.

## Références primaires consultées le 1 novembre 2026

- [Journal officiel algérien, loi n° 08-13 du 20 juillet 2008, définition à l’article 173 de la loi n° 85-05](https://www.joradp.dz/FTP/jo-francais/2008/F2008044.PDF).
- [ANPP, mission d’homologation des dispositifs médicaux](https://anpp.dz/fr/).
- [Journal officiel algérien, loi n° 18-07 du 10 juin 2018](https://www.joradp.dz/FTP/JO-FRANCAIS/2018/F2018034.pdf).
- [Journal officiel algérien, loi n° 25-11 du 24 juillet 2025 modifiant la loi n° 18-07](https://www.joradp.dz/FTP/jo-francais/2025/F2025048.pdf).
- [Règlement européen (UE) 2017/745](https://eur-lex.europa.eu/eli/reg/2017/745/oj/eng) et [guidance MDCG 2019-11 rev.1 (juin 2025)](https://health.ec.europa.eu/system/files/2025-06/mdcg_2019_11_en.pdf).
