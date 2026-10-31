# Dossier de relecture humaine — arabe standard et darija algérienne

**Version du paquet :** `ar-initial-review-20261101`
**État :** préparation de revue uniquement; aucun contenu approuvé, aucune activité importée dans l’application.

## Périmètre exact

Le paquet rassemble les versions de travail les plus récentes présentes dans les deux fichiers sources verrouillés par SHA-256 dans `manifest.json` :

- **Arabe standard (ar-msa-pilot) : 42 brouillons, version 1**, issus de `docs/arabic-library-v1.json`.
- **Darija algérienne (ar-dz-pilot) : 32 brouillons, version 2**, issus de `docs/arabic-library-v2.json`; chaque v2 est la version courante de sa série et succède à la v1 conservée dans le dépôt.
- **10 propositions MSA** sont étiquetées `phonological_contrast`; **aucune proposition Darija** ne l’est.
- **Aucun audio** n’est attaché aux versions incluses. **20 champs de transcription de travail MSA** sont présents; ils sont reproduits explicitement comme non approuvés.
- Les 92 références d’illustration sont des fichiers SVG existants. Leur présence technique et leur empreinte ne démontrent ni la bonne interprétation de l’image, ni sa familiarité, ni ses droits d’usage.

Ces nombres décrivent le contenu des deux sources au moment de la préparation. Ils ne sont ni des résultats cliniques, ni une approbation linguistique, ni une décision de commercialisation.

## Fichiers du paquet

| Fichier | Utilisation |
|---|---|
| `manifest.json` | Empreintes des sources et feuilles, versions incluses, comptes observés et limites du dossier. |
| `candidates_for_review.csv` | Une ligne par version courante; identifiants de série/version, variété, mots, sens et annotations de travail, images, sources et champs de revue vierges. |
| `recording_queue.csv` | Une ligne par couple unique variété/mot/sens; script parlé exact, transcription, personne modèle adulte, consentement, droits, fichier, empreinte et revues restent à compléter. |
| `image_assets_for_review.csv` | Empreintes, tailles et nombre d’utilisations de chaque SVG cité; les décisions d’interprétation, familiarité et droits restent vierges. |
| `evidence_sources_for_review.csv` | Références reprises des fiches et limites de portée fournies par leurs auteurs; chaque référence et son lien avec l’affirmation doivent être vérifiés. |

Les colonnes contenant `working_copy`, `unapproved` ou `as_supplied_by_source` restituent les propositions telles qu’écrites. Elles ne valent pas transcription correcte, sens convenu, cible pertinente ou preuve établie. Les colonnes de décision sont laissées vides; aucun avis n’est simulé.

## Ordre de revue recommandé

1. **Revue linguistique indépendante.** Attribuer la bonne variété et le registre; préciser la région et la communauté pour chaque relecture Darija. Vérifier le mot, son sens exact, sa vocalisation, les réalisations orales effectivement admises, les synonymes familiaux, les ambiguïtés et les images. Pour MSA, confirmer que la famille et l’enfant utilisent réellement ce registre dans des situations pertinentes. Ne pas substituer MSA à la langue familiale par défaut.
2. **Revue clinique indépendante.** Déterminer si l’activité et sa cible conviennent à un objectif individualisé après l’évaluation de l’orthophoniste. Pour chacune des 10 propositions MSA étiquetées comme contraste, vérifier les formes parlées dans la variété visée, le contraste phonémique, le sens des deux mots et le profil d’erreur auquel une approche de paires minimales pourrait éventuellement s’appliquer. Corriger ou rejeter l’étiquette si un de ces éléments ne tient pas. Une étiquette de catalogue ou une paire orthographique ne suffit pas.
3. **Revue des images et de la familiarité.** Vérifier chaque concept dans le rendu à la taille réellement utilisée, documenter les autres interprétations, puis réunir les preuves de familiarité adaptées au public et à la variété. Une image liée dans le dépôt ne prouve pas que l’enfant reconnaît l’objet sous le nom prévu.
4. **Revue des droits et des médias.** Ne créer un modèle vocal qu’après validation du texte parlé exact. Utiliser un adulte compétent pour la variété et la région retenues. Obtenir et conserver les pièces de permission du locuteur et les droits de chaque enregistrement et illustration. Garder le texte, la source, les dates, les empreintes et les avis sur les mêmes octets.
5. **Décision de version.** Inscrire les codes de relecteur, la date, la justification et les références des pièces dans une copie privée du dossier. Si une fiche change, elle doit recevoir une nouvelle version et être relue de nouveau. Après tout import autorisé dans un environnement de revue contrôlé, relever le fingerprint du CMS et prendre une décision distincte de disponibilité sur cette empreinte exacte.

L’éventuelle observation de la compréhension ou de la dénomination par des enfants est une étape séparée. Elle nécessite d’abord un protocole établi par l’équipe compétente, les autorisations éthiques et de protection des données applicables, une information et un consentement valides, une collecte minimale et une règle de conservation. **Ne pas ajouter de nom, coordonnées, voix ou autre donnée personnelle d’enfant à ces feuilles.**

## Limites scientifiques

Les sources de l’ASHA demandent de tenir compte des systèmes linguistiques réellement utilisés : les différences de langue ou de dialecte peuvent influencer la production et ne sont pas, à elles seules, un trouble. Le tutoriel de Storkel décrit le choix de l’approche contrastive selon le profil; il précise que l’approche conventionnelle des paires minimales convient surtout aux enfants ayant un nombre limité d’erreurs et qu’elle cible le contraste entre la cible et une substitution ou une omission propre au profil. Ces travaux éclairent la sélection professionnelle d’une approche; **ils ne testent pas le contenu, le logiciel ou l’efficacité thérapeutique de Nehedrou**.

- [ASHA — Speech Sound Disorders: Articulation and Phonology](https://www.asha.org/practice-portal/clinical-topics/articulation-and-phonology/)
- [ASHA — Multilingual Service Delivery](https://www.asha.org/practice-portal/professional-issues/multilingual-service-delivery/)
- [Storkel, 2022 — Minimal, Maximal, or Multiple: Which Contrastive Intervention Approach to Use With Children With Speech Sound Disorders?](https://doi.org/10.1044/2021_LSHSS-21-00105)

La catégorie `phonological_contrast` des fiches est une annotation éditoriale à vérifier; elle ne déclare pas une paire minimale reconnue dans chaque variété. Les exemples lexicographiques MSA, les conventions d’écriture Darija et les descriptions dialectologiques répertoriées dans le CSV ont chacune leur portée propre. Une attestation d’un mot n’établit ni sa fréquence chez l’enfant, ni son choix thérapeutique, ni une norme nationale de prononciation.

## Reproduire et vérifier le paquet

À la racine du dépôt :

```powershell
.\.venv\Scripts\python.exe scripts\build_arabic_review_pack.py --check
```

Le contrôle échoue si les sources verrouillées, les images référencées ou les fichiers générés ont changé. Une modification du contenu doit être préparée comme une nouvelle version du paquet, avec de nouvelles empreintes. `--write` régénère les feuilles déterministes; cette commande ne contacte aucune base et n’importe rien dans Nehedrou.

## Ce paquet ne fait pas

Il ne crée ni audio, essai d’enfant, approbation, droits, compte, décision de disponibilité, affectation familiale, ni import dans Neon/Render. Les exemples et fiches restent indisponibles pour un usage thérapeutique tant que les personnes compétentes n’ont pas remis et relié les pièces requises aux versions exactes.
