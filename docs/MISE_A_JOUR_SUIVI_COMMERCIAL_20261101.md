# Mise à jour de suivi — 1 novembre 2026 (branche PR #30)

## État du dernier correctif

Le commit `fdf04f1a2ec26d016d4d4e41d2617fabac486307` est poussé sur `codex/browser-qa-report-20261101` et la PR #30 reste ouverte. Il étend le blocage en mode non-démo aux créations et modifications de dossiers, programmes, séances et suivis, et empêche l'acceptation d'une invitation avant présentation et accusé de lecture de la notice courante. La voie démo conserve son parcours existant. Les demandes de suppression et les arrêts de sécurité restent accessibles. Tests locaux ciblés : 123 réussis, 4 ignorés.

La CI GitHub run 142 est en cours au moment de cette mise à jour. La suite de tests a commencé; build Docker et smoke test sont encore en attente. Ne pas présenter ce commit comme validé par CI avant résultat final. Il n'est pas fusionné et n'est pas déployé sur Render. La version publique reste une démonstration et n'est pas autorisée à traiter des données réelles.

## Relecture clinique et linguistique à organiser

Le porteur indique pouvoir mobiliser un orthophoniste et des locuteurs compétents pour les variétés visées, notamment la Darija régionale. Cette disponibilité permet d'organiser une revue humaine; elle ne vaut pas validation tant que les personnes, leurs compétences, la variété/région et les décisions par version ne sont pas consignées.

Ordre de travail recommandé :

1. Confirmer les personnes et domaines de compétence par langue, variété et région, et nommer un orthophoniste responsable de la revue clinique.
2. Exporter depuis le CMS les versions exactes à réviser; ne pas réutiliser le paquet statique si son empreinte ne correspond pas aux versions du catalogue.
3. Pour chaque activité, consigner la forme locale, sens, familiarité, contraste réellement visé, public/profil, étapes, aides, limites, illustration, texte audio et décision de chaque relecteur. Un contraste ou une paire minimale ne doit rester revendiqué que si les formes orales de la variété ciblée établissent effectivement ce contraste et si l'orthophoniste juge le choix adapté au profil.
4. Enregistrer l'audio seulement après approbation du texte oral, avec un locuteur adulte autorisé et une preuve documentée de consentement, licence et droits de réutilisation. Une synthèse vocale ne remplace pas la revue de prononciation.
5. Exiger des avis indépendants de langue et clinique, résoudre leurs désaccords, puis faire approuver la version par les rôles prévus du CMS. Laisser explicitement en brouillon tout élément non tranché.
6. Tenir un registre des décisions, date, identité/compétence des relecteurs, empreinte de version et limites d'usage; aucune revue de méthode ne doit être présentée comme preuve d'efficacité clinique de l'application.

Le catalogue non-démo recensé dans la note principale reste entièrement en brouillon; les fiches Darija ne sont pas présumées minimales. Cette étape exige l'intervention effective des relecteurs; aucun contenu n'est approuvé par la présente note.

## Point documentaire réglementaire confirmé

La loi algérienne n° 25-11 du 24 juillet 2025 modifie la loi n° 18-07. Le texte officiel ajoute notamment, aux articles 41 bis et 41 bis 1, la désignation et les missions d'un délégué à la protection des données pour le responsable du traitement et l'autorité compétente; les articles 41 bis 2 et 41 bis 3 prévoient un registre d'activités chez le responsable et le sous-traitant, ainsi qu'un carnet automatisé des opérations indiquant motifs, date/heure et, dans la mesure du possible, les identités concernées. Ces dispositions doivent être analysées et mises en œuvre par les acteurs responsables avec un conseil local; la simple présence dans le code d'un modèle de registre ou d'un journal n'établit ni son exhaustivité ni la conformité du service.

Pour un marché européen, le guide MDCG 2019-11 révision 1 (juin 2025) indique que la qualification d'un logiciel comme logiciel de dispositif médical dépend de son usage prévu et ne dépend pas du fait qu'il tourne sur mobile, cloud ou autre plateforme. Les mentions marketing et instructions font partie des éléments qui expriment l'usage prévu. Cela confirme la nécessité d'une qualification formelle par marché avant les allégations et la vente, sans conclure ici au statut de Nehedrou.

Sources primaires : [Journal officiel algérien, loi n° 25-11 (2025), articles 41 bis à 41 bis 3](https://www.joradp.dz/FTP/jo-francais/2025/F2025048.pdf); [Commission européenne, MDCG 2019-11 rev.1, juin 2025](https://health.ec.europa.eu/system/files/2025-06/mdcg_2019_11_en.pdf).
